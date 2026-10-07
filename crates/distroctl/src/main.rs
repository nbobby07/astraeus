use distro_config::{parse_toml, BUNDLED};
use std::{env, fs, process::ExitCode};

const HELP: &str = "distroctl: Phase 0 build metadata tools

Usage:
  distroctl info [--json]       Show metadata compiled into this binary
  distroctl validate <path>    Validate a project release TOML file
  distroctl --version
  distroctl --help

These commands are read-only. System status, updates and installation are not implemented.";

fn run(args: &[String]) -> Result<(), String> {
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
                    "{} {}\nArchitecture: {}\nArch snapshot: {}\nStage: Phase 0 (bootstrap)",
                    project.identity.name,
                    project.identity.version,
                    project.build.architecture,
                    project.build.archive_date
                );
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
