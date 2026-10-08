#![cfg(target_os = "linux")]

use distro_transactions::UpdateSession;
use std::{
    fs,
    os::unix::{fs::PermissionsExt, process::CommandExt},
    process::Command,
};

static SERIAL: std::sync::Mutex<()> = std::sync::Mutex::new(());

// A separate process avoids fork temporarily inheriting locks from parallel unit tests.
#[test]
fn unprivileged_process_cannot_open_private_history_or_update_lock() {
    let _serial = SERIAL.lock().unwrap();
    if unsafe { libc::geteuid() } != 0 {
        eprintln!("cross-UID check requires root");
        return;
    }
    let temp = std::env::temp_dir().join(format!("astraeus-permissions-{}", std::process::id()));
    fs::create_dir(&temp).unwrap();
    fs::set_permissions(&temp, fs::Permissions::from_mode(0o755)).unwrap();
    let private = temp.join("private/history.sqlite");
    let public = temp.join("history.sqlite");
    let lock = temp.join("update.lock");
    fs::write(&lock, b"").unwrap();
    fs::set_permissions(&lock, fs::Permissions::from_mode(0o644)).unwrap();
    let vulnerable = Command::new("python3")
        .args(["-c", "import fcntl,sys\nf=open(sys.argv[1],'rb')\nfcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"])
        .arg(&lock).uid(65534).gid(65534).output().unwrap();
    assert!(
        vulnerable.status.success(),
        "legacy mode must reproduce read-only flock access"
    );
    let session = UpdateSession::open_published(&private, &lock, &public).unwrap();
    let output = Command::new("python3")
        .args(["-c", "import os,sys\nfor p in sys.argv[1:3]:\n try: os.open(p,os.O_RDONLY)\n except PermissionError: pass\n else: raise AssertionError(p)\nimport sqlite3\nc=sqlite3.connect('file:'+sys.argv[3]+'?mode=ro',uri=True)\nc.execute('select * from transactions').fetchall()"])
        .args([&private, &lock, &public]).uid(65534).gid(65534).output().unwrap();
    drop(session);
    fs::remove_dir_all(temp).unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn migration_recovers_a_legacy_hot_journal() {
    let _serial = SERIAL.lock().unwrap();
    let temp = std::env::temp_dir().join(format!("astraeus-migration-{}", std::process::id()));
    fs::create_dir(&temp).unwrap();
    let public = temp.join("history.sqlite");
    let private = temp.join("private/history.sqlite");
    let lock = temp.join("update.lock");
    drop(UpdateSession::open(&public, &lock).unwrap());
    let output = Command::new("python3")
        .args(["-c", "import sqlite3,os,sys\nc=sqlite3.connect(sys.argv[1])\nc.executescript('PRAGMA cache_size=1; BEGIN IMMEDIATE; INSERT INTO transactions(record) VALUES (zeroblob(100000));')\nos._exit(0)"])
        .arg(&public).output().unwrap();
    assert!(output.status.success());
    assert!(public.with_extension("sqlite-journal").exists());
    let session = UpdateSession::open_published(&private, &lock, &public).unwrap();
    assert!(session.records().unwrap().is_empty());
    assert!(distro_transactions::read_history(&public)
        .unwrap()
        .is_empty());
    drop(session);
    fs::remove_dir_all(temp).unwrap();
}
