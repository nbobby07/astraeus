use distro_hardware::Gpu;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug, Serialize)]
pub struct DriverSelection {
    pub bundle: Option<String>,
    pub kernel_drivers: Vec<String>,
    pub userspace: Option<String>,
    pub icd_library: Option<String>,
    pub reason: Option<String>,
    pub alternative: Option<String>,
}

#[derive(Deserialize)]
struct Bundles {
    base: Vec<String>,
    bundles: BTreeMap<String, Vec<String>>,
}

pub fn bundle_packages(bundle: Option<&str>) -> Vec<String> {
    let manifest: Bundles =
        serde_json::from_str(include_str!("../../../distro/graphics/bundles.json"))
            .expect("compiled graphics manifest");
    let mut packages: BTreeSet<_> = manifest.base.into_iter().collect();
    if let Some(extra) = bundle.and_then(|b| manifest.bundles.get(b)) {
        packages.extend(extra.iter().cloned());
    }
    packages.into_iter().collect()
}

#[derive(Deserialize)]
pub(crate) struct PackageLock {
    pub archive_date: String,
    pub packages: BTreeMap<String, Package>,
}
#[derive(Deserialize)]
pub(crate) struct Package {
    pub version: String,
}
pub(crate) fn package_lock() -> PackageLock {
    serde_json::from_str(include_str!("../../../distro/graphics/packages.lock.json"))
        .expect("compiled package lock")
}

#[derive(Deserialize)]
struct NvidiaSupport {
    device_ids: Vec<String>,
}

pub fn select_driver(gpu: &Gpu) -> DriverSelection {
    let supported: NvidiaSupport =
        serde_json::from_str(include_str!("../../../distro/graphics/nvidia-open.json"))
            .expect("compiled NVIDIA support list");
    let modern = gpu
        .device_id
        .as_ref()
        .is_some_and(|id| supported.device_ids.contains(id));
    let (bundle, drivers, userspace, library, reason, alternative) = match gpu.vendor_id.as_deref() {
        Some("0x1002") if gpu.driver.as_deref() == Some("radeon") => (None, vec!["radeon"], Some("Mesa legacy Radeon"), None, Some("Legacy radeon binding: RADV requires amdgpu; no automatic kernel-driver switch"), None),
        Some("0x1002") => (Some("amd"), vec!["amdgpu"], Some("Mesa RadeonSI / RADV"), Some("libvulkan_radeon.so"), None, None),
        Some("0x8086") => (Some("intel"), vec!["i915", "xe"], Some("Mesa Iris/Crocus / ANV"), Some("libvulkan_intel.so"), None, None),
        Some("0x10de") if gpu.driver.as_deref() == Some("nouveau") => (Some("nouveau"), vec!["nouveau"], Some("Mesa Nouveau / NVK"), Some("libvulkan_nouveau.so"), Some("Preserving nouveau; NVK generation/API support must be tested. Driver-family changes require explicit approval and transaction support"), modern.then_some("nvidia-open")),
        Some("0x10de") if modern => (Some("nvidia-open"), vec!["nvidia"], Some("NVIDIA 615.71.09 proprietary userspace"), Some("libGLX_nvidia.so"), Some("Listed by NVIDIA 615.71.09 for open modules; activation refused pending module trust, kernel compatibility and transaction integration"), Some("nouveau")),
        Some("0x10de") => (None, vec!["nouveau", "nvidia"], None, None, Some("Device absent from pinned generic open-module support list. Older, subsystem-specific and unknown devices require review; no legacy driver or automatic family switch"), Some("nouveau")),
        Some("0x1af4") => (Some("virtio"), vec!["virtio_gpu"], Some("Mesa VirGL / Venus"), Some("libvulkan_virtio.so"), Some("Guest Vulkan depends on host Venus support; virtual device enumeration is not proof of physical acceleration"), None),
        Some("0x1234" | "0x15ad" | "0x1414" | "0x1b36") => (None, vec!["bochs-drm", "vmwgfx", "hyperv_drm", "qxl"], Some("Mesa virtual display"), None, Some("Display-only/virtual GPU: Vulkan hardware support is unknown; software fallback is not acceleration"), None),
        _ => (None, vec![], None, None, Some("Unknown GPU: retain the existing binding; no vendor driver selected"), None),
    };
    DriverSelection {
        bundle: bundle.map(str::to_string),
        kernel_drivers: drivers.into_iter().map(str::to_string).collect(),
        userspace: userspace.map(str::to_string),
        icd_library: library.map(str::to_string),
        reason: reason.map(str::to_string),
        alternative: alternative.map(str::to_string),
    }
}
