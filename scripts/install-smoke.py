#!/usr/bin/env python3
"""Private QEMU installation workflow: create a blank disk, then cold boot it without ISO.

Calamares interaction, LUKS unlock and SDDM login use validate/qmp.py. This launcher
does not claim an installation passed; run tests/boot/installed-smoke.sh in each
installed user session and retain screenshots and installer logs.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def qemu_command(code, variables, disk, log, monitor, iso=None):
    command = ["qemu-system-x86_64", "-machine", "q35,accel=kvm", "-cpu", "host",
               "-m", "4096", "-smp", "4", "-device", "virtio-vga",
               "-drive", f"if=pflash,format=raw,readonly=on,file={code}",
               "-drive", f"if=pflash,format=raw,file={variables}",
               "-drive", f"if=virtio,format=qcow2,file={disk}",
               "-nic", "user,model=virtio-net-pci", "-display", "none",
               "-serial", f"file:{log}", "-monitor", "none",
               "-qmp", f"unix:{monitor},server=on,wait=off",
               "-device", "qemu-xhci", "-device", "usb-tablet", "-daemonize"]
    if iso:
        command += ["-cdrom", str(iso), "-boot", "d"]
    else:
        command += ["-boot", "c"]
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["install", "boot"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ovmf-code", type=Path, required=True)
    parser.add_argument("--ovmf-vars", type=Path)
    parser.add_argument("--iso", type=Path)
    parser.add_argument("--disk-gib", type=int, default=32)
    parser.add_argument("--run", default="boot1")
    args = parser.parse_args()
    if not Path("/dev/kvm").exists():
        parser.error("a Linux KVM host is required")
    code = args.ovmf_code.resolve(strict=True)
    out = args.output.resolve()
    if not args.run.isalnum() or not 4 <= args.disk_gib <= 256:
        parser.error("run must be alphanumeric; disk size must be 4..256 GiB")
    if any("," in str(p) or any(c.isspace() for c in str(p)) for p in [out, code]):
        parser.error("QEMU paths must contain no whitespace or commas")
    if args.mode == "install":
        if not args.iso or not args.ovmf_vars:
            parser.error("installation requires ISO and a fresh OVMF VARS template")
        iso = args.iso.resolve(strict=True)
        if "," in str(iso):
            parser.error("unsupported ISO path")
        out.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(args.ovmf_vars.resolve(strict=True), out / "vars.fd")
        subprocess.run(["qemu-img", "create", "-f", "qcow2", str(out / "disk.qcow2"), f"{args.disk_gib}G"], check=True)
        session = out / "install"
    else:
        if args.iso:
            parser.error("installed disk acceptance must not attach an ISO")
        iso = None
        for file in [out / "disk.qcow2", out / "vars.fd"]:
            if not file.is_file():
                parser.error(f"missing installed guest input: {file}")
        session = out / args.run
    session.mkdir(exist_ok=False)
    command = qemu_command(code, out / "vars.fd", out / "disk.qcow2", session / "serial.log", session / "qmp.sock", iso)
    command += ["-pidfile", str(session / "qemu.pid")]
    (session / "qemu-command.json").write_text(json.dumps(command, indent=2) + "\n")
    subprocess.run(command, check=True)
    print(f"Guest running. Private QMP: {session / 'qmp.sock'}")
    print("Use QMP quit after shutdown; retain this disk/VARS for the second cold boot.")


if __name__ == "__main__":
    main()
