#!/usr/bin/env python3
"""Boot a real ISO with UEFI; retain serial output, fail on timeout or early exit."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

MARKER = b"DISTRO_BOOT_OK: uefi plasma wayland pipewire networkmanager distroctl"


def qemu_command(args, variables):
    command = ["qemu-system-x86_64", "-machine", f"q35,accel={args.accel}", "-m", "4096", "-smp", "4",
               "-drive", f"if=pflash,format=raw,readonly=on,file={args.ovmf_code.resolve()}",
               "-drive", f"if=pflash,format=raw,file={variables}",
               "-cdrom", str(args.iso.resolve()), "-boot", "d", "-device", args.gpu,
               "-display", "none", "-serial", f"file:{args.log.resolve()}",
               "-monitor", "none", "-nic", "user,model=virtio-net-pci", "-no-reboot"]
    if args.accel == "kvm":
        command += ["-cpu", "host"]
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path)
    parser.add_argument("--ovmf-code", type=Path, required=True)
    parser.add_argument("--ovmf-vars", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--accel", choices=["kvm", "tcg"], default="kvm",
                        help="KVM is required by default; TCG must be explicitly requested")
    parser.add_argument("--gpu", choices=["virtio-vga", "VGA"], default="virtio-vga")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    for file in [args.iso, args.ovmf_code, args.ovmf_vars]:
        if not file.is_file() or "," in str(file):
            parser.error(f"file missing or unsupported comma in path: {file}")
    if args.log.exists():
        parser.error("log already exists; use a new path to avoid a stale pass marker")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.touch(exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="distro-boot-") as temp:
        variables = Path(temp) / "vars.fd"
        shutil.copyfile(args.ovmf_vars, variables)
        command = qemu_command(args, variables)
        args.log.with_suffix(".qemu.json").write_text(json.dumps(command, indent=2) + "\n")
        print(f"Requested accelerator: {args.accel}")
        try:
            child = subprocess.Popen(command)
        except OSError as error:
            parser.exit(1, f"QEMU unavailable: {error}\n")
        try:
            deadline = time.monotonic() + args.timeout
            while child.poll() is None and time.monotonic() < deadline:
                if MARKER in args.log.read_bytes():
                    print(f"UEFI live desktop smoke passed. Evidence: {args.log}")
                    return
                time.sleep(1)
            parser.exit(1, f"Boot failed or timed out; inspect {args.log}\n")
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    main()
