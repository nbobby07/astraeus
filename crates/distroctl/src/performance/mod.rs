//! Ordinary-user observations and bounded, versioned development microbenchmarks.
mod collect;
mod store;
#[cfg(test)]
mod tests;
mod workload;

pub use collect::{collect, Context, Sample};
use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, io::Write, time::Duration};
type Result<T> = std::result::Result<T, String>;
pub const MAX_REPORT: usize = 2 * 1024 * 1024;
pub const HELP: &str = "Performance observations and development microbenchmarks
  distroctl performance status [--json]
  distroctl performance record [--duration <1..300 seconds>] [--json]
  distroctl performance baseline [--json]
  distroctl performance list [--json]
  distroctl performance show|export <32-hex-id> [--json]
  distroctl performance compare <id> <id> [--json]

Record defaults to 60 seconds. Baselines take roughly two minutes (180-second limit).
CPU: at most 4 threads. Memory: at most 128 MiB. Scratch: one 128 MiB file.
Measurements never change system settings. Ctrl+C/Stop preserves an incomplete run.
Long-running --json output is newline-delimited schema-1 events, ending in a result.
Missing sensors remain unavailable. VM and software-rendering results are labelled.
These workloads do not establish gaming or physical hardware performance.";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Workload {
    pub name: String,
    pub version: u32,
    pub threads: usize,
    pub bytes: u64,
    pub repetition_seconds: u64,
    pub repetitions: u32,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Measurement {
    pub workload: Workload,
    pub unit: String,
    pub values: Vec<f64>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Report {
    pub schema_version: u32,
    pub id: String,
    pub kind: String,
    pub state: String,
    pub created_unix_seconds: u64,
    pub requested_seconds: u64,
    pub elapsed_seconds: f64,
    pub context: Context,
    pub samples: Vec<Sample>,
    pub measurements: Vec<Measurement>,
    pub warnings: Vec<String>,
    pub failure: Option<String>,
}
impl Report {
    fn validate(&self) -> Result<()> {
        if self.schema_version != 1
            || !store::valid_id(&self.id)
            || !matches!(self.kind.as_str(), "record" | "baseline")
            || !matches!(
                self.state.as_str(),
                "incomplete" | "completed" | "cancelled" | "failed"
            )
            || !(1..=300).contains(&self.requested_seconds)
            || !self.elapsed_seconds.is_finite()
            || !(0.0..=3600.0).contains(&self.elapsed_seconds)
            || self.samples.len() > 301
            || self.measurements.len() > 3
            || self.warnings.len() > 64
        {
            return Err("invalid performance report".into());
        }
        for sample in &self.samples {
            sample.validate()?;
        }
        for m in &self.measurements {
            if !matches!(
                m.workload.name.as_str(),
                "sha256" | "memory-copy" | "scratch-sync-read"
            ) || m.workload.version != 1
                || !(1..=4).contains(&m.workload.threads)
                || m.workload.bytes == 0
                || m.workload.bytes > 128 * 1024 * 1024
                || m.workload.repetition_seconds != 10
                || m.workload.repetitions != 3
                || m.unit != "MiB/s"
                || m.values.len() > 3
                || m.values.iter().any(|v| !v.is_finite() || *v < 0.0)
                || (self.state == "completed" && m.values.len() != 3)
            {
                return Err("invalid workload measurements".into());
            }
        }
        if self.state == "completed"
            && (self.failure.is_some()
                || self.samples.is_empty()
                || self.kind == "baseline" && self.measurements.len() != 3)
        {
            return Err("completed report has incomplete evidence".into());
        }
        if self.kind == "record" && !self.measurements.is_empty() {
            return Err("passive record cannot contain benchmark measurements".into());
        }
        if self.kind == "baseline" {
            let threads = self
                .measurements
                .first()
                .map(|m| m.workload.threads)
                .unwrap_or(1);
            let expected = workload::definitions(threads);
            if self
                .measurements
                .iter()
                .zip(expected)
                .any(|(m, w)| m.workload != w)
            {
                return Err("workload definitions do not match baseline version 1".into());
            }
        }
        Ok(())
    }
}

pub fn compare(a: &Report, b: &Report) -> Result<serde_json::Value> {
    a.validate()?;
    b.validate()?;
    let mut blockers = Vec::new();
    if a.state != "completed" || b.state != "completed" {
        blockers.push("Both runs must be completed baselines");
    }
    if a.kind != "baseline" || b.kind != "baseline" {
        blockers.push("Passive recordings are observations, not comparable workloads");
    }
    if a.context.architecture != b.context.architecture
        || a.context.cpu_model != b.context.cpu_model
        || a.context.logical_cpus != b.context.logical_cpus
        || a.context.virtual_machine != b.context.virtual_machine
        || a.context.virtualization != b.context.virtualization
        || a.context.memory_bytes != b.context.memory_bytes
        || a.context.cpu_model.is_none()
        || a.context.virtual_machine.is_none()
    {
        blockers.push("Machine or execution class differs or is unknown");
    }
    if a.measurements
        .iter()
        .map(|m| &m.workload)
        .ne(b.measurements.iter().map(|m| &m.workload))
    {
        blockers.push("Workload versions or resource settings differ");
    }
    let mut changes = BTreeMap::new();
    for key in [
        "kernel",
        "binary_sha256",
        "version",
        "governors",
        "power_sources",
        "renderer",
    ] {
        let x = serde_json::to_value(&a.context).map_err(|e| e.to_string())?;
        let y = serde_json::to_value(&b.context).map_err(|e| e.to_string())?;
        if x[key] != y[key] {
            changes.insert(key, serde_json::json!({"before":x[key],"after":y[key]}));
        }
    }
    let rows: Vec<_> = if blockers.is_empty() {
        a.measurements.iter().zip(&b.measurements).map(|(x,y)| {
            let before = summary(&x.values); let after = summary(&y.values);
            let delta = if before.0 > 0.0 { Some((after.0-before.0)/before.0*100.0) } else { None };
            serde_json::json!({"workload":x.workload,"unit":x.unit,"before":{"values":x.values,"median":before.0,"spread":before.1},"after":{"values":y.values,"median":after.0,"spread":after.1},"change_percent":delta})
        }).collect()
    } else {
        vec![]
    };
    Ok(
        serde_json::json!({"schema_version":1,"before":a.id,"after":b.id,"comparable":blockers.is_empty(),"blockers":blockers,"context_changes":changes,"conditions":{"before":conditions(a),"after":conditions(b)},"measurements":rows,"warning":"Three repetitions are descriptive; background load, thermal conditions and filesystem caching affect results. Matching models do not prove the same physical machine."}),
    )
}
fn conditions(r: &Report) -> serde_json::Value {
    let cpus: Vec<_> = r
        .samples
        .iter()
        .filter_map(|s| s.cpu_busy_percent)
        .collect();
    let temps: Vec<_> = r
        .samples
        .iter()
        .flat_map(|s| s.temperatures.iter().map(|t| t.celsius))
        .collect();
    serde_json::json!({"cpu_busy_percent_median":(!cpus.is_empty()).then(||summary(&cpus).0),"peak_observed_celsius":temps.into_iter().reduce(f64::max),"minimum_available_memory_bytes":r.samples.iter().filter_map(|s|s.memory_available_bytes).min(),"power_microwatts_last_observation":r.samples.last().map(|s|&s.power_microwatts),"samples":r.samples.len()})
}
fn summary(values: &[f64]) -> (f64, f64) {
    if values.is_empty() {
        return (0.0, 0.0);
    }
    let mut values = values.to_vec();
    values.sort_by(f64::total_cmp);
    (
        values[values.len() / 2],
        values[values.len() - 1] - values[0],
    )
}

fn output(value: &impl Serialize, json: bool) -> Result<()> {
    let value = serde_json::to_value(value).map_err(|e| e.to_string())?;
    if json {
        println!(
            "{}",
            serde_json::to_string(&value).map_err(|e| e.to_string())?
        );
    } else {
        println!(
            "{}",
            serde_json::to_string_pretty(&value).map_err(|e| e.to_string())?
        );
    }
    Ok(())
}
fn event(kind: &str, value: serde_json::Value, json: bool) -> Result<()> {
    if json {
        let mut stdout = std::io::stdout().lock();
        writeln!(
            stdout,
            "{}",
            serde_json::json!({"schema_version":1,"event":kind,"data":value})
        )
        .map_err(|e| e.to_string())?;
        stdout.flush().map_err(|e| e.to_string())?;
    } else {
        eprintln!("{kind}: {value}");
    }
    Ok(())
}
pub fn run(args: &[String]) -> Result<()> {
    let json = args.iter().any(|a| a == "--json");
    if args.iter().filter(|a| a.as_str() == "--json").count() > 1 {
        return Err("duplicate --json".into());
    }
    let args: Vec<_> = args
        .iter()
        .filter(|a| a.as_str() != "--json")
        .map(String::as_str)
        .collect();
    match args.as_slice() {
        [] | ["--help"] => {
            println!("{HELP}");
            Ok(())
        }
        ["status"] => {
            let sample = collect::collect();
            output(
                &serde_json::json!({"schema_version":1,"context":collect::context(),"sample":sample,"baseline_blockers":workload::blockers()}),
                json,
            )
        }
        ["record"] => workload::execute("record", Duration::from_secs(60), json),
        ["record", "--duration", seconds] => {
            let n = seconds
                .parse::<u64>()
                .map_err(|_| "duration must be 1..300 seconds")?;
            if !(1..=300).contains(&n) {
                return Err("duration must be 1..300 seconds".into());
            }
            workload::execute("record", Duration::from_secs(n), json)
        }
        ["baseline"] => workload::execute("baseline", Duration::from_secs(180), json),
        ["list"] => output(
            &serde_json::json!({"schema_version":1,"runs":store::Store::open()?.list()?}),
            json,
        ),
        ["show" | "export", id] => output(&store::Store::open()?.read(id)?, json),
        ["compare", a, b] => {
            let store = store::Store::open()?;
            output(&compare(&store.read(a)?, &store.read(b)?)?, json)
        }
        _ => Err(format!("invalid performance arguments\n{HELP}")),
    }
}
