"""Privileged installed-system finalization, called only after Calamares provisions accounts/filesystems."""
import json
import os
from pathlib import Path
import re
import subprocess


def run(*args):
    try:
        return subprocess.run([str(a) for a in args], check=True, text=True, capture_output=True).stdout.strip()
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"{args[0]} failed ({error.returncode}): {error.stderr.strip()}") from error


def uuid(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise ValueError("invalid partition UUID")
    return value


def kernel_command_line(partition):
    if partition.get("fs") != "btrfs" or partition.get("mountPoint") != "/":
        raise ValueError("root must be Btrfs")
    if "luksMapperName" in partition:
        return f'rd.luks.name={uuid(partition["luksUuid"])}=root root=/dev/mapper/root rootflags=subvol=@ rw'
    return f'root=UUID={uuid(partition["uuid"])} rootflags=subvol=@ rw'


def crypttab(text, partition):
    """Use the same root mapper name as sd-encrypt, avoiding a second unlock."""
    if "luksMapperName" not in partition:
        return text
    device = "UUID=" + uuid(partition["luksUuid"])
    lines = []
    found = False
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and not line.lstrip().startswith("#") and fields[1] == device:
            line = f"root {device} none luks"
            found = True
        lines.append(line)
    if not found:
        raise ValueError("encrypted root missing from Calamares crypttab")
    return "\n".join(lines) + "\n"


def fstab(text, partition):
    """Keep Calamares' six mounts on the same mapper as the UKI and crypttab."""
    if "luksMapperName" not in partition:
        return text
    source = "/dev/mapper/" + partition["luksMapperName"]
    lines = []
    for line in text.splitlines():
        fields = line.split()
        if fields and not line.lstrip().startswith("#") and fields[0] == source:
            fields[0] = "/dev/mapper/root"
            line = "\t".join(fields)
        lines.append(line)
    return "\n".join(lines) + "\n"


def write(root, path, value):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(value, encoding="utf-8", newline="\n")


def provision(target, partitions, keyboard=None, username=None):
    if os.geteuid() != 0 or not target:
        raise ValueError("a privileged Calamares target is required")
    root = Path(target).resolve(strict=True)
    if root == Path("/") or not os.path.ismount(root):
        raise ValueError("target must be a mounted installation root, never the live root")
    roots = [p for p in partitions if p.get("mountPoint") == "/"]
    if len(roots) != 1:
        raise ValueError("exactly one root partition required")
    partition = roots[0]
    command_line = kernel_command_line(partition)
    config = json.loads(Path("/usr/share/distro/installer/config.json").read_text())
    for subvolume in config["modules"]["mount"]["btrfsSubvolumes"]:
        mount = root / subvolume["mountPoint"].lstrip("/")
        actual = run("findmnt", "-rn", "-M", mount, "-o", "FSTYPE,FSROOT")
        if actual != "btrfs " + subvolume["subvolume"]:
            raise ValueError(f"unexpected filesystem/subvolume at {mount}: {actual}")
    if run("findmnt", "-rn", "-M", root / "efi", "-o", "FSTYPE") != "vfat":
        raise ValueError("an unencrypted FAT ESP must be mounted at /efi")
    if not Path("/sys/firmware/efi").is_dir():
        raise ValueError("UEFI installation required")
    run("arch-chroot", root, "/usr/bin/astraeus-secure-boot", "guard-legacy")
    luks = None
    if "luksMapperName" in partition:
        run("cryptsetup", "isLuks", "--type", "luks2", partition["device"])
        metadata = json.loads(run("cryptsetup", "luksDump", "--dump-json-metadata", partition["device"]))
        luks = {"uuid": uuid(partition["luksUuid"]), "keyslots": {
            key: {"kdf": value.get("kdf"), "area": value.get("area")} for key, value in metadata["keyslots"].items()
        }, "segments": metadata["segments"]}
        if any(v["kdf"].get("type") != "argon2id" for v in luks["keyslots"].values()):
            raise ValueError("LUKS2 must retain cryptsetup's Argon2id default")
    fingerprint = (root / "usr/share/distro/repository-fingerprint").read_text().strip()
    if not re.fullmatch(r"[A-F0-9]{40}", fingerprint):
        raise ValueError("invalid repository signing fingerprint")
    (root / "etc/pacman.d/gnupg").mkdir(parents=True, exist_ok=True)
    for arguments in [("--init",), ("--populate", "archlinux"),
                      ("--add", "/usr/share/distro/repository-key.asc"), ("--lsign-key", fingerprint)]:
        run("arch-chroot", root, "pacman-key", *arguments)
    write(root, "etc/kernel/cmdline", command_line + "\n")
    write(root, "etc/crypttab", crypttab((root / "etc/crypttab").read_text(), partition))
    write(root, "etc/fstab", fstab((root / "etc/fstab").read_text(), partition))
    if keyboard and username:
        if not re.fullmatch(r"[a-z_][a-z0-9_-]*", username):
            raise ValueError("invalid installed username")
        layout, variant = keyboard
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", layout) or not re.fullmatch(r"[a-zA-Z0-9_-]*", variant or ""):
            raise ValueError("invalid keyboard selection")
        write(root, f"home/{username}/.config/kxkbrc", f"[Layout]\nUse=true\nLayoutList={layout}\nVariantList={variant or ''}\n")
        run("arch-chroot", root, "chown", "-R", f"{username}:{username}", f"/home/{username}/.config")
    # One Type #2 UKI. systemd-boot discovers /EFI/Linux/*.efi automatically.
    (root / "efi/EFI/Linux").mkdir(parents=True, exist_ok=True)
    product = json.loads((root / "usr/share/distro/installer-identity.json").read_text())
    entry = product["id"] + "-linux.efi"
    write(root, "efi/loader/loader.conf", f"default {entry}\ntimeout 3\nconsole-mode keep\neditor no\n")
    write(root, "etc/sddm.conf.d/10-astraeus.conf", "[General]\nDisplayServer=wayland\nGreeterEnvironment=QT_WAYLAND_SHELL_INTEGRATION=layer-shell\nInputMethod=\n[Wayland]\nCompositorCommand=kwin_wayland --no-lockscreen --no-global-shortcuts --locale1\n[Autologin]\nSession=plasma.desktop\n")
    write(root, "var/lib/sddm/state.conf", "[Last]\nSession=/usr/share/wayland-sessions/plasma.desktop\n")
    run("arch-chroot", root, "chown", "sddm:sddm", "/var/lib/sddm/state.conf")
    run("arch-chroot", root, "systemctl", "enable", "NetworkManager.service", "sddm.service", "systemd-timesyncd.service", "astraeus-confirm-boot.service")
    run("arch-chroot", root, "systemctl", "set-default", "graphical.target")
    run("arch-chroot", root, "systemctl", "--global", "enable", "pipewire.socket", "pipewire-pulse.socket", "wireplumber.service")
    run("arch-chroot", root, "bootctl", "--esp-path=/efi", "install")
    run("arch-chroot", root, "mkinitcpio", "-P")
    uki = root / "efi/EFI/Linux" / entry
    if not uki.is_file() or uki.stat().st_size < 1024 * 1024:
        raise ValueError("UKI generation did not produce a boot artifact")
    run("arch-chroot", root, "ukify", "inspect", "/" + uki.relative_to(root).as_posix())
    write(root, "var/log/installer/storage.json", json.dumps({
        "root": {k: partition.get(k) for k in ["device", "uuid", "fs", "mountPoint", "luksUuid"]},
        "subvolumes": config["modules"]["mount"]["btrfsSubvolumes"], "luks": luks,
        "kernel_command_line": command_line,
    }, indent=2) + "\n")
