//! Pure ownership reconciliation. Filesystem persistence belongs to the coordinator.
use crate::{CurrentSystemState, Result};
use distro_config::{valid_package_name, SystemConfig};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

pub const MANAGEMENT_ROOT: &str = "/var/lib/astraeus/management";
pub const CONFIG_PATH: &str = "/etc/astraeus/system.toml";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InstallReason {
    Explicit,
    Dependency,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ManagedPackage {
    pub version: String,
    pub reason: InstallReason,
    pub owners: BTreeSet<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LockedPackage {
    pub version: String,
    pub repository: String,
    pub sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ManagementState {
    pub schema_version: u32,
    pub applied: SystemConfig,
    pub packages: BTreeMap<String, ManagedPackage>,
    pub protected: BTreeSet<String>,
    pub repositories: BTreeMap<String, String>,
    #[serde(default)]
    pub resolution: BTreeMap<String, LockedPackage>,
    #[serde(default)]
    pub resolved_providers: BTreeMap<String, String>,
}

impl Default for ManagementState {
    fn default() -> Self {
        Self {
            schema_version: 1,
            applied: SystemConfig::default(),
            packages: BTreeMap::new(),
            protected: BTreeSet::new(),
            repositories: BTreeMap::new(),
            resolution: BTreeMap::new(),
            resolved_providers: BTreeMap::new(),
        }
    }
}

impl ManagementState {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != 1 {
            return Err("unsupported management state schema".into());
        }
        if self.resolved_providers.iter().any(|(dependency, package)| {
            !valid_package_name(dependency) || !valid_package_name(package)
        }) {
            return Err("invalid recorded provider selection".into());
        }
        let requested = self.applied.request_owners()?;
        for name in self.packages.keys().chain(&self.protected) {
            if !valid_package_name(name) {
                return Err("management state contains an invalid package name".into());
            }
        }
        for (name, package) in &self.packages {
            if self.protected.contains(name)
                || package.version.is_empty()
                || package.version.len() > 256
                || package.version.chars().any(char::is_whitespace)
                || package.version.chars().any(char::is_control)
                || package.owners != requested.get(name).cloned().unwrap_or_default()
            {
                return Err(format!("invalid ownership receipt for {name}"));
            }
        }
        for (repository, identity) in &self.repositories {
            let hash = identity.strip_prefix("sha256:").unwrap_or(identity);
            if !valid_package_name(repository)
                || hash.len() != 64
                || !hash
                    .bytes()
                    .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
            {
                return Err("invalid repository identity in management state".into());
            }
        }
        for (name, package) in &self.resolution {
            if !valid_package_name(name)
                || !self.repositories.contains_key(&package.repository)
                || package.version.is_empty()
                || package.version.len() > 256
                || package
                    .version
                    .chars()
                    .any(|c| c.is_control() || c.is_whitespace())
                || package.sha256.len() != 64
                || !package
                    .sha256
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
            {
                return Err("invalid resolved package identity".into());
            }
        }
        Ok(())
    }

    pub fn digest(&self) -> String {
        management_digest(Some(self))
    }
}

pub fn management_digest(state: Option<&ManagementState>) -> String {
    let bytes = serde_json::to_vec(&state).expect("management state serializes");
    format!("sha256:{:x}", Sha256::digest(bytes))
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ManagementPlan {
    pub before: Option<ManagementState>,
    pub after: ManagementState,
    pub before_digest: String,
    pub after_digest: String,
    pub reasons_before: BTreeMap<String, InstallReason>,
    pub reasons_after: BTreeMap<String, InstallReason>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub removal_integrity: Option<String>,
}

fn reasons_match(state: &CurrentSystemState, reasons: &BTreeMap<String, InstallReason>) -> bool {
    state.packages.keys().eq(reasons.keys())
}

pub fn removal_candidates(
    before: &ManagementState,
    current: &CurrentSystemState,
    reasons: &BTreeMap<String, InstallReason>,
    desired: &SystemConfig,
) -> Result<BTreeSet<String>> {
    before.validate()?;
    if !reasons_match(current, reasons) {
        return Err("complete installed package reasons are required".into());
    }
    let requested = desired.requested_packages()?;
    Ok(before
        .packages
        .iter()
        .filter(|(name, package)| {
            !package.owners.is_empty()
                && !requested.contains(*name)
                && !before.protected.contains(*name)
                && current.packages.get(*name) == Some(&package.version)
                && reasons.get(*name) == Some(&package.reason)
        })
        .map(|(name, _)| name.clone())
        .collect())
}

// The native resolver supplies complete before/after observations, never guessed dependencies.
#[allow(clippy::too_many_arguments)]
pub fn reconcile(
    before: Option<&ManagementState>,
    current: &CurrentSystemState,
    reasons_before: &BTreeMap<String, InstallReason>,
    resolved: &CurrentSystemState,
    reasons_after: &BTreeMap<String, InstallReason>,
    desired: &SystemConfig,
    protected: &BTreeSet<String>,
    repositories: &BTreeMap<String, String>,
) -> Result<ManagementPlan> {
    desired.validate()?;
    if !reasons_match(current, reasons_before) || !reasons_match(resolved, reasons_after) {
        return Err("complete installed package reasons are required".into());
    }
    if let Some(before) = before {
        before.validate()?;
    }
    let owners = desired.request_owners()?;
    if owners
        .keys()
        .any(|name| !resolved.packages.contains_key(name))
    {
        return Err("resolved package state does not satisfy the requested configuration".into());
    }
    let allowed_removals = match before {
        Some(before) => removal_candidates(before, current, reasons_before, desired)?,
        None => BTreeSet::new(),
    };
    let mut after = ManagementState {
        applied: desired.clone(),
        protected: protected.clone(),
        repositories: repositories.clone(),
        ..ManagementState::default()
    };
    if let Some(before) = before {
        after.protected.extend(before.protected.iter().cloned());
        after.resolution = before
            .resolution
            .iter()
            .filter(|(name, package)| resolved.packages.get(*name) == Some(&package.version))
            .map(|(name, package)| (name.clone(), package.clone()))
            .collect();
        after.resolved_providers = before
            .resolved_providers
            .iter()
            .filter(|(_, package)| resolved.packages.contains_key(*package))
            .map(|(dependency, package)| (dependency.clone(), package.clone()))
            .collect();
    }
    for name in current.packages.keys() {
        if !resolved.packages.contains_key(name)
            && (!allowed_removals.contains(name) || after.protected.contains(name))
        {
            return Err(format!(
                "removal of unowned, protected or externally changed package {name} refused"
            ));
        }
    }
    for (name, version) in &resolved.packages {
        let previous = before.and_then(|state| state.packages.get(name));
        let unchanged = previous.is_some_and(|package| {
            current.packages.get(name) == Some(&package.version)
                && reasons_before.get(name) == Some(&package.reason)
        });
        let introduced = !current.packages.contains_key(name);
        if (introduced || unchanged) && !after.protected.contains(name) {
            after.packages.insert(
                name.clone(),
                ManagedPackage {
                    version: version.clone(),
                    reason: reasons_after[name],
                    owners: owners.get(name).cloned().unwrap_or_default(),
                },
            );
        } else {
            // External packages and externally changed receipts never become removal authority.
            after.protected.insert(name.clone());
        }
    }
    let plan = ManagementPlan {
        before: before.cloned(),
        before_digest: management_digest(before),
        after_digest: after.digest(),
        after,
        reasons_before: reasons_before.clone(),
        reasons_after: reasons_after.clone(),
        removal_integrity: None,
    };
    plan.validate(current, resolved)?;
    Ok(plan)
}

impl ManagementPlan {
    pub fn has_mutation(&self) -> bool {
        self.before_digest != self.after_digest || self.reasons_before != self.reasons_after
    }

    pub fn validate(
        &self,
        current: &CurrentSystemState,
        resolved: &CurrentSystemState,
    ) -> Result<()> {
        if self
            .removal_integrity
            .as_ref()
            .is_some_and(|digest| !crate::package_integrity::valid_digest(digest))
        {
            return Err("invalid removal integrity identity".into());
        }
        if let Some(before) = &self.before {
            before.validate()?;
        }
        self.after.validate()?;
        if self.before_digest != management_digest(self.before.as_ref())
            || self.after_digest != self.after.digest()
            || !reasons_match(current, &self.reasons_before)
            || !reasons_match(resolved, &self.reasons_after)
        {
            return Err("management identity or package reasons disagree with the plan".into());
        }
        if self
            .after
            .applied
            .requested_packages()?
            .iter()
            .any(|name| !resolved.packages.contains_key(name))
        {
            return Err("resolved state is missing a requested package".into());
        }
        if self
            .after
            .resolution
            .iter()
            .any(|(name, package)| resolved.packages.get(name) != Some(&package.version))
        {
            return Err("system.lock version disagrees with resolved state".into());
        }
        if self
            .after
            .resolved_providers
            .values()
            .any(|package| !resolved.packages.contains_key(package))
        {
            return Err("recorded provider is absent from the resolved system".into());
        }
        if let Some(before) = &self.before {
            if !before.protected.is_subset(&self.after.protected) {
                return Err("protected package ownership cannot be taken over".into());
            }
        }
        let removals = match &self.before {
            Some(before) => {
                removal_candidates(before, current, &self.reasons_before, &self.after.applied)?
            }
            None => BTreeSet::new(),
        };
        for name in current.packages.keys() {
            if !resolved.packages.contains_key(name)
                && (!removals.contains(name) || self.after.protected.contains(name))
            {
                return Err(format!("unapproved removal of {name}"));
            }
            if resolved.packages.contains_key(name)
                && !self.after.packages.contains_key(name)
                && self.reasons_before.get(name) != self.reasons_after.get(name)
            {
                return Err(format!(
                    "install reason of externally owned package {name} must be preserved"
                ));
            }
        }
        for (name, package) in &self.after.packages {
            if resolved.packages.get(name) != Some(&package.version)
                || self.reasons_after.get(name) != Some(&package.reason)
            {
                return Err(format!(
                    "ownership receipt does not match resolved package {name}"
                ));
            }
            if current.packages.contains_key(name)
                && !self
                    .before
                    .as_ref()
                    .and_then(|state| state.packages.get(name))
                    .is_some_and(|previous| {
                        current.packages.get(name) == Some(&previous.version)
                            && self.reasons_before.get(name) == Some(&previous.reason)
                    })
            {
                return Err(format!(
                    "ownership takeover of existing package {name} refused"
                ));
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state(names: &[&str]) -> CurrentSystemState {
        CurrentSystemState::new(
            names
                .iter()
                .map(|name| (name.to_string(), "1-1".into()))
                .collect(),
        )
    }
    fn reasons(state: &CurrentSystemState) -> BTreeMap<String, InstallReason> {
        state
            .packages
            .keys()
            .map(|name| (name.clone(), InstallReason::Explicit))
            .collect()
    }
    fn requested(names: &[&str]) -> SystemConfig {
        SystemConfig {
            packages: names.iter().map(|name| name.to_string()).collect(),
            ..SystemConfig::default()
        }
    }
    fn make(
        before: Option<&ManagementState>,
        current: &CurrentSystemState,
        after: &CurrentSystemState,
        desired: &SystemConfig,
    ) -> ManagementPlan {
        reconcile(
            before,
            current,
            &reasons(current),
            after,
            &reasons(after),
            desired,
            &BTreeSet::new(),
            &BTreeMap::new(),
        )
        .unwrap()
    }

    #[test]
    fn preexisting_apps_are_preserved_while_new_requests_are_owned() {
        let current = state(&["manual"]);
        let installed = state(&["manual", "new-app", "new-dependency"]);
        let first = make(
            None,
            &current,
            &installed,
            &requested(&["manual", "new-app"]),
        );
        assert!(first.after.protected.contains("manual"));
        assert!(!first.after.packages.contains_key("manual"));
        assert!(first.after.packages["new-dependency"].owners.is_empty());
        let removals = removal_candidates(
            &first.after,
            &installed,
            &reasons(&installed),
            &SystemConfig::default(),
        )
        .unwrap();
        assert_eq!(removals, BTreeSet::from(["new-app".into()]));
        let after = state(&["manual", "new-dependency"]);
        make(
            Some(&first.after),
            &installed,
            &after,
            &SystemConfig::default(),
        );
        assert!(reconcile(
            Some(&first.after),
            &installed,
            &reasons(&installed),
            &state(&[]),
            &BTreeMap::new(),
            &SystemConfig::default(),
            &BTreeSet::new(),
            &BTreeMap::new()
        )
        .is_err());
    }

    #[test]
    fn external_reason_or_version_changes_relinquish_ownership() {
        let empty = state(&[]);
        let installed = state(&["app"]);
        let first = make(None, &empty, &installed, &requested(&["app"]));
        let mut changed_reasons = reasons(&installed);
        changed_reasons.insert("app".into(), InstallReason::Dependency);
        let changed = reconcile(
            Some(&first.after),
            &installed,
            &changed_reasons,
            &installed,
            &changed_reasons,
            &SystemConfig::default(),
            &BTreeSet::new(),
            &BTreeMap::new(),
        )
        .unwrap();
        assert!(changed.after.packages.is_empty());
        assert!(changed.after.protected.contains("app"));
        assert!(reconcile(
            None,
            &installed,
            &changed_reasons,
            &installed,
            &reasons(&installed),
            &requested(&["app"]),
            &BTreeSet::new(),
            &BTreeMap::new(),
        )
        .is_err());
        let mut upgraded = installed.clone();
        upgraded.packages.insert("app".into(), "2-1".into());
        upgraded = CurrentSystemState::new(upgraded.packages);
        assert!(removal_candidates(
            &first.after,
            &upgraded,
            &reasons(&upgraded),
            &SystemConfig::default()
        )
        .unwrap()
        .is_empty());
    }

    #[test]
    fn shared_requests_idempotence_and_tampering_are_checked() {
        let empty = state(&[]);
        let installed = state(&["mangohud", "lib32-mangohud"]);
        let desired = SystemConfig {
            gaming: BTreeSet::from(["mangohud".into()]),
            ..SystemConfig::default()
        };
        let first = make(None, &empty, &installed, &desired);
        let again = make(Some(&first.after), &installed, &installed, &desired);
        assert!(!again.has_mutation());
        let mut retained = desired.clone();
        retained.packages.insert("mangohud".into());
        retained.gaming.clear();
        assert_eq!(
            removal_candidates(&first.after, &installed, &reasons(&installed), &retained).unwrap(),
            BTreeSet::from(["lib32-mangohud".into()])
        );
        let mut tampered = again.clone();
        tampered.after_digest = "sha256:wrong".into();
        assert!(tampered.validate(&installed, &installed).is_err());
        let mut takeover = make(None, &installed, &installed, &desired);
        takeover.after.protected.clear();
        takeover.after.packages = first.after.packages;
        takeover.after_digest = takeover.after.digest();
        assert!(takeover.validate(&installed, &installed).is_err());
    }
}
