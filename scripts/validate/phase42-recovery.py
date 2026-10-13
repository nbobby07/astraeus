"""Candidate-only, RAM-verified recovery media for disposable Phase 4.2 VMs.

Linux tools: xorriso, unsquashfs, cpio, ukify dependencies, sbsigntools,
openssl, dosfstools, mtools, gdisk. Creates only a new regular image file.
The accepted candidate baseline supplies the public certificate identity.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

OFFSET = 1024 * 1024
MINIMUM_SIZE = 4 * 1024**3
FAT_FILE_LIMIT = 2**32 - 1
GUARD_ORIGIN_SHA256 = "23298042ca035c8b2b1e2360e5a6bda66db94fe55d8dc32e035740c937c3c0d0"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(value, count=64):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{' + str(count) + '}', value),
            'invalid lowercase hexadecimal source identity')
    return value


def regular(path, private=False):
    path = Path(path)
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and not path.is_symlink() and metadata.st_nlink == 1,
            'input must be a single regular file: ' + str(path))
    if private:
        require(metadata.st_mode & 0o077 == 0, 'private key is accessible to group/others')
        if hasattr(os, 'geteuid'):
            require(metadata.st_uid == os.geteuid(), 'private key must belong to the validation operator')
    return path.resolve(strict=True)


def baseline_identity(manifest, source, iso):
    identity(source, 40)
    identity(iso)
    require(isinstance(manifest, dict) and type(manifest.get('schema_version')) is int
            and manifest.get('schema_version') == 1
            and manifest.get('kind') == 'phase42-fresh-candidate-payload'
            and manifest.get('accepted') is True, 'an accepted fresh Phase 4.2 baseline is required')
    inputs = manifest.get('inputs', {})
    require(source == manifest.get('source_commit') and source in inputs.get('source_commits', []),
            'baseline belongs to a different source candidate')
    require(inputs.get('iso', {}).get('sha256') == iso, 'baseline belongs to a different candidate ISO')
    pin = identity(manifest.get('signer_sha256'))
    require(manifest.get('public_fingerprints', {}).get('db') == pin, 'baseline signing identities disagree')
    cli = identity(manifest.get('installed_binaries', {}).get('distroctl'))
    return pin, cli


def image_size(rootfs_bytes, uki_bytes):
    require(type(rootfs_bytes) is int and type(uki_bytes) is int
            and 0 < rootfs_bytes <= FAT_FILE_LIMIT and 0 < uki_bytes <= FAT_FILE_LIMIT,
            'recovery files must each fit the FAT32 single-file limit')
    # Two MiB reserve the GPT boundaries; an additional 128 MiB covers FAT metadata.
    needed = rootfs_bytes + uki_bytes + 128 * OFFSET + 2 * OFFSET
    return max(MINIMUM_SIZE, ((needed + OFFSET - 1) // OFFSET) * OFFSET)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def guard_hook(original, expected):
    identity(expected)
    anchor = '    img_loopdev="$(losetup --find --show --read-only -- "${img}")"'
    if original.count(anchor) != 1:
        raise ValueError("unsupported ArchISO mount hook")
    guard = '''    # Verify the RAM copy, so removing/changing the USB cannot replace verified bytes.
    [ "${copytoram}" = y ] && [ "${img}" = /run/archiso/copytoram/airootfs.sfs ] || launch_interactive_shell
    echo 'ASTRAEUS: verifying live filesystem in RAM...'
    printf '%s  %s\\n' '@HASH@' "${img}" | sha256sum -c - || launch_interactive_shell
    mkdir -p /sys/firmware/efi/efivars
    mountpoint -q /sys/firmware/efi/efivars || mount -t efivarfs efivarfs /sys/firmware/efi/efivars || launch_interactive_shell
    [ "$(busybox tail -c 1 /sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c | busybox base64)" = AQ== ] || launch_interactive_shell
    [ "$(busybox tail -c 1 /sys/firmware/efi/efivars/SetupMode-8be4df61-93ca-11d2-aa0d-00e098032b8c | busybox base64)" = AA== ] || launch_interactive_shell
    echo 'ASTRAEUS_SECURE_LIVE_OK: SecureBoot=1 SetupMode=0 rootfs=verified-in-RAM'
'''.replace("@HASH@", expected)
    refusal = '''
# Authentication failures must never fall through to an unverified root or recovery shell.
launch_interactive_shell() {
    echo 'ASTRAEUS_SECURE_LIVE_REFUSED: verification or required boot step failed; powering off.'
    sleep 10
    poweroff -f
    while :; do sleep 60; done
}
'''
    return original.replace(anchor, guard + anchor) + refusal


def copied_digest(fat, member):
    """Hash actual FAT bytes without allocating a second SquashFS staging copy."""
    process = subprocess.Popen(['mtype', '-i', fat, member], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        digest = hashlib.file_digest(process.stdout, 'sha256').hexdigest()
        process.stdout.close()
        require(process.wait(timeout=120) == 0, 'cannot read assembled FAT member: ' + member)
        return digest
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def public_der(key=None, cert=None):
    require((key is None) != (cert is None), 'choose one public-key source')
    if key is not None:
        return subprocess.check_output(['openssl', 'pkey', '-in', str(key), '-passin', 'pass:',
                                        '-pubout', '-outform', 'DER'], timeout=30)
    pem = subprocess.check_output(['openssl', 'x509', '-in', str(cert), '-pubkey', '-noout'], timeout=30)
    return subprocess.check_output(['openssl', 'pkey', '-pubin', '-outform', 'DER'], input=pem, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, required=True)
    parser.add_argument("--iso-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform == 'linux' and os.geteuid() == 0, 'run only on the disposable Linux validator as root')
    for tool in ['xorriso', 'unsquashfs', 'bash', 'cpio', 'python3', 'sbsign', 'sbverify', 'openssl',
                 'sgdisk', 'mkfs.vfat', 'mmd', 'mcopy', 'mtype']:
        require(shutil.which(tool), 'missing recovery builder tool: ' + tool)
    args.iso, args.key = regular(args.iso), regular(args.key, private=True)
    baseline = args.baseline.resolve(strict=True)
    manifest_path = regular(baseline / 'baseline.json')
    require(manifest_path.stat().st_size <= 1024 * 1024, 'oversized baseline manifest')
    manifest = json.loads(manifest_path.read_text())
    pin, cli_sha256 = baseline_identity(manifest, args.source_commit, args.iso_sha256)
    certificate = regular(baseline / 'public-owner/db.crt')
    der = subprocess.check_output(['openssl', 'x509', '-in', str(certificate), '-outform', 'DER'])
    require(hashlib.sha256(der).hexdigest() == pin, 'public certificate is not this baseline owner')
    require(public_der(key=args.key) == public_der(cert=certificate), 'private key is not this baseline owner')
    require(digest(args.iso) == identity(args.iso_sha256), 'candidate ISO SHA-256 mismatch')
    out = args.output.resolve()
    require(not baseline.is_relative_to(out) and not out.is_relative_to(baseline),
            'recovery output and accepted baseline must be separate')
    require(not args.key.is_relative_to(out) and not args.iso.is_relative_to(out),
            'recovery output must not contain private keys or input images')
    args.output.mkdir(mode=0o755, parents=True, exist_ok=False)
    run("openssl", "x509", "-in", certificate, "-checkend", "86400", "-noout")
    run("xorriso", "-osirrox", "on", "-indev", args.iso, "-extract", "/arch", out / "arch")
    sfs = out / "arch/x86_64/airootfs.sfs"
    regular(sfs)
    require(0 < sfs.stat().st_size <= FAT_FILE_LIMIT, 'candidate live filesystem does not fit FAT32')
    extracted = {}
    for member, name in [("usr/bin/ukify", "ukify"),
                         ("usr/lib/systemd/boot/efi/linuxx64.efi.stub", "stub.efi"),
                         ("usr/lib/initcpio/hooks/archiso", "archiso-original"),
                         ("usr/lib/os-release", "os-release"), ("usr/bin/distroctl", "distroctl")]:
        with (out / name).open("wb") as stream:
            run("unsquashfs", "-cat", sfs, member, stdout=stream)
        extracted[member] = digest(out / name)
    require(extracted['usr/bin/distroctl'] == cli_sha256,
            'live coordinator binary differs from the accepted installed candidate')
    root_hash = digest(sfs)
    overlay = out / "overlay"
    (overlay / "hooks").mkdir(parents=True)
    (overlay / "hooks/archiso").write_text(guard_hook((out / "archiso-original").read_text(), root_hash))
    (overlay / "hooks/archiso").chmod(0o755)
    run("bash", "-n", overlay / "hooks/archiso")
    with (out / "guard.cpio").open("wb") as stream:
        run("cpio", "-o", "-H", "newc", "--reproducible", cwd=overlay,
            input=b"hooks\nhooks/archiso\n", stdout=stream)
    cmdline = "archisobasedir=arch archisolabel=ASTRAEUS_SB copytoram=y cow_spacesize=2G console=tty0 console=ttyS0,115200n8"
    (out / "cmdline").write_text(cmdline + "\n")
    run("python3", out / "ukify", "--config=/dev/null", "--stub", out / "stub.efi",
        "--linux", out / "arch/boot/x86_64/vmlinuz-linux",
        "--initrd", out / "arch/boot/x86_64/initramfs-linux.img", "--initrd", out / "guard.cpio",
        "--cmdline", "@" + str(out / "cmdline"), "--os-release", "@" + str(out / "os-release"),
        "--output", out / "live-unsigned.efi", "build")
    run("sbsign", "--key", args.key, "--cert", certificate, "--output", out / "BOOTX64.EFI", out / "live-unsigned.efi")
    run("sbverify", "--cert", certificate, out / "BOOTX64.EFI")
    (out / "Astraeus-Live.cer").write_bytes(der)
    size = image_size(sfs.stat().st_size, (out / 'BOOTX64.EFI').stat().st_size)
    require(shutil.disk_usage(out).free >= sfs.stat().st_size + (out / 'BOOTX64.EFI').stat().st_size + 128 * OFFSET,
            'insufficient free space for the recovery image')
    image = out / "recovery.img"
    with image.open("xb") as stream:
        stream.truncate(size)
    run("sgdisk", "--clear", "--new=1:2048:-2048", "--typecode=1:ef00", "--change-name=1:Astraeus Live", image)
    run("mkfs.vfat", "--offset=2048", "-F", "32", "-n", "ASTRAEUS_SB", image, (size - 2 * OFFSET) // 1024)
    fat = str(image) + "@@" + str(OFFSET)
    run("mmd", "-i", fat, "::/EFI", "::/EFI/BOOT", "::/arch", "::/arch/x86_64")
    for source, target in [(out / "BOOTX64.EFI", "::/EFI/BOOT/BOOTX64.EFI"),
                           (out / "Astraeus-Live.cer", "::/Astraeus-Live.cer"),
                           (sfs, "::/arch/x86_64/airootfs.sfs")]:
        run("mcopy", "-i", fat, source, target)
    run("sgdisk", "--verify", image)
    for member, expected in [('::/EFI/BOOT/BOOTX64.EFI', digest(out / 'BOOTX64.EFI')),
                             ('::/arch/x86_64/airootfs.sfs', root_hash), ('::/Astraeus-Live.cer', pin)]:
        require(copied_digest(fat, member) == expected, 'FAT image member changed during assembly: ' + member)
    require(digest(args.iso) == args.iso_sha256, 'candidate ISO changed during assembly')
    manifest = dict(schema_version=1, kind='phase42-ram-verified-recovery',
                    source_commit=args.source_commit, iso_sha256=args.iso_sha256, image=image.name,
                    image_sha256=digest(image), image_bytes=size, rootfs_sha256=root_hash, rootfs_bytes=sfs.stat().st_size,
                    certificate_sha256=pin, uki_sha256=digest(out / "BOOTX64.EFI"), distroctl_sha256=cli_sha256,
                    extracted=extracted, command_line=cmdline, builder_sha256=digest(__file__),
                    guard_origin_sha256=GUARD_ORIGIN_SHA256, baseline_manifest_sha256=digest(manifest_path),
                    qualified=False, qualification="Pending candidate enforcing-firmware boot and refusal tests",
                    minimum_ram_gib=max(8, (sfs.stat().st_size + 1024**3 - 1) // 1024**3 + 4), private_key_in_image=False)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # The verified image retains the original rootfs; drop only this generated
    # extraction copy to keep two independent VM baselines within the disk budget.
    sfs.unlink()
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
