//! Root-contained management state. History stays outside this rollback boundary.
use crate::{InstallReason, ManagementState, Result};
use std::{
    collections::BTreeMap,
    fs,
    io::{Read, Write},
    path::Path,
};

pub const STATE: &str = "var/lib/astraeus/management/state.json";
pub const LOCK: &str = "var/lib/astraeus/management/system.lock";
pub const CONFIG: &str = "etc/astraeus/system.toml";

pub fn trusted_directory(path: &Path) -> Result<()> {
    if !path.is_absolute() {
        return Err("trusted path must be absolute".into());
    }
    for part in path.ancestors() {
        let meta = fs::symlink_metadata(part).map_err(|e| format!("{}: {e}", part.display()))?;
        if !meta.is_dir() || meta.file_type().is_symlink() {
            return Err("management path contains a link or non-directory".into());
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            #[cfg(not(test))]
            let owner = 0;
            #[cfg(test)]
            let owner = unsafe { libc::geteuid() };
            // /tmp is used only by unit fixtures, never by the installed path.
            if meta.uid() != owner && meta.uid() != 0
                || meta.mode() & 0o022 != 0 && !(cfg!(test) && part == Path::new("/tmp"))
            {
                return Err(format!("untrusted directory {}", part.display()));
            }
        }
    }
    Ok(())
}

pub fn read_text(path: &Path, limit: u64) -> Result<String> {
    trusted_directory(path.parent().ok_or("missing parent")?)?;
    let observed = fs::symlink_metadata(path).map_err(|e| e.to_string())?;
    if observed.file_type().is_symlink() || !observed.is_file() {
        return Err("management path is not a regular file".into());
    }
    let mut options = fs::OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK);
    }
    let file = options
        .open(path)
        .map_err(|e| format!("{}: {e}", path.display()))?;
    let meta = file.metadata().map_err(|e| e.to_string())?;
    if !meta.is_file() || meta.len() > limit {
        return Err("invalid or oversized management file".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        #[cfg(not(test))]
        let owner = 0;
        #[cfg(test)]
        let owner = unsafe { libc::geteuid() };
        if meta.uid() != owner || meta.mode() & 0o022 != 0 || meta.nlink() != 1 {
            return Err("untrusted management file".into());
        }
    }
    let mut text = String::new();
    file.take(limit + 1)
        .read_to_string(&mut text)
        .map_err(|e| e.to_string())?;
    if text.len() as u64 > limit {
        return Err("oversized management file".into());
    }
    Ok(text)
}

pub fn read_state(root: &Path) -> Result<Option<ManagementState>> {
    trusted_directory(root)?;
    for relative in [STATE, CONFIG, LOCK] {
        if present(&root.join(relative).with_extension("pending"))? {
            return Err("unfinished management publication; preserve files for recovery".into());
        }
    }
    let path = root.join(STATE);
    if !present(&path)? {
        if present(&root.join(CONFIG))? || present(&root.join(LOCK))? {
            return Err("incomplete management state; preserve files for recovery".into());
        }
        return Ok(None);
    }
    let state: ManagementState = serde_json::from_str(&read_text(&path, 32 * 1024 * 1024)?)
        .map_err(|e| format!("management state: {e}"))?;
    state.validate()?;
    let config = distro_config::parse_system_toml(&read_text(&root.join(CONFIG), 256 * 1024)?)?;
    let lock: serde_json::Value =
        serde_json::from_str(&read_text(&root.join(LOCK), 32 * 1024 * 1024)?)
            .map_err(|e| e.to_string())?;
    if config != state.applied || lock != lock_value(&state)? {
        return Err(
            "applied configuration, ownership and system.lock disagree; recovery required".into(),
        );
    }
    Ok(Some(state))
}

fn present(path: &Path) -> Result<bool> {
    for parent in path.parent().ok_or("missing parent")?.ancestors() {
        match fs::symlink_metadata(parent) {
            Ok(_) => {
                trusted_directory(parent)?;
                break;
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.to_string()),
        }
    }
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.is_file() && !metadata.file_type().is_symlink() => Ok(true),
        Ok(_) => Err("management path is not a regular file".into()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(e.to_string()),
    }
}

fn lock_value(state: &ManagementState) -> Result<serde_json::Value> {
    Ok(
        serde_json::json!({"schema_version":1,"management_sha256":state.digest(),"repositories":state.repositories,"packages":state.resolution,"providers":state.resolved_providers,"configured_providers":state.applied.providers}),
    )
}

pub fn ensure_directory(path: &Path, mode: u32) -> Result<()> {
    if !path.exists() {
        let parent = path.parent().ok_or("missing directory parent")?;
        ensure_directory(parent, 0o755)?;
        #[cfg(unix)]
        let builder = {
            use std::os::unix::fs::DirBuilderExt;
            let mut value = fs::DirBuilder::new();
            value.mode(mode);
            value
        };
        #[cfg(not(unix))]
        let builder = {
            let _ = mode;
            fs::DirBuilder::new()
        };
        builder.create(path).map_err(|e| e.to_string())?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(path, fs::Permissions::from_mode(mode))
                .map_err(|e| e.to_string())?;
        }
    }
    trusted_directory(path)
}

pub fn atomic_write(path: &Path, bytes: &[u8], mode: u32) -> Result<()> {
    let parent = path.parent().ok_or("missing parent")?;
    trusted_directory(parent)?;
    if present(path)? {
        let _ = read_text(path, 32 * 1024 * 1024)?;
    }
    let temporary = path.with_extension("pending");
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(mode);
    }
    #[cfg(not(unix))]
    let _ = mode;
    let mut file = options
        .open(&temporary)
        .map_err(|e| format!("stage {}: {e}", temporary.display()))?;
    file.write_all(bytes).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        file.set_permissions(fs::Permissions::from_mode(mode))
            .map_err(|e| e.to_string())?;
    }
    file.sync_all().map_err(|e| e.to_string())?;
    drop(file);
    fs::rename(&temporary, path).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    fs::File::open(parent)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Caller holds both mutation locks and has persisted Applying after a pre-snapshot.
pub fn write_state(root: &Path, state: &ManagementState) -> Result<()> {
    state.validate()?;
    ensure_directory(&root.join("var/lib/astraeus/management"), 0o755)?;
    ensure_directory(&root.join("etc/astraeus"), 0o755)?;
    atomic_write(
        &root.join(CONFIG),
        state.applied.to_toml()?.as_bytes(),
        0o644,
    )?;
    atomic_write(
        &root.join(LOCK),
        &serde_json::to_vec_pretty(&lock_value(state)?).map_err(|e| e.to_string())?,
        0o644,
    )?;
    atomic_write(
        &root.join(STATE),
        &serde_json::to_vec_pretty(state).map_err(|e| e.to_string())?,
        0o644,
    )?;
    if read_state(root)?.as_ref() != Some(state) {
        return Err("management state readback failed".into());
    }
    Ok(())
}

pub fn read_reasons(root: &Path) -> Result<BTreeMap<String, InstallReason>> {
    let local = root.join("var/lib/pacman/local");
    trusted_directory(&local)?;
    let mut result = BTreeMap::new();
    for entry in fs::read_dir(local).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        if entry.file_name() == "ALPM_DB_VERSION" {
            continue;
        }
        let desc = read_text(&entry.path().join("desc"), 1024 * 1024)?;
        let name = crate::pacman::database_field(&desc, "NAME")?.to_string();
        if !distro_config::valid_package_name(&name) {
            return Err("invalid installed package name".into());
        }
        // libalpm omits the default explicit reason from local database records.
        let lines: Vec<_> = desc.lines().collect();
        let markers: Vec<_> = lines
            .iter()
            .enumerate()
            .filter(|(_, line)| **line == "%REASON%")
            .map(|(index, _)| index)
            .collect();
        let reason = match markers.as_slice() {
            [] => InstallReason::Explicit,
            [index] => match lines[index + 1..]
                .iter()
                .take_while(|line| !line.is_empty())
                .copied()
                .collect::<Vec<_>>()
                .as_slice()
            {
                ["0"] => InstallReason::Explicit,
                ["1"] => InstallReason::Dependency,
                _ => return Err("invalid installed package reason".into()),
            },
            _ => return Err("duplicate installed package reason".into()),
        };
        if result.insert(name, reason).is_some() {
            return Err("duplicate installed package".into());
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    static NEXT: AtomicUsize = AtomicUsize::new(0);
    struct Root(std::path::PathBuf);
    impl Root {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "astraeus-management-store-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for Root {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }
    #[test]
    fn rejects_incomplete_or_inconsistent_state() {
        let temporary = Root::new();
        let root = &temporary.0;
        let state = ManagementState::default();
        write_state(root, &state).unwrap();
        assert_eq!(read_state(root).unwrap(), Some(state));
        fs::write(root.join(CONFIG), "schema_version=1\npackages=['other']\n").unwrap();
        assert!(read_state(root).is_err());
    }
    #[test]
    fn absent_explicit_reason_matches_libalpm_but_invalid_or_duplicate_reason_is_rejected() {
        let temporary = Root::new();
        let root = &temporary.0;
        let desc = root.join("var/lib/pacman/local/fixture-1-1/desc");
        fs::create_dir_all(desc.parent().unwrap()).unwrap();
        for (field, expected) in [
            ("", InstallReason::Explicit),
            ("%REASON%\n0\n", InstallReason::Explicit),
            ("%REASON%\n1\n", InstallReason::Dependency),
        ] {
            fs::write(&desc, format!("%NAME%\nfixture\n\n{field}")).unwrap();
            assert_eq!(read_reasons(root).unwrap()["fixture"], expected);
        }
        for field in [
            "%REASON%\n2\n",
            "%REASON%\n\n",
            "%REASON%\n0\n1\n",
            "%REASON%\n0\n\n%REASON%\n1\n",
        ] {
            fs::write(&desc, format!("%NAME%\nfixture\n\n{field}")).unwrap();
            assert!(read_reasons(root).is_err());
        }
    }
    #[test]
    fn pending_publication_refuses_a_consistent_but_incomplete_receipt() {
        let temporary = Root::new();
        let root = &temporary.0;
        write_state(root, &ManagementState::default()).unwrap();
        fs::write(root.join(CONFIG).with_extension("pending"), "unfinished").unwrap();
        assert!(read_state(root).unwrap_err().contains("unfinished"));
    }
    #[cfg(unix)]
    #[test]
    fn dangling_state_link_cannot_look_like_an_unmanaged_system() {
        use std::os::unix::fs::symlink;
        let temporary = Root::new();
        let root = &temporary.0;
        let path = root.join(STATE);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        symlink(root.join("missing.json"), &path).unwrap();
        assert!(read_state(root).is_err());
        assert!(atomic_write(&path, b"{}", 0o644).is_err());
        assert!(fs::symlink_metadata(path).unwrap().file_type().is_symlink());
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn service_umask_does_not_hide_public_management_state() {
        use std::os::unix::{fs::PermissionsExt, process::CommandExt};
        const CHILD: &str = "ASTRAEUS_TEST_MANAGEMENT_UMASK_CHILD";
        if std::env::var_os(CHILD).is_none() {
            let mut child = std::process::Command::new(std::env::current_exe().unwrap());
            child
                .args([
                    "--exact",
                    "management_store::tests::service_umask_does_not_hide_public_management_state",
                    "--nocapture",
                ])
                .env(CHILD, "1");
            // Isolate the process-wide umask from other tests running in parallel.
            unsafe {
                child.pre_exec(|| {
                    libc::umask(0o077);
                    Ok(())
                });
            }
            let output = child.output().unwrap();
            assert!(
                output.status.success(),
                "{}\n{}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            );
            return;
        }
        let temporary = Root::new();
        write_state(&temporary.0, &ManagementState::default()).unwrap();
        for path in [STATE, LOCK, CONFIG] {
            assert_eq!(
                fs::metadata(temporary.0.join(path))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o644,
                "{path}"
            );
        }
        for path in [
            "etc",
            "etc/astraeus",
            "var",
            "var/lib",
            "var/lib/astraeus",
            "var/lib/astraeus/management",
        ] {
            assert_eq!(
                fs::metadata(temporary.0.join(path))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o755,
                "{path}"
            );
        }
    }
}
