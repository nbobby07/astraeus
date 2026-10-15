use super::*;
use std::{fs, path::PathBuf};
pub(super) fn fixture() -> Report {
    Report {
        schema_version: 1,
        id: "a".repeat(32),
        kind: "baseline".into(),
        state: "completed".into(),
        created_unix_seconds: 1,
        requested_seconds: 180,
        elapsed_seconds: 110.0,
        context: Context {
            architecture: "x86_64".into(),
            cpu_model: Some("fixture".into()),
            logical_cpus: Some(8),
            memory_bytes: Some(8 * 1024 * 1024 * 1024),
            virtual_machine: Some(true),
            virtualization: Some("kvm".into()),
            kernel: Some("fixture-kernel".into()),
            version: "fixture".into(),
            binary_sha256: Some("0".repeat(64)),
            governors: vec![],
            power_sources: BTreeMap::new(),
            renderer: vec!["software; physical acceleration unqualified".into()],
        },
        samples: vec![
            collect::sample(
                std::path::Path::new("/missing-performance-fixture"),
                0.0,
                None,
            )
            .0,
        ],
        measurements: workload::definitions(4)
            .into_iter()
            .map(|workload| Measurement {
                workload,
                unit: "MiB/s".into(),
                values: vec![10.0, 12.0, 11.0],
            })
            .collect(),
        warnings: vec![],
        failure: None,
    }
}
struct Temp(PathBuf);
impl Temp {
    fn new() -> Self {
        let p = std::env::temp_dir().join(format!(
            "astraeus-performance-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir(&p).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&p, fs::Permissions::from_mode(0o700)).unwrap();
        }
        Self(p)
    }
    fn put(&self, path: &str, value: &str) {
        let p = self.0.join(path);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, value).unwrap();
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
#[test]
fn comparison_is_compatible_and_does_not_claim_significance() {
    let a = fixture();
    let mut b = a.clone();
    b.id = "b".repeat(32);
    b.measurements[0].values = vec![20.0, 22.0, 24.0];
    b.context.kernel = Some("changed".into());
    let v = compare(&a, &b).unwrap();
    assert_eq!(v["comparable"], true);
    assert_eq!(v["measurements"][0]["change_percent"], 100.0);
    assert!(v["context_changes"].get("kernel").is_some());
}
#[test]
fn comparison_rejects_different_workload_and_execution_class() {
    let a = fixture();
    let mut b = a.clone();
    b.measurements[0].workload.threads = 2;
    assert!(compare(&a, &b).is_err() || compare(&a, &b).unwrap()["comparable"] == false);
    b = a.clone();
    b.context.virtual_machine = Some(false);
    assert_eq!(compare(&a, &b).unwrap()["comparable"], false);
    b = a.clone();
    b.state = "incomplete".into();
    assert_eq!(compare(&a, &b).unwrap()["comparable"], false);
}
#[test]
fn bare_metal_and_kernel_memory_changes_remain_comparable() {
    let mut a = fixture();
    a.context.virtual_machine = Some(false);
    a.context.virtualization = None;
    let mut b = a.clone();
    b.id = "b".repeat(32);
    b.context.memory_bytes = Some(8 * 1024 * 1024 * 1024 - 48 * 1024 * 1024);
    let v = compare(&a, &b).unwrap();
    assert_eq!(v["comparable"], true);
    assert!(v["context_changes"].get("memory_bytes").is_some());
    b.context.memory_bytes = Some(4 * 1024 * 1024 * 1024);
    assert_eq!(compare(&a, &b).unwrap()["comparable"], false);
    b.context.memory_bytes = None;
    assert_eq!(compare(&a, &b).unwrap()["comparable"], false);
    let t = Temp::new();
    assert_eq!(collect::hypervisor_flag(&t.0), None);
    t.put("proc/cpuinfo", "processor\t: 0\nflags\t\t: fpu sse2 avx2\n");
    assert_eq!(collect::hypervisor_flag(&t.0), Some(false));
    t.put(
        "proc/cpuinfo",
        "processor\t: 0\nflags\t\t: fpu hypervisor\n",
    );
    assert_eq!(collect::hypervisor_flag(&t.0), Some(true));
}
#[test]
fn zero_denominator_is_unavailable() {
    let mut a = fixture();
    a.measurements[0].values = vec![0.0; 3];
    assert!(compare(&a, &fixture()).unwrap()["measurements"][0]["change_percent"].is_null());
}
#[test]
fn invalid_reports_never_become_success() {
    let a = fixture();
    a.validate().unwrap();
    let mut b = a.clone();
    b.measurements[0].values.pop();
    assert!(b.validate().is_err());
    b = a.clone();
    b.samples[0].elapsed_seconds = f64::NAN;
    assert!(b.validate().is_err());
    b = a.clone();
    b.measurements[0].values[0] = f64::INFINITY;
    assert!(b.validate().is_err());
    b = a;
    b.schema_version = 2;
    assert!(b.validate().is_err());
}
#[test]
fn missing_sensors_are_not_zero() {
    let t = Temp::new();
    let s = collect::sample(&t.0, 0.0, None).0;
    assert!(s.cpu_busy_percent.is_none());
    assert!(s.memory_available_bytes.is_none());
    assert!(!s.unavailable.is_empty());
}
#[test]
fn counters_use_elapsed_time_and_reject_resets() {
    assert_eq!(
        collect::cpu_counters("cpu  10 0 10 70 10 0 0 0 99 99\n"),
        Some((100, 80))
    );
    assert_eq!(collect::rate(100, 20, 2.0), Some(40.0));
    assert_eq!(collect::rate(10, 20, 2.0), None);
    assert_eq!(collect::rate(10, 0, 0.0), None);
    let t = Temp::new();
    t.put("proc/stat", "cpu 10 0 10 80 0 0 0 0\n");
    t.put(
        "proc/meminfo",
        "MemAvailable: 100 kB\nSwapTotal: 50 kB\nSwapFree: 30 kB\n",
    );
    t.put("proc/vmstat", "pswpin 10\npswpout 20\n");
    let (_, a) = collect::sample(&t.0, 0.0, None);
    t.put("proc/stat", "cpu 20 0 20 100 0 0 0 0\n");
    t.put("proc/vmstat", "pswpin 14\npswpout 26\n");
    let (s, b) = collect::sample(&t.0, 2.0, Some(&a));
    assert_eq!(s.cpu_busy_percent, Some(50.0));
    assert_eq!(s.swap_in_pages_per_second, Some(2.0));
    assert_eq!(s.swap_out_pages_per_second, Some(3.0));
    assert_eq!(s.swap_used_bytes, Some(20 * 1024));
    t.put("proc/stat", "cpu 1 0 1 1 0 0 0 0\n");
    assert!(collect::sample(&t.0, 3.0, Some(&b))
        .0
        .cpu_busy_percent
        .is_none());
}
#[test]
fn temperature_and_pressure_are_bounded() {
    let t = Temp::new();
    t.put("sys/class/thermal/thermal_zone0/temp", "85000");
    t.put("sys/class/thermal/thermal_zone0/type", "fixture");
    t.put(
        "sys/class/thermal/thermal_zone0/trip_point_0_type",
        "critical",
    );
    t.put("sys/class/thermal/thermal_zone0/trip_point_0_temp", "90000");
    t.put(
        "proc/pressure/cpu",
        "some avg10=1.50 avg60=2.0 total=20\nfull avg10=nan total=2",
    );
    let s = collect::sample(&t.0, 0.0, None).0;
    assert_eq!(s.temperatures[0].celsius, 85.0);
    assert_eq!(s.temperatures[0].critical_celsius, Some(90.0));
    assert_eq!(s.pressure_avg10_percent.len(), 1);
    s.validate().unwrap();
}
#[cfg(unix)]
#[test]
fn peripheral_power_supplies_never_enter_reports() {
    let t = Temp::new();
    t.put("sys/class/power_supply/AC/type", "Mains\n");
    t.put("sys/class/power_supply/AC/online", "1\n");
    t.put("sys/class/power_supply/BAT0/type", "Battery\n");
    t.put("sys/class/power_supply/BAT0/scope", "System\n");
    t.put("sys/class/power_supply/BAT0/power_now", "5000000\n");
    let peripheral = "sys/class/power_supply/hid-aa:bb:cc:dd:ee:ff-battery";
    t.put(&format!("{peripheral}/type"), "Battery\n");
    t.put(&format!("{peripheral}/scope"), "Device\n");
    t.put(&format!("{peripheral}/status"), "Discharging\n");
    t.put(&format!("{peripheral}/power_now"), "1000\n");
    let s = collect::sample(&t.0, 0.0, None).0;
    assert_eq!(s.power_microwatts.keys().collect::<Vec<_>>(), ["BAT0"]);
    let sources = collect::power_sources(&t.0);
    assert_eq!(
        sources.keys().collect::<Vec<_>>(),
        ["AC.online", "AC.type", "BAT0.type"]
    );
    assert!(!serde_json::to_string(&s).unwrap().contains("aa:bb"));
}
#[test]
fn store_roundtrip_and_failed_publication_preserves_original() {
    let t = Temp::new();
    let store = store::Store::at(t.0.clone()).unwrap();
    let mut r = fixture();
    r.samples[0].cpu_busy_percent = Some(13.165680473372781);
    r.measurements[1].values[2] = 14696.678710017999;
    r.measurements[2].values[2] = 921.9176614809459;
    store.create(&r.id).unwrap();
    store.write(&r).unwrap();
    assert_eq!(
        serde_json::to_value(store.read(&r.id).unwrap()).unwrap(),
        serde_json::to_value(&r).unwrap()
    );
    fs::write(
        t.0.join(&r.id)
            .join(format!("result-{}.tmp", std::process::id())),
        b"occupied",
    )
    .unwrap();
    r.state = "failed".into();
    assert!(store.write(&r).is_err());
    assert_eq!(store.read(&r.id).unwrap().state, "completed");
    assert!(store.read("../escape").is_err());
    assert!(store.create(&r.id).is_err());
}
#[test]
fn storage_refuses_future_and_oversized_documents() {
    let t = Temp::new();
    let store = store::Store::at(t.0.clone()).unwrap();
    let r = fixture();
    store.create(&r.id).unwrap();
    store.write(&r).unwrap();
    let p = t.0.join(&r.id).join("result.json");
    let mut v = serde_json::to_value(r).unwrap();
    v["schema_version"] = 2.into();
    fs::write(&p, v.to_string()).unwrap();
    assert!(store.read(&"a".repeat(32)).is_err());
    fs::write(&p, vec![b' '; MAX_REPORT + 1]).unwrap();
    assert!(store.read(&"a".repeat(32)).is_err());
}
#[cfg(target_os = "linux")]
#[test]
fn storage_refuses_symlinks_and_excludes_parallel_runs() {
    use std::os::unix::fs::symlink;
    let t = Temp::new();
    let store = store::Store::at(t.0.clone()).unwrap();
    let lock = store.lock().unwrap();
    assert!(store.lock().is_err());
    drop(lock);
    store.lock().unwrap();
    let target = t.0.join("target");
    fs::write(&target, b"personal").unwrap();
    let id = "a".repeat(32);
    symlink(&target, t.0.join(&id)).unwrap();
    assert!(store.read(&id).is_err());
    assert!(store.create(&id).is_err());
    assert_eq!(fs::read(target).unwrap(), b"personal");
}
#[test]
fn definitions_respect_limits_and_cli_rejects_unbounded_input() {
    for w in workload::definitions(999) {
        assert!(w.threads <= 4 && w.bytes <= 128 * 1024 * 1024);
        assert_eq!(w.repetitions, 3);
    }
    for args in [
        vec!["record", "--duration", "301"],
        vec!["record", "--duration", "0"],
        vec!["baseline", "--command", "sh"],
        vec!["status", "--json", "--json"],
    ] {
        assert!(run(&args.into_iter().map(String::from).collect::<Vec<_>>()).is_err());
    }
}
