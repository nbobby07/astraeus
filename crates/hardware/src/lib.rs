//! Read-only Linux discovery. Missing observations remain unknown.
use serde::Serialize;
use std::{fs, path::Path};

#[derive(Debug, Default)]
pub struct RawHardware {
    pub cpuinfo: Option<String>,
    pub meminfo: Option<String>,
    pub pci: Option<Vec<(String, String, String, String)>>,
    pub blocks: Option<Vec<RawBlock>>,
    pub dmi_vendor: Option<String>,
    pub dmi_product: Option<String>,
    pub uefi: Option<bool>,
}

#[derive(Debug)]
pub struct RawBlock {
    pub name: String,
    pub model: Option<String>,
    pub sys_path: Option<String>,
    pub sectors: Option<u64>,
}

#[derive(Debug, Serialize)]
pub struct Cpu {
    pub architecture: String,
    pub vendor: Option<String>,
    pub model: Option<String>,
    pub logical_count: Option<usize>,
}

#[derive(Debug, Serialize)]
pub struct Gpu {
    pub pci_address: String,
    pub vendor: String,
    pub vendor_id: String,
    pub device_id: String,
}

#[derive(Debug, Serialize)]
pub struct Storage {
    pub name: String,
    pub model: Option<String>,
    pub transport: Option<String>,
    pub size_bytes: Option<u64>,
}

#[derive(Debug, Serialize)]
pub struct Capabilities {
    pub uefi: Option<bool>,
    pub virtual_machine: Option<bool>,
}

#[derive(Debug, Serialize)]
pub struct Hardware {
    pub cpu: Cpu,
    pub memory_bytes: Option<u64>,
    pub gpus: Option<Vec<Gpu>>,
    pub storage: Option<Vec<Storage>>,
    pub capabilities: Capabilities,
}

fn read(path: impl AsRef<Path>) -> Option<String> {
    fs::read_to_string(path).ok().map(|s| s.trim().to_owned())
}

/// A filesystem root permits captured proc/sysfs fixtures without probing the host.
pub fn discover(root: &Path) -> RawHardware {
    let pci = fs::read_dir(root.join("sys/bus/pci/devices"))
        .ok()
        .map(|dir| {
            let mut devices = Vec::new();
            for entry in dir.flatten() {
                let p = entry.path();
                if let (Some(class), Some(vendor), Some(device)) = (
                    read(p.join("class")),
                    read(p.join("vendor")),
                    read(p.join("device")),
                ) {
                    devices.push((
                        entry.file_name().to_string_lossy().into(),
                        class,
                        vendor,
                        device,
                    ));
                }
            }
            devices.sort();
            devices
        });
    let blocks = fs::read_dir(root.join("sys/block")).ok().map(|dir| {
        let mut devices = Vec::new();
        for entry in dir.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            if ["loop", "ram", "dm-", "zram"]
                .iter()
                .any(|prefix| name.starts_with(prefix))
            {
                continue;
            }
            let p = entry.path();
            let link = fs::canonicalize(&p)
                .ok()
                .map(|p| p.to_string_lossy().into_owned());
            devices.push(RawBlock {
                name,
                model: read(p.join("device/model")),
                sys_path: link,
                sectors: read(p.join("size")).and_then(|s| s.parse::<u64>().ok()),
            });
        }
        devices.sort_by(|a, b| a.name.cmp(&b.name));
        devices
    });
    RawHardware {
        cpuinfo: read(root.join("proc/cpuinfo")),
        meminfo: read(root.join("proc/meminfo")),
        pci,
        blocks,
        dmi_vendor: read(root.join("sys/class/dmi/id/sys_vendor")),
        dmi_product: read(root.join("sys/class/dmi/id/product_name")),
        uefi: root
            .join("sys/firmware")
            .is_dir()
            .then(|| root.join("sys/firmware/efi").is_dir()),
    }
}

fn field(text: &str, name: &str) -> Option<String> {
    text.lines().find_map(|line| {
        let (key, value) = line.split_once(':')?;
        (key.trim() == name && !value.trim().is_empty()).then(|| value.trim().to_owned())
    })
}

pub fn normalize(raw: RawHardware) -> Hardware {
    let cpuinfo = raw.cpuinfo.as_deref().unwrap_or("");
    let logical_count = raw.cpuinfo.as_ref().and_then(|s| {
        let n = s
            .lines()
            .filter(|line| {
                line.split_once(':')
                    .is_some_and(|(k, _)| k.trim() == "processor")
            })
            .count();
        (n > 0).then_some(n)
    });
    let memory_bytes = raw
        .meminfo
        .as_deref()
        .and_then(|s| field(s, "MemTotal"))
        .and_then(|s| {
            let mut words = s.split_whitespace();
            let size = words.next()?.parse::<u64>().ok()?;
            (words.next()? == "kB")
                .then(|| size.checked_mul(1024))
                .flatten()
        });
    let gpus = raw.pci.map(|devices| {
        devices
            .into_iter()
            .filter(|(_, c, _, _)| c.starts_with("0x03"))
            .map(|(address, _, vendor_id, device_id)| {
                let vendor = match vendor_id.to_ascii_lowercase().as_str() {
                    "0x1002" => "AMD",
                    "0x10de" => "NVIDIA",
                    "0x8086" => "Intel",
                    "0x1af4" => "Virtio",
                    "0x1234" => "QEMU",
                    _ => "Unknown",
                }
                .to_owned();
                Gpu {
                    pci_address: address,
                    vendor,
                    vendor_id,
                    device_id,
                }
            })
            .collect()
    });
    let dmi = format!(
        "{} {}",
        raw.dmi_vendor.as_deref().unwrap_or(""),
        raw.dmi_product.as_deref().unwrap_or("")
    )
    .to_ascii_lowercase();
    let vm = cpuinfo
        .lines()
        .any(|l| l.starts_with("flags") && l.split_whitespace().any(|f| f == "hypervisor"))
        || [
            "qemu",
            "kvm",
            "vmware",
            "virtualbox",
            "virtual machine",
            "xen",
            "bochs",
            "amazon ec2",
            "google compute",
        ]
        .iter()
        .any(|v| dmi.contains(v));
    // Absence of VM evidence does not prove physical hardware.
    Hardware {
        cpu: Cpu {
            architecture: std::env::consts::ARCH.into(),
            vendor: field(cpuinfo, "vendor_id"),
            model: field(cpuinfo, "model name"),
            logical_count,
        },
        memory_bytes,
        gpus,
        storage: raw.blocks.map(|devices| {
            devices
                .into_iter()
                .map(|d| {
                    let path = d.sys_path.as_deref().unwrap_or("");
                    let transport = if d.name.starts_with("nvme") {
                        Some("nvme")
                    } else if path.contains("virtio") || d.name.starts_with("vd") {
                        Some("virtio")
                    } else if path.contains("/ata") {
                        Some("sata")
                    } else if path.contains("/usb") {
                        Some("usb")
                    } else {
                        None
                    };
                    Storage {
                        name: d.name,
                        model: d.model,
                        transport: transport.map(str::to_owned),
                        size_bytes: d.sectors.and_then(|n| n.checked_mul(512)),
                    }
                })
                .collect()
        }),
        capabilities: Capabilities {
            uefi: raw.uefi,
            virtual_machine: vm.then_some(true),
        },
    }
}

pub fn probe() -> Hardware {
    normalize(discover(Path::new("/")))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn captured_hardware_and_missing_data() {
        for (vendor, model, gpu_vendor, gpu_name) in [
            ("AuthenticAMD", "Ryzen", "0x1002", "AMD"),
            ("GenuineIntel", "Core", "0x8086", "Intel"),
            ("GenuineIntel", "QEMU", "0x10de", "NVIDIA"),
        ] {
            let result = normalize(RawHardware {
                cpuinfo: Some(format!("processor : 0\nvendor_id : {vendor}\nmodel name : {model}\nflags : sse hypervisor\n\nprocessor : 1")),
                meminfo: Some("MemTotal: 8192 kB".into()),
                pci: Some(vec![("0000:01:00.0".into(), "0x030000".into(), gpu_vendor.into(), "0x0001".into()), ("0000:00:02.0".into(), "0x030200".into(), "0x1af4".into(), "0x1050".into())]),
                uefi: Some(true), ..Default::default()
            });
            assert_eq!(result.cpu.vendor.as_deref(), Some(vendor));
            assert_eq!(result.cpu.model.as_deref(), Some(model));
            assert_eq!(result.cpu.logical_count, Some(2));
            assert_eq!(result.memory_bytes, Some(8388608));
            assert_eq!(result.gpus.as_ref().unwrap()[0].vendor, gpu_name);
            assert_eq!(result.gpus.as_ref().unwrap().len(), 2);
            assert_eq!(result.capabilities.virtual_machine, Some(true));
        }
        let empty = normalize(RawHardware::default());
        assert!(
            empty.cpu.logical_count.is_none()
                && empty.gpus.is_none()
                && empty.capabilities.uefi.is_none()
        );
        let malformed = normalize(RawHardware {
            meminfo: Some("MemTotal: 18446744073709551615 kB".into()),
            ..Default::default()
        });
        assert!(malformed.memory_bytes.is_none());
        let blocks = normalize(RawHardware {
            blocks: Some(vec![
                RawBlock {
                    name: "nvme0n1".into(),
                    model: Some("NVMe disk".into()),
                    sys_path: None,
                    sectors: Some(2048),
                },
                RawBlock {
                    name: "vda".into(),
                    model: None,
                    sys_path: None,
                    sectors: Some(u64::MAX),
                },
                RawBlock {
                    name: "sda".into(),
                    model: None,
                    sys_path: Some("/sys/devices/pci/ata1/host0".into()),
                    sectors: None,
                },
            ]),
            ..Default::default()
        });
        let blocks = blocks.storage.unwrap();
        assert_eq!(blocks[0].transport.as_deref(), Some("nvme"));
        assert_eq!(blocks[0].size_bytes, Some(1048576));
        assert_eq!(blocks[1].transport.as_deref(), Some("virtio"));
        assert!(blocks[1].size_bytes.is_none());
        assert_eq!(blocks[2].transport.as_deref(), Some("sata"));
    }
}
