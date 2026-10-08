use crate::{Failure, Result, TransactionRecord, TransactionState};
use rusqlite::{params, Connection, OpenFlags};
use std::{
    fs::{File, OpenOptions},
    path::Path,
};

pub const HISTORY_PATH: &str = "/var/log/astraeus/transactions.sqlite";
pub const LOCK_PATH: &str = "/run/astraeus-update.lock";

/// The OS releases this lock on process exit. Never unlink a held lock file.
pub struct UpdateSession {
    db: Connection,
    _lock: File,
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

impl UpdateSession {
    /// Callers supply trusted paths. The lock must be shared by every system update.
    pub fn open(path: &Path, lock_path: &Path) -> Result<Self> {
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(lock_path)
            .map_err(|e| format!("update lock: {e}"))?;
        lock.try_lock()
            .map_err(|e| format!("another Astraeus update holds the lock: {e}"))?;
        let db = Connection::open(path).map_err(|e| e.to_string())?;
        // DELETE journals keep read-only history independent of writable WAL/shm files.
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
        Ok(Self { db, _lock: lock })
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
        Ok(())
    }

    pub(crate) fn save(&mut self, record: &TransactionRecord) -> Result<()> {
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
        self.save(&saved)?;
        *record = saved;
        Ok(())
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
