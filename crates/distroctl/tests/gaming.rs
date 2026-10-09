use distroctl::gaming::*;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::PathBuf,
    process::Command,
};

struct GraphicsFixture(Graphics);
impl GraphicsProvider for GraphicsFixture {
    fn readiness(&self) -> Graphics {
        self.0.clone()
    }
}

fn graphics() -> GraphicsFixture {
    let installed = Check::new(State::Installed, "fixture: installed, not executed");
    GraphicsFixture(Graphics {
        acceleration: installed.clone(),
        vulkan64: installed.clone(),
        vulkan32: installed,
        ..Default::default()
    })
}

fn desktop() -> Observations {
    Observations {
        packages: Some(
            catalog()
                .packages
                .into_iter()
                .map(|(name, p)| (name, p.version))
                .collect(),
        ),
        repositories: Some(
            ["core", "extra", "multilib"]
                .into_iter()
                .map(str::to_owned)
                .collect(),
        ),
        session_type: Some("wayland".into()),
        display: true,
        wayland_display: true,
        session_bus: true,
        steam_launcher: Some(true),
        tools_complete: true,
        ..Default::default()
    }
}

#[test]
fn feature_requests_are_deterministic_and_optional() {
    let obs = Observations {
        packages: Some(BTreeMap::new()),
        ..Default::default()
    };
    let core = plan("core", true, &obs, &graphics()).unwrap();
    let names: Vec<_> = core.requests.iter().map(|r| r.name.as_str()).collect();
    assert!(names.contains(&"steam") && names.contains(&"lib32-glibc"));
    for optional in ["gamescope", "mangohud", "gamemode", "lutris", "obs-studio"] {
        assert!(!names.contains(&optional));
    }
    assert_eq!(
        names.iter().copied().collect::<BTreeSet<_>>().len(),
        names.len()
    );
    assert!(names.windows(2).all(|w| w[0] < w[1]));
    assert!(core
        .requests
        .iter()
        .all(|r| r.action == "install_requested"));
    assert_eq!(
        core.graphics_requirements,
        ["vulkan64", "vulkan32", "graphics_acceleration"]
    );
    let tools = plan("tools", true, &desktop(), &graphics()).unwrap();
    assert_eq!(tools.requests.len(), 5);
    assert!(tools.requests.iter().any(|p| p.name == "lib32-mangohud"));
    assert!(tools.requests.iter().all(|r| r.action == "keep_installed"));
    let heroic = plan("heroic", true, &obs, &graphics()).unwrap();
    assert!(heroic.requests.is_empty());
    assert_eq!(heroic.flatpak_requests, ["com.heroicgameslauncher.hgl"]);
    assert!(heroic.blockers.iter().any(|b| b.contains("signature")));
    assert_eq!(
        plan("lutris", true, &obs, &graphics()).unwrap().requests[0].name,
        "lutris"
    );
    assert!(plan("streaming", true, &obs, &graphics())
        .unwrap()
        .requests
        .iter()
        .any(|p| p.name == "obs-studio"));
}

#[test]
fn missing_or_failed_graphics_and_multilib_are_explicit_blockers() {
    for state in [State::NotInstalled, State::Unknown, State::Unsupported] {
        for bitness in [32, 64] {
            let mut gpu = graphics();
            if bitness == 32 {
                gpu.0.vulkan32.state = state;
            } else {
                gpu.0.vulkan64.state = state;
            }
            let proposal = plan("core", true, &desktop(), &gpu).unwrap();
            assert!(proposal
                .blockers
                .iter()
                .any(|b| b.contains(&format!("vulkan{bitness}"))));
        }
    }
    let mut gpu = graphics();
    gpu.0.vulkan32.runtime = Runtime::Failed;
    assert!(plan("core", true, &desktop(), &gpu)
        .unwrap()
        .blockers
        .iter()
        .any(|b| b.contains("vulkan32")));
    let mut obs = desktop();
    obs.repositories.as_mut().unwrap().remove("multilib");
    assert!(plan("core", true, &obs, &graphics())
        .unwrap()
        .blockers
        .iter()
        .any(|b| b.contains("Repository multilib")));
}

#[test]
fn unknown_package_state_never_becomes_missing_or_a_safe_plan() {
    let obs = Observations::default();
    let report = report(&obs, &UnavailableGraphics);
    assert_eq!(report.checks["steam"].state, State::Unknown);
    assert_eq!(report.checks["vulkan32"].state, State::Unknown);
    assert_eq!(report.checks["proton"].state, State::Unknown);
    let proposal = plan("core", true, &obs, &UnavailableGraphics).unwrap();
    assert!(proposal.requests.iter().all(|r| r.action == "unknown"));
    assert!(!proposal.executable);
}

#[test]
fn steam_missing_broken_and_incomplete_32_bit_stack_are_distinct() {
    let mut obs = desktop();
    obs.packages.as_mut().unwrap().remove("steam");
    assert_eq!(
        report(&obs, &graphics()).checks["steam"].state,
        State::NotInstalled
    );
    obs = desktop();
    obs.steam_launcher = Some(false);
    let broken = report(&obs, &graphics());
    assert_eq!(broken.checks["steam"].state, State::Installed);
    assert_eq!(broken.checks["steam_launcher"].state, State::NotInstalled);
    assert_eq!(broken.checks["steam"].runtime, Runtime::Untested);
    assert_eq!(broken.checks["steam_runtime"].state, State::Unknown);
    obs.packages.as_mut().unwrap().remove("lib32-glibc");
    let missing = report(&obs, &graphics());
    assert_eq!(missing.checks["lib32-glibc"].state, State::NotInstalled);
    assert_eq!(missing.checks["lib32-nss"].state, State::NotInstalled);
    assert!(missing.next_steps.iter().any(|s| s.contains("32-bit")));
}

#[test]
fn optional_tools_do_not_prove_execution_hdr_or_vrr() {
    let mut obs = desktop();
    let present = report(&obs, &graphics());
    for name in [
        "gamescope",
        "mangohud",
        "lib32-mangohud",
        "gamemode",
        "lib32-gamemode",
    ] {
        assert_eq!(present.checks[name].state, State::Installed);
        assert_eq!(present.checks[name].runtime, Runtime::Untested);
        obs.packages.as_mut().unwrap().remove(name);
    }
    let absent = report(&obs, &graphics());
    assert_eq!(absent.checks["gamescope"].state, State::NotInstalled);
    assert_eq!(absent.checks["gamemode"].state, State::NotInstalled);
    for name in ["hdr", "vrr", "controllers"] {
        assert_eq!(present.checks[name].state, State::Unknown);
    }
}

#[test]
fn headless_and_incomplete_wayland_sessions_are_not_ready() {
    let mut obs = desktop();
    assert_eq!(
        report(&obs, &graphics()).checks["session"].state,
        State::Configured
    );
    obs.display = false;
    assert_eq!(
        report(&obs, &graphics()).checks["session"].state,
        State::Unknown
    );
    obs.wayland_display = false;
    assert_eq!(
        report(&obs, &graphics()).checks["session"].state,
        State::Unsupported
    );
    obs = desktop();
    obs.session_bus = false;
    assert_eq!(
        report(&obs, &graphics()).checks["session"].state,
        State::Unknown
    );
    obs = desktop();
    obs.packages.as_mut().unwrap().remove("xorg-xwayland");
    assert_eq!(
        report(&obs, &graphics()).checks["session"].state,
        State::Unknown
    );
    obs.session_type = Some("tty".into());
    assert_eq!(
        report(&obs, &graphics()).checks["session"].state,
        State::Unsupported
    );
}

#[test]
fn no_proposal_can_execute_or_guess_removal_ownership() {
    for feature in catalog().profiles.keys() {
        for enable in [true, false] {
            let proposal = plan(feature, enable, &desktop(), &graphics()).unwrap();
            assert!(!proposal.executable);
            assert!(proposal.dependency_resolution.starts_with("unresolved"));
            assert!(proposal.blockers.iter().any(|b| b == TRANSACTION_BLOCK));
            if !enable {
                assert!(proposal
                    .requests
                    .iter()
                    .all(|r| r.action == "removal_review_required"));
                assert!(proposal.blockers.iter().any(|b| b.contains("ownership")));
            }
        }
    }
    assert!(plan("overclock", true, &desktop(), &graphics()).is_err());
    assert!(plan("proton-ge-download", true, &desktop(), &graphics()).is_err());
}

struct Tree(PathBuf);
impl Tree {
    fn new(name: &str) -> Self {
        let path =
            std::env::temp_dir().join(format!("astraeus-gaming-{name}-{}", std::process::id()));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn write(&self, path: &str, text: &str) {
        let path = self.0.join(path);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }
}
impl Drop for Tree {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn proton_and_ge_discovery_is_metadata_only_and_deduplicated() {
    let tree = Tree::new("discovery");
    tree.write(
        "steam/steamapps/common/Proton Test/proton",
        "must never execute",
    );
    tree.write(
        "steam/steamapps/common/Proton Test/toolmanifest.vdf",
        "\"manifest\" { \"version\" \"2\" }",
    );
    tree.write(
        "steam/steamapps/common/Proton Test/version",
        "123 proton-fixture\n",
    );
    tree.write(
        "steam/compatibilitytools.d/GE-Proton-test/proton",
        "must never execute",
    );
    tree.write("steam/compatibilitytools.d/GE-Proton-test/compatibilitytool.vdf", "\"compatibilitytools\" { \"compat_tools\" { \"GE-Proton-test\" { \"display_name\" \"fixture\" } } }");
    tree.write(
        "steam/compatibilitytools.d/GE-Proton-empty/README",
        "directory alone is not a tool",
    );
    let root = tree.0.join("steam");
    let (tools, issues) = discover_tools(&[root.clone(), root]);
    assert!(issues.is_empty(), "{issues:?}");
    assert_eq!(tools.len(), 2);
    assert!(tools.iter().any(|t| t.kind == "ge"));
    assert!(tools
        .iter()
        .any(|t| t.kind == "steam" && t.version.as_deref() == Some("123 proton-fixture")));
    let obs = Observations {
        tools,
        tools_complete: true,
        ..desktop()
    };
    let report = report(&obs, &graphics());
    for key in ["proton", "proton_ge"] {
        assert_eq!(report.checks[key].state, State::Installed);
        assert_eq!(report.checks[key].runtime, Runtime::Untested);
    }
    assert_eq!(report.checks["proton_custom"].state, State::NotInstalled);
}

#[test]
fn extra_libraries_and_malformed_metadata_are_handled_without_execution() {
    let tree = Tree::new("libraries");
    tree.write(
        "external/steamapps/common/Proton Fixture/proton",
        "never execute",
    );
    tree.write(
        "external/steamapps/common/Proton Fixture/toolmanifest.vdf",
        "\"manifest\" { }",
    );
    let library = tree
        .0
        .join("external")
        .to_string_lossy()
        .replace('\\', "\\\\");
    tree.write(
        "steam/steamapps/libraryfolders.vdf",
        &format!("\"libraryfolders\" {{ \"0\" {{ \"path\" \"{library}\" }} }}"),
    );
    let roots = [tree.0.join("steam")];
    let (tools, issues) = discover_tools(&roots);
    assert!(issues.is_empty(), "{issues:?}");
    assert_eq!(tools.len(), 1);
    tree.write(
        "steam/steamapps/libraryfolders.vdf",
        "\"libraryfolders\" { \"0\" { \"path\" \"../escape\" } }",
    );
    let (tools, issues) = discover_tools(&roots);
    assert!(tools.is_empty());
    assert!(!issues.is_empty());
    tree.write(
        "steam/compatibilitytools.d/GE-Proton-broken/proton",
        "never execute",
    );
    tree.write(
        "steam/compatibilitytools.d/GE-Proton-broken/compatibilitytool.vdf",
        "\"unterminated",
    );
    assert!(discover_tools(&roots)
        .1
        .iter()
        .any(|e| e.contains("unterminated")));
}

#[cfg(unix)]
#[test]
fn metadata_symlinks_and_nonregular_files_are_not_read() {
    let tree = Tree::new("links");
    tree.write(
        "steam/compatibilitytools.d/GE-Proton-link/proton",
        "never execute",
    );
    tree.write("private", "must not appear in output");
    std::os::unix::fs::symlink(
        tree.0.join("private"),
        tree.0
            .join("steam/compatibilitytools.d/GE-Proton-link/compatibilitytool.vdf"),
    )
    .unwrap();
    let (tools, issues) = discover_tools(&[tree.0.join("steam")]);
    assert!(tools.is_empty());
    assert!(issues.iter().any(|e| e.contains("regular file")));
    assert!(issues.iter().all(|e| !e.contains("must not appear")));
}

#[test]
fn package_probe_only_issues_read_only_query_and_preserves_failure() {
    use distro_transactions::pacman::{CommandOutput, CommandRunner};
    struct Query(bool);
    impl CommandRunner for Query {
        fn run(&mut self, program: &str, args: &[String]) -> Result<CommandOutput, String> {
            assert_eq!(program, "/usr/bin/pacman");
            assert_eq!(args, ["--query"]);
            Ok(CommandOutput {
                success: self.0,
                stdout: "steam 1.0.0.87-3\n".into(),
                stderr: String::new(),
            })
        }
    }
    assert_eq!(
        installed_packages(&mut Query(true)).unwrap()["steam"],
        "1.0.0.87-3"
    );
    assert!(installed_packages(&mut Query(false)).is_err());
}

#[test]
fn json_contract_and_text_do_not_invent_runtime_success() {
    let mut obs = desktop();
    obs.issues.push("untrusted\u{1b}[31m\ntext".into());
    let report = report(&obs, &UnavailableGraphics);
    let json = serde_json::to_value(&report).unwrap();
    let schema: serde_json::Value =
        serde_json::from_str(include_str!("../src/gaming/status.schema.json")).unwrap();
    for required in schema["required"].as_array().unwrap() {
        assert!(json.get(required.as_str().unwrap()).is_some());
    }
    assert_eq!(json["schema_version"], 1);
    assert!(json["checks"].is_object() && json["tools"].is_array());
    assert!(json["warnings"].is_array() && json["next_steps"].is_array());
    for check in json["checks"].as_object().unwrap().values() {
        assert!(check["state"].is_string() && check["detail"].is_string());
        assert_eq!(check["runtime"], "untested");
        assert!(schema["$defs"]["check"]["properties"]["state"]["enum"]
            .as_array()
            .unwrap()
            .contains(&check["state"]));
    }
    let _: Report = serde_json::from_value(json).unwrap();
    let text = format_report(&report, true);
    assert!(text.contains("Gaming Readiness") && text.contains("Next:"));
    assert!(!text.contains('\u{1b}'));
    assert!(text.contains("Physical GPU rendering has not been validated"));
    let proposal = plan("core", true, &obs, &UnavailableGraphics).unwrap();
    let json = serde_json::to_value(&proposal).unwrap();
    let schema: serde_json::Value =
        serde_json::from_str(include_str!("../src/gaming/plan.schema.json")).unwrap();
    for required in schema["required"].as_array().unwrap() {
        assert!(json.get(required.as_str().unwrap()).is_some());
    }
    assert_eq!(json["executable"], false);
    assert!(json["requests"][0]["pinned"]["depends"].is_array());
    let _: Proposal = serde_json::from_value(json).unwrap();
}

#[test]
fn cli_commands_refuse_mutation_and_reject_unsupported_options() {
    let run = |args: &[&str]| {
        Command::new(env!("CARGO_BIN_EXE_distroctl"))
            .arg("gaming")
            .args(args)
            .output()
            .unwrap()
    };
    for args in [&["status", "--json"][..], &["doctor", "--json"]] {
        let output = run(args);
        assert!(output.status.success());
        let report: Report = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(report.schema_version, 1);
    }
    assert!(String::from_utf8(run(&["doctor"]).stdout)
        .unwrap()
        .contains("Next:"));
    assert!(String::from_utf8(run(&["--help"]).stdout)
        .unwrap()
        .contains("no automatic installation"));
    assert_eq!(
        String::from_utf8(run(&["mangohud-config"]).stdout).unwrap(),
        MANGOHUD_CONFIG
    );
    for action in ["enable", "disable"] {
        let dry = run(&[action, "--dry-run", "--json"]);
        assert!(dry.status.success());
        let proposal: Proposal = serde_json::from_slice(&dry.stdout).unwrap();
        assert!(!proposal.executable);
        let blocked = run(&[action, "core", "--json"]);
        assert_eq!(blocked.status.code(), Some(1));
        assert!(String::from_utf8(blocked.stderr)
            .unwrap()
            .contains("only supports synchronized upgrades"));
        let _: Proposal = serde_json::from_slice(&blocked.stdout).unwrap();
    }
    for args in [
        &["status", "--execute"][..],
        &["doctor", "--json", "--json"],
        &["enable", "--dry-run", "--dry-run"],
        &["enable", "core", "tools"],
        &["enable", "overclock"],
        &["proton-ge", "download"],
        &["enable", "--execute"],
        &["disable", "--bad"],
    ] {
        let output = run(args);
        assert_eq!(output.status.code(), Some(1), "{args:?}");
        assert!(output.stdout.is_empty());
    }
}
