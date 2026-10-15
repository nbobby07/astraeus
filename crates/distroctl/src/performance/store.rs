use super::{Report, Result, MAX_REPORT};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};

pub(super) fn valid_id(id: &str) -> bool {
    id.len() == 32
        && id
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn options() -> OpenOptions {
    let mut o = OpenOptions::new();
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        o.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
            .mode(0o600);
    }
    o.read(true);
    o
}
fn file_private(file: &File) -> Result<()> {
    let m = file.metadata().map_err(|e| e.to_string())?;
    if !m.is_file() {
        return Err("performance state is not a regular file".into());
    }
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::MetadataExt;
        if m.uid() != unsafe { libc::geteuid() } || m.mode() & 0o077 != 0 || m.nlink() != 1 {
            return Err("performance state must be private, owned and unlinked elsewhere".into());
        }
    }
    Ok(())
}
fn directory(path: &Path, _private: bool) -> Result<()> {
    if !path.is_absolute() {
        return Err("performance state directory must be absolute".into());
    }
    let mut chain: Vec<_> = path.ancestors().collect();
    chain.reverse();
    for p in chain {
        match fs::symlink_metadata(p) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                #[allow(unused_mut)]
                let mut builder = fs::DirBuilder::new();
                #[cfg(unix)]
                {
                    use std::os::unix::fs::DirBuilderExt;
                    builder.mode(0o700);
                }
                builder.create(p).map_err(|e| e.to_string())?;
            }
            Err(e) => return Err(e.to_string()),
            Ok(_) => {}
        }
        let m = fs::symlink_metadata(p).map_err(|e| e.to_string())?;
        if !m.is_dir() || m.file_type().is_symlink() {
            return Err("performance state contains a symlink or non-directory".into());
        }
        #[cfg(target_os = "linux")]
        {
            use std::os::unix::fs::MetadataExt;
            let uid = unsafe { libc::geteuid() };
            let sticky_temp = cfg!(test) && p == Path::new("/tmp") && m.mode() & libc::S_ISVTX != 0;
            if (m.uid() != uid && m.uid() != 0)
                || (m.mode() & 0o022 != 0 && !sticky_temp)
                || (_private && p == path && (m.uid() != uid || m.mode() & 0o077 != 0))
            {
                return Err("untrusted performance state directory permissions".into());
            }
        }
    }
    Ok(())
}
pub(super) struct Store {
    pub path: PathBuf,
}
impl Store {
    pub fn open() -> Result<Self> {
        #[cfg(not(target_os = "linux"))]
        {
            Err("performance storage requires Linux".into())
        }
        #[cfg(target_os = "linux")]
        {
            if unsafe { libc::geteuid() } == 0 {
                return Err("run performance measurements as your ordinary desktop user".into());
            }
            let base = match std::env::var_os("XDG_STATE_HOME").filter(|s| !s.is_empty()) {
                Some(v) => PathBuf::from(v),
                None => PathBuf::from(std::env::var_os("HOME").ok_or("HOME is unavailable")?)
                    .join(".local/state"),
            };
            Self::at(base.join("astraeus/performance"))
        }
    }
    #[cfg(any(target_os = "linux", test))]
    pub fn at(path: PathBuf) -> Result<Self> {
        directory(&path, true)?;
        Ok(Self { path })
    }
    pub fn lock(&self) -> Result<File> {
        directory(&self.path, true)?;
        let mut o = options();
        o.write(true).create(true).truncate(false);
        let f = o
            .open(self.path.join("active.lock"))
            .map_err(|e| e.to_string())?;
        file_private(&f)?;
        f.try_lock()
            .map_err(|_| "another measurement is running for this user")?;
        Ok(f)
    }
    pub fn create(&self, id: &str) -> Result<()> {
        if !valid_id(id) {
            return Err("invalid performance run ID".into());
        }
        let p = self.path.join(id);
        #[allow(unused_mut)]
        let mut builder = fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder.create(&p).map_err(|e| e.to_string())?;
        directory(&p, true)
    }
    pub fn write(&self, report: &Report) -> Result<()> {
        report.validate()?;
        let p = self.path.join(&report.id);
        directory(&p, true)?;
        let data = serde_json::to_vec(report).map_err(|e| e.to_string())?;
        if data.len() > MAX_REPORT {
            return Err("performance report exceeds 2 MiB".into());
        }
        let temporary = p.join(format!("result-{}.tmp", std::process::id()));
        let mut o = options();
        o.write(true).create_new(true);
        let mut f = o.open(&temporary).map_err(|e| e.to_string())?;
        let result = (|| {
            file_private(&f)?;
            f.write_all(&data).map_err(|e| e.to_string())?;
            f.sync_all().map_err(|e| e.to_string())?;
            let target = p.join("result.json");
            if let Ok(m) = fs::symlink_metadata(&target) {
                if !m.is_file() || m.file_type().is_symlink() {
                    return Err("result target is not a regular file".into());
                }
            }
            fs::rename(&temporary, &target).map_err(|e| e.to_string())?;
            #[cfg(unix)]
            File::open(&p)
                .and_then(|f| f.sync_all())
                .map_err(|e| e.to_string())?;
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        result
    }
    pub fn read(&self, id: &str) -> Result<Report> {
        if !valid_id(id) {
            return Err("invalid performance run ID".into());
        }
        let dir = self.path.join(id);
        directory_existing(&dir)?;
        let f = options()
            .open(dir.join("result.json"))
            .map_err(|e| e.to_string())?;
        file_private(&f)?;
        let mut data = Vec::new();
        f.take((MAX_REPORT + 1) as u64)
            .read_to_end(&mut data)
            .map_err(|e| e.to_string())?;
        if data.len() > MAX_REPORT {
            return Err("performance report exceeds 2 MiB".into());
        }
        let report: Report = serde_json::from_slice(&data)
            .map_err(|e| format!("invalid performance report: {e}"))?;
        report.validate()?;
        if report.id != id {
            return Err("performance report ID mismatch".into());
        }
        Ok(report)
    }
    pub fn list(&self) -> Result<Vec<serde_json::Value>> {
        let mut names = fs::read_dir(&self.path)
            .map_err(|e| e.to_string())?
            .filter_map(|e| e.ok()?.file_name().into_string().ok())
            .filter(|s| valid_id(s))
            .collect::<Vec<_>>();
        names.sort();
        if names.len() > 1000 {
            return Err(
                "more than 1000 saved runs; archive old results manually before listing".into(),
            );
        }
        let mut rows = vec![];
        for id in names {
            match self.read(&id){Ok(r)=>rows.push(serde_json::json!({"id":id,"kind":r.kind,"state":r.state,"created_unix_seconds":r.created_unix_seconds,"elapsed_seconds":r.elapsed_seconds,"failure":r.failure})),Err(e)=>rows.push(serde_json::json!({"id":id,"state":"unreadable","failure":e}))}
        }
        rows.sort_by_key(|r| std::cmp::Reverse(r["created_unix_seconds"].as_u64().unwrap_or(0)));
        Ok(rows)
    }
}
fn directory_existing(path: &Path) -> Result<()> {
    if !fs::symlink_metadata(path)
        .map_err(|e| e.to_string())?
        .is_dir()
    {
        return Err("run directory missing".into());
    }
    directory(path, true)
}
