use std::process::Command;

#[test]
fn graphics_cli_is_read_only_and_schema_versioned() {
    let run = |args: &[&str]| {
        Command::new(env!("CARGO_BIN_EXE_distroctl"))
            .args(args)
            .output()
            .unwrap()
    };
    let output = run(&["graphics", "--json"]);
    assert!(output.status.success());
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["schema_version"], 1);
    assert!(report["issues"].is_array());
    assert_eq!(report["activation"], "unsupported");
    assert_eq!(report["native"]["enumeration"], "untested");
    let output = run(&["graphics"]);
    assert!(output.status.success());
    assert!(output.stdout.starts_with(b"Graphics\n"));
    for action in ["--install", "--activate", "--apply", "--bad"] {
        assert!(!run(&["graphics", action]).status.success());
    }
}
