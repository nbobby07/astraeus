use std::process::Command;

#[test]
fn cli_contract() {
    let run = |args: &[&str]| {
        Command::new(env!("CARGO_BIN_EXE_distroctl"))
            .args(args)
            .output()
            .unwrap()
    };
    let info = run(&["info", "--json"]);
    assert!(info.status.success());
    let json: serde_json::Value = serde_json::from_slice(&info.stdout).unwrap();
    assert_eq!(json["build"]["architecture"], "x86_64");
    for command in ["status", "hardware"] {
        let text = run(&[command]);
        assert_eq!(text.status.code(), Some(0));
        assert!(text.stderr.is_empty());
        let text = String::from_utf8(text.stdout).unwrap();
        assert!(text.contains("CPU") && text.contains("Storage"));
        assert!(!text.trim_start().starts_with('{'));
        let output = run(&[command, "--json"]);
        assert!(output.status.success());
        let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
        if command == "status" {
            assert_eq!(value["schema_version"], 1);
            assert!(value["hardware"]["issues"].is_array());
            assert!(value.get("hostname").is_some());
        } else {
            assert_eq!(value["schema_version"], 1);
            assert!(value["cpu"]["architecture"].is_string());
            assert!(value["issues"].is_array());
        }
    }
    assert!(run(&["--help"]).status.success());
    assert!(run(&[
        "validate",
        concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../distro/branding/project.toml"
        )
    ])
    .status
    .success());
    for args in [
        &["apply"][..],
        &["info", "extra"],
        &["validate"],
        &["validate", "missing.toml"],
        &["status", "--bad"],
        &["hardware", "--json", "extra"],
    ] {
        let output = run(args);
        assert_eq!(output.status.code(), Some(1));
        assert!(!output.stderr.is_empty());
        assert!(output.stdout.is_empty());
    }
}
