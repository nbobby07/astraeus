//! Read-only Linux discovery, normalization and capabilities. No subprocesses.
use serde::Serialize;
use std::{
    collections::BTreeSet,
    fs, io,
    path::{Path, PathBuf},
};

#[derive(Debug, Default)]
pub struct RawHardware {
    pub cpuinfo: Option<String>,
    pub meminfo: Option<String>,
    pub pci: Option<Vec<RawGpu>>,
    pub blocks: Option<Vec<RawBlock>>,
    pub dmi_vendor: Option<String>,
    pub dmi_product: Option<String>,
    pub hypervisor: Option<String>,
    pub device_tree_compatible: Option<String>,
    pub container: Option<String>,
    pub uefi: Option<bool>,
    pub issues: Vec<ProbeIssue>,
}

#[derive(Debug, Default)]
pub struct RawGpu {
    pub pci_address: Option<String>,
    pub vendor_id: Option<String>,
    pub device_id: Option<String>,
    pub model: Option<String>,
    pub driver: Option<String>,
    pub drm_nodes: Vec<String>,
    pub boot_vga: Option<bool>,
}

#[derive(Debug, Default)]
pub struct RawBlock {
    pub name: String,
    pub model: Option<String>,
    pub sys_path: Option<String>,
    pub sectors: Option<u64>,
    pub rotational: Option<bool>,
    pub partition: bool,
    pub parent: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct Cpu {
    pub architecture: String,
    pub vendor: Option<String>,
    pub model: Option<String>,
    pub logical_count: Option<usize>,
    pub physical_core_count: Option<usize>,
}

#[derive(Debug, Clone, Serialize, serde::Deserialize)]
pub struct Gpu {
    pub pci_address: Option<String>,
    pub vendor: Option<String>,
    pub vendor_id: Option<String>,
    pub device_id: Option<String>,
    pub model: Option<String>,
    pub driver: Option<String>,
    pub drm_nodes: Vec<String>,
    /// Firmware's boot VGA device, not a guess about the active compositor GPU.
    pub boot_vga: Option<bool>,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum StorageKind {
    Disk,
    Partition,
    Mapped,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Transport {
    Nvme,
    Sata,
    Virtio,
    Usb,
}

#[derive(Debug, Serialize)]
pub struct Storage {
    pub name: String,
    pub path: String,
    pub model: Option<String>,
    pub transport: Option<Transport>,
    pub size_bytes: Option<u64>,
    pub rotational: Option<bool>,
    pub kind: StorageKind,
    pub parent: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct Capabilities {
    pub uefi: Option<bool>,
    pub virtual_machine: Option<bool>,
    pub virtualization_type: Option<String>,
    pub container_type: Option<String>,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum IssueKind {
    Unavailable,
    Unknown,
    Error,
}

#[derive(Debug, Serialize)]
pub struct ProbeIssue {
    pub source: String,
    pub kind: IssueKind,
    pub message: String,
}

#[derive(Debug, Serialize)]
pub struct Hardware {
    pub schema_version: u32,
    pub cpu: Cpu,
    pub memory_bytes: Option<u64>,
    pub memory_available_bytes: Option<u64>,
    pub gpus: Option<Vec<Gpu>>,
    pub storage: Option<Vec<Storage>>,
    pub capabilities: Capabilities,
    pub issues: Vec<ProbeIssue>,
}

struct Discovery<'a> {
    root: &'a Path,
    issues: Vec<ProbeIssue>,
}

impl Discovery<'_> {
    fn issue(&mut self, path: &Path, kind: IssueKind, message: String) {
        self.issues.push(ProbeIssue {
            source: format!(
                "/{}",
                path.strip_prefix(self.root)
                    .unwrap_or(path)
                    .to_string_lossy()
                    .replace('\\', "/")
            ),
            kind,
            message,
        });
    }

    fn result<T>(&mut self, path: &Path, result: io::Result<T>, required: bool) -> Option<T> {
        match result {
            Ok(value) => Some(value),
            Err(error) => {
                let missing = error.kind() == io::ErrorKind::NotFound;
                if required || !missing {
                    self.issue(
                        path,
                        if missing {
                            IssueKind::Unavailable
                        } else {
                            IssueKind::Error
                        },
                        error.to_string(),
                    );
                }
                None
            }
        }
    }

    fn read(&mut self, path: &Path, required: bool) -> Option<String> {
        self.result(path, fs::read_to_string(path), required)
            .map(|s| s.trim().to_owned())
            .filter(|s| !s.is_empty())
    }

    fn entries(&mut self, path: &Path, required: bool) -> Option<Vec<PathBuf>> {
        let dir = self.result(path, fs::read_dir(path), required)?;
        let mut paths = Vec::new();
        for entry in dir {
            if let Some(entry) = self.result(path, entry, true) {
                paths.push(entry.path());
            }
        }
        paths.sort();
        Some(paths)
    }

    fn number(&mut self, path: &Path) -> Option<u64> {
        let value = self.read(path, false)?;
        match value.parse() {
            Ok(value) => Some(value),
            Err(_) => {
                self.issue(path, IssueKind::Unknown, "invalid unsigned integer".into());
                None
            }
        }
    }

    fn link_name(&mut self, path: &Path) -> Option<String> {
        self.result(path, fs::canonicalize(path), false)?
            .file_name()
            .map(|s| s.to_string_lossy().into_owned())
    }

    fn boolean(&mut self, path: &Path) -> Option<bool> {
        match self.number(path)? {
            0 => Some(false),
            1 => Some(true),
            _ => {
                self.issue(path, IssueKind::Unknown, "expected 0 or 1".into());
                None
            }
        }
    }
}

/// Resolve a partition's containing disk through sysfs, without requiring slaves.
/// Returns None for a disk. IO errors remain distinguishable from that case.
pub fn partition_parent(device: &Path) -> io::Result<Option<PathBuf>> {
    match fs::metadata(device.join("partition")) {
        Ok(_) => Ok(fs::canonicalize(device)?.parent().map(Path::to_path_buf)),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error),
    }
}

fn node_name(name: &str, prefix: &str) -> bool {
    name.strip_prefix(prefix)
        .is_some_and(|n| !n.is_empty() && n.bytes().all(|c| c.is_ascii_digit()))
}

fn pci_name(text: &str, vendor: &str, device: &str) -> Option<String> {
    let mut in_vendor = false;
    for line in text.lines() {
        if line.starts_with('#') || line.is_empty() {
            continue;
        }
        if !line.starts_with(char::is_whitespace) {
            in_vendor = line.split_whitespace().next() == Some(vendor);
        } else if in_vendor && line.starts_with('\t') && !line.starts_with("\t\t") {
            if let Some((id, name)) = line.trim().split_once(char::is_whitespace) {
                if id == device {
                    return Some(name.trim().to_owned());
                }
            }
        }
    }
    None
}

fn pci_id(value: Option<String>) -> Option<String> {
    let value = value?.to_ascii_lowercase();
    let digits = value.strip_prefix("0x").unwrap_or(&value);
    (digits.len() == 4 && digits.bytes().all(|b| b.is_ascii_hexdigit()))
        .then(|| format!("0x{digits}"))
}

/// The supplied root replaces / for captured proc/sysfs trees. No host files or
/// environment variables are consulted here.
pub fn discover(root: &Path) -> RawHardware {
    let mut d = Discovery {
        root,
        issues: Vec::new(),
    };
    let pci_ids = ["usr/share/hwdata/pci.ids", "usr/share/misc/pci.ids"]
        .iter()
        .find_map(|p| d.read(&root.join(p), false));
    let pci_dir = root.join("sys/bus/pci/devices");
    let mut pci = d.entries(&pci_dir, true).map(|paths| {
        let mut devices = Vec::new();
        for p in paths {
            let Some(class) = d.read(&p.join("class"), false) else {
                continue;
            };
            let class = u32::from_str_radix(class.trim_start_matches("0x"), 16).ok();
            if class.is_none_or(|c| c >> 16 != 3) {
                continue;
            }
            let vendor_id = pci_id(d.read(&p.join("vendor"), false));
            let device_id = pci_id(d.read(&p.join("device"), false));
            let model = match (&pci_ids, &vendor_id, &device_id) {
                (Some(ids), Some(v), Some(i)) => pci_name(ids, &v[2..], &i[2..]),
                _ => None,
            };
            devices.push(RawGpu {
                pci_address: p.file_name().map(|s| s.to_string_lossy().into_owned()),
                vendor_id,
                device_id,
                model,
                driver: d.link_name(&p.join("driver")),
                boot_vga: d.boolean(&p.join("boot_vga")),
                drm_nodes: Vec::new(),
            });
        }
        devices
    });
    // DRM also exposes non-PCI GPUs and virtio/platform devices.
    if let Some(nodes) = d.entries(&root.join("sys/class/drm"), false) {
        let devices = pci.get_or_insert_with(Vec::new);
        let mut drm_devices = Vec::<(PathBuf, usize)>::new();
        for node in nodes {
            let name = node.file_name().unwrap().to_string_lossy();
            if !node_name(&name, "card") && !node_name(&name, "renderD") {
                continue;
            }
            let Some(device) = d.result(
                &node.join("device"),
                fs::canonicalize(node.join("device")),
                false,
            ) else {
                continue;
            };
            // Walk ancestors to find the owning PCI function (virtio adds a level).
            let address = device
                .ancestors()
                .find(|p| {
                    p.parent() == Some(&pci_dir)
                        || p.join("class").is_file() && p.join("vendor").is_file()
                })
                .and_then(|p| p.file_name())
                .map(|s| s.to_string_lossy().into_owned());
            let index = devices
                .iter()
                .position(|gpu| address.is_some() && gpu.pci_address == address)
                .or_else(|| {
                    drm_devices
                        .iter()
                        .find(|(p, _)| *p == device)
                        .map(|(_, i)| *i)
                })
                .unwrap_or_else(|| {
                    let i = devices.len();
                    devices.push(RawGpu {
                        driver: d.link_name(&device.join("driver")),
                        ..Default::default()
                    });
                    i
                });
            if let Some(driver) = d.link_name(&device.join("driver")) {
                devices[index].driver = Some(driver);
            }
            drm_devices.push((device, index));
            devices[index].drm_nodes.push(format!("/dev/dri/{name}"));
        }
    }
    let class_blocks = root.join("sys/class/block");
    let block_dir = if class_blocks.is_dir() {
        class_blocks
    } else {
        root.join("sys/block")
    };
    let blocks = d.entries(&block_dir, true).map(|mut paths| {
        // /sys/block only lists disks. Include their partition children as fallback.
        if block_dir == root.join("sys/block") {
            for disk in paths.clone() {
                if let Some(children) = d.entries(&disk, false) {
                    paths.extend(
                        children
                            .into_iter()
                            .filter(|p| p.join("partition").is_file()),
                    );
                }
            }
        }
        let mut blocks = Vec::new();
        for p in paths {
            let name = p.file_name().unwrap().to_string_lossy().into_owned();
            if ["loop", "ram", "zram"]
                .iter()
                .any(|prefix| name.starts_with(prefix))
            {
                continue;
            }
            let parent = d.result(&p, partition_parent(&p), false).flatten();
            let metadata = parent.as_deref().unwrap_or(&p);
            let sys_path = d
                .result(&p, fs::canonicalize(&p), false)
                .map(|p| p.to_string_lossy().replace('\\', "/"));
            blocks.push(RawBlock {
                name,
                model: d.read(&metadata.join("device/model"), false),
                sys_path,
                sectors: d.number(&p.join("size")),
                rotational: d.boolean(&metadata.join("queue/rotational")),
                partition: p.join("partition").is_file(),
                parent: parent
                    .and_then(|p| p.file_name().map(|s| s.to_string_lossy().into_owned())),
            });
        }
        blocks.sort_by(|a, b| a.name.cmp(&b.name));
        blocks
    });
    let container = d.read(&root.join("run/systemd/container"), false);
    let firmware = root.join("sys/firmware");
    let uefi = d
        .result(&firmware, fs::read_dir(&firmware), true)
        .and_then(|_| {
            let path = firmware.join("efi");
            match fs::metadata(&path) {
                Ok(metadata) => Some(metadata.is_dir()),
                // Containers can mask EFI or load a kernel without guest firmware.
                Err(e) if e.kind() == io::ErrorKind::NotFound => {
                    container.is_none().then_some(false)
                }
                Err(e) => {
                    d.result::<()>(&path, Err(e), true);
                    None
                }
            }
        });
    RawHardware {
        cpuinfo: d.read(&root.join("proc/cpuinfo"), true),
        meminfo: d.read(&root.join("proc/meminfo"), true),
        pci,
        blocks,
        dmi_vendor: d.read(&root.join("sys/class/dmi/id/sys_vendor"), false),
        dmi_product: d.read(&root.join("sys/class/dmi/id/product_name"), false),
        hypervisor: d.read(&root.join("sys/hypervisor/type"), false),
        device_tree_compatible: d.read(&root.join("proc/device-tree/hypervisor/compatible"), false),
        container,
        uefi,
        issues: d.issues,
    }
}

fn field(text: &str, name: &str) -> Option<String> {
    text.lines().find_map(|line| {
        let (key, value) = line.split_once(':')?;
        (key.trim() == name && !value.trim().is_empty()).then(|| value.trim().to_owned())
    })
}

fn memory(text: &str, name: &str) -> Option<u64> {
    let value = field(text, name)?;
    let mut words = value.split_whitespace();
    let size = words.next()?.parse::<u64>().ok()?;
    (words.next()? == "kB" && words.next().is_none())
        .then(|| size.checked_mul(1024))
        .flatten()
}

fn cpu_counts(text: &str) -> (Option<usize>, Option<usize>) {
    let mut logical = BTreeSet::new();
    for line in text.lines() {
        if let Some((key, value)) = line.split_once(':') {
            if key.trim() == "processor" {
                let Ok(id) = value.trim().parse::<u32>() else {
                    return (None, None);
                };
                if !logical.insert(id) {
                    return (None, None);
                }
            }
        }
    }
    let mut cores = BTreeSet::new();
    let mut complete = true;
    let mut records = 0;
    for record in text.split("\n\n") {
        if field(record, "processor").is_none() {
            continue;
        }
        records += 1;
        match (
            field(record, "physical id").and_then(|s| s.parse::<u32>().ok()),
            field(record, "core id").and_then(|s| s.parse::<u32>().ok()),
        ) {
            (Some(socket), Some(core)) => {
                cores.insert((socket, core));
            }
            _ => complete = false,
        }
    }
    (
        (!logical.is_empty()).then_some(logical.len()),
        (complete && records == logical.len() && !cores.is_empty()).then_some(cores.len()),
    )
}

fn virtualization(raw: &RawHardware) -> Option<String> {
    if let Some(kind) = &raw.hypervisor {
        return Some(kind.to_ascii_lowercase());
    }
    if let Some(compatible) = &raw.device_tree_compatible {
        if compatible.split('\0').any(|s| s == "linux,kvm") {
            return Some("kvm".into());
        }
        if compatible.split('\0').any(|s| s.starts_with("xen,")) {
            return Some("xen".into());
        }
    }
    let dmi = format!(
        "{} {}",
        raw.dmi_vendor.as_deref().unwrap_or(""),
        raw.dmi_product.as_deref().unwrap_or("")
    )
    .to_ascii_lowercase();
    [
        ("vmware", "vmware"),
        ("virtualbox", "oracle"),
        ("innotek", "oracle"),
        ("microsoft corporation virtual machine", "microsoft"),
        ("parallels", "parallels"),
        ("qemu", "qemu"),
        ("kvm", "kvm"),
        ("xen", "xen"),
        ("bochs", "bochs"),
        ("google compute engine", "google"),
    ]
    .iter()
    .find_map(|(needle, kind)| dmi.contains(needle).then(|| (*kind).into()))
}

pub fn normalize(raw: RawHardware) -> Hardware {
    let cpuinfo = raw.cpuinfo.as_deref().unwrap_or("").replace("\r\n", "\n");
    let (logical_count, physical_core_count) = cpu_counts(&cpuinfo);
    let virtualization_type = virtualization(&raw);
    let hypervisor_flag = cpuinfo.lines().any(|line| {
        line.split_once(':').is_some_and(|(key, value)| {
            key.trim() == "flags" && value.split_whitespace().any(|f| f == "hypervisor")
        })
    });
    let mut issues = raw.issues;
    let memory_bytes = raw.meminfo.as_deref().and_then(|s| memory(s, "MemTotal"));
    let memory_available_bytes = raw
        .meminfo
        .as_deref()
        .and_then(|s| memory(s, "MemAvailable"));
    for name in ["MemTotal", "MemAvailable"] {
        if raw
            .meminfo
            .as_deref()
            .is_some_and(|s| field(s, name).is_some() && memory(s, name).is_none())
        {
            issues.push(ProbeIssue {
                source: "/proc/meminfo".into(),
                kind: IssueKind::Unknown,
                message: format!("invalid {name} byte count"),
            });
        }
    }
    Hardware {
        schema_version: 1,
        cpu: Cpu {
            architecture: std::env::consts::ARCH.into(),
            vendor: field(&cpuinfo, "vendor_id"),
            model: field(&cpuinfo, "model name")
                .or_else(|| field(&cpuinfo, "Hardware"))
                .or_else(|| field(&cpuinfo, "cpu model")),
            logical_count,
            physical_core_count,
        },
        memory_bytes,
        memory_available_bytes,
        gpus: raw.pci.map(|devices| {
            devices
                .into_iter()
                .map(|d| Gpu {
                    vendor: d
                        .vendor_id
                        .as_deref()
                        .and_then(|v| match v {
                            "0x1002" => Some("AMD"),
                            "0x10de" => Some("NVIDIA"),
                            "0x8086" => Some("Intel"),
                            "0x1af4" => Some("Virtio"),
                            "0x1234" => Some("QEMU"),
                            "0x15ad" => Some("VMware"),
                            "0x1414" => Some("Microsoft"),
                            "0x1b36" => Some("Red Hat"),
                            _ => None,
                        })
                        .map(str::to_owned),
                    pci_address: d.pci_address,
                    vendor_id: d.vendor_id,
                    device_id: d.device_id,
                    model: d.model,
                    driver: d.driver,
                    drm_nodes: d.drm_nodes,
                    boot_vga: d.boot_vga,
                })
                .collect()
        }),
        storage: raw.blocks.map(|devices| {
            devices
                .into_iter()
                .map(|d| {
                    let path = d.sys_path.as_deref().unwrap_or("");
                    let transport = if path.contains("/usb") {
                        Some(Transport::Usb)
                    } else if d.name.starts_with("nvme") {
                        Some(Transport::Nvme)
                    } else if path.contains("virtio") || d.name.starts_with("vd") {
                        Some(Transport::Virtio)
                    } else if path.contains("/ata") {
                        Some(Transport::Sata)
                    } else {
                        None
                    };
                    Storage {
                        path: format!("/dev/{}", d.name),
                        kind: if d.partition {
                            StorageKind::Partition
                        } else if d.name.starts_with("dm-") {
                            StorageKind::Mapped
                        } else {
                            StorageKind::Disk
                        },
                        name: d.name,
                        model: d.model,
                        transport,
                        size_bytes: d.sectors.and_then(|n| n.checked_mul(512)),
                        rotational: d.rotational,
                        parent: d.parent,
                    }
                })
                .collect()
        }),
        capabilities: Capabilities {
            uefi: raw.uefi,
            virtual_machine: (virtualization_type.is_some() || hypervisor_flag).then_some(true),
            virtualization_type,
            container_type: raw.container,
        },
        issues,
    }
}

pub fn probe() -> Hardware {
    normalize(discover(Path::new("/")))
}

#[cfg(test)]
mod tests;
