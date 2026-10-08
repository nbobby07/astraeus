//! System snapshots and offline recovery for the qualified Phase 1 layout.
//! Package transactions must hold the same store lock while changing root/ESP.
use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::{Path, PathBuf},
};

mod system;
pub use system::{Commands, Manager, MutationGuard, Native};

pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;
pub const SUBVOLUMES: [(&str, &str); 6] = [
    ("@", "/"),
    ("@home", "/home"),
    ("@snapshots", "/.snapshots"),
    ("@log", "/var/log"),
    ("@cache", "/var/cache"),
    ("@containers", "/var/lib/containers"),
];
pub const UKI: &str = "EFI/Linux/astraeus-dev-linux.efi";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(transparent)]
pub struct SnapshotId(String);
impl SnapshotId {
    pub fn parse(value: &str) -> Result<Self> {
        require(
            !value.is_empty()
                && value.len() <= 80
                && value.bytes().all(|c| c.is_ascii_digit() || c == b'-'),
            "invalid snapshot ID",
        )?;
        Ok(Self(value.into()))
    }
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum Health {
    Unknown,
    Candidate,
    KnownGood,
    Bad,
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum Reason {
    Manual,
    PreUpdate,
    PostUpdate,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Subvolume {
    pub id: u64,
    pub uuid: String,
    pub parent_uuid: Option<String>,
    pub top_level: u64,
    pub read_only: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BootState {
    pub esp_uuid: String,
    pub sha256: String,
    pub relative_path: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub schema_version: u32,
    pub id: SnapshotId,
    pub created_unix_seconds: u64,
    pub filesystem_uuid: String,
    pub source_state: Subvolume,
    pub reason: Reason,
    pub transaction_id: Option<String>,
    pub root: Subvolume,
    pub health: Health,
    pub validation_evidence: Option<String>,
    pub boot: BootState,
}
impl Snapshot {
    pub fn validate(&self) -> Result<()> {
        SnapshotId::parse(self.id.as_str())?;
        require(self.schema_version == 1, "unsupported snapshot schema")?;
        require(
            uuid(&self.filesystem_uuid) && uuid(&self.root.uuid) && uuid(&self.source_state.uuid),
            "invalid filesystem/subvolume UUID",
        )?;
        require(
            self.root.id > 5
                && self.source_state.id > 5
                && self.root.id != self.source_state.id
                && self.root.top_level > 5
                && self.source_state.parent_uuid.as_deref().is_none_or(uuid)
                && self.source_state.top_level == 5
                && !self.source_state.read_only,
            "invalid source/root identity",
        )?;
        require(
            self.root.read_only
                && self.root.parent_uuid.as_deref() == Some(&self.source_state.uuid),
            "snapshot is not a read-only child of source",
        )?;
        require(
            self.boot.relative_path == UKI
                && !self.boot.esp_uuid.is_empty()
                && self.boot.sha256.len() == 64
                && self.boot.sha256.bytes().all(|c| c.is_ascii_hexdigit()),
            "invalid boot binding",
        )?;
        if let Some(id) = &self.transaction_id {
            text_field(id)?;
        }
        if self.health == Health::KnownGood {
            text_field(self.validation_evidence.as_deref().unwrap_or(""))?;
        }
        Ok(())
    }
    pub fn set_health(&mut self, health: Health, evidence: &str) -> Result<()> {
        text_field(evidence)?;
        // Failed states need a fresh candidate validation before promotion.
        require(
            !(self.health == Health::Bad && health == Health::KnownGood),
            "bad state must become candidate before revalidation",
        )?;
        self.health = health;
        self.validation_evidence = Some(evidence.into());
        self.validate()
    }
}

#[derive(Debug, Serialize)]
pub struct CreationPlan {
    pub source: PathBuf,
    pub store: PathBuf,
    pub filesystem_uuid: String,
    pub affected: Vec<String>,
    pub persistent: Vec<String>,
    pub read_only: bool,
}
#[derive(Debug, Serialize)]
pub struct RollbackPlan {
    pub current_state: Subvolume,
    pub target: Snapshot,
    pub affected: Vec<String>,
    pub persistent: Vec<String>,
    pub reboot_required: bool,
    pub execution_supported: bool,
    pub boot_implications: String,
    pub safety_checks: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct RollbackResult {
    pub plan: RollbackPlan,
    pub restored_state: Subvolume,
    pub previous_root: PathBuf,
    pub previous_uki: PathBuf,
    pub operation_id: String,
}

pub(crate) fn require(ok: bool, message: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(message.into())
    }
}
pub(crate) fn uuid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(i, c)| {
            if [8, 13, 18, 23].contains(&i) {
                c == b'-'
            } else {
                c.is_ascii_hexdigit()
            }
        })
}
pub(crate) fn text_field(value: &str) -> Result<()> {
    require(
        !value.trim().is_empty() && value.len() <= 4096 && !value.chars().any(char::is_control),
        "empty, oversized or control-containing metadata text",
    )
}
pub(crate) fn persistent() -> Vec<String> {
    SUBVOLUMES[1..]
        .iter()
        .map(|(s, m)| format!("{s}: {m}"))
        .collect()
}

/// Reject links, including links in existing ancestors. Managed paths are root-owned.
pub(crate) fn no_links(path: &Path) -> Result<()> {
    for p in path.ancestors() {
        match fs::symlink_metadata(p) {
            Ok(m) => require(!m.file_type().is_symlink(), "symlink in managed path")?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) => return Err(e.into()),
        }
    }
    Ok(())
}

/// systemd-stub 262 appends detected consoles only when the UKI has no console=.
/// Preserve every embedded token, including root/LUKS and the transaction marker.
/// See systemd v262 src/boot/console.c: cmdline_append_console().
pub(crate) fn boot_command_line_matches(embedded: &str, running: &str) -> bool {
    let expected: Vec<_> = embedded.split_whitespace().collect();
    let actual: Vec<_> = running.split_whitespace().collect();
    if expected.is_empty() {
        return false;
    }
    let Some(extra) = actual.strip_prefix(expected.as_slice()) else {
        return false;
    };
    if extra.is_empty() {
        return true;
    }
    if expected.iter().any(|word| word.starts_with("console=")) {
        return false;
    }
    let serial = |arg: &str| {
        matches!(
            arg,
            "console=uart,io,0x3f8"
                | "console=uart,io,0x2f8"
                | "console=uart,io,0x3e8"
                | "console=uart,io,0x2e8"
        )
    };
    match extra {
        [uart]
        | [uart, "console=tty0"]
        | [uart, "console=hvc0"]
        | [uart, "console=hvc0", "console=tty0"]
            if serial(uart) =>
        {
            true
        }
        ["console=hvc0"] | ["console=hvc0", "console=tty0"] => true,
        _ => false,
    }
}

/// Parse the small, documented `btrfs subvolume show` identity fields in C locale.
pub fn parse_subvolume(text: &str) -> Result<Subvolume> {
    let field = |key| -> Result<&str> {
        let values: Vec<_> = text
            .lines()
            .filter_map(|l| l.trim().split_once(':'))
            .filter(|(k, _)| *k == key)
            .map(|(_, v)| v.trim())
            .collect();
        require(values.len() == 1, "missing/duplicate Btrfs identity field")?;
        Ok(values[0])
    };
    let result = Subvolume {
        id: field("Subvolume ID")?.parse()?,
        uuid: field("UUID")?.into(),
        parent_uuid: match field("Parent UUID")? {
            "-" => None,
            v => Some(v.into()),
        },
        top_level: field("Top level ID")?.parse()?,
        read_only: match field("Flags")? {
            "readonly" => true,
            "-" => false,
            _ => return Err("unsupported subvolume flags".into()),
        },
    };
    require(
        uuid(&result.uuid) && result.parent_uuid.as_deref().is_none_or(uuid),
        "invalid Btrfs UUID",
    )?;
    Ok(result)
}

/// Read PE sections without invoking a tool that might rewrite its input UKI.
pub(crate) fn pe_section<'a>(bytes: &'a [u8], name: &[u8]) -> Result<&'a [u8]> {
    let range = |offset: usize, len: usize| -> Result<&[u8]> {
        bytes
            .get(offset..offset.checked_add(len).ok_or("PE overflow")?)
            .ok_or_else(|| "truncated PE image".into())
    };
    let u16_at = |o| -> Result<usize> { Ok(u16::from_le_bytes(range(o, 2)?.try_into()?) as usize) };
    let u32_at = |o| -> Result<usize> { Ok(u32::from_le_bytes(range(o, 4)?.try_into()?) as usize) };
    require(range(0, 2)? == b"MZ", "invalid UKI DOS header")?;
    let pe = u32_at(0x3c)?;
    require(
        pe <= bytes.len().saturating_sub(24) && range(pe, 4)? == b"PE\0\0",
        "invalid PE header",
    )?;
    require(u16_at(pe + 4)? == 0x8664, "UKI is not x86-64")?;
    let count = u16_at(pe + 6)?;
    let table = pe + 24 + u16_at(pe + 20)?;
    require(count <= 96, "too many PE sections")?;
    let mut found = None;
    for n in 0..count {
        let h = table + n * 40;
        let section_name = range(h, 8)?;
        if section_name.split(|v| *v == 0).next() == Some(name) {
            require(found.is_none(), "duplicate UKI section")?;
            let size = u32_at(h + 8)?;
            require(
                size > 0 && size <= u32_at(h + 16)?,
                "invalid UKI section size",
            )?;
            found = Some(range(u32_at(h + 20)?, size)?);
        }
    }
    found.ok_or_else(|| "required UKI section missing".into())
}

#[cfg(test)]
mod tests;
