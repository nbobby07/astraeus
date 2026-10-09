use super::*;
use distro_hardware::{normalize, RawGpu, RawHardware};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

fn hardware(entries: &[(&str, &str, Option<&str>)]) -> Hardware {
    normalize(RawHardware {
        pci: Some(
            entries
                .iter()
                .enumerate()
                .map(|(i, (vendor, device, driver))| RawGpu {
                    pci_address: Some(format!("0000:{i:02x}:00.0")),
                    vendor_id: Some((*vendor).into()),
                    device_id: Some((*device).into()),
                    driver: driver.map(str::to_string),
                    boot_vga: Some(i == 0),
                    ..Default::default()
                })
                .collect(),
        ),
        ..Default::default()
    })
}

fn amd() -> Hardware {
    hardware(&[("0x1002", "0x744c", Some("amdgpu"))])
}
fn installed() -> BTreeMap<String, String> {
    policy::package_lock()
        .packages
        .into_iter()
        .map(|(name, p)| (name, p.version))
        .collect()
}
fn report(hardware: Hardware) -> GraphicsReport {
    diagnose(
        hardware,
        Observations {
            packages: Some(installed()),
            ..Default::default()
        },
    )
}
fn has(report: &GraphicsReport, code: &str) -> bool {
    report.issues.iter().any(|i| i.code == code)
}
fn device(vendor: u32, device: u32, kind: u32) -> VulkanDevice {
    VulkanDevice {
        name: "fixture".into(),
        vendor_id: vendor,
        device_id: device,
        device_type: kind,
        api_version: (1 << 22) | (3 << 12),
        driver_version: 1,
        driver_name: Some("fixture".into()),
        driver_info: None,
        driver_id: None,
        pci_address: None,
        software: kind == 4,
        rendering: State::Passed,
    }
}

#[test]
fn vendor_policy_fixtures() {
    for (vendor, id, driver, bundle) in [
        ("0x1002", "0x744c", "amdgpu", Some("amd")),
        ("0x8086", "0x56a0", "xe", Some("intel")),
        ("0x8086", "0x9a49", "i915", Some("intel")),
        ("0x10de", "0x1e04", "nvidia", Some("nvidia-open")),
        ("0x10de", "0x2f04", "nvidia", Some("nvidia-open")),
        ("0x10de", "0x1e04", "nouveau", Some("nouveau")),
        ("0x10de", "0x1b80", "nvidia", None),
        ("0x1af4", "0x1050", "virtio_gpu", Some("virtio")),
        ("0x15ad", "0x0405", "vmwgfx", None),
        ("0x1234", "0x1111", "bochs-drm", None),
        ("0xffff", "0xffff", "other", None),
        ("0x1002", "0x6779", "radeon", None),
    ] {
        let r = report(hardware(&[(vendor, id, Some(driver))]));
        let g = &r.gpus.as_ref().unwrap()[0];
        assert_eq!(g.selection.bundle.as_deref(), bundle);
        assert_eq!(g.rendering, State::Untested);
        assert_eq!(r.activation, State::Unsupported);
        assert_eq!(g.firmware_loaded, State::Unknown);
    }
}

#[test]
fn hybrid_requirements_union_preserves_binding_and_does_not_guess_primary_renderer() {
    for integrated in ["0x8086", "0x1002"] {
        let r = report(hardware(&[
            (
                integrated,
                "0x0001",
                Some(if integrated == "0x8086" {
                    "i915"
                } else {
                    "amdgpu"
                }),
            ),
            ("0x10de", "0x1e04", Some("nouveau")),
        ]));
        assert_eq!(r.multi_gpu, Some(true));
        assert_eq!(r.boot_gpu, Some(0));
        assert!(r.wayland.compositor_gpu.is_none());
        assert!(r.required_packages.contains(&"lib32-vulkan-nouveau".into()));
        assert!(!r.required_packages.contains(&"nvidia-utils".into()));
    }
}

#[test]
fn missing_packages_firmware_and_unsupported_versions() {
    let mut p = installed();
    p.remove("linux-firmware-amdgpu");
    p.remove("lib32-vulkan-radeon");
    p.insert("mesa".into(), "0.1-1".into());
    let r = diagnose(
        amd(),
        Observations {
            packages: Some(p),
            ..Default::default()
        },
    );
    for code in [
        "missing_packages",
        "missing_firmware",
        "unsupported_package_version",
        "inconsistent_package_state",
    ] {
        assert!(has(&r, code), "{code}");
    }
}

#[test]
fn missing_loader_icd_and_32_bit_icd_are_distinct() {
    let mut native = Architecture::unknown(64);
    native.loader = State::Absent;
    let mut compat32 = Architecture::unknown(32);
    compat32.loader = State::Present;
    let r = diagnose(
        amd(),
        Observations {
            native: Some(native),
            compat32: Some(compat32),
            ..Default::default()
        },
    );
    for code in ["missing_loader", "missing_icd", "missing_icd_32"] {
        assert!(has(&r, code));
    }
}

#[test]
fn wrong_driver_and_nvidia_version_kernel_mismatches() {
    let r = report(hardware(&[("0x1002", "0x744c", Some("vfio-pci"))]));
    assert!(has(&r, "wrong_driver"));
    let r = diagnose(
        hardware(&[("0x10de", "0x1e04", Some("nvidia"))]),
        Observations {
            packages: Some(installed()),
            kernel: Some("7.2.7-arch1-1".into()),
            nvidia_loaded_version: Some("580.1".into()),
            nvidia_disk_version: Some("615.71.09".into()),
            nvidia_vermagic: Some("7.1.0 SMP".into()),
            nvidia_modeset: Some(false),
            ..Default::default()
        },
    );
    for code in [
        "nvidia_module_userspace_mismatch",
        "nvidia_module_disk_mismatch",
        "nvidia_kernel_mismatch",
        "nvidia_kms_unconfirmed",
        "nvidia_module_trust_unverified",
    ] {
        assert!(has(&r, code), "{code}");
    }
    assert_eq!(r.nvidia_module.trusted, State::Unknown);
    assert_eq!(r.gpus.unwrap()[0].wayland, State::Failed);
}

#[test]
fn software_success_is_not_gpu_rendering_success() {
    let mut native = Architecture::unknown(64);
    native.enumeration = State::Passed;
    native.devices.push(device(0x10005, 0, 4));
    let r = diagnose(
        amd(),
        Observations {
            native: Some(native),
            ..Default::default()
        },
    );
    assert!(has(&r, "no_hardware_vulkan_device"));
    assert!(has(&r, "gpu_not_enumerated"));
    assert_eq!(r.gpus.unwrap()[0].rendering, State::Untested);
}

#[test]
fn amd_integrated_discrete_are_matched_by_pci_and_render_failures_survive() {
    let mut native = Architecture::unknown(64);
    native.enumeration = State::Passed;
    let mut integrated = device(0x1002, 0x744c, 1);
    integrated.pci_address = Some("0000:00:00.0".into());
    let mut discrete = device(0x1002, 0x744c, 2);
    discrete.pci_address = Some("0000:01:00.0".into());
    discrete.rendering = State::Failed;
    native.devices = vec![integrated, discrete];
    let r = diagnose(
        hardware(&[
            ("0x1002", "0x744c", Some("amdgpu")),
            ("0x1002", "0x744c", Some("amdgpu")),
        ]),
        Observations {
            native: Some(native),
            ..Default::default()
        },
    );
    let g = r.gpus.unwrap();
    assert_eq!(g[0].form_factor.as_deref(), Some("integrated"));
    assert_eq!(g[1].form_factor.as_deref(), Some("discrete"));
    assert_eq!(g[0].rendering, State::Passed);
    assert_eq!(g[1].rendering, State::Failed);
}

#[test]
fn identical_gpu_ids_without_bus_evidence_are_ambiguous() {
    let mut native = Architecture::unknown(64);
    native.enumeration = State::Passed;
    native.devices.push(device(0x1002, 0x744c, 2));
    let r = diagnose(
        hardware(&[
            ("0x1002", "0x744c", Some("amdgpu")),
            ("0x1002", "0x744c", Some("amdgpu")),
        ]),
        Observations {
            native: Some(native),
            ..Default::default()
        },
    );
    assert!(r
        .gpus
        .unwrap()
        .iter()
        .all(|g| g.native_devices.is_empty() && g.rendering == State::Untested));
}

#[test]
fn probe_protocol_is_architecture_checked_and_rejects_unknown_fields() {
    let p = VulkanProbe {
        schema_version: 1,
        architecture: 32,
        loader_version: Some(1 << 22),
        status: State::Passed,
        devices: vec![device(0x10005, 0, 4)],
    };
    let bytes = serde_json::to_vec(&p).unwrap();
    assert!(parse_probe(&bytes, 64).is_err());
    assert!(parse_probe(&bytes, 32).unwrap().devices[0].software);
    let mut value = serde_json::to_value(p).unwrap();
    value["trusted"] = true.into();
    assert!(parse_probe(&serde_json::to_vec(&value).unwrap(), 32).is_err());
    assert!(parse_probe(b"not json", 32).is_err());
}

#[test]
fn json_readiness_keeps_unknown_and_untested() {
    let r = report(amd());
    let j = serde_json::to_value(&r).unwrap();
    assert_eq!(j["schema_version"], 1);
    assert_eq!(j["native"]["enumeration"], "untested");
    assert!(j["opengl_renderer"].is_null());
    assert_eq!(j["wayland"]["hdr"], "unknown");
    assert_eq!(j["gpus"][0]["firmware_loaded"], "unknown");
    assert_eq!(j["activation"], "unsupported");
    assert!(format_report(&r).contains("Rendering: Untested"));
}

#[test]
fn no_discovery_and_no_packages_remain_unknown() {
    let r = diagnose(normalize(RawHardware::default()), Observations::default());
    assert!(r.gpus.is_none());
    assert!(r.packages.is_none());
    assert!(r.multi_gpu.is_none());
    assert_eq!(r.native.loader, State::Unknown);
}

struct Tree(PathBuf);
impl Tree {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let p = std::env::temp_dir().join(format!(
            "astraeus-graphics-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&p).unwrap();
        Self(p)
    }
    fn write(&self, path: &str, bytes: impl AsRef<[u8]>) {
        let p = self.0.join(path);
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(p, bytes).unwrap();
    }
    fn elf(&self, path: &str, bits: u8) {
        let mut bytes = vec![0; 20];
        bytes[..4].copy_from_slice(b"\x7fELF");
        bytes[4] = if bits == 64 { 2 } else { 1 };
        bytes[5] = 1;
        bytes[18] = if bits == 64 { 62 } else { 3 };
        self.write(path, bytes);
    }
}
impl Drop for Tree {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn file_discovery_checks_elf_instead_of_icd_filename() {
    let t = Tree::new();
    t.elf("usr/lib/libvulkan.so.1", 64);
    t.elf("usr/lib32/libvulkan.so.1", 64);
    t.elf("usr/lib/libvulkan_radeon.so", 64);
    t.elf("usr/lib32/libvulkan_radeon.so", 32);
    t.write(
        "usr/share/vulkan/icd.d/ambiguous.json",
        r#"{"ICD":{"library_path":"libvulkan_radeon.so","api_version":"1.3.0"}}"#,
    );
    let raw = discover(&t.0);
    assert_eq!(raw.native.as_ref().unwrap().icds[0].architecture, Some(64));
    assert_eq!(
        raw.compat32.as_ref().unwrap().icds[0].architecture,
        Some(32)
    );
    let r = diagnose(amd(), raw);
    assert!(has(&r, "incorrect_architecture"));
}

#[test]
fn invalid_and_absent_icd_libraries_never_become_present() {
    let t = Tree::new();
    t.write("etc/vulkan/icd.d/broken.json", b"broken");
    t.write(
        "etc/vulkan/icd.d/missing.json",
        r#"{"ICD":{"library_path":"/usr/lib/missing.so"}}"#,
    );
    let raw = discover(&t.0);
    assert!(raw.issues.iter().any(|i| i.code == "invalid_icd"));
    assert_eq!(raw.native.unwrap().icds[0].state, State::Absent);
}

#[test]
fn duplicate_or_malformed_package_database_is_unavailable() {
    let t = Tree::new();
    t.write(
        "var/lib/pacman/local/mesa-a/desc",
        b"%NAME%\nmesa\n\n%VERSION%\n1-1\n",
    );
    assert_eq!(discover(&t.0).packages.unwrap()["mesa"], "1-1");
    t.write(
        "var/lib/pacman/local/mesa-b/desc",
        b"%NAME%\nmesa\n\n%VERSION%\n2-1\n",
    );
    assert!(discover(&t.0).packages.is_none());
}

#[test]
fn driver_update_guard_preserves_full_transaction_and_multilib_coherence() {
    let mut before = BTreeMap::from([
        ("mesa".into(), "1:26.2.3-2".into()),
        ("lib32-mesa".into(), "1:26.2.3-2".into()),
    ]);
    let mut after = before.clone();
    after.insert("mesa".into(), "1:26.3.0-1".into());
    assert!(validate_update(&before, &after).is_err());
    after.insert("lib32-mesa".into(), "1:26.3.0-2".into());
    assert!(validate_update(&before, &after).is_ok());
    before.insert("nvidia-utils".into(), "615.71.09-1".into());
    after = before.clone();
    after.insert("linux".into(), "7.3-1".into());
    assert!(validate_update(&before, &after)
        .unwrap_err()
        .contains("entire plan rejected"));
    after = before.clone();
    after.remove("nvidia-utils");
    assert!(validate_update(&before, &after).is_err());
    assert!(validate_update(&before, &before).is_ok());
}
