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

/// The OS releases this lock on process exit. Never unlink a held lock file.
pub struct UpdateSession {
    db: Connection,
    _lock: File,
    public: Option<PathBuf>,
}

fn records(db: &Connection) -> Result<Vec<TransactionRecord>> {
    // ponytail: scan the small history; add indexed summaries/pagination when history grows large.
    let mut statement = db
        .prepare("SELECT record FROM transactions ORDER BY id DESC")
        .map_err(|e| e.to_string())?;
    let rows = statement
        .query_map([], |r| r.get::<_, String>(0))
        .map_err(|e| e.to_string())?;
    rows.map(|row| {
        serde_json::from_str(&row.map_err(|e| e.to_string())?).map_err(|e| e.to_string())
    })
    .collect()
}

fn version(db: &Connection) -> Result<i64> {
    db.pragma_query_value(None, "user_version", |r| r.get(0))
        .map_err(|e| e.to_string())
}

pub fn read_history(path: &Path) -> Result<Vec<TransactionRecord>> {
    match path.try_exists() {
        Ok(false) => return Ok(vec![]),
        Err(e) => return Err(e.to_string()),
        _ => {}
    }
    let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|e| e.to_string())?;
    if version(&db)? != 1 {
        return Err("unsupported history schema".into());
    }
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
    if version(current)? != 1 || version(published)? != 1 {
        return Err("unsupported history schema".into());
    }
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
        if let Some(source) = public.as_ref() {
            if source.try_exists().map_err(|e| e.to_string())? {
                let exists = path.try_exists().map_err(|e| e.to_string())?;
                let legacy = Connection::open_with_flags(source, OpenFlags::SQLITE_OPEN_READ_WRITE)
                    .map_err(|e| e.to_string())?;
                if version(&legacy)? != 1 {
                    return Err("unsupported history schema".into());
                }
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
        db.execute_batch("PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL;")
            .map_err(|e| e.to_string())?;
        match version(&db)? {
            0 => db.execute_batch("BEGIN IMMEDIATE;
                CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, record TEXT NOT NULL);
                PRAGMA user_version=1;
                COMMIT;").map_err(|e| e.to_string())?,
            1 => {},
            _ => return Err("unsupported history schema".into()),
        }
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
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(true).truncate(false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        file.set_permissions(fs::Permissions::from_mode(0o600))?;
    }
    Ok(file)
}

fn records_digest(db: &Connection) -> Result<String> {
    Ok(format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&records(db)?).map_err(|e| e.to_string())?)
    ))
}

fn snapshot(
    db: &Connection,
    destination: &Path,
    temporary: PathBuf,
    publication: bool,
) -> Result<()> {
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
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o644))
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
