#!/usr/bin/env python3
"""Disposable Phase 2 KVM validation. See docs/phase2-validation.md before use."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid

import qmp

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
spec = importlib.util.spec_from_file_location('install_smoke', HERE.parent / 'install-smoke.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)
GUEST = 'python3 /mnt/astraeus-validation/phase2-guest.py'
ADAPTER = 'bash /mnt/astraeus-validation/fixtures/adapter.sh'
SENTINEL = '/etc/astraeus-test-state'
PERSISTENT = '/home/astraeus-validation/persistent-marker'
FAULTS = ['package', 'health', 'service', 'payload', 'space']


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class QemuExited(RuntimeError):
    def __init__(self, code):
        self.returncode = code
        super().__init__(f'QEMU exited before acceptance (exit {code})')


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def host(command, timeout=120):
    return subprocess.check_output([str(x) for x in command], timeout=timeout, text=True)


def safe_path(path):
    path = Path(path).resolve()
    require(not any(c.isspace() or c == ',' for c in str(path)), 'QEMU paths cannot contain whitespace or commas')
    return path


def marker_present(text, marker):
    return marker in text.splitlines()


def verify_baseline(base):
    manifest = json.loads((base / 'baseline.json').read_text())
    require(manifest.get('accepted') is True, 'baseline was not accepted')
    for name in ['disk.qcow2', 'vars.fd']:
        require(digest(base / name) == manifest['sha256'][name], f'baseline changed: {name}')
    return manifest


def clone(base, out):
    manifest = verify_baseline(base)
    host(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', base / 'disk.qcow2', out / 'disk.qcow2'])
    shutil.copyfile(base / 'vars.fd', out / 'vars.fd')
    save(out / 'baseline-reference.json', dict(path=str(base), manifest=manifest))
    return manifest


class VM:
    def __init__(self, out, code, share, timeout, secure_boot=False):
        self.out, self.code, self.share, self.timeout = out, code, share, timeout
        self.secure_boot = secure_boot
        self.child = None
        self.number = 0
        self.session = None
        self.boot_id = None
        self.sequence = 0

    def start(self, iso=None):
        require(self.child is None or self.child.poll() is not None, 'guest already running')
        self.boot_id = None
        self.number += 1
        self.session = self.out / f'boot-{self.number}'
        self.session.mkdir()
        self.monitor = self.session / 'qmp.sock'
        self.channel = self.session / 'guest.sock'
        require(len(str(self.channel).encode()) < 104, 'output path too long for Unix sockets')
        command = install.qemu_command(self.code, self.out / 'vars.fd', self.out / 'disk.qcow2',
                                       self.session / 'serial.log', self.monitor, iso, self.share,
                                       **({'secure_boot': True} if self.secure_boot else {}))
        command.remove('-daemonize')
        command += ['-no-reboot', '-device', 'virtio-serial-pci', '-chardev',
                    f'socket,id=validation,path={self.channel},server=on,wait=off',
                    '-device', 'virtserialport,chardev=validation,name=org.astraeus.validation']
        save(self.session / 'qemu-command.json', command)
        print(f'QMP: {self.monitor}', flush=True)
        with (self.session / 'qemu.log').open('wb') as log:
            self.child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        save(self.session / 'process.json', dict(pid=self.child.pid, started=now(), iso=str(iso) if iso else None))

    def alive(self):
        require(self.child is not None, 'QEMU has not been started')
        code = self.child.poll()
        if code is not None:
            save(self.session / 'qemu-exit.json', dict(time=now(), code=code))
            raise QemuExited(code)

    def command(self, command, timeout=None, check=True, label='command'):
        self.alive()
        timeout = timeout or self.timeout
        request = dict(id=uuid.uuid4().hex, command=command, timeout=timeout)
        started = now()
        deadline = time.monotonic() + timeout + 5
        self.sequence += 1
        record = self.session / f'{self.sequence:03d}-{label}.json'
        result = dict(error='no reply', code=None)
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(max(0.01, deadline - time.monotonic()))
                client.connect(str(self.channel))
                client.sendall(json.dumps(request).encode() + b'\n')
                pending = bytearray()
                while True:
                    require(time.monotonic() < deadline, 'guest reply timed out')
                    if b'\n' not in pending:
                        client.settimeout(max(0.01, deadline - time.monotonic()))
                        chunk = client.recv(65536)
                        require(chunk, 'guest disconnected')
                        pending.extend(chunk)
                        require(len(pending) <= 32 * 1024 * 1024, 'oversized guest reply')
                        continue
                    line, _, pending = pending.partition(b'\n')
                    reply = json.loads(line)
                    if reply.get('id') == request['id']:
                        result = reply
                        break
            self.boot_id = result['boot_id']
            require(result.get('error') is None, f'guest command {label}: {result.get("error")}')
            if check:
                require(result['code'] == 0, f'guest command {label} exited {result["code"]}; see {record}')
            return result
        finally:
            save(record, dict(started=started, finished=now(), command=command, result=result))

    def ready(self):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.alive()
            try:
                result = self.command('printf "ASTRAEUS_VALIDATION_READY\\n"', timeout=2, label='ready')
                require(marker_present(result['output'], 'ASTRAEUS_VALIDATION_READY'), 'missing acceptance marker')
                self.qmp_state('ready')
                return
            except (OSError, ValueError, RuntimeError):
                time.sleep(0.2)
        raise TimeoutError('guest readiness timed out; unlock LUKS/start the test agent through private QMP')

    def qmp_state(self, label):
        result = {name: qmp.execute(str(self.monitor), {'execute': name})
                  for name in ['query-status', 'query-kvm', 'query-block']}
        save(self.session / f'qmp-{label}.json', result)
        require(result['query-kvm'].get('enabled') is True, 'KVM was not enabled')

    def shutdown(self):
        self.alive()
        if self.boot_id:
            # KDE may turn ACPI powerdown into an unanswered dialog. Give the
            # command channel time to acknowledge, then request a normal shutdown.
            self.command('systemd-run --unit=astraeus-validation-poweroff --on-active=1s '
                         '/usr/bin/systemctl poweroff', label='schedule-poweroff')
        else:
            qmp.execute(str(self.monitor), {'execute': 'system_powerdown'})
        code = self.child.wait(timeout=60)
        require(code == 0, f'QEMU shutdown exited {code}')
        save(self.session / 'shutdown.json', dict(finished=now(), code=code, graceful=True))

    def stop(self):
        """Only terminate the Popen child owned by this invocation, never a saved PID."""
        if self.child is not None and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=10)
            save(self.session / 'shutdown.json', dict(finished=now(), code=self.child.returncode, graceful=False))

    def reboot(self):
        previous = self.boot_id
        self.shutdown()
        self.start()
        self.ready()
        require(self.boot_id != previous, 'reboot did not change the guest boot ID')
        save(self.session / 'reboot.json', dict(previous=previous, current=self.boot_id))


def observe(vm, label, product=True):
    """Collect each item independently so one broken command does not erase others."""
    commands = {
        'status': 'distroctl status --json', 'packages': 'LC_ALL=C pacman -Q | LC_ALL=C sort',
        'database': 'pacman -Dk', 'failed': 'systemctl --failed --no-legend --plain',
        'mounts': 'findmnt --list --json -o TARGET,SOURCE,FSTYPE,FSROOT,UUID,OPTIONS',
        'subvolumes': 'btrfs subvolume list /', 'boot': 'bootctl status --no-pager',
        'root': f'cat {SENTINEL}', 'persistent': f'cat {PERSISTENT}',
        'journal': 'journalctl -b -p warning --no-pager -n 100',
        'boot-journal': 'journalctl -b --no-pager',
        'uki-sha256': 'sha256sum /efi/EFI/Linux/astraeus-dev-linux.efi',
        'kernel-command-line': 'cat /proc/cmdline',
        'pacman-log': 'tail -c 1048576 /var/log/pacman.log',
        'transaction-log': 'tail -c 1048576 /var/log/astraeus-validation-update.log',
    }
    if product:
        commands.update(history='distroctl history --json', snapshots='distroctl snapshot list --json')
    results = {}
    for name, command in commands.items():
        try:
            results[name] = vm.command(command, timeout=30, check=False, label=f'{label}-{name}')
        except (OSError, ValueError, RuntimeError) as error:
            results[name] = dict(code=None, error=str(error), output='')
    save(vm.out / f'{label}.json', results)
    vm.qmp_state(label)
    return results


def value(evidence, name, json_value=False):
    result = evidence[name]
    require(result['code'] == 0 and not result.get('error'), f'missing evidence: {name}')
    return json.loads(result['output']) if json_value else result['output'].strip()


def healthy(evidence, encryption):
    status = value(evidence, 'status', True)
    require(status['filesystem']['root_type'] == 'btrfs', 'root is not Btrfs')
    require(status['filesystem']['encryption'] == encryption, 'unexpected encryption')
    require(status['boot']['firmware'] == 'UEFI', 'boot is not UEFI')
    require(value(evidence, 'failed') == '', 'unexpected failed system units')
    value(evidence, 'database')
    value(evidence, 'boot')
    mounts = value(evidence, 'mounts', True)['filesystems']
    roots = {m['target']: m['fsroot'] for m in mounts}
    require(roots.get('/') == '/@' and roots.get('/home') == '/@home', 'rollback subvolume boundary missing')


def transaction(before, after, states, transaction_id=None):
    old_ids = {record['id'] for record in value(before, 'history', True)}
    records = [record for record in value(after, 'history', True) if record['id'] not in old_ids]
    require(len(records) == 1, 'expected exactly one new transaction')
    record = records[0]
    require(record['schema_version'] == 1 and record['state'] in states, 'unexpected transaction state')
    expected_outcome = 'in_progress' if record['state'] == 'applying' else record['state']
    require(record['outcome'] == expected_outcome, 'transaction outcome contradicts its state')
    if transaction_id is not None:
        require(record['id'] == transaction_id, 'transaction identity changed')
    require(record['plan']['packages']['changes'], 'empty update cannot validate package mutation')
    snapshots = value(after, 'snapshots', True)
    matching = [s for s in snapshots if s['id'] == record['snapshot']]
    require(len(matching) == 1, 'pre-update snapshot missing')
    snapshot = matching[0]
    require(snapshot['id'] not in {s['id'] for s in value(before, 'snapshots', True)}, 'stale pre-update snapshot')
    require(snapshot['reason'] == 'pre-update' and snapshot['transaction_id'] == str(record['id']), 'snapshot transaction mismatch')
    require(snapshot['root']['read_only'] is True, 'pre-update snapshot must be read-only')
    events = [event['state'] for event in record['events']]
    require('snapshot_created' in events and 'applying' in events and
            events.index('snapshot_created') < events.index('applying'), 'snapshot did not precede mutation')
    if record['state'] in ['awaiting_boot', 'succeeded']:
        checks = record['health_checks']
        require(checks and all(c['status'] != 'fail' and (not c['required'] or c['status'] == 'pass') for c in checks), 'health checks did not pass')
        require(record['boot_regenerated'] is True, 'boot artifacts not regenerated')
        expected = dict(record['plan']['current']['packages'])
        for change in record['plan']['packages']['changes']:
            if change['kind'] == 'remove':
                expected.pop(change['name'])
            else:
                expected[change['name']] = change.get('to', change.get('version'))
        actual = dict(line.split(maxsplit=1) for line in value(after, 'packages').splitlines())
        require(actual == expected, 'installed packages disagree with the transaction plan')
    if record['state'] in ['succeeded', 'rolled_back']:
        rollback = record['state'] == 'rolled_back'
        reference = record['snapshot'] if rollback else record.get('post_snapshot')
        targets = [s for s in snapshots if s['id'] == reference]
        require(len(targets) == 1 and targets[0]['health'] == 'known-good', 'confirmed generation is not known-good')
        require(value(after, 'uki-sha256').split()[0] == targets[0]['boot']['sha256'], 'active UKI differs from confirmed generation')
        confirmation = record.get('confirmation') or {}
        require(confirmation.get('error') is None and confirmation.get('snapshot') == reference
                and confirmation.get('rollback') is rollback and confirmation.get('boot_id')
                and confirmation['boot_id'] != record.get('update_boot_id'), 'missing matching new-boot confirmation')
        checks = confirmation.get('checks', [])
        require(checks and all(c['status'] != 'fail' and (not c['required'] or c['status'] == 'pass') for c in checks), 'post-boot health evidence missing')
    return record


def adapter(vm, action, *args, check=True):
    if action in ['confirm-boot', 'finalize-rollback', 'reconcile']:
        # Wait for the actual systemd job, not a sleep or a guessed boot delay.
        # Failure is evidence: never race its lock or skip a failed service.
        vm.command('systemctl start astraeus-confirm-boot.service', label='wait-boot-confirmation')
    return vm.command(shlex.join(['bash', '/mnt/astraeus-validation/fixtures/adapter.sh', action, *args]),
                      label=action, check=check)


def recover(vm, args, snapshot):
    vm.shutdown()
    vm.start(args.iso)
    print('Recovery ISO: start phase2-guest.py serve as root; unlock LUKS as root if needed.', flush=True)
    vm.ready()
    adapter(vm, 'recover', snapshot)
    vm.reboot()


def scenario(vm, args):
    vm.start()
    vm.ready()
    adapter(vm, 'prepare')
    marker = uuid.uuid4().hex
    vm.command(f'mkdir -p /home/astraeus-validation; printf %s {marker} > {PERSISTENT}', label='seed-persistent')
    before = observe(vm, 'before')
    healthy(before, args.encryption)
    require(value(before, 'root') == 'version-A', 'baseline fixture is not version A')
    if args.scenario == 'interruption':
        adapter(vm, 'arm', 'interruption')
        vm.command(f'systemd-run --unit=astraeus-validation-update --property=RuntimeMaxSec={args.timeout} '
                   f'{ADAPTER} update', label='start-update')
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            at_barrier = vm.command('test -e /var/log/astraeus-validation-barrier', timeout=5, check=False, label='barrier')
            if at_barrier['code'] == 0:
                break
            time.sleep(0.2)
        else:
            raise TimeoutError('update never reached the controlled package barrier')
        changed = observe(vm, 'interrupted-before-powercut')
        record = transaction(before, changed, ['applying'])
        require(value(changed, 'root') == 'version-B' and
                value(changed, 'packages') != value(before, 'packages'),
                'interruption barrier reached before package state changed')
        vm.qmp_state('powercut')
        vm.child.kill()
        vm.child.wait(timeout=10)
        save(vm.session / 'powercut.json', dict(time=now(), transaction=record['id'], boot_id=vm.boot_id))
        previous_boot = vm.boot_id
        vm.start()
        vm.ready()
        require(vm.boot_id != previous_boot, 'power cut did not produce a new boot')
        changed = observe(vm, 'after-interruption')
        transaction(before, changed, ['applying', 'rollback_required'], record['id'])
        adapter(vm, 'reconcile')
        changed = observe(vm, 'reconciled')
        record = transaction(before, changed, ['rollback_required'], record['id'])
    else:
        if args.scenario in ['update-failure', 'rejected-update']:
            adapter(vm, 'arm', args.fault)
        result = adapter(vm, 'update', check=False)
        changed = observe(vm, 'after-update')
        if args.scenario == 'rejected-update':
            require(vm.command('cat /var/log/astraeus-validation-fault', label='fault-evidence')['output'].strip() == args.fault, 'fault was not injected')
            require(result['code'] not in [0, 77, 124, 137], 'expected rejection, not missing hook/timeout')
            old_ids = {r['id'] for r in value(before, 'history', True)}
            records = [r for r in value(changed, 'history', True) if r['id'] not in old_ids]
            require(len(records) == 1 and records[0]['state'] == 'failed' and records[0]['failure'], 'missing failed transaction')
            message = records[0]['failure']['message'].lower()
            expected = ['insufficient disk space'] if args.fault == 'space' else ['package download:', 'package verification:']
            require(any(part in message for part in expected), 'update failed for an unrelated reason')
            require(records[0]['snapshot'] is None, 'rejection unexpectedly created a snapshot')
            require(value(changed, 'packages') == value(before, 'packages'), 'rejected update changed packages')
            require(value(changed, 'root') == 'version-A', 'rejected update changed root sentinel')
            require(value(changed, 'snapshots', True) == value(before, 'snapshots', True), 'rejection changed snapshots')
            if args.fault == 'space':
                adapter(vm, 'disarm', 'space')
            vm.reboot()
            final = observe(vm, 'after-rejection')
            healthy(final, args.encryption)
            require(value(final, 'root') == 'version-A' and value(final, 'persistent') == marker, 'rejection changed sentinels')
            require(value(final, 'packages') == value(before, 'packages'), 'rejection reboot changed packages')
            vm.shutdown()
            return
        if args.scenario == 'update-failure':
            require(result['code'] not in [0, 77, 124, 137], 'expected product failure, not missing hook/timeout')
            record = transaction(before, changed, ['rollback_required'])
            require(record['failure'] is not None, 'failure diagnostic missing')
            require(vm.command('cat /var/log/astraeus-validation-fault', label='fault-evidence')['output'].strip() == args.fault, 'fault was not injected')
        else:
            require(result['code'] == 0, 'update command failed')
            record = transaction(before, changed, ['awaiting_boot'])
            healthy(changed, args.encryption)
            require(value(changed, 'root') == 'version-B', 'update did not install version B')
            require(value(before, 'packages') != value(changed, 'packages'), 'package set did not change')
    snapshot_sentinel = f'/.snapshots/astraeus/{record["snapshot"]}/private/root/etc/astraeus-test-state'
    saved_root = vm.command(shlex.join(['cat', snapshot_sentinel]), label='snapshot-sentinel')['output'].strip()
    require(saved_root == 'version-A', 'pre-update snapshot does not contain the previous sentinel')
    # Write after the snapshot. Restoring @home by accident must fail this test.
    marker += '-after-snapshot'
    vm.command(f'printf %s {marker} > {PERSISTENT}; sync', label='change-persistent')
    if args.scenario == 'update-success':
        vm.reboot()
        booted = observe(vm, 'before-boot-confirmation')
        healthy(booted, args.encryption)
        require(value(booted, 'root') == 'version-B' and value(booted, 'persistent') == marker, 'booted sentinels disagree')
        require(value(booted, 'packages') == value(changed, 'packages'), 'booted packages disagree')
        adapter(vm, 'confirm-boot', str(record['id']))
        final = observe(vm, 'after-reboot')
        transaction(before, final, ['succeeded'], record['id'])
        require(value(final, 'root') == 'version-B', 'updated sentinel lost after reboot')
        require(value(final, 'packages') == value(changed, 'packages'), 'package set changed at reboot')
    else:
        # The snapshot owner requires a known-good target, justified by before.json.
        vm.command(shlex.join(['distroctl', 'snapshot', 'mark', record['snapshot'], 'known-good',
                              '--evidence', f'phase2 validation {vm.out.name}/before.json {marker}']), label='mark-baseline-good')
        if args.scenario == 'boot-recovery':
            vm.command(GUEST + ' fault boot', label='break-boot')
            vm.shutdown()
            vm.start()
            try:
                vm.ready()
            except (TimeoutError, QemuExited) as error:
                if isinstance(error, QemuExited):
                    # With no valid UKI, systemd-boot selects firmware setup.
                    # Its reset exits QEMU cleanly because we use -no-reboot.
                    require(error.returncode == 0, 'QEMU crashed during the broken-boot test')
                    require('Reboot Into Firmware Interface' in (vm.session / 'serial.log').read_text(errors='replace'),
                            'clean QEMU exit lacks firmware-reset evidence')
                else:
                    vm.qmp_state('expected-boot-failure')
                save(vm.session / 'expected-boot-failure.json', dict(time=now(), timeout=args.timeout,
                     reason=str(error), qemu_exit=getattr(error, 'returncode', None)))
                vm.stop()
            else:
                raise RuntimeError('broken UKI unexpectedly booted')
            vm.start(args.iso)
            vm.ready()
            adapter(vm, 'recover', record['snapshot'])
            vm.reboot()
        else:
            recover(vm, args, record['snapshot'])
        restored = observe(vm, 'before-rollback-finalization')
        healthy(restored, args.encryption)
        require(value(restored, 'root') == 'version-A' and value(restored, 'persistent') == marker, 'restored sentinels disagree')
        require(value(restored, 'packages') == value(before, 'packages'), 'restored packages disagree')
        adapter(vm, 'finalize-rollback', str(record['id']))
        final = observe(vm, 'after-rollback')
        transaction(before, final, ['rolled_back'], record['id'])
        require(value(final, 'root') == 'version-A', 'root sentinel was not restored')
        require(value(final, 'packages') == value(before, 'packages'), 'package database not restored with root')
    require(value(final, 'persistent') == marker, 'persistent user data changed during recovery')
    healthy(final, args.encryption)
    vm.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['install', 'baseline', 'run'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ovmf-code', type=Path, required=True)
    parser.add_argument('--ovmf-vars', type=Path)
    parser.add_argument('--iso', type=Path, required=True, help='installer/recovery ISO; never attached on normal boots')
    parser.add_argument('--source', type=Path, help='stopped installation directory for baseline mode')
    parser.add_argument('--base', type=Path, help='sealed baseline directory for run mode')
    parser.add_argument('--fixtures', type=Path, default=REPO / 'tests/fixtures/phase2')
    parser.add_argument('--source-commit', action='append', required=True, help='repeat for product input commits')
    parser.add_argument('--scenario', choices=['update-success', 'update-failure', 'rejected-update', 'rollback', 'interruption', 'boot-recovery'], default='update-success')
    parser.add_argument('--fault', choices=FAULTS, default='package')
    parser.add_argument('--encryption', choices=['LUKS2', 'none'], default='LUKS2')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--disk-gib', type=int, default=32)
    args = parser.parse_args()
    require(all(re.fullmatch('[0-9a-f]{40}', commit) for commit in args.source_commit), 'source commits must be full lowercase Git SHA-1 IDs')
    require(args.scenario != 'update-failure' or args.fault in ['package', 'health', 'service'], 'use rejected-update for payload/space faults')
    require(args.scenario != 'rejected-update' or args.fault in ['payload', 'space'], 'rejected-update requires payload/space fault')
    require(sys.platform == 'linux' and Path('/dev/kvm').exists(), 'Linux with nested KVM is required')
    require(10 <= args.timeout <= 3600 and 20 <= args.disk_gib <= 256, 'invalid timeout/disk size')
    for tool in ['qemu-system-x86_64', 'qemu-img']:
        require(shutil.which(tool), f'missing {tool}')
    args.output, args.ovmf_code, args.iso = map(safe_path, [args.output, args.ovmf_code, args.iso])
    require(args.ovmf_code.is_file() and args.iso.is_file(), 'missing OVMF/ISO input')
    if args.mode == 'install':
        require(args.ovmf_vars and args.ovmf_vars.is_file(), 'install requires --ovmf-vars')
    if args.mode == 'baseline':
        require(args.source and args.source.is_dir(), 'baseline requires --source')
    if args.mode == 'run':
        require(args.base and args.base.is_dir(), 'run requires --base')
        args.base = safe_path(args.base)
    args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(args.output, 0o700)
    vm = None
    result = dict(passed=False, started=now(), mode=args.mode, scenario=args.scenario, encryption=args.encryption)
    base_manifest = None
    try:
        share = args.output / 'share'
        share.mkdir()
        for source in [HERE / 'phase2-guest.py', REPO / 'tests/boot/installed-smoke.sh']:
            shutil.copyfile(source, share / source.name)
        shutil.copytree(args.fixtures, share / 'fixtures', symlinks=False)
        save(args.output / 'inputs.json', dict(source_commits=args.source_commit,
             harness_commit=host(['git', '-C', REPO, 'rev-parse', 'HEAD']).strip(),
             harness_dirty=bool(host(['git', '-C', REPO, 'status', '--porcelain']).strip()),
             harness_files={str(p.relative_to(REPO)): digest(p) for p in
                            [Path(__file__), HERE / 'qmp.py', HERE.parent / 'install-smoke.py']},
             iso=dict(path=str(args.iso), sha256=digest(args.iso)),
             ovmf_code=dict(path=str(args.ovmf_code), sha256=digest(args.ovmf_code)),
             files={str(p.relative_to(share)): digest(p) for p in share.rglob('*') if p.is_file()},
             host=dict(platform=sys.platform, qemu=host(['qemu-system-x86_64', '--version']))))
        vm = VM(args.output, args.ovmf_code, share, args.timeout)
        if args.mode == 'install':
            host(['qemu-img', 'create', '-f', 'qcow2', args.output / 'disk.qcow2', f'{args.disk_gib}G'])
            shutil.copyfile(args.ovmf_vars, args.output / 'vars.fd')
            save(args.output / 'ovmf-vars-input.json', dict(path=str(args.ovmf_vars.resolve()), sha256=digest(args.ovmf_vars)))
            vm.start(args.iso)
            print('Complete Calamares through QMP, then shut down. This mode does not certify installation.', flush=True)
            require(vm.child.wait(timeout=args.timeout) == 0, 'installer guest exited unsuccessfully')
            result['installation_accepted'] = False
        elif args.mode == 'baseline':
            # qemu-img locking refuses a running source. Flatten any backing chain.
            host(['qemu-img', 'convert', '-O', 'qcow2', args.source.resolve() / 'disk.qcow2', args.output / 'disk.qcow2'], timeout=3600)
            shutil.copyfile(args.source / 'vars.fd', args.output / 'vars.fd')
            save(args.output / 'source-installation.json', dict(path=str(args.source.resolve()), disk_sha256=digest(args.source / 'disk.qcow2'), vars_sha256=digest(args.source / 'vars.fd')))
            vm.start()
            print('Run installed-smoke.sh as the desktop user, then phase2-guest.py setup HEALTH_LOG as root.', flush=True)
            vm.ready()
            log = vm.command('cat /var/lib/astraeus-validation/installed-acceptance.log', label='phase1-acceptance')['output']
            marker = f'DISTRO_INSTALL_OK: uefi uki {args.encryption} btrfs sddm plasma wayland network audio status'
            require(marker_present(log, marker), 'Phase 1 installed acceptance marker missing')
            first = observe(vm, 'baseline-first', product=False)
            healthy(first, args.encryption)
            vm.reboot()
            second = observe(vm, 'baseline-second', product=False)
            healthy(second, args.encryption)
            vm.shutdown()
            manifest = dict(accepted=True, created=now(), encryption=args.encryption,
                            inputs=json.loads((args.output / 'inputs.json').read_text()),
                            sha256={name: digest(args.output / name) for name in ['disk.qcow2', 'vars.fd']})
            for name in ['disk.qcow2', 'vars.fd']:
                os.chmod(args.output / name, 0o444)
            save(args.output / 'baseline.json', manifest)
        else:
            base_manifest = clone(args.base, args.output)
            require(base_manifest['encryption'] == args.encryption, 'baseline encryption does not match requested gate')
            require(base_manifest['inputs']['ovmf_code']['sha256'] == digest(args.ovmf_code), 'baseline OVMF CODE changed')
            scenario(vm, args)
        result['passed'] = True
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
        if vm and vm.boot_id and vm.child.poll() is None:
            try:
                observe(vm, 'failure-diagnostics', product=args.mode == 'run')
            except Exception as diagnostic_error:
                result['diagnostic_error'] = str(diagnostic_error)
        raise
    finally:
        try:
            if vm:
                vm.stop()
            if base_manifest:
                verify_baseline(args.base)
        except BaseException as error:
            result.update(passed=False, cleanup_error=str(error))
            raise
        finally:
            result['finished'] = now()
            save(args.output / 'result.json', result)
            save(args.output / 'evidence-sha256.json', {str(p.relative_to(args.output)): digest(p)
                 for p in args.output.rglob('*') if p.is_file() and p.suffix not in ['.qcow2', '.fd']
                 and p.name != 'evidence-sha256.json'})
            print(f'Evidence retained: {args.output}', flush=True)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise InterruptedError(f'validation interrupted by signal {signum}')

    signal.signal(signal.SIGTERM, interrupted)
    main()
