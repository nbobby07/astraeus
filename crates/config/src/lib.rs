//! Bootstrap release metadata. This is not the future desired-system-state model.
use serde::{Deserialize, Serialize};

pub const BUNDLED: &str = include_str!("../../../distro/branding/project.toml");

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Project {
    pub schema_version: u32,
    pub identity: Identity,
    pub build: Build,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Identity {
    pub id: String,
    pub name: String,
    pub version: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Build {
    pub architecture: String,
    pub archive_date: String,
    pub source_date_epoch: u64,
    pub archiso_version: String,
    pub rust_version: String,
}

/// Parsing is deliberately separate from semantic validation.
pub fn parse_toml(input: &str) -> Result<Project, toml::de::Error> {
    toml::from_str(input)
}

fn token(value: &str) -> bool {
    !value.is_empty()
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b".-".contains(&c))
        && value.as_bytes()[0].is_ascii_alphanumeric()
}

impl Project {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != 1 {
            return Err("schema_version must be 1".into());
        }
        if !token(&self.identity.id) || !token(&self.identity.version) {
            return Err("identity.id and version must be safe nonempty filename tokens".into());
        }
        if self.identity.name.is_empty()
            || !self
                .identity
                .name
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b" .-".contains(&c))
        {
            return Err(
                "identity.name must contain only ASCII letters, digits, spaces, dots or hyphens"
                    .into(),
            );
        }
        if self.build.architecture != "x86_64" {
            return Err("only x86_64 is supported".into());
        }
        if !token(&self.build.archiso_version) || !token(&self.build.rust_version) {
            return Err("build tool versions must be safe nonempty tokens".into());
        }
        let date: Vec<_> = self.build.archive_date.split('/').collect();
        if date.len() != 3
            || date
                .iter()
                .zip([4, 2, 2])
                .any(|(v, len)| v.len() != len || !v.bytes().all(|c| c.is_ascii_digit()))
        {
            return Err("archive_date must be YYYY/MM/DD".into());
        }
        let year: u32 = date[0].parse().unwrap();
        let month: usize = date[1].parse().unwrap();
        let day: u32 = date[2].parse().unwrap();
        let leap =
            year.is_multiple_of(4) && (!year.is_multiple_of(100) || year.is_multiple_of(400));
        let days = [
            31,
            if leap { 29 } else { 28 },
            31,
            30,
            31,
            30,
            31,
            31,
            30,
            31,
            30,
            31,
        ];
        if year < 2015 || !(1..=12).contains(&month) || day == 0 || day > days[month - 1] {
            return Err("archive_date is not a valid archive calendar date".into());
        }
        // Count UTC days without adding a date dependency for one build metadata field.
        let preceding_years: u64 = (1970..year)
            .map(|y| {
                if y.is_multiple_of(4) && (!y.is_multiple_of(100) || y.is_multiple_of(400)) {
                    366
                } else {
                    365
                }
            })
            .sum();
        let expected = (preceding_years
            + u64::from(days[..month - 1].iter().sum::<u32>())
            + u64::from(day - 1))
            * 86400;
        if self.build.source_date_epoch != expected {
            return Err("source_date_epoch must be archive_date at midnight UTC".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metadata_rejects_invalid_inputs() {
        let mut project = parse_toml(BUNDLED).unwrap();
        project.validate().unwrap();
        project.identity.id = "../escape".into();
        assert!(project.validate().is_err());
        assert!(parse_toml(&format!("unknown = true\n{BUNDLED}")).is_err());
        assert!(parse_toml("[identity]\nname = 4").is_err());
        for (from, to) in [
            ("schema_version = 1", "schema_version = 2"),
            ("x86_64", "aarch64"),
            ("2026/10/01", "2026/02/30"),
            ("2026/10/01", "2026/00/01"),
            ("2026/10/01", "2026/10/02"),
            ("1790812800", "0"),
        ] {
            assert!(
                parse_toml(&BUNDLED.replace(from, to))
                    .unwrap()
                    .validate()
                    .is_err(),
                "{to}"
            );
        }
    }
}
