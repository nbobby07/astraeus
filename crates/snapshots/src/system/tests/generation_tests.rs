use super::*;
use crate::generations::*;

fn baseline(f: &Fixture) -> Generation {
    let snapshot = f
        .manager
        .create(Reason::PreUpdate, Some("1".into()))
        .unwrap();
    f.manager
        .mark(
            &snapshot.id,
            Health::KnownGood,
            "verified boot and package map",
        )
        .unwrap();
    let guard = f.manager.lock().unwrap();
    let generation = f
        .manager
        .stage_generation_locked(&guard, &snapshot.id, None)
        .unwrap();
    f.manager
        .select_generation_locked(
            &guard,
            Selection {
                schema_version: 1,
                current: None,
                previous: generation.id.clone(),
            },
        )
        .unwrap();
    generation
}

fn candidate(f: &Fixture, prior: &Generation) -> Generation {
    let snapshot = f
        .manager
        .create(Reason::PostUpdate, Some("1".into()))
        .unwrap();
    f.manager
        .mark(&snapshot.id, Health::Candidate, "awaiting observed boot")
        .unwrap();
    let guard = f.manager.lock().unwrap();
    let generation = f
        .manager
        .stage_generation_locked(&guard, &snapshot.id, Some(prior.id.clone()))
        .unwrap();
    f.manager
        .select_generation_locked(
            &guard,
            Selection {
                schema_version: 1,
                current: Some(generation.id.clone()),
                previous: prior.id.clone(),
            },
        )
        .unwrap();
    generation
}

fn simulate_boot(f: &mut Fixture, generation: &Generation, counter: Option<&str>) {
    let mut mounts: Vec<_> = SUBVOLUMES.iter().map(|(s,p)| serde_json::json!({"target":p,"fstype":"btrfs","fsroot":format!("/{s}"),"uuid":FS,"options":"rw"})).collect();
    if generation.root_kind == RootKind::Retained {
        mounts[0]["fsroot"] = format!(
            "/@snapshots/astraeus/generations/{}/private/root",
            generation.id.as_str()
        )
        .into();
        f.manager.root = f
            .manager
            .store
            .join("generations")
            .join(generation.id.as_str())
            .join("private/root");
    }
    mounts.push(serde_json::json!({"target":f.manager.esp,"fstype":"vfat","fsroot":"/","uuid":ESP,"options":"rw"}));
    *f.fake.mounts.borrow_mut() = serde_json::json!({"filesystems":mounts});
    f.manager.top = None;
    let mut variables = f.fake.boot.borrow_mut();
    variables.insert("LoaderEntrySelected".into(), generation.id.entry());
    variables.insert(
        "stub_path".into(),
        f.manager
            .esp
            .join(generation.id.artifact())
            .to_str()
            .unwrap()
            .into(),
    );
    variables.insert("cmdline".into(), generation.embedded_cmdline.clone());
    if let Some(counter) = counter {
        let (old, _) = f
            .manager
            .generation_counter(&generation.id)
            .unwrap()
            .unwrap();
        let filename = format!("astraeus-{}+{counter}.conf", generation.id.as_str());
        fs::rename(
            f.manager.esp.join("loader/entries").join(old),
            f.manager.esp.join("loader/entries").join(&filename),
        )
        .unwrap();
        variables.insert(
            "LoaderBootCountPath".into(),
            format!("/loader/entries/{filename}"),
        );
    }
}

#[test]
fn candidate_and_independent_prior_remain_coherent() {
    let f = Fixture::new();
    let prior = baseline(&f);
    let prior_image = fs::read(f.manager.esp.join(prior.id.artifact())).unwrap();
    let current = candidate(&f, &prior);
    assert_ne!(current.root.id, prior.root.id);
    assert!(prior
        .embedded_cmdline
        .contains(&format!("rootflags=subvolid={}", prior.root.id)));
    assert!(current.embedded_cmdline.contains("rootflags=subvol=@"));
    assert_eq!(
        f.manager
            .generation_counter(&current.id)
            .unwrap()
            .unwrap()
            .1,
        BootCount::Counted { left: 3, done: 0 }
    );
    f.manager.verify_generation(&prior.id).unwrap();
    f.manager.verify_generation(&current.id).unwrap();
    assert_eq!(
        fs::read(f.manager.esp.join(prior.id.artifact())).unwrap(),
        prior_image
    );
    assert!(f
        .manager
        .delete(&current.snapshot)
        .unwrap_err()
        .to_string()
        .contains("pinned"));
    assert_eq!(f.manager.generations().unwrap().len(), 2);
    assert!(!f.manager.esp.join(UKI).exists());
    assert!(f.manager.esp.join(MAINTENANCE_UKI).exists());
    assert!(
        fs::read_to_string(f.manager.root.join("etc/mkinitcpio.d/linux.preset"))
            .unwrap()
            .contains(MAINTENANCE_UKI)
    );
}

#[test]
fn unmanaged_entries_and_unfinished_selection_are_not_accepted() {
    for filename in ["EFI/Linux/stale.efi", "loader/entries/foreign.conf"] {
        let f = Fixture::new();
        let prior = baseline(&f);
        fs::write(f.manager.esp.join(filename), b"foreign boot artifact").unwrap();
        let guard = f.manager.lock().unwrap();
        assert!(f
            .manager
            .select_generation_locked(
                &guard,
                Selection {
                    schema_version: 1,
                    current: None,
                    previous: prior.id
                }
            )
            .is_err());
        assert!(!f.manager.generation_pending().unwrap());
    }
    let f = Fixture::new();
    baseline(&f);
    fs::write(f.manager.store.join("generations/selection.next"), b"{}").unwrap();
    assert!(f.manager.lock().is_err());
}

#[test]
fn first_activation_interruption_keeps_original_and_retained_boot_material() {
    for failure in 0..70 {
        let f = Fixture::new();
        let snapshot = f
            .manager
            .create(Reason::PreUpdate, Some("1".into()))
            .unwrap();
        f.manager
            .mark(&snapshot.id, Health::KnownGood, "verified")
            .unwrap();
        let guard = f.manager.lock().unwrap();
        let prior = f
            .manager
            .stage_generation_locked(&guard, &snapshot.id, None)
            .unwrap();
        f.fake.fail_after.set(Some(failure));
        let result = f.manager.select_generation_locked(
            &guard,
            Selection {
                schema_version: 1,
                current: None,
                previous: prior.id.clone(),
            },
        );
        f.fake.fail_after.set(None);
        assert!(f.manager.esp.join(UKI).exists() || f.manager.esp.join(MAINTENANCE_UKI).exists());
        assert!(f.manager.esp.join(prior.id.artifact()).exists());
        assert!(f
            .manager
            .store
            .join("generations")
            .join(prior.id.as_str())
            .join("private/root")
            .exists());
        if result.is_err() && f.manager.generation_pending().unwrap() {
            assert!(f.manager.plan_create().is_err());
        }
    }
}

#[test]
fn exhausted_candidate_cannot_be_rearmed_but_last_attempt_can_be_blessed() {
    let mut f = Fixture::new();
    let prior = baseline(&f);
    let current = candidate(&f, &prior);
    simulate_boot(&mut f, &current, Some("0-3"));
    let guard = f.manager.lock().unwrap();
    assert!(f
        .manager
        .select_generation_locked(
            &guard,
            Selection {
                schema_version: 1,
                current: Some(current.id.clone()),
                previous: prior.id.clone()
            }
        )
        .is_err());
    f.manager
        .bless_generation_locked(&guard, &current.snapshot)
        .unwrap();
    assert_eq!(
        f.manager
            .generation_counter(&current.id)
            .unwrap()
            .unwrap()
            .1,
        BootCount::Uncounted
    );
    f.manager
        .bless_generation_locked(&guard, &current.snapshot)
        .unwrap();
    assert_eq!(
        f.fake
            .calls
            .borrow()
            .iter()
            .filter(|(p, _)| p == "systemd-bless-boot")
            .count(),
        1
    );
    assert!(f.manager.esp.join(prior.id.artifact()).exists());
}

#[test]
fn baseline_cannot_promote_a_maintenance_initrd_that_was_not_booted() {
    let mut f = Fixture::new();
    let prior = baseline(&f);
    let current = candidate(&f, &prior);
    simulate_boot(&mut f, &current, Some("2-1"));
    let first = f
        .manager
        .create(Reason::PreUpdate, Some("2".into()))
        .unwrap();
    f.manager.verify_booted(&first.id, false).unwrap();
    let maintenance = f.manager.working_uki().unwrap();
    let mut image = fs::read(&maintenance).unwrap();
    let offset = image
        .windows(b"test initrd".len())
        .position(|v| v == b"test initrd")
        .unwrap();
    image[offset] = b'X';
    fs::write(&maintenance, image).unwrap();
    let altered = f
        .manager
        .create(Reason::PreUpdate, Some("2".into()))
        .unwrap();
    assert!(f
        .manager
        .verify_booted(&altered.id, false)
        .unwrap_err()
        .to_string()
        .contains("immutable booted generation"));
    assert_eq!(
        f.manager.inspect(&altered.id).unwrap().health,
        Health::Unknown
    );
}

#[test]
fn blessing_refuses_wrong_entry_esp_counter_root_or_cmdline() {
    for damage in [
        "entry",
        "esp",
        "counter",
        "root",
        "cmdline",
        "untrusted",
        "uncounted",
    ] {
        let mut f = Fixture::new();
        let prior = baseline(&f);
        let current = candidate(&f, &prior);
        simulate_boot(&mut f, &current, Some("2-1"));
        match damage {
            "entry" => {
                f.fake
                    .boot
                    .borrow_mut()
                    .insert("LoaderEntrySelected".into(), prior.id.entry());
            }
            "esp" => {
                f.fake
                    .boot
                    .borrow_mut()
                    .insert("stub_path".into(), "/other-esp/evil.efi".into());
            }
            "counter" => {
                f.fake.boot.borrow_mut().insert(
                    "LoaderBootCountPath".into(),
                    "/loader/entries/other+2-1.conf".into(),
                );
            }
            "root" => identity(&f.manager.root, 4000, None, 5, false),
            "cmdline" => {
                f.fake.boot.borrow_mut().insert(
                    "cmdline".into(),
                    format!("{} rootflags=subvol=@other", current.embedded_cmdline),
                );
            }
            "untrusted" => {
                f.fake
                    .boot
                    .borrow_mut()
                    .insert("untrusted".into(), "true".into());
            }
            "uncounted" => {
                let (name, _) = f.manager.generation_counter(&current.id).unwrap().unwrap();
                let directory = f.manager.esp.join("loader/entries");
                fs::rename(directory.join(name), directory.join(current.id.entry())).unwrap();
            }
            _ => unreachable!(),
        }
        let guard = f.manager.lock().unwrap();
        assert!(
            f.manager
                .bless_generation_locked(&guard, &current.snapshot)
                .is_err(),
            "{damage}"
        );
        assert!(!f
            .fake
            .calls
            .borrow()
            .iter()
            .any(|(p, _)| p == "systemd-bless-boot"));
    }
}

#[test]
fn missing_root_uki_wrong_pair_and_invalid_metadata_fail_closed() {
    for damage in [
        "root",
        "uki",
        "pair",
        "metadata",
        "snapshot",
        "entry",
        "duplicate",
        "unsigned",
    ] {
        let f = Fixture::new();
        let prior = baseline(&f);
        let directory = f.manager.store.join("generations").join(prior.id.as_str());
        match damage {
            "root" => {
                fs::rename(
                    directory.join("private/root"),
                    directory.join("private/missing-root"),
                )
                .unwrap();
            }
            "uki" => {
                fs::remove_file(f.manager.esp.join(prior.id.artifact())).unwrap();
            }
            "pair" => {
                fs::copy(
                    f.manager.working_uki().unwrap(),
                    f.manager.esp.join(prior.id.artifact()),
                )
                .unwrap();
            }
            "metadata" => {
                fs::write(directory.join("metadata.json"), b"{}").unwrap();
            }
            "snapshot" => {
                fs::remove_file(
                    f.manager
                        .entry(&prior.snapshot)
                        .unwrap()
                        .join("metadata.json"),
                )
                .unwrap();
            }
            "entry" => {
                fs::write(
                    f.manager.esp.join("loader/entries").join(prior.id.entry()),
                    b"uki /wrong.efi\n",
                )
                .unwrap();
            }
            "duplicate" => {
                fs::copy(
                    f.manager.esp.join("loader/entries").join(prior.id.entry()),
                    f.manager
                        .esp
                        .join("loader/entries")
                        .join(format!("astraeus-{}+3.conf", prior.id.as_str())),
                )
                .unwrap();
            }
            "unsigned" => {
                f.fake
                    .boot
                    .borrow_mut()
                    .insert("untrusted".into(), "true".into());
            }
            _ => unreachable!(),
        }
        assert!(f.manager.verify_generation(&prior.id).is_err(), "{damage}");
    }
}

#[test]
fn retained_boot_is_a_recovery_session_and_never_an_update_root() {
    let mut f = Fixture::new();
    let prior = baseline(&f);
    let current = candidate(&f, &prior);
    simulate_boot(&mut f, &prior, None);
    f.manager.verify_generation(&prior.id).unwrap();
    f.manager.verify_running_generation(&prior).unwrap();
    assert!(f
        .manager
        .plan_create()
        .unwrap_err()
        .to_string()
        .contains("recovery session"));
    let guard = f.manager.lock().unwrap();
    assert!(f
        .manager
        .bless_generation_locked(&guard, &current.snapshot)
        .is_err());
}

#[test]
fn encrypted_generation_keeps_unlock_mapping_but_changes_root_selection() {
    let f = Fixture::new();
    let luks = "22222222-2222-2222-2222-222222222222";
    let root = &f.manager.root;
    fs::write(
        root.join("etc/crypttab"),
        format!("root UUID={luks} none luks\n"),
    )
    .unwrap();
    let fstab = fs::read_to_string(root.join("etc/fstab"))
        .unwrap()
        .replace(&format!("UUID={FS}"), "/dev/mapper/root");
    fs::write(root.join("etc/fstab"), fstab).unwrap();
    let cmdline = format!("rd.luks.name={luks}=root root=/dev/mapper/root rootflags=subvol=@ rw");
    fs::write(root.join("etc/kernel/cmdline"), &cmdline).unwrap();
    fs::write(
        f.manager.esp.join(UKI),
        crate::tests::image(b"test kernel", cmdline.as_bytes()),
    )
    .unwrap();
    let prior = baseline(&f);
    let current = candidate(&f, &prior);
    for generation in [&prior, &current] {
        f.manager.verify_generation(&generation.id).unwrap();
        assert!(generation
            .embedded_cmdline
            .contains(&format!("rd.luks.name={luks}=root")));
        assert!(generation
            .embedded_cmdline
            .contains("root=/dev/mapper/root"));
    }
}

#[test]
fn interruption_at_every_staging_and_activation_command_preserves_prior() {
    let measured = Fixture::new();
    baseline(&measured);
    let calls = measured.fake.calls.borrow().len();
    let mut failed = 0;
    for n in 0..calls {
        let f = Fixture::new();
        let prior = baseline(&f);
        let prior_image = fs::read(f.manager.esp.join(prior.id.artifact())).unwrap();
        let snapshot = f
            .manager
            .create(Reason::PostUpdate, Some("1".into()))
            .unwrap();
        f.manager
            .mark(&snapshot.id, Health::Candidate, "pending")
            .unwrap();
        let guard = f.manager.lock().unwrap();
        f.fake.fail_after.set(Some(n));
        let result = f
            .manager
            .stage_generation_locked(&guard, &snapshot.id, Some(prior.id.clone()))
            .and_then(|generation| {
                f.manager.select_generation_locked(
                    &guard,
                    Selection {
                        schema_version: 1,
                        current: Some(generation.id),
                        previous: prior.id.clone(),
                    },
                )
            });
        f.fake.fail_after.set(None);
        if result.is_err() {
            failed += 1;
        }
        assert_eq!(
            fs::read(f.manager.esp.join(prior.id.artifact())).unwrap(),
            prior_image
        );
        assert!(f
            .manager
            .store
            .join("generations")
            .join(prior.id.as_str())
            .join("private/root")
            .is_dir());
        if f.manager.generation_pending().unwrap() {
            assert!(f.manager.plan_create().is_err());
        }
    }
    assert!(failed > 30);
}

#[test]
fn offline_rollback_retires_generation_selection_only_after_restoring_pair() {
    let f = Fixture::new();
    let prior = baseline(&f);
    candidate(&f, &prior);
    let result = f.manager.rollback(&prior.snapshot).unwrap();
    assert_eq!(
        result.restored_state.parent_uuid,
        Some(f.manager.inspect(&prior.snapshot).unwrap().root.uuid)
    );
    assert!(f.manager.generation_selection().unwrap().is_none());
    assert!(fs::read_to_string(f.manager.esp.join("loader/loader.conf"))
        .unwrap()
        .starts_with("default astraeus-dev-linux.efi\n"));
    assert!(f.manager.esp.join(prior.id.artifact()).exists());
    assert!(f.manager.generation_counter(&prior.id).unwrap().is_none());
    assert!(!f.manager.generation_pending().unwrap());
}
