//! Shared command interface for the desktop and terminal system-management flows.
mod ops;

use distro_config::{parse_system_toml, SystemConfig, MAX_SYSTEM_CONFIG_BYTES};
use distro_transactions::{
    management_store, read_history, ExecutionPlan, Result, TransactionState, HISTORY_PATH,
};
use serde::{Deserialize, Serialize};
use std::{io::Read, path::Path};

pub const HELP: &str = "System management
  distroctl system status|features|adopt|export --json
  distroctl system packages search <text>|details <name>|installed --json
  distroctl system parse --stdin --json           Validate TOML from stdin
  distroctl system plan|diff --stdin --json       Review a JSON SystemConfig
  distroctl system plan <config.toml> [--json]    Review a saved configuration
  distroctl system apply <config.toml> --expect-plan <sha256:...> [--json]
  distroctl system submit --json                 Submit a reviewed request (root)
  distroctl system operation <32-hex-id> --json   Inspect durable progress

Submit reads {schema_version:1,config:SystemConfig,expected_plan:sha256} from stdin.
Only approved native packages are supported. Existing applications remain protected.
The worker continues when the desktop closes. Boot confirmation is still required.";

pub const NATIVE_AVAILABLE: bool = cfg!(all(target_os = "linux", feature = "native-alpm"));
#[cfg(not(all(target_os = "linux", feature = "native-alpm")))]
const NATIVE_REQUIRED: &str =
    "Native management requires an installed Astraeus Linux system and a native-alpm build";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Submission {
    pub schema_version: u32,
    pub config: SystemConfig,
    pub expected_plan: String,
}

impl Submission {
    pub fn validate(&self) -> Result<()> {
        if self.schema_version != 1 || !valid_plan_id(&self.expected_plan) {
            return Err("invalid submission schema or expected plan digest".into());
        }
        self.config.validate()
    }
}

fn valid_plan_id(value: &str) -> bool {
    value.strip_prefix("sha256:").is_some_and(|hash| {
        hash.len() == 64
            && hash
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    })
}

pub fn read_bounded(mut reader: impl Read) -> Result<String> {
    let mut bytes = Vec::new();
    reader
        .by_ref()
        .take((MAX_SYSTEM_CONFIG_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| error.to_string())?;
    if bytes.len() > MAX_SYSTEM_CONFIG_BYTES {
        return Err("system request exceeds 256 KiB".into());
    }
    String::from_utf8(bytes).map_err(|_| "system request must be UTF-8".into())
}

pub fn parse_submission(input: &str) -> Result<Submission> {
    if input.len() > MAX_SYSTEM_CONFIG_BYTES {
        return Err("system request exceeds 256 KiB".into());
    }
    let submission: Submission = serde_json::from_str(input).map_err(|error| error.to_string())?;
    submission.validate()?;
    Ok(submission)
}

fn parse_configuration(input: &str) -> Result<SystemConfig> {
    let configuration: SystemConfig =
        serde_json::from_str(input).map_err(|error| error.to_string())?;
    configuration.validate()?;
    Ok(configuration)
}

fn read_configuration_file(path: &str) -> Result<SystemConfig> {
    if path.starts_with('-') {
        return Err("expected a TOML configuration path".into());
    }
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK);
    }
    let file = options
        .open(path)
        .map_err(|error| format!("configuration: {error}"))?;
    if !file
        .metadata()
        .map_err(|error| error.to_string())?
        .is_file()
    {
        return Err("configuration must be a regular file".into());
    }
    parse_system_toml(&read_bounded(file)?)
}

fn emit(value: &impl Serialize) -> Result<()> {
    println!(
        "{}",
        serde_json::to_string_pretty(value).map_err(|error| error.to_string())?
    );
    Ok(())
}

pub fn installed_configuration() -> Result<SystemConfig> {
    Ok(management_store::read_state(Path::new("/"))?
        .map(|state| state.applied)
        .unwrap_or_default())
}

fn configuration_response(configuration: SystemConfig) -> Result<serde_json::Value> {
    Ok(
        serde_json::json!({"schema_version":1,"toml":configuration.to_toml()?,"configuration":configuration}),
    )
}

#[derive(Debug, Serialize)]
pub struct PlanResponse {
    pub schema_version: u32,
    pub plan_id: String,
    pub executable: bool,
    pub plan: Option<ExecutionPlan>,
    pub blockers: Vec<String>,
    pub warnings: Vec<String>,
}

pub fn live() -> bool {
    Path::new("/run/archiso").exists()
}

#[cfg(all(target_os = "linux", feature = "native-alpm"))]
fn resolve(configuration: SystemConfig) -> Result<ExecutionPlan> {
    use distro_transactions::{native_alpm::NativePackages, PackageBackend};
    NativePackages::new(configuration)?.resolve()
}

#[cfg(not(all(target_os = "linux", feature = "native-alpm")))]
fn resolve(_: SystemConfig) -> Result<ExecutionPlan> {
    Err(NATIVE_REQUIRED.into())
}

pub fn preview(configuration: SystemConfig) -> Result<PlanResponse> {
    configuration.validate()?;
    preview_observed(
        resolve(configuration),
        live(),
        read_history(Path::new(HISTORY_PATH)),
        ops::active(),
    )
}

fn preview_observed(
    resolved: Result<ExecutionPlan>,
    is_live: bool,
    history: Result<Vec<distro_transactions::TransactionRecord>>,
    active: Result<Option<ops::Operation>>,
) -> Result<PlanResponse> {
    let mut response = PlanResponse {
        schema_version: 1,
        plan_id: String::new(),
        executable: false,
        plan: None,
        blockers: vec![],
        warnings: vec![],
    };
    match resolved {
        Ok(plan) => {
            plan.validate()?;
            response.plan_id = plan.fingerprint();
            response.warnings.extend(plan.notes.iter().cloned());
            if !plan.has_mutation() {
                response
                    .warnings
                    .push("The requested state is already applied.".into());
            }
            response.plan = Some(plan);
        }
        Err(error) => response.blockers.push(error),
    }
    if is_live {
        response.blockers.push(
            "Live sessions support inspection only; install the system before applying changes."
                .into(),
        );
    }
    match history {
        Ok(records) if records.iter().any(|record| !record.state.terminal()) => response.blockers.push("A previous transaction needs boot confirmation or recovery. Inspect transaction history.".into()),
        Err(error) => response.blockers.push(format!("Transaction history unavailable: {error}")),
        _ => {},
    }
    match active {
        Ok(Some(operation)) if operation.in_progress() => response
            .blockers
            .push("Another system operation is queued or running.".into()),
        Err(error) => response
            .blockers
            .push(format!("Operation state unavailable: {error}")),
        _ => {}
    }
    response.executable = response.blockers.is_empty()
        && response
            .plan
            .as_ref()
            .is_some_and(ExecutionPlan::has_mutation);
    response.warnings.push("User game files and settings are outside OS rollback. Dependency-only packages are retained when a feature is disabled.".into());
    Ok(response)
}

fn features() -> Result<serde_json::Value> {
    let features = [("core","Steam and runtime"),("tools","Gaming tools"),("gamescope","Gamescope"),("mangohud","MangoHud"),("gamemode","GameMode"),("lutris","Lutris"),("streaming","OBS streaming")]
        .into_iter().map(|(id,title)| Ok(serde_json::json!({"id":id,"title":title,"supported":true,"packages":distro_config::gaming_feature_packages(id)?}))).collect::<Result<Vec<_>>>()?;
    Ok(serde_json::json!({"schema_version":1,"features":features}))
}

fn status() -> Result<serde_json::Value> {
    let mut drift = Vec::<String>::new();
    let mut recovery = false;
    let state = match management_store::read_state(Path::new("/")) {
        Ok(state) => state,
        Err(error) => {
            drift.push(error);
            recovery = true;
            None
        }
    };
    let configuration = if recovery {
        None
    } else {
        Some(
            state
                .as_ref()
                .map(|state| state.applied.clone())
                .unwrap_or_default(),
        )
    };
    #[cfg(all(target_os = "linux", feature = "native-alpm"))]
    if let Some(state) = state {
        use distro_transactions::{pacman::Pacman, PackageBackend};
        match (
            Pacman::default().current_state(),
            management_store::read_reasons(Path::new("/")),
        ) {
            (Ok(current), Ok(reasons)) => {
                for (name, receipt) in &state.packages {
                    if current.packages.get(name) != Some(&receipt.version)
                        || reasons.get(name) != Some(&receipt.reason)
                    {
                        drift.push(format!("Managed package {name} changed outside Astraeus"));
                    }
                }
                for name in state.applied.requested_packages()? {
                    if !current.packages.contains_key(&name) {
                        drift.push(format!("Requested package {name} is missing"));
                    }
                }
            }
            (Err(error), _) | (_, Err(error)) => drift.push(error),
        }
    }
    let records = match read_history(Path::new(HISTORY_PATH)) {
        Ok(records) => records,
        Err(error) => {
            drift.push(format!("History unavailable: {error}"));
            recovery = true;
            vec![]
        }
    };
    let reboot = records
        .iter()
        .any(|record| record.state == TransactionState::AwaitingBoot);
    recovery |= records
        .iter()
        .any(|record| record.state == TransactionState::RollbackRequired);
    let observed = crate::status();
    let active = match ops::active() {
        Ok(operation) => operation,
        Err(error) => {
            drift.push(format!("Operation unavailable: {error}"));
            recovery = true;
            None
        }
    };
    Ok(
        serde_json::json!({"schema_version":1,"supported":NATIVE_AVAILABLE,"configuration":configuration,"configuration_available":configuration.is_some(),"drift":drift,"live":live(),"active_operation":active,"reboot_required":reboot,"recovery_required":recovery,
        "health":{"observation":"Current read-only observations","boot":observed.boot,"kernel":observed.kernel,"filesystem":observed.filesystem,"desktop":observed.desktop},
        "security":security_observation()}),
    )
}

fn security_observation() -> serde_json::Value {
    match security_query() {
        Ok(value) => value,
        Err(error) => serde_json::json!({"state":"unknown","detail":error}),
    }
}

fn security_query() -> Result<serde_json::Value> {
    use std::{process::Command, time::Duration};
    let mut command = Command::new("/usr/bin/astraeus-secure-boot");
    command
        .args(["status", "--json"])
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("LC_ALL", "C");
    query_security_command(command, Duration::from_secs(5))
}

fn query_security_command(
    mut command: std::process::Command,
    timeout: std::time::Duration,
) -> Result<serde_json::Value> {
    use std::{
        process::Stdio,
        sync::mpsc,
        thread,
        time::{Duration, Instant},
    };
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("Secure Boot observation unavailable: {error}"))?;
    let stdout = child.stdout.take().ok_or("security stdout unavailable")?;
    let stderr = child.stderr.take().ok_or("security stderr unavailable")?;
    let (sender, receiver) = mpsc::channel();
    for (kind, reader) in [
        (true, Box::new(stdout) as Box<dyn Read + Send>),
        (false, Box::new(stderr) as Box<dyn Read + Send>),
    ] {
        let sender = sender.clone();
        thread::spawn(move || {
            let mut bytes = vec![];
            let result = reader
                .take(512 * 1024 + 1)
                .read_to_end(&mut bytes)
                .map(|_| bytes);
            let _ = sender.send((kind, result));
        });
    }
    drop(sender);
    let deadline = Instant::now() + timeout;
    let result = (|| -> Result<serde_json::Value> {
        let mut stdout = vec![];
        let mut stderr = vec![];
        for _ in 0..2 {
            let (output, bytes) = receiver
                .recv_timeout(deadline.saturating_duration_since(Instant::now()))
                .map_err(|_| "Secure Boot observation timed out")?;
            let bytes = bytes.map_err(|error| error.to_string())?;
            if bytes.len() > 512 * 1024 {
                return Err("Secure Boot observation exceeded its output limit".into());
            }
            if output {
                stdout = bytes;
            } else {
                stderr = bytes;
            }
        }
        let status = loop {
            if let Some(status) = child.try_wait().map_err(|error| error.to_string())? {
                break status;
            }
            if Instant::now() >= deadline {
                return Err("Secure Boot observation timed out".into());
            }
            thread::sleep(Duration::from_millis(10));
        };
        if !status.success() {
            return Err(format!(
                "Secure Boot observation failed: {}",
                String::from_utf8_lossy(&stderr)
                    .chars()
                    .take(2048)
                    .collect::<String>()
            ));
        }
        let value: serde_json::Value =
            serde_json::from_slice(&stdout).map_err(|error| error.to_string())?;
        if !value.is_object() {
            return Err("invalid Secure Boot observation".into());
        }
        Ok(value)
    })();
    if result.is_err() {
        #[cfg(target_os = "linux")]
        // SAFETY: the child was launched in its own process group; only that read-only query is stopped.
        unsafe {
            libc::kill(-(child.id() as i32), libc::SIGKILL);
        }
        let _ = child.kill();
        let _ = child.wait();
    }
    result
}

fn packages(mode: &str, query: &str) -> Result<serde_json::Value> {
    if query.len() > 256
        || query.chars().any(char::is_control)
        || (mode == "search" && query.trim().is_empty())
    {
        return Err("invalid package query".into());
    }
    if mode == "details" && !distro_config::valid_package_name(query) {
        return Err("invalid package name".into());
    }
    #[cfg(all(target_os = "linux", feature = "native-alpm"))]
    return Ok(
        serde_json::json!({"schema_version":1,"packages":distro_transactions::native_alpm::NativePackages::query(mode,query)?}),
    );
    #[cfg(not(all(target_os = "linux", feature = "native-alpm")))]
    Err(NATIVE_REQUIRED.into())
}

fn adopt() -> Result<SystemConfig> {
    #[cfg(all(target_os = "linux", feature = "native-alpm"))]
    {
        use distro_transactions::{native_alpm::NativePackages, InstallReason};
        let installed = NativePackages::query("installed", "")?;
        let reasons = management_store::read_reasons(Path::new("/"))?;
        let mut config = installed_configuration()?;
        let supported: std::collections::BTreeSet<_> = installed
            .iter()
            .filter(|package| package.repository.is_some())
            .map(|package| package.name.clone())
            .collect();
        for package in &installed {
            if package.selectable && reasons.get(&package.name) == Some(&InstallReason::Explicit) {
                config.packages.insert(package.name.clone());
            }
        }
        for feature in [
            "core",
            "tools",
            "gamescope",
            "mangohud",
            "gamemode",
            "lutris",
            "streaming",
        ] {
            if config.gaming.contains("tools")
                && ["gamescope", "mangohud", "gamemode"].contains(&feature)
            {
                continue;
            }
            let packages = distro_config::gaming_feature_packages(feature)?;
            if packages.is_subset(&supported) {
                config.gaming.insert(feature.into());
                for package in packages {
                    config.packages.remove(&package);
                }
            }
        }
        config.validate()?;
        Ok(config)
    }
    #[cfg(not(all(target_os = "linux", feature = "native-alpm")))]
    Err(NATIVE_REQUIRED.into())
}

pub fn update(dry_run: bool, json: bool) -> Result<()> {
    let config = installed_configuration()?;
    let plan = resolve(config.clone())?;
    plan.validate()?;
    if dry_run {
        if json {
            emit(&plan)
        } else {
            println!(
                "{}No changes have been made.",
                crate::updates::format_plan(&plan)
            );
            Ok(())
        }
    } else {
        let receipt = ops::submit_reviewed(Submission {
            schema_version: 1,
            config,
            expected_plan: plan.fingerprint(),
        })?;
        emit(&receipt)
    }
}

pub fn gaming(feature: &str, enable: bool, dry_run: bool, json: bool) -> Result<()> {
    distro_config::gaming_feature_packages(feature)?;
    let mut config = installed_configuration()?;
    if enable {
        config.gaming.insert(feature.into());
    } else {
        config.gaming.remove(feature);
    }
    let report = preview(config.clone())?;
    if dry_run {
        if json {
            emit(&report)
        } else {
            if let Some(plan) = &report.plan {
                print!("{}", crate::updates::format_plan(plan));
            }
            for blocker in &report.blockers {
                println!("Blocked: {blocker}");
            }
            println!("No changes have been made.");
            Ok(())
        }
    } else if report.blockers.is_empty() {
        emit(&ops::submit_reviewed(Submission {
            schema_version: 1,
            config,
            expected_plan: report.plan_id,
        })?)
    } else {
        Err(report.blockers.join("; "))
    }
}

pub fn run(args: &[String]) -> Result<()> {
    let words: Vec<_> = args.iter().map(String::as_str).collect();
    match words.as_slice() {
        [] | ["--help"] => {
            println!("{HELP}");
            Ok(())
        }
        ["status", "--json"] | ["status"] => emit(&status()?),
        ["features", "--json"] | ["features"] => emit(&features()?),
        ["export", "--json"] | ["export"] => {
            emit(&configuration_response(installed_configuration()?)?)
        }
        ["adopt", "--json"] | ["adopt"] => emit(&configuration_response(adopt()?)?),
        ["parse", "--stdin", "--json"] => emit(&configuration_response(parse_system_toml(
            &read_bounded(std::io::stdin().lock())?,
        )?)?),
        ["plan" | "diff", "--stdin", "--json"] => emit(&preview(parse_configuration(
            &read_bounded(std::io::stdin().lock())?,
        )?)?),
        ["plan" | "diff", path] | ["plan" | "diff", path, "--json"] => {
            emit(&preview(read_configuration_file(path)?)?)
        }
        ["apply", path, "--expect-plan", digest]
        | ["apply", path, "--expect-plan", digest, "--json"] => {
            emit(&ops::submit_reviewed(Submission {
                schema_version: 1,
                config: read_configuration_file(path)?,
                expected_plan: (*digest).into(),
            })?)
        }
        ["submit", "--json"] => emit(&ops::submit(parse_submission(&read_bounded(
            std::io::stdin().lock(),
        )?)?)?),
        ["worker", id] => ops::worker(id),
        ["worker-finished", id] => ops::worker_finished(id),
        ["operation", id, "--json"] => emit(&ops::operation(id)?),
        ["packages", "installed", "--json"] => emit(&packages("installed", "")?),
        ["packages", mode @ ("search" | "details"), query, "--json"] => {
            emit(&packages(mode, query)?)
        }
        _ => Err(format!("unsupported system arguments\n{HELP}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn submission_requires_exact_bounded_intent_and_digest() {
        let request = serde_json::json!({"schema_version":1,"config":SystemConfig::default(),"expected_plan":format!("sha256:{}","a".repeat(64))});
        parse_submission(&request.to_string()).unwrap();
        for changed in [
            serde_json::json!({"schema_version":2,"config":SystemConfig::default(),"expected_plan":format!("sha256:{}","a".repeat(64))}),
            serde_json::json!({"schema_version":1,"config":SystemConfig::default(),"expected_plan":"../../root"}),
            serde_json::json!({"schema_version":1,"config":SystemConfig::default(),"expected_plan":format!("sha256:{}","a".repeat(64)),"command":"touch /x"}),
        ] {
            assert!(parse_submission(&changed.to_string()).is_err());
        }
        assert!(read_bounded(&b"\xff"[..]).is_err());
        assert!(read_bounded(&vec![b' '; MAX_SYSTEM_CONFIG_BYTES + 1][..]).is_err());
        let duplicate = request
            .to_string()
            .replace("\"packages\":[]", "\"packages\":[\"steam\",\"steam\"]");
        assert!(parse_submission(&duplicate).is_err());
    }
    #[test]
    fn export_and_parse_share_the_same_configuration() {
        let response = configuration_response(SystemConfig::default()).unwrap();
        let config = parse_system_toml(response["toml"].as_str().unwrap()).unwrap();
        assert_eq!(config, SystemConfig::default());
        assert_eq!(response["schema_version"], 1);
    }

    #[test]
    fn preview_disables_noops_live_sessions_pending_history_and_active_workers() {
        use distro_transactions::{CurrentSystemState, PackagePlan, TransactionRecord};
        let current = CurrentSystemState::new(Default::default());
        let plan = ExecutionPlan::new(
            current.clone(),
            PackagePlan {
                changes: vec![],
                targets: vec![],
                download_bytes: 0,
                installed_delta_bytes: Some(0),
            },
        );
        let noop = preview_observed(Ok(plan.clone()), false, Ok(vec![]), Ok(None)).unwrap();
        assert!(!noop.executable);
        assert!(noop.blockers.is_empty());
        let management = distro_transactions::reconcile(
            None,
            &current,
            &Default::default(),
            &current,
            &Default::default(),
            &SystemConfig::default(),
            &Default::default(),
            &Default::default(),
        )
        .unwrap();
        let plan = plan.with_management(management);
        assert!(
            preview_observed(Ok(plan.clone()), false, Ok(vec![]), Ok(None))
                .unwrap()
                .executable
        );
        assert!(
            !preview_observed(Ok(plan.clone()), true, Ok(vec![]), Ok(None))
                .unwrap()
                .executable
        );
        assert!(
            !preview_observed(
                Ok(plan.clone()),
                false,
                Ok(vec![TransactionRecord::new(plan.clone())]),
                Ok(None)
            )
            .unwrap()
            .executable
        );
        let active = ops::Operation {
            schema_version: 1,
            operation_id: "a".repeat(32),
            state: "queued".into(),
            transaction: None,
            error: None,
        };
        assert!(
            !preview_observed(Ok(plan), false, Ok(vec![]), Ok(Some(active)))
                .unwrap()
                .executable
        );
        let blocked =
            preview_observed(Err("invalid signature".into()), false, Ok(vec![]), Ok(None)).unwrap();
        assert!(!blocked.executable && blocked.plan.is_none() && blocked.plan_id.is_empty());
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn security_observation_keeps_diagnostics_separate_and_bounds_output_and_time() {
        use std::{process::Command, time::Duration};
        let invoke = |script: &str, timeout: Duration| {
            let mut command = Command::new("/bin/sh");
            command.args(["-c", script]);
            query_security_command(command, timeout)
        };
        let result = invoke(
            "printf warning >&2; printf '%s' '{\"secure_boot\":true}'",
            Duration::from_secs(2),
        )
        .unwrap();
        assert_eq!(result["secure_boot"], true);
        assert!(invoke("head -c 600000 /dev/zero", Duration::from_secs(2))
            .unwrap_err()
            .contains("output limit"));
        assert!(invoke("sleep 5", Duration::from_millis(50))
            .unwrap_err()
            .contains("timed out"));
        assert!(
            invoke("printf 'bad signature' >&2; exit 1", Duration::from_secs(2))
                .unwrap_err()
                .contains("bad signature")
        );
    }
}
