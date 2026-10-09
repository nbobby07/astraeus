//! Gaming observations and feature proposals. This module has no mutation backend.
mod graphics;
mod probe;
mod proton;

use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub use probe::{collect, installed_packages};
pub use proton::{discover_tools, Tool};

pub const HELP: &str = "Gaming setup (no automatic installation yet)
  distroctl gaming status [--probe] [--json]
  distroctl gaming doctor [--probe] [--json]
  distroctl gaming enable [core|tools|gamescope|mangohud|gamemode|heroic|lutris|streaming] [--dry-run] [--json]
  distroctl gaming disable [same feature] [--dry-run] [--json]
  distroctl gaming mangohud-config

Core proposes Steam and its runtime prerequisites. Tools and launchers are optional.
Start with doctor, then enable --dry-run to inspect requested changes.
Enable/disable always refuse execution: targeted package transactions are not supported.
Dry-run prints a blocked proposal, not a complete pacman dependency transaction.
No packages, repositories, user configuration or boot settings are changed.
--probe explicitly runs bounded, unprivileged Vulkan clear/readback tests.
After supported setup, launch Steam from your desktop and select Proton per game.
Windows game compatibility depends on the game, DRM and anti-cheat support.";

pub const MANGOHUD_CONFIG: &str = "fps\nframetime\ngpu_stats\ncpu_stats\nposition=top-left\n";
pub const TRANSACTION_BLOCK: &str = "The transaction backend only supports synchronized upgrades. Targeted install/remove needs dependency resolution, install-reason tracking, snapshot/boot preservation and rollback integration. No changes were made.";

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    NotInstalled,
    Installed,
    Configured,
    RuntimeVerified,
    Unsupported,
    #[default]
    Unknown,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Runtime {
    #[default]
    Untested,
    Passed,
    Failed,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Check {
    pub state: State,
    pub runtime: Runtime,
    pub detail: String,
}

impl Check {
    pub fn new(state: State, detail: impl Into<String>) -> Self {
        Self {
            state,
            runtime: Runtime::Untested,
            detail: detail.into(),
        }
    }
    pub fn available(&self) -> bool {
        matches!(
            self.state,
            State::Installed | State::Configured | State::RuntimeVerified
        ) && self.runtime != Runtime::Failed
    }
}

/// The graphics owner supplies evidence, including the selected GPU and test scope in detail.
/// Loader/package presence alone must not produce RuntimeVerified.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Graphics {
    pub acceleration: Check,
    pub vulkan64: Check,
    pub vulkan32: Check,
    pub vrr: Check,
    pub hdr: Check,
}

pub trait GraphicsProvider {
    fn readiness(&self) -> Graphics;
    fn evidence(&self) -> Option<&distro_graphics::GraphicsReport> {
        None
    }
}

pub struct UnavailableGraphics;
impl GraphicsProvider for UnavailableGraphics {
    fn readiness(&self) -> Graphics {
        let unknown = Check::new(
            State::Unknown,
            "Graphics provider is not connected; no rendering test performed",
        );
        Graphics {
            acceleration: unknown.clone(),
            vulkan64: unknown.clone(),
            vulkan32: unknown.clone(),
            vrr: unknown.clone(),
            hdr: unknown,
        }
    }
}

#[derive(Debug, Default)]
pub struct Observations {
    pub packages: Option<BTreeMap<String, String>>,
    pub repositories: Option<BTreeSet<String>>,
    pub session_type: Option<String>,
    pub display: bool,
    pub wayland_display: bool,
    pub session_bus: bool,
    pub steam_launcher: Option<bool>,
    pub tools: Vec<Tool>,
    pub tools_complete: bool,
    pub mangohud_config: Check,
    pub issues: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Report {
    pub schema_version: u32,
    pub checks: BTreeMap<String, Check>,
    pub tools: Vec<Tool>,
    pub warnings: Vec<String>,
    pub next_steps: Vec<String>,
    #[serde(default)]
    pub graphics: Option<distro_graphics::GraphicsReport>,
}

fn package(obs: &Observations, name: &str) -> Check {
    match &obs.packages {
        None => Check::new(State::Unknown, "Package database unavailable"),
        Some(packages) => match packages.get(name) {
            Some(version) => Check::new(
                State::Installed,
                format!("{name} {version}; execution untested"),
            ),
            None => Check::new(
                State::NotInstalled,
                format!("{name} is absent from the package database"),
            ),
        },
    }
}

pub fn report(obs: &Observations, provider: &impl GraphicsProvider) -> Report {
    let graphics = provider.readiness();
    let mut checks: BTreeMap<String, Check> = BTreeMap::from([
        ("graphics_acceleration".into(), graphics.acceleration),
        ("vulkan64".into(), graphics.vulkan64),
        ("vulkan32".into(), graphics.vulkan32),
        ("vrr".into(), graphics.vrr),
        ("hdr".into(), graphics.hdr),
    ]);
    for name in [
        "steam",
        "steam-devices",
        "lib32-glibc",
        "lib32-gcc-libs",
        "lib32-alsa-plugins",
        "lib32-pipewire",
        "xorg-xwayland",
        "gamescope",
        "mangohud",
        "lib32-mangohud",
        "gamemode",
        "lib32-gamemode",
        "lutris",
        "obs-studio",
    ] {
        checks.insert(name.into(), package(obs, name));
    }
    for dependency in &catalog().packages["steam"].depends {
        if dependency.starts_with("lib32-")
            && !matches!(
                dependency.as_str(),
                "lib32-libgl" | "lib32-vulkan-driver" | "lib32-vulkan-icd-loader"
            )
        {
            checks.insert(dependency.clone(), package(obs, dependency));
        }
    }
    checks.insert("steam_launcher".into(), match obs.steam_launcher {
        Some(true) => Check::new(State::Installed, "/usr/bin/steam executable file present; process startup untested"),
        Some(false) => Check::new(State::NotInstalled, "/usr/bin/steam missing or not executable; an installed package alone cannot launch Steam"),
        None => Check::new(State::Unknown, "Steam launcher could not be inspected"),
    });
    checks.insert("steam_runtime".into(), Check::new(State::Unknown, "Steam downloads/updates its runtime on first launch; package presence does not verify client startup or pressure-vessel"));
    for (key, kind) in [
        ("proton", "steam"),
        ("proton_ge", "ge"),
        ("proton_custom", "custom"),
    ] {
        let found = obs.tools.iter().any(|t| t.kind == kind);
        checks.insert(key.into(), Check::new(
            if found { State::Installed } else if obs.tools_complete { State::NotInstalled } else { State::Unknown },
            if found { "Tool metadata and launcher present; version claims untrusted, runtime and provenance unverified" }
            else { "No matching tool observed in inspected locations; extra libraries and Flatpak installations may need separate inspection" },
        ));
    }
    checks.insert("mangohud_config".into(), obs.mangohud_config.clone());
    checks.insert("controllers".into(), Check::new(State::Unknown, "steam-devices supplies udev policy when installed; controller/uinput access and Steam Input require a user-session device test"));
    let session = match obs.session_type.as_deref() {
        Some("wayland") if obs.wayland_display && obs.display && obs.session_bus && checks["xorg-xwayland"].available() => Check::new(State::Configured, "Wayland, X display, session bus and XWayland package observed; server connection/permissions untested"),
        Some("x11") if obs.display && obs.session_bus => Check::new(State::Configured, "X11 display and session bus advertised; connection/permissions untested"),
        Some("tty") => Check::new(State::Unsupported, "Headless/TTY session; run Steam as your desktop user"),
        _ if !obs.display && !obs.wayland_display => Check::new(State::Unsupported, "No graphical display advertised; Steam startup cannot be verified here"),
        _ => Check::new(State::Unknown, "Incomplete session environment; Wayland Steam needs XWayland, DISPLAY and a user session bus"),
    };
    checks.insert("session".into(), session);
    let mut warnings = obs.issues.clone();
    if let Some(evidence) = provider.evidence() {
        warnings.extend(
            evidence
                .issues
                .iter()
                .map(|issue| format!("Graphics {}: {}", issue.code, issue.message)),
        );
    }
    if !checks["graphics_acceleration"].available()
        || checks["graphics_acceleration"].runtime != Runtime::Passed
    {
        warnings.push("Physical GPU rendering has not been validated by this report.".into());
    }
    warnings.push("Installed/configured does not mean runtime verified. No games or services are launched by status/doctor.".into());
    warnings.push("HDR and VRR depend on GPU, driver, compositor, display and game; Gamescope installation proves neither.".into());
    let mut next_steps = vec![];
    for (name, check) in &checks {
        if matches!(
            name.as_str(),
            "vulkan64" | "vulkan32" | "graphics_acceleration"
        ) && !check.available()
        {
            next_steps.push(format!(
                "Resolve {name} with the graphics provider before launching games."
            ));
        }
    }
    if !checks["steam"].available() || !checks["steam_launcher"].available() {
        next_steps.push("Inspect distroctl gaming enable core --dry-run; package execution is currently blocked.".into());
    }
    if checks
        .iter()
        .any(|(name, check)| name.starts_with("lib32-") && !check.available())
    {
        next_steps.push("Some 32-bit runtime packages are absent or unknown. Inspect core --dry-run and have the transaction resolver include Steam's complete dependencies; graphics libraries/providers belong to the graphics adapter.".into());
    }
    next_steps.push("In a working desktop session, open Steam, allow its runtime setup, then use Settings > Compatibility and each game's Properties > Compatibility to select a Steam-managed Proton version.".into());
    next_steps.push("Optional per-game launch options: mangohud %command%, gamemoderun %command%, or gamescope -w 1280 -h 720 -r 60 -- %command%. Test each separately; remove the option to revert.".into());
    Report {
        schema_version: 1,
        checks,
        tools: obs.tools.clone(),
        warnings,
        next_steps,
        graphics: provider.evidence().cloned(),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Package {
    pub repository: String,
    pub version: String,
    pub sha256: String,
    pub depends: Vec<String>,
    pub provides: Vec<String>,
}

#[derive(Debug, Deserialize)]
pub struct Catalog {
    pub schema_version: u32,
    pub archive_date: String,
    pub databases: BTreeMap<String, String>,
    pub profiles: BTreeMap<String, Vec<String>>,
    pub packages: BTreeMap<String, Package>,
}

pub fn catalog() -> Catalog {
    serde_json::from_str(include_str!("catalog.json")).expect("tested bundled gaming catalog")
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Request {
    pub name: String,
    pub pinned: Package,
    pub installed_version: Option<String>,
    pub action: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Proposal {
    pub schema_version: u32,
    pub feature: String,
    pub operation: String,
    pub archive_date: String,
    pub executable: bool,
    pub dependency_resolution: String,
    pub requests: Vec<Request>,
    pub graphics_requirements: Vec<String>,
    pub flatpak_requests: Vec<String>,
    pub blockers: Vec<String>,
}

pub fn plan(
    feature: &str,
    enable: bool,
    obs: &Observations,
    provider: &impl GraphicsProvider,
) -> Result<Proposal, String> {
    let catalog = catalog();
    let names = catalog
        .profiles
        .get(feature)
        .ok_or_else(|| format!("unsupported gaming feature: {feature}"))?;
    let mut blockers = vec![TRANSACTION_BLOCK.into()];
    if obs.packages.is_none() {
        blockers.push("Installed package state unavailable; requested actions are unknown.".into());
    }
    let mut requests = vec![];
    for name in names.iter().collect::<BTreeSet<_>>() {
        let pinned = catalog.packages[name].clone();
        let installed = obs.packages.as_ref().and_then(|p| p.get(name)).cloned();
        let action = match (&obs.packages, &installed, enable) {
            (None, _, _) => "unknown",
            (_, None, true) => "install_requested",
            (_, Some(_), true) => "keep_installed",
            (_, None, false) => "absent",
            (_, Some(_), false) => "removal_review_required",
        };
        if enable
            && obs
                .repositories
                .as_ref()
                .is_none_or(|repos| !repos.contains(&pinned.repository))
        {
            let reason = format!("Repository {} is absent or unknown; pinned configuration/signature verification belongs to repository integration.", pinned.repository);
            if !blockers.contains(&reason) {
                blockers.push(reason);
            }
        }
        requests.push(Request {
            name: name.clone(),
            pinned,
            installed_version: installed,
            action: action.into(),
        });
    }
    let graphics_requirements =
        if matches!(feature, "core" | "tools" | "mangohud" | "lutris" | "heroic") {
            vec![
                "vulkan64".into(),
                "vulkan32".into(),
                "graphics_acceleration".into(),
            ]
        } else if feature == "gamescope" {
            vec!["vulkan64".into(), "graphics_acceleration".into()]
        } else {
            vec![]
        };
    let readiness = report(obs, provider);
    if enable {
        for requirement in &graphics_requirements {
            if !readiness.checks[requirement].available() {
                blockers.push(format!("Graphics prerequisite {requirement} is missing, unsupported, failed or unknown; the graphics owner must resolve vendor ICDs and 32-bit graphics dependencies."));
            }
        }
    } else {
        blockers.push("No feature ownership ledger exists. Shared packages, manual installs, dependents and user game data must be preserved; this is not an approved removal set.".into());
    }
    let flatpak_requests = if feature == "heroic" {
        blockers.push("Heroic requires a reviewed Flathub remote with signature verification, application ID/origin/commit and permission review; no Flatpak operation is performed.".into());
        vec!["com.heroicgameslauncher.hgl".into()]
    } else {
        vec![]
    };
    Ok(Proposal { schema_version: 1, feature: feature.into(), operation: if enable { "enable" } else { "disable" }.into(), archive_date: catalog.archive_date, executable: false, dependency_resolution: "unresolved; direct feature requests only; use the future transaction resolver for full dependencies, conflicts, providers and sizes".into(), requests, graphics_requirements, flatpak_requests, blockers })
}

fn safe(text: &str) -> String {
    text.chars()
        .flat_map(|c| {
            if c.is_control() {
                c.escape_default().collect::<Vec<_>>()
            } else {
                vec![c]
            }
        })
        .collect()
}

pub fn format_report(report: &Report, doctor: bool) -> String {
    let mut text = String::from("Gaming Readiness\n\n");
    if let Some(graphics) = &report.graphics {
        text.push_str(
            &distro_graphics::format_report(graphics)
                .lines()
                .map(safe)
                .collect::<Vec<_>>()
                .join("\n"),
        );
        text.push('\n');
    }
    for (name, check) in &report.checks {
        let state = serde_json::to_value(check.state).unwrap();
        let runtime = serde_json::to_value(check.runtime).unwrap();
        text.push_str(&format!(
            "{name:<24} {:<18} runtime {}\n  {}\n",
            state.as_str().unwrap(),
            runtime.as_str().unwrap(),
            safe(&check.detail)
        ));
    }
    for warning in &report.warnings {
        text.push_str(&format!("Warning: {}\n", safe(warning)));
    }
    if doctor {
        for step in &report.next_steps {
            text.push_str(&format!("Next: {}\n", safe(step)));
        }
    }
    text
}

pub fn run(args: &[String]) -> Result<(), String> {
    let words: Vec<_> = args.iter().map(String::as_str).collect();
    match words.as_slice() {
        ["--help"] | [] => println!("{HELP}"),
        ["mangohud-config"] => print!("{MANGOHUD_CONFIG}"),
        [action @ ("status" | "doctor"), rest @ ..] => {
            let mut json = false;
            let mut probe = false;
            for word in rest {
                match *word {
                    "--json" if !json => json = true,
                    "--probe" if !probe => probe = true,
                    _ => return Err(format!("unsupported gaming arguments\n{HELP}")),
                }
            }
            let report = report(&collect(), &distro_graphics::probe(probe));
            if json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&report).map_err(|e| e.to_string())?
                );
            } else {
                print!("{}", format_report(&report, *action == "doctor"));
            }
        }
        [action @ ("enable" | "disable"), rest @ ..] => {
            let mut feature = None;
            let mut json = false;
            let mut dry_run = false;
            for word in rest {
                match *word {
                    "--json" if !json => json = true,
                    "--dry-run" if !dry_run => dry_run = true,
                    name if !name.starts_with('-') && feature.is_none() => feature = Some(name),
                    _ => return Err(format!("unsupported gaming arguments\n{HELP}")),
                }
            }
            let proposal = plan(
                feature.unwrap_or("core"),
                *action == "enable",
                &collect(),
                &distro_graphics::probe(false),
            )?;
            if json {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&proposal).map_err(|e| e.to_string())?
                );
            } else {
                println!(
                    "Gaming {} {}: BLOCKED\n{}",
                    proposal.operation, proposal.feature, proposal.dependency_resolution
                );
                for request in &proposal.requests {
                    println!(
                        "  {}: {} (archive {}/{}, installed {})",
                        request.name,
                        request.action,
                        request.pinned.repository,
                        request.pinned.version,
                        safe(
                            request
                                .installed_version
                                .as_deref()
                                .unwrap_or("absent or unknown")
                        )
                    );
                }
                for app in &proposal.flatpak_requests {
                    println!("  Optional user Flatpak request: {app}");
                }
                for blocker in &proposal.blockers {
                    println!("Blocked: {blocker}");
                }
            }
            if !dry_run {
                return Err(TRANSACTION_BLOCK.into());
            }
        }
        _ => return Err(format!("unsupported gaming arguments\n{HELP}")),
    }
    Ok(())
}
