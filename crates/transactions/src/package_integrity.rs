//! Read-only evidence for conservative removal of previously managed packages.
use crate::Result;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PackageIntegrity {
    pub removable: bool,
    pub digest: String,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IntegrityReport {
    pub schema_version: u32,
    pub packages: BTreeMap<String, PackageIntegrity>,
}

impl IntegrityReport {
    pub fn digest(&self) -> String {
        format!(
            "sha256:{:x}",
            Sha256::digest(serde_json::to_vec(self).expect("integrity report serializes"))
        )
    }
}

pub(crate) fn valid_digest(value: &str) -> bool {
    value.strip_prefix("sha256:").is_some_and(|hash| {
        hash.len() == 64
            && hash
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    })
}

#[cfg(any(target_os = "linux", test))]
fn decode(bytes: &[u8], candidates: &BTreeMap<String, String>) -> Result<IntegrityReport> {
    if bytes.len() > 1024 * 1024 {
        return Err("package integrity report exceeded its size limit".into());
    }
    let report: IntegrityReport =
        serde_json::from_slice(bytes).map_err(|_| "invalid package integrity report")?;
    if report.schema_version != 1
        || !report.packages.keys().eq(candidates.keys())
        || report.packages.values().any(|package| {
            !valid_digest(&package.digest)
                || package.detail.is_empty()
                || package.detail.len() > 2048
                || package.detail.chars().any(char::is_control)
        })
    {
        return Err("incomplete or unsupported package integrity report".into());
    }
    Ok(report)
}

/// Inspects only installed packages in the current root. Unverifiable packages are retained;
/// failure of the fixed inspector itself stops planning before any removal is authorized.
pub fn inspect(candidates: &BTreeMap<String, String>) -> Result<IntegrityReport> {
    if candidates.len() > 1024
        || candidates.iter().any(|(name, version)| {
            !distro_config::valid_package_name(name)
                || version.is_empty()
                || version.len() > 256
                || version
                    .chars()
                    .any(|c| c.is_control() || c.is_whitespace() || c == '/' || c == '\\')
        })
    {
        return Err("invalid package integrity candidates".into());
    }
    if candidates.is_empty() {
        return Ok(IntegrityReport {
            schema_version: 1,
            packages: BTreeMap::new(),
        });
    }
    #[cfg(target_os = "linux")]
    {
        use std::io::Write;
        use std::process::{Command, Stdio};
        let request = serde_json::to_vec(candidates).map_err(|error| error.to_string())?;
        let mut child = Command::new("/usr/bin/python3")
            .args(["-I", "-S", "-c", include_str!("package_integrity.py")])
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("LC_ALL", "C")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| format!("cannot start package integrity inspector: {error}"))?;
        if let Err(error) = child
            .stdin
            .take()
            .expect("requested inspector stdin")
            .write_all(&request)
        {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("cannot send package integrity request: {error}"));
        }
        let output = child
            .wait_with_output()
            .map_err(|error| format!("package integrity inspector failed: {error}"))?;
        if !output.status.success() {
            return Err("package integrity inspector failed; removal is refused".into());
        }
        decode(&output.stdout, candidates)
    }
    #[cfg(not(target_os = "linux"))]
    {
        Err("installed package integrity inspection requires Linux".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn report_requires_exact_candidate_coverage_and_valid_evidence() {
        let candidates = [("fixture".into(), "1-1".into())].into();
        let report = IntegrityReport {
            schema_version: 1,
            packages: [(
                "fixture".into(),
                PackageIntegrity {
                    removable: false,
                    digest: format!("sha256:{}", "a".repeat(64)),
                    detail: "changed package file".into(),
                },
            )]
            .into(),
        };
        let bytes = serde_json::to_vec(&report).unwrap();
        assert_eq!(decode(&bytes, &candidates).unwrap(), report);
        assert!(decode(&bytes, &BTreeMap::new()).is_err());
        let mut tampered = report.clone();
        tampered.packages.get_mut("fixture").unwrap().removable = true;
        assert_ne!(tampered.digest(), report.digest());
        tampered.packages.get_mut("fixture").unwrap().digest = "sha256:unverified".into();
        assert!(decode(&serde_json::to_vec(&tampered).unwrap(), &candidates).is_err());
        tampered = report;
        tampered.schema_version = 2;
        assert!(decode(&serde_json::to_vec(&tampered).unwrap(), &candidates).is_err());
    }

    #[test]
    fn empty_inspection_is_portable_and_invalid_names_cannot_be_arguments() {
        assert!(inspect(&BTreeMap::new()).unwrap().packages.is_empty());
        assert!(inspect(&[("--config".into(), "1".into())].into()).is_err());
        assert!(inspect(&[("fixture".into(), "../../etc".into())].into()).is_err());
    }
}
