//! Conservative pacman adapter. No refresh, shell evaluation, or trust-policy overrides.
use crate::*;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
    process::{Command, Stdio},
};

pub const PRINT_FORMAT: &str = "%n\t%v\t%r\t%s\t%h\t%H\t%R";

pub struct CommandOutput {
    pub success: bool,
    pub stdout: String,
    pub stderr: String,
}
pub trait CommandRunner {
    fn working_uki(&mut self, configured: &str) -> Result<String> {
        Ok(configured.into())
    }
    fn managed_loader(&mut self) -> Result<bool> {
        Ok(false)
    }
    fn prepare_boot(&mut self, _: i64) -> Result<()> {
        Err("boot marker writer unavailable".into())
    }
    fn run(&mut self, program: &str, args: &[String]) -> Result<CommandOutput>;
    fn read_file(&mut self, path: &str) -> Result<String> {
        fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))
    }
}

pub struct NativeRunner;
impl CommandRunner for NativeRunner {
    fn working_uki(&mut self, _: &str) -> Result<String> {
        distro_snapshots::Manager::online(distro_snapshots::Native)
            .working_uki()
            .map(|path| path.to_string_lossy().into_owned())
            .map_err(|e| e.to_string())
    }
    fn managed_loader(&mut self) -> Result<bool> {
        let manager = distro_snapshots::Manager::online(distro_snapshots::Native);
        if !manager.generations_enabled().map_err(|e| e.to_string())? {
            return Ok(false);
        }
        manager
            .generation_prerequisites()
            .map_err(|e| e.to_string())?;
        Ok(true)
    }
    fn prepare_boot(&mut self, transaction_id: i64) -> Result<()> {
        let path = Path::new("/etc/kernel/cmdline");
        let previous = fs::read_to_string(path).map_err(|e| e.to_string())?;
        let mut words: Vec<_> = previous
            .split_whitespace()
            .filter(|s| !s.starts_with("astraeus.transaction="))
            .collect();
        let marker = format!(
            "astraeus.transaction={transaction_id}-{}",
            crate::integration::boot_id()?
        );
        words.push(&marker);
        let mut file = fs::OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(path)
            .map_err(|e| e.to_string())?;
        use std::io::Write;
        writeln!(file, "{}", words.join(" ")).map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
        Ok(())
    }
    fn run(&mut self, program: &str, args: &[String]) -> Result<CommandOutput> {
        let output = Command::new(program)
            .args(args)
            .env("LC_ALL", "C")
            .env("PATH", "/usr/bin:/usr/sbin")
            .stdin(Stdio::null())
            .output()
            .map_err(|e| format!("cannot run {program}: {e}"))?;
        Ok(CommandOutput {
            success: output.status.success(),
            stdout: String::from_utf8(output.stdout).map_err(|e| e.to_string())?,
            stderr: String::from_utf8_lossy(&output.stderr)
                .chars()
                .take(4096)
                .collect(),
        })
    }
}

fn checked(runner: &mut impl CommandRunner, program: &str, args: &[&str]) -> Result<String> {
    let result = runner.run(
        program,
        &args.iter().map(|s| (*s).to_string()).collect::<Vec<_>>(),
    )?;
    if !result.success {
        return Err(format!("{program} failed: {}", result.stderr.trim()));
    }
    Ok(result.stdout)
}

fn token(value: &str) -> bool {
    !value.is_empty()
        && !value.starts_with(['-', '.'])
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"@_+.-:".contains(&b))
}

pub fn parse_current(text: &str) -> Result<CurrentSystemState> {
    let mut packages = BTreeMap::new();
    for line in text.lines() {
        let fields: Vec<_> = line.split_whitespace().collect();
        if fields.len() != 2
            || !fields.iter().all(|s| token(s))
            || packages
                .insert(fields[0].into(), fields[1].into())
                .is_some()
        {
            return Err("invalid or duplicate pacman query row".into());
        }
    }
    if packages.is_empty() {
        return Err("installed package database is empty".into());
    }
    Ok(CurrentSystemState::new(packages))
}

pub fn parse_targets(text: &str) -> Result<Vec<PackageTarget>> {
    let mut targets = Vec::new();
    let mut names = BTreeSet::new();
    for line in text.lines() {
        let fields: Vec<_> = line.split('\t').collect();
        if fields.len() != 7 || !fields[..3].iter().all(|s| token(s)) {
            return Err("invalid pacman print-format row".into());
        }
        if !fields[5].is_empty() || !fields[6].is_empty() {
            return Err(format!(
                "{} has conflicts/replacements; this adapter cannot safely enumerate removals",
                fields[0]
            ));
        }
        if !names.insert(fields[0])
            || fields[4].len() != 64
            || !fields[4].bytes().all(|b| b.is_ascii_hexdigit())
        {
            return Err("duplicate package or missing SHA-256 in pacman plan".into());
        }
        targets.push(PackageTarget {
            name: fields[0].into(),
            version: fields[1].into(),
            repository: fields[2].into(),
            archive_bytes: fields[3]
                .parse()
                .map_err(|_| "invalid package archive size")?,
            installed_bytes: 0,
            sha256: fields[4].to_ascii_lowercase(),
        });
    }
    targets.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(targets)
}

/// Pacman's tagged database records, not localized `pacman -Si` text.
pub fn database_field<'a>(text: &'a str, key: &str) -> Result<&'a str> {
    let marker = format!("%{key}%");
    let mut matches = text.lines().enumerate().filter(|(_, s)| *s == marker);
    let index = matches
        .next()
        .ok_or_else(|| format!("database field {key} missing"))?
        .0;
    if matches.next().is_some() {
        return Err(format!("duplicate database field {key}"));
    }
    let value = text
        .lines()
        .nth(index + 1)
        .filter(|s| !s.is_empty() && !s.starts_with('%'))
        .ok_or("empty database field")?;
    Ok(value)
}

pub struct Pacman<R = NativeRunner> {
    pub runner: R,
}
impl Default for Pacman {
    fn default() -> Self {
        Self {
            runner: NativeRunner,
        }
    }
}

impl<R: CommandRunner> Pacman<R> {
    fn pacman(&mut self, args: &[&str]) -> Result<String> {
        checked(&mut self.runner, "/usr/bin/pacman", args)
    }

    fn layout(&mut self) -> Result<()> {
        for (key, expected) in [("RootDir", "/"), ("DBPath", "/var/lib/pacman/")] {
            let value = checked(&mut self.runner, "/usr/bin/pacman-conf", &[key])?;
            if value.trim().trim_end_matches('/') != expected.trim_end_matches('/') {
                return Err(format!("unsupported pacman {key}; expected {expected}"));
            }
        }
        Ok(())
    }

    fn require_signatures(&mut self, plan: &ExecutionPlan) -> Result<()> {
        let repositories: BTreeSet<_> = plan
            .packages
            .targets
            .iter()
            .map(|t| t.repository.as_str())
            .collect();
        for repo in repositories {
            let mut policy = checked(
                &mut self.runner,
                "/usr/bin/pacman-conf",
                &["--repo", repo, "SigLevel"],
            )?;
            // Empty output means this repository inherits the global signature policy.
            if policy.trim().is_empty() {
                policy = checked(&mut self.runner, "/usr/bin/pacman-conf", &["SigLevel"])?;
            }
            let policy: Vec<_> = policy.split_whitespace().collect();
            if !policy.contains(&"PackageRequired")
                || !policy.contains(&"PackageTrustedOnly")
                || policy.contains(&"PackageNever")
                || policy.contains(&"PackageOptional")
                || policy.contains(&"PackageTrustAll")
            {
                return Err(format!(
                    "repository {repo} must require trusted package signatures"
                ));
            }
        }
        Ok(())
    }

    fn same_plan(&mut self, plan: &ExecutionPlan) -> Result<()> {
        if self.resolve()? != *plan {
            return Err("package state or repository inputs changed since planning".into());
        }
        self.require_signatures(plan)
    }

    fn sync(&mut self, plan: &ExecutionPlan, download: bool) -> Result<()> {
        plan.validate()?;
        self.same_plan(plan)?;
        if plan.packages.targets.is_empty() {
            return Err("empty package transaction".into());
        }
        let mut args = vec![
            "--sync".to_string(),
            "--sysupgrade".into(),
            "--noconfirm".into(),
        ];
        if download {
            args.push("--downloadonly".into());
        }
        // Explicit dependency targets would mark newly pulled dependencies as
        // explicitly installed. Keep pacman's native system-upgrade semantics.
        let borrowed: Vec<_> = args.iter().map(String::as_str).collect();
        self.pacman(&borrowed)?;
        Ok(())
    }
}

impl<R: CommandRunner> PackageBackend for Pacman<R> {
    fn current_state(&mut self) -> Result<CurrentSystemState> {
        parse_current(&self.pacman(&["--query"])?)
    }

    fn resolve(&mut self) -> Result<ExecutionPlan> {
        self.layout()?;
        let current = self.current_state()?;
        let output = self.pacman(&[
            "--sync",
            "--sysupgrade",
            "--print-format",
            PRINT_FORMAT,
            "--noconfirm",
        ])?;
        let mut targets = parse_targets(&output)?;
        let mut changes = Vec::new();
        let mut download_bytes = 0u64;
        let mut delta = 0i64;
        for target in &mut targets {
            let db = format!("/var/lib/pacman/sync/{}.db", target.repository);
            let member = format!("{}-{}/desc", target.name, target.version);
            let desc = checked(&mut self.runner, "/usr/bin/bsdtar", &["-xOf", &db, &member])?;
            for (key, expected) in [
                ("NAME", target.name.as_str()),
                ("VERSION", target.version.as_str()),
                ("SHA256SUM", target.sha256.as_str()),
            ] {
                if database_field(&desc, key)? != expected {
                    return Err("repository metadata changed during planning".into());
                }
            }
            // pacman's %s is remaining download size and becomes zero when cached.
            // Bind the reviewed plan to the repository's immutable archive size.
            target.archive_bytes = database_field(&desc, "CSIZE")?
                .parse()
                .map_err(|_| "invalid archive size")?;
            target.installed_bytes = database_field(&desc, "ISIZE")?
                .parse()
                .map_err(|_| "invalid installed size")?;
            download_bytes = download_bytes
                .checked_add(target.archive_bytes)
                .ok_or("download size overflow")?;
            let size =
                i64::try_from(target.installed_bytes).map_err(|_| "installed size overflow")?;
            delta = delta.checked_add(size).ok_or("installed delta overflow")?;
            if let Some(old) = current.packages.get(&target.name) {
                let path = format!("/var/lib/pacman/local/{}-{old}/desc", target.name);
                let desc = self.runner.read_file(&path)?;
                let size: i64 = database_field(&desc, "SIZE")?
                    .parse()
                    .map_err(|_| "invalid local installed size")?;
                if size < 0 {
                    return Err("negative installed size".into());
                }
                delta = delta.checked_sub(size).ok_or("installed delta overflow")?;
                changes.push(PackageChange::Upgrade {
                    name: target.name.clone(),
                    from: old.clone(),
                    to: target.version.clone(),
                });
            } else {
                changes.push(PackageChange::Install {
                    name: target.name.clone(),
                    version: target.version.clone(),
                });
            }
        }
        if self.current_state()? != current {
            return Err("installed state changed during planning".into());
        }
        let plan = ExecutionPlan::new(
            current,
            PackagePlan {
                changes,
                targets,
                download_bytes,
                installed_delta_bytes: Some(delta),
            },
        );
        plan.validate()?;
        Ok(plan)
    }

    fn prerequisites(&mut self, plan: &ExecutionPlan) -> Result<()> {
        require_root()?;
        self.same_plan(plan)?;
        if Path::new("/var/lib/pacman/db.lck")
            .try_exists()
            .map_err(|e| e.to_string())?
        {
            return Err("pacman is locked; do not remove its lock automatically".into());
        }
        self.pacman(&["--database", "--check"])?;
        let cache = checked(&mut self.runner, "/usr/bin/pacman-conf", &["CacheDir"])?;
        if cache.trim().trim_end_matches('/') != "/var/cache/pacman/pkg" {
            return Err("only the standard single pacman cache directory is supported".into());
        }
        let installed = plan.packages.targets.iter().try_fold(0u64, |sum, t| {
            sum.checked_add(t.installed_bytes)
                .ok_or("installed size overflow")
        })?;
        for path in ["/", "/var/cache/pacman/pkg"] {
            check_disk_space(
                available_space(Path::new(path))?,
                plan.packages.download_bytes,
                installed,
                256 * 1024 * 1024,
            )?;
        }
        if plan.boot.regenerate_uki {
            check_disk_space(available_space(Path::new("/efi"))?, 0, 0, 512 * 1024 * 1024)?;
        }
        Ok(())
    }

    fn download(&mut self, plan: &ExecutionPlan) -> Result<()> {
        self.sync(plan, true)
    }
    fn verify(&mut self, plan: &ExecutionPlan) -> Result<()> {
        // Pacman verifies cached archives and signatures during download-only transactions.
        // Repeating this phase delegates trust checks to libalpm, including key revocation.
        self.sync(plan, true)
    }
    fn apply(&mut self, plan: &ExecutionPlan) -> Result<()> {
        self.sync(plan, false)
    }
}

pub fn require_root() -> Result<()> {
    #[cfg(target_os = "linux")]
    {
        // SAFETY: geteuid takes no pointers and does not mutate memory.
        if unsafe { libc::geteuid() } == 0 {
            return Ok(());
        }
        Err("updates require root; use sudo distroctl update (planning/history do not)".into())
    }
    #[cfg(not(target_os = "linux"))]
    {
        Err("package updates require an installed Astraeus Linux system".into())
    }
}

pub fn available_space(path: &Path) -> Result<u64> {
    #[cfg(target_os = "linux")]
    {
        use std::{ffi::CString, mem::MaybeUninit, os::unix::ffi::OsStrExt};
        let path = CString::new(path.as_os_str().as_bytes()).map_err(|e| e.to_string())?;
        let mut stat = MaybeUninit::<libc::statvfs>::uninit();
        // SAFETY: path is NUL-terminated and stat points to writable storage of the correct type.
        if unsafe { libc::statvfs(path.as_ptr(), stat.as_mut_ptr()) } != 0 {
            return Err(std::io::Error::last_os_error().to_string());
        }
        // SAFETY: statvfs initialized the structure on success.
        let stat = unsafe { stat.assume_init() };
        stat.f_bavail
            .checked_mul(stat.f_frsize)
            .ok_or_else(|| "filesystem size overflow".into())
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = path;
        Err("disk-space checks require Linux".into())
    }
}

pub struct SystemBoot<R = NativeRunner> {
    pub runner: R,
}
impl<R: CommandRunner> BootBackend for SystemBoot<R> {
    fn regenerate(&mut self, plan: &ExecutionPlan, transaction_id: i64) -> Result<()> {
        plan.validate()?;
        if plan.boot.regenerate_uki {
            self.runner.prepare_boot(transaction_id)?;
            checked(&mut self.runner, "/usr/bin/mkinitcpio", &["-P"])?;
            if self.runner.managed_loader()? {
                return Ok(());
            }
            // Loader binaries are outside the saved UKI recovery boundary.
            // Reject systemd plans before mutation and only read these copies.
            for installed in [
                "/efi/EFI/systemd/systemd-bootx64.efi",
                "/efi/EFI/BOOT/BOOTX64.EFI",
            ] {
                checked(
                    &mut self.runner,
                    "/usr/bin/cmp",
                    &[
                        "--",
                        "/usr/lib/systemd/boot/efi/systemd-bootx64.efi",
                        installed,
                    ],
                )?;
            }
        }
        Ok(())
    }
}

pub struct SystemHealth<R = NativeRunner> {
    pub runner: R,
    pub uki_path: String,
}
impl<R: CommandRunner> HealthChecks for SystemHealth<R> {
    fn run(&mut self, _: &ExecutionPlan) -> Vec<HealthCheckResult> {
        let uki_path = match self.runner.working_uki(&self.uki_path) {
            Ok(path) => path,
            Err(detail) => {
                return vec![HealthCheckResult {
                    name: "boot_generation_metadata".into(),
                    required: true,
                    status: HealthStatus::Unavailable,
                    detail,
                }]
            }
        };
        let mut checks = vec![];
        match self.runner.managed_loader() {
            Ok(false) => {}
            managed => {
                let result = managed.and_then(|_| {
                    let output = checked(
                        &mut self.runner,
                        "/usr/bin/astraeus-boot-artifact",
                        &["verify", &uki_path],
                    )?;
                    let verdict: distro_snapshots::generations::TrustVerdict =
                        serde_json::from_str(&output).map_err(|error| error.to_string())?;
                    verdict
                        .require_trusted(&verdict.sha256)
                        .map_err(|error| error.to_string())
                });
                checks.push(HealthCheckResult {
                    name: "secure_boot".into(),
                    required: true,
                    status: if result.is_ok() {
                        HealthStatus::Pass
                    } else {
                        HealthStatus::Fail
                    },
                    detail: result.map_or_else(std::convert::identity, |_| {
                        "Signed loader/UKI and enforced owner trust verified".into()
                    }),
                });
            }
        }
        for (name, program, args, empty) in [
            (
                "package_database",
                "/usr/bin/pacman",
                vec!["--database", "--check"],
                false,
            ),
            (
                "repository_configuration",
                "/usr/bin/pacman-conf",
                vec!["--repo-list"],
                false,
            ),
            ("uki", "/usr/bin/ukify", vec!["inspect", &uki_path], false),
            (
                "boot_loader",
                "/usr/bin/bootctl",
                vec!["--esp-path=/efi", "is-installed"],
                false,
            ),
            (
                "failed_system_units",
                "/usr/bin/systemctl",
                vec!["--failed", "--no-legend", "--plain", "--no-pager"],
                true,
            ),
            (
                "root_filesystem",
                "/usr/bin/findmnt",
                vec!["--noheadings", "--output", "OPTIONS", "--mountpoint", "/"],
                false,
            ),
            (
                "critical_services",
                "/usr/bin/systemctl",
                vec!["is-active", "NetworkManager.service"],
                false,
            ),
            (
                "display_manager",
                "/usr/bin/systemctl",
                vec!["is-active", "sddm.service"],
                false,
            ),
            (
                "login_service",
                "/usr/bin/systemctl",
                vec!["is-active", "systemd-logind.service"],
                false,
            ),
            (
                "distroctl",
                "/usr/bin/distroctl",
                vec!["info", "--json"],
                false,
            ),
        ] {
            let result = self.runner.run(
                program,
                &args.iter().map(|s| (*s).to_string()).collect::<Vec<_>>(),
            );
            let (status, detail) = match result {
                Err(e) => (HealthStatus::Unavailable, e),
                Ok(o)
                    if !o.success
                        && (name == "failed_system_units"
                            || (name == "critical_services"
                                && !matches!(o.stdout.trim(), "inactive" | "failed"))) =>
                {
                    (HealthStatus::Unavailable, o.stderr)
                }
                Ok(o) if !o.success => (HealthStatus::Fail, o.stderr),
                Ok(o) if empty && !o.stdout.trim().is_empty() => (HealthStatus::Fail, o.stdout),
                Ok(o)
                    if name == "root_filesystem"
                        && !o.stdout.trim().split(',').any(|s| s == "rw") =>
                {
                    (HealthStatus::Fail, "root is not mounted read-write".into())
                }
                Ok(o) if name == "repository_configuration" && o.stdout.trim().is_empty() => {
                    (HealthStatus::Fail, "no repositories configured".into())
                }
                Ok(o)
                    if name == "distroctl"
                        && serde_json::from_str::<serde_json::Value>(&o.stdout).is_err() =>
                {
                    (HealthStatus::Fail, "invalid distroctl JSON".into())
                }
                Ok(_) => (HealthStatus::Pass, "check passed".into()),
            };
            checks.push(HealthCheckResult {
                name: name.into(),
                status,
                required: true,
                detail: detail.chars().take(4096).collect(),
            });
        }
        checks
    }
}
