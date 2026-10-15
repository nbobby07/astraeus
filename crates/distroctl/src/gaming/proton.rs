//! Bounded metadata inspection only. Never execute tools, load Steam credentials or follow scripts.
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeSet,
    fs,
    io::Read,
    path::{Path, PathBuf},
};

const LIMIT: usize = 256 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tool {
    pub kind: String,
    pub name: String,
    pub path: PathBuf,
    pub version: Option<String>,
    pub provenance: String,
}

pub(super) fn metadata(path: &Path) -> Result<String, String> {
    let stat = fs::symlink_metadata(path).map_err(|e| format!("{}: {e}", path.display()))?;
    if !stat.is_file() || stat.len() > LIMIT as u64 {
        return Err(format!(
            "{}: metadata must be a bounded regular file",
            path.display()
        ));
    }
    let mut text = String::new();
    fs::File::open(path)
        .and_then(|f| f.take(LIMIT as u64 + 1).read_to_string(&mut text))
        .map_err(|e| format!("{}: {e}", path.display()))?;
    if text.len() > LIMIT {
        return Err("metadata exceeded size limit".into());
    }
    Ok(text)
}

#[derive(Debug)]
enum Value {
    Text(String),
    Object(Vec<(String, Value)>),
}

// Steam's metadata subset uses quoted key/value pairs and braces, with // comments.
fn vdf(text: &str) -> Result<Vec<(String, Value)>, String> {
    let mut chars = text.chars().peekable();
    let mut tokens = vec![];
    while let Some(c) = chars.next() {
        match c {
            c if c.is_whitespace() => (),
            '/' if chars.next_if_eq(&'/').is_some() => {
                for c in chars.by_ref() {
                    if c == '\n' {
                        break;
                    }
                }
            }
            '{' | '}' => tokens.push((false, c.to_string())),
            '"' => {
                let mut word = String::new();
                let mut closed = false;
                while let Some(c) = chars.next() {
                    match c {
                        '"' => {
                            closed = true;
                            break;
                        }
                        '\\' => {
                            let escaped = chars.next().ok_or("truncated VDF escape")?;
                            if !matches!(escaped, '"' | '\\') {
                                word.push('\\');
                            }
                            word.push(escaped);
                        }
                        c => word.push(c),
                    }
                }
                if !closed {
                    return Err("unterminated VDF string".into());
                }
                tokens.push((true, word));
            }
            _ => return Err("unsupported VDF token".into()),
        }
        if tokens.len() > 8192 {
            return Err("VDF token limit exceeded".into());
        }
    }
    fn object(
        tokens: &[(bool, String)],
        index: &mut usize,
        depth: usize,
    ) -> Result<Vec<(String, Value)>, String> {
        if depth > 12 {
            return Err("VDF nesting limit exceeded".into());
        }
        let mut result: Vec<(String, Value)> = vec![];
        while let Some((quoted, key)) = tokens.get(*index) {
            if !quoted && key == "}" && depth > 0 {
                *index += 1;
                return Ok(result);
            }
            if !quoted {
                return Err("expected VDF key".into());
            }
            let key = key.clone();
            if result
                .iter()
                .any(|(existing, _)| existing.eq_ignore_ascii_case(&key))
            {
                return Err("duplicate VDF key".into());
            }
            *index += 1;
            let (quoted, value) = tokens.get(*index).ok_or("missing VDF value")?;
            *index += 1;
            let value = if *quoted {
                Value::Text(value.clone())
            } else if value == "{" {
                Value::Object(object(tokens, index, depth + 1)?)
            } else {
                return Err("expected VDF value".into());
            };
            result.push((key, value));
        }
        if depth > 0 {
            return Err("unclosed VDF object".into());
        }
        Ok(result)
    }
    object(&tokens, &mut 0, 0)
}

fn child<'a>(object: &'a [(String, Value)], key: &str) -> Option<&'a [(String, Value)]> {
    object.iter().find_map(|(k, v)| match v {
        Value::Object(o) if k.eq_ignore_ascii_case(key) => Some(o.as_slice()),
        _ => None,
    })
}

fn string<'a>(object: &'a [(String, Value)], key: &str) -> Option<&'a str> {
    object.iter().find_map(|(k, v)| match v {
        Value::Text(s) if k.eq_ignore_ascii_case(key) => Some(s.as_str()),
        _ => None,
    })
}

fn regular(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok_and(|s| s.is_file())
}

fn inspect(path: &Path, custom: bool) -> Result<Option<Tool>, String> {
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .ok_or("non-UTF8 tool directory")?;
    if !custom && !name.starts_with("Proton") {
        return Ok(None);
    }
    if !regular(&path.join("proton")) {
        return Ok(None);
    }
    let meta_path = path.join(if custom {
        "compatibilitytool.vdf"
    } else {
        "toolmanifest.vdf"
    });
    let object = vdf(&metadata(&meta_path)?)?;
    if custom {
        let tools = child(&object, "compatibilitytools")
            .and_then(|o| child(o, "compat_tools"))
            .ok_or("missing compatibilitytools/compat_tools metadata")?;
        if tools.is_empty()
            || tools
                .iter()
                .any(|(_, value)| !matches!(value, Value::Object(_)))
        {
            return Err("empty or malformed compatibility tool metadata".into());
        }
    } else if child(&object, "manifest").is_none() {
        return Err("missing Proton tool manifest".into());
    }
    let version = if path
        .join("version")
        .try_exists()
        .map_err(|e| e.to_string())?
    {
        Some(
            metadata(&path.join("version"))?
                .trim()
                .chars()
                .take(256)
                .collect(),
        )
    } else {
        None
    };
    Ok(Some(Tool {
        kind: if !custom {
            "steam"
        } else if name.starts_with("GE-Proton") || name.contains("-GE-") {
            "ge"
        } else {
            "custom"
        }
        .into(),
        name: name.into(),
        path: path.to_owned(),
        version,
        provenance:
            "unverified local metadata; directory names do not authenticate publisher or build"
                .into(),
    }))
}

/// Inspect default native Steam roots plus libraryfolders.vdf. Missing roots are normal.
/// Custom root paths must be chosen by the caller, never a privileged execution input.
pub fn discover_tools(roots: &[PathBuf]) -> (Vec<Tool>, Vec<String>) {
    let mut issues = vec![];
    let mut locations = BTreeSet::new();
    for root in roots {
        match root.try_exists() {
            Ok(false) => continue,
            Err(e) => {
                issues.push(format!("{}: {e}", root.display()));
                continue;
            }
            Ok(true) => (),
        }
        locations.insert((root.join("compatibilitytools.d"), true));
        locations.insert((root.join("steamapps/common"), false));
        let folders = root.join("steamapps/libraryfolders.vdf");
        match folders.try_exists() {
            Ok(false) => (),
            Err(e) => issues.push(format!("{}: {e}", folders.display())),
            Ok(true) => match metadata(&folders).and_then(|s| vdf(&s)) {
                Err(e) => issues.push(e),
                Ok(object) => match child(&object, "libraryfolders") {
                    None => issues.push("missing libraryfolders object".into()),
                    Some(libraries) => {
                        for (key, value) in libraries {
                            if key.parse::<u32>().is_err() {
                                continue;
                            }
                            let path = match value {
                                Value::Text(s) => Some(s.as_str()),
                                Value::Object(o) => string(o, "path"),
                            };
                            if let Some(path) = path {
                                if Path::new(path).is_absolute()
                                    && !path.chars().any(char::is_control)
                                {
                                    locations
                                        .insert((Path::new(path).join("steamapps/common"), false));
                                } else {
                                    issues.push(
                                        "relative or control-bearing Steam library path ignored"
                                            .into(),
                                    );
                                }
                            } else {
                                issues.push("Steam library path missing".into());
                            }
                        }
                    }
                },
            },
        }
    }
    let mut tools = vec![];
    let mut seen = BTreeSet::new();
    for (location, custom) in locations {
        let entries = match fs::read_dir(&location) {
            Ok(entries) => entries,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => continue,
            Err(e) => {
                issues.push(format!("{}: {e}", location.display()));
                continue;
            }
        };
        for (index, entry) in entries.enumerate() {
            if index == 2048 {
                issues.push("Steam directory entry limit exceeded".into());
                break;
            }
            let result = (|| {
                let entry = entry.map_err(|e| e.to_string())?;
                let kind = entry.file_type().map_err(|e| e.to_string())?;
                if kind.is_symlink() {
                    return Err(format!(
                        "{}: linked tool/game directory not inspected",
                        entry.path().display()
                    ));
                }
                if !kind.is_dir() {
                    return Ok(None);
                }
                let path = entry.path().canonicalize().map_err(|e| e.to_string())?;
                if !seen.insert(path.clone()) {
                    return Ok(None);
                }
                inspect(&path, custom)
            })();
            match result {
                Ok(Some(tool)) => tools.push(tool),
                Ok(None) => (),
                Err(e) => issues.push(e),
            }
        }
    }
    tools.sort_by(|a, b| a.path.cmp(&b.path));
    issues.sort();
    issues.dedup();
    (tools, issues)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn metadata_parser_is_bounded_and_rejects_ambiguity() {
        for malformed in [
            "\"a\"",
            "\"a\" {",
            "}",
            "\"a\" \"1\" \"a\" \"2\"",
            "\"path\" \"1\" \"PATH\" \"2\"",
            "\"x\" \"unclosed",
            "#include file",
        ] {
            assert!(vdf(malformed).is_err(), "{malformed}");
        }
        assert!(vdf(&format!("{}{}", "\"x\" {".repeat(14), "}".repeat(14))).is_err());
        let parsed = vdf("// comment\n\"a\" { \"path\" \"/tmp/test\\\"name\" }").unwrap();
        assert_eq!(
            string(child(&parsed, "a").unwrap(), "path"),
            Some("/tmp/test\"name")
        );
    }
}
