"""Generate Calamares configuration and build its separate signed-package payload."""
import json
from pathlib import Path
import re
import shutil

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


def build_payload(out, profile, values, run, write, render):
    root = out / "installed-root"
    root.mkdir()
    names = (ROOT / "distro/installed/packages.x86_64").read_text().split()
    run("pacstrap", "-C", profile / "pacman.conf", "-c", "-G", "-M", root, *names)
    shutil.copytree(ROOT / "distro/installed", root / "usr/share/distro/install-inputs")
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
    # Packages are authenticated with the build keyring. Initialize a fresh installed keyring in Calamares.
    shutil.rmtree(root / "etc/pacman.d/gnupg", ignore_errors=True)
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
    with (out / "installed-packages.txt").open("w") as log:
        run("pacman", "--root", root, "-Q", stdout=log)
    target = profile / "airootfs/opt/distro/install-root.sfs"
    run("env", "-u", "SOURCE_DATE_EPOCH", "mksquashfs", root, target, "-noappend", "-comp", "xz", "-Xbcj", "x86", "-b", "1M",
        "-all-time", values["EPOCH"], "-mkfs-time", values["EPOCH"], "-processors", "2")
