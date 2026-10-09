//! Read-only graphics policy and evidence. Package presence never proves rendering.
use distro_hardware::{Gpu, Hardware};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

mod discover;
pub use discover::{discover, probe};
mod policy;
pub use policy::{bundle_packages, select_driver, DriverSelection};

pub const SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    Present,
    Absent,
    Passed,
    Failed,
    Unsupported,
    #[default]
    Unknown,
    Untested,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Issue {
    pub code: String,
    pub gpu: Option<usize>,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Icd {
    pub manifest: String,
    pub library: String,
    pub api_version: Option<String>,
    pub architecture: Option<u8>,
    pub state: State,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VulkanDevice {
    pub name: String,
    pub vendor_id: u32,
    pub device_id: u32,
    pub device_type: u32,
    pub api_version: u32,
    pub driver_version: u32,
    pub driver_name: Option<String>,
    pub driver_info: Option<String>,
    pub driver_id: Option<u32>,
    pub pci_address: Option<String>,
    pub software: bool,
    pub rendering: State,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VulkanProbe {
    pub schema_version: u32,
    pub architecture: u8,
    pub loader_version: Option<u32>,
    pub status: State,
    pub devices: Vec<VulkanDevice>,
}

/// Parse only helper protocol v1, never human-readable vulkaninfo output.
pub fn parse_probe(bytes: &[u8], architecture: u8) -> Result<VulkanProbe, String> {
    if bytes.len() > 1024 * 1024 {
        return Err("Vulkan probe output exceeds limit".into());
    }
    let mut probe: VulkanProbe = serde_json::from_slice(bytes).map_err(|e| e.to_string())?;
    if probe.schema_version != 1
        || !matches!(architecture, 32 | 64)
        || probe.architecture != architecture
        || probe.devices.len() > 64
    {
        return Err("Vulkan probe schema, architecture or device count mismatch".into());
    }
    if !matches!(
        probe.status,
        State::Passed | State::Failed | State::Absent | State::Unsupported
    ) || (probe.status != State::Passed && !probe.devices.is_empty())
    {
        return Err("inconsistent Vulkan probe status".into());
    }
    for device in &mut probe.devices {
        if !matches!(
            device.rendering,
            State::Passed | State::Failed | State::Unsupported | State::Untested
        ) || device.device_type > 4
        {
            return Err("invalid Vulkan device evidence".into());
        }
        // CPU and Mesa llvmpipe are software even if a malformed producer says otherwise.
        device.software |= device.device_type == 4 || device.driver_id == Some(13);
    }
    Ok(probe)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Architecture {
    pub bits: u8,
    pub loader: State,
    pub icds: Vec<Icd>,
    pub enumeration: State,
    pub loader_version: Option<u32>,
    pub devices: Vec<VulkanDevice>,
}

impl Architecture {
    pub fn unknown(bits: u8) -> Self {
        Self {
            bits,
            loader: State::Unknown,
            icds: Vec::new(),
            enumeration: State::Untested,
            loader_version: None,
            devices: Vec::new(),
        }
    }
    pub fn apply_probe(&mut self, probe: VulkanProbe) {
        self.enumeration = probe.status;
        self.loader_version = probe.loader_version;
        self.devices = probe.devices;
    }
}

#[derive(Debug, Default)]
pub struct Observations {
    pub packages: Option<BTreeMap<String, String>>,
    pub native: Option<Architecture>,
    pub compat32: Option<Architecture>,
    pub session_type: Option<String>,
    pub kernel: Option<String>,
    pub nvidia_loaded_version: Option<String>,
    pub nvidia_disk_version: Option<String>,
    pub nvidia_vermagic: Option<String>,
    pub nvidia_modeset: Option<bool>,
    pub nvidia_module_signer: Option<String>,
    pub overrides: Vec<String>,
    pub issues: Vec<Issue>,
}

#[derive(Debug, Serialize)]
pub struct GraphicsGpu {
    pub hardware: Gpu,
    pub selection: DriverSelection,
    pub required_packages: Vec<String>,
    pub missing_packages: Option<Vec<String>>,
    pub firmware_package: State,
    pub firmware_loaded: State,
    pub native_devices: Vec<usize>,
    pub compat32_devices: Vec<usize>,
    pub form_factor: Option<String>,
    pub wayland: State,
    pub rendering: State,
}

#[derive(Debug, Serialize)]
pub struct Wayland {
    pub session_type: Option<String>,
    pub active: Option<bool>,
    pub compositor_gpu: Option<String>,
    pub vrr: State,
    pub hdr: State,
}

#[derive(Debug, Serialize)]
pub struct NvidiaModule {
    pub loaded_version: Option<String>,
    pub disk_version: Option<String>,
    pub vermagic: Option<String>,
    pub modeset: Option<bool>,
    pub signer: Option<String>,
    pub trusted: State,
    pub activation: State,
}

#[derive(Debug, Serialize)]
pub struct GraphicsReport {
    pub schema_version: u32,
    pub archive_date: String,
    pub gpus: Option<Vec<GraphicsGpu>>,
    pub boot_gpu: Option<usize>,
    pub multi_gpu: Option<bool>,
    pub native: Architecture,
    pub compat32: Architecture,
    pub wayland: Wayland,
    pub opengl_renderer: Option<String>,
    pub nvidia_module: NvidiaModule,
    pub packages: Option<BTreeMap<String, String>>,
    pub required_packages: Vec<String>,
    pub environment_overrides: Vec<String>,
    pub activation: State,
    pub activation_reason: String,
    pub issues: Vec<Issue>,
}

fn issue(issues: &mut Vec<Issue>, code: &str, gpu: Option<usize>, message: &str) {
    issues.push(Issue {
        code: code.into(),
        gpu,
        message: message.into(),
    });
}

fn matches(gpu: &Gpu, all: &[Gpu], runtime: &VulkanDevice) -> bool {
    if runtime.software {
        return false;
    }
    if let Some(address) = &runtime.pci_address {
        return gpu.pci_address.as_ref() == Some(address);
    }
    let vendor = format!("0x{:04x}", runtime.vendor_id);
    let device = format!("0x{:04x}", runtime.device_id);
    let same =
        |g: &&Gpu| g.vendor_id.as_ref() == Some(&vendor) && g.device_id.as_ref() == Some(&device);
    same(&gpu) && all.iter().filter(same).count() == 1
}

pub fn diagnose(hardware: Hardware, mut raw: Observations) -> GraphicsReport {
    let native = raw
        .native
        .take()
        .unwrap_or_else(|| Architecture::unknown(64));
    let compat32 = raw
        .compat32
        .take()
        .unwrap_or_else(|| Architecture::unknown(32));
    let mut issues = raw.issues;
    for a in [&native, &compat32] {
        if a.loader == State::Absent {
            issue(
                &mut issues,
                "missing_loader",
                None,
                &format!("{}-bit Vulkan loader is absent", a.bits),
            );
        }
        if a.loader == State::Failed {
            issue(
                &mut issues,
                "incorrect_architecture",
                None,
                &format!(
                    "{}-bit Vulkan loader has an invalid ELF architecture",
                    a.bits
                ),
            );
        }
        if a.enumeration == State::Passed && a.devices.iter().all(|d| d.software) {
            issue(
                &mut issues,
                "no_hardware_vulkan_device",
                None,
                &format!("{}-bit enumeration found no non-software device", a.bits),
            );
        }
        if a.enumeration == State::Failed {
            issue(
                &mut issues,
                "enumeration_failed",
                None,
                &format!("{}-bit Vulkan enumeration failed", a.bits),
            );
        }
        if a.enumeration == State::Absent {
            issue(
                &mut issues,
                "runtime_loader_unavailable",
                None,
                &format!(
                    "{}-bit loader could not be opened by the runtime probe",
                    a.bits
                ),
            );
        }
        if a.enumeration == State::Unsupported {
            issue(
                &mut issues,
                "runtime_probe_unsupported",
                None,
                &format!(
                    "{}-bit probe requires an ordinary user and Vulkan 1.1 entry points",
                    a.bits
                ),
            );
        }
        if a.devices.iter().any(|d| d.rendering == State::Failed) {
            issue(
                &mut issues,
                "rendering_failed",
                None,
                &format!(
                    "{}-bit offscreen rendering/readback failed on at least one device",
                    a.bits
                ),
            );
        }
    }
    if !raw.overrides.is_empty() {
        issue(&mut issues, "environment_override", None, "Runtime results reflect this process's graphics overrides, not an application or system default");
    }
    let lock = policy::package_lock();
    if let Some(packages) = &raw.packages {
        for (name, version) in packages {
            if let Some(expected) = lock.packages.get(name) {
                if version != &expected.version {
                    issue(
                        &mut issues,
                        "unsupported_package_version",
                        None,
                        &format!("{name} {version} differs from pinned {}", expected.version),
                    );
                }
            }
        }
        for (a, b) in [
            ("mesa", "lib32-mesa"),
            ("vulkan-radeon", "lib32-vulkan-radeon"),
            ("vulkan-intel", "lib32-vulkan-intel"),
            ("vulkan-nouveau", "lib32-vulkan-nouveau"),
            ("nvidia-utils", "lib32-nvidia-utils"),
        ] {
            if let (Some(left), Some(right)) = (packages.get(a), packages.get(b)) {
                if upstream_version(left) != upstream_version(right) {
                    issue(
                        &mut issues,
                        "inconsistent_package_state",
                        None,
                        &format!("{a} and {b} have different upstream versions"),
                    );
                }
            }
        }
    }
    let boot_gpu = hardware.gpus.as_ref().and_then(|gpus| {
        let candidates: Vec<_> = gpus
            .iter()
            .enumerate()
            .filter(|(_, g)| g.boot_vga == Some(true))
            .collect();
        (candidates.len() == 1).then(|| candidates[0].0)
    });
    let mut required: BTreeSet<_> = bundle_packages(None).into_iter().collect();
    let mappings = hardware.gpus.as_ref().map(|gpus| {
        gpus.iter()
            .map(|gpu| {
                let find = |a: &Architecture| {
                    a.devices
                        .iter()
                        .enumerate()
                        .filter(|(_, d)| matches(gpu, gpus, d))
                        .map(|(i, _)| i)
                        .collect::<Vec<_>>()
                };
                (find(&native), find(&compat32))
            })
            .collect::<Vec<_>>()
    });
    let gpus = hardware.gpus.map(|gpus| {
        let mut observations = Vec::new();
        for (index, gpu) in gpus.into_iter().enumerate() {
            let selection = select_driver(&gpu);
            if let Some(problem) = &selection.reason {
                issue(&mut issues, "driver_selection", Some(index), problem);
            }
            let required_packages = bundle_packages(selection.bundle.as_deref());
            required.extend(required_packages.iter().cloned());
            let missing_packages = raw.packages.as_ref().map(|packages| {
                required_packages.iter().filter(|p| !packages.contains_key(*p)).cloned().collect::<Vec<_>>()
            });
            if missing_packages.as_ref().is_some_and(|p| !p.is_empty()) {
                issue(&mut issues, "missing_packages", Some(index), "Selected graphics bundle is incomplete; installation does not prove runtime readiness");
            }
            let firmware = required_packages.iter().find(|p| p.starts_with("linux-firmware-"));
            let firmware_package = firmware.and_then(|p| {
                raw.packages.as_ref().map(|pkgs| {
                    if pkgs.contains_key(p) { State::Present } else { State::Absent }
                })
            }).unwrap_or(State::Unknown);
            if firmware_package == State::Absent {
                issue(&mut issues, "missing_firmware", Some(index), "Selected firmware package is absent; loaded firmware is unknown");
            }
            if let Some(driver) = gpu.driver.as_deref() {
                if !selection.kernel_drivers.is_empty() && !selection.kernel_drivers.iter().any(|d| d == driver) {
                    issue(&mut issues, "wrong_driver", Some(index), "Observed kernel binding does not match the selected candidate stack");
                }
            } else {
                issue(&mut issues, "kernel_driver_unknown", Some(index), "No kernel driver binding was observed");
            }
            let (native_devices, compat32_devices) = mappings.as_ref().unwrap()[index].clone();
            if native.enumeration == State::Passed && native_devices.is_empty() {
                issue(&mut issues, "gpu_not_enumerated", Some(index), "No uniquely matched native Vulkan device; another GPU or software device may be rendering");
            }
            if compat32.enumeration == State::Passed && compat32_devices.is_empty() {
                issue(&mut issues, "gpu_not_enumerated_32", Some(index), "No uniquely matched 32-bit Vulkan device");
            }
            for (arch, suffix) in [(&native, ""), (&compat32, "_32")] {
                if let Some(library) = selection.icd_library.as_deref() {
                    if arch.loader != State::Unknown && !arch.icds.iter().any(|i| {
                        i.library.contains(library) && i.state == State::Present && i.architecture == Some(arch.bits)
                    }) {
                        issue(&mut issues, &format!("missing_icd{suffix}"), Some(index), &format!("No usable {}-bit system ICD for selected driver; runtime overrides may differ", arch.bits));
                    }
                }
            }
            let types: BTreeSet<_> = native_devices.iter().map(|i| native.devices[*i].device_type).collect();
            let form_factor = if types.len() == 1 {
                match types.first() {
                    Some(1) => Some("integrated".into()),
                    Some(2) => Some("discrete".into()),
                    Some(3) => Some("virtual".into()),
                    _ => None,
                }
            } else { None };
            let rendering = if native_devices.iter().any(|i| native.devices[*i].rendering == State::Failed) {
                State::Failed
            } else if native_devices.len() == 1 {
                native.devices[native_devices[0]].rendering
            } else { State::Untested };
            let wayland = if gpu.driver.as_deref() == Some("nvidia") && raw.nvidia_modeset == Some(false) {
                State::Failed
            } else { State::Unknown };
            observations.push(GraphicsGpu {
                hardware: gpu, selection, required_packages, missing_packages,
                firmware_package, firmware_loaded: State::Unknown,
                native_devices, compat32_devices, form_factor, wayland, rendering,
            });
        }
        observations
    });
    if gpus.as_ref().is_some_and(|gs| {
        gs.iter()
            .any(|g| g.hardware.driver.as_deref() == Some("nvidia"))
    }) {
        let utils = raw.packages.as_ref().and_then(|p| p.get("nvidia-utils"));
        if let (Some(loaded), Some(utils)) = (&raw.nvidia_loaded_version, utils) {
            if loaded != upstream_version(utils) {
                issue(
                    &mut issues,
                    "nvidia_module_userspace_mismatch",
                    None,
                    "Loaded NVIDIA module and installed userspace versions differ",
                );
            }
        }
        if let (Some(disk), Some(loaded)) = (&raw.nvidia_disk_version, &raw.nvidia_loaded_version) {
            if disk != loaded {
                issue(
                    &mut issues,
                    "nvidia_module_disk_mismatch",
                    None,
                    "Loaded and on-disk NVIDIA modules differ; a reboot may still require recovery",
                );
            }
        }
        if let (Some(vermagic), Some(kernel)) = (&raw.nvidia_vermagic, &raw.kernel) {
            if vermagic.split_whitespace().next() != Some(kernel.as_str()) {
                issue(
                    &mut issues,
                    "nvidia_kernel_mismatch",
                    None,
                    "On-disk NVIDIA module vermagic does not match the running kernel",
                );
            }
        }
        if raw.nvidia_modeset != Some(true) {
            issue(
                &mut issues,
                "nvidia_kms_unconfirmed",
                None,
                "NVIDIA DRM modeset must be enabled and verified for Plasma Wayland",
            );
        }
        issue(&mut issues, "nvidia_module_trust_unverified", None, "UKI signing does not authorize external kernel modules; activation is unsupported until module signing and key trust are integrated");
    }
    GraphicsReport { schema_version: SCHEMA_VERSION, archive_date: lock.archive_date,
        multi_gpu: gpus.as_ref().map(|g| g.len() > 1), gpus, boot_gpu, native, compat32,
        wayland: Wayland { active: raw.session_type.as_deref().map(|s| s == "wayland"), session_type: raw.session_type, compositor_gpu: None, vrr: State::Unknown, hdr: State::Unknown },
        nvidia_module: NvidiaModule { loaded_version: raw.nvidia_loaded_version, disk_version: raw.nvidia_disk_version, vermagic: raw.nvidia_vermagic, modeset: raw.nvidia_modeset, signer: raw.nvidia_module_signer, trusted: State::Unknown, activation: State::Unsupported },
        opengl_renderer: None,
        packages: raw.packages, required_packages: required.into_iter().collect(), environment_overrides: raw.overrides,
        activation: State::Unsupported,
        activation_reason: "Read-only requirements. The current transaction adapter accepts system upgrades only, not install targets or driver-family changes. Use explicitly selected image bundles for initial installation; never run a separate pacman transaction.".into(), issues }
}

fn upstream_version(version: &str) -> &str {
    let version = version.split_once(':').map_or(version, |(_, v)| v);
    version.rsplit_once('-').map_or(version, |(v, _)| v)
}

/// Called by the existing transaction planner, before download or mutation.
pub fn validate_update(
    current: &BTreeMap<String, String>,
    candidate: &BTreeMap<String, String>,
) -> Result<(), String> {
    let nvidia = |name: &str| {
        name == "nvidia" || name.starts_with("nvidia-") || name == "lib32-nvidia-utils"
    };
    let nvidia_installed = current.keys().any(|n| nvidia(n));
    for name in current.keys().chain(candidate.keys()) {
        if current.get(name) != candidate.get(name)
            && (nvidia(name)
                || (nvidia_installed && matches!(name.as_str(), "linux" | "linux-headers")))
        {
            return Err("NVIDIA driver/kernel changes are unsupported until module signing, key trust and kernel ABI validation are integrated with retained boot generations; entire plan rejected".into());
        }
    }
    for (native, compat) in [
        ("mesa", "lib32-mesa"),
        ("vulkan-icd-loader", "lib32-vulkan-icd-loader"),
        ("vulkan-radeon", "lib32-vulkan-radeon"),
        ("vulkan-intel", "lib32-vulkan-intel"),
        ("vulkan-nouveau", "lib32-vulkan-nouveau"),
        ("vulkan-virtio", "lib32-vulkan-virtio"),
    ] {
        if let Some(compat_version) = candidate.get(compat) {
            if candidate
                .get(native)
                .is_none_or(|v| upstream_version(v) != upstream_version(compat_version))
            {
                return Err(format!("inconsistent graphics package state: {native} and {compat} must have matching upstream versions; entire plan rejected"));
            }
        }
    }
    Ok(())
}

pub fn format_report(report: &GraphicsReport) -> String {
    let mut text = String::from("Graphics\n");
    if let Some(gpus) = &report.gpus {
        for (i, gpu) in gpus.iter().enumerate() {
            text.push_str(&format!("\nGPU {i}: {} {}\n  Kernel driver: {}\n  Candidate stack: {}\n  Native Vulkan matches: {}\n  32-bit Vulkan matches: {}\n  Rendering: {:?}\n",
                gpu.hardware.vendor.as_deref().unwrap_or("unknown"), gpu.hardware.model.as_deref().or(gpu.hardware.device_id.as_deref()).unwrap_or("unknown"),
                gpu.hardware.driver.as_deref().unwrap_or("unknown"), gpu.selection.bundle.as_deref().unwrap_or("unsupported"),
                gpu.native_devices.len(), gpu.compat32_devices.len(), gpu.rendering));
        }
    } else {
        text.push_str("  GPU discovery unavailable\n");
    }
    text.push_str(&format!("\nVulkan enumeration: native {:?}, 32-bit {:?}\nWayland session: {:?}; VRR/HDR: unknown\nActivation: unsupported\n", report.native.enumeration, report.compat32.enumeration, report.wayland.active));
    text.push_str("\nIssues\n");
    if report.issues.is_empty() {
        text.push_str(
            "  None detected from collected evidence; untested capabilities remain untested.\n",
        );
    }
    for issue in &report.issues {
        text.push_str(&format!("  {}: {}\n", issue.code, issue.message));
    }
    text
}

#[cfg(test)]
mod tests;
