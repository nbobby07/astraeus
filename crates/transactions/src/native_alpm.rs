//! The native resolver and committer share one prepared, locked libalpm transaction.
use crate::{management_store as store, *};
use alpm::{Alpm, Package, PackageReason, Question, SigLevel, TransFlag};
use distro_config::SystemConfig;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
    process::Command,
    rc::Rc,
};

#[cfg(test)]
#[path = "native_tests.rs"]
mod tests;

fn err(error: impl std::fmt::Display) -> String {
    error.to_string()
}
fn pattern_matches(pattern: &str, value: &str) -> bool {
    let (Ok(pattern), Ok(value)) = (
        std::ffi::CString::new(pattern),
        std::ffi::CString::new(value),
    ) else {
        return false;
    };
    unsafe { libc::fnmatch(pattern.as_ptr(), value.as_ptr(), 0) == 0 }
}
fn hash(path: &Path) -> Result<String> {
    use std::io::Read;
    store::trusted_directory(path.parent().ok_or("missing parent")?)?;
    let mut options = fs::OpenOptions::new();
    options.read(true);
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    let mut file = options
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)
        .map_err(err)?;
    let meta = file.metadata().map_err(err)?;
    if !meta.is_file() || meta.uid() != 0 || meta.mode() & 0o022 != 0 {
        return Err("untrusted repository input".into());
    }
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let count = file.read(&mut buffer).map_err(err)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("sha256:{:x}", digest.finalize()))
}
fn conf(args: &[&str]) -> Result<String> {
    let output = Command::new("/usr/bin/pacman-conf")
        .args(args)
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("LC_ALL", "C")
        .output()
        .map_err(err)?;
    if !output.status.success() {
        return Err(format!(
            "pacman-conf failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    if output.stdout.len() > 1024 * 1024 {
        return Err("oversized package configuration".into());
    }
    String::from_utf8(output.stdout).map_err(err)
}

#[derive(Clone)]
struct Repository {
    name: String,
    values: BTreeMap<String, Vec<String>>,
}
struct Configuration {
    options: BTreeMap<String, Vec<String>>,
    repositories: Vec<Repository>,
    digest: String,
}
impl Configuration {
    fn read() -> Result<Self> {
        let text = conf(&[])?;
        let mut out = Self {
            options: BTreeMap::new(),
            repositories: vec![],
            digest: format!("sha256:{:x}", Sha256::digest(text.as_bytes())),
        };
        let mut section = "options".to_string();
        for raw in text.lines() {
            let line = raw.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            if line.starts_with('[') && line.ends_with(']') {
                section = line[1..line.len() - 1].to_string();
                if section != "options" {
                    if !["distro", "core", "extra", "multilib"].contains(&section.as_str())
                        || out.repositories.iter().any(|r| r.name == section)
                    {
                        return Err("unsupported or duplicate package repository".into());
                    }
                    out.repositories.push(Repository {
                        name: section.clone(),
                        values: BTreeMap::new(),
                    });
                }
                continue;
            }
            let (key, value) = line
                .split_once('=')
                .map(|(k, v)| (k.trim(), v.trim()))
                .unwrap_or((line, ""));
            if key.is_empty() || value.contains('\0') {
                return Err("invalid package configuration".into());
            }
            let values = if section == "options" {
                &mut out.options
            } else {
                &mut out
                    .repositories
                    .last_mut()
                    .ok_or("repository section missing")?
                    .values
            };
            values
                .entry(key.to_string())
                .or_default()
                .push(value.to_string());
        }
        for (key, expected) in [
            ("RootDir", "/"),
            ("DBPath", "/var/lib/pacman"),
            ("CacheDir", "/var/cache/pacman/pkg"),
            ("GPGDir", "/etc/pacman.d/gnupg"),
            ("LogFile", "/var/log/pacman.log"),
        ] {
            let value = out.value(key)?;
            if value.trim_end_matches('/') != expected.trim_end_matches('/') {
                return Err(format!(
                    "unsupported {key}: standard installed layout required"
                ));
            }
        }
        if out.repositories.is_empty() {
            return Err("no approved repositories configured".into());
        }
        for key in [
            "XferCommand",
            "DisableSandbox",
            "DisableSandboxFilesystem",
            "DisableSandboxSyscalls",
        ] {
            if out.options.contains_key(key) {
                return Err(format!("unsupported unsafe pacman option {key}"));
            }
        }
        if out.words("Architecture") != ["x86_64"] {
            return Err("exactly the x86_64 architecture is required".into());
        }
        for repo in &out.repositories {
            if !repo.values.contains_key("Server") || repo.values.contains_key("CacheServer") {
                return Err(
                    "repository requires approved servers without a cache-server override".into(),
                );
            }
        }
        Ok(out)
    }
    fn value(&self, key: &str) -> Result<String> {
        match self.options.get(key).map(Vec::as_slice) {
            Some([value]) => Ok(value.clone()),
            _ => Err(format!("missing or multiple {key}")),
        }
    }
    fn words(&self, key: &str) -> Vec<String> {
        self.options
            .get(key)
            .into_iter()
            .flatten()
            .flat_map(|v| v.split_whitespace().map(str::to_string))
            .collect()
    }
    fn identities(&self) -> Result<BTreeMap<String, String>> {
        let mut ids = BTreeMap::from([("pacman-config".into(), self.digest.clone())]);
        let lock: serde_json::Value =
            serde_json::from_str(include_str!("../../../distro/repo/archive.lock.json"))
                .map_err(err)?;
        for repo in &self.repositories {
            let id = hash(&Path::new("/var/lib/pacman/sync").join(format!("{}.db", repo.name)))?;
            if repo.name != "distro"
                && lock["databases"][&repo.name].as_str() != id.strip_prefix("sha256:")
            {
                return Err(format!(
                    "{} database differs from the approved archive",
                    repo.name
                ));
            }
            ids.insert(repo.name.clone(), id);
            let sig = Path::new("/var/lib/pacman/sync").join(format!("{}.db.sig", repo.name));
            if sig.exists() {
                ids.insert(format!("{}-signature", repo.name), hash(&sig)?);
            }
        }
        Ok(ids)
    }
    fn handle(&self) -> Result<Alpm> {
        let mut handle = Alpm::new("/", "/var/lib/pacman").map_err(err)?;
        handle.set_logfile("/var/log/pacman.log").map_err(err)?;
        handle.set_gpgdir(self.value("GPGDir")?).map_err(err)?;
        handle.add_cachedir(self.value("CacheDir")?).map_err(err)?;
        handle.set_check_space(true);
        handle
            .set_default_siglevel(
                SigLevel::PACKAGE | SigLevel::DATABASE | SigLevel::DATABASE_OPTIONAL,
            )
            .map_err(err)?;
        handle
            .set_local_file_siglevel(SigLevel::PACKAGE)
            .map_err(err)?;
        handle
            .set_remote_file_siglevel(SigLevel::PACKAGE)
            .map_err(err)?;
        for arch in self.words("Architecture") {
            if arch != "x86_64" {
                return Err("only x86_64 package architecture is supported".into());
            }
            handle.add_architecture(arch).map_err(err)?;
        }
        for name in self.words("IgnorePkg") {
            handle.add_ignorepkg(name).map_err(err)?;
        }
        for name in self.words("IgnoreGroup") {
            handle.add_ignoregroup(name).map_err(err)?;
        }
        for name in self.words("NoUpgrade") {
            handle.add_noupgrade(name).map_err(err)?;
        }
        for name in self.words("NoExtract") {
            handle.add_noextract(name).map_err(err)?;
        }
        for path in self.words("HookDir") {
            store::trusted_directory(Path::new(&path))?;
            handle.add_hookdir(path).map_err(err)?;
        }
        if let Some(value) = self.options.get("DownloadUser") {
            if value.len() != 1 {
                return Err("invalid DownloadUser".into());
            }
            handle
                .set_sandbox_user(Some(value[0].clone()))
                .map_err(err)?;
        }
        if let Some(value) = self.options.get("ParallelDownloads") {
            handle.set_parallel_downloads(value[0].parse().map_err(err)?);
        }
        handle.set_log_cb((), |level, message, _| {
            if level.intersects(alpm::LogLevel::ERROR | alpm::LogLevel::WARNING) {
                eprint!("{message}");
            }
        });
        for repo in &self.repositories {
            let mut args = vec!["--repo", repo.name.as_str(), "SigLevel"];
            let mut policy = conf(&args)?;
            if policy.trim().is_empty() {
                args = vec!["SigLevel"];
                policy = conf(&args)?;
            }
            let words: Vec<_> = policy.split_whitespace().collect();
            if !words.contains(&"PackageRequired")
                || !words.contains(&"PackageTrustedOnly")
                || words.iter().any(|v| {
                    v.ends_with("TrustAll") || *v == "PackageOptional" || *v == "PackageNever"
                })
            {
                return Err(format!(
                    "{} must require trusted package signatures",
                    repo.name
                ));
            }
            if repo.name == "distro"
                && (!words.contains(&"DatabaseRequired") || !words.contains(&"DatabaseTrustedOnly"))
            {
                return Err("custom repository requires a trusted database signature".into());
            }
            let mut level = SigLevel::PACKAGE;
            if words.contains(&"DatabaseRequired") {
                level |= SigLevel::DATABASE;
            } else if words.contains(&"DatabaseOptional") {
                level |= SigLevel::DATABASE | SigLevel::DATABASE_OPTIONAL;
            } else {
                return Err("database verification must remain enabled".into());
            }
            let db = handle
                .register_syncdb_mut(repo.name.as_str(), level)
                .map_err(err)?;
            for server in repo.values.get("Server").into_iter().flatten() {
                let valid = if repo.name == "distro" {
                    server.trim_end_matches('/') == "file:///opt/distro/repo"
                } else {
                    server.trim_end_matches('/')
                        == format!(
                            "https://archive.archlinux.org/repos/2026/10/01/{}/os/x86_64",
                            repo.name
                        )
                };
                if !valid {
                    return Err(format!("unsupported server for {}", repo.name));
                }
                db.add_server(server.as_str()).map_err(err)?;
            }
            if repo.values.contains_key("Usage") && repo.values["Usage"].join(" ") != "All" {
                return Err("restricted repository Usage is unsupported".into());
            }
            db.is_valid()
                .map_err(|e| format!("{} database: {e}", repo.name))?;
        }
        Ok(handle)
    }
}

fn current(handle: &Alpm) -> CurrentSystemState {
    CurrentSystemState::new(
        handle
            .localdb()
            .pkgs()
            .iter()
            .map(|p| (p.name().into(), p.version().to_string()))
            .collect(),
    )
}
fn reason(package: &Package) -> InstallReason {
    if package.reason() == PackageReason::Explicit {
        InstallReason::Explicit
    } else {
        InstallReason::Dependency
    }
}
fn reasons(handle: &Alpm) -> BTreeMap<String, InstallReason> {
    handle
        .localdb()
        .pkgs()
        .iter()
        .map(|p| (p.name().into(), reason(p)))
        .collect()
}
fn provides_requirements(
    handle: &Alpm,
    selected: &Package,
    dependency: &str,
    consumers: &[&Package],
) -> bool {
    if selected.name() != dependency
        && !selected
            .provides()
            .iter()
            .any(|provided| provided.name() == dependency)
    {
        return false;
    }
    consumers
        .iter()
        .filter(|p| {
            p.depends()
                .iter()
                .any(|required| required.name() == dependency)
        })
        .all(|package| {
            let missing = handle.check_deps(
                [selected.as_ref()].iter(),
                std::iter::empty::<&alpm::Pkg>(),
                [package.as_ref()].iter(),
                false,
            );
            !missing
                .iter()
                .any(|missing| missing.depend().name() == dependency)
        })
}
fn protected(before: Option<&ManagementState>) -> BTreeSet<String> {
    let mut result: BTreeSet<String> = include_str!("../../../distro/installed/packages.x86_64")
        .lines()
        .map(str::trim)
        .filter(|s| !s.is_empty() && !s.starts_with('#'))
        .map(str::to_string)
        .collect();
    if let Some(state) = before {
        result.extend(state.protected.iter().cloned());
    }
    result
}

const INSTALLER_MANAGEMENT_RECEIPT: &str = "usr/share/distro/install-inputs/management.json";
const INSTALLER_RECEIPT_LIMIT: u64 = 8 * 1024 * 1024;

#[derive(Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct InstalledPackageReceipt {
    version: String,
    reason: InstallReason,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct InstallerManagementReceipt {
    schema_version: u32,
    graphics_bundles: Vec<String>,
    gaming_features: Vec<String>,
    protected_baseline: BTreeMap<String, InstalledPackageReceipt>,
    final_packages: BTreeMap<String, InstalledPackageReceipt>,
    management_sha256: String,
}

fn parse_system_baseline(text: &str) -> Result<BTreeSet<String>> {
    let receipt: InstallerManagementReceipt =
        serde_json::from_str(text).map_err(|e| format!("installer management receipt: {e}"))?;
    if receipt.schema_version != 1 {
        return Err("unsupported installer management receipt schema".into());
    }
    let pin = receipt
        .management_sha256
        .strip_prefix("sha256:")
        .unwrap_or("");
    if pin.len() != 64
        || !pin
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
        || receipt
            .graphics_bundles
            .iter()
            .collect::<BTreeSet<_>>()
            .len()
            != receipt.graphics_bundles.len()
        || receipt.graphics_bundles.iter().any(|bundle| {
            ![
                "amd",
                "intel",
                "nouveau",
                "nvidia-open",
                "virtio",
                "software",
            ]
            .contains(&bundle.as_str())
        })
        || receipt
            .gaming_features
            .iter()
            .collect::<BTreeSet<_>>()
            .len()
            != receipt.gaming_features.len()
        || receipt
            .gaming_features
            .iter()
            .any(|feature| distro_config::gaming_feature_packages(feature).is_err())
    {
        return Err("invalid installer management receipt identity".into());
    }
    for (name, package) in receipt
        .final_packages
        .iter()
        .chain(&receipt.protected_baseline)
    {
        if !distro_config::valid_package_name(name)
            || package.version.is_empty()
            || package.version.len() > 256
            || package
                .version
                .chars()
                .any(|c| c.is_control() || c.is_whitespace())
        {
            return Err("invalid installer package receipt".into());
        }
    }
    if receipt
        .protected_baseline
        .iter()
        .any(|(name, package)| receipt.final_packages.get(name) != Some(package))
    {
        return Err("installer base closure differs from its final package receipt".into());
    }
    Ok(receipt.protected_baseline.into_keys().collect())
}

fn system_packages(root: &Path) -> Result<BTreeSet<String>> {
    // Removal protection grows as externally owned packages are observed. The
    // immutable installer baseline separately identifies system components.
    let mut result = protected(None);
    for family in [
        "amd",
        "intel",
        "nouveau",
        "nvidia-open",
        "virtio",
        "software",
    ] {
        result.extend(distro_graphics::bundle_packages(Some(family)));
    }
    let path = root.join(INSTALLER_MANAGEMENT_RECEIPT);
    // Missing receipts on older installations are allowed. Broken links or
    // writable ancestors are not equivalent to a missing receipt.
    for parent in path.parent().ok_or("missing receipt parent")?.ancestors() {
        match fs::symlink_metadata(parent) {
            Ok(_) => {
                store::trusted_directory(parent)?;
                break;
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.to_string()),
        }
    }
    match fs::symlink_metadata(&path) {
        Ok(_) => result.extend(parse_system_baseline(&store::read_text(
            &path,
            INSTALLER_RECEIPT_LIMIT,
        )?)?),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(e.to_string()),
    }
    Ok(result)
}

fn is_system_package(name: &str, system: &BTreeSet<String>) -> bool {
    system.contains(name)
        || ["linux", "systemd", "nvidia", "mkinitcpio", "shim"]
            .iter()
            .any(|family| {
                name == *family
                    || name
                        .strip_prefix(family)
                        .is_some_and(|suffix| suffix.starts_with('-'))
            })
        || name.starts_with("lib32-nvidia-")
        || [
            "grub",
            "refind",
            "limine",
            "dracut",
            "sbctl",
            "efitools",
            "sbsigntools",
        ]
        .contains(&name)
}

struct Prepared {
    handle: Alpm,
    plan: ExecutionPlan,
    proof: Option<distro_snapshots::OwnedPackageLock>,
    removal_candidates: BTreeMap<String, String>,
}
impl Drop for Prepared {
    fn drop(&mut self) {
        let _ = self.handle.trans_release();
    }
}
pub struct NativePackages {
    pub desired: SystemConfig,
    pub operation: Option<String>,
    prepared: Option<Prepared>,
}
impl NativePackages {
    pub fn new(desired: SystemConfig) -> Result<Self> {
        desired.validate()?;
        Ok(Self {
            desired,
            operation: None,
            prepared: None,
        })
    }
    pub fn installed_config() -> Result<SystemConfig> {
        Ok(store::read_state(Path::new("/"))?
            .map(|s| s.applied)
            .unwrap_or_default())
    }
    fn prepare(&self, flags: TransFlag) -> Result<Prepared> {
        let settings = Configuration::read()?;
        let repositories = settings.identities()?;
        let handle = settings.handle()?;
        handle.trans_init(flags | TransFlag::NEEDED).map_err(err)?;
        // Own the handle immediately so every error releases only our native lock.
        let mut prepared = Prepared {
            handle,
            plan: ExecutionPlan::new(
                CurrentSystemState::new(BTreeMap::new()),
                PackagePlan {
                    changes: vec![],
                    targets: vec![],
                    download_bytes: 0,
                    installed_delta_bytes: Some(0),
                },
            ),
            proof: None,
            removal_candidates: BTreeMap::new(),
        };
        if !flags.contains(TransFlag::NO_LOCK) {
            // The successful transaction owns this lock; Prepared releases it after all snapshots.
            prepared.proof = Some(
                unsafe {
                    distro_snapshots::OwnedPackageLock::from_active_transaction(Path::new(
                        "/var/lib/pacman/db.lck",
                    ))
                }
                .map_err(err)?,
            );
        }
        let before = store::read_state(Path::new("/"))?;
        let initial = current(&prepared.handle);
        let old_reasons = reasons(&prepared.handle);
        let mut protected = protected(before.as_ref());
        let requests = self.desired.requested_packages()?;
        let removes = match before.as_ref() {
            Some(state) => {
                management::removal_candidates(state, &initial, &old_reasons, &self.desired)?
            }
            None => BTreeSet::new(),
        };
        prepared.removal_candidates = removes
            .iter()
            .map(|name| (name.clone(), initial.packages[name].clone()))
            .collect();
        let integrity = if removes.is_empty() {
            None
        } else {
            Some(crate::package_integrity::inspect(
                &prepared.removal_candidates,
            )?)
        };
        if let Some(report) = &integrity {
            protected.extend(
                report
                    .packages
                    .iter()
                    .filter(|(_, check)| !check.removable)
                    .map(|(name, _)| name.clone()),
            );
        }
        let questions = Rc::new(RefCell::new(Vec::<String>::new()));
        let selections = Rc::new(RefCell::new(BTreeMap::<String, String>::new()));
        let mut preferences = before
            .as_ref()
            .map(|s| s.resolved_providers.clone())
            .unwrap_or_default();
        preferences.extend(self.desired.providers.clone());
        let callback = (
            preferences,
            initial.packages.keys().cloned().collect::<BTreeSet<_>>(),
            questions.clone(),
            selections.clone(),
        );
        prepared.handle.set_question_cb(
            callback,
            |mut any, (choices, installed, errors, selections)| {
                any.set_answer(false);
                match any.question() {
                    Question::SelectProvider(mut q) => {
                        let names: Vec<String> =
                            q.providers().iter().map(|p| p.name().to_string()).collect();
                        let explicit = choices.get(q.depend().name());
                        let existing: Vec<_> = names
                            .iter()
                            .enumerate()
                            .filter(|(_, n)| installed.contains(*n))
                            .collect();
                        let selected = if let Some(wanted) = explicit {
                            names.iter().position(|n| n == wanted)
                        } else if existing.len() == 1 {
                            Some(existing[0].0)
                        } else if names.len() == 1 {
                            Some(0)
                        } else {
                            None
                        };
                        if let Some(index) = selected {
                            q.set_index(index as i32);
                            selections
                                .borrow_mut()
                                .insert(q.depend().name().into(), names[index].clone());
                        } else {
                            errors.borrow_mut().push(format!(
                                "Choose provider for {} from {} in configuration.providers",
                                q.depend(),
                                names.join(", ")
                            ));
                            q.set_index(0);
                        }
                    }
                    other => errors.borrow_mut().push(format!(
                        "Package operation requires an unsupported decision: {other:?}"
                    )),
                }
            },
        );
        prepared.handle.sync_sysupgrade(false).map_err(err)?;
        for name in &requests {
            let package = prepared
                .handle
                .syncdbs()
                .iter()
                .find_map(|db| db.pkg(name.as_str()).ok())
                .ok_or_else(|| format!("package {name} is not in an approved repository"))?;
            if package.should_ignore() {
                return Err(format!("requested package {name} is held"));
            }
            if prepared
                .handle
                .trans_add()
                .iter()
                .any(|target| target.name() == name)
            {
                continue;
            }
            if prepared
                .handle
                .localdb()
                .pkg(name.as_str())
                .is_ok_and(|installed| installed.version() >= package.version())
            {
                continue;
            }
            prepared.handle.trans_add_pkg(package).map_err(err)?;
        }
        let mut safe_removes: BTreeSet<_> = removes.difference(&protected).cloned().collect();
        loop {
            let previous = safe_removes.clone();
            safe_removes.retain(|name| {
                let Ok(package) = prepared.handle.localdb().pkg(name.as_str()) else {
                    return false;
                };
                !package
                    .required_by()
                    .iter()
                    .chain(package.optional_for().iter())
                    .any(|name| !previous.contains(name))
            });
            if safe_removes == previous {
                break;
            }
        }
        for name in &safe_removes {
            if protected.contains(name)
                || settings
                    .words("HoldPkg")
                    .iter()
                    .any(|pattern| pattern_matches(pattern, name))
            {
                return Err(format!("protected or held system package: {name}"));
            }
            let package = prepared.handle.localdb().pkg(name.as_str()).map_err(err)?;
            prepared.handle.trans_remove_pkg(package).map_err(err)?;
        }
        prepared
            .handle
            .trans_prepare()
            .map_err(|e| format!("dependency resolution: {e}"))?;
        if !questions.borrow().is_empty() {
            return Err(questions.borrow().join("; "));
        }
        let mut changes = vec![];
        let mut targets = vec![];
        let mut bytes = 0u64;
        let mut delta = 0i64;
        let mut after_reasons = old_reasons.clone();
        let mut final_packages = initial.packages.clone();
        for p in prepared.handle.trans_remove() {
            if protected.contains(p.name()) || !removes.contains(p.name()) {
                return Err(format!("unreviewed or protected removal {}", p.name()));
            }
            changes.push(PackageChange::Remove {
                name: p.name().into(),
                version: p.version().to_string(),
            });
            delta = delta.checked_sub(p.isize()).ok_or("size overflow")?;
            final_packages.remove(p.name());
            after_reasons.remove(p.name());
        }
        for p in prepared.handle.trans_add() {
            if initial
                .packages
                .get(p.name())
                .is_some_and(|v| v == p.version().as_str())
            {
                return Err(format!("unexpected reinstall of {}", p.name()));
            }
            let repository = p.db().ok_or("target has no repository")?.name().to_string();
            let sha = p.sha256sum().ok_or("target lacks SHA-256")?.to_string();
            if sha.len() != 64 || !sha.bytes().all(|b| b.is_ascii_hexdigit()) {
                return Err("invalid package digest".into());
            }
            let size = u64::try_from(p.size()).map_err(err)?;
            let installed = u64::try_from(p.isize()).map_err(err)?;
            targets.push(PackageTarget {
                name: p.name().into(),
                version: p.version().to_string(),
                repository,
                archive_bytes: size,
                installed_bytes: installed,
                sha256: sha,
            });
            bytes = bytes.checked_add(size).ok_or("size overflow")?;
            delta = delta.checked_add(p.isize()).ok_or("size overflow")?;
            if let Some(old) = initial.packages.get(p.name()) {
                delta = delta
                    .checked_sub(
                        prepared
                            .handle
                            .localdb()
                            .pkg(p.name())
                            .map_err(err)?
                            .isize(),
                    )
                    .ok_or("size overflow")?;
                changes.push(PackageChange::Upgrade {
                    name: p.name().into(),
                    from: old.clone(),
                    to: p.version().to_string(),
                });
            } else {
                changes.push(PackageChange::Install {
                    name: p.name().into(),
                    version: p.version().to_string(),
                });
                after_reasons.insert(
                    p.name().into(),
                    if requests.contains(p.name()) {
                        InstallReason::Explicit
                    } else {
                        InstallReason::Dependency
                    },
                );
            }
            final_packages.insert(p.name().into(), p.version().to_string());
        }
        changes.sort_by(|a, b| a.name().cmp(b.name()));
        targets.sort_by(|a, b| a.name.cmp(&b.name));
        let mut managed = management::reconcile(
            before.as_ref(),
            &initial,
            &old_reasons,
            &CurrentSystemState::new(final_packages.clone()),
            &after_reasons,
            &self.desired,
            &protected,
            &repositories,
        )?;
        managed.removal_integrity = integrity
            .as_ref()
            .map(crate::package_integrity::IntegrityReport::digest);
        let additions: BTreeMap<_, _> = prepared
            .handle
            .trans_add()
            .iter()
            .map(|p| (p.name(), p))
            .collect();
        let final_objects: Vec<_> = prepared
            .handle
            .localdb()
            .pkgs()
            .iter()
            .filter(|p| final_packages.contains_key(p.name()) && !additions.contains_key(p.name()))
            .chain(additions.values().copied())
            .collect();
        managed.after.resolved_providers.retain(|dependency, name| {
            final_objects
                .iter()
                .find(|p| p.name() == name)
                .is_some_and(|selected| {
                    provides_requirements(&prepared.handle, selected, dependency, &final_objects)
                })
        });
        for (dependency, name) in &self.desired.providers {
            let selected = final_objects
                .iter()
                .find(|p| p.name() == name)
                .ok_or_else(|| {
                    format!(
                        "selected provider {name} is absent; provider switching is not implicit"
                    )
                })?;
            if !provides_requirements(&prepared.handle, selected, dependency, &final_objects) {
                return Err(format!(
                    "{name} does not provide {dependency} under all resolved version constraints"
                ));
            }
            managed
                .after
                .resolved_providers
                .insert(dependency.clone(), name.clone());
        }
        managed
            .after
            .resolved_providers
            .extend(selections.borrow().clone());
        let mut seen = BTreeSet::new();
        for db in prepared.handle.syncdbs() {
            for package in db.pkgs() {
                if final_packages
                    .get(package.name())
                    .is_some_and(|version| version == package.version().as_str())
                {
                    if !seen.insert(package.name()) {
                        continue;
                    }
                    if let Some(sha256) = package.sha256sum() {
                        let identity = LockedPackage {
                            version: package.version().to_string(),
                            repository: db.name().into(),
                            sha256: sha256.into(),
                        };
                        if let Some(previous) = managed.after.resolution.get(package.name()) {
                            if previous.repository == db.name() && *previous != identity {
                                return Err(format!("repository package {} changed without a version change; installed provenance cannot be relabeled",package.name()));
                            }
                        } else {
                            managed
                                .after
                                .resolution
                                .insert(package.name().into(), identity);
                        }
                    }
                }
            }
        }
        managed.after_digest = managed.after.digest();
        prepared.plan = ExecutionPlan::new(
            initial.clone(),
            PackagePlan {
                changes,
                targets,
                download_bytes: bytes,
                installed_delta_bytes: Some(delta),
            },
        )
        .with_management(managed);
        for name in removes.difference(&safe_removes) {
            let reason = integrity
                .as_ref()
                .and_then(|report| report.packages.get(name))
                .filter(|check| !check.removable)
                .map(|check| check.detail.as_str())
                .unwrap_or("an installed application still needs it");
            prepared
                .plan
                .notes
                .push(format!("Retaining {name}: {reason}."));
        }
        prepared.plan.validate()?;
        if pacman::Pacman::default().current_state()? != initial
            || store::read_reasons(Path::new("/"))? != old_reasons
            || Configuration::read()?.identities()? != repositories
            || store::read_state(Path::new("/"))? != before
        {
            return Err("package, management or repository state changed during resolution".into());
        }
        Ok(prepared)
    }
    fn download_checked(&self, plan: &ExecutionPlan) -> Result<()> {
        let mut transaction = self.prepare(TransFlag::DOWNLOAD_ONLY)?;
        if transaction.plan != *plan {
            return Err("reviewed plan is stale".into());
        }
        if !plan.packages.targets.is_empty() {
            transaction
                .handle
                .trans_commit()
                .map_err(|e| format!("download/signature verification: {e}"))?;
        }
        Ok(())
    }
    pub fn query(mode: &str, query: &str) -> Result<Vec<PackageInfo>> {
        let config = Configuration::read()?;
        config.identities()?;
        let handle = config.handle()?;
        let before = store::read_state(Path::new("/"))?;
        let protect = protected(before.as_ref());
        let system = system_packages(Path::new("/"))?;
        let installed = current(&handle);
        let mut found = BTreeMap::new();
        for db in handle.syncdbs() {
            for p in db.pkgs() {
                let matches = match mode {
                    "details" => p.name() == query,
                    "installed" => installed.packages.contains_key(p.name()),
                    "search" => {
                        p.name().contains(query)
                            || p.desc()
                                .unwrap_or("")
                                .to_lowercase()
                                .contains(&query.to_lowercase())
                    }
                    _ => return Err("unknown package query".into()),
                };
                if matches {
                    found
                        .entry(p.name().to_string())
                        .or_insert_with(|| PackageInfo {
                            name: p.name().into(),
                            version: p.version().to_string(),
                            description: p.desc().unwrap_or("").into(),
                            repository: Some(db.name().into()),
                            installed_version: installed.packages.get(p.name()).cloned(),
                            protected: protect.contains(p.name()),
                            system_package: is_system_package(p.name(), &system),
                            selectable: !is_system_package(p.name(), &system),
                        });
                }
            }
        }
        if mode == "installed" {
            for p in handle.localdb().pkgs() {
                found.entry(p.name().into()).or_insert_with(|| PackageInfo {
                    name: p.name().into(),
                    version: p.version().to_string(),
                    description: p.desc().unwrap_or("").into(),
                    repository: None,
                    installed_version: Some(p.version().to_string()),
                    protected: true,
                    system_package: is_system_package(p.name(), &system),
                    selectable: false,
                });
            }
        }
        if mode == "search" && found.len() > 1000 {
            return Err("More than 1000 packages match; enter a more specific search.".into());
        }
        Ok(found.into_values().collect())
    }
}

#[derive(Serialize)]
pub struct PackageInfo {
    pub name: String,
    pub version: String,
    pub description: String,
    pub repository: Option<String>,
    pub installed_version: Option<String>,
    pub protected: bool,
    pub system_package: bool,
    pub selectable: bool,
}

impl PackageBackend for NativePackages {
    fn operation_id(&self) -> Option<String> {
        self.operation.clone()
    }
    fn resolve(&mut self) -> Result<ExecutionPlan> {
        if let Some(prepared) = &self.prepared {
            let managed = prepared
                .plan
                .management
                .as_ref()
                .ok_or("missing management plan")?;
            if !prepared.removal_candidates.is_empty()
                && Some(crate::package_integrity::inspect(&prepared.removal_candidates)?.digest())
                    != managed.removal_integrity
            {
                return Err("package file integrity changed after review".into());
            }
            if pacman::Pacman::default().current_state()? != prepared.plan.current
                || Configuration::read()?.identities()? != managed.after.repositories
                || store::read_state(Path::new("/"))? != managed.before
                || store::read_reasons(Path::new("/"))? != managed.reasons_before
            {
                return Err("locked plan inputs changed".into());
            }
            return Ok(prepared.plan.clone());
        }
        Ok(self.prepare(TransFlag::NO_LOCK)?.plan.clone())
    }
    fn prerequisites(&mut self, plan: &ExecutionPlan) -> Result<()> {
        pacman::require_root()?;
        if Path::new("/run/archiso").exists() {
            return Err("live systems support inspection only".into());
        }
        if Path::new("/var/lib/pacman/db.lck").exists() {
            return Err("pacman is locked; never remove its live lock".into());
        }
        if self.resolve()? != *plan {
            return Err("reviewed plan is stale".into());
        }
        let installed = plan.packages.targets.iter().try_fold(0u64, |n, p| {
            n.checked_add(p.installed_bytes).ok_or("size overflow")
        })?;
        for path in ["/", "/var/cache/pacman/pkg"] {
            check_disk_space(
                pacman::available_space(Path::new(path))?,
                plan.packages.download_bytes,
                installed,
                256 * 1024 * 1024,
            )?;
        }
        if plan.boot.regenerate_uki {
            check_disk_space(
                pacman::available_space(Path::new("/efi"))?,
                0,
                0,
                512 * 1024 * 1024,
            )?;
        }
        Ok(())
    }
    fn download(&mut self, plan: &ExecutionPlan) -> Result<()> {
        self.download_checked(plan)
    }
    fn verify(&mut self, plan: &ExecutionPlan) -> Result<()> {
        self.download_checked(plan)
    }
    fn prepare_locked(&mut self, plan: &ExecutionPlan) -> Result<()> {
        let prepared = self.prepare(TransFlag::NONE)?;
        if prepared.plan != *plan {
            return Err("reviewed plan changed before locked preparation".into());
        }
        self.prepared = Some(prepared);
        Ok(())
    }
    fn owned_package_lock(&self) -> Option<&distro_snapshots::OwnedPackageLock> {
        self.prepared.as_ref().and_then(|p| p.proof.as_ref())
    }
    fn apply(&mut self, plan: &ExecutionPlan) -> Result<()> {
        let prepared = self
            .prepared
            .as_mut()
            .ok_or("no prepared locked transaction")?;
        if prepared.plan != *plan {
            return Err("prepared transaction disagrees with reviewed plan".into());
        }
        prepared
            .proof
            .as_ref()
            .ok_or("missing native lock proof")?
            .verify(Path::new("/var/lib/pacman/db.lck"))
            .map_err(err)?;
        if !prepared.removal_candidates.is_empty()
            && Some(crate::package_integrity::inspect(&prepared.removal_candidates)?.digest())
                != plan
                    .management
                    .as_ref()
                    .ok_or("missing management plan")?
                    .removal_integrity
        {
            return Err("package file integrity changed before commit".into());
        }
        // alpm 5.0.2's Debug payload casts file conflicts incorrectly; Display preserves its error safely.
        if !plan.packages.changes.is_empty() {
            prepared
                .handle
                .trans_commit()
                .map_err(|e| format!("package commit: {e}"))?;
        }
        Ok(())
    }
    fn apply_management(&mut self, plan: &ExecutionPlan) -> Result<()> {
        let prepared = self.prepared.as_ref().ok_or("no held package lock")?;
        let managed = plan.management.as_ref().ok_or("missing management plan")?;
        for (name, reason) in &managed.reasons_after {
            let package = prepared.handle.localdb().pkg(name.as_str()).map_err(err)?;
            let expected = match reason {
                InstallReason::Explicit => PackageReason::Explicit,
                InstallReason::Dependency => PackageReason::Depend,
            };
            if package.reason() != expected {
                package.set_reason(expected).map_err(err)?;
            }
        }
        store::write_state(Path::new("/"), &managed.after)
    }
    fn verify_management(&mut self, plan: &ExecutionPlan) -> Result<()> {
        let managed = plan.management.as_ref().ok_or("missing management plan")?;
        if store::read_state(Path::new("/"))?.as_ref() != Some(&managed.after)
            || store::read_reasons(Path::new("/"))? != managed.reasons_after
        {
            return Err("installed management state or reasons differ from reviewed plan".into());
        }
        Ok(())
    }
    fn current_state(&mut self) -> Result<CurrentSystemState> {
        use crate::pacman::Pacman;
        Pacman::default().current_state()
    }
}
