//! Reusable read-only status model for the CLI and future UI.
use distro_hardware::{discover, normalize, Hardware};
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
    if device.join("partition").is_file() {
        let path = fs::canonicalize(device).ok()?;
        return encryption(path.parent()?, depth + 1);
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
            name: std::env::var("XDG_CURRENT_DESKTOP").ok(),
            session_type: std::env::var("XDG_SESSION_TYPE").ok(),
        },
    )
}

pub fn known(value: &Option<String>) -> &str {
    value.as_deref().unwrap_or("unknown")
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
        write(
            "sys/firmware/efi/efivars/StubInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f",
            b"bad",
        );
        assert!(collect(&root, desktop()).boot.stub.is_none());
        fs::remove_dir_all(root).unwrap();
    }
}
