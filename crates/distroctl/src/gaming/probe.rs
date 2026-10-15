use super::*;
use distro_transactions::pacman::{parse_current, CommandRunner, NativeRunner};
use std::{
    env, fs,
    path::{Path, PathBuf},
};

/// The only package command used by gaming inspection is a read-only query.
pub fn installed_packages(
    runner: &mut impl CommandRunner,
) -> Result<BTreeMap<String, String>, String> {
    let output = runner.run("/usr/bin/pacman", &["--query".into()])?;
    if !output.success {
        return Err("Installed package query failed; state remains unknown".into());
    }
    Ok(parse_current(&output.stdout)?.packages)
}

pub fn collect() -> Observations {
    let mut obs = Observations {
        mangohud_config: Check::new(State::Unknown, "User configuration has not been inspected"),
        ..Default::default()
    };
    if !cfg!(target_os = "linux") {
        obs.issues
            .push("Gaming inspection requires an installed Astraeus Linux user session.".into());
        return obs;
    }
    match installed_packages(&mut NativeRunner) {
        Ok(packages) => obs.packages = Some(packages),
        Err(e) => obs.issues.push(e),
    }
    match NativeRunner.run("/usr/bin/pacman-conf", &["--repo-list".into()]) {
        Ok(output) if output.success => {
            obs.repositories = Some(output.stdout.lines().map(str::to_owned).collect())
        }
        _ => obs.issues.push(
            "Repository list unavailable; trust and snapshot alignment are not checked by status."
                .into(),
        ),
    }
    let present = |name| env::var_os(name).is_some_and(|s| !s.is_empty());
    obs.session_type = env::var("XDG_SESSION_TYPE").ok();
    obs.display = present("DISPLAY");
    obs.wayland_display = present("WAYLAND_DISPLAY");
    obs.session_bus = present("DBUS_SESSION_BUS_ADDRESS");
    obs.steam_launcher = launcher(Path::new("/usr/bin/steam"));
    // Root must not inspect or create a user's Steam state using inherited environment paths.
    let user_session = fs::read_to_string("/proc/self/status")
        .ok()
        .is_some_and(|s| {
            s.lines()
                .find_map(|l| l.strip_prefix("Uid:"))
                .is_some_and(|ids| {
                    let ids: Vec<_> = ids.split_whitespace().collect();
                    ids.len() == 4 && ids[0] != "0" && ids[0] == ids[1]
                })
        });
    if !user_session {
        obs.issues.push(
            "User metadata inspection skipped for root or unknown UID; rerun as the desktop user."
                .into(),
        );
        return obs;
    }
    let home = env::var_os("HOME")
        .map(PathBuf::from)
        .filter(|p| p.is_absolute());
    if let Some(home) = home {
        let data = env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .filter(|p| p.is_absolute())
            .unwrap_or_else(|| home.join(".local/share"));
        let roots = [
            data.join("Steam"),
            home.join(".local/share/Steam"),
            home.join(".steam/root"),
            home.join(".steam/steam"),
        ];
        let (tools, issues) = discover_tools(&roots);
        obs.tools = tools;
        obs.tools_complete = issues.is_empty();
        obs.issues.extend(issues);
        let config = env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .filter(|p| p.is_absolute())
            .unwrap_or_else(|| home.join(".config"));
        obs.mangohud_config = inspect_mangohud(&config.join("MangoHud/MangoHud.conf"));
    } else {
        obs.issues
            .push("HOME is absent or relative; user metadata inspection skipped.".into());
    }
    obs
}

fn launcher(path: &Path) -> Option<bool> {
    match fs::metadata(path) {
        Ok(stat) => {
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                Some(stat.is_file() && stat.permissions().mode() & 0o111 != 0)
            }
            #[cfg(not(unix))]
            {
                Some(stat.is_file())
            }
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Some(false),
        Err(_) => None,
    }
}

pub(super) fn inspect_mangohud(path: &Path) -> Check {
    match path.try_exists() {
        Ok(false) => Check::new(State::NotInstalled, "No user MangoHud config; upstream defaults apply. gaming mangohud-config prints a minimal optional template"),
        Ok(true) => match proton::metadata(path) {
            Ok(_) => Check::new(State::Configured, "User MangoHud config is readable; upstream parses its options at game launch. Overlay remains untested"),
            Err(e) => Check::new(State::Unknown, e),
        },
        Err(e) => Check::new(State::Unknown, e.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn config_is_optional_and_never_written() {
        let path = env::temp_dir().join(format!("astraeus-mangohud-{}", std::process::id()));
        assert!(!path.exists());
        assert_eq!(inspect_mangohud(&path).state, State::NotInstalled);
        assert!(!path.exists());
        fs::write(&path, MANGOHUD_CONFIG).unwrap();
        assert_eq!(inspect_mangohud(&path).state, State::Configured);
        assert_eq!(fs::read_to_string(&path).unwrap(), MANGOHUD_CONFIG);
        fs::write(&path, vec![b'x'; 300_000]).unwrap();
        assert_eq!(inspect_mangohud(&path).state, State::Unknown);
        fs::remove_file(path).unwrap();
    }
}
