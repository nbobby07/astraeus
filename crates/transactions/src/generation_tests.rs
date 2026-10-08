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
