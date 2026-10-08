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
