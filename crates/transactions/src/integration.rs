//! Coordination with the existing Btrfs manager. One guard covers the entire update.
use crate::{pacman::*, *};
use distro_snapshots::{Commands, Health, Manager, MutationGuard, Native, Reason, SnapshotId};

fn error(e: impl std::fmt::Display) -> String {
    e.to_string()
}

pub fn boot_id() -> Result<String> {
    let value = std::fs::read_to_string("/proc/sys/kernel/random/boot_id").map_err(error)?;
    let value = value.trim();
    if value.len() != 36
        || !value.bytes().enumerate().all(|(i, b)| {
            if [8, 13, 18, 23].contains(&i) {
                b == b'-'
            } else {
                b.is_ascii_hexdigit()
            }
        })
    {
        return Err("invalid kernel boot ID".into());
    }
    Ok(value.into())
}

pub fn system_health() -> SystemHealth {
    SystemHealth {
        runner: NativeRunner,
        uki_path: format!("/efi/{}", distro_snapshots::UKI),
    }
}

pub struct BtrfsSnapshots<C: Commands = Native> {
    pub manager: Manager<C>,
    guard: MutationGuard,
}
impl<C: Commands> BtrfsSnapshots<C> {
    pub fn new(manager: Manager<C>) -> Result<Self> {
        let guard = manager.lock().map_err(error)?;
        Ok(Self { manager, guard })
    }
    fn create(&self, id: i64, reason: Reason) -> Result<String> {
        // Idempotent only for a completed, unique correlated snapshot. Incomplete
        // snapshot journals block the manager lock and require offline inspection.
        let matches: Vec<_> = self
            .manager
            .list()
            .map_err(error)?
            .into_iter()
            .filter(|s| s.transaction_id.as_deref() == Some(&id.to_string()) && s.reason == reason)
            .collect();
        if matches.len() > 1 {
            return Err("ambiguous transaction snapshot".into());
        }
        let snapshot = match matches.into_iter().next() {
            Some(s) => s,
            None => self
                .manager
                .create_locked(&self.guard, reason, Some(id.to_string()))
                .map_err(error)?,
        };
        Ok(snapshot.id.as_str().into())
    }
}
impl SnapshotBackend for BtrfsSnapshots {
    fn prerequisites(&mut self, plan: &ExecutionPlan) -> Result<()> {
        self.manager.plan_create().map_err(error)?;
        if !health_acceptable(&system_health().run(plan)) {
            return Err("current system health does not establish a recoverable baseline".into());
        }
        Ok(())
    }
    fn boot_id(&mut self) -> Result<String> {
        boot_id()
    }
    fn create_pre_transaction_snapshot(&mut self, id: i64, plan: &ExecutionPlan) -> Result<String> {
        let reference = self.create(id, Reason::PreUpdate)?;
        let snapshot = SnapshotId::parse(&reference).map_err(error)?;
        self.manager
            .verify_booted(&snapshot, false)
            .map_err(error)?;
        if !health_acceptable(&system_health().run(plan)) {
            return Err("pre-update boot health failed".into());
        }
        self.manager.mark_locked(&self.guard, &snapshot, Health::KnownGood,
            &format!("Pre-update boot {}: root/UKI identity and required system health passed; transaction {id}", boot_id()?)).map_err(error)?;
        Ok(reference)
    }
    fn create_post_transaction_snapshot(&mut self, id: i64, _: &ExecutionPlan) -> Result<String> {
        let reference = self.create(id, Reason::PostUpdate)?;
        self.manager
            .mark_locked(
                &self.guard,
                &SnapshotId::parse(&reference).map_err(error)?,
                Health::Candidate,
                &format!("Transaction {id} requires a new boot and health confirmation"),
            )
            .map_err(error)?;
        Ok(reference)
    }
    fn mark_snapshot_good(&mut self, _: &str) -> Result<()> {
        Err("use verified boot confirmation to promote a candidate".into())
    }
    fn request_rollback(&mut self, reference: &str) -> Result<()> {
        self.manager
            .plan_rollback(&SnapshotId::parse(reference).map_err(error)?)
            .map_err(error)?;
        Err("offline recovery required; rollback has not executed".into())
    }
}

/// Evidence providers must observe the boot, never infer it from elapsed time.
pub trait BootEvidence {
    fn boot_id(&mut self) -> Result<String>;
    fn verify(&mut self, snapshot: &str, transaction_id: i64, rollback: bool) -> Result<()>;
    fn current_state(&mut self) -> Result<CurrentSystemState>;
    fn health(&mut self, plan: &ExecutionPlan) -> Vec<HealthCheckResult>;
    fn promote(&mut self, snapshot: &str, evidence: &str) -> Result<()>;
}
impl BootEvidence for BtrfsSnapshots {
    fn boot_id(&mut self) -> Result<String> {
        boot_id()
    }
    fn verify(&mut self, reference: &str, id: i64, rollback: bool) -> Result<()> {
        let sid = SnapshotId::parse(reference).map_err(error)?;
        let snapshot = self.manager.inspect(&sid).map_err(error)?;
        if snapshot.transaction_id.as_deref() != Some(&id.to_string())
            || snapshot.reason
                != if rollback {
                    Reason::PreUpdate
                } else {
                    Reason::PostUpdate
                }
            || (rollback && snapshot.health != Health::KnownGood)
        {
            return Err("snapshot is not the expected transaction generation".into());
        }
        self.manager.verify_booted(&sid, rollback).map_err(error)
    }
    fn current_state(&mut self) -> Result<CurrentSystemState> {
        Pacman::default().current_state()
    }
    fn health(&mut self, plan: &ExecutionPlan) -> Vec<HealthCheckResult> {
        system_health().run(plan)
    }
    fn promote(&mut self, reference: &str, evidence: &str) -> Result<()> {
        self.manager
            .mark_locked(
                &self.guard,
                &SnapshotId::parse(reference).map_err(error)?,
                Health::KnownGood,
                evidence,
            )
            .map_err(error)?;
        Ok(())
    }
}

fn ensure_not_stale(records: &[TransactionRecord], id: i64) -> Result<()> {
    if records
        .iter()
        .any(|r| r.id > id && !r.plan.packages.changes.is_empty())
    {
        return Err("stale transaction cannot be confirmed after a later update".into());
    }
    Ok(())
}

/// Run before offline rollback changes the root. History remains on @log.
pub fn validate_rollback_target(
    records: &[TransactionRecord],
    transaction_id: Option<&str>,
    snapshot: &str,
) -> Result<()> {
    let Some(id) = transaction_id else {
        return Ok(());
    };
    let id = id
        .parse::<i64>()
        .map_err(|_| "invalid snapshot transaction ID")?;
    let record = records
        .iter()
        .find(|r| r.id == id)
        .ok_or("snapshot transaction history missing")?;
    ensure_not_stale(records, id)?;
    if record.snapshot.as_deref() != Some(snapshot)
        || !(record.state.mutation_possible() || record.state == TransactionState::Succeeded)
    {
        return Err("target is not an eligible transaction pre-update snapshot".into());
    }
    Ok(())
}

pub fn confirm(
    session: &mut UpdateSession,
    id: i64,
    rollback: bool,
    evidence: &mut impl BootEvidence,
) -> Result<TransactionRecord> {
    session.recover_interrupted()?;
    let records = session.records()?;
    let mut record = records
        .iter()
        .find(|r| r.id == id)
        .ok_or("transaction does not exist")?
        .clone();
    let terminal = if rollback {
        TransactionState::RolledBack
    } else {
        TransactionState::Succeeded
    };
    if record.state == terminal
        && record
            .confirmation
            .as_ref()
            .is_some_and(|c| c.error.is_none() && c.rollback == rollback)
    {
        return Ok(record); // Idempotent retry after durable completion, not new health evidence.
    }
    ensure_not_stale(&records, id)?;
    if !matches!(
        (rollback, record.state),
        (false, TransactionState::AwaitingBoot)
            | (
                true,
                TransactionState::AwaitingBoot
                    | TransactionState::RollbackRequired
                    | TransactionState::Succeeded
            )
    ) {
        return Err("transaction is not eligible for this confirmation".into());
    }
    let reference = if rollback {
        &record.snapshot
    } else {
        &record.post_snapshot
    }
    .clone()
    .ok_or("missing generation snapshot")?;
    let mut observation = BootConfirmation {
        boot_id: String::new(),
        snapshot: reference.clone(),
        rollback,
        checks: vec![],
        error: None,
    };
    let result = (|| -> Result<()> {
        observation.boot_id = evidence.boot_id()?;
        if record
            .update_boot_id
            .as_ref()
            .is_none_or(|id| *id == observation.boot_id)
        {
            return Err("a different kernel boot is required; update remains unconfirmed".into());
        }
        evidence.verify(&reference, id, rollback)?;
        let expected = if rollback {
            record.plan.current.clone()
        } else {
            record.plan.expected_state()
        };
        if evidence.current_state()? != expected {
            return Err("booted package state differs from intended generation".into());
        }
        observation.checks = evidence.health(&record.plan);
        if !health_acceptable(&observation.checks) {
            return Err("post-boot health checks did not pass".into());
        }
        Ok(())
    })();
    observation.error = result.as_ref().err().cloned();
    record.boot_attempts.push(observation.clone());
    record.confirmation = Some(observation);
    session.save(&record)?; // Evidence survives a crash between promotion and finalization.
    result?; // Failures remain pending and block further updates; retry requires fresh evidence.
    if !rollback {
        evidence.promote(
            &reference,
            &format!(
                "Transaction {id}: verified boot {}, root, UKI, package map and required services",
                record.confirmation.as_ref().unwrap().boot_id
            ),
        )?;
    }
    if rollback && record.state != TransactionState::RollbackRequired {
        // A verified restoration is the only path allowed from a previously successful update.
        session.advance(&mut record, TransactionState::RollbackRequired)?;
    }
    session.advance(&mut record, terminal)?;
    Ok(record)
}
