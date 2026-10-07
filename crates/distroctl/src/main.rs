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
  distroctl --version
  distroctl --help

Snapshot mutations require root. Rollback execution requires offline recovery.";

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
