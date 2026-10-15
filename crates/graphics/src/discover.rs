use crate::{diagnose, issue, parse_probe, Architecture, GraphicsReport, Icd, Observations, State};
use serde::Deserialize;
use std::{
    collections::BTreeMap,
    fs,
    io::{self, Read},
    path::Path,
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

fn read(path: &Path) -> io::Result<String> {
    let mut text = String::new();
    fs::File::open(path)?
        .take(1024 * 1024 + 1)
        .read_to_string(&mut text)?;
    if text.len() > 1024 * 1024 {
        return Err(io::Error::other("file exceeds diagnostic limit"));
    }
    Ok(text)
}

fn optional(root: &Path, path: &str) -> Option<String> {
    read(&root.join(path))
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

pub(crate) fn elf(path: &Path, bits: u8) -> State {
    let mut header = [0u8; 20];
    match fs::File::open(path).and_then(|mut f| f.read_exact(&mut header)) {
        Ok(()) => {
            let machine = u16::from_le_bytes([header[18], header[19]]);
            if header[..4] == *b"\x7fELF"
                && header[5] == 1
                && ((bits == 64 && header[4] == 2 && machine == 62)
                    || (bits == 32 && header[4] == 1 && machine == 3))
            {
                State::Present
            } else {
                State::Failed
            }
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => State::Absent,
        Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => State::Failed,
        Err(_) => State::Unknown,
    }
}

#[derive(Deserialize)]
struct Manifest {
    #[serde(rename = "ICD")]
    icd: Driver,
}
#[derive(Deserialize)]
struct Driver {
    library_path: String,
    api_version: Option<String>,
    library_arch: Option<String>,
}

fn architecture(root: &Path, bits: u8, raw: &mut Observations) -> Architecture {
    let lib = if bits == 64 { "usr/lib" } else { "usr/lib32" };
    let mut result = Architecture::unknown(bits);
    result.loader = elf(&root.join(lib).join("libvulkan.so.1"), bits);
    for directory in ["etc/vulkan/icd.d", "usr/share/vulkan/icd.d"] {
        let entries = match fs::read_dir(root.join(directory)) {
            Ok(entries) => entries,
            Err(e) if e.kind() == io::ErrorKind::NotFound => continue,
            Err(_) => {
                issue(
                    &mut raw.issues,
                    "icd_directory_unavailable",
                    None,
                    directory,
                );
                continue;
            }
        };
        for entry in entries {
            let Ok(entry) = entry else {
                issue(&mut raw.issues, "icd_entry_unavailable", None, directory);
                continue;
            };
            let path = entry.path();
            if path.extension().is_none_or(|e| e != "json") {
                continue;
            }
            let manifest = match read(&path)
                .ok()
                .and_then(|s| serde_json::from_str::<Manifest>(&s).ok())
            {
                Some(m) if !m.icd.library_path.is_empty() => m,
                _ => {
                    issue(
                        &mut raw.issues,
                        "invalid_icd",
                        None,
                        &path.display().to_string(),
                    );
                    continue;
                }
            };
            let driver = manifest.icd;
            if driver
                .library_arch
                .as_deref()
                .is_some_and(|a| a != "32" && a != "64")
            {
                issue(
                    &mut raw.issues,
                    "invalid_icd_architecture",
                    None,
                    &path.display().to_string(),
                );
                continue;
            }
            if driver
                .library_arch
                .as_deref()
                .is_some_and(|a| a != bits.to_string())
            {
                continue;
            }
            let library = Path::new(&driver.library_path);
            // Resolve the installed Arch layout only; runtime loader search and user overrides are separate evidence.
            let resolved = if library.is_absolute() {
                root.join(library.strip_prefix("/").unwrap_or(library))
            } else if driver.library_path.contains('/') {
                path.parent().unwrap().join(library)
            } else {
                root.join(lib).join(library)
            };
            let state = elf(&resolved, bits);
            result.icds.push(Icd {
                manifest: path
                    .strip_prefix(root)
                    .unwrap_or(&path)
                    .display()
                    .to_string(),
                library: driver.library_path,
                api_version: driver.api_version,
                architecture: (state == State::Present).then_some(bits),
                state,
            });
        }
    }
    result.icds.sort_by(|a, b| a.manifest.cmp(&b.manifest));
    result
}

pub(crate) fn packages(root: &Path) -> Result<BTreeMap<String, String>, String> {
    let entries = fs::read_dir(root.join("var/lib/pacman/local")).map_err(|e| e.to_string())?;
    let mut packages = BTreeMap::new();
    for entry in entries {
        let entry = entry.map_err(|e| e.to_string())?;
        if !entry.file_type().map_err(|e| e.to_string())?.is_dir() {
            continue;
        }
        let text = read(&entry.path().join("desc")).map_err(|e| e.to_string())?;
        let field = |key: &str| -> Result<String, String> {
            let lines: Vec<_> = text.lines().collect();
            let values: Vec<_> = lines
                .windows(2)
                .filter(|w| w[0] == key)
                .map(|w| w[1])
                .collect();
            if values.len() != 1 || values[0].is_empty() {
                return Err("malformed pacman record".into());
            }
            Ok(values[0].into())
        };
        let name = field("%NAME%")?;
        if packages.insert(name, field("%VERSION%")?).is_some() {
            return Err("duplicate pacman package".into());
        }
    }
    Ok(packages)
}

/// Collect file evidence from a root without subprocesses, PCI rescanning or writes.
pub fn discover(root: &Path) -> Observations {
    let mut raw = Observations::default();
    match packages(root) {
        Ok(packages) => raw.packages = Some(packages),
        Err(error) => issue(
            &mut raw.issues,
            "package_database_unavailable",
            None,
            &error,
        ),
    }
    raw.native = Some(architecture(root, 64, &mut raw));
    raw.compat32 = Some(architecture(root, 32, &mut raw));
    raw.kernel = optional(root, "proc/sys/kernel/osrelease");
    raw.nvidia_loaded_version = optional(root, "sys/module/nvidia/version");
    raw.nvidia_modeset =
        optional(root, "sys/module/nvidia_drm/parameters/modeset").and_then(|s| match s.as_str() {
            "Y" | "1" => Some(true),
            "N" | "0" => Some(false),
            _ => None,
        });
    raw
}

// Driver calls can hang. Drain bounded stdout concurrently and kill the child on timeout.
fn command(program: &str, args: &[&str], inherit: bool) -> Result<Vec<u8>, String> {
    let mut command = Command::new(program);
    command
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    if !inherit {
        command.env_clear().env("PATH", "/usr/bin:/bin");
    }
    command.env("LC_ALL", "C");
    let mut child = command.spawn().map_err(|e| e.to_string())?;
    let stdout = child.stdout.take().ok_or("missing stdout")?;
    let reader = thread::spawn(move || {
        let mut data = Vec::new();
        stdout
            .take(1024 * 1024 + 1)
            .read_to_end(&mut data)
            .map(|_| data)
    });
    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) if start.elapsed() < Duration::from_secs(20) => {
                thread::sleep(Duration::from_millis(20))
            }
            result => {
                let _ = child.kill();
                let _ = child.wait();
                break Err(result
                    .err()
                    .map_or("probe timed out".into(), |e| e.to_string()));
            }
        }
    };
    let output = reader
        .join()
        .map_err(|_| "probe reader failed")?
        .map_err(|e| e.to_string())?;
    if !status?.success() || output.len() > 1024 * 1024 {
        return Err("probe failed, refused, or exceeded output limit".into());
    }
    Ok(output)
}

/// Runtime probes are explicit and unprivileged; no configuration or package operations.
pub fn probe(runtime: bool) -> GraphicsReport {
    let hardware = distro_hardware::probe();
    let mut raw = discover(Path::new("/"));
    for problem in &hardware.issues {
        issue(&mut raw.issues, "hardware_probe", None, &problem.message);
    }
    raw.session_type = std::env::var("XDG_SESSION_TYPE")
        .ok()
        .filter(|s| matches!(s.as_str(), "wayland" | "x11"));
    for name in [
        "VK_DRIVER_FILES",
        "VK_ICD_FILENAMES",
        "VK_ADD_DRIVER_FILES",
        "VK_LOADER_DRIVERS_SELECT",
        "VK_LOADER_DRIVERS_DISABLE",
        "VK_LAYER_PATH",
        "VK_INSTANCE_LAYERS",
        "DRI_PRIME",
        "MESA_VK_DEVICE_SELECT",
        "LIBGL_ALWAYS_SOFTWARE",
        "GALLIUM_DRIVER",
        "__NV_PRIME_RENDER_OFFLOAD",
        "__VK_LAYER_NV_optimus",
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
    ] {
        if std::env::var_os(name).is_some() {
            raw.overrides.push(name.into());
        }
    }
    if cfg!(target_os = "linux") && raw.nvidia_loaded_version.is_some() {
        let value = |field| {
            command("/usr/bin/modinfo", &["-F", field, "nvidia"], false)
                .ok()
                .and_then(|b| String::from_utf8(b).ok())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        };
        raw.nvidia_disk_version = value("version");
        raw.nvidia_vermagic = value("vermagic");
        raw.nvidia_module_signer = value("signer");
    }
    if runtime {
        for (bits, executable) in [
            (64, "/usr/lib/distroctl/graphics-probe64"),
            (32, "/usr/lib/distroctl/graphics-probe32"),
        ] {
            match command(executable, &[], true).and_then(|bytes| parse_probe(&bytes, bits)) {
                Ok(probe) => {
                    let arch = if bits == 64 {
                        &mut raw.native
                    } else {
                        &mut raw.compat32
                    };
                    arch.as_mut().unwrap().apply_probe(probe);
                }
                Err(error) => {
                    let arch = if bits == 64 {
                        &mut raw.native
                    } else {
                        &mut raw.compat32
                    };
                    arch.as_mut().unwrap().enumeration = State::Unknown;
                    issue(
                        &mut raw.issues,
                        "runtime_probe_unavailable",
                        None,
                        &format!("{bits}-bit: {error}"),
                    );
                }
            }
        }
    }
    diagnose(hardware, raw)
}
