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
            id: format!("sha256:{}", crate::hex(&Sha256::digest(bytes))),
            packages,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DesiredUpdate {
    SystemUpgrade,
    ManagedSystem,
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub management: Option<crate::ManagementPlan>,
}

impl ExecutionPlan {
    pub fn validate(&self) -> Result<()> {
        distro_graphics::validate_update(&self.current.packages, &self.expected_state().packages)?;
        if self.boot.update_bootloader
            || self.packages.changes.iter().any(|c| c.name() == "systemd")
        {
            return Err("systemd/bootloader updates are unsupported until loader binaries can be restored with the root; entire plan rejected".into());
        }
        if self
            .packages
            .changes
            .iter()
            .any(|c| c.name() == "distroctl")
        {
            // shortcut: reject self-updates until signing can authenticate a replaced coordinator executable.
            return Err("distroctl self-updates are unsupported until coordinator authorization survives executable replacement; entire plan rejected".into());
        }
        if !matches!(
            (self.schema_version, &self.management, self.desired),
            (1, None, DesiredUpdate::SystemUpgrade) | (2, Some(_), DesiredUpdate::ManagedSystem)
        ) || self.current != CurrentSystemState::new(self.current.packages.clone())
        {
            return Err("invalid plan schema or current-state identifier".into());
        }
        let mut names = BTreeSet::new();
        let mut expected_targets = BTreeMap::new();
        for change in &self.packages.changes {
            if !distro_config::valid_package_name(change.name()) {
                return Err("invalid package name in transaction".into());
            }
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
            if !distro_config::valid_package_name(&t.repository)
                || t.version.is_empty()
                || t.version.len() > 256
                || t.version
                    .chars()
                    .any(|character| character.is_whitespace() || character.is_control())
                || t.sha256.len() != 64
                || !t
                    .sha256
                    .bytes()
                    .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
            {
                return Err("invalid package target identity");
            }
            sum.checked_add(t.archive_bytes)
                .ok_or("download size overflow")
        })?;
        if targets.len() != self.packages.targets.len()
            || targets != expected_targets
            || total != self.packages.download_bytes
        {
            return Err("package targets or download total disagree with changes".into());
        }
        if self.has_mutation() && (!self.snapshot_required || !self.boot.regenerate_uki) {
            return Err("system mutation requires a snapshot and boot regeneration".into());
        }
        if let Some(management) = &self.management {
            management.validate(&self.current, &self.expected_state())?;
            let candidate = self.expected_state();
            for family in ["amd", "intel", "nouveau", "virtio", "software"] {
                for name in distro_graphics::bundle_packages(Some(family)) {
                    if self.current.packages.contains_key(&name)
                        != candidate.packages.contains_key(&name)
                    {
                        return Err("graphics-stack installation, removal and driver-family changes are outside the qualified managed-system scope".into());
                    }
                }
            }
            if self.packages.changes.iter().any(|change| {
                matches!(
                    change.name(),
                    "linux"
                        | "linux-headers"
                        | "linux-lts"
                        | "linux-lts-headers"
                        | "linux-zen"
                        | "linux-zen-headers"
                        | "linux-hardened"
                        | "linux-hardened-headers"
                        | "linux-rt"
                        | "linux-rt-headers"
                        | "linux-rt-lts"
                        | "linux-rt-lts-headers"
                )
            }) {
                return Err("kernel changes are outside the qualified managed-system transaction scope; entire plan rejected".into());
            }
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
                update_bootloader: false,
            },
            packages,
            snapshot_required: changed,
            management: None,
            notes: vec![
                "Uses existing sync databases; does not refresh repositories.".into(),
                "Boot regeneration is conservative for every nonempty update.".into(),
                "Loader binaries are not updated; plans changing systemd are rejected.".into(),
                "Plans changing distroctl are rejected until coordinator self-updates are supported.".into(),
            ],
        }
    }

    pub fn with_management(mut self, management: crate::ManagementPlan) -> Self {
        self.schema_version = 2;
        self.desired = DesiredUpdate::ManagedSystem;
        self.management = Some(management);
        self.snapshot_required = self.has_mutation();
        self.boot.regenerate_uki = self.has_mutation();
        self
    }

    pub fn has_mutation(&self) -> bool {
        !self.packages.changes.is_empty()
            || self
                .management
                .as_ref()
                .is_some_and(crate::ManagementPlan::has_mutation)
    }

    pub fn fingerprint(&self) -> String {
        let mut canonical = self.clone();
        canonical
            .packages
            .changes
            .sort_by(|a, b| a.name().cmp(b.name()));
        canonical
            .packages
            .targets
            .sort_by(|a, b| a.name.cmp(&b.name));
        canonical.notes.clear();
        let bytes = serde_json::to_vec(&canonical).expect("execution plan serializes");
        format!("sha256:{}", crate::hex(&Sha256::digest(bytes)))
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub operation_id: Option<String>,
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
    #[serde(default)]
    pub boot_count: Option<distro_snapshots::generations::BootCount>,
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
            schema_version: 2,
            id: 0,
            operation_id: None,
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
            && self.plan.has_mutation()
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
