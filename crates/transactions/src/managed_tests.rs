use crate::*;
use distro_config::SystemConfig;
use std::{
    collections::BTreeMap,
    fs,
    sync::atomic::{AtomicU64, Ordering},
};

static NEXT: AtomicU64 = AtomicU64::new(0);

fn metadata_plan() -> ExecutionPlan {
    let current = CurrentSystemState::new(BTreeMap::new());
    let managed = reconcile(
        None,
        &current,
        &BTreeMap::new(),
        &current,
        &BTreeMap::new(),
        &SystemConfig::default(),
        &Default::default(),
        &BTreeMap::new(),
    )
    .unwrap();
    ExecutionPlan::new(
        current,
        PackagePlan {
            changes: vec![],
            targets: vec![],
            download_bytes: 0,
            installed_delta_bytes: Some(0),
        },
    )
    .with_management(managed)
}

struct Packages {
    plan: ExecutionPlan,
    applied: bool,
    fail_persistence: bool,
}
impl PackageBackend for Packages {
    fn resolve(&mut self) -> Result<ExecutionPlan> {
        Ok(self.plan.clone())
    }
    fn prerequisites(&mut self, _: &ExecutionPlan) -> Result<()> {
        Ok(())
    }
    fn download(&mut self, _: &ExecutionPlan) -> Result<()> {
        Ok(())
    }
    fn verify(&mut self, _: &ExecutionPlan) -> Result<()> {
        Ok(())
    }
    fn apply(&mut self, _: &ExecutionPlan) -> Result<()> {
        Ok(())
    }
    fn current_state(&mut self) -> Result<CurrentSystemState> {
        Ok(self.plan.expected_state())
    }
    fn operation_id(&self) -> Option<String> {
        Some("a".repeat(32))
    }
    fn prepare_locked(&mut self, _: &ExecutionPlan) -> Result<()> {
        Ok(())
    }
    fn apply_management(&mut self, _: &ExecutionPlan) -> Result<()> {
        if self.fail_persistence {
            return Err("injected persistence failure".into());
        }
        self.applied = true;
        Ok(())
    }
    fn verify_management(&mut self, _: &ExecutionPlan) -> Result<()> {
        if !self.applied {
            return Err("management not written".into());
        }
        Ok(())
    }
}

#[derive(Default)]
struct Snapshots {
    pre: bool,
    post: bool,
    active: bool,
}
impl SnapshotBackend for Snapshots {
    fn prerequisites(&mut self, _: &ExecutionPlan) -> Result<()> {
        Ok(())
    }
    fn boot_id(&mut self) -> Result<String> {
        Ok("previous-boot".into())
    }
    fn create_pre_transaction_snapshot(&mut self, _: i64, _: &ExecutionPlan) -> Result<String> {
        self.pre = true;
        Ok("before".into())
    }
    fn create_post_transaction_snapshot(&mut self, _: i64, _: &ExecutionPlan) -> Result<String> {
        assert!(self.pre);
        self.post = true;
        Ok("after".into())
    }
    fn activate_boot(&mut self, _: &str) -> Result<()> {
        assert!(self.post);
        self.active = true;
        Ok(())
    }
    fn mark_snapshot_good(&mut self, _: &str) -> Result<()> {
        panic!("no live promotion")
    }
    fn request_rollback(&mut self, _: &str) -> Result<()> {
        panic!("no online rollback")
    }
}
struct Boot(bool);
impl BootBackend for Boot {
    fn regenerate(&mut self, plan: &ExecutionPlan, id: i64) -> Result<()> {
        assert!(plan.boot.regenerate_uki && id > 0);
        self.0 = true;
        Ok(())
    }
}
struct Health;
impl HealthChecks for Health {
    fn run(&mut self, _: &ExecutionPlan) -> Vec<HealthCheckResult> {
        vec![HealthCheckResult {
            name: "fixture".into(),
            status: HealthStatus::Pass,
            required: true,
            detail: "passed".into(),
        }]
    }
}

#[test]
fn metadata_only_apply_uses_snapshots_and_requires_a_new_boot() {
    for fail_persistence in [false, true] {
        let directory = std::env::temp_dir().join(format!(
            "astraeus-management-engine-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&directory).unwrap();
        let mut session =
            UpdateSession::open(&directory.join("history.sqlite"), &directory.join("lock"))
                .unwrap();
        let plan = metadata_plan();
        plan.validate().unwrap();
        let mut packages = Packages {
            plan: plan.clone(),
            applied: false,
            fail_persistence,
        };
        let mut snapshots = Snapshots::default();
        let mut boot = Boot(false);
        let record = execute(
            &mut session,
            plan,
            &mut packages,
            &mut snapshots,
            &mut boot,
            &mut Health,
            || false,
        )
        .unwrap();
        assert_eq!(record.schema_version, 2);
        assert_eq!(record.operation_id, Some("a".repeat(32)));
        assert!(snapshots.pre);
        if fail_persistence {
            assert_eq!(record.state, TransactionState::RollbackRequired);
            assert!(!snapshots.post && !snapshots.active && !boot.0);
            assert!(record
                .failure
                .unwrap()
                .message
                .contains("management persistence"));
        } else {
            assert_eq!(record.state, TransactionState::AwaitingBoot);
            assert!(snapshots.post && snapshots.active && boot.0 && packages.applied);
        }
        drop(session);
        fs::remove_dir_all(directory).unwrap();
    }
}

#[test]
fn managed_fingerprints_and_noop_rules_cover_metadata() {
    let plan = metadata_plan();
    assert!(plan.has_mutation());
    assert!(TransactionRecord::new(plan.clone())
        .transition(TransactionState::Succeeded)
        .is_err());
    let mut changed = plan.clone();
    changed.notes.push("presentation text".into());
    assert_eq!(plan.fingerprint(), changed.fingerprint());
    changed
        .management
        .as_mut()
        .unwrap()
        .after
        .protected
        .insert("base".into());
    assert_ne!(plan.fingerprint(), changed.fingerprint());
    assert!(changed.validate().is_err());
    let mut unprotected = plan.clone();
    unprotected.snapshot_required = false;
    assert!(unprotected.validate().is_err());
    let mut mismatched = plan.clone();
    mismatched.schema_version = 1;
    assert!(mismatched.validate().is_err());
    let mut legacy = ExecutionPlan::new(plan.current, plan.packages);
    assert!(!legacy.has_mutation());
    legacy.validate().unwrap();
    let json = serde_json::to_string(&legacy).unwrap();
    assert!(!json.contains("management"));
    legacy = serde_json::from_str(&json).unwrap();
    legacy.validate().unwrap();
}

#[test]
fn complete_managed_closure_rejects_kernel_changes_and_untrusted_targets() {
    let current = CurrentSystemState::new(BTreeMap::from([("linux".into(), "1-1".into())]));
    let legacy = ExecutionPlan::new(
        current.clone(),
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
                archive_bytes: 1,
                installed_bytes: 2,
                sha256: "a".repeat(64),
            }],
            download_bytes: 1,
            installed_delta_bytes: Some(1),
        },
    );
    legacy.validate().unwrap();
    let reasons = BTreeMap::from([("linux".into(), InstallReason::Explicit)]);
    let management = reconcile(
        None,
        &current,
        &reasons,
        &legacy.expected_state(),
        &reasons,
        &SystemConfig::default(),
        &Default::default(),
        &BTreeMap::new(),
    )
    .unwrap();
    assert!(legacy
        .clone()
        .with_management(management)
        .validate()
        .unwrap_err()
        .contains("kernel changes"));
    let mut corrupt = legacy;
    corrupt.packages.targets[0].sha256 = "not-a-hash".into();
    assert!(corrupt.validate().is_err());
}
