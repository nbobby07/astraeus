use crate::Result;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CurrentSystemState {
    /// SHA-256 of the canonical package/version map, not a filesystem generation ID.
    pub id: String,
    pub packages: BTreeMap<String, String>,
}

impl CurrentSystemState {
    pub fn new(packages: BTreeMap<String, String>) -> Self {
        let bytes = serde_json::to_vec(&packages).expect("string map serializes");
        Self {
            id: format!("sha256:{:x}", Sha256::digest(bytes)),
            packages,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesiredUpdate {
    SystemUpgrade,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum PackageChange {
    Install {
        name: String,
        version: String,
    },
    Upgrade {
        name: String,
        from: String,
        to: String,
    },
    Remove {
        name: String,
        version: String,
    },
}

impl PackageChange {
    pub fn name(&self) -> &str {
        match self {
            Self::Install { name, .. } | Self::Upgrade { name, .. } | Self::Remove { name, .. } => {
                name
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PackageTarget {
    pub name: String,
    pub version: String,
    pub repository: String,
    pub archive_bytes: u64,
    pub installed_bytes: u64,
    pub sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PackagePlan {
    pub changes: Vec<PackageChange>,
    pub targets: Vec<PackageTarget>,
    /// Upper bound: includes archives already present in the cache.
    pub download_bytes: u64,
    /// None when the selected backend cannot observe installed sizes before download.
    pub installed_delta_bytes: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BootArtifacts {
    pub regenerate_uki: bool,
    pub update_bootloader: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ExecutionPlan {
    pub schema_version: u32,
    pub current: CurrentSystemState,
    pub desired: DesiredUpdate,
    pub packages: PackagePlan,
    pub boot: BootArtifacts,
    pub snapshot_required: bool,
    pub notes: Vec<String>,
}

impl ExecutionPlan {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != 1
            || self.current != CurrentSystemState::new(self.current.packages.clone())
        {
            return Err("invalid plan schema or current-state identifier".into());
        }
        let mut names = BTreeSet::new();
        let mut expected_targets = BTreeMap::new();
        for change in &self.packages.changes {
            if !names.insert(change.name()) {
                return Err("duplicate package change".into());
            }
            match change {
                PackageChange::Install { name, version } => {
                    if self.current.packages.contains_key(name) {
                        return Err("install target already installed".into());
                    }
                    expected_targets.insert(name, version);
                }
                PackageChange::Upgrade { name, from, to } => {
                    if self.current.packages.get(name) != Some(from) {
                        return Err("upgrade has incorrect previous version".into());
                    }
                    expected_targets.insert(name, to);
                }
                PackageChange::Remove { name, version } => {
                    if self.current.packages.get(name) != Some(version) {
                        return Err("removal has incorrect previous version".into());
                    }
                }
            }
        }
        let targets: BTreeMap<_, _> = self
            .packages
            .targets
            .iter()
            .map(|t| (&t.name, &t.version))
            .collect();
        let total = self.packages.targets.iter().try_fold(0u64, |sum, t| {
            sum.checked_add(t.archive_bytes)
                .ok_or("download size overflow")
        })?;
        if targets.len() != self.packages.targets.len()
            || targets != expected_targets
            || total != self.packages.download_bytes
        {
            return Err("package targets or download total disagree with changes".into());
        }
        if !self.packages.changes.is_empty() && !self.snapshot_required {
            return Err("package mutation requires a snapshot".into());
        }
        Ok(())
    }

    pub fn new(current: CurrentSystemState, packages: PackagePlan) -> Self {
        let changed = !packages.changes.is_empty();
        Self {
            schema_version: 1,
            current,
            desired: DesiredUpdate::SystemUpgrade,
            boot: BootArtifacts {
                regenerate_uki: changed,
                update_bootloader: changed,
            },
            packages,
            snapshot_required: changed,
            notes: vec![
                "Uses existing sync databases; does not refresh repositories.".into(),
                "Boot regeneration is conservative for every nonempty update.".into(),
            ],
        }
    }

    pub fn expected_state(&self) -> CurrentSystemState {
        let mut packages = self.current.packages.clone();
        for change in &self.packages.changes {
            match change {
                PackageChange::Install { name, version } => {
                    packages.insert(name.clone(), version.clone());
                }
                PackageChange::Upgrade { name, to, .. } => {
                    packages.insert(name.clone(), to.clone());
                }
                PackageChange::Remove { name, .. } => {
                    packages.remove(name);
                }
            }
        }
        CurrentSystemState::new(packages)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TransactionState {
    Planned,
    Preparing,
    Downloaded,
    SnapshotPending,
    SnapshotCreated,
    Applying,
    Validating,
    AwaitingBoot,
    Succeeded,
    Failed,
    RollbackRequired,
    RolledBack,
}

impl TransactionState {
    pub fn can_transition(self, next: Self) -> bool {
        use TransactionState::*;
        matches!(
            (self, next),
            (Planned, Preparing | Succeeded | Failed)
                | (Preparing, Downloaded | Failed)
                | (Downloaded, SnapshotPending | Failed)
                | (SnapshotPending, SnapshotCreated | Failed)
                | (SnapshotCreated, Applying | Failed)
                | (Applying, Validating | RollbackRequired)
                | (Validating, AwaitingBoot | RollbackRequired)
                | (AwaitingBoot, Succeeded | RollbackRequired)
                | (Succeeded, RollbackRequired)
                | (RollbackRequired, RolledBack)
        )
    }

    pub fn mutation_possible(self) -> bool {
        matches!(
            self,
            Self::Applying | Self::Validating | Self::AwaitingBoot | Self::RollbackRequired
        )
    }

    pub fn terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed | Self::RolledBack)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HealthStatus {
    Pass,
    Warn,
    Fail,
    Unavailable,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HealthCheckResult {
    pub name: String,
    pub status: HealthStatus,
    pub required: bool,
    pub detail: String,
}

pub fn health_acceptable(checks: &[HealthCheckResult]) -> bool {
    !checks.is_empty()
        && checks.iter().all(|c| {
            c.status != HealthStatus::Fail && (!c.required || c.status == HealthStatus::Pass)
        })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TransactionOutcome {
    InProgress,
    AwaitingBoot,
    Succeeded,
    Failed,
    RollbackRequired,
    RolledBack,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Failure {
    pub at: TransactionState,
    pub message: String,
    pub interrupted: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StateEvent {
    pub state: TransactionState,
    pub timestamp: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransactionRecord {
    pub schema_version: u32,
    pub id: i64,
    pub timestamp: u64,
    pub state: TransactionState,
    pub outcome: TransactionOutcome,
    pub plan: ExecutionPlan,
    pub snapshot: Option<String>,
    #[serde(default)]
    pub post_snapshot: Option<String>,
    #[serde(default)]
    pub update_boot_id: Option<String>,
    #[serde(default)]
    pub confirmation: Option<BootConfirmation>,
    #[serde(default)]
    pub boot_attempts: Vec<BootConfirmation>,
    pub previous_system_state: String,
    pub resulting_system_state: Option<String>,
    pub failure: Option<Failure>,
    pub health_checks: Vec<HealthCheckResult>,
    pub boot_regenerated: bool,
    pub events: Vec<StateEvent>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BootConfirmation {
    pub boot_id: String,
    pub snapshot: String,
    pub rollback: bool,
    pub checks: Vec<HealthCheckResult>,
    pub error: Option<String>,
}

pub(crate) fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

impl TransactionRecord {
    pub fn new(plan: ExecutionPlan) -> Self {
        let timestamp = now();
        Self {
            schema_version: 1,
            id: 0,
            timestamp,
            state: TransactionState::Planned,
            outcome: TransactionOutcome::InProgress,
            previous_system_state: plan.current.id.clone(),
            plan,
            snapshot: None,
            post_snapshot: None,
            update_boot_id: None,
            confirmation: None,
            boot_attempts: vec![],
            resulting_system_state: None,
            failure: None,
            health_checks: vec![],
            boot_regenerated: false,
            events: vec![StateEvent {
                state: TransactionState::Planned,
                timestamp,
            }],
        }
    }

    pub fn transition(&mut self, next: TransactionState) -> Result<()> {
        if self.state == TransactionState::Planned
            && next == TransactionState::Succeeded
            && !self.plan.packages.changes.is_empty()
        {
            return Err("only an empty transaction can succeed without execution".into());
        }
        if !self.state.can_transition(next) {
            return Err(format!("invalid transition {:?} -> {next:?}", self.state));
        }
        self.state = next;
        self.outcome = match next {
            TransactionState::Succeeded => TransactionOutcome::Succeeded,
            TransactionState::Failed => TransactionOutcome::Failed,
            TransactionState::RollbackRequired => TransactionOutcome::RollbackRequired,
            TransactionState::RolledBack => TransactionOutcome::RolledBack,
            TransactionState::AwaitingBoot => TransactionOutcome::AwaitingBoot,
            _ => TransactionOutcome::InProgress,
        };
        self.events.push(StateEvent {
            state: next,
            timestamp: now(),
        });
        Ok(())
    }
}
