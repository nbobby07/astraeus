use super::{collect, event, store::Store, Measurement, Report, Result, Workload};
use sha2::{Digest, Sha256};
#[cfg(target_os = "linux")]
use std::io::Write;
use std::{
    fs,
    io::Read,
    path::Path,
    sync::atomic::{AtomicBool, Ordering},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
static STOP: AtomicBool = AtomicBool::new(false);
const MIB: usize = 1024 * 1024;
const GIB: u64 = 1024 * 1024 * 1024;

pub(super) fn blockers() -> Vec<String> {
    let mut b = conflicts();
    if !cfg!(target_os = "linux") {
        b.push("Measurements require Linux".into());
    }
    if crate::system::live() {
        b.push(
            "Baselines require an installed session; passive observations remain available".into(),
        );
    }
    match distro_transactions::management_store::read_state(Path::new("/")) {
        Ok(Some(_)) => {}
        Ok(None) => b.push("An installed managed Astraeus system is required".into()),
        Err(e) => b.push(format!("Management state requires inspection: {e}")),
    }
    b
}
fn conflicts() -> Vec<String> {
    let mut b = vec![];
    if Path::new("/var/lib/pacman/db.lck").exists() {
        b.push("A native package transaction is active".into());
    }
    match distro_transactions::read_history(Path::new(distro_transactions::HISTORY_PATH)) {
        Ok(h) if h.iter().any(|r| !r.state.terminal()) => {
            b.push("A transaction requires completion, reboot or recovery".into())
        }
        Err(e) => b.push(format!("Transaction history unavailable: {e}")),
        _ => {}
    }
    match crate::system::performance_operation_active() {
        Ok(true) => b.push("A system operation is queued or running".into()),
        Err(e) => b.push(format!("System operation unavailable: {e}")),
        _ => {}
    }
    b
}
#[cfg(target_os = "linux")]
extern "C" fn stop(_: libc::c_int) {
    STOP.store(true, Ordering::Relaxed);
}
#[cfg(target_os = "linux")]
struct Signals(Vec<(libc::c_int, libc::sighandler_t)>);
#[cfg(target_os = "linux")]
impl Signals {
    fn install() -> Result<Self> {
        STOP.store(false, Ordering::Relaxed);
        let mut guard = Self(vec![]);
        for signal in [libc::SIGINT, libc::SIGTERM, libc::SIGHUP] {
            let old = unsafe { libc::signal(signal, stop as *const () as libc::sighandler_t) };
            if old == libc::SIG_ERR {
                return Err("cannot install measurement stop handler".into());
            }
            guard.0.push((signal, old));
        }
        let parent = unsafe { libc::getppid() };
        if unsafe { libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) } != 0 {
            return Err("cannot bind measurement lifetime to caller".into());
        }
        if unsafe { libc::getppid() } != parent {
            STOP.store(true, Ordering::Relaxed);
        }
        Ok(guard)
    }
}
#[cfg(target_os = "linux")]
impl Drop for Signals {
    fn drop(&mut self) {
        unsafe {
            libc::prctl(libc::PR_SET_PDEATHSIG, 0);
        }
        for (n, h) in &self.0 {
            unsafe {
                libc::signal(*n, *h);
            }
        }
    }
}

struct Run<'a> {
    report: &'a mut Report,
    started: Instant,
    previous: Option<collect::Counters>,
    last_sample: Option<Instant>,
    json: bool,
}
impl Run<'_> {
    fn tick(&mut self) -> Result<()> {
        if STOP.load(Ordering::Relaxed) {
            return Err("cancelled by caller".into());
        }
        if self.started.elapsed()
            > Duration::from_secs(
                self.report.requested_seconds + if self.report.kind == "record" { 2 } else { 0 },
            )
        {
            return Err("measurement execution budget exceeded".into());
        }
        if self
            .last_sample
            .is_none_or(|t| t.elapsed() >= Duration::from_secs(1))
        {
            let (s, c) = collect::sample(
                Path::new("/"),
                self.started.elapsed().as_secs_f64(),
                self.previous.as_ref(),
            );
            if self.report.kind == "baseline" {
                let b = conflicts();
                if !b.is_empty() {
                    return Err(b.join("; "));
                }
                if s.memory_available_bytes.is_none_or(|n| n < GIB) {
                    return Err("available memory fell below 1 GiB or became unavailable".into());
                }
                if s.temperatures.iter().any(|v| {
                    v.critical_celsius
                        .is_some_and(|limit| v.celsius >= limit - 5.0)
                }) {
                    return Err("reported temperature is within 5 C of its critical limit".into());
                }
            }
            s.validate()?;
            event(
                "sample",
                serde_json::to_value(&s).map_err(|e| e.to_string())?,
                self.json,
            )?;
            let stride = (self.report.requested_seconds / 60).max(1) as f64;
            if self
                .report
                .samples
                .last()
                .is_none_or(|previous| s.elapsed_seconds - previous.elapsed_seconds >= stride)
            {
                self.report.samples.push(s);
            }
            self.previous = Some(c);
            self.last_sample = Some(Instant::now());
        }
        Ok(())
    }
    fn phase(&self, name: &str) -> Result<()> {
        event("phase", serde_json::json!({"name":name}), self.json)
    }
    fn wait(&mut self, seconds: u64) -> Result<()> {
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(seconds) {
            self.tick()?;
            std::thread::sleep(Duration::from_millis(50));
        }
        Ok(())
    }
}
pub(super) fn definitions(threads: usize) -> Vec<Workload> {
    [
        ("sha256", threads.clamp(1, 4), 4 * MIB),
        ("memory-copy", 1, 128 * MIB),
        ("scratch-sync-read", 1, 128 * MIB),
    ]
    .into_iter()
    .map(|(name, threads, bytes)| Workload {
        name: name.into(),
        version: 1,
        threads,
        bytes: bytes as u64,
        repetition_seconds: 10,
        repetitions: 3,
    })
    .collect()
}
fn cpu(run: &mut Run<'_>, w: &Workload) -> Result<f64> {
    let started = Instant::now();
    std::thread::scope(|scope| {
        let threads: Vec<_> = (0..w.threads)
            .map(|_| {
                scope.spawn(|| {
                    let data = vec![0x5au8; w.bytes as usize / w.threads];
                    let expected = Sha256::digest(&data);
                    let mut bytes = 0u64;
                    while started.elapsed() < Duration::from_secs(w.repetition_seconds)
                        && !STOP.load(Ordering::Relaxed)
                    {
                        let actual =
                            std::hint::black_box(Sha256::digest(std::hint::black_box(&data)));
                        if actual != expected {
                            return Err("CPU hash verification failed".to_owned());
                        }
                        bytes += data.len() as u64;
                    }
                    Ok(bytes)
                })
            })
            .collect();
        let mut failure = None;
        while threads.iter().any(|t| !t.is_finished()) {
            if let Err(e) = run.tick() {
                failure = Some(e);
                STOP.store(true, Ordering::Relaxed);
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        let bytes = threads.into_iter().try_fold(0u64, |sum, t| {
            t.join()
                .map_err(|_| "CPU workload thread failed".to_owned())?
                .map(|n| sum + n)
        })?;
        if let Some(e) = failure {
            return Err(e);
        }
        Ok(bytes as f64 / MIB as f64 / started.elapsed().as_secs_f64())
    })
}
fn memory(run: &mut Run<'_>, w: &Workload) -> Result<f64> {
    let size = w.bytes as usize / 2;
    let mut from = Vec::new();
    let mut to = Vec::new();
    from.try_reserve_exact(size).map_err(|e| e.to_string())?;
    to.try_reserve_exact(size).map_err(|e| e.to_string())?;
    from.resize(size, 0x5au8);
    to.resize(size, 0u8);
    let start = Instant::now();
    let mut bytes = 0u64;
    while start.elapsed() < Duration::from_secs(w.repetition_seconds) {
        run.tick()?;
        std::hint::black_box(&mut to).copy_from_slice(std::hint::black_box(&from));
        std::hint::black_box(&to);
        bytes += size as u64;
    }
    let checksum: u64 = to.iter().map(|v| u64::from(*v)).sum();
    if checksum != size as u64 * 0x5a {
        return Err("memory checksum mismatch".into());
    }
    Ok(bytes as f64 / MIB as f64 / start.elapsed().as_secs_f64())
}
#[cfg(target_os = "linux")]
fn scratch(run: &mut Run<'_>, path: &Path, w: &Workload) -> Result<f64> {
    let start = Instant::now();
    let mut f = scratch_file(path.parent().ok_or("scratch directory missing")?)?;
    let result: Result<f64> = (|| {
        let mut buffer = vec![0x5au8; MIB];
        let mut hash = Sha256::new();
        for _ in 0..w.bytes / MIB as u64 {
            run.tick()?;
            f.write_all(&buffer).map_err(|e| e.to_string())?;
            hash.update(&buffer);
        }
        f.sync_all().map_err(|e| e.to_string())?;
        use std::io::{Seek, SeekFrom};
        f.seek(SeekFrom::Start(0)).map_err(|e| e.to_string())?;
        let mut read_hash = Sha256::new();
        for _ in 0..w.bytes / MIB as u64 {
            run.tick()?;
            f.read_exact(&mut buffer).map_err(|e| e.to_string())?;
            read_hash.update(&buffer);
        }
        if hash.finalize() != read_hash.finalize() {
            return Err("scratch readback checksum mismatch".into());
        }
        Ok(w.bytes as f64 * 2.0 / MIB as f64 / start.elapsed().as_secs_f64())
    })();
    drop(f);
    result
}
#[cfg(target_os = "linux")]
fn scratch_file(directory: &Path) -> Result<fs::File> {
    use std::os::{fd::FromRawFd, unix::ffi::OsStrExt};
    let path =
        std::ffi::CString::new(directory.as_os_str().as_bytes()).map_err(|e| e.to_string())?;
    // An unnamed inode is reclaimed even after SIGKILL; no user pathname is removed.
    let fd = unsafe {
        libc::open(
            path.as_ptr(),
            libc::O_TMPFILE | libc::O_EXCL | libc::O_RDWR | libc::O_CLOEXEC | libc::O_NOFOLLOW,
            0o600 as libc::mode_t,
        )
    };
    if fd < 0 {
        return Err(format!(
            "scratch filesystem must support private unnamed files: {}",
            std::io::Error::last_os_error()
        ));
    }
    Ok(unsafe { fs::File::from_raw_fd(fd) })
}
#[cfg(not(target_os = "linux"))]
fn scratch(_: &mut Run<'_>, _: &Path, _: &Workload) -> Result<f64> {
    Err("scratch workload requires Linux".into())
}
#[cfg(target_os = "linux")]
fn free_space(path: &Path) -> Result<u64> {
    use std::os::unix::ffi::OsStrExt;
    let path = std::ffi::CString::new(path.as_os_str().as_bytes()).map_err(|e| e.to_string())?;
    let mut stat = std::mem::MaybeUninit::<libc::statvfs>::uninit();
    if unsafe { libc::statvfs(path.as_ptr(), stat.as_mut_ptr()) } != 0 {
        return Err("cannot measure scratch filesystem free space".into());
    }
    let stat = unsafe { stat.assume_init() };
    stat.f_bavail
        .checked_mul(stat.f_frsize)
        .ok_or("scratch free-space overflow".into())
}
#[cfg(not(target_os = "linux"))]
fn free_space(_: &Path) -> Result<u64> {
    Err("scratch workload requires Linux".into())
}

pub(super) fn execute(kind: &str, duration: Duration, json: bool) -> Result<()> {
    #[cfg(target_os = "linux")]
    let _signals = Signals::install()?;
    let store = Store::open()?;
    let _lock = store.lock()?;
    if kind == "baseline" {
        let b = blockers();
        if !b.is_empty() {
            return Err(b.join("; "));
        }
    }
    let mut entropy = [0u8; 16];
    fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut entropy))
        .map_err(|e| e.to_string())?;
    let id = entropy
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    store.create(&id)?;
    let mut report=Report{schema_version:1,id,kind:kind.into(),state:"incomplete".into(),created_unix_seconds:SystemTime::now().duration_since(UNIX_EPOCH).map_err(|e|e.to_string())?.as_secs(),requested_seconds:duration.as_secs(),elapsed_seconds:0.0,context:collect::context(),samples:vec![],measurements:vec![],warnings:vec!["Development microbenchmarks; no physical or gaming performance qualification. Missing sensors remain unavailable. Filesystem results include caching and sync overhead.".into()],failure:None};
    store.write(&report)?;
    let start = Instant::now();
    let result: Result<()> = (|| {
        event(
            "started",
            serde_json::json!({"id":report.id,"kind":kind,"requested_seconds":duration.as_secs()}),
            json,
        )?;
        let mut run = Run {
            report: &mut report,
            started: start,
            previous: None,
            last_sample: None,
            json,
        };
        run.tick()?;
        if kind == "record" {
            run.phase("passive-recording")?;
            run.wait(duration.as_secs())?;
        } else {
            if free_space(&store.path)? < GIB {
                return Err("scratch filesystem requires at least 1 GiB available".into());
            }
            run.phase("idle-baseline")?;
            run.wait(15)?;
            let threads = std::thread::available_parallelism()
                .map_err(|e| e.to_string())?
                .get();
            for w in definitions(threads) {
                run.phase(&format!("{}-warmup", w.name))?;
                if w.name == "sha256" {
                    std::hint::black_box(Sha256::digest(vec![0x5a; MIB]));
                }
                if w.name == "memory-copy" {
                    let a = vec![0x5a; MIB];
                    let mut b = vec![0; MIB];
                    b.copy_from_slice(&a);
                    std::hint::black_box(b);
                }
                run.wait(2)?;
                let mut m = Measurement {
                    workload: w.clone(),
                    unit: "MiB/s".into(),
                    values: vec![],
                };
                for n in 0..3 {
                    run.phase(&format!("{}-repetition-{}", w.name, n + 1))?;
                    let value = match w.name.as_str() {
                        "sha256" => cpu(&mut run, &w)?,
                        "memory-copy" => memory(&mut run, &w)?,
                        _ => {
                            if free_space(&store.path)? < GIB {
                                return Err("scratch free space fell below 1 GiB".into());
                            }
                            let before = Instant::now();
                            let scratch_path = store.path.join(&run.report.id).join("scratch.bin");
                            let v = scratch(&mut run, &scratch_path, &w)?;
                            if before.elapsed() > Duration::from_secs(10) {
                                return Err("scratch repetition exceeded 10 seconds".into());
                            }
                            v
                        }
                    };
                    m.values.push(value);
                }
                run.report.measurements.push(m);
                run.phase("cooldown")?;
                run.wait(5)?;
            }
        }
        run.last_sample = None;
        run.tick()?;
        Ok(())
    })();
    report.elapsed_seconds = start.elapsed().as_secs_f64();
    match &result {
        Ok(()) => report.state = "completed".into(),
        Err(e) => {
            report.state = if e == "cancelled by caller" {
                "cancelled"
            } else {
                "failed"
            }
            .into();
            report.failure = Some(e.clone());
        }
    }
    store.write(&report).map_err(|e| {
        format!("result publication failed; original incomplete record retained: {e}")
    })?;
    event(
        "result",
        serde_json::to_value(&report).map_err(|e| e.to_string())?,
        json,
    )?;
    if !json {
        super::output(&report, false)?;
    }
    result
}

#[cfg(all(test, target_os = "linux"))]
mod real_tests {
    use super::*;
    #[test]
    #[ignore = "explicit bounded Linux workload and unnamed-file test"]
    fn real_workloads_and_stop_cleanup() {
        let root =
            std::env::temp_dir().join(format!("astraeus-real-performance-{}", std::process::id()));
        fs::create_dir(&root).unwrap();
        let mut report = crate::performance::tests::fixture();
        report.kind = "record".into();
        report.requested_seconds = 180;
        let mut run = Run {
            report: &mut report,
            started: Instant::now(),
            previous: None,
            last_sample: None,
            json: false,
        };
        STOP.store(false, Ordering::Relaxed);
        let definitions = definitions(2);
        assert!(cpu(&mut run, &definitions[0]).unwrap() > 0.0);
        assert!(memory(&mut run, &definitions[1]).unwrap() > 0.0);
        assert!(scratch(&mut run, &root.join("never-created.bin"), &definitions[2]).unwrap() > 0.0);
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        let file = scratch_file(&root).unwrap();
        use std::os::unix::fs::MetadataExt;
        assert_eq!(file.metadata().unwrap().nlink(), 0);
        drop(file);
        STOP.store(true, Ordering::Relaxed);
        assert!(scratch(&mut run, &root.join("never-created.bin"), &definitions[2]).is_err());
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        STOP.store(false, Ordering::Relaxed);
        fs::remove_dir(&root).unwrap();
    }
}
