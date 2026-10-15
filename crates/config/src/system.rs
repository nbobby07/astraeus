//! User requests, separate from the release manifest and resolved package state.
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub const MAX_SYSTEM_CONFIG_BYTES: usize = 256 * 1024;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SystemConfig {
    pub schema_version: u32,
    #[serde(default, deserialize_with = "unique_set")]
    pub packages: BTreeSet<String>,
    #[serde(default, deserialize_with = "unique_set")]
    pub gaming: BTreeSet<String>,
    #[serde(default, deserialize_with = "unique_providers")]
    pub providers: BTreeMap<String, String>,
}

impl Default for SystemConfig {
    fn default() -> Self {
        Self {
            schema_version: 1,
            packages: BTreeSet::new(),
            gaming: BTreeSet::new(),
            providers: BTreeMap::new(),
        }
    }
}

fn unique_set<'de, D: Deserializer<'de>>(input: D) -> Result<BTreeSet<String>, D::Error> {
    let values = Vec::<String>::deserialize(input)?;
    let unique: BTreeSet<_> = values.iter().cloned().collect();
    if unique.len() != values.len() {
        return Err(serde::de::Error::custom("duplicate request"));
    }
    Ok(unique)
}

fn unique_providers<'de, D: Deserializer<'de>>(
    input: D,
) -> Result<BTreeMap<String, String>, D::Error> {
    struct Providers;
    impl<'de> serde::de::Visitor<'de> for Providers {
        type Value = BTreeMap<String, String>;
        fn expecting(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
            formatter.write_str("unique dependency-provider choices")
        }
        fn visit_map<M: serde::de::MapAccess<'de>>(
            self,
            mut input: M,
        ) -> Result<Self::Value, M::Error> {
            let mut choices = BTreeMap::new();
            while let Some((name, value)) = input.next_entry::<String, String>()? {
                if choices.insert(name, value).is_some() {
                    return Err(serde::de::Error::custom("duplicate provider choice"));
                }
            }
            Ok(choices)
        }
    }
    input.deserialize_map(Providers)
}

pub fn valid_package_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 128
        && name.as_bytes()[0].is_ascii_alphanumeric()
        && name.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || b"@._+-".contains(&byte)
        })
}

pub fn gaming_feature_packages(feature: &str) -> Result<BTreeSet<String>, String> {
    #[derive(Deserialize)]
    struct Catalog {
        profiles: BTreeMap<String, BTreeSet<String>>,
    }
    if feature == "heroic" {
        return Err(
            "Heroic requires Flatpak; only native repository features are supported".into(),
        );
    }
    let catalog: Catalog =
        serde_json::from_str(include_str!("../../distroctl/src/gaming/catalog.json"))
            .map_err(|error| format!("invalid bundled gaming catalog: {error}"))?;
    catalog
        .profiles
        .get(feature)
        .cloned()
        .ok_or_else(|| format!("unsupported gaming feature: {feature}"))
}

pub fn parse_system_toml(input: &str) -> Result<SystemConfig, String> {
    if input.len() > MAX_SYSTEM_CONFIG_BYTES {
        return Err("system configuration exceeds 256 KiB".into());
    }
    let config: SystemConfig = toml::from_str(input).map_err(|error| error.to_string())?;
    config.validate()?;
    Ok(config)
}

impl SystemConfig {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != 1 {
            return Err("unsupported system configuration schema".into());
        }
        if self.packages.len() > 1024 || self.providers.len() > 128 || self.gaming.len() > 7 {
            return Err("too many system configuration requests".into());
        }
        for name in self
            .packages
            .iter()
            .chain(self.providers.keys())
            .chain(self.providers.values())
        {
            if !valid_package_name(name) {
                return Err(format!(
                    "invalid canonical package or provider name: {name:?}"
                ));
            }
        }
        for feature in &self.gaming {
            gaming_feature_packages(feature)?;
        }
        Ok(())
    }

    pub fn to_toml(&self) -> Result<String, String> {
        self.validate()?;
        toml::to_string_pretty(self).map_err(|error| error.to_string())
    }

    pub fn request_owners(&self) -> Result<BTreeMap<String, BTreeSet<String>>, String> {
        self.validate()?;
        let mut owners = BTreeMap::<String, BTreeSet<String>>::new();
        for package in &self.packages {
            owners
                .entry(package.clone())
                .or_default()
                .insert(format!("package:{package}"));
        }
        for feature in &self.gaming {
            for package in gaming_feature_packages(feature)? {
                owners
                    .entry(package)
                    .or_default()
                    .insert(format!("gaming:{feature}"));
            }
        }
        Ok(owners)
    }

    pub fn requested_packages(&self) -> Result<BTreeSet<String>, String> {
        Ok(self.request_owners()?.into_keys().collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn config_round_trip_and_shared_feature_owners() {
        let config = parse_system_toml(
            "schema_version = 1\npackages = ['obs-studio']\ngaming = ['tools', 'mangohud']\n[providers]\nlib32-vulkan-driver = 'lib32-vulkan-radeon'\n",
        )
        .unwrap();
        assert_eq!(
            parse_system_toml(&config.to_toml().unwrap()).unwrap(),
            config
        );
        assert_eq!(config.request_owners().unwrap()["mangohud"].len(), 2);
        assert!(config.requested_packages().unwrap().contains("obs-studio"));
        assert!(!config
            .requested_packages()
            .unwrap()
            .contains("lib32-vulkan-radeon"));
    }

    #[test]
    fn config_rejects_unknown_fields_unsupported_features_and_non_names() {
        assert!(serde_json::from_str::<SystemConfig>(
            r#"{"schema_version":1,"providers":{"virtual":"first","virtual":"second"}}"#
        )
        .is_err());
        for input in [
            "schema_version = 1\nschema_version = 1",
            "schema_version = 1\npackages = [1]",
            "schema_version = 1\npackages = [",
            "schema_version = 1\n[providers]\nlibgl = 'mesa'\nlibgl = 'mesa'",
            "schema_version = 1\n[providers]\n[providers]",
            "schema_version = 2",
            "schema_version = 1\ncommand = 'echo yes'",
            "schema_version = 1\npackages = ['steam', 'steam']",
            "schema_version = 1\ngaming = ['heroic']",
            "schema_version = 1\ngaming = ['unknown']",
            "schema_version = 1\npackages = ['--overwrite']",
            "schema_version = 1\npackages = ['../steam']",
            "schema_version = 1\npackages = ['Steam']",
            "schema_version = 1\npackages = ['extra/steam']",
            "schema_version = 1\n[providers]\nlibgl = 'sh;exit'",
        ] {
            assert!(parse_system_toml(input).is_err(), "{input}");
        }
        assert!(parse_system_toml(&" ".repeat(MAX_SYSTEM_CONFIG_BYTES + 1)).is_err());
    }
}
