//! Boot bindings are authoritative here; snapshot health and transaction evidence
//! remain in their Phase 2 stores. Counters are observations of BLS filenames.
use crate::{require, uuid, Result, SnapshotId, Subvolume};
use serde::{Deserialize, Serialize};

pub const TRIES: u32 = 3;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LoaderTrust {
    pub schema_version: u32,
    pub systemd_version: u32,
    pub loader_verified: bool,
    pub firmware_trusted: bool,
}
impl LoaderTrust {
    pub fn validate(&self) -> Result<()> {
        require(
            self.schema_version == 1
                && self.systemd_version == 262
                && self.loader_verified
                && self.firmware_trusted,
            "systemd 262 loader trust is not established",
        )
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct GenerationId(SnapshotId);
impl GenerationId {
    pub fn parse(value: &str) -> Result<Self> {
        Ok(Self(SnapshotId::parse(value)?))
    }
    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }
    pub fn entry(&self) -> String {
        format!("astraeus-{}.conf", self.as_str())
    }
    pub fn artifact(&self) -> String {
        format!("EFI/Astraeus/{}.efi", self.as_str())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum RootKind {
    Current,
    Retained,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Generation {
    pub schema_version: u32,
    pub id: GenerationId,
    pub snapshot: SnapshotId,
    pub root: Subvolume,
    pub root_kind: RootKind,
    pub filesystem_uuid: String,
    pub esp_uuid: String,
    pub uki_sha256: String,
    pub embedded_cmdline: String,
    pub prior_known_good: Option<GenerationId>,
}
impl Generation {
    pub fn validate(&self) -> Result<()> {
        GenerationId::parse(self.id.as_str())?;
        SnapshotId::parse(self.snapshot.as_str())?;
        require(
            self.schema_version == 1 && self.id.as_str() == self.snapshot.as_str(),
            "invalid generation schema or snapshot reference",
        )?;
        require(
            uuid(&self.filesystem_uuid)
                && uuid(&self.root.uuid)
                && self.root.parent_uuid.as_deref().is_none_or(uuid)
                && self.root.id > 5
                && !self.root.read_only
                && !self.esp_uuid.is_empty()
                && self.uki_sha256.len() == 64
                && self.uki_sha256.bytes().all(|b| b.is_ascii_hexdigit()),
            "invalid generation identity or digest",
        )?;
        require(
            (self.root_kind == RootKind::Current) == self.prior_known_good.is_some(),
            "candidate requires a prior generation; retained root cannot have one",
        )?;
        let words: Vec<_> = self.embedded_cmdline.split_whitespace().collect();
        let selection = match self.root_kind {
            RootKind::Current => "rootflags=subvol=@".into(),
            RootKind::Retained => format!("rootflags=subvolid={}", self.root.id),
        };
        require(
            words.iter().filter(|s| s.starts_with("rootflags=")).count() == 1
                && words.contains(&selection.as_str()),
            "generation root selection mismatch",
        )?;
        require(
            words.iter().filter(|s| s.starts_with("root=")).count() == 1
                && (words.contains(&format!("root=UUID={}", self.filesystem_uuid).as_str())
                    || words.contains(&"root=/dev/mapper/root")),
            "generation filesystem selection mismatch",
        )?;
        if let Some(prior) = &self.prior_known_good {
            GenerationId::parse(prior.as_str())?;
            require(
                prior != &self.id && self.root_kind == RootKind::Current,
                "invalid prior generation",
            )?;
        }
        Ok(())
    }
    pub fn entry_text(&self) -> String {
        let title = match self.root_kind {
            RootKind::Current => "Astraeus",
            RootKind::Retained => "Astraeus Previous Known Good (Recovery)",
        };
        format!(
            "title {title}\nversion {}\nsort-key astraeus\nuki /{}\n",
            self.id.as_str(),
            self.id.artifact()
        )
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Selection {
    pub schema_version: u32,
    pub current: Option<GenerationId>,
    pub previous: GenerationId,
}
impl Selection {
    pub fn validate(&self) -> Result<()> {
        GenerationId::parse(self.previous.as_str())?;
        require(
            self.schema_version == 1 && self.current.as_ref() != Some(&self.previous),
            "invalid generation selection",
        )?;
        if let Some(id) = &self.current {
            GenerationId::parse(id.as_str())?;
        }
        Ok(())
    }
    pub fn loader_config(&self) -> String {
        let preferred = self
            .current
            .as_ref()
            .map(|id| format!("preferred {}\n", id.entry()))
            .unwrap_or_default();
        format!("{preferred}default {}\ntimeout 3\nconsole-mode keep\neditor no\nauto-entries no\nauto-firmware yes\n", self.previous.entry())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "kebab-case", deny_unknown_fields)]
pub enum BootCount {
    Uncounted,
    Counted { left: u32, done: u32 },
}
impl BootCount {
    pub fn parse(id: &GenerationId, filename: &str) -> Result<Self> {
        if filename == id.entry() {
            return Ok(Self::Uncounted);
        }
        let prefix = format!("astraeus-{}+", id.as_str());
        let tag = filename
            .strip_prefix(&prefix)
            .and_then(|s| s.strip_suffix(".conf"))
            .ok_or("foreign boot entry")?;
        let (left, done) = tag.split_once('-').unwrap_or((tag, "0"));
        let number = |s: &str| -> Result<u32> {
            require(
                !s.is_empty()
                    && s.bytes().all(|b| b.is_ascii_digit())
                    && (s == "0" || !s.starts_with('0')),
                "invalid boot counter",
            )?;
            Ok(s.parse()?)
        };
        let (left, done) = (number(left)?, number(done)?);
        require(
            left <= TRIES && done <= TRIES && left + done == TRIES,
            "boot counter differs from attempt budget",
        )?;
        Ok(Self::Counted { left, done })
    }
}

/// Returned by the native provider on each verification, never trusted from stored metadata.
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TrustVerdict {
    pub schema_version: u32,
    pub sha256: String,
    pub signature_verified: bool,
    pub firmware_trusted: bool,
}
impl TrustVerdict {
    pub fn require_trusted(&self, digest: &str) -> Result<()> {
        require(
            self.schema_version == 1
                && self.sha256.len() == 64
                && self.sha256.bytes().all(|byte| byte.is_ascii_hexdigit())
                && self.sha256 == digest
                && self.signature_verified
                && self.firmware_trusted,
            "boot artifact is not signature-verified and firmware-trusted",
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn upstream_counter_transitions_and_exhaustion() {
        let id = GenerationId::parse("1-2-3").unwrap();
        for (tag, left, done) in [("3", 3, 0), ("2-1", 2, 1), ("1-2", 1, 2), ("0-3", 0, 3)] {
            assert_eq!(
                BootCount::parse(&id, &format!("astraeus-1-2-3+{tag}.conf")).unwrap(),
                BootCount::Counted { left, done }
            );
        }
        assert_eq!(
            BootCount::parse(&id, &id.entry()).unwrap(),
            BootCount::Uncounted
        );
        for tag in [
            "",
            "03",
            "4",
            "0-0",
            "2-2",
            "-1",
            "1-4294967295",
            "3-0.conf/../",
        ] {
            assert!(BootCount::parse(&id, &format!("astraeus-1-2-3+{tag}.conf")).is_err());
        }
        assert!(GenerationId::parse("../root").is_err());
    }
    #[test]
    fn preferred_respects_assessment_default_preserves_fallback() {
        let selection = Selection {
            schema_version: 1,
            current: Some(GenerationId::parse("2").unwrap()),
            previous: GenerationId::parse("1").unwrap(),
        };
        assert!(selection
            .loader_config()
            .starts_with("preferred astraeus-2.conf\ndefault astraeus-1.conf\n"));
        assert!(TrustVerdict {
            schema_version: 1,
            sha256: "a".repeat(64),
            signature_verified: false,
            firmware_trusted: true
        }
        .require_trusted(&"a".repeat(64))
        .is_err());
    }
}
