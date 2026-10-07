//! Reusable read-only status model for the CLI and future UI.
use distro_hardware::{discover, normalize, partition_parent, Hardware, StorageKind, Transport};
use serde::Serialize;
use std::{collections::BTreeMap, fs, path::Path};

#[derive(Debug, Serialize)]
pub struct Boot {
    pub firmware: Option<String>,
    pub bootloader: Option<String>,
    pub stub: Option<String>,
    pub uki_path: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct Filesystem {
    pub root_type: Option<String>,
    pub source: Option<String>,
    pub options: Option<String>,
    pub encryption: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct Desktop {
    pub name: Option<String>,
    pub session_type: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct Status {
    pub schema_version: u32,
    pub name: Option<String>,
    pub version: Option<String>,
    pub channel: Option<String>,
    pub hostname: Option<String>,
    pub kernel: Option<String>,
    pub boot: Boot,
    pub filesystem: Filesystem,
    pub desktop: Desktop,
    pub hardware: Hardware,
}

fn read(root: &Path, path: &str) -> Option<String> {
    fs::read_to_string(root.join(path))
        .ok()
        .map(|s| s.trim().to_owned())
        .filter(|s| !s.is_empty())
}

fn os_release(text: &str) -> BTreeMap<String, String> {
    text.lines()
        .filter_map(|l| {
            let (key, value) = l.split_once('=')?;
            if key.starts_with('#') {
                return None;
            }
            Some((key.into(), value.trim_matches(['"', '\'']).into()))
        })
        .collect()
}

fn efi(root: &Path, name: &str) -> Option<String> {
    let path = root.join(format!(
        "sys/firmware/efi/efivars/{name}-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"
    ));
    let bytes = fs::read(path).ok()?;
    let content = bytes.get(4..)?;
    if !content.len().is_multiple_of(2) {
        return None;
    }
    let words: Vec<_> = content
        .chunks_exact(2)
        .map(|v| u16::from_le_bytes([v[0], v[1]]))
        .take_while(|v| *v != 0)
        .collect();
    String::from_utf16(&words).ok().filter(|s| !s.is_empty())
}

fn unescape_mount(value: &str) -> String {
    value
        .replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
}

fn root_mount(text: &str) -> Option<(String, String, String)> {
    text.lines().find_map(|l| {
        let (left, right) = l.split_once(" - ")?;
        let left: Vec<_> = left.split_whitespace().collect();
        let right: Vec<_> = right.split_whitespace().collect();
        if left.get(4)? != &"/" {
            return None;
        }
        Some((
            right.first()?.to_string(),
            unescape_mount(right.get(1)?),
            format!("{},{}", left.get(5)?, right.get(2)?),
        ))
    })
}

fn encryption(device: &Path, depth: usize) -> Option<String> {
    if depth > 16 || !device.is_dir() {
        return None;
    }
    // Partition sysfs directories have no slaves; follow their containing disk.
    if let Some(parent) = partition_parent(device).ok()? {
        return encryption(&parent, depth + 1);
    }
    if device.join("dm").is_dir() {
        let uuid = fs::read_to_string(device.join("dm/uuid")).ok()?;
        if uuid.starts_with("CRYPT-LUKS2-") {
            return Some("LUKS2".into());
        }
        if uuid.starts_with("CRYPT-LUKS1-") {
            return Some("LUKS1".into());
        }
        if uuid.starts_with("CRYPT-") {
            return Some("dm-crypt".into());
        }
    }
    let slaves = fs::read_dir(device.join("slaves")).ok()?;
    let mut unknown = false;
    for slave in slaves {
        match slave
            .ok()
            .and_then(|s| encryption(&s.path(), depth + 1))
            .as_deref()
        {
            Some("none") => (),
            Some(value) => return Some(value.into()),
            None => unknown = true,
        }
    }
    (!unknown).then(|| "none".into())
}

pub fn collect(root: &Path, desktop: Desktop) -> Status {
    let release = read(root, "etc/os-release")
        .or_else(|| read(root, "usr/lib/os-release"))
        .map(|s| os_release(&s))
        .unwrap_or_default();
    let hardware = normalize(discover(root));
    let mount = read(root, "proc/self/mountinfo").and_then(|s| root_mount(&s));
    let mut filesystem = Filesystem {
        root_type: None,
        source: None,
        options: None,
        encryption: None,
    };
    if let Some((kind, source, options)) = mount {
        // Btrfs uses an anonymous mount device number; resolve its actual source.
        if source.starts_with("/dev/") {
            let path = root.join(source.trim_start_matches('/'));
            let resolved = fs::canonicalize(&path).unwrap_or(path);
            if let Some(name) = resolved.file_name() {
                filesystem.encryption = encryption(&root.join("sys/class/block").join(name), 0);
            }
        }
        filesystem.root_type = Some(kind);
        filesystem.source = Some(source);
        filesystem.options = Some(options);
    }
    Status {
        schema_version: 1,
        name: release.get("NAME").cloned(),
        version: release.get("VERSION_ID").cloned(),
        channel: release.get("VARIANT_ID").cloned(),
        hostname: read(root, "proc/sys/kernel/hostname"),
        kernel: read(root, "proc/sys/kernel/osrelease"),
        boot: Boot {
            firmware: hardware
                .capabilities
                .uefi
                .map(|v| if v { "UEFI" } else { "BIOS" }.into()),
            bootloader: efi(root, "LoaderInfo"),
            stub: efi(root, "StubInfo"),
            uki_path: efi(root, "StubImageIdentifier"),
        },
        filesystem,
        desktop,
        hardware,
    }
}

pub fn status() -> Status {
    collect(
        Path::new("/"),
        Desktop {
            name: std::env::var("XDG_CURRENT_DESKTOP")
                .ok()
                .filter(|s| !s.trim().is_empty()),
            session_type: std::env::var("XDG_SESSION_TYPE")
                .ok()
                .filter(|s| matches!(s.as_str(), "wayland" | "x11")),
        },
    )
}

pub fn known(value: &Option<String>) -> &str {
    value
        .as_deref()
        .filter(|s| !s.is_empty())
        .unwrap_or("unknown")
}

/// IEC units are presentation only; the JSON model always retains byte counts.
pub fn human_bytes(bytes: Option<u64>) -> String {
    let Some(bytes) = bytes else {
        return "unknown".into();
    };
    let mut size = bytes as f64;
    let mut unit = "B";
    for next in ["KiB", "MiB", "GiB", "TiB", "PiB", "EiB"] {
        if size < 1024.0 {
            break;
        }
        size /= 1024.0;
        unit = next;
    }
    if unit == "B" {
        format!("{bytes} B")
    } else {
        format!("{size:.1} {unit}")
    }
}

fn count(value: Option<usize>) -> String {
    value
        .map(|v| v.to_string())
        .unwrap_or_else(|| "unknown".into())
}

fn gpu_summary(hardware: &Hardware) -> String {
    match &hardware.gpus {
        None => "unknown".into(),
        Some(gpus) if gpus.is_empty() => "none detected".into(),
        Some(gpus) => gpus
            .iter()
            .map(|g| {
                format!(
                    "{} {}",
                    known(&g.vendor),
                    g.model.clone().unwrap_or_else(|| format!(
                        "{}:{}",
                        known(&g.vendor_id),
                        known(&g.device_id)
                    ))
                )
            })
            .collect::<Vec<_>>()
            .join(", "),
    }
}

fn disk_summary(hardware: &Hardware) -> String {
    match &hardware.storage {
        None => "unknown".into(),
        Some(devices) => {
            let disks = devices
                .iter()
                .filter(|d| d.kind == StorageKind::Disk)
                .map(|d| format!("{} ({})", d.path, human_bytes(d.size_bytes)))
                .collect::<Vec<_>>();
            if disks.is_empty() {
                "none detected".into()
            } else {
                disks.join(", ")
            }
        }
    }
}

pub fn format_status(s: &Status) -> String {
    let k = known;
    format!("{}\n\nSystem\n  Version       {}\n  Channel       {}\n  Architecture  {}\n  Hostname      {}\n\nKernel\n  Version       {}\n\nBoot\n  Firmware      {}\n  Bootloader    {}\n  Stub          {}\n  UKI path      {}\n\nFilesystem\n  Root          {}\n  Encryption    {}\n\nDesktop\n  Name          {}\n  Session       {}\n\nHardware\n  CPU           {}\n  Logical CPUs  {}\n  GPU           {}\n  Memory        {}\n  Storage       {}\n",
        k(&s.name), k(&s.version), k(&s.channel), s.hardware.cpu.architecture, k(&s.hostname),
        k(&s.kernel), k(&s.boot.firmware), k(&s.boot.bootloader), k(&s.boot.stub), k(&s.boot.uki_path),
        k(&s.filesystem.root_type), k(&s.filesystem.encryption), k(&s.desktop.name), k(&s.desktop.session_type),
        k(&s.hardware.cpu.model), count(s.hardware.cpu.logical_count), gpu_summary(&s.hardware),
        human_bytes(s.hardware.memory_bytes), disk_summary(&s.hardware))
}

pub fn format_hardware(h: &Hardware) -> String {
    use std::fmt::Write;
    let mut output = format!("Hardware\n\nCPU\n  Architecture  {}\n  Vendor        {}\n  Model         {}\n  Logical CPUs  {}\n  Physical cores {}\n\nMemory\n  Total         {}\n  Available     {}\n\nGPU\n  {}\n",
        h.cpu.architecture, known(&h.cpu.vendor), known(&h.cpu.model), count(h.cpu.logical_count),
        count(h.cpu.physical_core_count), human_bytes(h.memory_bytes), human_bytes(h.memory_available_bytes), gpu_summary(h));
    for gpu in h.gpus.iter().flatten() {
        writeln!(
            output,
            "  PCI           {}\n  Driver        {}\n  DRM nodes     {}\n  Boot VGA      {}",
            known(&gpu.pci_address),
            known(&gpu.driver),
            if gpu.drm_nodes.is_empty() {
                "none detected".into()
            } else {
                gpu.drm_nodes.join(", ")
            },
            gpu.boot_vga
                .map(|v| v.to_string())
                .unwrap_or_else(|| "unknown".into())
        )
        .unwrap();
    }
    output.push_str("\nStorage\n");
    if let Some(devices) = &h.storage {
        if devices.is_empty() {
            output.push_str("  none detected\n");
        }
        for d in devices {
            let transport = match d.transport {
                Some(Transport::Nvme) => "NVMe",
                Some(Transport::Sata) => "SATA",
                Some(Transport::Virtio) => "virtio",
                Some(Transport::Usb) => "USB",
                None => "unknown",
            };
            let kind = match d.kind {
                StorageKind::Disk => "disk",
                StorageKind::Partition => "partition",
                StorageKind::Mapped => "mapped",
            };
            writeln!(output, "  {} ({}, {})\n    Model       {}\n    Transport   {}\n    Rotational  {}\n    Parent      {}", d.path, kind, human_bytes(d.size_bytes), known(&d.model), transport,
                d.rotational.map(|v| v.to_string()).unwrap_or_else(|| "unknown".into()), known(&d.parent)).unwrap();
        }
    } else {
        output.push_str("  unknown\n");
    }
    writeln!(output, "\nEnvironment\n  Firmware      {}\n  VM            {}\n  VM type       {}\n  Container     {}",
        h.capabilities.uefi.map(|v| if v { "UEFI" } else { "BIOS" }).unwrap_or("unknown"),
        h.capabilities.virtual_machine.map(|v| v.to_string()).unwrap_or_else(|| "unknown".into()),
        known(&h.capabilities.virtualization_type), known(&h.capabilities.container_type)).unwrap();
    if !h.issues.is_empty() {
        writeln!(
            output,
            "\nObservations\n  {} unavailable, unknown or failed reads; see --json issues",
            h.issues.len()
        )
        .unwrap();
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn parse_observations_without_inventing_status() {
        let release =
            os_release("NAME=\"Project Astraeus\"\nVERSION_ID=0.1.0-dev\n#COMMENT=value\n");
        assert_eq!(release.get("NAME").unwrap(), "Project Astraeus");
        assert!(!release.contains_key("#COMMENT"));
        let mount = root_mount(
            "36 1 0:32 /@ / rw,relatime - btrfs /dev/mapper/root rw,compress=zstd:1,subvol=/@\n",
        )
        .unwrap();
        assert_eq!(mount.0, "btrfs");
        assert_eq!(mount.1, "/dev/mapper/root");
        assert!(root_mount("malformed").is_none());
        assert_eq!(unescape_mount("/dev/a\\040b"), "/dev/a b");
        let missing = collect(
            Path::new("/nonexistent-distroctl-fixture"),
            Desktop {
                name: None,
                session_type: None,
            },
        );
        let json = serde_json::to_value(missing).unwrap();
        assert!(json["boot"]["bootloader"].is_null());
        assert!(json["filesystem"]["encryption"].is_null());
        assert!(json["kernel"].is_null());
        assert_eq!(json["schema_version"], 1);
    }

    #[test]
    fn formatting_and_json_share_normalized_hardware() {
        let mut s = collect(
            Path::new("/nonexistent-distroctl-fixture"),
            Desktop {
                name: None,
                session_type: None,
            },
        );
        s.hardware = normalize(distro_hardware::RawHardware {
            cpuinfo: Some("processor : 0\nmodel name : Fixture CPU".into()),
            meminfo: Some("MemTotal: 8388608 kB\nMemAvailable: 4194304 kB".into()),
            pci: Some(Vec::new()),
            blocks: Some(vec![distro_hardware::RawBlock {
                name: "vda".into(),
                sectors: Some(2097152),
                ..Default::default()
            }]),
            ..Default::default()
        });
        s.name = Some("Fixture OS".into());
        s.hostname = Some("fixture-host".into());
        let text = format_status(&s);
        for expected in [
            "Fixture OS",
            "fixture-host",
            "Fixture CPU",
            "8.0 GiB",
            "/dev/vda (1.0 GiB)",
            "GPU           none detected",
            "Encryption    unknown",
        ] {
            assert!(text.contains(expected), "missing {expected}: {text}");
        }
        let hardware_text = format_hardware(&s.hardware);
        assert!(hardware_text.contains("Available     4.0 GiB"));
        assert!(hardware_text.contains("Transport   virtio"));
        assert!(hardware_text.contains("Physical cores unknown"));
        let json = serde_json::to_value(&s).unwrap();
        assert_eq!(json["hardware"]["memory_bytes"], 8589934592u64);
        assert_eq!(json["hardware"]["memory_available_bytes"], 4294967296u64);
        assert_eq!(json["hardware"]["storage"][0]["transport"], "virtio");
        assert_eq!(json["hardware"]["storage"][0]["kind"], "disk");
        assert!(json["hardware"]["cpu"]["physical_core_count"].is_null());
        assert_eq!(json["hardware"]["gpus"], serde_json::json!([]));
        assert_eq!(json["hostname"], "fixture-host");
        assert_eq!(human_bytes(Some(0)), "0 B");
        assert_eq!(human_bytes(Some(1023)), "1023 B");
        assert_eq!(human_bytes(Some(1024)), "1.0 KiB");
        assert_eq!(human_bytes(None), "unknown");
        assert_eq!(human_bytes(Some(u64::MAX)), "16.0 EiB");
    }

    #[cfg(unix)]
    #[test]
    fn status_resolves_real_partition_and_mapper_symlinks() {
        use std::os::unix::fs::symlink;
        let root = std::env::temp_dir().join(format!("distroctl-symlinks-{}", std::process::id()));
        let write = |name: &str, text: &str| {
            let path = root.join(name);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, text).unwrap();
        };
        write("sys/devices/block/vda/vda2/partition", "2");
        fs::create_dir_all(root.join("sys/devices/block/vda/slaves")).unwrap();
        fs::create_dir_all(root.join("sys/class/block")).unwrap();
        symlink(
            root.join("sys/devices/block/vda/vda2"),
            root.join("sys/class/block/vda2"),
        )
        .unwrap();
        write("dev/vda2", "");
        write(
            "proc/self/mountinfo",
            "36 1 0:32 /@ / rw - btrfs /dev/vda2 rw\n",
        );
        let desktop = || Desktop {
            name: None,
            session_type: None,
        };
        assert_eq!(
            collect(&root, desktop()).filesystem.encryption.as_deref(),
            Some("none")
        );
        assert!(!root.join("sys/devices/block/vda/vda2/slaves").exists());
        write(
            "sys/devices/virtual/block/dm-0/dm/uuid",
            "CRYPT-LUKS2-fixture-root",
        );
        symlink(
            root.join("sys/devices/virtual/block/dm-0"),
            root.join("sys/class/block/dm-0"),
        )
        .unwrap();
        write("dev/dm-0", "");
        fs::create_dir_all(root.join("dev/mapper")).unwrap();
        symlink("../dm-0", root.join("dev/mapper/root")).unwrap();
        write(
            "proc/self/mountinfo",
            "36 1 0:32 /@ / rw - btrfs /dev/mapper/root rw\n",
        );
        assert_eq!(
            collect(&root, desktop()).filesystem.encryption.as_deref(),
            Some("LUKS2")
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn fixture_detects_encrypted_and_plain_root_and_running_uki() {
        let root = std::env::temp_dir().join(format!("distroctl-fixture-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let write = |name: &str, bytes: &[u8]| {
            let path = root.join(name);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, bytes).unwrap();
        };
        write(
            "etc/os-release",
            b"NAME=Test OS\nVERSION_ID=0.1.0-dev\nVARIANT_ID=development\n",
        );
        write("proc/sys/kernel/hostname", b"fixture-host");
        write(
            "proc/self/mountinfo",
            b"36 1 0:32 /@ / rw - btrfs /dev/dm-0 rw,subvol=/@\n",
        );
        write(
            "sys/class/block/dm-0/dm/uuid",
            b"CRYPT-LUKS2-12345678123412341234123456789abc-root",
        );
        fs::create_dir_all(root.join("sys/class/block/dm-0/slaves")).unwrap();
        for (name, value) in [
            ("LoaderInfo", "systemd-boot 262"),
            ("StubInfo", "systemd-stub 262"),
            ("StubImageIdentifier", "\\EFI\\Linux\\test-linux.efi"),
        ] {
            let mut bytes = vec![7, 0, 0, 0];
            for word in value.encode_utf16().chain([0]) {
                bytes.extend(word.to_le_bytes());
            }
            write(
                &format!("sys/firmware/efi/efivars/{name}-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"),
                &bytes,
            );
        }
        let desktop = || Desktop {
            name: Some("KDE".into()),
            session_type: Some("wayland".into()),
        };
        let result = collect(&root, desktop());
        assert_eq!(result.filesystem.encryption.as_deref(), Some("LUKS2"));
        assert_eq!(result.boot.bootloader.as_deref(), Some("systemd-boot 262"));
        assert_eq!(
            result.boot.uki_path.as_deref(),
            Some("\\EFI\\Linux\\test-linux.efi")
        );
        assert_eq!(result.boot.firmware.as_deref(), Some("UEFI"));
        assert_eq!(result.hostname.as_deref(), Some("fixture-host"));
        write(
            "proc/self/mountinfo",
            b"36 1 0:32 /@ / rw - btrfs /dev/vda rw,subvol=/@\n",
        );
        fs::create_dir_all(root.join("sys/class/block/vda/slaves")).unwrap();
        write("sys/class/block/vda/vda2/partition", b"2");
        assert_eq!(
            encryption(&root.join("sys/class/block/vda/vda2"), 0).as_deref(),
            Some("none")
        );
        assert_eq!(
            collect(&root, desktop()).filesystem.encryption.as_deref(),
            Some("none")
        );
        // A mapped partition must trace through the parent, even without slaves.
        write("sys/class/block/dm-0/dm-0p1/partition", b"1");
        assert_eq!(
            encryption(&root.join("sys/class/block/dm-0/dm-0p1"), 0).as_deref(),
            Some("LUKS2")
        );
        assert!(!root.join("sys/class/block/dm-0/dm-0p1/slaves").exists());
        assert!(encryption(&root.join("sys/class/block/missing"), 0).is_none());
        assert!(encryption(&root.join("sys/class/block/dm-0"), 17).is_none());
        write(
            "sys/firmware/efi/efivars/StubInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f",
            b"bad",
        );
        assert!(collect(&root, desktop()).boot.stub.is_none());
        fs::remove_dir_all(root).unwrap();
    }
}
