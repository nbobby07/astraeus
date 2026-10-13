use super::*;

fn config(names: &[&str]) -> SystemConfig {
    SystemConfig {
        packages: names.iter().map(|s| s.to_string()).collect(),
        ..Default::default()
    }
}

fn apply(config: SystemConfig) -> ExecutionPlan {
    let mut backend = NativePackages::new(config).unwrap();
    let plan = backend.resolve().unwrap();
    assert_eq!(plan.fingerprint(), backend.resolve().unwrap().fingerprint());
    backend.download(&plan).unwrap();
    backend.verify(&plan).unwrap();
    backend.prepare_locked(&plan).unwrap();
    assert!(Path::new("/var/lib/pacman/db.lck").exists());
    assert!(backend.owned_package_lock().is_some());
    backend.apply(&plan).unwrap();
    backend.apply_management(&plan).unwrap();
    backend.verify_management(&plan).unwrap();
    assert_eq!(backend.current_state().unwrap(), plan.expected_state());
    drop(backend);
    assert!(!Path::new("/var/lib/pacman/db.lck").exists());
    plan
}

#[test]
#[ignore = "run only through scripts/validate/native-alpm.py in its isolated chroot"]
fn signed_native_backend() {
    assert_eq!(
        fs::read_to_string("/.astraeus-native-fixture").unwrap(),
        "isolated-package-test\n"
    );
    assert!(
        !Path::new("/etc/os-release").exists(),
        "refuse a real OS root"
    );
    assert_eq!(unsafe { libc::geteuid() }, 0);

    let desired = config(&["test-app"]);
    let mut backend = NativePackages::new(desired.clone()).unwrap();
    let plan = backend.resolve().unwrap();
    assert_eq!(plan.packages.targets.len(), 3);
    assert!(plan
        .packages
        .changes
        .iter()
        .any(|change| matches!(change,PackageChange::Upgrade{name,..} if name=="manual-app")));
    fs::write("/var/lib/pacman/db.lck", "different owner\n").unwrap();
    assert!(backend.prepare_locked(&plan).is_err());
    assert_eq!(
        fs::read_to_string("/var/lib/pacman/db.lck").unwrap(),
        "different owner\n"
    );
    fs::remove_file("/var/lib/pacman/db.lck").unwrap();
    let first = apply(desired.clone());
    assert_eq!(
        first.management.as_ref().unwrap().reasons_after["test-dep"],
        InstallReason::Dependency
    );
    assert!(Path::new("/hook-ran").exists());
    assert!(!first
        .management
        .as_ref()
        .unwrap()
        .after
        .packages
        .contains_key("manual-app"));
    assert!(!NativePackages::new(desired.clone())
        .unwrap()
        .resolve()
        .unwrap()
        .has_mutation());
    let metadata = apply(config(&["test-app", "manual-app"]));
    assert!(metadata.packages.changes.is_empty());
    assert!(metadata.has_mutation());
    let both = config(&["test-app", "test-app2"]);
    apply(both);
    let removed = apply(config(&["test-app2"]));
    assert!(removed
        .packages
        .changes
        .iter()
        .any(|c| matches!(c,PackageChange::Remove{name,..} if name=="test-app")));
    assert!(removed.expected_state().packages.contains_key("test-dep"));

    // A changed reason relinquishes removal authority even at the same version.
    let handle = Configuration::read().unwrap().handle().unwrap();
    handle
        .localdb()
        .pkg("test-app2")
        .unwrap()
        .set_reason(PackageReason::Depend)
        .unwrap();
    drop(handle);
    let external = apply(SystemConfig::default());
    assert!(external.expected_state().packages.contains_key("test-app2"));
    assert!(external
        .management
        .unwrap()
        .after
        .protected
        .contains("test-app2"));

    let mut ambiguous = config(&["test-needs-provider"]);
    assert!(NativePackages::new(ambiguous.clone())
        .unwrap()
        .resolve()
        .unwrap_err()
        .contains("Choose provider"));
    ambiguous
        .providers
        .insert("test-virtual".into(), "test-provider-b".into());
    let provider = apply(ambiguous);
    assert!(provider
        .expected_state()
        .packages
        .contains_key("test-provider-b"));
    assert!(!provider
        .expected_state()
        .packages
        .contains_key("test-provider-a"));
    assert_eq!(
        provider.management.unwrap().after.resolved_providers["test-virtual"],
        "test-provider-b"
    );
    let mut ignored_choice = config(&["test-needs-provider"]);
    ignored_choice
        .providers
        .insert("test-virtual".into(), "test-provider-a".into());
    assert!(NativePackages::new(ignored_choice.clone())
        .unwrap()
        .resolve()
        .unwrap_err()
        .contains("selected provider"));
    ignored_choice
        .providers
        .insert("test-virtual".into(), "test-dep".into());
    assert!(NativePackages::new(ignored_choice)
        .unwrap()
        .resolve()
        .unwrap_err()
        .contains("does not provide"));
    assert!(NativePackages::new(config(&["test-conflict"]))
        .unwrap()
        .resolve()
        .is_err());

    for name in ["test-unsigned", "test-corrupt"] {
        let mut backend = NativePackages::new(config(&[name])).unwrap();
        let plan = backend.resolve().unwrap();
        assert!(
            backend.download(&plan).is_err(),
            "{name} must fail signature/hash checks"
        );
        assert!(!backend.current_state().unwrap().packages.contains_key(name));
    }
    fs::write(
        "/usr/share/astraeus-fixtures/collision",
        "user-owned file\n",
    )
    .unwrap();
    for name in ["test-file-conflict", "test-hook-failure"] {
        let mut backend = NativePackages::new(config(&[name])).unwrap();
        let plan = backend.resolve().unwrap();
        backend.download(&plan).unwrap();
        backend.prepare_locked(&plan).unwrap();
        assert!(
            backend.apply(&plan).is_err(),
            "{name} must fail its commit check"
        );
    }
    assert_eq!(
        fs::read_to_string("/usr/share/astraeus-fixtures/collision").unwrap(),
        "user-owned file\n"
    );
    let mut stale = NativePackages::new(SystemConfig::default()).unwrap();
    let reviewed = stale.resolve().unwrap();
    let handle = Configuration::read().unwrap().handle().unwrap();
    handle
        .localdb()
        .pkg("test-app2")
        .unwrap()
        .set_reason(PackageReason::Explicit)
        .unwrap();
    drop(handle);
    assert!(stale.prepare_locked(&reviewed).is_err());
    apply(config(&["test-file-edited"]));
    let edited = Path::new("/usr/share/astraeus-fixtures/test-file-edited");
    let original = fs::metadata(edited).unwrap();
    fs::write(edited, vec![b'X'; original.len() as usize]).unwrap();
    fs::OpenOptions::new()
        .write(true)
        .open(edited)
        .unwrap()
        .set_times(
            fs::FileTimes::new()
                .set_accessed(original.accessed().unwrap())
                .set_modified(original.modified().unwrap()),
        )
        .unwrap();
    let retained = apply(SystemConfig::default());
    assert!(retained
        .expected_state()
        .packages
        .contains_key("test-file-edited"));
    assert!(retained
        .management
        .unwrap()
        .after
        .protected
        .contains("test-file-edited"));
    assert_eq!(
        fs::read(edited).unwrap(),
        vec![b'X'; original.len() as usize]
    );

    apply(config(&["test-stale-file"]));
    let mut removing = NativePackages::new(SystemConfig::default()).unwrap();
    let reviewed = removing.resolve().unwrap();
    assert!(reviewed
        .packages
        .changes
        .iter()
        .any(|c| matches!(c,PackageChange::Remove{name,..} if name=="test-stale-file")));
    removing.prepare_locked(&reviewed).unwrap();
    fs::write(
        "/usr/share/astraeus-fixtures/test-stale-file",
        "changed after locked preparation",
    )
    .unwrap();
    assert!(removing
        .apply(&reviewed)
        .unwrap_err()
        .contains("integrity changed"));
}
