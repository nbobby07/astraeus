#!/usr/bin/env python3
"""TEST ONLY: root command channel for disposable nested Astraeus guests.

Never shipped in an ISO/package. Installed explicitly in a validation baseline.
No network listener, credentials, or writable host share.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

PORT = Path('/dev/virtio-ports/org.astraeus.validation')
ROOT = Path('/var/lib/astraeus-validation')
SHARE = Path('/mnt/astraeus-validation')
LIMIT = 4 * 1024 * 1024


def guard():
    if os.geteuid() != 0 or not PORT.exists():
        raise RuntimeError('requires root and the dedicated disposable-guest virtio port')
    if subprocess.check_output(['systemd-detect-virt'], text=True).strip() != 'kvm':
        raise RuntimeError('fault injection requires a nested KVM guest')


def run(command, timeout):
    """Bound output and kill the entire command group on timeout, not just Bash."""
    if not isinstance(command, str) or not 0 < timeout <= 3600:
        raise ValueError('invalid guest command or timeout')
    with tempfile.TemporaryFile() as output:
        child = subprocess.Popen(['bash', '-euo', 'pipefail', '-c', command],
                                 stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + timeout
        reason = None
        while child.poll() is None:
            if time.monotonic() >= deadline:
                reason = 'timeout'
            elif os.fstat(output.fileno()).st_size > LIMIT:
                reason = 'output limit'
            if reason:
                os.killpg(child.pid, signal.SIGKILL)
                break
            time.sleep(0.05)
        code = child.wait(timeout=5)
        if os.fstat(output.fileno()).st_size > LIMIT:
            reason = reason or 'output limit'
        output.seek(0)
        return dict(code=code, error=reason, output=output.read(LIMIT).decode('utf-8', 'replace'))


def setup(acceptance):
    guard()
    text = acceptance.read_text()
    if not any(line.startswith('DISTRO_INSTALL_OK: uefi uki ') for line in text.splitlines()):
        raise ValueError('missing installed-smoke.sh acceptance marker')
    ROOT.mkdir(exist_ok=True)
    (ROOT / 'installed-acceptance.log').write_text(text)
    (ROOT / 'guest.py').write_bytes(Path(__file__).read_bytes())
    unit = Path('/etc/systemd/system/astraeus-validation.service')
    unit.write_text('''[Unit]
Description=Disposable Phase 2 validation command channel
ConditionPathExists=/dev/virtio-ports/org.astraeus.validation
After=local-fs.target
[Service]
ExecStart=/usr/bin/python3 /var/lib/astraeus-validation/guest.py serve
Restart=on-failure
RestartSec=1
[Install]
WantedBy=multi-user.target
''')
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', unit.name], check=True)


def fault(kind):
    guard()
    if kind == 'package':
        hooks = Path('/etc/pacman.d/hooks')
        hooks.mkdir(exist_ok=True)
        (ROOT / 'abort-package.sh').write_text('printf "package\\n" > /var/log/astraeus-validation-fault\nexit 1\n')
        (hooks / '00-astraeus-validation.hook').write_text('''[Trigger]
Operation = Upgrade
Type = Package
Target = astraeus-validation-fixture
[Action]
Description = Deliberate validation failure
When = PreTransaction
Exec = /bin/bash /var/lib/astraeus-validation/abort-package.sh
AbortOnFail
''')
    elif kind == 'health':
        Path('/etc/systemd/system/astraeus-validation-failed.service').write_text('''[Service]
Type=oneshot
ExecStart=/usr/bin/false
''')
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        result = subprocess.run(['systemctl', 'start', 'astraeus-validation-failed.service'])
        if result.returncode == 0:
            raise RuntimeError('failed-health fixture unexpectedly succeeded')
    elif kind == 'service':
        subprocess.run(['systemctl', 'mask', '--now', 'NetworkManager.service'], check=True)
    elif kind == 'boot':
        status = json.loads(subprocess.check_output(['distroctl', 'status', '--json']))
        relative = status['boot']['uki_path'].replace('\\', '/').lstrip('/')
        uki = (Path('/efi') / relative).resolve(strict=True)
        if not uki.is_relative_to('/efi/EFI/Linux') or uki.suffix != '.efi':
            raise ValueError('refusing unexpected boot artifact path')
        uki.write_bytes(b'ASTRAEUS INTENTIONALLY BROKEN TEST UKI\n')
        os.sync()
    elif kind == 'payload':
        # Only the disposable guest's local signed test repository is damaged.
        archive = Path('/var/lib/astraeus-validation/repo/astraeus-validation-fixture-2-1-any.pkg.tar.zst')
        if not archive.is_file():
            raise RuntimeError('missing local version-2 test repository archive')
        archive.write_bytes(b'not a package\n')
        cache = Path('/var/cache/pacman/pkg') / archive.name
        cache.unlink(missing_ok=True)
    elif kind == 'space':
        target = Path('/var/cache/pacman/pkg')
        subprocess.run(['mount', '-t', 'tmpfs', '-o', 'size=16m', 'tmpfs', str(target)], check=True)
        # ponytail: bounded cache ENOSPC; root/ESP exhaustion needs a separate disk budget.
        with (target / 'filler').open('wb', buffering=0) as stream:
            try:
                while True:
                    stream.write(b'x' * 65536)
            except OSError as error:
                import errno
                if error.errno != errno.ENOSPC:
                    raise
    else:
        raise ValueError('unknown fault')
    if kind != 'package':
        Path('/var/log/astraeus-validation-fault').write_text(kind + '\n')


def serve():
    guard()
    SHARE.mkdir(exist_ok=True)
    if not os.path.ismount(SHARE):
        subprocess.run(['mount', '-t', '9p', '-o', 'trans=virtio,version=9p2000.L,ro',
                        'acceptance', str(SHARE)], check=True)
    with PORT.open('r+b', buffering=0) as stream:
        while True:
            # Reconnects are initiated by a new request, so stale boot greetings cannot pass.
            raw = stream.readline(65537)
            if not raw:
                time.sleep(0.1)
                continue
            request = json.loads(raw)
            if len(raw) > 65536:
                raise ValueError('oversized request')
            result = run(request['command'], request['timeout'])
            result.update(id=request['id'], boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
            remaining = memoryview(json.dumps(result).encode() + b'\n')
            while remaining:
                written = stream.write(remaining)
                if not written:
                    raise ConnectionError('validation channel disconnected')
                remaining = remaining[written:]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'serve', 'fault'])
    parser.add_argument('value', nargs='?')
    args = parser.parse_args()
    if args.action == 'setup':
        setup(Path(args.value))
    elif args.action == 'fault':
        fault(args.value)
    else:
        serve()
