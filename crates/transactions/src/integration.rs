//! Coordination with the existing Btrfs manager. One guard covers the entire update.
use crate::{pacman::*, *};
use distro_snapshots::generations::{Generation, RootKind, Selection};
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
        if self.manager.generations_enabled().map_err(error)? {
            self.manager.generation_prerequisites().map_err(error)?;
        } else if self
            .manager
            .generation_selection()
            .map_err(error)?
            .is_some()
        {
            return Err("managed boot selection exists but generation mode was disabled".into());
        }
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
    fn prepare_boot_baseline(&mut self, reference: &str) -> Result<()> {
        if self.manager.generations_enabled().map_err(error)? {
            let previous = self
                .manager
                .stage_generation_locked(
                    &self.guard,
                    &SnapshotId::parse(reference).map_err(error)?,
                    None,
                )
                .map_err(error)?;
            self.manager
                .select_generation_locked(
                    &self.guard,
                    Selection {
                        schema_version: 1,
                        current: None,
                        previous: previous.id,
                    },
                )
                .map_err(error)?;
        }
        Ok(())
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
    fn activate_boot(&mut self, reference: &str) -> Result<()> {
        if !self.manager.generations_enabled().map_err(error)? {
            return Ok(());
        }
        let selection = self
            .manager
            .generation_selection()
            .map_err(error)?
            .ok_or("missing retained baseline")?;
        let generation = self
            .manager
            .stage_generation_locked(
                &self.guard,
                &SnapshotId::parse(reference).map_err(error)?,
                Some(selection.previous.clone()),
            )
            .map_err(error)?;
        self.manager
            .select_generation_locked(
                &self.guard,
                Selection {
                    schema_version: 1,
                    current: Some(generation.id),
                    previous: selection.previous,
                },
            )
            .map_err(error)
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
    fn boot_count(
        &mut self,
        _snapshot: &str,
    ) -> Result<Option<distro_snapshots::generations::BootCount>> {
        Ok(None)
    }
    fn boot_id(&mut self) -> Result<String>;
    fn verify(&mut self, snapshot: &str, transaction_id: i64, rollback: bool) -> Result<()>;
    fn current_state(&mut self) -> Result<CurrentSystemState>;
    fn health(&mut self, plan: &ExecutionPlan) -> Vec<HealthCheckResult>;
    fn promote(&mut self, snapshot: &str, evidence: &str) -> Result<()>;
}
impl BootEvidence for BtrfsSnapshots {
    fn boot_count(
        &mut self,
        snapshot: &str,
    ) -> Result<Option<distro_snapshots::generations::BootCount>> {
        if self
            .manager
            .generation_selection()
            .map_err(error)?
            .is_none()
        {
            return Ok(None);
        }
        self.manager
            .generation_counter(
                &distro_snapshots::generations::GenerationId::parse(snapshot).map_err(error)?,
            )
            .map(|c| c.map(|(_, count)| count))
            .map_err(error)
    }
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
        self.manager.verify_booted(&sid, rollback).map_err(error)?;
        if !rollback
            && self
                .manager
                .generation_selection()
                .map_err(error)?
                .is_some()
        {
            let generation = self
                .manager
                .verify_generation(
                    &distro_snapshots::generations::GenerationId::parse(reference)
                        .map_err(error)?,
                )
                .map_err(error)?;
            if self
                .manager
                .selected_generation()
                .map_err(error)?
                .is_none_or(|g| g.id != generation.id)
            {
                return Err("bootloader did not select the expected candidate".into());
            }
            self.manager
                .verify_running_generation(&generation)
                .map_err(error)?;
        }
        Ok(())
    }
    fn current_state(&mut self) -> Result<CurrentSystemState> {
        Pacman::default().current_state()
    }
    fn health(&mut self, plan: &ExecutionPlan) -> Vec<HealthCheckResult> {
        system_health().run(plan)
    }
    fn promote(&mut self, reference: &str, evidence: &str) -> Result<()> {
        self.manager
            .bless_generation_locked(&self.guard, &SnapshotId::parse(reference).map_err(error)?)
            .map_err(error)?;
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

/// No filename or snapshot health label can substitute for the owning transaction.
pub fn validate_generation_reference(
    records: &[TransactionRecord],
    generation: &Generation,
    snapshot: &distro_snapshots::Snapshot,
) -> Result<()> {
    generation.validate().map_err(error)?;
    snapshot.validate().map_err(error)?;
    let id: i64 = snapshot
        .transaction_id
        .as_deref()
        .ok_or("generation has no transaction")?
        .parse()
        .map_err(error)?;
    let record = records
        .iter()
        .find(|r| r.id == id)
        .ok_or("generation transaction is missing")?;
    ensure_not_stale(records, id)?;
    let expected = match generation.root_kind {
        RootKind::Current => &record.post_snapshot,
        RootKind::Retained => &record.snapshot,
    };
    if generation.snapshot != snapshot.id || expected.as_deref() != Some(snapshot.id.as_str()) {
        return Err("generation is not the transaction's recorded snapshot".into());
    }
    match generation.root_kind {
        RootKind::Current
            if matches!(
                record.state,
                TransactionState::AwaitingBoot | TransactionState::Succeeded
            ) && matches!(snapshot.health, Health::Candidate | Health::KnownGood) =>
        {
            Ok(())
        }
        RootKind::Retained
            if snapshot.health == Health::KnownGood
                && record.state != TransactionState::RolledBack =>
        {
            Ok(())
        }
        _ => Err("generation transaction is not eligible".into()),
    }
}

/// A boot of the retained root is recovery evidence, never a completed offline restore.
pub fn record_fallback(
    session: &mut UpdateSession,
    generation: &Generation,
    snapshot: &distro_snapshots::Snapshot,
    boot: String,
) -> Result<TransactionRecord> {
    session.recover_interrupted()?;
    let records = session.records()?;
    validate_generation_reference(&records, generation, snapshot)?;
    if generation.root_kind != RootKind::Retained {
        return Err("not a retained recovery root".into());
    }
    let id: i64 = snapshot
        .transaction_id
        .as_deref()
        .ok_or("missing transaction")?
        .parse()
        .map_err(error)?;
    let mut record = records
        .into_iter()
        .find(|r| r.id == id)
        .ok_or("missing transaction")?;
    if !record
        .boot_attempts
        .iter()
        .any(|a| a.boot_id == boot && a.snapshot == snapshot.id.as_str())
    {
        record.boot_attempts.push(BootConfirmation { boot_count: None, boot_id: boot, snapshot: snapshot.id.as_str().into(), rollback: false, checks: vec![], error: Some("Booted retained known-good recovery root; offline restoration and finalize-rollback still required".into()) });
        session.save(&record)?;
    }
    Ok(record)
}

/// Run before offline rollback changes the root. History remains on @log.
/// Accepts mutation_possible states too: a killed updater never reaches recover_interrupted.
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
        || !(record.state == TransactionState::Succeeded || record.state.mutation_possible())
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
        boot_count: None,
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
        observation.boot_count = evidence.boot_count(&reference)?;
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
        if let Err(message) = evidence.promote(
            &reference,
            &format!(
                "Transaction {id}: verified boot {}, root, UKI, package map and required services",
                record.confirmation.as_ref().unwrap().boot_id
            ),
        ) {
            record.confirmation.as_mut().unwrap().error = Some(message.clone());
            record.boot_attempts.last_mut().unwrap().error = Some(message.clone());
            session.save(&record)?;
            return Err(message);
        }
    }
    if rollback && record.state != TransactionState::RollbackRequired {
        // A verified restoration is the only path allowed from a previously successful update.
        session.advance(&mut record, TransactionState::RollbackRequired)?;
    }
    session.advance(&mut record, terminal)?;
    Ok(record)
}
