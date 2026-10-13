use super::Submission;
use distro_transactions::{
    management_store as store, read_history, Result, TransactionRecord, HISTORY_PATH,
};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

const ROOT: &str = "/run/astraeus";
const RECEIPTS: &str = "/var/log/astraeus/operations";
const RECEIPT_LIMIT: u64 = 16 * 1024;
const STARTUP_GRACE_SECONDS: u64 = 30;

pub fn valid_id(id: &str) -> bool {
    id.len() == 32
        && id
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn check_id(id: &str) -> Result<()> {
    if valid_id(id) {
        Ok(())
    } else {
        Err("operation ID must contain 32 lowercase hexadecimal characters".into())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
#[cfg(all(target_os = "linux", feature = "native-alpm"))]
struct Request {
    schema_version: u32,
    operation_id: String,
    initiating_uid: u32,
    submission: Submission,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ReceiptState {
    Queued,
    Running,
    Linked,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt {
    schema_version: u32,
    operation_id: String,
    boot_id: String,
    created_unix_seconds: u64,
    state: ReceiptState,
    transaction_id: Option<i64>,
    error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Operation {
    pub schema_version: u32,
    pub operation_id: String,
    pub state: String,
    pub transaction: Option<TransactionRecord>,
    pub error: Option<String>,
}

impl Operation {
    pub fn in_progress(&self) -> bool {
        matches!(
            self.state.as_str(),
            "queued"
                | "running"
                | "planned"
                | "preparing"
                | "downloaded"
                | "snapshot_pending"
                | "snapshot_created"
                | "applying"
                | "validating"
        )
    }
}

#[cfg(any(test, all(target_os = "linux", feature = "native-alpm")))]
fn start_worker(
    mut receipt: Receipt,
    mut persist: impl FnMut(&Receipt) -> Result<()>,
    start: impl FnOnce(&str) -> Result<()>,
) -> Result<Operation> {
    persist(&receipt)?;
    if let Err(error) = start(&receipt.operation_id) {
        receipt.state = ReceiptState::Failed;
        receipt.error = Some(error.clone());
        persist(&receipt)?;
        return Err(error);
    }
    Ok(Operation {
        schema_version: 1,
        operation_id: receipt.operation_id,
        state: "queued".into(),
        transaction: None,
        error: None,
    })
}

fn receipt_path(id: &str) -> PathBuf {
    Path::new(RECEIPTS).join(format!("{id}.json"))
}
#[cfg(all(target_os = "linux", feature = "native-alpm"))]
fn request_path(id: &str, started: bool) -> PathBuf {
    Path::new(ROOT).join("requests").join(format!(
        "{id}.{}.json",
        if started { "started" } else { "queued" }
    ))
}

fn from_record(record: TransactionRecord) -> Result<Operation> {
    let id = record
        .operation_id
        .clone()
        .ok_or("transaction has no operation ID")?;
    check_id(&id)?;
    let state = serde_json::to_value(record.state)
        .map_err(|error| error.to_string())?
        .as_str()
        .ok_or("invalid transaction state")?
        .to_string();
    Ok(Operation {
        schema_version: 1,
        operation_id: id,
        state,
        error: record
            .failure
            .as_ref()
            .map(|failure| failure.message.clone()),
        transaction: Some(record),
    })
}

fn matching_record(records: &[TransactionRecord], id: &str) -> Result<Option<TransactionRecord>> {
    let matching: Vec<_> = records
        .iter()
        .filter(|record| record.operation_id.as_deref() == Some(id))
        .collect();
    match matching.as_slice() {
        [] => Ok(None),
        [record] => Ok(Some((*record).clone())),
        _ => Err("operation ID is associated with multiple transactions".into()),
    }
}

fn read_receipt(id: &str) -> Result<Receipt> {
    check_id(id)?;
    let receipt: Receipt =
        serde_json::from_str(&store::read_text(&receipt_path(id), RECEIPT_LIMIT)?)
            .map_err(|error| error.to_string())?;
    if receipt.schema_version != 1
        || receipt.operation_id != id
        || receipt.boot_id.len() != 36
        || receipt.transaction_id.is_some_and(|id| id <= 0)
    {
        return Err("invalid operation receipt".into());
    }
    Ok(receipt)
}

pub fn operation(id: &str) -> Result<Operation> {
    check_id(id)?;
    let records = read_history(Path::new(HISTORY_PATH))?;
    if let Some(record) = matching_record(&records, id)? {
        return from_record(record);
    }
    let receipt = read_receipt(id)?;
    let boot = distro_transactions::integration::boot_id()?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_secs();
    let unit = if queued_past_startup_grace(&receipt, &boot, now) {
        worker_unit(id).ok()
    } else {
        None
    };
    receipt_operation(project_orphaned_queue(receipt, &boot, now, unit), &boot)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum WorkerUnit {
    Inactive,
    #[cfg(any(test, all(target_os = "linux", feature = "native-alpm")))]
    Busy,
}

fn queued_past_startup_grace(receipt: &Receipt, boot: &str, now: u64) -> bool {
    matches!(receipt.state, ReceiptState::Queued)
        && receipt.transaction_id.is_none()
        && receipt.boot_id == boot
        && now
            .checked_sub(receipt.created_unix_seconds)
            .is_some_and(|elapsed| elapsed >= STARTUP_GRACE_SECONDS)
}

fn project_orphaned_queue(
    mut receipt: Receipt,
    boot: &str,
    now: u64,
    unit: Option<WorkerUnit>,
) -> Receipt {
    if queued_past_startup_grace(&receipt, boot, now) && unit == Some(WorkerUnit::Inactive) {
        receipt.state = ReceiptState::Failed;
        receipt.error = Some("Submission stopped before the worker started. The request will not be replayed; review the current state before submitting again.".into());
    }
    receipt
}

#[cfg(any(test, all(target_os = "linux", feature = "native-alpm")))]
fn parse_worker_unit(text: &str) -> Result<WorkerUnit> {
    let mut values = std::collections::BTreeMap::new();
    for line in text.lines() {
        let (key, value) = line.split_once('=').ok_or("invalid worker unit response")?;
        if !["LoadState", "ActiveState", "Job"].contains(&key)
            || values.insert(key, value).is_some()
        {
            return Err("unexpected worker unit response".into());
        }
    }
    let [Some(load), Some(active), Some(job)] = [
        values.get("LoadState"),
        values.get("ActiveState"),
        values.get("Job"),
    ] else {
        return Err("incomplete worker unit response".into());
    };
    if ["loaded", "not-found"].contains(load) && *active == "inactive" && ["", "0"].contains(job) {
        Ok(WorkerUnit::Inactive)
    } else {
        // Unknown states never authorize classifying a submission as abandoned.
        Ok(WorkerUnit::Busy)
    }
}

#[cfg(all(target_os = "linux", feature = "native-alpm"))]
fn worker_unit(id: &str) -> Result<WorkerUnit> {
    use std::{
        io::Read,
        os::unix::process::CommandExt,
        process::{Command, Stdio},
        sync::mpsc,
        thread,
        time::{Duration, Instant},
    };
    check_id(id)?;
    let mut child = Command::new("/usr/bin/systemctl")
        .args([
            "show",
            "--no-pager",
            "--all",
            "--property=LoadState,ActiveState,Job",
            &format!("astraeus-apply@{id}.service"),
        ])
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("LC_ALL", "C")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .process_group(0)
        .spawn()
        .map_err(|error| error.to_string())?;
    let reader = child
        .stdout
        .take()
        .ok_or("worker unit stdout unavailable")?;
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let mut bytes = vec![];
        let result = reader
            .take(16 * 1024 + 1)
            .read_to_end(&mut bytes)
            .map(|_| bytes);
        let _ = sender.send(result);
    });
    let deadline = Instant::now() + Duration::from_secs(3);
    let result = (|| -> Result<WorkerUnit> {
        let bytes = receiver
            .recv_timeout(deadline.saturating_duration_since(Instant::now()))
            .map_err(|_| "worker unit query timed out")?
            .map_err(|error| error.to_string())?;
        if bytes.len() > 16 * 1024 {
            return Err("worker unit response exceeded its size limit".into());
        }
        loop {
            if let Some(status) = child.try_wait().map_err(|error| error.to_string())? {
                if !status.success() {
                    return Err("worker unit query failed".into());
                }
                break;
            }
            if Instant::now() >= deadline {
                return Err("worker unit query timed out".into());
            }
            thread::sleep(Duration::from_millis(10));
        }
        parse_worker_unit(std::str::from_utf8(&bytes).map_err(|error| error.to_string())?)
    })();
    if result.is_err() && child.try_wait().is_ok_and(|status| status.is_none()) {
        // SAFETY: only the isolated read-only query's process group is stopped.
        unsafe { libc::kill(-(child.id() as i32), libc::SIGKILL) };
        let _ = child.kill();
        let _ = child.wait();
    }
    result
}

#[cfg(not(all(target_os = "linux", feature = "native-alpm")))]
fn worker_unit(_: &str) -> Result<WorkerUnit> {
    Err(super::NATIVE_REQUIRED.into())
}

fn receipt_operation(receipt: Receipt, current_boot: &str) -> Result<Operation> {
    if matches!(receipt.state, ReceiptState::Queued | ReceiptState::Running)
        && receipt.boot_id != current_boot
    {
        return Ok(Operation{schema_version:1,operation_id:receipt.operation_id,state:"failed".into(),transaction:None,error:Some("The system restarted before this operation completed. The request will not be replayed.".into())});
    }
    let state = match receipt.state {
        ReceiptState::Queued => "queued",
        ReceiptState::Running => "running",
        ReceiptState::Failed => "failed",
        ReceiptState::Linked => {
            return Err(
                "operation references a missing transaction; preserve history for recovery".into(),
            )
        }
    };
    Ok(Operation {
        schema_version: 1,
        operation_id: receipt.operation_id,
        state: state.into(),
        transaction: None,
        error: receipt.error,
    })
}

pub fn active() -> Result<Option<Operation>> {
    let path = Path::new(ROOT).join("active");
    if path.try_exists().map_err(|error| error.to_string())? {
        let id = store::read_text(&path, 128)?;
        return operation(id.trim()).map(Some);
    }
    let records = read_history(Path::new(HISTORY_PATH))?;
    if let Some(record) = records
        .into_iter()
        .find(|record| record.operation_id.is_some() && !record.state.terminal())
    {
        return from_record(record).map(Some);
    }
    if !Path::new(RECEIPTS)
        .try_exists()
        .map_err(|error| error.to_string())?
    {
        return Ok(None);
    }
    store::trusted_directory(Path::new(RECEIPTS))?;
    let mut latest: Option<Receipt> = None;
    for (index, entry) in fs::read_dir(RECEIPTS)
        .map_err(|error| error.to_string())?
        .enumerate()
    {
        if index >= 4096 {
            return Err("operation receipt inventory exceeds the inspection limit".into());
        }
        let entry = entry.map_err(|error| error.to_string())?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| "invalid receipt filename")?;
        let Some(id) = name.strip_suffix(".json") else {
            continue;
        };
        let receipt = read_receipt(id)?;
        if latest
            .as_ref()
            .is_none_or(|previous| receipt.created_unix_seconds > previous.created_unix_seconds)
        {
            latest = Some(receipt);
        }
    }
    latest
        .map(|receipt| operation(&receipt.operation_id))
        .transpose()
}

#[cfg(all(target_os = "linux", feature = "native-alpm"))]
fn submission_lock() -> Result<fs::File> {
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
    store::ensure_directory(Path::new(ROOT), 0o755)?;
    store::ensure_directory(&Path::new(ROOT).join("requests"), 0o700)?;
    if fs::metadata(Path::new(ROOT).join("requests"))
        .map_err(|error| error.to_string())?
        .mode()
        & 0o077
        != 0
    {
        return Err("request staging directory must be root-private".into());
    }
    store::ensure_directory(Path::new(RECEIPTS), 0o755)?;
    let file = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(Path::new(ROOT).join("submission.lock"))
        .map_err(|error| error.to_string())?;
    let meta = file.metadata().map_err(|error| error.to_string())?;
    if !meta.is_file() || meta.uid() != 0 || meta.mode() & 0o077 != 0 || meta.nlink() != 1 {
        return Err("untrusted submission lock".into());
    }
    file.lock().map_err(|error| error.to_string())?;
    Ok(file)
}

#[cfg(all(target_os = "linux", feature = "native-alpm"))]
fn write_receipt(receipt: &Receipt) -> Result<()> {
    let data = serde_json::to_vec_pretty(receipt).map_err(|error| error.to_string())?;
    store::atomic_write(&receipt_path(&receipt.operation_id), &data, 0o644)
}

#[cfg(all(target_os = "linux", feature = "native-alpm"))]
pub fn submit(submission: Submission) -> Result<Operation> {
    use std::{
        io::{Read, Write},
        os::unix::fs::OpenOptionsExt,
        process::Command,
    };
    distro_transactions::pacman::require_root()?;
    submission.validate()?;
    if super::live() {
        return Err("live sessions cannot apply system changes".into());
    }
    distro_snapshots::Manager::online(distro_snapshots::Native)
        .plan_create()
        .map_err(|error| format!("installed system required: {error}"))?;
    let mut guard = Some(submission_lock()?);
    if active()?.is_some_and(|operation| operation.in_progress()) {
        return Err("another system operation is queued or running".into());
    }
    if read_history(Path::new(HISTORY_PATH))?
        .iter()
        .any(|record| !record.state.terminal())
    {
        return Err("previous transaction requires boot confirmation or recovery".into());
    }
    let mut bytes = [0u8; 16];
    fs::File::open("/dev/urandom")
        .and_then(|mut source| source.read_exact(&mut bytes))
        .map_err(|error| error.to_string())?;
    let id = bytes
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    if receipt_path(&id).exists()
        || request_path(&id, true).exists()
        || matching_record(&read_history(Path::new(HISTORY_PATH))?, &id)?.is_some()
    {
        return Err("operation identifier collision".into());
    }
    let initiating_uid = std::env::var("PKEXEC_UID")
        .ok()
        .map(|value| value.parse::<u32>())
        .transpose()
        .map_err(|_| "invalid authenticated user ID")?
        .unwrap_or(0);
    let request = Request {
        schema_version: 1,
        operation_id: id.clone(),
        initiating_uid,
        submission,
    };
    let payload = serde_json::to_vec(&request).map_err(|error| error.to_string())?;
    let mut output = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(request_path(&id, false))
        .map_err(|error| error.to_string())?;
    output
        .write_all(&payload)
        .and_then(|_| output.sync_all())
        .map_err(|error| error.to_string())?;
    drop(output);
    fs::File::open(Path::new(ROOT).join("requests"))
        .and_then(|directory| directory.sync_all())
        .map_err(|error| error.to_string())?;
    let receipt = Receipt {
        schema_version: 1,
        operation_id: id.clone(),
        boot_id: distro_transactions::integration::boot_id()?,
        created_unix_seconds: std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_secs(),
        state: ReceiptState::Queued,
        transaction_id: None,
        error: None,
    };
    start_worker(
        receipt,
        |receipt| {
            let _failure_guard = if matches!(receipt.state, ReceiptState::Failed) {
                Some(submission_lock()?)
            } else {
                None
            };
            if matches!(receipt.state, ReceiptState::Failed)
                && !matches!(
                    read_receipt(&receipt.operation_id)?.state,
                    ReceiptState::Queued
                )
            {
                return Ok(());
            }
            write_receipt(receipt)?;
            if matches!(receipt.state, ReceiptState::Queued) {
                store::atomic_write(
                    &Path::new(ROOT).join("active"),
                    receipt.operation_id.as_bytes(),
                    0o644,
                )?;
                // The unit and its exit finalizer must not wait on the submitting process.
                drop(guard.take());
            }
            Ok(())
        },
        |id| {
            let output = Command::new("/usr/bin/systemctl")
                .args(["start", &format!("astraeus-apply@{id}.service")])
                .env_clear()
                .env("PATH", "/usr/bin:/bin")
                .env("LC_ALL", "C")
                .output()
                .map_err(|error| error.to_string())?;
            if output.status.success() {
                Ok(())
            } else {
                Err(format!(
                    "worker did not start: {}",
                    String::from_utf8_lossy(&output.stderr)
                        .chars()
                        .take(2048)
                        .collect::<String>()
                ))
            }
        },
    )
}

#[cfg(not(all(target_os = "linux", feature = "native-alpm")))]
pub fn submit(submission: Submission) -> Result<Operation> {
    submission.validate()?;
    Err(super::NATIVE_REQUIRED.into())
}

pub fn submit_reviewed(submission: Submission) -> Result<Operation> {
    submission.validate()?;
    #[cfg(all(target_os = "linux", feature = "native-alpm"))]
    {
        use std::{
            io::Write,
            process::{Command, Stdio},
        };
        // SAFETY: geteuid takes no pointers and does not mutate memory.
        if unsafe { libc::geteuid() } == 0 {
            return submit(submission);
        }
        let payload = serde_json::to_vec(&submission).map_err(|error| error.to_string())?;
        let mut child = Command::new("/usr/bin/pkexec")
            .args([
                "--disable-internal-agent",
                "/usr/bin/distroctl",
                "system",
                "submit",
                "--json",
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| error.to_string())?;
        child
            .stdin
            .take()
            .ok_or("authentication input unavailable")?
            .write_all(&payload)
            .map_err(|error| error.to_string())?;
        let output = child
            .wait_with_output()
            .map_err(|error| error.to_string())?;
        if !output.status.success() {
            return Err(format!("administrator authentication or submission failed (exit {:?}); inspect system status before retrying",output.status.code()));
        }
        if output.stdout.len() > RECEIPT_LIMIT as usize {
            return Err("oversized submission receipt".into());
        }
        let operation: Operation =
            serde_json::from_slice(&output.stdout).map_err(|error| error.to_string())?;
        check_id(&operation.operation_id)?;
        if operation.schema_version != 1 || operation.state != "queued" {
            return Err("invalid submission acknowledgement".into());
        }
        Ok(operation)
    }
    #[cfg(not(all(target_os = "linux", feature = "native-alpm")))]
    submit(submission)
}

#[cfg(all(target_os = "linux", feature = "native-alpm"))]
fn claim(id: &str) -> Result<Request> {
    check_id(id)?;
    let _guard = submission_lock()?;
    let active = store::read_text(&Path::new(ROOT).join("active"), 128)?;
    if active != id {
        return Err("operation is not the current submitted request".into());
    }
    let mut receipt = read_receipt(id)?;
    if !matches!(receipt.state, ReceiptState::Queued)
        || receipt.transaction_id.is_some()
        || request_path(id, true).exists()
        || receipt.boot_id != distro_transactions::integration::boot_id()?
    {
        return Err("operation has already started or is terminal; replay refused".into());
    }
    let request: Request = serde_json::from_str(&store::read_text(
        &request_path(id, false),
        (distro_config::MAX_SYSTEM_CONFIG_BYTES + 4096) as u64,
    )?)
    .map_err(|error| error.to_string())?;
    if request.schema_version != 1 || request.operation_id != id {
        return Err("request identity mismatch".into());
    }
    request.submission.validate()?;
    fs::rename(request_path(id, false), request_path(id, true))
        .map_err(|error| error.to_string())?;
    fs::File::open(Path::new(ROOT).join("requests"))
        .and_then(|directory| directory.sync_all())
        .map_err(|error| error.to_string())?;
    receipt.state = ReceiptState::Running;
    write_receipt(&receipt)?;
    Ok(request)
}

#[cfg(all(target_os = "linux", feature = "native-alpm"))]
fn execute_request(request: &Request) -> Result<TransactionRecord> {
    use distro_transactions::{
        execute, integration,
        native_alpm::NativePackages,
        pacman::{NativeRunner, SystemBoot},
        PackageBackend,
    };
    let mut session = crate::updates::session()?;
    session.ensure_ready()?;
    if matching_record(&session.records()?, &request.operation_id)?.is_some() {
        return Err("operation already exists in history; replay refused".into());
    }
    let mut snapshots = integration::BtrfsSnapshots::new(distro_snapshots::Manager::online(
        distro_snapshots::Native,
    ))?;
    let mut packages = NativePackages::new(request.submission.config.clone())?;
    packages.operation = Some(request.operation_id.clone());
    let plan = packages.resolve()?;
    plan.validate()?;
    if plan.fingerprint() != request.submission.expected_plan {
        return Err(
            "reviewed plan is stale; review the current system state before applying".into(),
        );
    }
    execute(
        &mut session,
        plan,
        &mut packages,
        &mut snapshots,
        &mut SystemBoot {
            runner: NativeRunner,
        },
        &mut integration::system_health(),
        || false,
    )
}

#[cfg(all(target_os = "linux", feature = "native-alpm"))]
pub fn worker(id: &str) -> Result<()> {
    distro_transactions::pacman::require_root()?;
    check_id(id)?;
    if super::live() {
        return Err("live sessions cannot apply system changes".into());
    }
    let request = claim(id)?;
    let outcome = execute_request(&request);
    let mut receipt = read_receipt(id)?;
    match outcome {
        Ok(record) => {
            receipt.state = ReceiptState::Linked;
            receipt.transaction_id = Some(record.id);
            receipt.error = record
                .failure
                .as_ref()
                .map(|failure| failure.message.clone());
            write_receipt(&receipt)?;
            Ok(())
        }
        Err(error) => {
            receipt.state = ReceiptState::Failed;
            receipt.error = Some(error.chars().take(4096).collect());
            write_receipt(&receipt)?;
            // The receipt carries handled rejections; they must not poison system unit health.
            Ok(())
        }
    }
}

#[cfg(not(all(target_os = "linux", feature = "native-alpm")))]
pub fn worker(id: &str) -> Result<()> {
    check_id(id)?;
    Err(super::NATIVE_REQUIRED.into())
}

#[cfg(all(target_os = "linux", feature = "native-alpm"))]
pub fn worker_finished(id: &str) -> Result<()> {
    distro_transactions::pacman::require_root()?;
    check_id(id)?;
    let mut receipt = read_receipt(id)?;
    let mut session = crate::updates::session()?;
    if let Some(record) = matching_record(&session.records()?, id)? {
        if !record.state.terminal()
            && !matches!(
                record.state,
                distro_transactions::TransactionState::AwaitingBoot
                    | distro_transactions::TransactionState::RollbackRequired
            )
        {
            session.recover_interrupted()?;
        }
        let final_record = matching_record(&session.records()?, id)?
            .ok_or("operation disappeared from history")?;
        receipt.state = ReceiptState::Linked;
        receipt.transaction_id = Some(final_record.id);
        receipt.error = final_record.failure.map(|failure| failure.message);
    } else if !matches!(receipt.state, ReceiptState::Failed) {
        receipt.state = ReceiptState::Failed;
        receipt.error=Some("Worker stopped before creating a durable transaction. The request will not be replayed.".into());
    }
    write_receipt(&receipt)
}

#[cfg(not(all(target_os = "linux", feature = "native-alpm")))]
pub fn worker_finished(id: &str) -> Result<()> {
    check_id(id)?;
    Err(super::NATIVE_REQUIRED.into())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn identifiers_cannot_escape_the_fixed_request_directory() {
        assert!(valid_id(&"a".repeat(32)));
        for value in [
            "../requests",
            "--help",
            "0000",
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "0000000000000000000000000000000/",
        ] {
            assert!(!valid_id(value));
            assert!(operation(value).is_err());
        }
    }
    #[test]
    fn receipts_distinguish_mutating_work_and_boot_wait() {
        let mut operation = Operation {
            schema_version: 1,
            operation_id: "a".repeat(32),
            state: "applying".into(),
            transaction: None,
            error: None,
        };
        assert!(operation.in_progress());
        operation.state = "awaiting_boot".into();
        assert!(!operation.in_progress());
        let corrupt = serde_json::json!({"schema_version":1,"operation_id":"a".repeat(32),"state":"succeeded","transaction_id":null,"error":null});
        assert!(serde_json::from_value::<Receipt>(corrupt).is_err());
    }

    #[test]
    fn worker_start_failure_is_persisted_before_submission_returns() {
        let receipt = Receipt {
            schema_version: 1,
            operation_id: "a".repeat(32),
            boot_id: "b".repeat(36),
            created_unix_seconds: 1,
            state: ReceiptState::Queued,
            transaction_id: None,
            error: None,
        };
        let persisted = std::cell::RefCell::new(Vec::<Receipt>::new());
        let result = start_worker(
            receipt.clone(),
            |value| {
                persisted.borrow_mut().push(value.clone());
                Ok(())
            },
            |_| {
                assert!(matches!(persisted.borrow()[0].state, ReceiptState::Queued));
                Err("service start failed".into())
            },
        );
        assert!(result.is_err());
        let last = persisted.borrow().last().unwrap().clone();
        assert!(matches!(last.state, ReceiptState::Failed));
        assert_eq!(last.error.as_deref(), Some("service start failed"));
        assert!(start_worker(
            receipt,
            |_| Err("receipt could not be persisted".into()),
            |_| panic!("must not start without a receipt")
        )
        .is_err());
    }

    #[test]
    fn rebooted_requests_fail_without_replay_and_terminal_receipts_survive() {
        let mut receipt = Receipt {
            schema_version: 1,
            operation_id: "a".repeat(32),
            boot_id: "before".into(),
            created_unix_seconds: 1,
            state: ReceiptState::Queued,
            transaction_id: None,
            error: None,
        };
        assert_eq!(
            receipt_operation(receipt.clone(), "before").unwrap().state,
            "queued"
        );
        let interrupted = receipt_operation(receipt.clone(), "after").unwrap();
        assert_eq!(interrupted.state, "failed");
        assert!(interrupted.error.unwrap().contains("will not be replayed"));
        receipt.state = ReceiptState::Failed;
        receipt.error = Some("original refusal".into());
        assert_eq!(
            receipt_operation(receipt, "after")
                .unwrap()
                .error
                .as_deref(),
            Some("original refusal")
        );
    }

    #[test]
    fn only_old_queued_receipts_with_confirmed_idle_units_are_orphans() {
        let receipt = Receipt {
            schema_version: 1,
            operation_id: "a".repeat(32),
            boot_id: "current-boot".into(),
            created_unix_seconds: 100,
            state: ReceiptState::Queued,
            transaction_id: None,
            error: None,
        };
        for now in [99, 100, 129] {
            let fresh = project_orphaned_queue(
                receipt.clone(),
                "current-boot",
                now,
                Some(WorkerUnit::Inactive),
            );
            assert!(matches!(fresh.state, ReceiptState::Queued));
        }
        for unit in [None, Some(WorkerUnit::Busy)] {
            let uncertain = project_orphaned_queue(receipt.clone(), "current-boot", 500, unit);
            assert!(matches!(uncertain.state, ReceiptState::Queued));
        }
        let orphan = project_orphaned_queue(
            receipt.clone(),
            "current-boot",
            130,
            Some(WorkerUnit::Inactive),
        );
        assert!(matches!(orphan.state, ReceiptState::Failed));
        let operation = receipt_operation(orphan, "current-boot").unwrap();
        assert!(!operation.in_progress());
        assert!(operation.error.unwrap().contains("will not be replayed"));
        for state in [
            ReceiptState::Running,
            ReceiptState::Linked,
            ReceiptState::Failed,
        ] {
            let mut other = receipt.clone();
            other.state = state.clone();
            let projected =
                project_orphaned_queue(other, "current-boot", 500, Some(WorkerUnit::Inactive));
            assert_eq!(
                serde_json::to_value(projected.state).unwrap(),
                serde_json::to_value(state).unwrap()
            );
        }
        let mut linked = receipt.clone();
        linked.transaction_id = Some(1);
        assert!(matches!(
            project_orphaned_queue(linked, "current-boot", 500, Some(WorkerUnit::Inactive)).state,
            ReceiptState::Queued
        ));
        assert!(matches!(
            project_orphaned_queue(receipt, "another-boot", 500, Some(WorkerUnit::Inactive)).state,
            ReceiptState::Queued
        ));
    }

    #[test]
    fn unit_projection_requires_complete_inactive_state_without_a_start_job() {
        for load in ["loaded", "not-found"] {
            for job in ["", "0"] {
                assert_eq!(
                    parse_worker_unit(&format!(
                        "LoadState={load}\nActiveState=inactive\nJob={job}\n"
                    ))
                    .unwrap(),
                    WorkerUnit::Inactive
                );
            }
        }
        for properties in [
            "LoadState=loaded\nActiveState=activating\nJob=\n",
            "LoadState=loaded\nActiveState=active\nJob=\n",
            "LoadState=loaded\nActiveState=deactivating\nJob=\n",
            "LoadState=loaded\nActiveState=failed\nJob=\n",
            "LoadState=loaded\nActiveState=inactive\nJob=127 start\n",
            "LoadState=unknown\nActiveState=inactive\nJob=\n",
        ] {
            assert_eq!(parse_worker_unit(properties).unwrap(), WorkerUnit::Busy);
        }
        for properties in [
            "",
            "LoadState=not-found\nActiveState=inactive\n",
            "LoadState=loaded\nActiveState=inactive\nJob=\nJob=1\n",
            "failed to connect to system bus",
        ] {
            assert!(parse_worker_unit(properties).is_err());
        }
    }
}
