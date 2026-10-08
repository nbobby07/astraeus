use crate::*;

pub trait PackageBackend {
    fn resolve(&mut self) -> Result<ExecutionPlan>;
    fn prerequisites(&mut self, plan: &ExecutionPlan) -> Result<()>;
    fn download(&mut self, plan: &ExecutionPlan) -> Result<()>;
    fn verify(&mut self, plan: &ExecutionPlan) -> Result<()>;
    fn apply(&mut self, plan: &ExecutionPlan) -> Result<()>;
    fn current_state(&mut self) -> Result<CurrentSystemState>;
}

/// Must protect both the root/package DB and the current ESP boot artifacts before apply.
/// No filesystem operation or boot entry implementation belongs to this crate.
pub trait SnapshotBackend {
    fn prerequisites(&mut self, plan: &ExecutionPlan) -> Result<()>;
    /// Must be idempotent by transaction ID, including recovery after snapshot_pending.
    fn create_pre_transaction_snapshot(&mut self, id: i64, plan: &ExecutionPlan) -> Result<String>;
    fn boot_id(&mut self) -> Result<String> {
        Err("boot identity backend unavailable".into())
    }
    fn create_post_transaction_snapshot(&mut self, _: i64, _: &ExecutionPlan) -> Result<String> {
        Err("post-update snapshot backend unavailable".into())
    }
    fn activate_boot(&mut self, _reference: &str) -> Result<()> {
        Ok(())
    }
    fn prepare_boot_baseline(&mut self, _reference: &str) -> Result<()> {
        Ok(())
    }
    /// Called only by an integrated boot-confirmation owner, never by execute().
    fn mark_snapshot_good(&mut self, reference: &str) -> Result<()>;
    /// Acceptance is not proof of a completed rollback.
    fn request_rollback(&mut self, reference: &str) -> Result<()>;
}

pub struct UnavailableSnapshots;
impl SnapshotBackend for UnavailableSnapshots {
    fn prerequisites(&mut self, _: &ExecutionPlan) -> Result<()> {
        Err("snapshot/boot-generation backend is not integrated; package mutation refused".into())
    }
    fn create_pre_transaction_snapshot(&mut self, _: i64, _: &ExecutionPlan) -> Result<String> {
        Err("snapshot backend unavailable".into())
    }
    fn mark_snapshot_good(&mut self, _: &str) -> Result<()> {
        Err("snapshot backend unavailable".into())
    }
    fn request_rollback(&mut self, _: &str) -> Result<()> {
        Err("snapshot backend unavailable; rollback was not performed".into())
    }
}

pub trait BootBackend {
    fn regenerate(&mut self, plan: &ExecutionPlan, transaction_id: i64) -> Result<()>;
}
pub trait HealthChecks {
    fn run(&mut self, plan: &ExecutionPlan) -> Vec<HealthCheckResult>;
}

/// Conservative budget: all downloads plus all new installed bytes, not merely net growth.
/// Cache/root can share a filesystem, so callers check their combined requirement on both.
pub fn check_disk_space(available: u64, download: u64, installed: u64, reserve: u64) -> Result<()> {
    let required = download
        .checked_add(installed)
        .and_then(|n| n.checked_add(reserve))
        .ok_or("disk requirement overflow")?;
    if available < required {
        return Err(format!(
            "insufficient disk space: {required} bytes required, {available} available"
        ));
    }
    Ok(())
}

/// Cancellation is checked at phase boundaries. Killing the process leaves durable intent.
/// A failed call never yields a success record, including failures to persist the result.
pub fn execute(
    session: &mut UpdateSession,
    plan: ExecutionPlan,
    packages: &mut impl PackageBackend,
    snapshots: &mut impl SnapshotBackend,
    boot: &mut impl BootBackend,
    health: &mut impl HealthChecks,
    canceled: impl Fn() -> bool,
) -> Result<TransactionRecord> {
    plan.validate()?;
    session.ensure_ready()?;
    let mut record = TransactionRecord::new(plan);
    session.insert(&mut record)?;
    let check_cancel = || -> Result<()> {
        if canceled() {
            Err("transaction canceled".into())
        } else {
            Ok(())
        }
    };
    let result = (|| -> Result<()> {
        check_cancel()?;
        if record.plan.packages.changes.is_empty() {
            record.resulting_system_state = Some(record.previous_system_state.clone());
            return session.advance(&mut record, TransactionState::Succeeded);
        }
        session.advance(&mut record, TransactionState::Preparing)?;
        snapshots
            .prerequisites(&record.plan)
            .map_err(|e| format!("snapshot prerequisites: {e}"))?;
        packages
            .prerequisites(&record.plan)
            .map_err(|e| format!("package prerequisites: {e}"))?;
        record.update_boot_id = Some(snapshots.boot_id()?);
        session.save(&record)?;
        check_cancel()?;
        packages
            .download(&record.plan)
            .map_err(|e| format!("package download: {e}"))?;
        check_cancel()?;
        packages
            .verify(&record.plan)
            .map_err(|e| format!("package verification: {e}"))?;
        session.advance(&mut record, TransactionState::Downloaded)?;
        check_cancel()?;
        session.advance(&mut record, TransactionState::SnapshotPending)?;
        let reference = snapshots
            .create_pre_transaction_snapshot(record.id, &record.plan)
            .map_err(|e| format!("snapshot creation: {e}"))?;
        if reference.trim().is_empty() {
            return Err("snapshot backend returned an empty reference".into());
        }
        record.snapshot = Some(reference);
        session.advance(&mut record, TransactionState::SnapshotCreated)?;
        check_cancel()?;
        // Revalidate the complete reviewed plan immediately before entering the mutation phase.
        if packages
            .resolve()
            .map_err(|e| format!("plan revalidation: {e}"))?
            != record.plan
        {
            return Err("package state or repositories changed since planning".into());
        }
        session.advance(&mut record, TransactionState::Applying)?;
        // Generation activation can change the root preset. Persist its recovery
        // reference and mutation phase before publishing any boot metadata.
        snapshots.prepare_boot_baseline(
            record
                .snapshot
                .as_deref()
                .ok_or("missing baseline snapshot")?,
        )?;
        packages
            .apply(&record.plan)
            .map_err(|e| format!("package application: {e}"))?;
        check_cancel()?;
        session.advance(&mut record, TransactionState::Validating)?;
        boot.regenerate(&record.plan, record.id)
            .map_err(|e| format!("boot artifact regeneration: {e}"))?;
        record.boot_regenerated = record.plan.boot.regenerate_uki;
        session.save(&record)?;
        check_cancel()?;
        let post = snapshots.create_post_transaction_snapshot(record.id, &record.plan)?;
        if post.trim().is_empty() {
            return Err("snapshot backend returned an empty post-update reference".into());
        }
        record.post_snapshot = Some(post);
        session.save(&record)?;
        record.health_checks = health.run(&record.plan);
        session.save(&record)?;
        if !health_acceptable(&record.health_checks) {
            return Err("post-update health checks did not pass".into());
        }
        let current = packages.current_state()?;
        record.resulting_system_state = Some(current.id.clone());
        session.save(&record)?;
        if current != record.plan.expected_state() {
            return Err("installed package state differs from the transaction plan".into());
        }
        check_cancel()?;
        // A live health check cannot establish that the new kernel/UKI boots.
        // Persist boot eligibility before the ESP can make the candidate selectable.
        session.advance(&mut record, TransactionState::AwaitingBoot)?;
        snapshots.activate_boot(
            record
                .post_snapshot
                .as_deref()
                .ok_or("missing candidate snapshot")?,
        )?;
        Ok(())
    })();
    if let Err(message) = result {
        let at = record.state;
        record.failure = Some(Failure {
            at,
            message,
            interrupted: canceled(),
        });
        let next = if at.mutation_possible() {
            TransactionState::RollbackRequired
        } else {
            TransactionState::Failed
        };
        session.advance(&mut record, next).map_err(|e| {
            format!("history persistence failed: {e}; inspect the last durable transaction phase")
        })?;
    }
    Ok(record)
}
