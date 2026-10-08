use super::*;
use std::{
    cell::{Cell, RefCell},
    collections::hash_map::DefaultHasher,
    hash::{Hash, Hasher},
    rc::Rc,
    sync::atomic::{AtomicUsize, Ordering},
};

const FS: &str = "11111111-1111-1111-1111-111111111111";
const ESP: &str = "1234-ABCD";
static NEXT: AtomicUsize = AtomicUsize::new(1);

#[derive(Clone)]
struct Fake {
    mounts: Rc<RefCell<serde_json::Value>>,
    calls: Rc<RefCell<Calls>>,
    next: Rc<Cell<u64>>,
    fail: Rc<RefCell<Option<String>>>,
    fail_after: Rc<Cell<Option<usize>>>,
}
type Calls = Vec<(String, Vec<String>)>;
impl Commands for Fake {
    fn authorize_mutation(&self, _: &Path, _: &Path) -> Result<()> {
        Ok(())
    }
    fn run(&self, program: &str, args: &[&str]) -> Result<String> {
        self.calls
            .borrow_mut()
            .push((program.into(), args.iter().map(|s| (*s).into()).collect()));
        if let Some(remaining) = self.fail_after.get() {
            self.fail_after.set(remaining.checked_sub(1));
            if remaining == 0 {
                return Err("injected interruption".into());
            }
        }
        if self.fail.borrow().as_deref() == Some(&format!("{program} {}", args.join(" "))) {
            return Err("injected command failure".into());
        }
        match program {
            "findmnt" => Ok(self.mounts.borrow().to_string()),
            "sync" => Ok(String::new()),
            "sha256sum" => {
                let mut hash = DefaultHasher::new();
                fs::read(args[1])?.hash(&mut hash);
                Ok(format!("{:016x}", hash.finish()).repeat(4))
            }
            "cryptsetup" => match args {
                ["status", "root"] => Ok("/dev/mapper/root is active.\n  device: /dev/vda2".into()),
                ["luksUUID", "/dev/vda2"] => Ok("22222222-2222-2222-2222-222222222222".into()),
                _ => Err("unexpected cryptsetup call".into()),
            },
            "lsblk" => Ok(FS.into()),
            "btrfs" => {
                match args {
                    ["subvolume", "show", path] => {
                        let s: Subvolume = serde_json::from_slice(&fs::read(
                            Path::new(path).join(".fake-subvolume"),
                        )?)?;
                        Ok(format!("UUID: {}\nParent UUID: {}\nSubvolume ID: {}\nTop level ID: {}\nFlags: {}",s.uuid,s.parent_uuid.as_deref().unwrap_or("-"),s.id,s.top_level,if s.read_only {"readonly"} else {"-"}))
                    }
                    ["subvolume", "list", "-o", _] => Ok(String::new()),
                    ["subvolume", "snapshot", rest @ ..] => {
                        let ro = rest[0] == "-r";
                        let src = Path::new(rest[usize::from(ro)]);
                        let dst = Path::new(rest[usize::from(ro) + 1]);
                        copy_tree(src, dst)?;
                        let parent: Subvolume =
                            serde_json::from_slice(&fs::read(src.join(".fake-subvolume"))?)?;
                        let n = self.next.get();
                        self.next.set(n + 1);
                        identity(dst, n, Some(parent.uuid), if ro { 258 } else { 5 }, ro);
                        Ok(String::new())
                    }
                    ["subvolume", "delete", "--commit-after", path] => {
                        fs::remove_dir_all(path)?;
                        Ok(String::new())
                    }
                    _ => Err("unexpected fake Btrfs call".into()),
                }
            }
            _ => Err(format!("unexpected command {program}").into()),
        }
    }
}
fn copy_tree(src: &Path, dst: &Path) -> Result<()> {
    fs::create_dir(dst)?;
    for item in fs::read_dir(src)? {
        let item = item?;
        let to = dst.join(item.file_name());
        if item.file_type()?.is_dir() {
            copy_tree(&item.path(), &to)?;
        } else {
            fs::copy(item.path(), to)?;
        }
    }
    Ok(())
}
fn identity(path: &Path, id: u64, parent_uuid: Option<String>, top_level: u64, read_only: bool) {
    fs::create_dir_all(path).unwrap();
    let sub = Subvolume {
        id,
        uuid: format!("00000000-0000-0000-0000-{id:012}"),
        parent_uuid,
        top_level,
        read_only,
    };
    fs::write(
        path.join(".fake-subvolume"),
        serde_json::to_vec(&sub).unwrap(),
    )
    .unwrap();
}
struct Fixture {
    path: PathBuf,
    manager: Manager<Fake>,
    fake: Fake,
}
impl Fixture {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "astraeus-snapshot-test-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        let top = path.join("top");
        let esp = path.join("esp");
        fs::create_dir(&top).unwrap();
        fs::create_dir(&esp).unwrap();
        let top = fs::canonicalize(top).unwrap();
        let esp = fs::canonicalize(esp).unwrap();
        for (i, (name, _)) in SUBVOLUMES.iter().enumerate() {
            identity(&top.join(name), 256 + i as u64, None, 5, false);
            fs::write(top.join(name).join("preserved"), name).unwrap();
        }
        let root = top.join("@");
        fs::create_dir_all(root.join("etc/kernel")).unwrap();
        fs::create_dir(root.join("boot")).unwrap();
        fs::create_dir_all(root.join("usr/lib/modules/test-release")).unwrap();
        let cmdline = format!("root=UUID={FS} rootflags=subvol=@ rw");
        fs::write(root.join("etc/kernel/cmdline"), &cmdline).unwrap();
        fs::write(root.join("boot/vmlinuz-linux"), b"test kernel").unwrap();
        let fstab = SUBVOLUMES
            .iter()
            .map(|(s, p)| format!("UUID={FS} {p} btrfs defaults,subvol=/{s} 0 0\n"))
            .collect::<String>();
        fs::write(
            root.join("etc/fstab"),
            format!("{fstab}UUID={ESP} /efi vfat defaults,umask=0077 0 2\n"),
        )
        .unwrap();
        fs::create_dir_all(esp.join("EFI/Linux")).unwrap();
        fs::create_dir(esp.join("loader")).unwrap();
        fs::write(
            esp.join("loader/loader.conf"),
            "default astraeus-dev-linux.efi\ntimeout 3\neditor no\n",
        )
        .unwrap();
        fs::write(
            esp.join(UKI),
            crate::tests::image(b"test kernel", cmdline.as_bytes()),
        )
        .unwrap();
        let mounts = serde_json::json!({"filesystems":[
            {"target":"/","fstype":"ext4","fsroot":"/","uuid":"host","options":"rw"},
            {"target":top,"fstype":"btrfs","fsroot":"/","uuid":FS,"options":"rw"},
            {"target":esp,"fstype":"vfat","fsroot":"/","uuid":ESP,"options":"rw"}
        ]});
        let fake = Fake {
            mounts: Rc::new(RefCell::new(mounts)),
            calls: Rc::new(RefCell::new(Vec::new())),
            next: Rc::new(Cell::new(1000)),
            fail: Rc::new(RefCell::new(None)),
            fail_after: Rc::new(Cell::new(None)),
        };
        let manager = Manager::recovery(fake.clone(), &top, &esp).unwrap();
        Self {
            path,
            manager,
            fake,
        }
    }
    fn create(&self) -> Snapshot {
        self.manager
            .create(Reason::PreUpdate, Some("transaction-108".into()))
            .unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.path).unwrap();
    }
}

#[test]
fn full_lifecycle_keeps_persistent_data_and_boot_evidence() {
    let f = Fixture::new();
    assert!(f.manager.list().unwrap().is_empty());
    let s = f.create();
    assert_eq!(s.health, Health::Unknown);
    assert_eq!(s.transaction_id.as_deref(), Some("transaction-108"));
    assert_eq!(f.manager.list().unwrap().len(), 1);
    assert!(f.manager.plan_rollback(&s.id).is_err());
    f.manager
        .mark(&s.id, Health::Candidate, "boot validation pending")
        .unwrap();
    f.manager
        .mark(
            &s.id,
            Health::KnownGood,
            "disposable guest boot1 and boot2 passed",
        )
        .unwrap();
    let plan = f.manager.plan_rollback(&s.id).unwrap();
    assert!(plan.reboot_required && plan.execution_supported);
    assert_eq!(plan.persistent.len(), 5);
    let old_root = f.manager.show(&f.manager.root).unwrap();
    fs::write(f.manager.root.join("preserved"), "broken").unwrap();
    f.manager.rollback(&s.id).unwrap();
    assert_eq!(
        fs::read_to_string(f.manager.root.join("preserved")).unwrap(),
        "@"
    );
    for (name, _) in &SUBVOLUMES[1..] {
        assert_eq!(
            fs::read_to_string(f.manager.top.as_ref().unwrap().join(name).join("preserved"))
                .unwrap(),
            *name
        );
    }
    let previous = fs::read_dir(f.manager.top.as_ref().unwrap())
        .unwrap()
        .map(|e| e.unwrap().path())
        .find(|p| {
            p.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("@previous-")
        })
        .unwrap();
    assert_eq!(f.manager.show(&previous).unwrap(), old_root);
    assert_eq!(
        fs::read_to_string(previous.join("preserved")).unwrap(),
        "broken"
    );
    assert!(!f.manager.store.join("pending.json").exists());
    assert!(f.manager.delete(&s.id).is_err());
    f.manager
        .mark(&s.id, Health::Bad, "later failure observed")
        .unwrap();
    assert!(f
        .manager
        .mark(&s.id, Health::KnownGood, "cannot skip candidate")
        .is_err());
    assert!(f.manager.delete(&s.id).is_err());
    let unused = f.create();
    f.manager.delete(&unused.id).unwrap();
    assert!(f.manager.inspect(&unused.id).is_err());
}

#[test]
fn planning_is_read_only_and_lock_can_cover_pre_and_post_snapshots() {
    let f = Fixture::new();
    let plan = f.manager.plan_create().unwrap();
    assert!(plan.read_only);
    assert!(!f.manager.store.exists());
    let lock = f.manager.lock().unwrap();
    assert!(f.manager.lock().is_err());
    let before = f
        .manager
        .create_locked(&lock, Reason::PreUpdate, Some("108".into()))
        .unwrap();
    let after = f
        .manager
        .create_locked(&lock, Reason::PostUpdate, Some("108".into()))
        .unwrap();
    assert_ne!(before.id, after.id);
    f.manager
        .mark_locked(&lock, &after.id, Health::Candidate, "awaiting boot")
        .unwrap();
    let foreign = Fixture::new();
    assert!(foreign
        .manager
        .mark_locked(&lock, &after.id, Health::KnownGood, "wrong store")
        .is_err());
    assert!(f
        .manager
        .mark(&after.id, Health::KnownGood, "second lock forbidden")
        .is_err());
    drop(lock);
    f.manager
        .mark(&before.id, Health::KnownGood, "verified")
        .unwrap();
    f.fake.calls.borrow_mut().clear();
    f.manager.plan_rollback(&before.id).unwrap();
    assert!(f.fake.calls.borrow().iter().all(|(cmd, args)| cmd != "sync"
        && !args
            .iter()
            .any(|v| matches!(v.as_str(), "snapshot" | "delete"))));
}

#[test]
fn online_layout_rejects_unprotected_package_mounts() {
    let f = Fixture::new();
    let mut mounts: Vec<_> = SUBVOLUMES.iter().map(|(s,p)| serde_json::json!({"target":p,"fstype":"btrfs","fsroot":format!("/{s}"),"uuid":FS,"options":"rw"})).collect();
    mounts.push(
        serde_json::json!({"target":"/efi","fstype":"vfat","fsroot":"/","uuid":ESP,"options":"rw"}),
    );
    let online = Manager {
        commands: f.fake.clone(),
        top: None,
        root: "/".into(),
        store: f.manager.store.clone(),
        esp: "/efi".into(),
    };
    for (target, options, accepted) in [
        ("/opt", "rw", false),
        ("/srv/data", "rw", false),
        ("/root", "rw", false),
        ("/custom-package-path", "rw", false),
        ("/usr", "ro", false),
        ("/mnt/external", "rw", false),
        ("/mnt/astraeus-validation", "ro", true),
        ("/run/user/1000/doc", "rw", true),
    ] {
        let mut observed = mounts.clone();
        observed.push(serde_json::json!({"target":target,"fstype":"tmpfs","fsroot":"/","uuid":null,"options":options}));
        *f.fake.mounts.borrow_mut() = serde_json::json!({"filesystems":observed});
        assert_eq!(online.plan_create().is_ok(), accepted, "{target} {options}");
    }
    assert!(!online.store.exists());
}

#[test]
fn nested_esp_mounts_are_rejected_online_and_offline() {
    for recovery in [true, false] {
        let f = Fixture::new();
        let manager = if recovery {
            Manager::recovery(
                f.fake.clone(),
                f.manager.top.as_ref().unwrap(),
                &f.manager.esp,
            )
            .unwrap()
        } else {
            let mut mounts: Vec<_> = SUBVOLUMES.iter().map(|(s,p)| serde_json::json!({"target":p,"fstype":"btrfs","fsroot":format!("/{s}"),"uuid":FS,"options":"rw"})).collect();
            mounts.push(serde_json::json!({"target":"/efi","fstype":"vfat","fsroot":"/","uuid":ESP,"options":"rw"}));
            *f.fake.mounts.borrow_mut() = serde_json::json!({"filesystems":mounts});
            Manager {
                commands: f.fake.clone(),
                top: None,
                root: "/".into(),
                store: f.manager.store.clone(),
                esp: "/efi".into(),
            }
        };
        assert!(manager.plan_create().is_ok());
        f.fake.mounts.borrow_mut()["filesystems"].as_array_mut().unwrap().push(
            serde_json::json!({"target":manager.esp.join("EFI/Linux"),"fstype":"tmpfs","fsroot":"/","uuid":null,"options":"rw"}));
        assert!(manager
            .plan_create()
            .unwrap_err()
            .to_string()
            .contains("nested mount beneath ESP"));
        assert!(!manager.store.exists());
    }
}

#[test]
fn unfinished_health_change_blocks_all_mutation_and_rollback_planning() {
    let f = Fixture::new();
    let snapshot = f.create();
    let mut good = f
        .manager
        .mark(&snapshot.id, Health::KnownGood, "boot passed")
        .unwrap();
    good.set_health(Health::Bad, "boot regression observed")
        .unwrap();
    let temporary = f.manager.entry(&snapshot.id).unwrap().join("metadata.next");
    write_new(&temporary, &serde_json::to_vec(&good).unwrap(), 0o644).unwrap();
    assert!(!f.manager.store.join("pending.json").exists());
    assert!(f.manager.plan_create().is_err());
    assert!(f.manager.lock().is_err());
    assert!(f.manager.plan_rollback(&snapshot.id).is_err());
    assert!(f.manager.rollback(&snapshot.id).is_err());
    assert!(f
        .manager
        .mark(&snapshot.id, Health::KnownGood, "retry")
        .is_err());
    assert!(f.manager.delete(&snapshot.id).is_err());
    assert!(temporary.exists());
    assert!(!f.manager.store.join("pending.json").exists());
}

#[test]
fn wrong_layout_missing_tools_metadata_and_targets_fail_closed() {
    let f = Fixture::new();
    f.fake.mounts.borrow_mut()["filesystems"][1]["fstype"] = "ext4".into();
    assert!(f.manager.plan_create().is_err());
    assert!(!f.manager.store.exists());
    f.fake.mounts.borrow_mut()["filesystems"][1]["fstype"] = "btrfs".into();
    let s = f.create();
    let root = f.manager.entry(&s.id).unwrap().join("private/root");
    *f.fake.fail.borrow_mut() = Some(format!("btrfs subvolume show {}", root.display()));
    assert!(f.manager.mark(&s.id, Health::KnownGood, "test").is_err());
    *f.fake.fail.borrow_mut() = None;
    assert!(f
        .manager
        .inspect(&SnapshotId::parse("999").unwrap())
        .is_err());
    let metadata = f.manager.entry(&s.id).unwrap().join("metadata.json");
    fs::write(&metadata, b"{broken").unwrap();
    assert!(f.manager.list().is_err());
    let mut invalid = s.clone();
    invalid.id = SnapshotId("../escape".into());
    fs::write(&metadata, serde_json::to_vec(&invalid).unwrap()).unwrap();
    assert!(f.manager.inspect(&s.id).is_err());
    fs::write(&metadata, serde_json::to_vec(&s).unwrap()).unwrap();
    fs::remove_dir_all(root).unwrap();
    assert!(f.manager.mark(&s.id, Health::KnownGood, "test").is_err());
}

#[test]
fn corruption_fstab_and_mount_conflicts_block_execution() {
    let f = Fixture::new();
    let s = f.create();
    f.manager.mark(&s.id, Health::KnownGood, "test").unwrap();
    let boot = f.manager.entry(&s.id).unwrap().join("private/boot.efi");
    fs::write(boot, b"corrupt").unwrap();
    assert!(f.manager.rollback(&s.id).is_err());
    f.manager
        .mark(&s.id, Health::Bad, "saved UKI corruption detected")
        .unwrap();
    assert_eq!(f.manager.inspect(&s.id).unwrap().health, Health::Bad);
    assert!(!f.manager.store.join("pending.json").exists());
    let f = Fixture::new();
    let fstab = f.manager.root.join("etc/fstab");
    fs::write(
        &fstab,
        fs::read_to_string(&fstab)
            .unwrap()
            .replace("subvol=/@,", "subvolid=256,")
            .replace("subvol=/@ ", "subvolid=256 "),
    )
    .unwrap();
    assert!(f.manager.create(Reason::Manual, None).is_err());
    let f = Fixture::new();
    f.fake.mounts.borrow_mut()["filesystems"].as_array_mut().unwrap().push(serde_json::json!({"target":"/mounted-installed-root","fstype":"btrfs","fsroot":"/@","uuid":FS,"options":"rw"}));
    assert!(f.manager.plan_create().is_err());
}

#[test]
fn encrypted_roots_bind_mapper_filesystem_and_luks_header() {
    let f = Fixture::new();
    let luks = "22222222-2222-2222-2222-222222222222";
    let cmdline = format!("rd.luks.name={luks}=root root=/dev/mapper/root rootflags=subvol=@ rw");
    let fstab = f.manager.root.join("etc/fstab");
    fs::write(
        &fstab,
        fs::read_to_string(&fstab)
            .unwrap()
            .replace(&format!("UUID={FS}"), "/dev/mapper/root"),
    )
    .unwrap();
    fs::write(f.manager.root.join("etc/kernel/cmdline"), &cmdline).unwrap();
    fs::write(
        f.manager.root.join("etc/crypttab"),
        format!("root UUID={luks} none luks\n"),
    )
    .unwrap();
    fs::write(
        f.manager.esp.join(UKI),
        crate::tests::image(b"test kernel", cmdline.as_bytes()),
    )
    .unwrap();
    let s = f.create();
    f.manager
        .mark(&s.id, Health::KnownGood, "encrypted fixture")
        .unwrap();
    f.manager.plan_rollback(&s.id).unwrap();
    *f.fake.fail.borrow_mut() = Some("cryptsetup luksUUID /dev/vda2".into());
    assert!(f.manager.plan_rollback(&s.id).is_err());
    assert!(!f.manager.store.join("pending.json").exists());
}

#[test]
fn interrupted_mutations_leave_a_durable_blocker() {
    let f = Fixture::new();
    let s = f.create();
    f.manager.mark(&s.id, Health::KnownGood, "test").unwrap();
    *f.fake.fail.borrow_mut() = Some(format!("sync -f {}", f.manager.esp.display()));
    assert!(f.manager.rollback(&s.id).is_err());
    assert!(f.manager.store.join("pending.json").exists());
    *f.fake.fail.borrow_mut() = None;
    assert!(f
        .manager
        .rollback(&s.id)
        .unwrap_err()
        .to_string()
        .contains("unfinished operation"));
    assert!(f.manager.create(Reason::Manual, None).is_err());
    assert!(f.manager.delete(&s.id).is_err());
    assert!(f.manager.inspect(&s.id).is_ok());
}

#[test]
fn each_rollback_durability_boundary_preserves_a_root_and_blocks_retry() {
    let f = Fixture::new();
    let snapshot = f.create();
    f.manager
        .mark(&snapshot.id, Health::KnownGood, "test")
        .unwrap();
    f.fake.calls.borrow_mut().clear();
    f.manager.rollback(&snapshot.id).unwrap();
    let points: Vec<_> = f
        .fake
        .calls
        .borrow()
        .iter()
        .enumerate()
        .filter(|(_, (p, a))| {
            p == "sync" || (p == "btrfs" && a.get(1).map(String::as_str) == Some("snapshot"))
        })
        .map(|(i, _)| i)
        .collect();
    assert!(points.len() >= 7);
    // Last sync follows the completed-history rename; all earlier failures retain pending intent.
    for point in &points[..points.len() - 1] {
        let f = Fixture::new();
        let s = f.create();
        f.manager.mark(&s.id, Health::KnownGood, "test").unwrap();
        f.fake.calls.borrow_mut().clear();
        f.fake.fail_after.set(Some(*point));
        assert!(f.manager.rollback(&s.id).is_err(), "failure point {point}");
        assert!(f.manager.store.join("pending.json").exists());
        let root_survives = f.manager.root.exists()
            || fs::read_dir(f.manager.top.as_ref().unwrap())
                .unwrap()
                .any(|e| {
                    e.unwrap()
                        .file_name()
                        .to_string_lossy()
                        .starts_with("@previous-")
                });
        assert!(root_survives);
        assert!(f.manager.rollback(&s.id).is_err());
        assert!(f
            .manager
            .entry(&s.id)
            .unwrap()
            .join("private/root")
            .exists());
    }
}

#[test]
fn online_discovery_and_unprivileged_catalog_do_not_call_btrfs() {
    let f = Fixture::new();
    let snapshot = f.create();
    let mut mounts: Vec<_> = SUBVOLUMES.iter().map(|(s,p)| serde_json::json!({"target":p,"fstype":"btrfs","fsroot":format!("/{s}"),"uuid":FS,"options":"rw"})).collect();
    mounts.push(
        serde_json::json!({"target":"/efi","fstype":"vfat","fsroot":"/","uuid":ESP,"options":"rw"}),
    );
    *f.fake.mounts.borrow_mut() = serde_json::json!({"filesystems":mounts});
    let online = Manager {
        commands: f.fake.clone(),
        top: None,
        root: "/".into(),
        store: f.manager.store.clone(),
        esp: "/efi".into(),
    };
    f.fake.calls.borrow_mut().clear();
    assert_eq!(online.list().unwrap()[0].id, snapshot.id);
    assert!(f.fake.calls.borrow().iter().all(|(p, _)| p == "findmnt"));
    assert!(online.rollback(&snapshot.id).is_err());
    f.fake.mounts.borrow_mut()["filesystems"][1]["uuid"] =
        "22222222-2222-2222-2222-222222222222".into();
    assert!(online.plan_create().is_err());
}

#[cfg(target_os = "linux")]
#[test]
#[ignore = "requires ASTRAEUS_LOOPBACK_TEST=1, root, loop devices, Btrfs and FAT tools"]
fn disposable_linux_btrfs_roundtrip() {
    // Test-only executor: permits WSL/private namespaces only for this newly made image.
    struct LoopCommands {
        directory: PathBuf,
    }
    impl Commands for LoopCommands {
        fn run(&self, program: &str, args: &[&str]) -> Result<String> {
            Native.run(program, args)
        }
        fn authorize_mutation(&self, store: &Path, esp: &Path) -> Result<()> {
            require(
                store.starts_with(&self.directory) && esp.starts_with(&self.directory),
                "test escaped disposable directory",
            )?;
            require(Native.run("id", &["-u"])? == "0", "test needs root")
        }
    }
    require(
        std::env::var("ASTRAEUS_LOOPBACK_TEST").as_deref() == Ok("1"),
        "explicit test opt-in missing",
    )
    .unwrap();
    assert_eq!(Native.run("id", &["-u"]).unwrap(), "0");
    let f = Fixture::new();
    // The fixture owns every path. Neither formatter ever receives a block-device path.
    let top = f.path.join("real-top");
    let esp = f.path.join("real-esp");
    fs::create_dir(&top).unwrap();
    fs::create_dir(&esp).unwrap();
    let btrfs = f.path.join("btrfs.img");
    let fat = f.path.join("esp.img");
    File::create_new(&btrfs)
        .unwrap()
        .set_len(512 * 1024 * 1024)
        .unwrap();
    File::create_new(&fat)
        .unwrap()
        .set_len(64 * 1024 * 1024)
        .unwrap();
    let run = |program: &str, args: &[&str]| {
        let output = Command::new(program).args(args).output().unwrap();
        assert!(
            output.status.success(),
            "{program}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    };
    run("mkfs.btrfs", &["-q", path_str(&btrfs).unwrap()]);
    run("mkfs.vfat", &["-F", "32", path_str(&fat).unwrap()]);
    struct Unmount(PathBuf);
    impl Drop for Unmount {
        fn drop(&mut self) {
            assert!(
                Command::new("umount")
                    .arg(&self.0)
                    .status()
                    .unwrap()
                    .success(),
                "failed to unmount test filesystem; retain fixture and inspect mount"
            );
        }
    }
    run(
        "mount",
        &[
            "-o",
            "loop,subvolid=5",
            path_str(&btrfs).unwrap(),
            path_str(&top).unwrap(),
        ],
    );
    let _unmount_top = Unmount(top.clone());
    run(
        "mount",
        &[
            "-o",
            "loop",
            path_str(&fat).unwrap(),
            path_str(&esp).unwrap(),
        ],
    );
    let _unmount_esp = Unmount(esp.clone());
    for (name, _) in SUBVOLUMES {
        run(
            "btrfs",
            &["subvolume", "create", path_str(&top.join(name)).unwrap()],
        );
    }
    fn populate(src: &Path, dst: &Path) {
        for item in fs::read_dir(src).unwrap() {
            let item = item.unwrap();
            if item.file_name() == ".fake-subvolume" {
                continue;
            }
            let target = dst.join(item.file_name());
            if item.file_type().unwrap().is_dir() {
                fs::create_dir(&target).unwrap();
                populate(&item.path(), &target);
            } else {
                fs::copy(item.path(), target).unwrap();
            }
        }
    }
    populate(&f.manager.root, &top.join("@"));
    populate(&f.manager.esp, &esp);
    let manager = Manager::recovery(
        LoopCommands {
            directory: f.path.clone(),
        },
        &top,
        &esp,
    )
    .unwrap();
    let (fs_uuid, esp_uuid) = manager.layout(false).unwrap();
    let fstab = top.join("@/etc/fstab");
    fs::write(
        &fstab,
        fs::read_to_string(&fstab)
            .unwrap()
            .replace(FS, &fs_uuid)
            .replace(ESP, &esp_uuid),
    )
    .unwrap();
    let cmdline = format!("root=UUID={fs_uuid} rootflags=subvol=@ rw");
    fs::write(top.join("@/etc/kernel/cmdline"), &cmdline).unwrap();
    fs::write(
        esp.join(UKI),
        crate::tests::image(b"test kernel", cmdline.as_bytes()),
    )
    .unwrap();
    for (name, _) in &SUBVOLUMES[1..] {
        fs::write(top.join(name).join("keep"), *name).unwrap();
    }
    let snapshot = manager
        .create(Reason::PreUpdate, Some("native-test".into()))
        .unwrap();
    assert!(snapshot.root.read_only);
    assert_eq!(manager.list().unwrap().len(), 1);
    assert_eq!(
        Native
            .run(
                "btrfs",
                &[
                    "property",
                    "get",
                    "-ts",
                    path_str(&manager.entry(&snapshot.id).unwrap().join("private/root")).unwrap(),
                    "ro"
                ]
            )
            .unwrap(),
        "ro=true"
    );
    manager
        .mark(
            &snapshot.id,
            Health::KnownGood,
            "storage fixture only, not boot qualification",
        )
        .unwrap();
    fs::write(top.join("@/preserved"), "broken").unwrap();
    manager.rollback(&snapshot.id).unwrap();
    assert_eq!(fs::read_to_string(top.join("@/preserved")).unwrap(), "@");
    for (name, _) in &SUBVOLUMES[1..] {
        assert_eq!(
            fs::read_to_string(top.join(name).join("keep")).unwrap(),
            *name
        );
    }
    let extra = manager.create(Reason::PostUpdate, None).unwrap();
    manager.delete(&extra.id).unwrap();
    assert!(manager.delete(&snapshot.id).is_err());
    assert!(!manager.store.join("pending.json").exists());
}

#[cfg(unix)]
#[test]
fn symlinks_cannot_redirect_store_or_boot_writes() {
    use std::os::unix::fs::symlink;
    let f = Fixture::new();
    symlink(&f.path, &f.manager.store).unwrap();
    assert!(f.manager.plan_create().is_err());
    fs::remove_file(&f.manager.store).unwrap();
    let boot = f.manager.esp.join(UKI);
    fs::remove_file(&boot).unwrap();
    symlink(f.path.join("outside"), boot).unwrap();
    assert!(f.manager.create(Reason::Manual, None).is_err());
    assert!(!f.path.join("outside").exists());
}
