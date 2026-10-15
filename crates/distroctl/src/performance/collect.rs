use super::Result;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fs, io::Read, path::Path};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Context {
    pub architecture: String,
    pub cpu_model: Option<String>,
    pub logical_cpus: Option<usize>,
    pub memory_bytes: Option<u64>,
    pub virtual_machine: Option<bool>,
    pub virtualization: Option<String>,
    pub kernel: Option<String>,
    pub version: String,
    pub binary_sha256: Option<String>,
    pub governors: Vec<String>,
    pub power_sources: BTreeMap<String, String>,
    pub renderer: Vec<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Temperature {
    pub label: String,
    pub celsius: f64,
    pub critical_celsius: Option<f64>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Sample {
    pub elapsed_seconds: f64,
    pub cpu_busy_percent: Option<f64>,
    pub load_average: Option<[f64; 3]>,
    pub memory_available_bytes: Option<u64>,
    pub swap_used_bytes: Option<u64>,
    pub swap_in_pages_per_second: Option<f64>,
    pub swap_out_pages_per_second: Option<f64>,
    pub pressure_avg10_percent: BTreeMap<String, f64>,
    pub cpu_frequency_khz: BTreeMap<String, u64>,
    pub temperatures: Vec<Temperature>,
    pub power_microwatts: BTreeMap<String, u64>,
    pub disk_read_bytes_per_second: Option<f64>,
    pub disk_write_bytes_per_second: Option<f64>,
    pub unavailable: Vec<String>,
}
impl Sample {
    pub(super) fn validate(&self) -> Result<()> {
        if !self.elapsed_seconds.is_finite()
            || !(0.0..=3600.0).contains(&self.elapsed_seconds)
            || self
                .cpu_busy_percent
                .is_some_and(|v| !v.is_finite() || !(0.0..=100.0).contains(&v))
            || self
                .load_average
                .is_some_and(|v| v.iter().any(|x| !x.is_finite() || *x < 0.0))
            || [
                self.swap_in_pages_per_second,
                self.swap_out_pages_per_second,
                self.disk_read_bytes_per_second,
                self.disk_write_bytes_per_second,
            ]
            .into_iter()
            .flatten()
            .any(|v| !v.is_finite() || v < 0.0)
            || self
                .pressure_avg10_percent
                .values()
                .any(|v| !v.is_finite() || !(0.0..=100.0).contains(v))
            || self.temperatures.iter().any(|v| {
                !valid_temp(v.celsius) || v.critical_celsius.is_some_and(|v| !valid_temp(v))
            })
            || self.temperatures.len() > 128
            || self.cpu_frequency_khz.len() > 128
            || self.power_microwatts.len() > 64
            || self.unavailable.len() > 32
        {
            return Err("invalid performance sample".into());
        }
        Ok(())
    }
}
#[derive(Debug, Clone)]
pub(super) struct Counters {
    elapsed: f64,
    cpu: Option<(u64, u64)>,
    swap: Option<(u64, u64)>,
    disk: Option<BTreeMap<String, (u64, u64)>>,
}
pub fn collect() -> Sample {
    let start = std::time::Instant::now();
    let (_, previous) = sample(Path::new("/"), 0.0, None);
    std::thread::sleep(std::time::Duration::from_millis(250));
    sample(
        Path::new("/"),
        start.elapsed().as_secs_f64(),
        Some(&previous),
    )
    .0
}
fn read(root: &Path, name: &str) -> Option<String> {
    let mut data = String::new();
    fs::File::open(root.join(name))
        .ok()?
        .take(64 * 1024)
        .read_to_string(&mut data)
        .ok()?;
    (data.len() < 64 * 1024).then_some(data)
}
fn number(root: &Path, name: &str) -> Option<u64> {
    read(root, name)?.trim().parse().ok()
}
pub(super) fn memory(root: &Path) -> BTreeMap<String, u64> {
    read(root, "proc/meminfo")
        .unwrap_or_default()
        .lines()
        .filter_map(|line| {
            let (key, value) = line.split_once(':')?;
            let mut parts = value.split_whitespace();
            let n = parts.next()?.parse::<u64>().ok()?;
            if parts.next()? != "kB" {
                return None;
            }
            Some((key.into(), n.checked_mul(1024)?))
        })
        .collect()
}
pub(super) fn cpu_counters(text: &str) -> Option<(u64, u64)> {
    let mut parts = text
        .lines()
        .find(|l| l.starts_with("cpu "))?
        .split_whitespace();
    parts.next()?;
    let values = parts
        .take(8)
        .map(str::parse::<u64>)
        .collect::<std::result::Result<Vec<_>, _>>()
        .ok()?;
    if values.len() < 4 {
        return None;
    }
    let total = values.iter().try_fold(0u64, |sum, n| sum.checked_add(*n))?;
    let idle = values[3].checked_add(values.get(4).copied().unwrap_or(0))?;
    Some((total, idle))
}
pub(super) fn rate(now: u64, old: u64, seconds: f64) -> Option<f64> {
    if !seconds.is_finite() || seconds <= 0.0 {
        return None;
    }
    Some(now.checked_sub(old)? as f64 / seconds)
}
fn children(root: &Path, name: &str, max: usize) -> Vec<String> {
    let mut entries: Vec<_> = fs::read_dir(root.join(name))
        .into_iter()
        .flatten()
        .filter_map(|e| e.ok()?.file_name().into_string().ok())
        .collect();
    entries.sort();
    entries.truncate(max);
    entries
}
fn valid_temp(v: f64) -> bool {
    v.is_finite() && (-100.0..=200.0).contains(&v)
}
fn temp(root: &Path, path: &str) -> Option<f64> {
    let v = read(root, path)?.trim().parse::<i64>().ok()? as f64 / 1000.0;
    valid_temp(v).then_some(v)
}
pub(super) fn sample(root: &Path, elapsed: f64, previous: Option<&Counters>) -> (Sample, Counters) {
    let cpu = read(root, "proc/stat").and_then(|s| cpu_counters(&s));
    let mem = memory(root);
    let vm: BTreeMap<_, _> = read(root, "proc/vmstat")
        .unwrap_or_default()
        .lines()
        .filter_map(|s| {
            let mut p = s.split_whitespace();
            Some((p.next()?.to_owned(), p.next()?.parse::<u64>().ok()?))
        })
        .collect();
    let swap = vm
        .get("pswpin")
        .zip(vm.get("pswpout"))
        .map(|(a, b)| (*a, *b));
    let mut disk = BTreeMap::new();
    let mut disk_valid = true;
    for name in children(root, "sys/block", 128) {
        if name.starts_with("loop")
            || name.starts_with("ram")
            || name.starts_with("dm-")
            || name.starts_with("md")
        {
            continue;
        }
        let path = format!("sys/block/{name}/stat");
        let values = read(root, &path).and_then(|s| {
            s.split_whitespace()
                .map(str::parse::<u64>)
                .collect::<std::result::Result<Vec<_>, _>>()
                .ok()
        });
        if let Some(v) = values.filter(|v| v.len() >= 7) {
            if let Some(pair) = v[2].checked_mul(512).zip(v[6].checked_mul(512)) {
                disk.insert(name, pair);
            } else {
                disk_valid = false;
            }
        } else {
            disk_valid = false;
        }
    }
    let disk = (!disk.is_empty() && disk_valid).then_some(disk);
    let mut s = Sample {
        elapsed_seconds: elapsed,
        cpu_busy_percent: None,
        load_average: None,
        memory_available_bytes: mem.get("MemAvailable").copied(),
        swap_used_bytes: mem
            .get("SwapTotal")
            .zip(mem.get("SwapFree"))
            .and_then(|(a, b)| a.checked_sub(*b)),
        swap_in_pages_per_second: None,
        swap_out_pages_per_second: None,
        pressure_avg10_percent: BTreeMap::new(),
        cpu_frequency_khz: BTreeMap::new(),
        temperatures: vec![],
        power_microwatts: BTreeMap::new(),
        disk_read_bytes_per_second: None,
        disk_write_bytes_per_second: None,
        unavailable: vec![],
    };
    if let Some(text) = read(root, "proc/loadavg") {
        let v: Vec<_> = text
            .split_whitespace()
            .take(3)
            .filter_map(|v| v.parse::<f64>().ok().filter(|v| v.is_finite() && *v >= 0.0))
            .collect();
        if v.len() == 3 {
            s.load_average = Some([v[0], v[1], v[2]]);
        }
    }
    if let Some(old) = previous {
        let seconds = elapsed - old.elapsed;
        if let (Some((total, idle)), Some((ot, oi))) = (cpu, old.cpu) {
            s.cpu_busy_percent = total
                .checked_sub(ot)
                .zip(idle.checked_sub(oi))
                .filter(|(t, i)| *t > 0 && i <= t)
                .map(|(t, i)| 100.0 * (t - i) as f64 / t as f64);
        }
        if let (Some((a, b)), Some((oa, ob))) = (swap, old.swap) {
            s.swap_in_pages_per_second = rate(a, oa, seconds);
            s.swap_out_pages_per_second = rate(b, ob, seconds);
        }
        if let (Some(now), Some(before)) = (&disk, &old.disk) {
            if now.keys().eq(before.keys()) {
                let sum = now.iter().try_fold((0u64, 0u64), |(r, w), (k, (nr, nw))| {
                    Some((
                        r.checked_add(nr.checked_sub(before[k].0)?)?,
                        w.checked_add(nw.checked_sub(before[k].1)?)?,
                    ))
                });
                if let Some((r, w)) = sum {
                    s.disk_read_bytes_per_second = rate(r, 0, seconds);
                    s.disk_write_bytes_per_second = rate(w, 0, seconds);
                }
            }
        }
    }
    for kind in ["cpu", "memory", "io"] {
        for line in read(root, &format!("proc/pressure/{kind}"))
            .unwrap_or_default()
            .lines()
        {
            let mut p = line.split_whitespace();
            let Some(class) = p.next() else { continue };
            if !matches!(class, "some" | "full") {
                continue;
            }
            if let Some(n) = p
                .find_map(|v| v.strip_prefix("avg10="))
                .and_then(|v| v.parse::<f64>().ok())
                .filter(|v| v.is_finite() && (0.0..=100.0).contains(v))
            {
                s.pressure_avg10_percent
                    .insert(format!("{kind}.{class}"), n);
            }
        }
    }
    for name in children(root, "sys/devices/system/cpu/cpufreq", 128) {
        if let Some(n) = number(
            root,
            &format!("sys/devices/system/cpu/cpufreq/{name}/scaling_cur_freq"),
        ) {
            s.cpu_frequency_khz.insert(name, n);
        }
    }
    for zone in children(root, "sys/class/thermal", 128) {
        if !zone.starts_with("thermal_zone") {
            continue;
        }
        let path = format!("sys/class/thermal/{zone}");
        if let Some(v) = temp(root, &format!("{path}/temp")) {
            let mut critical = None;
            for n in 0..32 {
                if read(root, &format!("{path}/trip_point_{n}_type"))
                    .is_some_and(|s| s.trim() == "critical")
                {
                    critical = temp(root, &format!("{path}/trip_point_{n}_temp"));
                    break;
                }
            }
            let label = read(root, &format!("{path}/type"))
                .unwrap_or(zone)
                .trim()
                .chars()
                .take(80)
                .collect();
            s.temperatures.push(Temperature {
                label,
                celsius: v,
                critical_celsius: critical,
            });
        }
    }
    for chip in children(root, "sys/class/hwmon", 32) {
        let path = format!("sys/class/hwmon/{chip}");
        for n in 1..=32 {
            if s.temperatures.len() < 128 {
                if let Some(value) = temp(root, &format!("{path}/temp{n}_input")) {
                    let chip_name =
                        read(root, &format!("{path}/name")).unwrap_or_else(|| chip.clone());
                    let channel = read(root, &format!("{path}/temp{n}_label"))
                        .unwrap_or_else(|| format!("temperature {n}"));
                    let label = format!("{} {}", chip_name.trim(), channel.trim())
                        .chars()
                        .take(80)
                        .collect();
                    s.temperatures.push(Temperature {
                        label,
                        celsius: value,
                        critical_celsius: temp(root, &format!("{path}/temp{n}_crit")),
                    });
                }
            }
            if s.power_microwatts.len() < 64 {
                if let Some(value) = number(root, &format!("{path}/power{n}_input")) {
                    s.power_microwatts.insert(format!("{chip}.power{n}"), value);
                }
            }
        }
    }
    for name in children(root, "sys/class/power_supply", 64) {
        if s.power_microwatts.len() >= 64 {
            break;
        }
        if let Some(n) = number(root, &format!("sys/class/power_supply/{name}/power_now")) {
            s.power_microwatts.insert(name, n);
        }
    }
    for (missing, label) in [
        (
            s.cpu_busy_percent.is_none(),
            "CPU utilization needs two valid counters",
        ),
        (s.memory_available_bytes.is_none(), "Available memory"),
        (s.load_average.is_none(), "Load average"),
        (
            s.swap_in_pages_per_second.is_none(),
            "Swap activity needs two valid counters",
        ),
        (
            s.disk_read_bytes_per_second.is_none(),
            "Disk activity needs unchanged device identities and two valid counters",
        ),
        (s.temperatures.is_empty(), "Readable thermal zones"),
        (
            s.power_microwatts.is_empty(),
            "Readable instantaneous power sensors",
        ),
        (s.pressure_avg10_percent.is_empty(), "Pressure measurements"),
        (s.cpu_frequency_khz.is_empty(), "CPU frequency policies"),
    ] {
        if missing {
            s.unavailable.push(label.into());
        }
    }
    (
        s,
        Counters {
            elapsed,
            cpu,
            swap,
            disk,
        },
    )
}

pub(super) fn context() -> Context {
    let root = Path::new("/");
    let observed = crate::status();
    let hw = observed.hardware;
    let mut governors = vec![];
    for name in children(root, "sys/devices/system/cpu/cpufreq", 128) {
        if let Some(v) = read(
            root,
            &format!("sys/devices/system/cpu/cpufreq/{name}/scaling_governor"),
        ) {
            governors.push(v.trim().chars().take(80).collect());
        }
    }
    governors.sort();
    governors.dedup();
    let mut power_sources = BTreeMap::new();
    for name in children(root, "sys/class/power_supply", 64) {
        for field in ["type", "status", "online"] {
            if let Some(v) = read(root, &format!("sys/class/power_supply/{name}/{field}")) {
                power_sources.insert(
                    format!("{name}.{field}"),
                    v.trim().chars().take(80).collect(),
                );
            }
        }
    }
    let graphics = distro_graphics::probe(false);
    // Only classification, never device serials, hostnames or user paths, enters a report.
    let mut renderer = vec![format!(
        "Graphics activation: {:?}; physical performance unqualified",
        graphics.activation
    )];
    if let Some(name) = graphics.opengl_renderer {
        renderer.push(name.chars().take(160).collect());
    }
    for gpu in hw.gpus.as_ref().into_iter().flatten() {
        renderer.push(format!(
            "{}: {}",
            gpu.vendor.as_deref().unwrap_or("Unknown vendor"),
            gpu.driver.as_deref().unwrap_or("No bound driver")
        ));
    }
    let binary_sha256 = std::env::current_exe().ok().and_then(|p| {
        let file = fs::File::open(p).ok()?;
        let mut hash = Sha256::new();
        let mut source = file.take(128 * 1024 * 1024);
        std::io::copy(&mut source, &mut hash).ok()?;
        Some(format!("{:x}", hash.finalize()))
    });
    Context {
        architecture: hw.cpu.architecture,
        cpu_model: hw.cpu.model,
        logical_cpus: hw.cpu.logical_count,
        memory_bytes: hw.memory_bytes,
        virtual_machine: hw.capabilities.virtual_machine,
        virtualization: hw.capabilities.virtualization_type,
        kernel: observed.kernel,
        version: env!("CARGO_PKG_VERSION").into(),
        binary_sha256,
        governors,
        power_sources,
        renderer,
    }
}
