use distro_config::{parse_toml, BUNDLED};
use std::{env, fs, process::ExitCode};

const HELP: &str = "distroctl: read-only system tools

Usage:
  distroctl info [--json]       Show metadata compiled into this binary
  distroctl status [--json]     Show observed system status
  distroctl hardware [--json]   Discover hardware without changing it
  distroctl validate <path>    Validate a project release TOML file
  distroctl --version
  distroctl --help

These commands are read-only. Updates and rollback are not implemented.";

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
                use distroctl::known as k;
                println!("{}\n\nSystem\n  Version       {}\n  Channel       {}\n  Architecture  {}\n\nKernel\n  {}\n\nBoot\n  Firmware      {}\n  Bootloader    {}\n  Stub          {}\n  UKI path      {}\n\nFilesystem\n  Root          {}\n  Encryption    {}\n\nDesktop\n  {}\n  {}\n\nHardware\n  CPU           {}\n  Memory bytes  {}",
                    k(&s.name), k(&s.version), k(&s.channel), s.hardware.cpu.architecture,
                    k(&s.kernel), k(&s.boot.firmware), k(&s.boot.bootloader), k(&s.boot.stub), k(&s.boot.uki_path),
                    k(&s.filesystem.root_type), k(&s.filesystem.encryption), k(&s.desktop.name), k(&s.desktop.session_type), k(&s.hardware.cpu.model),
                    s.hardware.memory_bytes.map(|v| v.to_string()).unwrap_or_else(|| "unknown".into()));
                match s.hardware.gpus {
                    Some(gpus) => {
                        for gpu in gpus {
                            println!(
                                "  GPU           {} {}:{} ({})",
                                gpu.vendor, gpu.vendor_id, gpu.device_id, gpu.pci_address
                            );
                        }
                    }
                    None => println!("  GPU           unknown"),
                }
            }
        }
        ["hardware"] | ["hardware", "--json"] => {
            println!(
                "{}",
                serde_json::to_string_pretty(&distro_hardware::probe())
                    .map_err(|e| e.to_string())?
            );
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
