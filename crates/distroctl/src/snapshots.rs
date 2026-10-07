use distro_snapshots::{Health, Manager, Native, Reason, Result, SnapshotId};
use std::path::Path;

const HELP: &str = "Usage:
  distroctl snapshot list [--json]
  distroctl snapshot show <id> [--json]
  distroctl snapshot create [--reason manual|pre-update|post-update] [--transaction <id>] [--dry-run] [--json]
  distroctl snapshot mark <id> unknown|candidate|known-good|bad --evidence <text> [--json]
  distroctl snapshot delete <id> --top-level <mount> --esp <mount>
  distroctl rollback <id> --dry-run [--json]
  distroctl rollback <id> --execute --top-level <mount> --esp <mount> [--json]

All commands accept --top-level and --esp together to inspect an offline install.
Mount Btrfs subvolid=5 and its ESP separately in recovery media. Installed
subvolumes must be unmounted. Execution preserves the old root and UKI.
List/show read public metadata without root. Rollback planning inspects private
snapshot content and requires read access (normally sudo). No automatic reboot.";

pub fn run(args: &[String]) -> Result<()> {
    if args == ["snapshot", "--help"] || args == ["rollback", "--help"] {
        println!("{HELP}");
        return Ok(());
    }
    let mut positionals = Vec::new();
    let mut flags = std::collections::BTreeMap::new();
    let mut args = args.iter();
    while let Some(arg) = args.next() {
        if arg.starts_with("--") {
            let value = match arg.as_str() {
                "--json" | "--dry-run" | "--execute" => "",
                "--top-level" | "--esp" | "--reason" | "--transaction" | "--evidence" => args
                    .next()
                    .filter(|v| !v.starts_with("--"))
                    .ok_or("missing option value")?,
                _ => return Err(format!("unknown snapshot option: {arg}").into()),
            };
            if flags.insert(arg.as_str(), value).is_some() {
                return Err("duplicate option".into());
            }
        } else {
            positionals.push(arg.as_str());
        }
    }
    let allowed: &[&str] = match positionals.as_slice() {
        ["snapshot", "list"] | ["snapshot", "show", _] => &["--json", "--top-level", "--esp"],
        ["snapshot", "create"] => &[
            "--json",
            "--top-level",
            "--esp",
            "--reason",
            "--transaction",
            "--dry-run",
        ],
        ["snapshot", "mark", _, _] => &["--json", "--top-level", "--esp", "--evidence"],
        ["snapshot", "delete", _] => &["--top-level", "--esp"],
        ["rollback", _] => &["--json", "--top-level", "--esp", "--dry-run", "--execute"],
        _ => return Err(format!("unsupported snapshot arguments\n{HELP}").into()),
    };
    if flags.keys().any(|f| !allowed.contains(f)) {
        return Err("option is not valid for this command".into());
    }
    let manager = match (flags.get("--top-level"), flags.get("--esp")) {
        (None, None) => Manager::online(Native),
        (Some(top), Some(esp)) => Manager::recovery(Native, Path::new(top), Path::new(esp))?,
        _ => return Err("--top-level and --esp are required together".into()),
    };
    let value = match positionals.as_slice() {
        ["snapshot", "list"] => serde_json::to_value(manager.list()?)?,
        ["snapshot", "show", id] => {
            serde_json::to_value(manager.inspect(&SnapshotId::parse(id)?)?)?
        }
        ["snapshot", "create"] => {
            let reason = match flags.get("--reason").copied().unwrap_or("manual") {
                "manual" => Reason::Manual,
                "pre-update" => Reason::PreUpdate,
                "post-update" => Reason::PostUpdate,
                _ => return Err("invalid snapshot reason".into()),
            };
            if flags.contains_key("--dry-run") {
                serde_json::to_value(manager.plan_create()?)?
            } else {
                serde_json::to_value(
                    manager.create(reason, flags.get("--transaction").map(|s| (*s).into()))?,
                )?
            }
        }
        ["snapshot", "mark", id, state] => {
            let health = match *state {
                "unknown" => Health::Unknown,
                "candidate" => Health::Candidate,
                "known-good" => Health::KnownGood,
                "bad" => Health::Bad,
                _ => return Err("invalid health state".into()),
            };
            serde_json::to_value(manager.mark(
                &SnapshotId::parse(id)?,
                health,
                flags.get("--evidence").ok_or("--evidence required")?,
            )?)?
        }
        ["snapshot", "delete", id] => {
            manager.delete(&SnapshotId::parse(id)?)?;
            serde_json::json!({"deleted":id})
        }
        ["rollback", id] => {
            let id = SnapshotId::parse(id)?;
            match (
                flags.contains_key("--dry-run"),
                flags.contains_key("--execute"),
            ) {
                (true, false) => serde_json::to_value(manager.plan_rollback(&id)?)?,
                (false, true) => serde_json::to_value(manager.rollback(&id)?)?,
                _ => return Err("select exactly one of --dry-run or --execute".into()),
            }
        }
        _ => unreachable!(),
    };
    if flags.contains_key("--json") {
        println!("{}", serde_json::to_string_pretty(&value)?);
    } else {
        print_value("", &value);
    }
    Ok(())
}

fn print_value(prefix: &str, value: &serde_json::Value) {
    match value {
        serde_json::Value::Object(map) => {
            for (key, value) in map {
                print_value(&format!("{prefix}{key}."), value);
            }
        }
        serde_json::Value::Array(values) => {
            if values.is_empty() {
                println!("{}: none", prefix.trim_end_matches('.'));
            }
            for (index, value) in values.iter().enumerate() {
                print_value(&format!("{prefix}{index}."), value);
            }
        }
        serde_json::Value::String(text) => println!("{}: {text}", prefix.trim_end_matches('.')),
        _ => println!("{}: {value}", prefix.trim_end_matches('.')),
    }
}
