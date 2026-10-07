use super::*;
use std::sync::atomic::{AtomicUsize, Ordering};

static NEXT: AtomicUsize = AtomicUsize::new(0);
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "hardware-fixture-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }
    fn write(&self, name: &str, text: &str) {
        let path = self.0.join(name);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }
    fn dir(&self, name: &str) {
        fs::create_dir_all(self.0.join(name)).unwrap();
    }
    fn probe(&self) -> Hardware {
        normalize(discover(&self.0))
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn cpu_parsing_counts_socket_core_pairs_and_partial_topology() {
    let cpuinfo = "processor : 0\nvendor_id : AuthenticAMD\nmodel name : Ryzen\nphysical id : 0\ncore id : 0\n\nprocessor : 1\nphysical id : 0\ncore id : 0\n\nprocessor : 2\nphysical id : 1\ncore id : 0\n";
    let result = normalize(RawHardware {
        cpuinfo: Some(cpuinfo.into()),
        ..Default::default()
    });
    assert_eq!(result.cpu.vendor.as_deref(), Some("AuthenticAMD"));
    assert_eq!(result.cpu.model.as_deref(), Some("Ryzen"));
    assert_eq!(result.cpu.logical_count, Some(3));
    assert_eq!(result.cpu.physical_core_count, Some(2));
    assert_eq!(
        cpu_counts(&cpuinfo.replace("physical id : 1", "missing : 1")).1,
        None
    );
    assert_eq!(cpu_counts("processor : nope\ncore id : 0"), (None, None));
    assert_eq!(cpu_counts("processor : 0\nprocessor : 1"), (Some(2), None));
    assert_eq!(cpu_counts("processor : 0\n\nprocessor : 0"), (None, None));
    let arm = normalize(RawHardware {
        cpuinfo: Some("processor : 0\n\nprocessor : 1\nHardware : ARM board".into()),
        ..Default::default()
    });
    assert_eq!(arm.cpu.model.as_deref(), Some("ARM board"));
    assert_eq!(arm.cpu.logical_count, Some(2));
    assert!(arm.cpu.physical_core_count.is_none());
}

#[test]
fn memory_parsing_preserves_bytes_and_rejects_overflow_and_wrong_units() {
    let result = normalize(RawHardware {
        meminfo: Some("MemTotal: 8192 kB\nMemAvailable: 4096 kB".into()),
        ..Default::default()
    });
    assert_eq!(result.memory_bytes, Some(8388608));
    assert_eq!(result.memory_available_bytes, Some(4194304));
    for value in [
        "18446744073709551615 kB",
        "-1 kB",
        "8 MB",
        "8",
        "bad kB",
        "8 kB extra",
    ] {
        let result = normalize(RawHardware {
            meminfo: Some(format!("MemTotal: {value}")),
            ..Default::default()
        });
        assert!(result.memory_bytes.is_none(), "{value}");
        assert_eq!(result.issues[0].kind, IssueKind::Unknown);
    }
}

#[test]
fn gpu_fixture_identifies_vendors_models_and_keeps_incomplete_devices() {
    let f = Fixture::new();
    for (index, vendor) in [
        "0x1002", "0x8086", "0x10de", "0x1af4", "0x1234", "0x15ad", "0xffff",
    ]
    .iter()
    .enumerate()
    {
        let path = format!("sys/bus/pci/devices/gpu{index}");
        f.write(&format!("{path}/class"), "0x030000");
        f.write(&format!("{path}/vendor"), vendor);
        f.write(&format!("{path}/device"), "0x0001");
    }
    f.write("sys/bus/pci/devices/gpu8/class", "0x030200");
    f.write("sys/bus/pci/devices/gpu9/class", "0x020000");
    f.write("sys/bus/pci/devices/gpu0/boot_vga", "1");
    f.write("usr/share/hwdata/pci.ids", "# fixture\n1002  AMD\n\t0001  Test Radeon\n\t\t0001 0002  subsystem\n8086  Intel\n\t0001  Test Intel\n");
    let gpus = f.probe().gpus.unwrap();
    assert_eq!(gpus.len(), 8);
    for (gpu, expected) in gpus.iter().zip([
        Some("AMD"),
        Some("Intel"),
        Some("NVIDIA"),
        Some("Virtio"),
        Some("QEMU"),
        Some("VMware"),
        None,
        None,
    ]) {
        assert_eq!(gpu.vendor.as_deref(), expected);
    }
    assert_eq!(gpus[0].model.as_deref(), Some("Test Radeon"));
    assert_eq!(gpus[0].boot_vga, Some(true));
    assert!(gpus[7].vendor_id.is_none());
    assert_eq!(pci_id(Some("0X10DE".into())).as_deref(), Some("0x10de"));
    assert!(pci_id(Some("0xzzzz".into())).is_none());
}

#[test]
fn storage_fixture_follows_partition_parent_without_slaves() {
    let f = Fixture::new();
    f.write("sys/block/nvme0n1/size", "2048");
    f.write("sys/block/nvme0n1/device/model", "Test SSD");
    f.write("sys/block/nvme0n1/queue/rotational", "0");
    f.write("sys/block/nvme0n1/nvme0n1p2/partition", "2");
    f.write("sys/block/nvme0n1/nvme0n1p2/size", "1024");
    let disk = f.0.join("sys/block/nvme0n1");
    let partition = disk.join("nvme0n1p2");
    assert!(!partition.join("slaves").exists());
    assert_eq!(
        partition_parent(&partition).unwrap(),
        Some(fs::canonicalize(&disk).unwrap())
    );
    assert_eq!(partition_parent(&disk).unwrap(), None);
    let storage = f.probe().storage.unwrap();
    assert_eq!(storage.len(), 2);
    assert_eq!(storage[0].size_bytes, Some(1048576));
    assert_eq!(storage[1].size_bytes, Some(524288));
    assert_eq!(storage[1].kind, StorageKind::Partition);
    assert_eq!(storage[1].parent.as_deref(), Some("nvme0n1"));
    assert_eq!(storage[1].model.as_deref(), Some("Test SSD"));
    assert_eq!(storage[1].rotational, Some(false));
    assert_eq!(storage[1].transport, Some(Transport::Nvme));
}

#[test]
fn storage_transports_and_malformed_capacity() {
    let result = normalize(RawHardware {
        blocks: Some(
            [
                ("sda", "/sys/devices/ata1/host0", Some(Transport::Sata)),
                ("sdb", "/sys/devices/usb1/1-1/host1", Some(Transport::Usb)),
                ("vda", "/sys/devices/pci/virtio0", Some(Transport::Virtio)),
                ("sdc", "/sys/devices/unknown", None),
            ]
            .iter()
            .map(|(name, path, _)| RawBlock {
                name: (*name).into(),
                sys_path: Some((*path).into()),
                sectors: Some(u64::MAX),
                ..Default::default()
            })
            .collect(),
        ),
        ..Default::default()
    });
    for (device, expected) in result.storage.unwrap().iter().zip([
        Some(Transport::Sata),
        Some(Transport::Usb),
        Some(Transport::Virtio),
        None,
    ]) {
        assert_eq!(device.transport, expected);
        assert!(device.size_bytes.is_none());
    }
}

#[test]
fn firmware_fixture_distinguishes_uefi_legacy_and_unavailable() {
    let f = Fixture::new();
    assert_eq!(f.probe().capabilities.uefi, None);
    f.dir("sys/firmware");
    assert_eq!(f.probe().capabilities.uefi, Some(false));
    f.write("run/systemd/container", "podman");
    assert_eq!(f.probe().capabilities.uefi, None);
    f.dir("sys/firmware/efi");
    assert_eq!(f.probe().capabilities.uefi, Some(true));
}

#[test]
fn vm_fallbacks_do_not_guess_physical_hardware_or_generic_dmi() {
    for (vendor, product, kind) in [
        ("QEMU", "Standard PC", Some("qemu")),
        ("VMware, Inc.", "VMware Virtual Platform", Some("vmware")),
        ("innotek GmbH", "VirtualBox", Some("oracle")),
        (
            "Microsoft Corporation",
            "Virtual Machine",
            Some("microsoft"),
        ),
        ("Google", "Google Compute Engine", Some("google")),
        ("Amazon EC2", "i3.metal", None),
        ("Dell", "Workstation", None),
    ] {
        let h = normalize(RawHardware {
            dmi_vendor: Some(vendor.into()),
            dmi_product: Some(product.into()),
            ..Default::default()
        });
        assert_eq!(h.capabilities.virtualization_type.as_deref(), kind);
        assert_eq!(h.capabilities.virtual_machine, kind.map(|_| true));
    }
    let f = Fixture::new();
    f.write("sys/hypervisor/type", "xen");
    f.write("run/systemd/container", "podman");
    let h = f.probe();
    assert_eq!(h.capabilities.virtualization_type.as_deref(), Some("xen"));
    assert_eq!(h.capabilities.container_type.as_deref(), Some("podman"));
    let h = normalize(RawHardware {
        device_tree_compatible: Some("linux,kvm\0".into()),
        ..Default::default()
    });
    assert_eq!(h.capabilities.virtualization_type.as_deref(), Some("kvm"));
    let h = normalize(RawHardware {
        cpuinfo: Some("flags : sse hypervisor".into()),
        ..Default::default()
    });
    assert_eq!(h.capabilities.virtual_machine, Some(true));
    assert!(h.capabilities.virtualization_type.is_none());
}

#[test]
fn missing_empty_malformed_and_io_errors_are_separate() {
    let f = Fixture::new();
    let h = f.probe();
    assert!(h.gpus.is_none() && h.storage.is_none() && h.memory_bytes.is_none());
    assert!(h.issues.iter().all(|i| i.kind == IssueKind::Unavailable));
    f.dir("sys/bus/pci/devices");
    f.dir("sys/block");
    let h = f.probe();
    assert!(h.gpus.unwrap().is_empty());
    assert!(h.storage.unwrap().is_empty());
    f.dir("proc/cpuinfo"); // reading a directory is an actual IO error on both platforms
    f.write("sys/block/sda/queue/rotational", "2");
    f.write("sys/block/sda/size", "bad");
    let h = f.probe();
    assert!(h
        .issues
        .iter()
        .any(|i| i.source == "/proc/cpuinfo" && i.kind == IssueKind::Error));
    assert!(h
        .issues
        .iter()
        .any(|i| i.source.ends_with("rotational") && i.kind == IssueKind::Unknown));
    assert!(h.storage.unwrap()[0].size_bytes.is_none());
}

#[cfg(unix)]
#[test]
fn real_sysfs_symlinks_link_drm_and_partitions_without_duplicates() {
    use std::os::unix::fs::symlink;
    let f = Fixture::new();
    let pci = "sys/devices/pci0000:00/0000:00:02.0";
    for (name, value) in [
        ("class", "0x030000"),
        ("vendor", "0x8086"),
        ("device", "0x0001"),
    ] {
        f.write(&format!("{pci}/{name}"), value);
    }
    f.dir("sys/bus/pci/devices");
    symlink(f.0.join(pci), f.0.join("sys/bus/pci/devices/0000:00:02.0")).unwrap();
    for node in ["card0", "renderD128", "card0-HDMI-A-1"] {
        f.dir(&format!("sys/class/drm/{node}"));
        symlink(
            f.0.join(pci),
            f.0.join(format!("sys/class/drm/{node}/device")),
        )
        .unwrap();
    }
    f.dir("sys/bus/pci/drivers/i915");
    symlink(
        f.0.join("sys/bus/pci/drivers/i915"),
        f.0.join(format!("{pci}/driver")),
    )
    .unwrap();
    let virtio = "sys/devices/pci0000:00/0000:00:03.0";
    for (name, value) in [
        ("class", "0x030000"),
        ("vendor", "0x1af4"),
        ("device", "0x1050"),
    ] {
        f.write(&format!("{virtio}/{name}"), value);
    }
    symlink(
        f.0.join(virtio),
        f.0.join("sys/bus/pci/devices/0000:00:03.0"),
    )
    .unwrap();
    f.dir(&format!("{virtio}/virtio0"));
    f.dir("sys/bus/virtio/drivers/virtio_gpu");
    symlink(
        f.0.join("sys/bus/virtio/drivers/virtio_gpu"),
        f.0.join(format!("{virtio}/virtio0/driver")),
    )
    .unwrap();
    for node in ["card1", "renderD129"] {
        f.dir(&format!("sys/class/drm/{node}"));
        symlink(
            f.0.join(format!("{virtio}/virtio0")),
            f.0.join(format!("sys/class/drm/{node}/device")),
        )
        .unwrap();
    }
    f.dir("sys/devices/platform/simple-framebuffer.0");
    f.dir("sys/bus/platform/drivers/simpledrm");
    symlink(
        f.0.join("sys/bus/platform/drivers/simpledrm"),
        f.0.join("sys/devices/platform/simple-framebuffer.0/driver"),
    )
    .unwrap();
    f.dir("sys/class/drm/card2");
    symlink(
        f.0.join("sys/devices/platform/simple-framebuffer.0"),
        f.0.join("sys/class/drm/card2/device"),
    )
    .unwrap();
    let disk = "sys/devices/pci0000:00/ata1/host0/sda";
    f.write(&format!("{disk}/size"), "4096");
    f.write(&format!("{disk}/queue/rotational"), "1");
    f.write(&format!("{disk}/sda2/partition"), "2");
    f.write(&format!("{disk}/sda2/size"), "2048");
    f.dir("sys/class/block");
    symlink(f.0.join(disk), f.0.join("sys/class/block/sda")).unwrap();
    symlink(
        f.0.join(format!("{disk}/sda2")),
        f.0.join("sys/class/block/sda2"),
    )
    .unwrap();
    let h = f.probe();
    let gpus = h.gpus.unwrap();
    assert_eq!(gpus.len(), 3);
    assert_eq!(gpus[0].drm_nodes, ["/dev/dri/card0", "/dev/dri/renderD128"]);
    assert_eq!(gpus[0].driver.as_deref(), Some("i915"));
    assert_eq!(gpus[1].vendor.as_deref(), Some("Virtio"));
    assert_eq!(gpus[1].pci_address.as_deref(), Some("0000:00:03.0"));
    assert_eq!(gpus[1].driver.as_deref(), Some("virtio_gpu"));
    assert_eq!(gpus[1].drm_nodes, ["/dev/dri/card1", "/dev/dri/renderD129"]);
    assert!(gpus[2].pci_address.is_none() && gpus[2].vendor.is_none());
    assert_eq!(gpus[2].driver.as_deref(), Some("simpledrm"));
    let storage = h.storage.unwrap();
    assert_eq!(storage[1].parent.as_deref(), Some("sda"));
    assert_eq!(storage[1].transport, Some(Transport::Sata));
    assert_eq!(storage[1].rotational, Some(true));
}
