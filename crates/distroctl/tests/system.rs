use std::{
    io::Write,
    process::{Command, Output, Stdio},
};

fn run(args: &[&str], input: &[u8]) -> Output {
    let mut child = Command::new(env!("CARGO_BIN_EXE_distroctl"))
        .arg("system")
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let _ = child.stdin.take().unwrap().write_all(input);
    child.wait_with_output().unwrap()
}

#[test]
fn json_cli_parses_user_configuration_and_never_accepts_unreviewed_mutation() {
    let parsed = run(
        &["parse", "--stdin", "--json"],
        b"schema_version=1\npackages=['steam']\n",
    );
    assert!(
        parsed.status.success(),
        "{}",
        String::from_utf8_lossy(&parsed.stderr)
    );
    let response: serde_json::Value = serde_json::from_slice(&parsed.stdout).unwrap();
    assert_eq!(response["schema_version"], 1);
    assert_eq!(
        response["configuration"]["packages"],
        serde_json::json!(["steam"])
    );
    let planned = run(
        &["plan", "--stdin", "--json"],
        &serde_json::to_vec(&response["configuration"]).unwrap(),
    );
    assert!(
        planned.status.success(),
        "{}",
        String::from_utf8_lossy(&planned.stderr)
    );
    let plan: serde_json::Value = serde_json::from_slice(&planned.stdout).unwrap();
    assert_eq!(plan["schema_version"], 1);
    assert!(plan["blockers"].is_array() && plan["warnings"].is_array());
    for args in [
        vec!["apply", "anything.toml"],
        vec!["apply", "anything.toml", "--yes"],
        vec!["worker", "../../escape"],
        vec!["worker-finished", "--help"],
        vec!["operation", "../requests", "--json"],
        vec!["operation", "../requests"],
        vec!["packages", "details", "--execute", "--json"],
        vec!["packages", "details", "--execute"],
    ] {
        let failed = run(&args, b"");
        assert!(!failed.status.success(), "{args:?}");
        assert!(failed.stdout.is_empty(), "{args:?}");
    }
    let failed=run(&["submit","--json"],br#"{"schema_version":1,"config":{"schema_version":1,"packages":[],"gaming":[],"providers":{}},"expected_plan":"not-reviewed","command":"touch /x"}"#);
    assert!(!failed.status.success() && failed.stdout.is_empty());
}

// Installed-state export reads the trusted Linux root. distro-config covers portable TOML round trips.
#[cfg(target_os = "linux")]
#[test]
fn plain_export_is_importable_toml_and_matches_json_export() {
    let plain = run(&["export"], b"");
    assert!(
        plain.status.success(),
        "{}",
        String::from_utf8_lossy(&plain.stderr)
    );
    let config =
        distro_config::parse_system_toml(std::str::from_utf8(&plain.stdout).unwrap()).unwrap();
    let json = run(&["export", "--json"], b"");
    assert!(
        json.status.success(),
        "{}",
        String::from_utf8_lossy(&json.stderr)
    );
    let response: serde_json::Value = serde_json::from_slice(&json.stdout).unwrap();
    assert_eq!(response["schema_version"], 1);
    assert_eq!(
        response["configuration"],
        serde_json::to_value(config).unwrap()
    );
    assert_eq!(
        response["toml"],
        std::str::from_utf8(&plain.stdout).unwrap()
    );
}

#[test]
fn submission_rejects_malformed_and_oversized_input_before_platform_work() {
    for (input, diagnostic) in [
        (b"{".to_vec(), "EOF while parsing"),
        (vec![0xff], "system request must be UTF-8"),
        (
            vec![b' '; distro_config::MAX_SYSTEM_CONFIG_BYTES + 1],
            "system request exceeds 256 KiB",
        ),
    ] {
        let output = run(&["submit", "--json"], &input);
        assert!(!output.status.success() && output.stdout.is_empty());
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(stderr.contains(diagnostic), "{stderr}");
    }
    let mut request = serde_json::json!({"schema_version":1,
        "config":distro_config::SystemConfig::default(),
        "expected_plan":format!("sha256:{}", "a".repeat(64))});
    request["command"] = serde_json::json!("touch /x");
    let output = run(
        &["submit", "--json"],
        &serde_json::to_vec(&request).unwrap(),
    );
    assert!(!output.status.success() && output.stdout.is_empty());
    assert!(String::from_utf8_lossy(&output.stderr).contains("unknown field"));
}

#[test]
fn cli_bounds_toml_and_rejects_future_configuration() {
    for input in [
        b"schema_version=2\n".to_vec(),
        vec![b' '; distro_config::MAX_SYSTEM_CONFIG_BYTES + 1],
        vec![0xff],
    ] {
        let output = run(&["parse", "--stdin", "--json"], &input);
        assert!(!output.status.success() && output.stdout.is_empty());
    }
    let output = run(&["features", "--json"], b"");
    assert!(output.status.success());
    let catalog: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(catalog["features"].as_array().unwrap().len(), 7);
}
