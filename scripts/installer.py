"""Generate Calamares configuration and build its separate signed-package payload."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[1]
SUBVOLUMES = {"/@": "/", "/@home": "/home", "/@snapshots": "/.snapshots",
              "/@log": "/var/log", "/@cache": "/var/cache", "/@containers": "/var/lib/containers"}


def configuration(path=None):
    data = json.loads((path or ROOT / "distro/installer/config.json").read_text())
    modules = data["modules"]
    partition = modules["partition"]
    actual = {s["subvolume"]: s["mountPoint"] for s in modules["mount"]["btrfsSubvolumes"]}
    if actual != SUBVOLUMES or len(modules["mount"]["btrfsSubvolumes"]) != 6:
        raise ValueError("installer must define exactly the six sibling Btrfs subvolumes")
    if (partition["luksGeneration"] != "luks2" or partition["defaultFileSystemType"] != "btrfs"
            or partition["requiredPartitionTableType"] != "gpt" or partition["efi"]["mountPoint"] != "/efi"
            or partition["efi"]["minimumSize"] != "1GiB"):
        raise ValueError("unsupported storage/boot configuration")
    if modules["users"]["doAutologin"] or modules["users"]["setRootPassword"]:
        raise ValueError("installed account policy must require user authentication and lock root")
    sequence = data["settings"]["sequence"]
    expected = ["astraeus-preflight", "partition", "mount", "unpackfs", "machineid", "locale", "keyboard", "localecfg", "fstab", "users", "astraeus", "umount"]
    if sequence[1]["exec"] != expected or data["settings"]["dont-chroot"]:
        raise ValueError("unsafe installer module ordering")
    return data


def stage(live, values, write):
    data = configuration()
    data["modules"]["partition"]["partitionLayout"][0]["name"] = values["NAME"]
    data["modules"]["users"]["hostname"]["template"] = "${login}-" + values["ID"].removesuffix("-dev")
    config = live / "etc/calamares"
    write(config / "settings.conf", json.dumps(data["settings"], indent=2) + "\n")
    for name, settings in data["modules"].items():
        write(config / "modules" / (name + ".conf"), json.dumps(settings, indent=2) + "\n")
    shutil.copytree(ROOT / "distro/installer/modules", config / "modules", dirs_exist_ok=True)
    write(live / "usr/share/distro/installer/provision.py", (ROOT / "scripts/provision.py").read_text())
    write(live / "usr/share/distro/installer/config.json", json.dumps(data, indent=2) + "\n")
    write(live / "usr/share/distro/installer-identity.json", json.dumps({"id": values["ID"], "name": values["NAME"]}) + "\n")
    branding = {
        "componentName": "astraeus", "welcomeStyleCalamares": False,
        "windowSize": "900px,620px", "windowPlacement": "center",
        "strings": {"productName": values["NAME"], "shortProductName": values["NAME"],
                    "version": values["VERSION"], "shortVersion": values["VERSION"],
                    "versionedName": values["NAME"] + " " + values["VERSION"],
                    "shortVersionedName": values["NAME"], "bootloaderEntryName": values["NAME"]},
        "images": {"productIcon": "logo.svg", "productLogo": "logo.svg", "productWelcome": "logo.svg"},
        "slideshow": ["logo.svg"],
        "style": {},
        "uploadServer": {"type": "none"},
    }
    write(config / "branding/astraeus/branding.desc", json.dumps(branding, indent=2) + "\n")
    write(config / "branding/astraeus/logo.svg", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="#254e70"/><path d="M25 75 50 20 75 75 M35 55H65" fill="none" stroke="white" stroke-width="8"/></svg>\n')
    desktop = f'[Desktop Entry]\nType=Application\nName=Install {values["NAME"]}\nComment=Install the operating system. Disk encryption is recommended.\nExec=pkexec /usr/bin/calamares\nIcon=system-software-install\nTerminal=false\nCategories=System;\n'
    write(live / "usr/share/applications/astraeus-install.desktop", desktop)


def graphics_packages(bundles):
    manifest = json.loads((ROOT / "distro/graphics/bundles.json").read_text())
    selected = set(manifest["base"])
    for bundle in bundles:
        if bundle not in {"amd", "intel", "nouveau", "virtio", "software"}:
            raise ValueError("unsupported graphics bundle; NVIDIA activation needs module trust and transaction integration")
        selected.update(manifest["bundles"][bundle])
    return sorted(selected)


def gaming_packages(features):
    catalog = json.loads((ROOT / "crates/distroctl/src/gaming/catalog.json").read_text())
    selected = set()
    for feature in features:
        if feature not in catalog["profiles"] or feature == "heroic":
            raise ValueError("unsupported native gaming feature; Heroic requires separate reviewed Flatpak setup")
        selected.update(catalog["profiles"][feature])
    return sorted(selected)


def metadata_fields(text):
    fields = {}
    current = None
    for line in text.split("\n"):
        if not line:
            current = None
        elif re.fullmatch(r"%[A-Z0-9_]+%", line):
            if current is not None or line in fields:
                raise ValueError("invalid or duplicate package metadata field")
            current = line
            fields[current] = []
        elif current is None:
            raise ValueError("invalid or duplicate package metadata field")
        else:
            fields[current].append(line)
    return fields


def one_field(fields, name):
    values = fields.get("%" + name + "%", [])
    if len(values) != 1 or not values[0] or len(values[0]) > 256 or any(c.isspace() or ord(c) < 32 for c in values[0]):
        raise ValueError("missing or invalid package metadata: " + name)
    return values[0]


def installed_state(root):
    observed = {}
    for entry in sorted((root / "var/lib/pacman/local").iterdir()):
        if entry.name == "ALPM_DB_VERSION":
            continue
        desc = entry / "desc"
        if entry.is_symlink() or desc.is_symlink() or not desc.is_file() or desc.stat().st_size > 1024 * 1024:
            raise ValueError("invalid installed package metadata")
        fields = metadata_fields(desc.read_text(encoding="utf-8"))
        name, version = [one_field(fields, key) for key in ("NAME", "VERSION")]
        # libalpm leaves its default explicit reason out of local desc records.
        reason = one_field(fields, "REASON") if "%REASON%" in fields else "0"
        if not re.fullmatch(r"[a-z0-9][a-z0-9@._+-]{0,127}", name) or name in observed or reason not in {"0", "1"}:
            raise ValueError("invalid installed package identity or reason")
        observed[name] = {"version": version, "reason": "explicit" if reason == "0" else "dependency"}
    if not observed:
        raise ValueError("installed package database is empty")
    return dict(sorted(observed.items()))


def locked_packages(root, installed):
    expected = json.loads((ROOT / "distro/repo/archive.lock.json").read_text())["databases"]
    repositories, resolution = {}, {}
    for repository in ("distro", "core", "extra", "multilib"):
        path = root / "var/lib/pacman/sync" / (repository + ".db")
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("invalid installed repository database: " + repository)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if repository != "distro" and expected.get(repository) != digest:
            raise ValueError("installed repository differs from approved archive: " + repository)
        repositories[repository] = "sha256:" + digest
        signature = path.with_name(path.name + ".sig")
        if signature.exists() or signature.is_symlink():
            if signature.is_symlink() or not signature.is_file() or signature.stat().st_size > 1024 * 1024:
                raise ValueError("invalid repository signature file: " + repository)
            repositories[repository + "-signature"] = "sha256:" + hashlib.sha256(signature.read_bytes()).hexdigest()
        seen = set()
        with tarfile.open(path) as archive:
            for member in archive:
                if not member.name.endswith("/desc"):
                    continue
                if not member.isfile() or member.size > 256 * 1024:
                    raise ValueError("invalid repository package metadata")
                fields = metadata_fields(archive.extractfile(member).read().decode("utf-8"))
                name = one_field(fields, "NAME")
                if name in seen:
                    raise ValueError("duplicate repository package: " + name)
                seen.add(name)
                if name not in installed or name in resolution:
                    continue
                version, sha256 = one_field(fields, "VERSION"), one_field(fields, "SHA256SUM")
                if installed[name]["version"] == version:
                    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
                        raise ValueError("invalid repository package hash: " + name)
                    resolution[name] = {"version": version, "repository": repository, "sha256": sha256}
    if resolution.keys() != installed.keys():
        raise ValueError("installed packages lack exact approved repository records: " + ", ".join(sorted(installed.keys() - resolution.keys())))
    return dict(sorted(repositories.items())), dict(sorted(resolution.items()))


def seed_management(root, before, graphics, gaming, write, pacman_configuration):
    after = installed_state(root)
    if any(after.get(name) != package for name, package in before.items()):
        raise ValueError("gaming payload changed the protected base/graphics package state")
    catalog = json.loads((ROOT / "crates/distroctl/src/gaming/catalog.json").read_text())
    owners = {}
    for feature in sorted(set(gaming)):
        for package in catalog["profiles"][feature]:
            owners.setdefault(package, set()).add("gaming:" + feature)
    if not owners.keys() <= after.keys():
        raise ValueError("gaming payload lacks a requested package")
    repositories, resolution = locked_packages(root, after)
    if not pacman_configuration or len(pacman_configuration.encode("utf-8")) > 1024 * 1024:
        raise ValueError("missing or oversized effective installed pacman configuration")
    repositories["pacman-config"] = "sha256:" + hashlib.sha256(pacman_configuration.encode("utf-8")).hexdigest()
    repositories = dict(sorted(repositories.items()))
    config = {"schema_version": 1, "packages": [], "gaming": sorted(set(gaming)), "providers": {}}
    packages = {name: {**package, "owners": sorted(owners.get(name, []))}
                for name, package in after.items() if name not in before}
    # Field order is the Rust ManagementState/receipt order; its compact JSON is the shared digest.
    state = {"schema_version": 1, "applied": config, "packages": packages,
             "protected": sorted(before), "repositories": repositories, "resolution": resolution,
             "resolved_providers": {}}
    digest = "sha256:" + hashlib.sha256(json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    lock = {"schema_version": 1, "management_sha256": digest, "repositories": repositories,
            "packages": resolution, "providers": state["resolved_providers"], "configured_providers": config["providers"]}
    write(root / "etc/astraeus/system.toml", "schema_version = 1\npackages = []\ngaming = " + json.dumps(config["gaming"]) + "\n\n[providers]\n")
    write(root / "var/lib/astraeus/management/system.lock", json.dumps(lock, indent=2) + "\n")
    write(root / "var/lib/astraeus/management/state.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    write(root / "usr/share/distro/install-inputs/management.json", json.dumps({"schema_version": 1,
          "graphics_bundles": sorted(set(graphics)), "gaming_features": config["gaming"],
          "protected_baseline": before, "final_packages": after, "management_sha256": digest}, indent=2) + "\n")


def build_payload(out, profile, values, run, write, render, graphics=(), gaming=()):
    graphics_names = graphics_packages(graphics)
    gaming_names = gaming_packages(gaming)
    root = out / "installed-root"
    root.mkdir()
    names = sorted(set((ROOT / "distro/installed/packages.x86_64").read_text().split()) | set(graphics_names))
    run("pacstrap", "-C", profile / "pacman.conf", "-c", "-G", "-M", root, *names)
    baseline = installed_state(root)
    extra = sorted(set(gaming_names) - baseline.keys())
    if extra:
        run("pacstrap", "-C", profile / "pacman.conf", "-c", "-G", "-M", root, *extra)
    shutil.copytree(ROOT / "distro/installed", root / "usr/share/distro/install-inputs")
    write(root / "usr/share/distro/install-inputs/graphics.json", json.dumps({"schema_version": 1,
          "bundles": sorted(set(graphics)), "packages": graphics_names}, indent=2) + "\n")
    write(root / "usr/share/distro/install-inputs/gaming.json", json.dumps({"schema_version": 1,
          "features": sorted(set(gaming)), "packages": gaming_names}, indent=2) + "\n")
    write(root / "etc/mkinitcpio.conf", (ROOT / "distro/installed/mkinitcpio.conf").read_text())
    write(root / "etc/mkinitcpio.d/linux.preset", render((ROOT / "distro/installed/linux.preset.in").read_text(), values))
    for hook in (ROOT / "distro/installed").glob("*.hook"):
        write(root / "etc/pacman.d/hooks" / hook.name, hook.read_text())
    write(root / "etc/xdg/kdeglobals", (profile / "airootfs/etc/xdg/kdeglobals").read_text())
    write(root / "etc/os-release", f'NAME="{values["NAME"]}"\nPRETTY_NAME="{values["NAME"]}"\nID={values["ID"]}\nID_LIKE=arch\nVERSION_ID={values["VERSION"]}\nVARIANT_ID=development\n')
    write(root / "etc/pacman.conf", render((ROOT / "distro/archiso/pacman.conf.in").read_text(), dict(values, KEYRING="/etc/pacman.d/gnupg", REPO="/opt/distro/repo")))
    shutil.copytree(profile / "airootfs/opt/distro/repo", root / "opt/distro/repo")
    shutil.copytree(profile / "airootfs/usr/share/distro", root / "usr/share/distro", dirs_exist_ok=True)
    write(root / "usr/share/distro/repository-fingerprint", values["FINGERPRINT"] + "\n")
    # pacman-conf requires GPGDir to exist. Ship no build keys; Calamares initializes fresh keys.
    keyring = root / "etc/pacman.d/gnupg"
    shutil.rmtree(keyring, ignore_errors=True)
    keyring.mkdir(mode=0o755)
    keyring.chmod(0o755)  # pacman-key preserves this directory's mode; public queries need access.
    write(root / "etc/machine-id", "")
    dbus_id = root / "var/lib/dbus/machine-id"
    dbus_id.unlink(missing_ok=True)
    dbus_id.parent.mkdir(parents=True, exist_ok=True)
    dbus_id.symlink_to("/etc/machine-id")
    (root / "etc/resolv.conf").unlink(missing_ok=True)
    (root / "etc/resolv.conf").symlink_to("/run/NetworkManager/resolv.conf")
    write(root / "var/log/pacman.log", "")
    for file in (root / "var/lib/pacman/local").glob("*/desc"):
        write(file, re.sub(r"(%INSTALLDATE%\n)\d+", lambda m: m[1] + str(values["EPOCH"]), file.read_text()))
    shadow = root / "etc/shadow"
    lines = []
    for line in shadow.read_text().splitlines():
        fields = line.split(":")
        if len(fields) >= 3:
            fields[2] = str(int(values["EPOCH"]) // 86400)
        lines.append(":".join(fields))
    write(shadow, "\n".join(lines) + "\n")
    for file in [*root.glob("boot/initramfs-*.img"), root / "var/cache/ldconfig/aux-cache", root / "var/lib/systemd/random-seed"]:
        file.unlink(missing_ok=True)
    for file in (root / "var/cache/pacman/pkg").glob("*"):
        if file.is_file():
            file.unlink()
    # Do not include live installer code/config in the installed OS.
    shutil.rmtree(root / "usr/share/distro/installer")
    configuration = run("arch-chroot", root, "/usr/bin/pacman-conf", capture_output=True, text=True)
    seed_management(root, baseline, graphics, gaming, write, configuration.stdout)
    # The installed Rust reader verifies the cross-language digest and all three seeded files.
    run("arch-chroot", root, "/usr/bin/distroctl", "system", "export", "--json")
    with (out / "installed-packages.txt").open("w") as log:
        run("pacman", "--root", root, "-Q", stdout=log)
    target = profile / "airootfs/opt/distro/install-root.sfs"
    run("env", "-u", "SOURCE_DATE_EPOCH", "mksquashfs", root, target, "-noappend", "-comp", "xz", "-Xbcj", "x86", "-b", "1M",
        "-all-time", values["EPOCH"], "-mkfs-time", values["EPOCH"], "-processors", "2")
