#!/usr/bin/env python3
"""Keep a KVM live guest open for private QMP screenshots and input checks."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

spec = importlib.util.spec_from_file_location("boot_smoke", Path(__file__).resolve().parents[1] / "boot-smoke.py")
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path)
    parser.add_argument("--ovmf-code", type=Path, required=True)
    parser.add_argument("--ovmf-vars", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu", choices=["virtio-vga", "VGA"], default="virtio-vga")
    args = parser.parse_args()
    for path in [args.iso, args.ovmf_code, args.ovmf_vars]:
        if not path.is_file():
            parser.error(f"missing input: {path}")
    out = args.output.resolve()
    if any("," in str(path) for path in [args.iso, args.ovmf_code, args.ovmf_vars, out]):
        parser.error("unsupported comma in path")
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(args.ovmf_vars, out / "vars.fd")
    args.log, args.accel = out / "serial.log", "kvm"
    command = boot.qemu_command(args, out / "vars.fd")
    command += ["-qmp", f"unix:{out / 'qmp.sock'},server=on,wait=off",
                "-device", "qemu-xhci", "-device", "usb-tablet",
                "-pidfile", str(out / "qemu.pid"), "-daemonize"]
    (out / "qemu-command.json").write_text(json.dumps(command, indent=2) + "\n")
    subprocess.run(command, check=True)
    print(f"Private QMP monitor: {out / 'qmp.sock'}; stop this guest with the QMP quit command.")


if __name__ == "__main__":
    main()
