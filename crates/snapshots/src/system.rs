use super::*;
use std::{
    fs::{File, OpenOptions},
    io::Write,
    process::Command,
    time::{SystemTime, UNIX_EPOCH},
};

/// Argument-array execution boundary. Tests use captured output and injected failures.
pub trait Commands {
    fn run(&self, program: &str, args: &[&str]) -> Result<String>;
    fn authorize_mutation(&self, store: &Path, esp: &Path) -> Result<()>;
}
pub struct Native;
impl Commands for Native {
    fn run(&self, program: &str, args: &[&str]) -> Result<String> {
        require(
            cfg!(target_os = "linux"),
            "snapshot operations require Linux",
        )?;
        let output = Command::new(format!("/usr/bin/{program}"))
            .args(args)
            .env_clear()
            .env("LC_ALL", "C")
            .env("PATH", "/usr/bin:/usr/sbin")
            .output()
            .map_err(|e| format!("{program}: {e}"))?;
        let not_container = program == "systemd-detect-virt"
            && args == ["--container"]
            && output.status.code() == Some(1)
            && output.stdout == b"none\n";
        require(
            output.status.success() || not_container,
            &format!(
                "{program} failed: {}",
                String::from_utf8_lossy(&output.stderr).trim()
            ),
        )?;
        Ok(String::from_utf8(output.stdout)?.trim().into())
    }
    fn authorize_mutation(&self, store: &Path, esp: &Path) -> Result<()> {
        require(
            self.run("id", &["-u"])? == "0",
            "snapshot mutation requires root",
        )?;
        require(
            self.run("systemd-detect-virt", &["--container"])? == "none",
            "snapshot mutation is unsupported in containers",
        )?;
        require(
            fs::read_link("/proc/self/ns/mnt")? == fs::read_link("/proc/1/ns/mnt")?,
            "private mount namespace is unsupported",
        )?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            let own = fs::metadata("/")?;
            let init = fs::metadata("/proc/1/root")?;
            require(
                own.dev() == init.dev() && own.ino() == init.ino(),
                "chroot is unsupported",
            )?;
        }
        trusted(store.parent().ok_or("store parent missing")?)?;
        if store.try_exists()? {
            trusted(store)?;
        }
        trusted(esp)
    }
}

/// Held across package mutation by the transaction owner; fields cannot be forged.
pub struct MutationGuard {
    _file: File,
    store: PathBuf,
}

#[derive(Clone, Debug, Deserialize)]
pub(crate) struct Mount {
    pub target: String,
    pub fstype: String,
    pub fsroot: String,
    pub uuid: Option<String>,
    pub options: String,
}
#[derive(Deserialize)]
struct Mounts {
    filesystems: Vec<Mount>,
}

/// Online paths are fixed. Offline paths must be explicit, canonical mountpoints.
pub struct Manager<C: Commands> {
    commands: C,
    top: Option<PathBuf>,
    root: PathBuf,
    store: PathBuf,
    esp: PathBuf,
}
impl<C: Commands> Manager<C> {
    pub fn online(commands: C) -> Self {
        Self {
            commands,
            top: None,
            root: "/".into(),
            store: "/.snapshots/astraeus".into(),
            esp: "/efi".into(),
        }
    }
    pub fn recovery(commands: C, top: &Path, esp: &Path) -> Result<Self> {
        no_links(top)?;
        no_links(esp)?;
        require(
            top.is_absolute() && esp.is_absolute(),
            "recovery mountpoints must be absolute",
        )?;
        let top = fs::canonicalize(top)?;
        let esp = fs::canonicalize(esp)?;
        require(
            !top.starts_with(&esp) && !esp.starts_with(&top),
            "recovery root and ESP mounts must be separate",
        )?;
        Ok(Self {
            root: top.join("@"),
            store: top.join("@snapshots/astraeus"),
            top: Some(top),
            esp,
            commands,
        })
    }
    fn mounts(&self) -> Result<Vec<Mount>> {
        let text = self.commands.run(
            "findmnt",
            &[
                "--json",
                "--list",
                "--output",
                "TARGET,FSTYPE,FSROOT,UUID,OPTIONS",
            ],
        )?;
        Ok(serde_json::from_str::<Mounts>(&text)?.filesystems)
    }
    fn mount<'a>(&self, mounts: &'a [Mount], path: &Path) -> Result<&'a Mount> {
        let matches: Vec<_> = mounts
            .iter()
            .filter(|m| Path::new(&m.target) == path)
            .collect();
        require(matches.len() == 1, "required mount missing or overmounted")?;
        Ok(matches[0])
    }
    fn show(&self, path: &Path) -> Result<Subvolume> {
        no_links(path)?;
        parse_subvolume(
            &self
                .commands
                .run("btrfs", &["subvolume", "show", path_str(path)?])?,
        )
    }
    fn digest(&self, path: &Path) -> Result<String> {
        no_links(path)?;
        let output = self.commands.run("sha256sum", &["--", path_str(path)?])?;
        let hash = output.split_whitespace().next().unwrap_or("");
        require(
            hash.len() == 64 && hash.bytes().all(|c| c.is_ascii_hexdigit()),
            "invalid SHA256 output",
        )?;
        Ok(hash.into())
    }
    fn sync(&self, path: &Path) -> Result<()> {
        self.commands.run("sync", &["-f", path_str(path)?])?;
        Ok(())
    }
    /// Discovery uses the mounted filesystem UUID, never disk-name heuristics.
    /// Mapper, virtual disks and partition parents are already resolved by Linux.
    fn layout(&self, offline: bool) -> Result<(String, String)> {
        let mounts = self.mounts()?;
        no_links(&self.root)?;
        no_links(&self.store)?;
        no_links(&self.esp)?;
        let base = self.top.as_deref().unwrap_or(Path::new("/"));
        let mount = self.mount(&mounts, base)?;
        require(mount.fstype == "btrfs", "system filesystem is not Btrfs")?;
        require(
            mount.fsroot == if self.top.is_some() { "/" } else { "/@" },
            "unexpected root subvolume (need @ or recovery subvolid=5)",
        )?;
        let fs_uuid = mount.uuid.as_deref().ok_or("Btrfs UUID unavailable")?;
        require(uuid(fs_uuid), "invalid Btrfs filesystem UUID")?;
        require(
            mount.options.split(',').any(|o| o == "rw"),
            "system mount is read-only",
        )?;
        if let Some(top) = &self.top {
            require(
                mounts
                    .iter()
                    .filter(|m| m.uuid.as_deref() == Some(fs_uuid))
                    .count()
                    == 1,
                "recovery requires all installed filesystem mounts removed except top-level",
            )?;
            require(
                self.mount(&mounts, Path::new("/"))?.uuid.as_deref() != Some(fs_uuid),
                "cannot roll back the running filesystem",
            )?;
            for (name, _) in SUBVOLUMES {
                let sub = self.show(&top.join(name))?;
                require(
                    sub.top_level == 5 && !sub.read_only,
                    "unexpected sibling subvolume layout",
                )?;
            }
        } else {
            require(
                !offline,
                "rollback execution requires recovery --top-level and --esp",
            )?;
            for (name, point) in SUBVOLUMES {
                let m = self.mount(&mounts, Path::new(point))?;
                require(
                    m.fstype == "btrfs"
                        && m.fsroot == format!("/{name}")
                        && m.uuid.as_deref() == Some(fs_uuid),
                    "persistent subvolume mount missing or on wrong filesystem",
                )?;
            }
        }
        let esp = self.mount(&mounts, &self.esp)?;
        require(
            esp.fstype == "vfat" && esp.fsroot == "/" && esp.options.split(',').any(|o| o == "rw"),
            "ESP must be a writable FAT filesystem mount",
        )?;
        let esp_uuid = esp
            .uuid
            .as_deref()
            .filter(|s| !s.is_empty())
            .ok_or("ESP UUID unavailable")?;
        // Refuse unexpected mounts below root, including separate /boot or /usr.
        let allowed: Vec<_> = SUBVOLUMES.iter().map(|(_, p)| Path::new(p)).collect();
        for m in &mounts {
            let p = Path::new(&m.target);
            if let Some(top) = &self.top {
                require(
                    p == top || !p.starts_with(top),
                    "nested mount in recovery tree",
                )?;
            } else if p.starts_with("/etc")
                || p.starts_with("/usr")
                || p.starts_with("/boot")
                || p.starts_with("/var")
                || p.starts_with("/.snapshots")
                || p.starts_with("/home")
            {
                require(
                    allowed.contains(&p),
                    "unsupported nested mount in system/persistent tree",
                )?;
            }
        }
        Ok((fs_uuid.into(), esp_uuid.into()))
    }
    fn no_pending(&self) -> Result<()> {
        require(!self.store.join("pending.json").try_exists()?, "unfinished operation: inspect astraeus/pending.json and recover offline before continuing")?;
        if self.store.try_exists()? {
            for entry in fs::read_dir(&self.store)? {
                let entry = entry?;
                if entry.file_type()?.is_dir() {
                    require(
                        !entry.path().join("metadata.next").try_exists()?,
                        "unfinished health change: inspect snapshot metadata.next and recover offline before continuing",
                    )?;
                }
            }
        }
        Ok(())
    }
    fn entry(&self, id: &SnapshotId) -> Result<PathBuf> {
        SnapshotId::parse(id.as_str())?;
        let entry = self.store.join(id.as_str());
        no_links(&entry)?;
        Ok(entry)
    }
    pub fn list(&self) -> Result<Vec<Snapshot>> {
        let (filesystem_uuid, _) = self.layout(false)?;
        if !self.store.try_exists()? {
            return Ok(Vec::new());
        }
        let mut items = Vec::new();
        for entry in fs::read_dir(&self.store)? {
            let entry = entry?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| "non-UTF8 store entry")?;
            if name == "lock" || name == "pending.json" || name.starts_with("operation-") {
                continue;
            }
            let snapshot = self.read(&SnapshotId::parse(&name)?)?;
            require(
                snapshot.filesystem_uuid == filesystem_uuid,
                "snapshot belongs to another filesystem",
            )?;
            items.push(snapshot);
        }
        items.sort_by_key(|s| (s.created_unix_seconds, s.id.0.clone()));
        Ok(items)
    }
    fn read(&self, id: &SnapshotId) -> Result<Snapshot> {
        let path = self.entry(id)?.join("metadata.json");
        no_links(&path)?;
        require(
            fs::metadata(&path)?.len() <= 65536,
            "oversized snapshot metadata",
        )?;
        let snapshot: Snapshot = serde_json::from_slice(&fs::read(path)?)?;
        snapshot.validate()?;
        require(snapshot.id == *id, "metadata ID differs from directory")?;
        Ok(snapshot)
    }
    pub fn inspect(&self, id: &SnapshotId) -> Result<Snapshot> {
        let (fs_uuid, _) = self.layout(false)?;
        let snapshot = self.read(id)?;
        require(
            snapshot.filesystem_uuid == fs_uuid,
            "snapshot belongs to another filesystem",
        )?;
        Ok(snapshot)
    }
    pub fn plan_create(&self) -> Result<CreationPlan> {
        let (filesystem_uuid, _) = self.layout(false)?;
        self.no_pending()?;
        Ok(CreationPlan {
            source: self.root.clone(),
            store: self.store.clone(),
            filesystem_uuid,
            affected: vec!["@: / (including /var/lib/pacman)".into()],
            persistent: persistent(),
            read_only: true,
        })
    }
    /// Keep this handle alive across a future transaction's root and ESP mutations.
    /// Never unlink the lock file; advisory locks follow the open inode.
    pub fn lock(&self) -> Result<MutationGuard> {
        self.commands.authorize_mutation(&self.store, &self.esp)?;
        self.layout(false)?;
        if !self.store.try_exists()? {
            fs::create_dir(&self.store)?;
            set_mode(&self.store, 0o755)?;
        }
        no_links(&self.store)?;
        let path = self.store.join("lock");
        no_links(&path)?;
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .write(true)
            .read(true)
            .open(path)?;
        lock.try_lock()
            .map_err(|e| format!("snapshot/transaction lock busy: {e}"))?;
        self.no_pending()?;
        Ok(MutationGuard {
            _file: lock,
            store: self.store.clone(),
        })
    }
    fn verify_root(&self, root: &Path, fs_uuid: &str, esp_uuid: &str) -> Result<()> {
        let fstab = read_text(root, "etc/fstab")?;
        let entries: Vec<Vec<&str>> = fstab
            .lines()
            .filter(|l| !l.trim_start().starts_with('#'))
            .map(|l| l.split_whitespace().collect())
            .filter(|v: &Vec<_>| !v.is_empty())
            .collect();
        let cmdline = read_text(root, "etc/kernel/cmdline")?;
        let tokens: Vec<_> = cmdline.split_whitespace().collect();
        let encrypted = tokens.contains(&"root=/dev/mapper/root");
        let source = if encrypted {
            "/dev/mapper/root".into()
        } else {
            format!("UUID={fs_uuid}")
        };
        require(
            tokens.iter().filter(|s| s.starts_with("root=")).count() == 1
                && tokens.contains(&format!("root={source}").as_str()),
            "kernel root selection disagrees with filesystem",
        )?;
        require(
            tokens
                .iter()
                .filter(|s| s.starts_with("rootflags="))
                .count()
                == 1
                && tokens.contains(&"rootflags=subvol=@"),
            "kernel must select subvol=@ explicitly",
        )?;
        if encrypted {
            let crypttab = read_text(root, "etc/crypttab")?;
            let roots: Vec<Vec<_>> = crypttab
                .lines()
                .map(|l| l.split_whitespace().collect::<Vec<_>>())
                .filter(|v| v.first() == Some(&"root"))
                .collect();
            require(
                roots.len() == 1
                    && roots[0].len() == 4
                    && roots[0][2] == "none"
                    && roots[0][3] == "luks",
                "unsupported crypttab root mapping",
            )?;
            let luks = roots[0][1]
                .strip_prefix("UUID=")
                .ok_or("crypttab needs LUKS UUID")?;
            require(
                uuid(luks) && tokens.contains(&format!("rd.luks.name={luks}=root").as_str()),
                "crypttab and UKI unlock mapping disagree",
            )?;
            let status = self.commands.run("cryptsetup", &["status", "root"])?;
            let backing = status
                .lines()
                .filter_map(|line| line.trim().split_once(':'))
                .find(|(key, _)| *key == "device")
                .map(|(_, value)| value.trim())
                .ok_or("root mapper backing unavailable")?;
            require(backing.starts_with("/dev/"), "invalid mapper backing path")?;
            let actual = self.commands.run("cryptsetup", &["luksUUID", backing])?;
            require(actual == luks, "LUKS backing unavailable")?;
            require(
                self.commands.run(
                    "lsblk",
                    &[
                        "--noheadings",
                        "--nodeps",
                        "--output",
                        "UUID",
                        "/dev/mapper/root",
                    ],
                )? == fs_uuid,
                "root mapper is not the inspected filesystem",
            )?;
        }
        for (name, point) in SUBVOLUMES {
            let rows: Vec<_> = entries
                .iter()
                .filter(|v| v.get(1) == Some(&point))
                .collect();
            require(rows.len() == 1, "missing/duplicate required fstab entry")?;
            let row = rows[0];
            require(
                row.len() == 6 && row[0] == source && row[2] == "btrfs",
                "fstab filesystem/source mismatch",
            )?;
            let opts: Vec<_> = row[3].split(',').collect();
            require(
                opts.contains(&format!("subvol=/{name}").as_str())
                    && !opts
                        .iter()
                        .any(|o| o.starts_with("subvolid=") || *o == "noauto")
                    && opts.iter().filter(|o| o.starts_with("subvol=")).count() == 1,
                "fstab root selection is incoherent",
            )?;
        }
        let esps: Vec<_> = entries
            .iter()
            .filter(|v| v.get(1) == Some(&"/efi"))
            .collect();
        require(
            esps.len() == 1
                && esps[0].len() == 6
                && esps[0][0] == format!("UUID={esp_uuid}")
                && esps[0][2] == "vfat",
            "fstab points to a different ESP",
        )?;
        for row in entries {
            require(
                row.len() == 6
                    && (SUBVOLUMES.iter().any(|(_, p)| *p == row[1])
                        || row[1] == "/efi"
                        || (row[1] == "/tmp" && row[2] == "tmpfs")),
                "unsupported extra fstab entry",
            )?;
        }
        Ok(())
    }
    fn verify_uki(&self, root: &Path, image: &Path) -> Result<()> {
        no_links(image)?;
        let bytes = fs::read(image)?;
        no_links(&root.join("boot/vmlinuz-linux"))?;
        require(
            pe_section(&bytes, b".linux")? == fs::read(root.join("boot/vmlinuz-linux"))?,
            "UKI kernel differs from snapshot /boot/vmlinuz-linux",
        )?;
        let cmdline = std::str::from_utf8(pe_section(&bytes, b".cmdline")?)?.trim_end_matches('\0');
        require(
            cmdline
                .split_whitespace()
                .eq(read_text(root, "etc/kernel/cmdline")?.split_whitespace()),
            "UKI command line differs from snapshot",
        )?;
        pe_section(&bytes, b".initrd")?;
        let uname = std::str::from_utf8(pe_section(&bytes, b".uname")?)?.trim_end_matches('\0');
        require(
            !uname.is_empty()
                && uname
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"._-+".contains(&b)),
            "invalid UKI kernel release",
        )?;
        let modules = root.join("usr/lib/modules").join(uname);
        no_links(&modules)?;
        require(modules.is_dir(), "UKI kernel module tree is missing")?;
        Ok(())
    }
    fn verify_loader(&self) -> Result<()> {
        let config = read_text(&self.esp, "loader/loader.conf")?;
        let defaults: Vec<_> = config
            .lines()
            .filter_map(|line| {
                let mut words = line.split_whitespace();
                (words.next() == Some("default")).then(|| words.collect::<Vec<_>>())
            })
            .collect();
        require(
            defaults == [vec!["astraeus-dev-linux.efi"]],
            "unsupported boot default; expected Phase 1 Astraeus UKI",
        )
    }
    fn no_children(&self, root: &Path) -> Result<()> {
        require(
            self.commands
                .run("btrfs", &["subvolume", "list", "-o", path_str(root)?])?
                .is_empty(),
            "unexpected nested subvolume under system root",
        )
    }
    fn begin(&self, value: &serde_json::Value) -> Result<()> {
        write_new(
            &self.store.join("pending.json"),
            &serde_json::to_vec_pretty(value)?,
            0o644,
        )?;
        self.sync(&self.store)
    }
    fn finish(&self, id: &str) -> Result<()> {
        let destination = self.store.join(format!("operation-{id}.json"));
        require(!destination.try_exists()?, "operation history collision")?;
        fs::rename(self.store.join("pending.json"), destination)?;
        self.sync(&self.store)
    }
    pub fn create(&self, reason: Reason, transaction_id: Option<String>) -> Result<Snapshot> {
        let lock = self.lock()?;
        self.create_locked(&lock, reason, transaction_id)
    }
    pub fn create_locked(
        &self,
        guard: &MutationGuard,
        reason: Reason,
        transaction_id: Option<String>,
    ) -> Result<Snapshot> {
        require(
            guard.store == self.store,
            "lock belongs to another snapshot store",
        )?;
        if let Some(id) = &transaction_id {
            text_field(id)?;
        }
        let plan = self.plan_create()?;
        let (_, esp_uuid) = self.layout(false)?;
        let source_state = self.show(&self.root)?;
        require(
            source_state.top_level == 5 && !source_state.read_only,
            "source is not writable sibling @",
        )?;
        self.no_children(&self.root)?;
        require(
            !self.root.join("var/lib/pacman/db.lck").try_exists()?,
            "package database is locked; snapshot requires a quiescent package transaction",
        )?;
        self.verify_root(&self.root, &plan.filesystem_uuid, &esp_uuid)?;
        self.verify_uki(&self.root, &self.esp.join(UKI))?;
        self.verify_loader()?;
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?;
        let id = SnapshotId::parse(&format!(
            "{}-{}-{}",
            now.as_secs(),
            now.subsec_nanos(),
            std::process::id()
        ))?;
        let entry = self.entry(&id)?;
        require(!entry.try_exists()?, "snapshot ID collision")?;
        self.begin(&serde_json::json!({"schema_version":1,"operation":"create","id":id,"filesystem_uuid":plan.filesystem_uuid}))?;
        fs::create_dir(&entry)?;
        set_mode(&entry, 0o755)?;
        // Store contents are private; only the metadata is public.
        let private = entry.join("private");
        fs::create_dir(&private)?;
        set_mode(&private, 0o700)?;
        let image = private.join("boot.efi");
        copy_new(&self.esp.join(UKI), &image)?;
        let root = private.join("root");
        self.commands.run(
            "btrfs",
            &[
                "subvolume",
                "snapshot",
                "-r",
                path_str(&self.root)?,
                path_str(&root)?,
            ],
        )?;
        let root_identity = self.show(&root)?;
        self.verify_root(&root, &plan.filesystem_uuid, &esp_uuid)?;
        self.verify_uki(&root, &image)?;
        require(
            self.digest(&image)? == self.digest(&self.esp.join(UKI))?,
            "UKI changed during snapshot",
        )?;
        let snapshot = Snapshot {
            schema_version: 1,
            id: id.clone(),
            created_unix_seconds: now.as_secs(),
            filesystem_uuid: plan.filesystem_uuid,
            source_state,
            reason,
            transaction_id,
            root: root_identity,
            health: Health::Unknown,
            validation_evidence: None,
            boot: BootState {
                esp_uuid,
                sha256: self.digest(&image)?,
                relative_path: UKI.into(),
            },
        };
        snapshot.validate()?;
        self.sync(&entry)?;
        write_new(
            &entry.join("metadata.json"),
            &serde_json::to_vec_pretty(&snapshot)?,
            0o644,
        )?;
        self.sync(&entry)?;
        self.finish(id.as_str())?;
        Ok(snapshot)
    }
    fn verify_snapshot(&self, snapshot: &Snapshot) -> Result<PathBuf> {
        let private = self.entry(&snapshot.id)?.join("private");
        let root = private.join("root");
        require(
            self.show(&root)? == snapshot.root,
            "snapshot missing, modified or replaced",
        )?;
        self.no_children(&root)?;
        require(
            self.digest(&private.join("boot.efi"))? == snapshot.boot.sha256,
            "saved UKI is corrupt or replaced",
        )?;
        self.verify_root(&root, &snapshot.filesystem_uuid, &snapshot.boot.esp_uuid)?;
        self.verify_uki(&root, &private.join("boot.efi"))?;
        Ok(root)
    }
    pub fn mark(&self, id: &SnapshotId, health: Health, evidence: &str) -> Result<Snapshot> {
        let lock = self.lock()?;
        self.mark_locked(&lock, id, health, evidence)
    }
    pub fn mark_locked(
        &self,
        guard: &MutationGuard,
        id: &SnapshotId,
        health: Health,
        evidence: &str,
    ) -> Result<Snapshot> {
        require(
            guard.store == self.store,
            "lock belongs to another snapshot store",
        )?;
        self.no_pending()?;
        let mut snapshot = self.inspect(id)?;
        if matches!(health, Health::Candidate | Health::KnownGood) {
            self.verify_snapshot(&snapshot)?;
        }
        snapshot.set_health(health, evidence)?;
        let entry = self.entry(id)?;
        let temporary = entry.join("metadata.next");
        write_new(&temporary, &serde_json::to_vec_pretty(&snapshot)?, 0o644)?;
        fs::rename(temporary, entry.join("metadata.json"))?;
        self.sync(&entry)?;
        Ok(snapshot)
    }
    /// Verify the actual running kernel/root against the saved generation. This is
    /// boot evidence, not a full filesystem integrity or Secure Boot assertion.
    pub fn verify_booted(&self, id: &SnapshotId, restored: bool) -> Result<()> {
        require(
            self.top.is_none(),
            "boot confirmation requires the installed system",
        )?;
        self.no_pending()?;
        let snapshot = self.inspect(id)?;
        self.verify_snapshot(&snapshot)?;
        let (_, esp_uuid) = self.layout(false)?;
        let current = self.show(&self.root)?;
        require(
            if restored {
                current.parent_uuid.as_deref() == Some(&snapshot.root.uuid)
            } else {
                current == snapshot.source_state
            },
            "running root does not match the intended generation",
        )?;
        require(
            esp_uuid == snapshot.boot.esp_uuid
                && self.digest(&self.esp.join(UKI))? == snapshot.boot.sha256,
            "running ESP does not match saved UKI",
        )?;
        self.verify_root(&self.root, &snapshot.filesystem_uuid, &esp_uuid)?;
        self.verify_uki(&self.root, &self.esp.join(UKI))?;
        let bytes = fs::read(self.entry(id)?.join("private/boot.efi"))?;
        let cmdline = std::str::from_utf8(pe_section(&bytes, b".cmdline")?)?.trim_end_matches('\0');
        let running = self.commands.run("cat", &["/proc/cmdline"])?;
        require(
            boot_command_line_matches(cmdline, &running),
            "booted command line differs from intended UKI",
        )?;
        let uname = std::str::from_utf8(pe_section(&bytes, b".uname")?)?.trim_end_matches('\0');
        require(
            self.commands.run("uname", &["-r"])? == uname,
            "booted kernel differs from intended UKI",
        )?;
        Ok(())
    }
    pub fn plan_rollback(&self, id: &SnapshotId) -> Result<RollbackPlan> {
        let (_, esp_uuid) = self.layout(false)?;
        self.no_pending()?;
        let snapshot = self.inspect(id)?;
        require(
            snapshot.health == Health::KnownGood,
            "rollback target must be explicitly validated known-good",
        )?;
        require(
            snapshot.boot.esp_uuid == esp_uuid,
            "rollback ESP UUID mismatch",
        )?;
        self.verify_snapshot(&snapshot)?;
        let current = self.show(&self.root)?;
        self.verify_loader()?;
        require(
            current.top_level == 5 && !current.read_only,
            "active root layout changed",
        )?;
        self.no_children(&self.root)?;
        Ok(RollbackPlan {
            current_state: current,
            target: snapshot,
            affected: vec!["@: / (OS, configuration, pacman database and service state)".into()],
            persistent: persistent(),
            reboot_required: true,
            execution_supported: self.top.is_some(),
            boot_implications: format!("Restore saved matching UKI to /efi/{UKI}; preserve old UKI and root. No boot menu changes. Recovery media required."),
            safety_checks: vec![
                "filesystem/ESP UUID and six-subvolume layout verified".into(),
                "target read-only identity, saved UKI hash, kernel, command line and fstab verified".into(),
                "known-good evidence required; no recursive snapshot".into(),
                "execution rechecks under lock and rejects mounted installed subvolumes".into(),
            ],
        })
    }
    /// Offline switch. Any partial failure leaves pending.json and retained roots.
    /// No automatic retry can rename or delete a root whose identity has changed.
    pub fn rollback(&self, id: &SnapshotId) -> Result<RollbackResult> {
        self.no_pending()?;
        self.layout(true)?;
        let _lock = self.lock()?;
        let plan = self.plan_rollback(id)?;
        let top = self.top.as_ref().ok_or("recovery mount missing")?;
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)?
            .as_nanos()
            .to_string();
        let candidate = top.join(format!("@restore-{stamp}"));
        let previous = top.join(format!("@previous-{stamp}"));
        let old_uki = self.store.join(format!("operation-{stamp}-previous.efi"));
        let staged_uki = self.esp.join(format!("EFI/Linux/.astraeus-{stamp}.tmp"));
        for p in [&candidate, &previous, &old_uki, &staged_uki] {
            no_links(p)?;
            require(!p.try_exists()?, "rollback staging collision")?;
        }
        let private = self.entry(id)?.join("private");
        self.begin(&serde_json::json!({"schema_version":1,"operation":"rollback","id":id,"filesystem_uuid":plan.target.filesystem_uuid,"esp_uuid":plan.target.boot.esp_uuid,"current_state":plan.current_state,"target_state":plan.target.root,"candidate":candidate,"previous":previous,"previous_uki":old_uki,"staged_uki":staged_uki,"target_sha256":plan.target.boot.sha256}))?;
        copy_new(&self.esp.join(UKI), &old_uki)?;
        copy_new(&private.join("boot.efi"), &staged_uki)?;
        require(
            self.digest(&staged_uki)? == plan.target.boot.sha256,
            "staged UKI verification failed",
        )?;
        self.sync(&self.store)?;
        self.sync(&self.esp)?;
        self.commands.run(
            "btrfs",
            &[
                "subvolume",
                "snapshot",
                path_str(&private.join("root"))?,
                path_str(&candidate)?,
            ],
        )?;
        let restored = self.show(&candidate)?;
        require(
            !restored.read_only && restored.parent_uuid.as_deref() == Some(&plan.target.root.uuid),
            "restored root identity mismatch",
        )?;
        self.verify_root(
            &candidate,
            &plan.target.filesystem_uuid,
            &plan.target.boot.esp_uuid,
        )?;
        self.verify_uki(&candidate, &staged_uki)?;
        self.sync(top)?;
        self.layout(true)?;
        require(
            self.show(&self.root)? == plan.current_state,
            "root changed during rollback preparation",
        )?;
        fs::rename(&self.root, &previous)?;
        self.sync(top)?;
        fs::rename(&candidate, &self.root)?;
        self.sync(top)?;
        fs::rename(&staged_uki, self.esp.join(UKI))?;
        self.sync(&self.esp)?;
        require(
            self.show(&self.root)? == restored
                && self.digest(&self.esp.join(UKI))? == plan.target.boot.sha256,
            "rollback final verification failed",
        )?;
        self.finish(&stamp)?;
        Ok(RollbackResult {
            plan,
            restored_state: restored,
            previous_root: previous,
            previous_uki: old_uki,
            operation_id: stamp,
        })
    }
    pub fn delete(&self, id: &SnapshotId) -> Result<()> {
        // Offline-only deletion prevents removing snapshots mounted in the installed session.
        self.layout(true)?;
        let _lock = self.lock()?;
        let snapshot = self.inspect(id)?;
        require(
            snapshot.health != Health::KnownGood,
            "known-good snapshots are protected from deletion",
        )?;
        let current = self.show(&self.root)?;
        require(
            current.uuid != snapshot.root.uuid
                && current.parent_uuid.as_deref() != Some(&snapshot.root.uuid),
            "snapshot backs the current root",
        )?;
        let root = self.verify_snapshot(&snapshot)?;
        // All previous rollback targets stay pinned until a future retention API exists.
        for entry in fs::read_dir(&self.store)? {
            let entry = entry?;
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with("operation-") && name.ends_with(".json") {
                no_links(&entry.path())?;
                let operation: serde_json::Value =
                    serde_json::from_slice(&fs::read(entry.path())?)?;
                require(
                    !(operation["operation"] == "rollback" && operation["id"] == id.as_str()),
                    "snapshot is pinned by rollback history",
                )?;
            }
        }
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)?
            .as_nanos()
            .to_string();
        self.begin(&serde_json::json!({"schema_version":1,"operation":"delete","id":id,"root":snapshot.root}))?;
        self.commands.run(
            "btrfs",
            &["subvolume", "delete", "--commit-after", path_str(&root)?],
        )?;
        let entry = self.entry(id)?;
        fs::remove_file(entry.join("private/boot.efi"))?;
        fs::remove_dir(entry.join("private"))?;
        fs::remove_file(entry.join("metadata.json"))?;
        fs::remove_dir(entry)?;
        self.sync(&self.store)?;
        self.finish(&stamp)
    }
}

fn path_str(path: &Path) -> Result<&str> {
    path.to_str()
        .ok_or_else(|| "non-UTF8 path unsupported".into())
}
fn read_text(root: &Path, path: &str) -> Result<String> {
    let p = root.join(path);
    no_links(&p)?;
    Ok(fs::read_to_string(p)?)
}
fn set_mode(path: &Path, mode: u32) -> Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(mode))?;
    }
    #[cfg(not(unix))]
    let _ = (path, mode);
    Ok(())
}
fn trusted(path: &Path) -> Result<()> {
    no_links(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        for p in path.ancestors() {
            let m = fs::metadata(p)?;
            require(
                m.uid() == 0 && m.mode() & 0o022 == 0,
                "managed path must be root-owned and not group/world writable",
            )?;
        }
    }
    Ok(())
}
fn write_new(path: &Path, bytes: &[u8], mode: u32) -> Result<()> {
    no_links(path)?;
    let mut file = OpenOptions::new().create_new(true).write(true).open(path)?;
    set_mode(path, mode)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
fn copy_new(source: &Path, target: &Path) -> Result<()> {
    no_links(source)?;
    no_links(target)?;
    let mut source = File::open(source)?;
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut output = options.open(target)?;
    std::io::copy(&mut source, &mut output)?;
    output.sync_all()?;
    Ok(())
}

#[cfg(test)]
mod tests;
