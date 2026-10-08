use distro_transactions::{
    pacman::{require_root, NativeRunner, Pacman, SystemBoot, SystemHealth},
    *,
};
use std::{fmt::Write, fs, path::Path};

pub fn format_plan(plan: &ExecutionPlan) -> String {
    let mut text = String::from("Transaction plan (existing repository databases)\n");
    for change in &plan.packages.changes {
        match change {
            PackageChange::Install { name, version } => {
                writeln!(text, "  Install  {name} {version}")
            }
            PackageChange::Upgrade { name, from, to } => {
                writeln!(text, "  Upgrade  {name} {from} -> {to}")
            }
            PackageChange::Remove { name, version } => {
                writeln!(text, "  Remove   {name} {version}")
            }
        }
        .unwrap();
    }
    if plan.packages.changes.is_empty() {
        text.push_str("  No package changes\n");
    }
    writeln!(text, "Boot artifacts: UKI regeneration {}, bootloader update {}\nSnapshot: {}\nDownload: {} bytes (upper bound)\nInstalled delta: {}",
        required(plan.boot.regenerate_uki), required(plan.boot.update_bootloader), required(plan.snapshot_required),
        plan.packages.download_bytes, plan.packages.installed_delta_bytes.map(|n| format!("{n:+} bytes")).unwrap_or_else(|| "unavailable".into())).unwrap();
    text
}

fn required(value: bool) -> &'static str {
    if value {
        "required"
    } else {
        "not required"
    }
}

/// Shared by the actual CLI and fixture tests; the dry-run path has no history writer.
pub fn dry_run(backend: &mut impl PackageBackend, json: bool) -> Result<String> {
    let plan = backend.resolve()?;
    plan.validate()?;
    if json {
        serde_json::to_string_pretty(&plan).map_err(|e| e.to_string())
    } else {
        Ok(format!(
            "{}No changes have been made.\n",
            format_plan(&plan)
        ))
    }
}

pub fn history(path: &Path, json: bool) -> Result<String> {
    let records = read_history(path)?;
    if json {
        return serde_json::to_string_pretty(&records).map_err(|e| e.to_string());
    }
    let mut text = String::from("ID    UNIX TIME (UTC)    STATE                 CHANGE\n");
    for record in records {
        let state = serde_json::to_value(record.state).map_err(|e| e.to_string())?;
        writeln!(
            text,
            "{:<5} {:<18} {:<21} system update ({} packages)",
            record.id,
            record.timestamp,
            state.as_str().unwrap(),
            record.plan.packages.changes.len()
        )
        .unwrap();
        if let Some(failure) = record.failure {
            writeln!(text, "      {:?}: {}", failure.at, failure.message).unwrap();
        }
    }
    Ok(text)
}

fn session() -> Result<UpdateSession> {
    require_root()?;
    fs::create_dir_all(Path::new(HISTORY_PATH).parent().unwrap()).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(
            Path::new(HISTORY_PATH).parent().unwrap(),
            fs::Permissions::from_mode(0o755),
        )
        .map_err(|e| e.to_string())?;
    }
    UpdateSession::open_published(
        Path::new(PRIVATE_HISTORY_PATH),
        Path::new(LOCK_PATH),
        Path::new(HISTORY_PATH),
    )
}

pub fn update() -> Result<()> {
    let mut session = session()?;
    session.ensure_ready()?;
    let mut snapshots = integration::BtrfsSnapshots::new(distro_snapshots::Manager::online(
        distro_snapshots::Native,
    ))?;
    let mut packages = Pacman::default();
    let plan = packages.resolve()?;
    print!("{}", format_plan(&plan));
    let project = distro_config::parse_toml(distro_config::BUNDLED).map_err(|e| e.to_string())?;
    project.validate()?;
    let record = execute(
        &mut session,
        plan,
        &mut packages,
        &mut snapshots,
        &mut SystemBoot {
            runner: NativeRunner,
        },
        &mut SystemHealth {
            runner: NativeRunner,
            uki_path: format!("/efi/EFI/Linux/{}-linux.efi", project.identity.id),
        },
        || false,
    )?;
    println!("Transaction {}: {:?}", record.id, record.state);
    match record.outcome {
        TransactionOutcome::Succeeded => Ok(()),
        TransactionOutcome::AwaitingBoot => {
            println!("Live checks passed; boot confirmation is still required.");
            Ok(())
        }
        _ => Err(record
            .failure
            .map(|f| f.message)
            .unwrap_or_else(|| "transaction did not complete".into())),
    }
}

pub fn confirm_boot(id: Option<i64>, mut rollback: bool) -> Result<()> {
    let mut session = session()?;
    session.recover_interrupted()?;
    let manager = distro_snapshots::Manager::online(distro_snapshots::Native);
    if let Some(generation) = manager.selected_generation().map_err(|e| e.to_string())? {
        if generation.root_kind == distro_snapshots::generations::RootKind::Retained {
            let _guard = manager.lock().map_err(|e| e.to_string())?;
            manager
                .verify_generation(&generation.id)
                .map_err(|e| e.to_string())?;
            manager
                .verify_running_generation(&generation)
                .map_err(|e| e.to_string())?;
            let snapshot = manager
                .inspect(&generation.snapshot)
                .map_err(|e| e.to_string())?;
            let record = integration::record_fallback(
                &mut session,
                &generation,
                &snapshot,
                integration::boot_id()?,
            )?;
            println!(
                "{}",
                serde_json::to_string_pretty(&record).map_err(|e| e.to_string())?
            );
            return Err("Previous known-good recovery root is running. No transaction was blessed or rolled back; use deliberate offline recovery.".into());
        }
    }
    let id = match id {
        Some(id) => id,
        None => {
            let pending: Vec<_> = session
                .records()?
                .into_iter()
                .filter(|r| r.state == TransactionState::AwaitingBoot)
                .collect();
            if pending.is_empty() {
                return Ok(());
            }
            if pending.len() != 1 {
                return Err("ambiguous pending boot transactions".into());
            }
            // An offline restore may precede this boot. The full confirmation
            // still requires the restored root parent and saved UKI to match.
            rollback = Pacman::default().current_state()? == pending[0].plan.current;
            pending[0].id
        }
    };
    let mut snapshots = integration::BtrfsSnapshots::new(distro_snapshots::Manager::online(
        distro_snapshots::Native,
    ))?;
    let record = integration::confirm(&mut session, id, rollback, &mut snapshots)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&record).map_err(|e| e.to_string())?
    );
    Ok(())
}

pub fn boot(action: &str, id: Option<&str>, json: bool) -> Result<()> {
    use distro_snapshots::{
        generations::{GenerationId, Selection},
        Manager, Native,
    };
    let manager = Manager::online(Native);
    let err = |e: Box<dyn std::error::Error + Send + Sync>| e.to_string();
    if action == "enable" {
        require_root()?;
        manager.enable_generations().map_err(err)?;
        println!("Boot generations enabled for the next update.");
        return Ok(());
    }
    let parsed = id.map(GenerationId::parse).transpose().map_err(err)?;
    if action == "set-default" {
        let session = session()?;
        let records = session.records()?;
        let guard = manager.lock().map_err(err)?;
        let id = parsed.as_ref().ok_or("missing generation ID")?;
        let generation = manager.verify_generation(id).map_err(err)?;
        let snapshot = manager.inspect(&generation.snapshot).map_err(err)?;
        integration::validate_generation_reference(&records, &generation, &snapshot)?;
        let selected = manager
            .generation_selection()
            .map_err(err)?
            .ok_or("no active generations")?;
        if *id != selected.previous && Some(id) != selected.current.as_ref() {
            return Err("only the current pair can be selected".into());
        }
        let previous = manager.verify_generation(&selected.previous).map_err(err)?;
        let snapshot = manager.inspect(&previous.snapshot).map_err(err)?;
        integration::validate_generation_reference(&records, &previous, &snapshot)?;
        manager
            .select_generation_locked(
                &guard,
                Selection {
                    schema_version: 1,
                    current: (id != &selected.previous).then(|| id.clone()),
                    previous: selected.previous,
                },
            )
            .map_err(err)?;
        println!(
            "Selected {} for the next boot. No root was restored.",
            id.as_str()
        );
        return Ok(());
    }
    let records = if action == "verify" {
        require_root()?;
        distro_transactions::read_recovery_history(Path::new(HISTORY_PATH))?
    } else {
        read_history(Path::new(HISTORY_PATH))?
    };
    let selection = manager.generation_selection().map_err(err)?;
    let pending = manager.generation_pending().map_err(err)?;
    let mut items = vec![];
    for generation in manager.generations().map_err(err)? {
        if parsed.as_ref().is_some_and(|id| *id != generation.id) {
            continue;
        }
        let snapshot = manager.inspect(&generation.snapshot).map_err(err)?;
        let eligibility =
            integration::validate_generation_reference(&records, &generation, &snapshot);
        if action == "verify" {
            require_root()?;
            eligibility.as_ref().map_err(Clone::clone)?;
            manager.verify_generation(&generation.id).map_err(err)?;
        }
        let counter = manager.generation_counter(&generation.id).map_err(err);
        let assessment = if pending {
            "unknown: unfinished operation"
        } else if eligibility.is_err() {
            "unknown: ineligible transaction reference"
        } else if matches!(
            counter,
            Ok(Some((
                _,
                distro_snapshots::generations::BootCount::Counted { left: 0, .. }
            )))
        ) {
            "attempt budget exhausted"
        } else {
            match snapshot.health {
                distro_snapshots::Health::Unknown => "unknown",
                distro_snapshots::Health::Bad => "unhealthy",
                distro_snapshots::Health::Candidate => "awaiting confirmation",
                distro_snapshots::Health::KnownGood => "known-good evidence",
            }
        };
        let record = snapshot
            .transaction_id
            .as_deref()
            .and_then(|s| s.parse::<i64>().ok())
            .and_then(|id| records.iter().find(|r| r.id == id));
        let role = if selection
            .as_ref()
            .is_some_and(|s| s.current.as_ref() == Some(&generation.id))
        {
            "current"
        } else if selection
            .as_ref()
            .is_some_and(|s| s.previous == generation.id)
        {
            "previous-known-good-recovery"
        } else {
            "inactive"
        };
        items.push(serde_json::json!({"generation":generation,"role":role,"transaction_id":snapshot.transaction_id,
            "health":snapshot.health,"confirmation":record.and_then(|r| r.confirmation.as_ref()),
            "boot_attempts":record.map(|r| &r.boot_attempts),"boot_counter":counter.as_ref().ok(),
            "counter_error":counter.err(),"reference_eligible":eligibility.is_ok(),"ineligible_reason":eligibility.err(),
            "assessment":assessment,"artifact_verified_now":action == "verify", "recovery_method":"retained-root boot; offline restoration is separate"}));
    }
    if parsed.is_some() && items.is_empty() {
        return Err("generation does not exist".into());
    }
    let value = serde_json::json!({"schema_version":1,"enabled":manager.generations_enabled().map_err(err)?,"pending":pending,"selection":selection,"generations":items});
    if json {
        println!(
            "{}",
            serde_json::to_string_pretty(&value).map_err(|e| e.to_string())?
        );
    } else {
        println!(
            "Boot generations: enabled={}, unfinished operation={pending}",
            value["enabled"]
        );
        for item in items {
            println!(
                "{}: {}, {}, reference eligible={}{}",
                item["generation"]["id"].as_str().unwrap_or("?"),
                item["role"].as_str().unwrap_or("?"),
                item["assessment"].as_str().unwrap_or("unknown"),
                item["reference_eligible"],
                if action == "verify" {
                    ", artifact/root/trust verified"
                } else {
                    ", artifact/root/trust not checked"
                }
            );
        }
        println!("Recovery: use trusted live media for offline restoration. Firmware Settings is supplied by systemd-boot.");
    }
    Ok(())
}
