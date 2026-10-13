use super::*;
use distro_snapshots::{generations::*, Snapshot, Subvolume, UKI};

fn bindings() -> (Generation, Snapshot) {
    let snapshot: Snapshot = serde_json::from_value(serde_json::json!({
        "schema_version":1,"id":"1","created_unix_seconds":1,
        "filesystem_uuid":"11111111-1111-1111-1111-111111111111",
        "source_state":{"id":256,"uuid":"22222222-2222-2222-2222-222222222222","parent_uuid":null,"top_level":5,"read_only":false},
        "root":{"id":1000,"uuid":"33333333-3333-3333-3333-333333333333","parent_uuid":"22222222-2222-2222-2222-222222222222","top_level":258,"read_only":true},
        "reason":"pre-update","transaction_id":"1","health":"known-good","validation_evidence":"fixture verified boot",
        "boot":{"esp_uuid":"1234-ABCD","sha256":"a".repeat(64),"relative_path":UKI}
    })).unwrap();
    let generation = Generation {
        schema_version: 1,
        id: GenerationId::parse("1").unwrap(),
        snapshot: snapshot.id.clone(),
        root: Subvolume {
            id: 1001,
            uuid: "44444444-4444-4444-4444-444444444444".into(),
            parent_uuid: Some(snapshot.root.uuid.clone()),
            top_level: 258,
            read_only: false,
        },
        root_kind: RootKind::Retained,
        filesystem_uuid: snapshot.filesystem_uuid.clone(),
        esp_uuid: snapshot.boot.esp_uuid.clone(),
        uki_sha256: "b".repeat(64),
        embedded_cmdline: format!(
            "root=UUID={} rootflags=subvolid=1001 rw",
            snapshot.filesystem_uuid
        ),
        prior_known_good: None,
    };
    (generation, snapshot)
}

#[test]
fn generation_references_reject_missing_stale_wrong_and_unhealthy_records() {
    let (generation, mut snapshot) = bindings();
    let mut record = TransactionRecord::new(plan());
    record.id = 1;
    record.snapshot = Some("1".into());
    record.state = TransactionState::AwaitingBoot;
    integration::validate_generation_reference(&[record.clone()], &generation, &snapshot).unwrap();
    assert!(integration::validate_generation_reference(&[], &generation, &snapshot).is_err());
    let mut later = TransactionRecord::new(plan());
    later.id = 2;
    assert!(integration::validate_generation_reference(
        &[record.clone(), later],
        &generation,
        &snapshot
    )
    .unwrap_err()
    .contains("stale"));
    record.snapshot = Some("999".into());
    assert!(
        integration::validate_generation_reference(&[record.clone()], &generation, &snapshot)
            .is_err()
    );
    record.snapshot = Some("1".into());
    snapshot.health = distro_snapshots::Health::Bad;
    assert!(
        integration::validate_generation_reference(&[record.clone()], &generation, &snapshot)
            .is_err()
    );
    snapshot.health = distro_snapshots::Health::KnownGood;
    record.state = TransactionState::RolledBack;
    assert!(integration::validate_generation_reference(&[record], &generation, &snapshot).is_err());
}

#[test]
fn fallback_evidence_is_idempotent_and_does_not_claim_restoration_or_success() {
    let (generation, snapshot) = bindings();
    let temp = Temp::new();
    let mut session = temp.session();
    let mut record = TransactionRecord::new(plan());
    record.state = TransactionState::AwaitingBoot;
    record.outcome = TransactionOutcome::AwaitingBoot;
    record.snapshot = Some("1".into());
    session.insert(&mut record).unwrap();
    let first =
        integration::record_fallback(&mut session, &generation, &snapshot, "recovery-boot".into())
            .unwrap();
    assert_eq!(first.state, TransactionState::AwaitingBoot);
    assert!(first.confirmation.is_none());
    assert_eq!(first.boot_attempts.len(), 1);
    assert!(first.boot_attempts[0]
        .error
        .as_ref()
        .unwrap()
        .contains("offline restoration"));
    assert_eq!(
        first,
        integration::record_fallback(&mut session, &generation, &snapshot, "recovery-boot".into())
            .unwrap()
    );
    assert!(session.ensure_ready().is_err());
}

#[test]
fn activation_failure_keeps_both_snapshots_and_requires_recovery() {
    let temp = Temp::new();
    let mut session = temp.session();
    let record = execute(
        &mut session,
        plan(),
        &mut Packages::new(""),
        &mut Snapshots {
            fail_activate: true,
            activation_history: Some(temp.0.join("history.sqlite")),
            ..Default::default()
        },
        &mut Boot(false),
        &mut Health(HealthStatus::Pass),
        || false,
    )
    .unwrap();
    assert_eq!(record.state, TransactionState::RollbackRequired);
    assert!(record.snapshot.is_some() && record.post_snapshot.is_some());
    assert!(record.confirmation.is_none());
    assert!(record.failure.unwrap().message.contains("activation"));
}

#[test]
fn baseline_publication_failure_has_durable_recovery_reference_before_packages() {
    let temp = Temp::new();
    let mut session = temp.session();
    let mut packages = Packages::new("");
    let record = execute(
        &mut session,
        plan(),
        &mut packages,
        &mut Snapshots {
            fail_baseline: true,
            ..Default::default()
        },
        &mut Boot(false),
        &mut Health(HealthStatus::Pass),
        || false,
    )
    .unwrap();
    assert_eq!(record.state, TransactionState::RollbackRequired);
    assert!(record.snapshot.is_some());
    assert!(record.post_snapshot.is_none());
    assert_eq!(
        record.failure.as_ref().unwrap().at,
        TransactionState::Applying
    );
    assert!(!packages.calls.contains(&"apply"));
    assert_eq!(session.records().unwrap()[0], record);
}

fn metadata_plan() -> ExecutionPlan {
    let current = CurrentSystemState::new(BTreeMap::from([("fixture".into(), "1-1".into())]));
    let before = ManagementState {
        packages: [(
            "fixture".into(),
            ManagedPackage {
                version: "1-1".into(),
                reason: InstallReason::Dependency,
                owners: Default::default(),
            },
        )]
        .into(),
        ..Default::default()
    };
    let mut after = before.clone();
    after.applied.packages.insert("fixture".into());
    let owners = after.applied.request_owners().unwrap();
    let package = after.packages.get_mut("fixture").unwrap();
    package.owners = owners["fixture"].clone();
    package.reason = InstallReason::Explicit;
    let management = ManagementPlan {
        before_digest: before.digest(),
        before: Some(before),
        after_digest: after.digest(),
        after,
        reasons_before: [("fixture".into(), InstallReason::Dependency)].into(),
        reasons_after: [("fixture".into(), InstallReason::Explicit)].into(),
        removal_integrity: None,
    };
    ExecutionPlan::new(
        current,
        PackagePlan {
            changes: vec![],
            targets: vec![],
            download_bytes: 0,
            installed_delta_bytes: Some(0),
        },
    )
    .with_management(management)
}

#[test]
fn metadata_only_confirmation_requires_boot_identity_ownership_and_full_reason_map() {
    use integration::{confirm, verify_management_state, BootEvidence};
    struct Evidence {
        plan: ExecutionPlan,
        state: Option<ManagementState>,
        reasons: BTreeMap<String, InstallReason>,
        wrong_identity: bool,
        promoted: usize,
    }
    impl BootEvidence for Evidence {
        fn boot_id(&mut self) -> Result<String> {
            Ok("boot-after".into())
        }
        fn verify(&mut self, _: &str, _: i64, _: bool) -> Result<()> {
            if self.wrong_identity {
                Err("wrong root or UKI transaction marker".into())
            } else {
                Ok(())
            }
        }
        fn current_state(&mut self) -> Result<CurrentSystemState> {
            Ok(self.plan.current.clone())
        }
        fn verify_management(&mut self, plan: &ExecutionPlan, rollback: bool) -> Result<()> {
            verify_management_state(plan, rollback, &self.state, &self.reasons)
        }
        fn health(&mut self, plan: &ExecutionPlan) -> Vec<HealthCheckResult> {
            Health(HealthStatus::Pass).run(plan)
        }
        fn promote(&mut self, _: &str, _: &str) -> Result<()> {
            self.promoted += 1;
            Ok(())
        }
    }
    let plan = metadata_plan();
    plan.validate().unwrap();
    assert_eq!(plan.current, plan.expected_state());
    let change = plan.management.as_ref().unwrap().clone();
    let temp = Temp::new();
    let mut session = temp.session();
    let mut record = TransactionRecord::new(plan.clone());
    record.state = TransactionState::AwaitingBoot;
    record.outcome = TransactionOutcome::AwaitingBoot;
    record.snapshot = Some("1".into());
    record.post_snapshot = Some("2".into());
    record.update_boot_id = Some("boot-before".into());
    session.insert(&mut record).unwrap();
    let mut evidence = Evidence {
        plan,
        state: change.before.clone(),
        reasons: change.reasons_before.clone(),
        wrong_identity: false,
        promoted: 0,
    };
    assert!(confirm(&mut session, record.id, false, &mut evidence)
        .unwrap_err()
        .contains("ownership"));
    evidence.state = Some(change.after.clone());
    assert!(confirm(&mut session, record.id, false, &mut evidence).is_err());
    evidence.reasons = change.reasons_after.clone();
    evidence
        .reasons
        .insert("unexpected-package".into(), InstallReason::Dependency);
    assert!(confirm(&mut session, record.id, false, &mut evidence).is_err());
    evidence.reasons = change.reasons_after.clone();
    evidence.wrong_identity = true;
    assert!(confirm(&mut session, record.id, false, &mut evidence)
        .unwrap_err()
        .contains("marker"));
    assert_eq!(evidence.promoted, 0);
    evidence.wrong_identity = false;
    assert_eq!(
        confirm(&mut session, record.id, false, &mut evidence)
            .unwrap()
            .state,
        TransactionState::Succeeded
    );
    assert_eq!(evidence.promoted, 1);
    assert!(confirm(&mut session, record.id, true, &mut evidence).is_err());
    evidence.state = change.before;
    evidence.reasons = change.reasons_before;
    assert_eq!(
        confirm(&mut session, record.id, true, &mut evidence)
            .unwrap()
            .state,
        TransactionState::RolledBack
    );
    assert_eq!(evidence.promoted, 1);
}

#[test]
fn later_metadata_mutation_makes_previous_generation_and_rollback_stale() {
    let (generation, snapshot) = bindings();
    let mut old = TransactionRecord::new(plan());
    old.id = 1;
    old.snapshot = Some("1".into());
    old.state = TransactionState::Succeeded;
    let mut later = TransactionRecord::new(metadata_plan());
    later.id = 2;
    later.state = TransactionState::Failed;
    assert!(later.plan.packages.changes.is_empty());
    assert!(later.plan.has_mutation());
    let records = [old, later];
    assert!(
        integration::validate_generation_reference(&records, &generation, &snapshot)
            .unwrap_err()
            .contains("stale")
    );
    assert!(
        integration::validate_rollback_target(&records, Some("1"), "1")
            .unwrap_err()
            .contains("stale")
    );
}

#[test]
fn installed_image_seed_is_accepted_by_the_actual_rust_management_reader() {
    let temp = Temp::new();
    let script = r#"
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import installer, bootstrap
root = Path(sys.argv[2])
def package(name, reason):
    bootstrap.write(root / 'var/lib/pacman/local' / name / 'desc',
        f'%NAME%\n{name}\n\n%VERSION%\n1-1\n\n%REASON%\n{reason}\n')
package('mesa', '0')
package('gamemode', '1')
before = installer.installed_state(root)
for name in set(installer.gaming_packages(['tools', 'mangohud'])) - before.keys():
    package(name, '0')
package('tool-library', '1')
def resolution(root, packages):
    return {'extra':'sha256:' + 'a'*64}, {name:{'version':p['version'], 'repository':'extra', 'sha256':'b'*64} for name,p in packages.items()}
installer.locked_packages = resolution
installer.seed_management(root, before, ['software'], ['tools','mangohud'], bootstrap.write, 'fixture config\n')
"#;
    let scripts = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../scripts");
    let output = std::process::Command::new(if cfg!(windows) { "python" } else { "python3" })
        .arg("-c")
        .arg(script)
        .arg(scripts)
        .arg(&temp.0)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let state = management_store::read_state(&temp.0).unwrap().unwrap();
    assert!(state.protected.contains("gamemode"));
    assert!(!state.packages.contains_key("gamemode"));
    assert_eq!(
        state.packages["mangohud"].owners,
        ["gaming:mangohud".into(), "gaming:tools".into()].into()
    );
    assert_eq!(
        state.packages["tool-library"].reason,
        InstallReason::Dependency
    );
    assert_eq!(state.resolution["tool-library"].sha256, "b".repeat(64));
    let current = CurrentSystemState::new(
        state
            .resolution
            .iter()
            .map(|(name, package)| (name.clone(), package.version.clone()))
            .collect(),
    );
    let reasons = management_store::read_reasons(&temp.0).unwrap();
    let reconciled = management::reconcile(
        Some(&state),
        &current,
        &reasons,
        &current,
        &reasons,
        &state.applied,
        &state.protected,
        &state.repositories,
    )
    .unwrap();
    assert!(
        !reconciled.has_mutation(),
        "unchanged installed-image receipt must reconcile to a no-op"
    );
}

#[test]
fn recorded_provider_validation_rejects_invalid_names_and_missing_packages() {
    for (dependency, provider) in [("virtual", "absent"), ("virtual>=2", "fixture")] {
        let mut plan = metadata_plan();
        let change = plan.management.as_mut().unwrap();
        change
            .after
            .resolved_providers
            .insert(dependency.into(), provider.into());
        change.after_digest = change.after.digest();
        assert!(plan.validate().is_err());
    }
}

#[test]
fn removal_integrity_is_validated_and_bound_to_the_reviewed_plan() {
    let mut plan = metadata_plan();
    let prior = plan.fingerprint();
    plan.management.as_mut().unwrap().removal_integrity =
        Some(format!("sha256:{}", "a".repeat(64)));
    assert_ne!(prior, plan.fingerprint());
    assert!(plan.validate().is_ok());
    plan.management.as_mut().unwrap().removal_integrity = Some("sha256:unverified".into());
    assert!(plan.validate().is_err());
}
