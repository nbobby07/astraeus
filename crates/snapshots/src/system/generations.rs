use super::*;
use crate::generations::{
    BootCount, Generation, GenerationId, RootKind, Selection, TrustVerdict, TRIES,
};

impl<C: Commands> Manager<C> {
    pub fn working_uki(&self) -> Result<PathBuf> {
        Ok(self.esp.join(if self.generation_selection()?.is_some() {
            MAINTENANCE_UKI
        } else {
            UKI
        }))
    }
    fn generation_dir(&self) -> PathBuf {
        self.store.join("generations")
    }
    fn generation_path(&self, id: &GenerationId) -> Result<PathBuf> {
        GenerationId::parse(id.as_str())?;
        let path = self.generation_dir().join(id.as_str());
        no_links(&path)?;
        Ok(path)
    }
    fn generation_read<T: serde::de::DeserializeOwned>(&self, path: &Path) -> Result<T> {
        no_links(path)?;
        require(
            fs::metadata(path)?.len() <= 65536,
            "oversized generation metadata",
        )?;
        Ok(serde_json::from_slice(&fs::read(path)?)?)
    }
    pub fn generations_enabled(&self) -> Result<bool> {
        let path = self.root.join("etc/astraeus/boot-generations");
        no_links(&path)?;
        if !path.try_exists()? {
            return Ok(false);
        }
        require(
            fs::read_to_string(path)? == "1\n",
            "unsupported boot generation configuration",
        )?;
        Ok(true)
    }
    /// Explicit opt-in. Signing and firmware enrollment must already be available.
    pub fn enable_generations(&self) -> Result<()> {
        let _guard = self.lock()?;
        require(
            self.top.is_none(),
            "enable generations on the installed system",
        )?;
        self.generation_prerequisites()?;
        self.verify_artifact_trust(&self.esp.join(UKI))?;
        let directory = self.root.join("etc/astraeus");
        no_links(&directory)?;
        fs::create_dir_all(&directory)?;
        write_new(&directory.join("boot-generations"), b"1\n", 0o644)?;
        self.sync(&directory)
    }
    pub fn generation_prerequisites(&self) -> Result<()> {
        self.no_pending()?;
        let version = self.commands.run("bootctl", &["--version"])?;
        require(
            version
                .split_whitespace()
                .nth(1)
                .is_some_and(|v| v == "262" || v.starts_with("262.")),
            "generation selection is qualified against systemd 262 only",
        )?;
        let trust: crate::generations::LoaderTrust = serde_json::from_str(
            &self
                .commands
                .boot_artifact(&["ready", path_str(&self.esp)?])?,
        )?;
        trust.validate()?;
        require(
            read_text(
                &self.root,
                "usr/lib/systemd/system/systemd-bless-boot.service.d/astraeus.conf",
            )? == include_str!("../../../../distro/installed/astraeus-bless-boot.conf"),
            "Astraeus blessing gate is not installed",
        )?;
        Ok(())
    }
    fn verify_artifact_trust(&self, image: &Path) -> Result<String> {
        let digest = self.digest(image)?;
        let verdict: TrustVerdict =
            serde_json::from_str(&self.commands.boot_artifact(&["verify", path_str(image)?])?)?;
        verdict.require_trusted(&digest)?;
        require(
            self.digest(image)? == digest,
            "artifact changed during trust verification",
        )?;
        Ok(digest)
    }
    /// Read-only catalog. Eligibility requires verify_generation and transaction history.
    pub fn generations(&self) -> Result<Vec<Generation>> {
        let directory = self.generation_dir();
        no_links(&directory)?;
        if !directory.try_exists()? {
            return Ok(vec![]);
        }
        let mut result = vec![];
        for entry in fs::read_dir(directory)? {
            let entry = entry?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| "invalid generation filename")?;
            if name == "selection.json" || name == "selection.next" {
                continue;
            }
            let id = GenerationId::parse(&name)?;
            let path = self.generation_path(&id)?.join("metadata.json");
            if !path.try_exists()? {
                require(
                    self.store.join("pending.json").try_exists()?,
                    "incomplete generation without journal",
                )?;
                continue;
            }
            let generation: Generation = self.generation_read(&path)?;
            generation.validate()?;
            require(generation.id == id, "generation ID differs from directory")?;
            result.push(generation);
        }
        result.sort_by(|a, b| a.id.as_str().cmp(b.id.as_str()));
        Ok(result)
    }
    pub fn generation(&self, id: &GenerationId) -> Result<Generation> {
        let generation: Generation =
            self.generation_read(&self.generation_path(id)?.join("metadata.json"))?;
        generation.validate()?;
        require(generation.id == *id, "generation ID differs from directory")?;
        Ok(generation)
    }
    pub fn generation_selection(&self) -> Result<Option<Selection>> {
        let path = self.generation_dir().join("selection.json");
        no_links(&path)?;
        if !path.try_exists()? {
            return Ok(None);
        }
        let selection: Selection = self.generation_read(&path)?;
        selection.validate()?;
        Ok(Some(selection))
    }
    pub fn generation_pending(&self) -> Result<bool> {
        no_links(&self.store.join("pending.json"))?;
        Ok(self.store.join("pending.json").try_exists()?
            || self.generation_dir().join("selection.next").try_exists()?)
    }
    pub fn generation_counter(&self, id: &GenerationId) -> Result<Option<(String, BootCount)>> {
        let directory = self.esp.join("loader/entries");
        no_links(&directory)?;
        if !directory.try_exists()? {
            return Ok(None);
        }
        let prefix = format!("astraeus-{}+", id.as_str());
        let mut found = None;
        for entry in fs::read_dir(directory)? {
            let entry = entry?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| "non-UTF8 boot entry")?;
            if name == id.entry() || (name.starts_with(&prefix) && name.ends_with(".conf")) {
                no_links(&entry.path())?;
                require(found.is_none(), "ambiguous boot counter files")?;
                found = Some((name.clone(), BootCount::parse(id, &name)?));
            }
        }
        Ok(found)
    }
    fn generation_root_path(&self, generation: &Generation) -> Result<PathBuf> {
        Ok(match generation.root_kind {
            RootKind::Current => self.root.clone(),
            RootKind::Retained => self.generation_path(&generation.id)?.join("private/root"),
        })
    }
    pub fn verify_generation(&self, id: &GenerationId) -> Result<Generation> {
        self.no_pending()?;
        let generation = self.generation(id)?;
        let snapshot = self.read(&generation.snapshot)?;
        let (fs_uuid, esp_uuid) = self.layout(false)?;
        require(
            generation.filesystem_uuid == fs_uuid
                && generation.esp_uuid == esp_uuid
                && snapshot.filesystem_uuid == fs_uuid
                && snapshot.boot.esp_uuid == esp_uuid,
            "generation filesystem/ESP mismatch",
        )?;
        self.verify_snapshot(&snapshot)?;
        let root = self.generation_root_path(&generation)?;
        require(
            self.show(&root)? == generation.root,
            "generation root missing or replaced",
        )?;
        let subvolid = match generation.root_kind {
            RootKind::Current => {
                require(
                    generation.root == snapshot.source_state
                        && snapshot.reason == Reason::PostUpdate
                        && matches!(snapshot.health, Health::Candidate | Health::KnownGood),
                    "candidate source mismatch",
                )?;
                None
            }
            RootKind::Retained => {
                require(
                    snapshot.health == Health::KnownGood
                        && snapshot.reason == Reason::PreUpdate
                        && generation.root.parent_uuid.as_deref() == Some(&snapshot.root.uuid),
                    "retained root is not a known-good snapshot clone",
                )?;
                Some(generation.root.id)
            }
        };
        self.no_children(&root)?;
        self.verify_root_selection(&root, &fs_uuid, &esp_uuid, subvolid)?;
        let image = self.esp.join(id.artifact());
        require(
            self.verify_artifact_trust(&image)? == generation.uki_sha256,
            "generation UKI hash mismatch",
        )?;
        self.verify_uki(&root, &image)?;
        let bytes = fs::read(&image)?;
        pe_section(&bytes, b".osrel")?;
        require(
            std::str::from_utf8(pe_section(&bytes, b".cmdline")?)?.trim_end_matches('\0')
                == generation.embedded_cmdline,
            "embedded root binding changed",
        )?;
        if let Some((filename, _)) = self.generation_counter(id)? {
            require(
                read_text(&self.esp, &format!("loader/entries/{filename}"))?
                    == generation.entry_text(),
                "boot entry differs from generation binding",
            )?;
        }
        Ok(generation)
    }
    fn generation_guard(&self, guard: &MutationGuard) -> Result<()> {
        require(
            guard.store == self.store,
            "generation lock belongs to another store",
        )?;
        self.no_pending()
    }
    /// Stage before publication. Every side effect follows the durable Phase 2 journal.
    pub fn stage_generation_locked(
        &self,
        guard: &MutationGuard,
        snapshot_id: &SnapshotId,
        prior: Option<GenerationId>,
    ) -> Result<Generation> {
        self.generation_guard(guard)?;
        let snapshot = self.inspect(snapshot_id)?;
        let source = self.verify_snapshot(&snapshot)?;
        let retained = snapshot.reason == Reason::PreUpdate;
        require(
            (retained && snapshot.health == Health::KnownGood && prior.is_none())
                || (snapshot.reason == Reason::PostUpdate
                    && snapshot.health == Health::Candidate
                    && prior.is_some()),
            "snapshot is not eligible for generation staging",
        )?;
        if let Some(id) = &prior {
            let previous = self.verify_generation(id)?;
            require(
                previous.root_kind == RootKind::Retained
                    && self.read(&previous.snapshot)?.transaction_id == snapshot.transaction_id,
                "prior must be a retained root",
            )?;
        }
        let id = GenerationId::parse(snapshot_id.as_str())?;
        let directory = self.generation_path(&id)?;
        require(
            !directory.try_exists()? && !self.esp.join(id.artifact()).try_exists()?,
            "generation already exists; inspect rather than replace",
        )?;
        self.begin(&serde_json::json!({"schema_version":1,"operation":"generation-stage","id":id,"snapshot":snapshot_id,"prior":prior,"root_directory":directory,"artifact":id.artifact()}))?;
        fs::create_dir_all(self.generation_dir())?;
        set_mode(&self.generation_dir(), 0o755)?;
        fs::create_dir(&directory)?;
        set_mode(&directory, 0o755)?;
        let private = directory.join("private");
        fs::create_dir(&private)?;
        set_mode(&private, 0o700)?;
        let root = if retained {
            let root = private.join("root");
            self.commands.run(
                "btrfs",
                &[
                    "subvolume",
                    "snapshot",
                    path_str(&source)?,
                    path_str(&root)?,
                ],
            )?;
            root
        } else {
            self.root.clone()
        };
        let identity = self.show(&root)?;
        let original = self.entry(snapshot_id)?.join("private/boot.efi");
        let old_bytes = fs::read(&original)?;
        let cmdline =
            std::str::from_utf8(pe_section(&old_bytes, b".cmdline")?)?.trim_end_matches('\0');
        let cmdline = if retained {
            require(
                identity.parent_uuid.as_deref() == Some(&snapshot.root.uuid) && !identity.read_only,
                "retained clone identity mismatch",
            )?;
            let cmdline = cmdline
                .split_whitespace()
                .map(|w| {
                    if w == "rootflags=subvol=@" {
                        format!("rootflags=subvolid={}", identity.id)
                    } else {
                        w.into()
                    }
                })
                .collect::<Vec<_>>()
                .join(" ");
            replace_existing(
                &root.join("etc/kernel/cmdline"),
                format!("{cmdline}\n").as_bytes(),
            )?;
            let fstab = read_text(&root, "etc/fstab")?;
            let mut updated = String::new();
            for line in fstab.lines() {
                let mut words: Vec<_> = line.split_whitespace().map(String::from).collect();
                if words.get(1).map(String::as_str) == Some("/")
                    && !line.trim_start().starts_with('#')
                {
                    words[3] = words[3]
                        .split(',')
                        .map(|w| {
                            if w == "subvol=/@" {
                                format!("subvolid={}", identity.id)
                            } else {
                                w.into()
                            }
                        })
                        .collect::<Vec<_>>()
                        .join(",");
                    updated.push_str(&words.join(" "));
                } else {
                    updated.push_str(line);
                }
                updated.push('\n');
            }
            replace_existing(&root.join("etc/fstab"), updated.as_bytes())?;
            cmdline
        } else {
            require(identity == snapshot.source_state, "candidate root changed")?;
            cmdline.into()
        };
        let image = private.join("boot.efi");
        if retained {
            // Chat 1 rebuilds/seals the UKI. It may change only cmdline and signing data.
            self.commands.boot_artifact(&[
                "rebind",
                path_str(&original)?,
                path_str(&root.join("etc/kernel/cmdline"))?,
                path_str(&image)?,
            ])?;
            let rebound = fs::read(&image)?;
            for section in [
                b".linux".as_slice(),
                b".initrd",
                b".uname",
                b".osrel",
                b".ucode",
            ] {
                let before = pe_section(&old_bytes, section);
                let after = pe_section(&rebound, section);
                require(
                    match (before, after) {
                        (Ok(a), Ok(b)) => a == b,
                        (Err(_), Err(_)) => section == b".osrel" || section == b".ucode",
                        _ => false,
                    },
                    "rebound UKI changed protected boot payload",
                )?;
            }
        } else {
            copy_new(&original, &image)?;
        }
        self.verify_root_selection(
            &root,
            &snapshot.filesystem_uuid,
            &snapshot.boot.esp_uuid,
            retained.then_some(identity.id),
        )?;
        self.verify_uki(&root, &image)?;
        pe_section(&fs::read(&image)?, b".osrel")?;
        let hash = self.verify_artifact_trust(&image)?;
        let generation = Generation {
            schema_version: 1,
            id: id.clone(),
            snapshot: snapshot_id.clone(),
            root: identity,
            root_kind: if retained {
                RootKind::Retained
            } else {
                RootKind::Current
            },
            filesystem_uuid: snapshot.filesystem_uuid,
            esp_uuid: snapshot.boot.esp_uuid,
            uki_sha256: hash,
            embedded_cmdline: cmdline,
            prior_known_good: prior,
        };
        generation.validate()?;
        self.sync(&directory)?;
        write_new(
            &directory.join("metadata.json"),
            &serde_json::to_vec_pretty(&generation)?,
            0o644,
        )?;
        self.sync(&directory)?;
        let esp_directory = self.esp.join("EFI/Astraeus");
        no_links(&esp_directory)?;
        fs::create_dir_all(&esp_directory)?;
        let temporary = esp_directory.join(format!(".{}.next", id.as_str()));
        copy_new(&image, &temporary)?;
        require(
            self.verify_artifact_trust(&temporary)? == generation.uki_sha256,
            "staged ESP artifact mismatch",
        )?;
        self.sync(&self.esp)?;
        fs::rename(&temporary, self.esp.join(id.artifact()))?;
        self.sync(&self.esp)?;
        self.finish(&format!("generation-stage-{}", id.as_str()))?;
        Ok(generation)
    }
    /// Select only a current candidate and its explicitly bound retained predecessor.
    pub fn select_generation_locked(
        &self,
        guard: &MutationGuard,
        selection: Selection,
    ) -> Result<()> {
        self.generation_guard(guard)?;
        self.verify_loader()?;
        self.exclusive_generation_entries()?;
        selection.validate()?;
        let previous = self.verify_generation(&selection.previous)?;
        require(
            previous.root_kind == RootKind::Retained,
            "fallback must have an independent retained root",
        )?;
        let current = selection
            .current
            .as_ref()
            .map(|id| self.verify_generation(id))
            .transpose()?;
        if let Some(current) = &current {
            require(
                current.root_kind == RootKind::Current
                    && current.prior_known_good.as_ref() == Some(&previous.id),
                "candidate/prior pairing mismatch",
            )?;
            require(
                !matches!(
                    self.generation_counter(&current.id)?,
                    Some((_, BootCount::Counted { left: 0, .. }))
                ),
                "exhausted generation cannot be rearmed",
            )?;
            if self
                .generation_counter(&current.id)?
                .is_some_and(|(_, count)| count == BootCount::Uncounted)
            {
                self.verify_blessing_receipt(&current.id)?;
            }
        }
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)?
            .as_nanos()
            .to_string();
        self.begin(&serde_json::json!({"schema_version":1,"operation":"generation-select","selection":selection,"previous_selection":self.generation_selection()?}))?;
        let entries = self.esp.join("loader/entries");
        no_links(&entries)?;
        fs::create_dir_all(&entries)?;
        for generation in std::iter::once(&previous).chain(current.iter()) {
            if self.generation_counter(&generation.id)?.is_none() {
                let filename = if generation.root_kind == RootKind::Retained {
                    generation.id.entry()
                } else {
                    format!("astraeus-{}+{TRIES}.conf", generation.id.as_str())
                };
                let temporary = entries.join(format!(".{filename}.next"));
                write_new(&temporary, generation.entry_text().as_bytes(), 0o644)?;
                self.sync(&self.esp)?;
                fs::rename(temporary, entries.join(filename))?;
                self.sync(&self.esp)?;
            }
        }
        let selection_next = self.generation_dir().join("selection.next");
        write_new(
            &selection_next,
            &serde_json::to_vec_pretty(&selection)?,
            0o644,
        )?;
        fs::rename(selection_next, self.generation_dir().join("selection.json"))?;
        self.sync(&self.generation_dir())?;
        let loader_next = self.esp.join("loader/astraeus.next");
        write_new(&loader_next, selection.loader_config().as_bytes(), 0o644)?;
        self.sync(&self.esp)?;
        fs::rename(loader_next, self.esp.join("loader/loader.conf"))?;
        self.sync(&self.esp)?;
        // Firmware preferences override loader.conf. Clearing them is part of the journal.
        for verb in ["set-oneshot", "set-default", "set-preferred"] {
            self.commands
                .run("bootctl", &["--esp-path", path_str(&self.esp)?, verb, ""])?;
        }
        // The maintenance UKI must not provide an uncounted Type #2 bypass.
        // The independent fallback is durable and selected before changing either side.
        let legacy = self.esp.join(UKI);
        if legacy.try_exists()? {
            let maintenance = self.esp.join(MAINTENANCE_UKI);
            require(!maintenance.try_exists()?, "maintenance UKI collision")?;
            let preset_path = self.root.join("etc/mkinitcpio.d/linux.preset");
            let preset = read_text(&self.root, "etc/mkinitcpio.d/linux.preset")?;
            let old = format!("/efi/{UKI}");
            require(preset.matches(&old).count() == 1, "unsupported UKI preset")?;
            replace_existing(
                &preset_path,
                preset
                    .replace(&old, &format!("/efi/{MAINTENANCE_UKI}"))
                    .as_bytes(),
            )?;
            self.sync(&self.root)?;
            fs::rename(&legacy, &maintenance)?;
            self.sync(&self.esp)?;
        }
        // Retire old menu entries only after the verified replacement is selectable.
        for generation in self.generations()? {
            if generation.id != selection.previous
                && Some(&generation.id) != selection.current.as_ref()
            {
                if let Some((filename, _)) = self.generation_counter(&generation.id)? {
                    fs::rename(
                        entries.join(&filename),
                        entries.join(format!("{filename}.retired")),
                    )?;
                }
            }
        }
        self.sync(&self.esp)?;
        self.finish(&format!("generation-select-{stamp}"))
    }
    pub(super) fn verify_generation_loader(&self) -> Result<()> {
        let selection = self
            .generation_selection()?
            .ok_or("generation selection missing")?;
        require(
            read_text(&self.esp, "loader/loader.conf")? == selection.loader_config(),
            "boot generation loader configuration changed",
        )
    }
    fn exclusive_generation_entries(&self) -> Result<()> {
        let linux = self.esp.join("EFI/Linux");
        no_links(&linux)?;
        if linux.try_exists()? {
            for entry in fs::read_dir(&linux)? {
                let entry = entry?;
                let name = entry.file_name().to_string_lossy().to_lowercase();
                require(
                    !name.ends_with(".efi") || entry.path() == self.esp.join(UKI),
                    "unmanaged Type #2 UKI could bypass boot assessment",
                )?;
            }
        }
        let entries = self.esp.join("loader/entries");
        no_links(&entries)?;
        if entries.try_exists()? {
            let known = self.generations()?;
            for entry in fs::read_dir(entries)? {
                let entry = entry?;
                let name = entry
                    .file_name()
                    .into_string()
                    .map_err(|_| "invalid boot entry filename")?;
                require(
                    !name.to_lowercase().ends_with(".conf")
                        || known.iter().any(|g| BootCount::parse(&g.id, &name).is_ok()),
                    "unmanaged boot entry could bypass boot assessment",
                )?;
            }
        }
        Ok(())
    }
    pub(super) fn restore_generation_preset(&self, root: &Path) -> Result<()> {
        let path = root.join("etc/mkinitcpio.d/linux.preset");
        let preset = read_text(root, "etc/mkinitcpio.d/linux.preset")?;
        let maintenance = format!("/efi/{MAINTENANCE_UKI}");
        if preset.contains(&maintenance) {
            require(
                preset.matches(&maintenance).count() == 1,
                "unsupported recovery UKI preset",
            )?;
            replace_existing(
                &path,
                preset
                    .replace(&maintenance, &format!("/efi/{UKI}"))
                    .as_bytes(),
            )?;
        }
        Ok(())
    }
    pub fn selected_generation(&self) -> Result<Option<Generation>> {
        if self.generation_selection()?.is_none() {
            return Ok(None);
        }
        let entry = self.loader_variable("LoaderEntrySelected")?;
        let matches: Vec<_> = self
            .generations()?
            .into_iter()
            .filter(|g| g.id.entry() == entry)
            .collect();
        require(
            matches.len() == 1,
            "running boot entry is not a managed generation",
        )?;
        let generation = matches
            .into_iter()
            .next()
            .ok_or("selected generation missing")?;
        let path = self.commands.run("bootctl", &["--print-stub-path"])?;
        require(
            Path::new(&path) == self.esp.join(generation.id.artifact()),
            "booted UKI came from another path or ESP",
        )?;
        Ok(Some(generation))
    }
    fn loader_variable(&self, name: &str) -> Result<String> {
        let path = format!("/sys/firmware/efi/efivars/{name}-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f");
        // Command fixture boundary keeps firmware evidence injectable without touching host EFI.
        let hex = self.commands.run("od", &["-An", "-v", "-t", "x1", &path])?;
        let bytes: Vec<u8> = hex
            .split_whitespace()
            .map(|s| u8::from_str_radix(s, 16))
            .collect::<std::result::Result<_, _>>()?;
        require(
            bytes.len() >= 6 && bytes.len() <= 4096 && bytes.len().is_multiple_of(2),
            "invalid loader EFI variable",
        )?;
        let words: Vec<_> = bytes[4..]
            .chunks_exact(2)
            .map(|v| u16::from_le_bytes([v[0], v[1]]))
            .collect();
        require(
            words.last() == Some(&0) && !words[..words.len() - 1].contains(&0),
            "invalid loader EFI string",
        )?;
        Ok(String::from_utf16(&words[..words.len() - 1])?)
    }
    pub fn bless_generation_locked(
        &self,
        guard: &MutationGuard,
        snapshot: &SnapshotId,
    ) -> Result<()> {
        self.generation_guard(guard)?;
        let Some(selection) = self.generation_selection()? else {
            return Ok(());
        };
        let id = GenerationId::parse(snapshot.as_str())?;
        require(
            selection.current.as_ref() == Some(&id),
            "confirmation is not for the selected candidate",
        )?;
        let generation = self.verify_generation(&id)?;
        require(
            self.selected_generation()?.is_some_and(|g| g.id == id),
            "firmware selected a different generation",
        )?;
        self.verify_running_generation(&generation)?;
        let (filename, count) = self
            .generation_counter(&id)?
            .ok_or("candidate boot entry missing")?;
        if count == BootCount::Uncounted {
            return self.verify_blessing_receipt(&id);
        }
        require(
            matches!(
                count,
                BootCount::Counted {
                    done: 1..=TRIES,
                    ..
                }
            ),
            "no boot counter evidence for candidate",
        )?;
        require(
            self.loader_variable("LoaderBootCountPath")?
                .replace('\\', "/")
                == format!("/loader/entries/{filename}"),
            "EFI counter path differs from verified candidate",
        )?;
        // Only invoked after durable package/root/kernel/service evidence.
        self.begin(&serde_json::json!({"schema_version":1,"operation":"generation-bless","id":id,"entry":filename,"counter":count}))?;
        self.commands.run(
            "systemd-bless-boot",
            &["--path", path_str(&self.esp)?, "good"],
        )?;
        self.sync(&self.esp)?;
        require(
            self.generation_counter(&id)?
                .is_some_and(|(_, c)| c == BootCount::Uncounted),
            "bootloader blessing did not remove candidate counter",
        )?;
        self.finish(&format!("generation-bless-{}", id.as_str()))
    }
    fn verify_blessing_receipt(&self, id: &GenerationId) -> Result<()> {
        let receipt: serde_json::Value = self.generation_read(
            &self
                .store
                .join(format!("operation-generation-bless-{}.json", id.as_str())),
        )?;
        require(
            receipt["schema_version"] == 1
                && receipt["operation"] == "generation-bless"
                && receipt["id"] == id.as_str(),
            "uncounted candidate has no Astraeus blessing receipt",
        )
    }
    pub fn verify_running_generation(&self, generation: &Generation) -> Result<()> {
        require(
            self.top.is_none(),
            "running generation verification requires installed system",
        )?;
        require(
            self.show(&self.root)? == generation.root,
            "booted root identity mismatch",
        )?;
        let running = self.commands.run("cat", &["/proc/cmdline"])?;
        require(
            boot_command_line_matches(&generation.embedded_cmdline, &running),
            "booted command line differs from generation UKI",
        )?;
        let bytes = fs::read(self.esp.join(generation.id.artifact()))?;
        let uname = std::str::from_utf8(pe_section(&bytes, b".uname")?)?.trim_end_matches('\0');
        require(
            self.commands.run("uname", &["-r"])? == uname,
            "booted kernel differs from generation",
        )
    }
    pub(super) fn finish_generation_rollback(&self, stamp: &str) -> Result<()> {
        if self.generation_selection()?.is_none() {
            return Ok(());
        }
        self.verify_artifact_trust(&self.esp.join(UKI))?;
        let temporary = self.esp.join("loader/astraeus-rollback.next");
        write_new(
            &temporary,
            b"default astraeus-dev-linux.efi\ntimeout 3\neditor no\n",
            0o644,
        )?;
        self.sync(&self.esp)?;
        let maintenance = self.esp.join(MAINTENANCE_UKI);
        if maintenance.try_exists()? {
            fs::rename(
                &maintenance,
                maintenance.with_file_name(format!("maintenance-{stamp}.retained")),
            )?;
            self.sync(&self.esp)?;
        }
        fs::rename(temporary, self.esp.join("loader/loader.conf"))?;
        for verb in ["set-oneshot", "set-default", "set-preferred"] {
            self.commands
                .run("bootctl", &["--esp-path", path_str(&self.esp)?, verb, ""])?;
        }
        for generation in self.generations()? {
            if let Some((filename, _)) = self.generation_counter(&generation.id)? {
                let entry = self.esp.join("loader/entries").join(&filename);
                fs::rename(
                    &entry,
                    entry.with_file_name(format!("{filename}.rollback-{stamp}")),
                )?;
            }
        }
        self.sync(&self.esp)?;
        fs::rename(
            self.generation_dir().join("selection.json"),
            self.store
                .join(format!("operation-generation-reset-{stamp}.json")),
        )?;
        self.sync(&self.store)
    }
    pub(super) fn quiesce_generation_candidate(&self, stamp: &str) -> Result<()> {
        let Some(selection) = self.generation_selection()? else {
            return Ok(());
        };
        let fallback = Selection {
            schema_version: 1,
            current: None,
            previous: selection.previous,
        };
        let temporary = self.esp.join("loader/astraeus-quiesce.next");
        write_new(&temporary, fallback.loader_config().as_bytes(), 0o644)?;
        self.sync(&self.esp)?;
        fs::rename(temporary, self.esp.join("loader/loader.conf"))?;
        self.sync(&self.esp)?;
        for verb in ["set-oneshot", "set-default", "set-preferred"] {
            self.commands
                .run("bootctl", &["--esp-path", path_str(&self.esp)?, verb, ""])?;
        }
        if let Some(current) = selection.current {
            if let Some((filename, _)) = self.generation_counter(&current)? {
                let path = self.esp.join("loader/entries").join(&filename);
                fs::rename(
                    &path,
                    path.with_file_name(format!("{filename}.rollback-{stamp}")),
                )?;
                self.sync(&self.esp)?;
            }
        }
        Ok(())
    }
    pub(super) fn verify_generation_rollback(&self, snapshot: &SnapshotId) -> Result<()> {
        let Some(selection) = self.generation_selection()? else {
            return Ok(());
        };
        let previous = self.verify_generation(&selection.previous)?;
        require(
            previous.snapshot == *snapshot,
            "managed recovery must restore the selected prior snapshot",
        )?;
        self.verify_artifact_trust(&self.entry(snapshot)?.join("private/boot.efi"))?;
        Ok(())
    }
}

fn replace_existing(path: &Path, bytes: &[u8]) -> Result<()> {
    no_links(path)?;
    let mut file = OpenOptions::new().write(true).truncate(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}
