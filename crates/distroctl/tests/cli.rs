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
    ] {
        let output = run(args);
        assert!(!output.status.success());
        assert!(!output.stderr.is_empty());
    }
}
