use super::*;
#[path = "generation_tests.rs"]
mod generation_tests;
use crate::pacman::*;
use std::{
    cell::Cell,
    collections::BTreeMap,
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "astraeus-transactions-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn session(&self) -> UpdateSession {
        UpdateSession::open(&self.0.join("history.sqlite"), &self.0.join("update.lock")).unwrap()
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn plan() -> ExecutionPlan {
    ExecutionPlan::new(
        CurrentSystemState::new(BTreeMap::from([("linux".into(), "1-1".into())])),
        PackagePlan {
            changes: vec![PackageChange::Upgrade {
                name: "linux".into(),
                from: "1-1".into(),
                to: "2-1".into(),
            }],
            targets: vec![PackageTarget {
                name: "linux".into(),
                version: "2-1".into(),
                repository: "core".into(),
                archive_bytes: 10,
                installed_bytes: 30,
                sha256: "a".repeat(64),
            }],
            download_bytes: 10,
            installed_delta_bytes: Some(20),
        },
    )
}

struct Packages {
    fail: &'static str,
    calls: Vec<&'static str>,
    plan: ExecutionPlan,
}
impl Packages {
    fn new(fail: &'static str) -> Self {
        Self {
            fail,
            calls: vec![],
            plan: plan(),
        }
    }
    fn call(&mut self, name: &'static str) -> Result<()> {
        self.calls.push(name);
        if self.fail == name {
            Err(format!("injected {name} failure"))
        } else {
            Ok(())
        }
    }
}
impl PackageBackend for Packages {
    fn resolve(&mut self) -> Result<ExecutionPlan> {
        self.call("resolve")?;
        Ok(self.plan.clone())
    }
    fn prerequisites(&mut self, _: &ExecutionPlan) -> Result<()> {
        self.call("disk")
    }
    fn download(&mut self, _: &ExecutionPlan) -> Result<()> {
        self.call("download")
    }
    fn verify(&mut self, _: &ExecutionPlan) -> Result<()> {
        self.call("signature")
    }
    fn apply(&mut self, _: &ExecutionPlan) -> Result<()> {
        self.call("apply")
    }
    fn current_state(&mut self) -> Result<CurrentSystemState> {
        self.call("current")?;
        Ok(if self.fail == "drift" {
            self.plan.current.clone()
        } else {
            self.plan.expected_state()
        })
    }
}
#[derive(Default)]
struct Snapshots {
    created: usize,
    fail_post: bool,
    fail_activate: bool,
    fail_baseline: bool,
}
impl SnapshotBackend for Snapshots {
    fn prepare_boot_baseline(&mut self, _: &str) -> Result<()> {
        if self.fail_baseline {
            Err("baseline publication interrupted".into())
        } else {
            Ok(())
        }
    }
    fn activate_boot(&mut self, _: &str) -> Result<()> {
        if self.fail_activate {
            Err("activation interrupted".into())
        } else {
            Ok(())
        }
    }
    fn boot_id(&mut self) -> Result<String> {
        Ok("boot-before".into())
    }
    fn create_post_transaction_snapshot(&mut self, id: i64, _: &ExecutionPlan) -> Result<String> {
        if self.fail_post {
            return Err("injected post-snapshot failure".into());
        }
        Ok(format!("post:{id}"))
    }
    fn prerequisites(&mut self, _: &ExecutionPlan) -> Result<()> {
        Ok(())
    }
    fn create_pre_transaction_snapshot(&mut self, id: i64, _: &ExecutionPlan) -> Result<String> {
        self.created += 1;
        Ok(format!("snapshot:{id}"))
    }
    fn mark_snapshot_good(&mut self, _: &str) -> Result<()> {
        panic!("live update cannot promote a boot generation")
    }
    fn request_rollback(&mut self, _: &str) -> Result<()> {
        panic!("never claim automatic rollback")
    }
}
struct Boot(bool);
impl BootBackend for Boot {
    fn regenerate(&mut self, _: &ExecutionPlan, _: i64) -> Result<()> {
        if self.0 {
            Err("UKI regeneration failed".into())
        } else {
            Ok(())
        }
    }
}
struct Health(HealthStatus);
impl HealthChecks for Health {
    fn run(&mut self, _: &ExecutionPlan) -> Vec<HealthCheckResult> {
        vec![HealthCheckResult {
            name: "fixture".into(),
            status: self.0,
            required: true,
            detail: "fixture result".into(),
        }]
    }
}

#[test]
fn execution_order_and_boot_confirmation_boundary() {
    let temp = Temp::new();
    let mut session = temp.session();
    let mut p = Packages::new("");
    let mut s = Snapshots::default();
    let record = execute(
        &mut session,
        plan(),
        &mut p,
        &mut s,
        &mut Boot(false),
        &mut Health(HealthStatus::Pass),
        || false,
    )
    .unwrap();
    assert_eq!(record.state, TransactionState::AwaitingBoot);
    assert_eq!(record.outcome, TransactionOutcome::AwaitingBoot);
    assert_eq!(
        p.calls,
        [
            "disk",
            "download",
            "signature",
            "resolve",
            "apply",
            "current"
        ]
    );
    assert_eq!(s.created, 1);
    assert!(record.boot_regenerated);
    assert_eq!(
        record.resulting_system_state,
        Some(plan().expected_state().id)
    );
    assert!(session.ensure_ready().is_err());
    assert_eq!(
        read_history(&temp.0.join("history.sqlite")).unwrap(),
        vec![record]
    );
}

#[test]
fn failure_matrix_is_durable_and_stops_at_the_failing_phase() {
    for (failure, state, at) in [
        (
            "disk",
            TransactionState::Failed,
            TransactionState::Preparing,
        ),
        (
            "download",
            TransactionState::Failed,
            TransactionState::Preparing,
        ),
        (
            "signature",
            TransactionState::Failed,
            TransactionState::Preparing,
        ),
        (
            "resolve",
            TransactionState::Failed,
            TransactionState::SnapshotCreated,
        ),
        (
            "apply",
            TransactionState::RollbackRequired,
            TransactionState::Applying,
        ),
        (
            "boot",
            TransactionState::RollbackRequired,
            TransactionState::Validating,
        ),
        (
            "health",
            TransactionState::RollbackRequired,
            TransactionState::Validating,
        ),
        (
            "unavailable",
            TransactionState::RollbackRequired,
            TransactionState::Validating,
        ),
        (
            "drift",
            TransactionState::RollbackRequired,
            TransactionState::Validating,
        ),
    ] {
        let temp = Temp::new();
        let mut session = temp.session();
        let mut p = Packages::new(failure);
        let health = match failure {
            "health" => HealthStatus::Fail,
            "unavailable" => HealthStatus::Unavailable,
            _ => HealthStatus::Pass,
        };
        let record = execute(
            &mut session,
            plan(),
            &mut p,
            &mut Snapshots::default(),
            &mut Boot(failure == "boot"),
            &mut Health(health),
            || false,
        )
        .unwrap();
        assert_eq!(record.state, state, "{failure}");
        assert_eq!(record.failure.as_ref().unwrap().at, at);
        if state == TransactionState::Failed {
            assert!(!p.calls.contains(&"apply"));
        }
        let loaded = session.records().unwrap();
        assert_eq!(loaded, vec![record]);
        let json = serde_json::to_value(&loaded).unwrap();
        assert!(json[0]["failure"]["message"].is_string());
    }
}

#[test]
fn missing_snapshots_prevents_all_package_work() {
    let temp = Temp::new();
    let mut p = Packages::new("");
    let record = execute(
        &mut temp.session(),
        plan(),
        &mut p,
        &mut UnavailableSnapshots,
        &mut Boot(false),
        &mut Health(HealthStatus::Pass),
        || false,
    )
    .unwrap();
    assert_eq!(record.state, TransactionState::Failed);
    assert!(p.calls.is_empty());
    assert!(record.snapshot.is_none());
}

#[test]
fn cancellation_at_every_boundary_never_succeeds() {
    for cancel_at in 0..8 {
        let temp = Temp::new();
        let count = Cell::new(0);
        let mut p = Packages::new("");
        let record = execute(
            &mut temp.session(),
            plan(),
            &mut p,
            &mut Snapshots::default(),
            &mut Boot(false),
            &mut Health(HealthStatus::Pass),
            || {
                let i = count.get();
                count.set(i + 1);
                i >= cancel_at
            },
        )
        .unwrap();
        assert!(matches!(
            record.state,
            TransactionState::Failed | TransactionState::RollbackRequired
        ));
        assert!(record.failure.unwrap().interrupted);
    }
}

#[test]
fn interrupted_transactions_are_recovered_without_replay() {
    for stop in [
        TransactionState::Preparing,
        TransactionState::SnapshotPending,
        TransactionState::Applying,
        TransactionState::Validating,
    ] {
        let temp = Temp::new();
        let mut session = temp.session();
        let mut record = TransactionRecord::new(plan());
        session.insert(&mut record).unwrap();
        for state in [
            TransactionState::Preparing,
            TransactionState::Downloaded,
            TransactionState::SnapshotPending,
            TransactionState::SnapshotCreated,
            TransactionState::Applying,
            TransactionState::Validating,
        ] {
            session.advance(&mut record, state).unwrap();
            if state == stop {
                break;
            }
        }
        drop(session);
        let mut session = temp.session();
        session.recover_interrupted().unwrap();
        let record = session.records().unwrap().remove(0);
        assert!(record.failure.as_ref().unwrap().interrupted);
        assert_eq!(record.failure.unwrap().at, stop);
        assert_eq!(
            record.state,
            if stop.mutation_possible() {
                TransactionState::RollbackRequired
            } else {
                TransactionState::Failed
            }
        );
    }
}

#[test]
fn state_machine_rejects_skipped_and_terminal_transitions() {
    let mut record = TransactionRecord::new(plan());
    assert!(record.transition(TransactionState::Succeeded).is_err());
    assert!(record.transition(TransactionState::Applying).is_err());
    for state in [
        TransactionState::Preparing,
        TransactionState::Downloaded,
        TransactionState::SnapshotPending,
        TransactionState::SnapshotCreated,
        TransactionState::Applying,
        TransactionState::Validating,
        TransactionState::AwaitingBoot,
        TransactionState::Succeeded,
    ] {
        record.transition(state).unwrap();
    }
    assert!(record.transition(TransactionState::Applying).is_err());
    assert!(!TransactionState::Applying.can_transition(TransactionState::Succeeded));
    assert!(!TransactionState::Failed.can_transition(TransactionState::RolledBack));
    assert!(TransactionState::RollbackRequired.can_transition(TransactionState::RolledBack));
}

#[test]
fn plan_validation_and_removal_state_are_consistent() {
    let mut p = plan();
    p.validate().unwrap();
    p.snapshot_required = false;
    assert!(p.validate().is_err());
    p.snapshot_required = true;
    p.packages.download_bytes += 1;
    assert!(p.validate().is_err());
    p.packages.download_bytes -= 1;
    p.current.id = "invented".into();
    assert!(p.validate().is_err());
    let mut p = plan();
    p.packages.changes = vec![PackageChange::Remove {
        name: "linux".into(),
        version: "1-1".into(),
    }];
    p.packages.targets.clear();
    p.packages.download_bytes = 0;
    p.validate().unwrap();
    assert!(p.expected_state().packages.is_empty());
    p.packages.changes.push(p.packages.changes[0].clone());
    assert!(p.validate().is_err());
}

#[test]
fn pacman_keeps_signature_policy_and_native_dependency_reasons() {
    struct Runner {
        planner: PlannerFixture,
        policy: &'static str,
        mutations: Vec<Vec<String>>,
        fail: bool,
    }
    impl CommandRunner for Runner {
        fn run(&mut self, program: &str, args: &[String]) -> Result<CommandOutput> {
            if args.first().map(String::as_str) == Some("SigLevel") {
                return Ok(CommandOutput {
                    success: true,
                    stdout: "PackageRequired PackageTrustedOnly".into(),
                    stderr: String::new(),
                });
            }
            if args.first().map(String::as_str) == Some("--repo") {
                return Ok(CommandOutput {
                    success: true,
                    stdout: self.policy.into(),
                    stderr: String::new(),
                });
            }
            if program == "/usr/bin/pacman"
                && args.first().map(String::as_str) == Some("--sync")
                && !args.iter().any(|a| a == "--print-format")
            {
                self.mutations.push(args.to_vec());
                return Ok(CommandOutput {
                    success: !self.fail,
                    stdout: String::new(),
                    stderr: "signature rejected".into(),
                });
            }
            self.planner.run(program, args)
        }
        fn read_file(&mut self, path: &str) -> Result<String> {
            self.planner.read_file(path)
        }
    }
    let mut backend = Pacman {
        runner: Runner {
            planner: PlannerFixture {
                calls: vec![],
                fail: false,
                cached: false,
            },
            policy: "PackageOptional PackageTrustedOnly",
            mutations: vec![],
            fail: false,
        },
    };
    let p = backend.resolve().unwrap();
    assert!(backend.download(&p).is_err());
    assert!(backend.runner.mutations.is_empty());
    backend.runner.policy = "PackageRequired PackageTrustAll";
    assert!(backend.download(&p).is_err());
    assert!(backend.runner.mutations.is_empty());
    backend.runner.policy =
        "PackageRequired PackageTrustedOnly DatabaseOptional DatabaseTrustedOnly";
    backend.download(&p).unwrap();
    backend.verify(&p).unwrap();
    backend.apply(&p).unwrap();
    for args in &backend.runner.mutations {
        assert!(args.contains(&"--sysupgrade".into()));
        assert!(args.iter().all(|a| a.starts_with("--")));
        assert!(!args
            .iter()
            .any(|a| a.contains("nodeps") || a.contains("overwrite") || a.contains("refresh")));
    }
    assert!(backend.runner.mutations[0].contains(&"--downloadonly".into()));
    assert!(backend.runner.mutations[1].contains(&"--downloadonly".into()));
    assert!(!backend.runner.mutations[2].contains(&"--downloadonly".into()));
    backend.runner.policy = "";
    backend.verify(&p).unwrap();
    backend.runner.planner.cached = true;
    assert_eq!(
        backend.resolve().unwrap(),
        p,
        "download must not change the reviewed plan"
    );
    backend.runner.fail = true;
    assert!(backend
        .verify(&p)
        .unwrap_err()
        .contains("signature rejected"));
}

#[test]
fn history_is_read_only_versioned_and_lock_is_exclusive() {
    let temp = Temp::new();
    let path = temp.0.join("history.sqlite");
    assert!(read_history(&path).unwrap().is_empty());
    assert!(!path.exists());
    let session = temp.session();
    assert!(UpdateSession::open(&path, &temp.0.join("update.lock")).is_err());
    drop(session);
    let db = rusqlite::Connection::open(&path).unwrap();
    db.pragma_update(None, "user_version", 99).unwrap();
    drop(db);
    assert!(read_history(&path).is_err());
    assert!(UpdateSession::open(&path, &temp.0.join("update.lock")).is_err());
}

#[test]
fn published_history_migrates_and_recovers_failed_publication() {
    let temp = Temp::new();
    let public = temp.0.join("history.sqlite");
    let private = temp.0.join("private/history.sqlite");
    let lock = temp.0.join("update.lock");
    let mut old = temp.session();
    let mut record = TransactionRecord::new(plan());
    old.insert(&mut record).unwrap();
    drop(old);
    let mut session = UpdateSession::open_published(&private, &lock, &public).unwrap();
    assert_eq!(session.records().unwrap(), vec![record.clone()]);
    assert_eq!(read_history(&public).unwrap(), vec![record.clone()]);
    fs::remove_file(&public).unwrap();
    fs::create_dir(&public).unwrap();
    assert!(session
        .advance(&mut record, TransactionState::Preparing)
        .is_err());
    assert_eq!(session.records().unwrap(), vec![record.clone()]);
    assert_eq!(record.state, TransactionState::Preparing);
    drop(session);
    fs::remove_dir(&public).unwrap();
    let session = UpdateSession::open_published(&private, &lock, &public).unwrap();
    assert_eq!(read_history(&public).unwrap(), vec![record]);
    drop(session);
    let db = rusqlite::Connection::open(&private).unwrap();
    db.pragma_update(None, "user_version", 99).unwrap();
    drop(db);
    assert!(UpdateSession::open_published(&private, &lock, &public).is_err());
}

#[cfg(unix)]
#[test]
fn public_sqlite_locks_cannot_block_private_commits_or_migration() {
    use rusqlite::{Connection, OpenFlags};
    use std::os::unix::fs::PermissionsExt;
    let temp = Temp::new();
    let public = temp.0.join("history.sqlite");
    let private = temp.0.join("private/history.sqlite");
    let lock = temp.0.join("update.lock");
    let mut old = temp.session();
    let mut record = TransactionRecord::new(plan());
    old.insert(&mut record).unwrap();
    drop(old);
    fs::set_permissions(&lock, fs::Permissions::from_mode(0o644)).unwrap();
    let reader = Connection::open_with_flags(&public, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
    reader
        .execute_batch("BEGIN; SELECT * FROM transactions;")
        .unwrap();
    // This same reader blocks a DELETE-journal writer before migration.
    let writer = Connection::open(&public).unwrap();
    writer.busy_timeout(std::time::Duration::ZERO).unwrap();
    assert!(writer
        .execute("UPDATE transactions SET record=record", [])
        .is_err());
    drop(writer);
    let mut session = UpdateSession::open_published(&private, &lock, &public).unwrap();
    session
        .advance(&mut record, TransactionState::Preparing)
        .unwrap();
    let current_reader =
        Connection::open_with_flags(&public, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
    current_reader
        .execute_batch("BEGIN; SELECT * FROM transactions;")
        .unwrap();
    session
        .advance(&mut record, TransactionState::Failed)
        .unwrap();
    assert_eq!(read_history(&public).unwrap(), vec![record.clone()]);
    assert_eq!(session.records().unwrap(), vec![record]);
    for (path, mode) in [(&private, 0o600), (&lock, 0o600), (&public, 0o644)] {
        assert_eq!(
            fs::metadata(path).unwrap().permissions().mode() & 0o777,
            mode
        );
    }
    assert_eq!(
        fs::metadata(private.parent().unwrap())
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o700
    );
    assert!(UpdateSession::open_published(&private, &lock, &public).is_err());
}

#[test]
fn old_updater_writes_survive_root_rollback_and_divergence_is_preserved() {
    let temp = Temp::new();
    let public = temp.0.join("history.sqlite");
    let private = temp.0.join("private/history.sqlite");
    let lock = temp.0.join("update.lock");
    let mut session = UpdateSession::open_published(&private, &lock, &public).unwrap();
    let mut record = TransactionRecord::new(plan());
    session.insert(&mut record).unwrap();
    drop(session);
    // The old schema-1 updater ignores publication metadata and writes to the public path.
    let mut old = UpdateSession::open(&public, &lock).unwrap();
    old.advance(&mut record, TransactionState::Preparing)
        .unwrap();
    let mut later = TransactionRecord::new(plan());
    old.insert(&mut later).unwrap();
    drop(old);
    let expected = vec![later, record.clone()];
    assert_eq!(read_recovery_history(&public).unwrap(), expected);
    let session = UpdateSession::open_published(&private, &lock, &public).unwrap();
    assert_eq!(session.records().unwrap(), expected);
    assert_eq!(read_history(&public).unwrap(), expected);
    drop(session);
    // A private commit whose publication failed must never be silently overwritten by an old writer.
    let mut writer = UpdateSession::open(&private, &lock).unwrap();
    writer
        .advance(&mut record, TransactionState::Downloaded)
        .unwrap();
    drop(writer);
    assert_eq!(read_recovery_history(&public).unwrap()[1], record);
    let mut old = UpdateSession::open(&public, &lock).unwrap();
    let mut old_record = old.records().unwrap()[1].clone();
    old.advance(&mut old_record, TransactionState::Failed)
        .unwrap();
    drop(old);
    let before_private = fs::read(&private).unwrap();
    let before_public = fs::read(&public).unwrap();
    assert!(read_recovery_history(&public)
        .unwrap_err()
        .contains("diverged"));
    assert!(UpdateSession::open_published(&private, &lock, &public)
        .err()
        .unwrap()
        .contains("diverged"));
    assert_eq!(fs::read(&private).unwrap(), before_private);
    assert_eq!(fs::read(&public).unwrap(), before_public);
}

#[test]
fn disk_checks_reject_shortfall_and_overflow() {
    assert!(check_disk_space(100, 20, 30, 50).is_ok());
    assert!(check_disk_space(99, 20, 30, 50).is_err());
    assert!(check_disk_space(u64::MAX, u64::MAX, 1, 0).is_err());
}

#[test]
fn health_distinguishes_failure_warning_and_unavailable() {
    assert!(!health_acceptable(&[]));
    let mut result = HealthCheckResult {
        name: "test".into(),
        status: HealthStatus::Pass,
        required: true,
        detail: "".into(),
    };
    assert!(health_acceptable(&[result.clone()]));
    for status in [
        HealthStatus::Fail,
        HealthStatus::Unavailable,
        HealthStatus::Warn,
    ] {
        result.status = status;
        assert!(!health_acceptable(&[result.clone()]));
    }
    result.required = false;
    assert!(health_acceptable(&[result.clone()]));
    result.status = HealthStatus::Unavailable;
    assert!(health_acceptable(&[result.clone()]));
    result.status = HealthStatus::Fail;
    assert!(!health_acceptable(&[result]));
}

#[test]
fn pacman_machine_output_rejects_ambiguity() {
    let row = format!("linux\t2-1\tcore\t10\t{}\t\t\n", "a".repeat(64));
    let targets = parse_targets(&row).unwrap();
    assert_eq!(targets.len(), 1);
    assert_eq!(targets[0].archive_bytes, 10);
    assert!(parse_targets("").unwrap().is_empty());
    for invalid in [
        "warning: text".into(),
        row.replace("\t10\t", "\t-1\t"),
        row.replace("linux\t", "../linux\t"),
        row.replace("\t\t\n", "\toldlinux\t\n"),
        row.replace("\t\t\n", "\t\toldlinux\n"),
        format!("{row}{row}"),
    ] {
        assert!(parse_targets(&invalid).is_err(), "{invalid}");
    }
    assert!(parse_current("linux 1-1\nlinux 2-1").is_err());
    assert!(parse_current("").is_err());
    assert!(database_field("%ISIZE%\n10\n\n%ISIZE%\n20\n", "ISIZE").is_err());
    assert_eq!(database_field("%ISIZE%\n10\n", "ISIZE").unwrap(), "10");
}

struct PlannerFixture {
    calls: Vec<String>,
    fail: bool,
    cached: bool,
}
impl CommandRunner for PlannerFixture {
    fn run(&mut self, program: &str, args: &[String]) -> Result<CommandOutput> {
        self.calls.push(format!("{program} {}", args.join(" ")));
        assert!(!args
            .iter()
            .any(|a| matches!(a.as_str(), "--refresh" | "--downloadonly" | "-y")));
        let stdout = match (program, args.first().map(String::as_str)) {
            (_, Some("RootDir")) => "/\n".into(),
            (_, Some("DBPath")) => "/var/lib/pacman/\n".into(),
            ("/usr/bin/pacman", Some("--query")) => "linux 1-1\n".into(),
            ("/usr/bin/pacman", Some("--sync")) => format!(
                "linux\t2-1\tcore\t{}\t{}\t\t\nmesa\t3-1\textra\t4\t{}\t\t\n",
                if self.cached { 0 } else { 10 },
                "a".repeat(64),
                "b".repeat(64)
            ),
            ("/usr/bin/bsdtar", _) => {
                let linux = args.last().unwrap().starts_with("linux-");
                format!(
                    "%NAME%\n{}\n\n%VERSION%\n{}\n\n%CSIZE%\n{}\n\n%ISIZE%\n30\n\n%SHA256SUM%\n{}\n",
                    if linux { "linux" } else { "mesa" },
                    if linux { "2-1" } else { "3-1" },
                    if linux { 10 } else { 4 },
                    if linux { "a" } else { "b" }.repeat(64)
                )
            }
            _ => panic!("unexpected command {program} {args:?}"),
        };
        Ok(CommandOutput {
            success: !self.fail,
            stdout,
            stderr: "fixture failure".into(),
        })
    }
    fn read_file(&mut self, path: &str) -> Result<String> {
        assert_eq!(path, "/var/lib/pacman/local/linux-1-1/desc");
        Ok("%SIZE%\n10\n".into())
    }
}

#[test]
fn planner_resolves_real_fields_and_propagates_command_errors() {
    let mut backend = Pacman {
        runner: PlannerFixture {
            calls: vec![],
            fail: false,
            cached: false,
        },
    };
    let plan = backend.resolve().unwrap();
    assert_eq!(plan.packages.changes.len(), 2);
    assert!(matches!(
        plan.packages.changes[0],
        PackageChange::Upgrade { .. }
    ));
    assert!(matches!(
        plan.packages.changes[1],
        PackageChange::Install { .. }
    ));
    assert_eq!(plan.packages.download_bytes, 14);
    assert_eq!(plan.packages.installed_delta_bytes, Some(50));
    assert!(plan.boot.regenerate_uki && plan.snapshot_required);
    backend.runner.cached = true;
    assert_eq!(
        backend.resolve().unwrap(),
        plan,
        "download must not change the reviewed plan"
    );
    backend.runner.fail = true;
    assert!(backend.resolve().is_err());
}

#[test]
fn no_op_needs_no_snapshot_or_package_mutation() {
    let temp = Temp::new();
    let mut p = plan();
    p.packages.changes.clear();
    p.packages.targets.clear();
    p.packages.download_bytes = 0;
    let mut packages = Packages::new("");
    let record = execute(
        &mut temp.session(),
        p,
        &mut packages,
        &mut UnavailableSnapshots,
        &mut Boot(true),
        &mut Health(HealthStatus::Fail),
        || false,
    )
    .unwrap();
    assert_eq!(record.state, TransactionState::Succeeded);
    assert!(packages.calls.is_empty());
}

#[test]
fn system_checks_distinguish_missing_tool_and_failed_check() {
    struct Runner;
    impl CommandRunner for Runner {
        fn run(&mut self, program: &str, _: &[String]) -> Result<CommandOutput> {
            if program == "/usr/bin/ukify" {
                return Err("tool missing".into());
            }
            Ok(CommandOutput {
                success: false,
                stdout: "".into(),
                stderr: "failure".into(),
            })
        }
    }
    let checks = SystemHealth {
        runner: Runner,
        uki_path: "/efi/fixture.efi".into(),
    }
    .run(&plan());
    assert_eq!(
        checks.iter().find(|c| c.name == "uki").unwrap().status,
        HealthStatus::Unavailable
    );
    assert_eq!(checks[0].status, HealthStatus::Fail);
    assert_eq!(
        checks
            .iter()
            .find(|c| c.name == "failed_system_units")
            .unwrap()
            .status,
        HealthStatus::Unavailable
    );
    assert!(!health_acceptable(&checks));
    assert!(SystemBoot { runner: Runner }
        .regenerate(&plan(), 1)
        .is_err());
}

#[test]
fn boot_refresh_only_reads_matching_installed_loader_copies() {
    struct Runner {
        fail_at: usize,
        calls: usize,
    }
    impl CommandRunner for Runner {
        fn prepare_boot(&mut self, _: i64) -> Result<()> {
            Ok(())
        }
        fn run(&mut self, program: &str, args: &[String]) -> Result<CommandOutput> {
            self.calls += 1;
            match self.calls {
                1 => assert_eq!(program, "/usr/bin/mkinitcpio"),
                2 | 3 => {
                    assert_eq!(program, "/usr/bin/cmp");
                    assert_eq!(args[1], "/usr/lib/systemd/boot/efi/systemd-bootx64.efi");
                    assert_eq!(
                        args[2],
                        if self.calls == 2 {
                            "/efi/EFI/systemd/systemd-bootx64.efi"
                        } else {
                            "/efi/EFI/BOOT/BOOTX64.EFI"
                        }
                    );
                }
                _ => panic!("unexpected boot command"),
            }
            Ok(CommandOutput {
                success: self.calls != self.fail_at,
                stdout: String::new(),
                stderr: "fixture failure".into(),
            })
        }
    }
    for fail_at in 0..=3 {
        let mut boot = SystemBoot {
            runner: Runner { fail_at, calls: 0 },
        };
        assert_eq!(boot.regenerate(&plan(), 1).is_ok(), fail_at == 0);
        assert_eq!(boot.runner.calls, if fail_at == 0 { 3 } else { fail_at });
    }
}

#[test]
fn systemd_or_loader_mutation_rejects_the_entire_plan_before_execution() {
    let mut systemd = plan();
    systemd.current = CurrentSystemState::new(BTreeMap::from([("systemd".into(), "1-1".into())]));
    systemd.packages.changes = vec![PackageChange::Upgrade {
        name: "systemd".into(),
        from: "1-1".into(),
        to: "2-1".into(),
    }];
    systemd.packages.targets[0].name = "systemd".into();
    let mut loader = plan();
    loader.boot.update_bootloader = true;
    for rejected in [systemd, loader] {
        assert!(rejected
            .validate()
            .unwrap_err()
            .contains("entire plan rejected"));
        let temp = Temp::new();
        let mut packages = Packages::new("");
        let mut snapshots = Snapshots::default();
        assert!(execute(
            &mut temp.session(),
            rejected,
            &mut packages,
            &mut snapshots,
            &mut Boot(false),
            &mut Health(HealthStatus::Pass),
            || false
        )
        .is_err());
        assert!(packages.calls.is_empty());
        assert_eq!(snapshots.created, 0);
        assert!(temp.session().records().unwrap().is_empty());
    }
}

#[test]
fn confirmation_requires_new_boot_matching_generation_and_fresh_health() {
    use crate::integration::{confirm, BootEvidence};
    struct Evidence {
        boot: &'static str,
        bad: &'static str,
        rollback: bool,
        promoted: usize,
    }
    impl BootEvidence for Evidence {
        fn boot_count(
            &mut self,
            _: &str,
        ) -> Result<Option<distro_snapshots::generations::BootCount>> {
            Ok(Some(distro_snapshots::generations::BootCount::Counted {
                left: 2,
                done: 1,
            }))
        }
        fn boot_id(&mut self) -> Result<String> {
            Ok(self.boot.into())
        }
        fn verify(&mut self, _: &str, _: i64, rollback: bool) -> Result<()> {
            self.rollback = rollback;
            if self.bad == "identity" {
                Err("wrong root or UKI".into())
            } else {
                Ok(())
            }
        }
        fn current_state(&mut self) -> Result<CurrentSystemState> {
            Ok(if self.rollback || self.bad == "packages" {
                plan().current
            } else {
                plan().expected_state()
            })
        }
        fn health(&mut self, _: &ExecutionPlan) -> Vec<HealthCheckResult> {
            Health(if self.bad == "health" {
                HealthStatus::Fail
            } else {
                HealthStatus::Pass
            })
            .run(&plan())
        }
        fn promote(&mut self, _: &str, _: &str) -> Result<()> {
            if self.bad == "promotion" {
                return Err("injected metadata write failure".into());
            }
            self.promoted += 1;
            Ok(())
        }
    }
    let temp = Temp::new();
    let mut session = temp.session();
    let record = execute(
        &mut session,
        plan(),
        &mut Packages::new(""),
        &mut Snapshots::default(),
        &mut Boot(false),
        &mut Health(HealthStatus::Pass),
        || false,
    )
    .unwrap();
    let mut e = Evidence {
        boot: "boot-before",
        bad: "",
        rollback: false,
        promoted: 0,
    };
    assert!(confirm(&mut session, record.id, false, &mut e).is_err());
    for bad in ["identity", "packages", "health", "promotion"] {
        e.boot = "boot-after";
        e.bad = bad;
        assert!(confirm(&mut session, record.id, false, &mut e).is_err());
        let saved = &session.records().unwrap()[0];
        assert_eq!(saved.state, TransactionState::AwaitingBoot);
        assert!(saved.confirmation.is_some());
        assert!(saved.confirmation.as_ref().unwrap().error.is_some());
        assert_eq!(e.promoted, 0);
    }
    drop(session); // interrupted confirmation resumes from persisted intent/evidence
    let mut session = temp.session();
    e.bad = "";
    let good = confirm(&mut session, record.id, false, &mut e).unwrap();
    assert_eq!(good.state, TransactionState::Succeeded);
    assert_eq!(
        good.confirmation.as_ref().unwrap().boot_count,
        Some(distro_snapshots::generations::BootCount::Counted { left: 2, done: 1 })
    );
    assert_eq!(e.promoted, 1);
    assert_eq!(
        confirm(&mut session, record.id, false, &mut e).unwrap(),
        good
    );
    assert_eq!(e.promoted, 1);
    assert_eq!(
        confirm(&mut session, record.id, true, &mut e)
            .unwrap()
            .state,
        TransactionState::RolledBack
    );
    assert_eq!(e.promoted, 1);
    assert_eq!(
        confirm(&mut session, record.id, true, &mut e)
            .unwrap()
            .state,
        TransactionState::RolledBack
    );
}

#[test]
fn rollback_planning_rejects_targets_that_confirmation_cannot_finalize() {
    use crate::integration::validate_rollback_target;
    let mut original = TransactionRecord::new(plan());
    original.id = 1;
    original.state = TransactionState::Succeeded;
    original.snapshot = Some("pre-1".into());
    assert!(validate_rollback_target(&[original.clone()], Some("1"), "pre-1").is_ok());
    assert!(validate_rollback_target(&[], Some("1"), "pre-1").is_err());
    assert!(validate_rollback_target(&[original.clone()], Some("1"), "post-1").is_err());
    let mut later = TransactionRecord::new(plan());
    later.id = 2;
    later.state = TransactionState::Failed; // Even a pre-mutation failure makes the old target stale.
    assert!(
        validate_rollback_target(&[original.clone(), later.clone()], Some("1"), "pre-1")
            .unwrap_err()
            .contains("stale")
    );
    later.plan.packages.changes.clear(); // Empty plans do not advance the generation.
    assert!(validate_rollback_target(&[original.clone(), later], Some("1"), "pre-1").is_ok());
    for interrupted in [
        TransactionState::Applying,
        TransactionState::Validating,
        TransactionState::AwaitingBoot,
        TransactionState::RollbackRequired,
    ] {
        original.state = interrupted;
        assert!(
            validate_rollback_target(&[original.clone()], Some("1"), "pre-1").is_ok(),
            "{interrupted:?}"
        );
    }
    original.state = TransactionState::RolledBack;
    assert!(validate_rollback_target(&[original], Some("1"), "pre-1").is_err());
    assert!(validate_rollback_target(&[], None, "manual").is_ok());
}

#[test]
fn stale_confirmation_and_missing_post_snapshot_fail_closed() {
    use crate::integration::{confirm, BootEvidence};
    struct Unreachable;
    impl BootEvidence for Unreachable {
        fn boot_id(&mut self) -> Result<String> {
            panic!("stale record must not probe")
        }
        fn verify(&mut self, _: &str, _: i64, _: bool) -> Result<()> {
            unreachable!()
        }
        fn current_state(&mut self) -> Result<CurrentSystemState> {
            unreachable!()
        }
        fn health(&mut self, _: &ExecutionPlan) -> Vec<HealthCheckResult> {
            unreachable!()
        }
        fn promote(&mut self, _: &str, _: &str) -> Result<()> {
            unreachable!()
        }
    }
    let temp = Temp::new();
    let mut session = temp.session();
    let mut record = execute(
        &mut session,
        plan(),
        &mut Packages::new(""),
        &mut Snapshots::default(),
        &mut Boot(false),
        &mut Health(HealthStatus::Pass),
        || false,
    )
    .unwrap();
    record.post_snapshot = None;
    session.save(&record).unwrap();
    assert!(confirm(&mut session, record.id, false, &mut Unreachable)
        .unwrap_err()
        .contains("missing generation"));
    let mut later = TransactionRecord::new(plan());
    session.insert(&mut later).unwrap();
    assert!(confirm(&mut session, record.id, false, &mut Unreachable)
        .unwrap_err()
        .contains("stale"));
}

#[test]
fn post_snapshot_failure_retains_pre_snapshot_and_requires_rollback() {
    let temp = Temp::new();
    let mut snapshots = Snapshots {
        fail_post: true,
        ..Default::default()
    };
    let mut packages = Packages::new("");
    let record = execute(
        &mut temp.session(),
        plan(),
        &mut packages,
        &mut snapshots,
        &mut Boot(false),
        &mut Health(HealthStatus::Pass),
        || false,
    )
    .unwrap();
    assert_eq!(record.state, TransactionState::RollbackRequired);
    assert!(record.snapshot.is_some());
    assert!(record.post_snapshot.is_none());
    assert!(packages.calls.contains(&"apply"));
    assert!(record.failure.unwrap().message.contains("post-snapshot"));
}
