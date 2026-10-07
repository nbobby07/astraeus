#!/usr/bin/env python3
"""Launch one independent, disposable Arch builder on a Linux KVM host.

Requires a previously signature-verified cloud image and cloud-localds. The shared
directory must contain source.tar.xz and arch-builder.sh. No public ports or SSH
credentials are created. B requires A's completed repository publication. Keep
combined guest memory below the outer host's usable RAM.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label", choices=["A", "B"])
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--share", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ovmf-code", type=Path, required=True)
    parser.add_argument("--ovmf-vars", type=Path, required=True)
    parser.add_argument("--memory-mib", type=int, choices=[4096, 6144, 8192], default=8192)
    args = parser.parse_args()
    if not Path("/dev/kvm").exists() or os.geteuid() != 0:
        parser.error("run as root on the disposable Linux KVM host")
    base, share = args.base.resolve(strict=True), args.share.resolve(strict=True)
    for file in [share / "source.tar.xz", share / "arch-builder.sh", args.ovmf_code, args.ovmf_vars]:
        if not file.is_file():
            parser.error(f"missing input: {file}")
    out = args.output.resolve()
    if any(c in str(path) for path in [base, share, out] for c in [",", "\n"]):
        parser.error("unsupported comma or newline in path")
    out.mkdir(parents=True, exist_ok=False)
    disk = out / "disk.qcow2"
    subprocess.run(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", str(base), str(disk), "36G"], check=True)
    (out / "vars.fd").write_bytes(args.ovmf_vars.read_bytes())
    (out / "user-data").write_text(f"""#cloud-config
hostname: phase0-builder
ssh_pwauth: false
runcmd:
  - [mkdir, -p, /mnt/phase0]
  - [mount, -t, 9p, -o, "trans=virtio,version=9p2000.L", phase0, /mnt/phase0]
  - [cp, /mnt/phase0/arch-builder.sh, /run/phase0-builder.sh]
  - [env, PHASE0_DISPOSABLE=1, bash, /run/phase0-builder.sh, {args.label}]
power_state:
  mode: poweroff
  delay: now
  timeout: 120
""")
    (out / "meta-data").write_text(f"instance-id: phase0-builder-{args.label}\nlocal-hostname: phase0-builder\n")
    subprocess.run(["cloud-localds", str(out / "seed.img"), str(out / "user-data"), str(out / "meta-data")], check=True)
    command = ["qemu-system-x86_64", "-name", f"builder-{args.label}", "-machine", "q35,accel=kvm",
               "-cpu", "host", "-m", str(args.memory_mib), "-smp", "6",
               "-drive", f"if=pflash,format=raw,readonly=on,file={args.ovmf_code.resolve()}",
               "-drive", f"if=pflash,format=raw,file={out / 'vars.fd'}",
               "-drive", f"file={disk},if=virtio,format=qcow2,discard=unmap",
               "-drive", f"file={out / 'seed.img'},if=virtio,format=raw,readonly=on",
               "-virtfs", f"local,path={share},mount_tag=phase0,security_model=none",
               "-nic", "user,model=virtio-net-pci", "-display", "none",
               "-serial", f"file:{out / 'serial.log'}", "-monitor",
               f"unix:{out / 'monitor.sock'},server=on,wait=off",
               "-pidfile", str(out / "qemu.pid"), "-daemonize", "-no-reboot"]
    (out / "qemu-command.json").write_text(json.dumps(command, indent=2) + "\n")
    subprocess.run(command, check=True)
    print(f"Started builder-{args.label}. Inspect {out / 'serial.log'} and shared evidence/{args.label}.")


if __name__ == "__main__":
    main()
