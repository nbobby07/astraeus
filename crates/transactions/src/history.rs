use crate::{Failure, Result, TransactionRecord, TransactionState};
use rusqlite::{params, Connection, OpenFlags};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    path::{Path, PathBuf},
};

pub const HISTORY_PATH: &str = "/var/log/astraeus/transactions.sqlite";
pub const PRIVATE_HISTORY_PATH: &str = "/var/log/astraeus/private/transactions.sqlite";
pub const LOCK_PATH: &str = "/run/astraeus-update.lock";

struct UpdateLock(File);

impl Drop for UpdateLock {
    fn drop(&mut self) {
        // Closing one descriptor does not release flock while a forked child retains it.
        let _ = self.0.unlock();
    }
}

/// Held until the session ends. Never unlink a held lock file.
pub struct UpdateSession {
    db: Connection,
    // Field drop order closes the database before releasing its writer lock.
    _lock: UpdateLock,
    public: Option<PathBuf>,
}

fn records(db: &Connection) -> Result<Vec<TransactionRecord>> {
    // ponytail: scan the small history; add indexed summaries/pagination when history grows large.
    let mut statement = db
        .prepare("SELECT id, record FROM transactions ORDER BY id DESC")
        .map_err(|e| e.to_string())?;
    let rows = statement
        .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))
        .map_err(|e| e.to_string())?;
    let database_version = version(db)?;
    require_version(database_version)?;
    rows.map(|row| {
        let (id, json) = row.map_err(|e| e.to_string())?;
        let record: TransactionRecord = serde_json::from_str(&json).map_err(|e| e.to_string())?;
        if !matches!(record.schema_version, 1 | 2)
            || !matches!(record.plan.schema_version, 1 | 2)
            || record.schema_version > database_version as u32
            || record.plan.schema_version > record.schema_version
            || (record.plan.management.is_some() && record.plan.schema_version != 2)
            || record.id != id
            || id <= 0
        {
            return Err("unsupported or inconsistent transaction record schema".into());
        }
        Ok(record)
    })
    .collect()
}

fn version(db: &Connection) -> Result<i64> {
    db.pragma_query_value(None, "user_version", |r| r.get(0))
        .map_err(|e| e.to_string())
}

fn require_version(version: i64) -> Result<()> {
    if matches!(version, 1 | 2) {
        Ok(())
    } else {
        Err("unsupported history schema".into())
    }
}

pub fn read_history(path: &Path) -> Result<Vec<TransactionRecord>> {
    match path.try_exists() {
        Ok(false) => return Ok(vec![]),
        Err(e) => return Err(e.to_string()),
        _ => {}
    }
    let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|e| e.to_string())?;
    require_version(version(&db)?)?;
    records(&db)
}

pub fn read_recovery_history(public: &Path) -> Result<Vec<TransactionRecord>> {
    let private = public
        .parent()
        .ok_or("history directory missing")?
        .join("private")
        .join(public.file_name().ok_or("history filename missing")?);
    if !private.try_exists().map_err(|e| e.to_string())? {
        return read_history(public);
    }
    if !public.try_exists().map_err(|e| e.to_string())? {
        return read_history(&private);
    }
    let current = Connection::open_with_flags(private, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|e| e.to_string())?;
    let published = Connection::open_with_flags(public, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|e| e.to_string())?;
    records(if legacy_changed(&current, &published)? {
        &published
    } else {
        &current
    })
}

fn legacy_changed(current: &Connection, published: &Connection) -> Result<bool> {
    require_version(version(current)?)?;
    require_version(version(published)?)?;
    let baseline: String = published
        .query_row("SELECT digest FROM astraeus_publication", [], |r| r.get(0))
        .map_err(|_| {
            "public history lacks publication evidence; preserve both databases for recovery"
                .to_string()
        })?;
    if records_digest(published)? == baseline {
        return Ok(false);
    }
    if records_digest(current)? != baseline {
        return Err(
            "private and legacy history diverged; preserve both databases for recovery".into(),
        );
    }
    Ok(true)
}

impl UpdateSession {
    /// Callers supply trusted paths. The lock must be shared by every system update.
    pub fn open(path: &Path, lock_path: &Path) -> Result<Self> {
        Self::open_inner(path, lock_path, None)
    }

    /// Keep public readers on replaceable copies, never on the writer's SQLite inode.
    pub fn open_published(path: &Path, lock_path: &Path, public: &Path) -> Result<Self> {
        let parent = path.parent().ok_or("history directory missing")?;
        no_links(parent).map_err(|e| e.to_string())?;
        no_links(public).map_err(|e| e.to_string())?;
        let mut directory = fs::DirBuilder::new();
        directory.recursive(false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            directory.mode(0o700);
        }
        match directory.create(parent) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(e) => return Err(e.to_string()),
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(parent, fs::Permissions::from_mode(0o700))
                .map_err(|e| e.to_string())?;
        }
        Self::open_inner(path, lock_path, Some(public.to_path_buf()))
    }

    fn open_inner(path: &Path, lock_path: &Path, public: Option<PathBuf>) -> Result<Self> {
        let lock = private_file(lock_path).map_err(|e| format!("update lock: {e}"))?;
        lock.try_lock()
            .map_err(|e| format!("another Astraeus update holds the lock: {e}"))?;
        let lock = UpdateLock(lock);
        no_links(path).map_err(|e| e.to_string())?;
        if let Some(source) = public.as_ref() {
            if source.try_exists().map_err(|e| e.to_string())? {
                let exists = path.try_exists().map_err(|e| e.to_string())?;
                let legacy = Connection::open_with_flags(source, OpenFlags::SQLITE_OPEN_READ_WRITE)
                    .map_err(|e| e.to_string())?;
                require_version(version(&legacy)?)?;
                let changed = if exists {
                    let current =
                        Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_WRITE)
                            .map_err(|e| e.to_string())?;
                    legacy_changed(&current, &legacy)?
                } else {
                    records(&legacy)?;
                    true
                };
                if changed {
                    // A restored old updater may have written newer public history under this lock.
                    snapshot(&legacy, path, path.with_extension("migration"), false)?;
                }
            }
        }
        private_file(path).map_err(|e| e.to_string())?;
        let db = Connection::open(path).map_err(|e| e.to_string())?;
        match version(&db)? {
            0 => db.execute_batch("BEGIN IMMEDIATE;
                CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, record TEXT NOT NULL);
                PRAGMA user_version=2;
                COMMIT;").map_err(|e| e.to_string())?,
            1 => {
                records(&db)?;
                db.execute_batch("BEGIN IMMEDIATE; PRAGMA user_version=2; COMMIT;")
                    .map_err(|e| e.to_string())?;
            },
            2 => { records(&db)?; },
            _ => return Err("unsupported history schema".into()),
        }
        db.execute_batch("PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL;")
            .map_err(|e| e.to_string())?;
        let session = Self {
            db,
            _lock: lock,
            public,
        };
        session.publish()?;
        Ok(session)
    }

    fn publish(&self) -> Result<()> {
        if let Some(public) = &self.public {
            let private = Path::new(self.db.path().ok_or("history database path missing")?);
            snapshot(
                &self.db,
                public,
                private.with_extension("publication"),
                true,
            )?;
        }
        Ok(())
    }

    pub fn records(&self) -> Result<Vec<TransactionRecord>> {
        records(&self.db)
    }

    pub fn insert(&mut self, record: &mut TransactionRecord) -> Result<()> {
        if record.id != 0 {
            return Err("transaction already has an ID".into());
        }
        let tx = self.db.transaction().map_err(|e| e.to_string())?;
        tx.execute("INSERT INTO transactions(record) VALUES ('{}')", [])
            .map_err(|e| e.to_string())?;
        let mut saved = record.clone();
        saved.id = tx.last_insert_rowid();
        tx.execute(
            "UPDATE transactions SET record=?1 WHERE id=?2",
            params![
                serde_json::to_string(&saved).map_err(|e| e.to_string())?,
                saved.id
            ],
        )
        .map_err(|e| e.to_string())?;
        tx.commit().map_err(|e| e.to_string())?;
        *record = saved;
        self.publish()
    }

    pub(crate) fn save(&mut self, record: &TransactionRecord) -> Result<()> {
        self.store(record)?;
        self.publish()
    }

    fn store(&mut self, record: &TransactionRecord) -> Result<()> {
        let count = self
            .db
            .execute(
                "UPDATE transactions SET record=?1 WHERE id=?2",
                params![
                    serde_json::to_string(record).map_err(|e| e.to_string())?,
                    record.id
                ],
            )
            .map_err(|e| e.to_string())?;
        if count != 1 {
            return Err("transaction record missing".into());
        }
        Ok(())
    }

    pub(crate) fn advance(
        &mut self,
        record: &mut TransactionRecord,
        next: TransactionState,
    ) -> Result<()> {
        let mut saved = record.clone();
        saved.transition(next)?;
        self.store(&saved)?;
        *record = saved;
        self.publish()
    }

    /// Only run while holding the update lock. No retries of package mutation.
    pub fn recover_interrupted(&mut self) -> Result<()> {
        for mut record in self.records()? {
            if record.state.terminal()
                || matches!(
                    record.state,
                    TransactionState::AwaitingBoot | TransactionState::RollbackRequired
                )
            {
                continue;
            }
            let next = if record.state.mutation_possible() {
                TransactionState::RollbackRequired
            } else {
                TransactionState::Failed
            };
            record.failure = Some(Failure { at: record.state, message: "previous updater stopped before completing this phase; inspect pacman lock/log before recovery".into(), interrupted: true });
            self.advance(&mut record, next)?;
        }
        Ok(())
    }

    pub fn ensure_ready(&mut self) -> Result<()> {
        self.recover_interrupted()?;
        if self.records()?.iter().any(|r| !r.state.terminal()) {
            return Err("previous transaction needs boot confirmation or recovery; inspect distroctl history".into());
        }
        Ok(())
    }
}

fn private_file(path: &Path) -> std::io::Result<File> {
    no_links(path)?;
    match fs::symlink_metadata(path) {
        Ok(metadata) if !metadata.is_file() => {
            return Err(std::io::Error::other(
                "history or lock path is not a regular file",
            ))
        }
        Ok(_) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(e),
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(true).truncate(false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK);
    }
    let file = options.open(path)?;
    if !file.metadata()?.is_file() {
        return Err(std::io::Error::other(
            "history or lock path is not a regular file",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};
        if file.metadata()?.nlink() != 1 {
            return Err(std::io::Error::other(
                "history or lock file has multiple links",
            ));
        }
        file.set_permissions(fs::Permissions::from_mode(0o600))?;
    }
    Ok(file)
}

fn no_links(path: &Path) -> std::io::Result<()> {
    if !path.is_absolute() {
        return Err(std::io::Error::other("history path must be absolute"));
    }
    for ancestor in path.ancestors() {
        match fs::symlink_metadata(ancestor) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                return Err(std::io::Error::other("symlink in history path"))
            }
            Ok(metadata) => {
                #[cfg(target_os = "linux")]
                {
                    use std::os::unix::fs::MetadataExt;
                    let owner = unsafe { libc::geteuid() };
                    if (metadata.uid() != 0 && metadata.uid() != owner)
                        || (metadata.is_dir()
                            && metadata.mode() & 0o022 != 0
                            && !(metadata.uid() == 0 && metadata.mode() & 0o1000 != 0))
                    {
                        return Err(std::io::Error::other(
                            "untrusted history path ownership or permissions",
                        ));
                    }
                }
                #[cfg(not(target_os = "linux"))]
                let _ = metadata;
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e),
        }
    }
    Ok(())
}

fn records_digest(db: &Connection) -> Result<String> {
    records(db)?;
    // Hash the stored JSON, so added serde defaults cannot invalidate a legacy publication.
    let mut query = db
        .prepare("SELECT record FROM transactions ORDER BY id DESC")
        .map_err(|e| e.to_string())?;
    let rows = query
        .query_map([], |r| r.get::<_, String>(0))
        .map_err(|e| e.to_string())?;
    let json = rows
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    Ok(crate::hex(&Sha256::digest(
        format!("[{}]", json.join(",")).as_bytes(),
    )))
}

fn snapshot(
    db: &Connection,
    destination: &Path,
    temporary: PathBuf,
    publication: bool,
) -> Result<()> {
    no_links(destination).map_err(|e| e.to_string())?;
    no_links(&temporary).map_err(|e| e.to_string())?;
    match fs::remove_file(&temporary) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(e.to_string()),
    }
    db.execute(
        "VACUUM main INTO ?1",
        [temporary.to_str().ok_or("invalid history path")?],
    )
    .map_err(|e| e.to_string())?;
    if publication {
        let copy = Connection::open(&temporary).map_err(|e| e.to_string())?;
        copy.execute_batch("CREATE TABLE IF NOT EXISTS astraeus_publication (digest TEXT NOT NULL); DELETE FROM astraeus_publication;")
            .map_err(|e| e.to_string())?;
        copy.execute(
            "INSERT INTO astraeus_publication VALUES (?1)",
            [records_digest(db)?],
        )
        .map_err(|e| e.to_string())?;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(
            &temporary,
            fs::Permissions::from_mode(if publication { 0o644 } else { 0o600 }),
        )
        .map_err(|e| e.to_string())?;
    }
    OpenOptions::new()
        .write(true)
        .open(&temporary)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())?;
    fs::rename(&temporary, destination).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    File::open(destination.parent().ok_or("history directory missing")?)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[cfg(test)]
mod migration_tests {
    use super::*;
    use crate::{CurrentSystemState, ExecutionPlan, PackagePlan};
    use std::sync::atomic::{AtomicUsize, Ordering};

    static NEXT: AtomicUsize = AtomicUsize::new(0);
    struct Directory(PathBuf);
    impl Directory {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "astraeus-history-v2-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for Directory {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }
    fn record() -> TransactionRecord {
        let mut record = TransactionRecord::new(ExecutionPlan::new(
            CurrentSystemState::new(Default::default()),
            PackagePlan {
                changes: vec![],
                targets: vec![],
                download_bytes: 0,
                installed_delta_bytes: Some(0),
            },
        ));
        record.id = 1;
        record.schema_version = 1;
        record.timestamp = 1;
        record.events[0].timestamp = 1;
        record
    }
    fn legacy(path: &Path) -> String {
        let db = Connection::open(path).unwrap();
        db.execute_batch("CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, record TEXT NOT NULL); PRAGMA user_version=1;").unwrap();
        let json = serde_json::to_string(&record())
            .unwrap()
            .replace(",\"management\":null", "")
            .replace(",\"operation_id\":null", "");
        db.execute("INSERT INTO transactions VALUES (1,?1)", [&json])
            .unwrap();
        json
    }

    #[cfg(unix)]
    #[test]
    fn session_releases_lock_while_an_inherited_descriptor_remains_open() {
        let temp = Directory::new();
        let history = temp.0.join("history.sqlite");
        let lock = temp.0.join("update.lock");
        let session = UpdateSession::open(&history, &lock).unwrap();
        let inherited = session._lock.0.try_clone().unwrap();
        assert!(UpdateSession::open(&history, &lock).is_err());
        drop(session);
        let next = UpdateSession::open(&history, &lock).unwrap();
        drop(inherited);
        assert!(UpdateSession::open(&history, &lock).is_err());
        drop(next);
        assert!(UpdateSession::open(&history, &lock).is_ok());
    }

    #[test]
    fn legacy_migration_is_read_only_until_writer_lock_and_preserves_raw_publication_digest() {
        let temp = Directory::new();
        let public = temp.0.join("history.sqlite");
        let private = temp.0.join("private/history.sqlite");
        let raw = legacy(&public);
        let before = fs::read(&public).unwrap();
        let expected = read_history(&public).unwrap();
        assert_eq!(expected.len(), 1);
        assert_eq!(expected[0].schema_version, 1);
        assert_eq!(fs::read(&public).unwrap(), before);
        let digest = crate::hex(&Sha256::digest(format!("[{raw}]").as_bytes()));
        // Publication bytes produced by fbb5562, before the dependency upgrades.
        assert_eq!(
            digest,
            "5ba53588761a8a83f64bba4be6096e2e14a7d2e48165a859fb17833ba63d259f"
        );
        let db = Connection::open(&public).unwrap();
        db.execute_batch("CREATE TABLE astraeus_publication (digest TEXT NOT NULL)")
            .unwrap();
        db.execute("INSERT INTO astraeus_publication VALUES (?1)", [&digest])
            .unwrap();
        drop(db);
        fs::create_dir(private.parent().unwrap()).unwrap();
        fs::copy(&public, &private).unwrap();
        let session =
            UpdateSession::open_published(&private, &temp.0.join("update.lock"), &public).unwrap();
        assert_eq!(version(&session.db).unwrap(), 2);
        assert_eq!(session.records().unwrap(), expected);
        assert_eq!(records_digest(&session.db).unwrap(), digest);
        let published = Connection::open(&public).unwrap();
        assert_eq!(version(&published).unwrap(), 2);
        assert_eq!(records_digest(&published).unwrap(), digest);
        drop(published);
        drop(session);
    }

    #[test]
    fn unknown_record_and_database_versions_fail_without_rewriting_either_database() {
        for unknown_record in [true, false] {
            let temp = Directory::new();
            let path = temp.0.join("history.sqlite");
            legacy(&path);
            let db = Connection::open(&path).unwrap();
            if unknown_record {
                let mut invalid = record();
                invalid.schema_version = 99;
                db.execute(
                    "UPDATE transactions SET record=?1",
                    [serde_json::to_string(&invalid).unwrap()],
                )
                .unwrap();
            } else {
                db.pragma_update(None, "user_version", 99).unwrap();
            }
            drop(db);
            let before = fs::read(&path).unwrap();
            assert!(read_history(&path).is_err());
            assert!(UpdateSession::open(&path, &temp.0.join("lock")).is_err());
            assert_eq!(fs::read(&path).unwrap(), before);
        }
    }

    #[cfg(unix)]
    #[test]
    fn migration_rejects_linked_private_history_and_does_not_touch_its_target() {
        use std::os::unix::fs::symlink;
        let temp = Directory::new();
        let original = temp.0.join("original.sqlite");
        legacy(&original);
        let before = fs::read(&original).unwrap();
        let linked = temp.0.join("history.sqlite");
        symlink(&original, &linked).unwrap();
        assert!(UpdateSession::open(&linked, &temp.0.join("lock")).is_err());
        assert_eq!(fs::read(&original).unwrap(), before);
    }
}
