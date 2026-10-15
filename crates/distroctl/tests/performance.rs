use std::process::Command;
#[test]
fn performance_queries_are_versioned_and_arguments_bounded() {
    let output = Command::new(env!("CARGO_BIN_EXE_distroctl"))
        .args(["performance", "status", "--json"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let v: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(v["schema_version"], 1);
    assert!(v["baseline_blockers"].is_array());
    assert!(v["sample"]["unavailable"].is_array());
    assert!(v.get("hostname").is_none());
    for args in [
        ["performance", "record", "--duration", "301"],
        ["performance", "baseline", "--command", "sh"],
        ["performance", "show", "../escape", "--json"],
    ] {
        let o = Command::new(env!("CARGO_BIN_EXE_distroctl"))
            .args(args)
            .output()
            .unwrap();
        assert!(!o.status.success());
        assert!(o.stdout.is_empty());
    }
}
#[cfg(target_os = "linux")]
#[test]
fn ordinary_user_recording_and_stop_leave_truthful_private_results() {
    if unsafe { libc::geteuid() } == 0 {
        return;
    }
    use std::{fs, io::BufRead, os::unix::fs::MetadataExt};
    let base = std::path::PathBuf::from(std::env::var_os("HOME").unwrap()).join(format!(
        ".astraeus-performance-fixture-{}",
        std::process::id()
    ));
    fs::create_dir(&base).unwrap();
    fs::set_permissions(&base, std::os::unix::fs::PermissionsExt::from_mode(0o700)).unwrap();
    let command = || {
        let mut c = Command::new(env!("CARGO_BIN_EXE_distroctl"));
        c.env("XDG_STATE_HOME", &base);
        c
    };
    let o = command()
        .args(["performance", "record", "--duration", "1", "--json"])
        .output()
        .unwrap();
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    let events: Vec<serde_json::Value> = String::from_utf8(o.stdout)
        .unwrap()
        .lines()
        .map(|l| serde_json::from_str(l).unwrap())
        .collect();
    let r = &events.last().unwrap()["data"];
    assert_eq!(r["state"], "completed");
    assert!(r["samples"].as_array().unwrap().len() >= 2);
    let id = r["id"].as_str().unwrap();
    let path = base
        .join("astraeus/performance")
        .join(id)
        .join("result.json");
    assert_eq!(fs::metadata(&path).unwrap().mode() & 0o777, 0o600);
    let export = command()
        .args(["performance", "export", id, "--json"])
        .output()
        .unwrap();
    assert!(export.status.success());
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&export.stdout).unwrap(),
        *r
    );
    let mut child = command()
        .args(["performance", "record", "--duration", "60", "--json"])
        .stdout(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let mut reader = std::io::BufReader::new(child.stdout.take().unwrap());
    let mut line = String::new();
    reader.read_line(&mut line).unwrap();
    let started: serde_json::Value = serde_json::from_str(&line).unwrap();
    let stopped_id = started["data"]["id"].as_str().unwrap().to_owned();
    assert_eq!(
        unsafe { libc::kill(child.id() as libc::pid_t, libc::SIGTERM) },
        0
    );
    let mut rest = String::new();
    std::io::Read::read_to_string(&mut reader, &mut rest).unwrap();
    assert!(!child.wait().unwrap().success());
    let saved = command()
        .args(["performance", "show", &stopped_id, "--json"])
        .output()
        .unwrap();
    assert!(saved.status.success());
    let s: serde_json::Value = serde_json::from_slice(&saved.stdout).unwrap();
    assert_eq!(s["state"], "cancelled");
    assert!(!base
        .join("astraeus/performance")
        .join(stopped_id)
        .join("scratch.bin")
        .exists());
    fs::remove_dir_all(&base).unwrap();
}
