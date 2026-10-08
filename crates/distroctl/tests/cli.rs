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
        &["snapshot", "create", "--reason", "invalid"],
        &["snapshot", "list", "--execute"],
        &["snapshot", "show", "../escape"],
        &["snapshot", "create", "--dry-run", "--dry-run"],
        &["snapshot", "mark", "1", "known-good"],
        &["rollback", "1"],
        &["rollback", "1", "--execute", "--dry-run"],
        &["update", "--json"],
        &["update", "--dry-run", "--bad"],
        &["history", "--database"],
        &["boot", "set-default"],
        &["boot", "inspect", "../escape"],
        &["boot", "list", "--execute"],
        &["boot", "verify", "1", "--json", "--json"],
    ] {
        let output = run(args);
        assert_eq!(output.status.code(), Some(1));
        assert!(!output.stderr.is_empty());
        assert!(output.stdout.is_empty());
    }
    let help = run(&["boot", "--help"]);
    assert!(help.status.success());
    assert!(String::from_utf8(help.stdout)
        .unwrap()
        .contains("set-default"));
    for command in ["snapshot", "rollback"] {
        let help = run(&[command, "--help"]);
        assert!(help.status.success());
        assert!(String::from_utf8(help.stdout)
            .unwrap()
            .contains("--top-level"));
    }
}

#[test]
fn history_json_does_not_create_a_database() {
    let path = std::env::temp_dir().join(format!(
        "astraeus-missing-history-{}.sqlite",
        std::process::id()
    ));
    assert!(!path.exists());
    let output = Command::new(env!("CARGO_BIN_EXE_distroctl"))
        .args(["history", "--json", "--database", path.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&output.stdout).unwrap(),
        serde_json::json!([])
    );
    assert!(!path.exists());
}

#[test]
fn dry_run_and_history_share_structured_models() {
    use distro_transactions::*;
    struct ReadOnly;
    impl PackageBackend for ReadOnly {
        fn resolve(&mut self) -> Result<ExecutionPlan> {
            Ok(ExecutionPlan::new(
                CurrentSystemState::new(Default::default()),
                PackagePlan {
                    changes: vec![],
                    targets: vec![],
                    download_bytes: 0,
                    installed_delta_bytes: Some(0),
                },
            ))
        }
        fn prerequisites(&mut self, _: &ExecutionPlan) -> Result<()> {
            panic!("dry run must only resolve")
        }
        fn download(&mut self, _: &ExecutionPlan) -> Result<()> {
            panic!("dry run must not download")
        }
        fn verify(&mut self, _: &ExecutionPlan) -> Result<()> {
            panic!("dry run must not verify/download")
        }
        fn apply(&mut self, _: &ExecutionPlan) -> Result<()> {
            panic!("dry run must not apply")
        }
        fn current_state(&mut self) -> Result<CurrentSystemState> {
            panic!("use resolved state")
        }
    }
    let text = distroctl::updates::dry_run(&mut ReadOnly, false).unwrap();
    assert!(text.contains("No changes have been made."));
    let json: serde_json::Value =
        serde_json::from_str(&distroctl::updates::dry_run(&mut ReadOnly, true).unwrap()).unwrap();
    assert_eq!(json["schema_version"], 1);
    assert_eq!(json["snapshot_required"], false);
    let dir = std::env::temp_dir().join(format!("astraeus-cli-history-{}", std::process::id()));
    std::fs::create_dir(&dir).unwrap();
    let db = dir.join("history.sqlite");
    let mut session = UpdateSession::open(&db, &dir.join("update.lock")).unwrap();
    let mut record = TransactionRecord::new(ReadOnly.resolve().unwrap());
    session.insert(&mut record).unwrap();
    drop(session);
    let output = Command::new(env!("CARGO_BIN_EXE_distroctl"))
        .args(["history", "--database", db.to_str().unwrap(), "--json"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let records: Vec<TransactionRecord> = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(records, vec![record]);
    let output = Command::new(env!("CARGO_BIN_EXE_distroctl"))
        .args(["history", "--database", db.to_str().unwrap()])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(String::from_utf8(output.stdout)
        .unwrap()
        .contains("planned"));
    std::fs::remove_dir_all(dir).unwrap();
}
