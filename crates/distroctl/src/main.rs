use distro_config::{parse_toml, BUNDLED};
use std::{env, fs, process::ExitCode};
mod snapshots;

const HELP: &str = "distroctl: system tools

Usage:
  distroctl info [--json]       Show metadata compiled into this binary
  distroctl status [--json]     Show observed system status
  distroctl hardware [--json]   Discover hardware without changing it
  distroctl validate <path>    Validate a project release TOML file
  distroctl snapshot --help   Snapshot commands and recovery usage
  distroctl rollback <id> --dry-run [--json]
  distroctl update --dry-run [--json]  Plan from existing sync databases
  distroctl update            Apply update with pre/post snapshots
  distroctl history [--json] [--database <path>]  Read transaction history
  distroctl confirm-boot [<transaction-id>]
  distroctl finalize-rollback <transaction-id>
  distroctl --version
  distroctl --help

Planning/history are read-only. Package mutation requires root and a snapshot backend.
Rollback execution requires offline recovery. Success requires a verified new boot.";

fn run(args: &[String]) -> Result<(), String> {
    if matches!(
        args.first().map(String::as_str),
        Some("snapshot" | "rollback")
    ) {
        return snapshots::run(args).map_err(|e| e.to_string());
    }
    match args
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>()
        .as_slice()
    {
        [] | ["--help"] | ["-h"] => println!("{HELP}"),
        ["--version"] => println!("distroctl {}", env!("CARGO_PKG_VERSION")),
        ["update", "--dry-run"]
        | ["update", "--dry-run", "--json"]
        | ["update", "--json", "--dry-run"] => {
            println!(
                "{}",
                distroctl::updates::dry_run(
                    &mut distro_transactions::pacman::Pacman::default(),
                    args.iter().any(|a| a == "--json")
                )?
            );
        }
        ["confirm-boot"] => distroctl::updates::confirm_boot(None, false)?,
        ["confirm-boot", id] | ["finalize-rollback", id] => {
            let id: i64 = id.parse().map_err(|_| "invalid transaction ID")?;
            if id <= 0 {
                return Err("invalid transaction ID".into());
            }
            distroctl::updates::confirm_boot(Some(id), args[0] == "finalize-rollback")?;
        }
        ["update"] => distroctl::updates::update()?,
        ["history"] | ["history", "--json"] => {
            print!(
                "{}",
                distroctl::updates::history(
                    std::path::Path::new(distro_transactions::HISTORY_PATH),
                    args.len() == 2
                )?
            );
        }
        ["history", "--database", path]
        | ["history", "--json", "--database", path]
        | ["history", "--database", path, "--json"] => {
            print!(
                "{}",
                distroctl::updates::history(
                    std::path::Path::new(path),
                    args.iter().any(|a| a == "--json")
                )?
            );
        }
        ["info"] | ["info", "--json"] => {
            let project = parse_toml(BUNDLED).map_err(|e| format!("bundled metadata: {e}"))?;
            project.validate()?;
            if args.len() == 2 {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&project).map_err(|e| e.to_string())?
                );
            } else {
                println!(
                    "{} {}\nArchitecture: {}\nArch snapshot: {}\nStage: Phase 1 (installation development)",
                    project.identity.name,
                    project.identity.version,
                    project.build.architecture,
                    project.build.archive_date
                );
            }
        }
        ["status"] | ["status", "--json"] => {
            let s = distroctl::status();
            if args.len() == 2 {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&s).map_err(|e| e.to_string())?
                );
            } else {
                print!("{}", distroctl::format_status(&s));
            }
        }
        ["hardware"] | ["hardware", "--json"] => {
            let hardware = distro_hardware::probe();
            if args.len() == 2 {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&hardware).map_err(|e| e.to_string())?
                );
            } else {
                print!("{}", distroctl::format_hardware(&hardware));
            }
        }
        ["validate", path] => {
            let text = fs::read_to_string(path).map_err(|e| format!("{path}: {e}"))?;
            let project = parse_toml(&text).map_err(|e| format!("{path}: {e}"))?;
            project.validate().map_err(|e| format!("{path}: {e}"))?;
            println!("{path}: valid project metadata");
        }
        _ => return Err(format!("unsupported arguments\n\n{HELP}")),
    }
    Ok(())
}

fn main() -> ExitCode {
    match run(&env::args().skip(1).collect::<Vec<_>>()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("distroctl: {error}");
            ExitCode::FAILURE
        }
    }
}
