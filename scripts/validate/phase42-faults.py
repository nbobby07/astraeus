#!/usr/bin/env python3
"""Candidate-only destructive fault acceptance, confined to disposable KVM overlays.

The host runner and its guarded guest actions share this file. No host block device
is opened. Runtime candidate identities and validation harness identities are separate.
"""
import argparse
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from phase42_trust import verify_maintained_uki

SHARE = Path('/mnt/astraeus-validation')
STATE = Path('/var/lib/astraeus/management/state.json')
SUBMISSIONS = Path('/run/astraeus')
RECEIPTS = Path('/var/log/astraeus/operations')
WORKER_TEMPLATE = 'astraeus-apply@.service'
RUNTIME_MASK = Path('/run/systemd/system') / WORKER_TEMPLATE
SCENARIOS = ('metadata', 'interruption', 'abandoned', 'failed-hook', 'signing-failure',
             'root-space', 'cache-space', 'esp-space')
SECURE_LIVE_MARKER = 'ASTRAEUS_SECURE_LIVE_OK: SecureBoot=1 SetupMode=0 rootfs=verified-in-RAM'
LIVE_DESKTOP_MARKER = 'DISTRO_BOOT_OK: uefi plasma wayland pipewire networkmanager distroctl'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def call(*arguments, timeout=120, check=True):
    result = subprocess.run([str(argument) for argument in arguments], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=timeout,
                            env=dict(os.environ, LC_ALL='C', PATH='/usr/bin:/bin'))
    require(len(result.stdout) + len(result.stderr) <= 8 * 1024 * 1024, 'guest command output limit')
    if check:
        require(result.returncode == 0, f'{arguments[0]} exited {result.returncode}: {result.stderr[-2048:]}')
    return {'code': result.returncode, 'output': result.stdout, 'error': result.stderr}


def configuration(value):
    require(isinstance(value, dict) and value.get('schema_version') == 1, 'invalid fault configuration')
    for key, pattern in [('run_id', '[0-9a-f]{32}'), ('source_commit', '[0-9a-f]{40}'),
                         ('distroctl_sha256', '[0-9a-f]{64}'), ('desktop_sha256', '[0-9a-f]{64}'),
                         ('certificate_sha256', '[0-9a-f]{64}'), ('image_sha256', '[0-9a-f]{64}'),
                         ('user', '[a-z_][a-z0-9_-]{0,30}'), ('package', '[a-z0-9][a-z0-9@._+-]{0,127}')]:
        require(isinstance(value.get(key), str) and re.fullmatch(pattern, value[key]), 'invalid fault input: ' + key)
    require(value['user'] not in ['root', 'live'], 'ordinary installed test user required')
    require(value.get('encryption') in ['none', 'LUKS2'], 'unsupported encryption')
    return value


def firmware():
    result = {}
    for name in ['SecureBoot', 'SetupMode']:
        paths = list(Path('/sys/firmware/efi/efivars').glob(name + '-*'))
        require(len(paths) == 1, 'missing or ambiguous firmware variable ' + name)
        value = paths[0].read_bytes()
        require(len(value) == 5 and value[4] in [0, 1], 'invalid firmware variable ' + name)
        result[name] = bool(value[4])
    require(result == {'SecureBoot': True, 'SetupMode': False}, 'firmware enforcement was lost')
    return result


def guest_guard(live=False):
    require(sys.platform == 'linux' and os.geteuid() == 0, 'root Linux test guest required')
    require(Path('/dev/virtio-ports/org.astraeus.validation').exists()
            and call('systemd-detect-virt')['output'].strip() == 'kvm', 'dedicated KVM validation channel required')
    require(Path('/run/archiso').exists() == live, 'wrong installed/recovery environment')
    config = configuration(json.loads((SHARE / 'fault-config.json').read_text()))
    require(digest('/usr/bin/distroctl') == config['distroctl_sha256'], 'candidate coordinator changed')
    require(digest('/usr/bin/astraeus-control-center') == config['desktop_sha256'], 'candidate desktop changed')
    firmware()
    if not live:
        # Public image trust remains observable during intentional key/signing-state failures.
        config['maintained_uki_verification'] = verify_maintained_uki(
            lambda *args: call(*args)['output'], config['certificate_sha256'])
    return config


def home_path(config):
    return Path('/home', config['user'], '.astraeus-phase42-fault-' + config['run_id'])


def guest_home():
    import pwd
    config = guest_guard()
    owner = pwd.getpwnam(config['user'])
    path = home_path(config)
    require(path.parent.is_dir() and not path.parent.is_symlink(), 'test home is unavailable')
    with path.open('xb') as stream:
        stream.write(('persistent-home:' + config['run_id'] + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)
    os.chown(path, owner.pw_uid, owner.pw_gid)
    return {'path': str(path), 'sha256': digest(path), 'uid': path.stat().st_uid}


def guest_observe():
    config = guest_guard()
    exported = json.loads(call('distroctl', 'system', 'export', '--json')['output'])
    packages = {}
    for line in call('pacman', '-Q')['output'].splitlines():
        name, version = line.split()
        require(name not in packages, 'duplicate installed package')
        packages[name] = version
    reasons = {}
    for option, reason in [('-Qqe', 'explicit'), ('-Qqd', 'dependency')]:
        output = call('pacman', option, check=False)
        require(output['code'] in [0, 1] and not output['error'], 'installed reason query failed')
        for name in output['output'].splitlines():
            require(name in packages and name not in reasons, 'inconsistent installed reasons')
            reasons[name] = reason
    require(packages.keys() == reasons.keys(), 'incomplete installed reasons')
    home = home_path(config)
    root_uuid = call('findmnt', '-rn', '-M', '/', '-o', 'UUID')['output'].strip()
    esp_uuid = call('findmnt', '-rn', '-M', '/efi', '-o', 'UUID')['output'].strip()
    require(re.fullmatch('[0-9a-fA-F-]{36}', root_uuid) and re.fullmatch('[0-9a-fA-F]{4}-[0-9a-fA-F]{4}', esp_uuid),
            'unexpected filesystem identities')
    return {'schema_version': 1, 'packages': packages, 'reasons': reasons,
            'configuration': exported['configuration'], 'management': json.loads(STATE.read_text()),
            'system_lock': json.loads(STATE.with_name('system.lock').read_text()),
            'config_toml': Path('/etc/astraeus/system.toml').read_text(),
            'root_uuid': root_uuid, 'esp_uuid': esp_uuid, 'firmware': firmware(),
            'maintained_uki_verification': config['maintained_uki_verification'],
            'home': {'sha256': digest(home), 'uid': home.stat().st_uid} if home.exists() else None,
            'package_lock_present': Path('/var/lib/pacman/db.lck').exists(),
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def barrier_paths(config):
    token = config['run_id']
    return (Path('/run/astraeus-phase42-' + token),
            Path('/etc/pacman.d/hooks/00-astraeus-phase42-' + token + '.hook'),
            Path('/var/log/astraeus/phase42-barrier-' + token + '.json'))


def guest_arm_hook(kind='interruption'):
    require(kind in ['interruption', 'failed-hook', 'signing-failure'], 'invalid hook fault')
    config = guest_guard()
    runtime, hook, marker = barrier_paths(config)
    require(not runtime.exists() and not hook.exists() and not marker.exists(), 'fault fixture already exists')
    runtime.mkdir(mode=0o700)
    hook.parent.mkdir(mode=0o755, exist_ok=True)
    marker.parent.mkdir(mode=0o755, exist_ok=True)
    script = runtime / 'barrier.py'
    source = '''import json,os,pathlib,stat,sys,time
pid=os.getppid()
chain=[]
while pid>1:
    path=pathlib.Path('/proc',str(pid))
    args=path.joinpath('cmdline').read_bytes().split(b'\\0')
    chain.append({'pid':pid,'argv':[v.decode() for v in args if v]})
    if len(args)>=4 and args[1:3]==[b'system',b'worker']:
        record={'worker_pid':pid,'worker_start_ticks':int(path.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]),'operation_id':args[3].decode(),'ancestors':chain}
        break
    pid=int(next(line.split()[1] for line in path.joinpath('status').read_text().splitlines() if line.startswith('PPid:')))
else: raise RuntimeError('production worker ancestor missing')
'''
    source += 'record["fault"]=' + repr(kind) + '\n'
    if kind == 'signing-failure':
        # Only this disposable guest's private key path changes; its bytes never enter evidence.
        source += '''policy=json.loads(pathlib.Path('/etc/astraeus/secure-boot/policy.json').read_text())
key=pathlib.Path('/var/lib/astraeus/keys/db.key')
assert policy['private_key']==str(key)
info=key.lstat()
assert stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and info.st_mode&0o077==0
backup=key.with_name(''' + repr('db.key.phase42-' + config['run_id']) + ''')
assert not backup.exists()
key.rename(backup)
record['expected_private_key_missing']=not key.exists()
'''
    source += 'path=pathlib.Path(' + repr(str(marker)) + ''')
with path.open('x') as output:
    json.dump(record,output);output.flush();os.fsync(output.fileno())
os.sync()
'''
    source += 'time.sleep(3600)\n' if kind == 'interruption' else 'sys.exit(1)\n' if kind == 'failed-hook' else ''
    script.write_text(source)
    script.chmod(0o600)
    when = 'PreTransaction' if kind == 'failed-hook' else 'PostTransaction'
    hook.write_text('[Trigger]\nOperation = Install\nType = Package\nTarget = ' + config['package']
                    + '\n[Action]\nDescription = Disposable Phase 4.2 fault\nWhen = ' + when + '\n'
                    + 'Exec = /usr/bin/python3 ' + str(script) + '\n'
                    + ('AbortOnFail\n' if kind == 'failed-hook' else ''))
    hook.chmod(0o644)
    os.sync()
    return {'hook': str(hook), 'hook_sha256': digest(hook), 'marker': str(marker), 'when': when, 'fault': kind}


def guest_barrier():
    config = guest_guard()
    marker = barrier_paths(config)[2]
    return json.loads(marker.read_text()) if marker.exists() else None


def entry_evidence(path):
    if not os.path.lexists(path):
        return None
    info = path.lstat()
    result = {'device': info.st_dev, 'inode': info.st_ino, 'uid': info.st_uid,
              'mode': stat.S_IMODE(info.st_mode)}
    if stat.S_ISLNK(info.st_mode):
        return dict(result, kind='symlink', target=os.readlink(path))
    if stat.S_ISDIR(info.st_mode):
        return dict(result, kind='directory')
    require(stat.S_ISREG(info.st_mode) and info.st_size <= 2 * 1024 * 1024, 'unsupported submission evidence file')
    return dict(result, kind='file', sha256=digest(path))


def directory_evidence(path):
    if not os.path.lexists(path):
        return None
    require(path.is_dir() and not path.is_symlink(), 'submission inventory is not a real directory')
    entries = sorted(path.iterdir())
    require(len(entries) <= 4096, 'submission evidence inventory too large')
    return {entry.name: entry_evidence(entry) for entry in entries}


def submission_inventory():
    return {'requests': directory_evidence(SUBMISSIONS / 'requests'),
            'receipts': directory_evidence(RECEIPTS), 'active': entry_evidence(SUBMISSIONS / 'active'),
            'history': json.loads(call('distroctl', 'history', '--json')['output'])}


def require_noop(plan):
    require(plan.get('executable') is False and not plan.get('blockers'), 'review is not a true no-op')
    inner = plan['plan']
    require(inner['packages']['changes'] == [] and inner['packages']['targets'] == []
            and inner['management']['before_digest'] == inner['management']['after_digest']
            and inner['management']['reasons_before'] == inner['management']['reasons_after']
            and inner['snapshot_required'] is False and inner['boot']['regenerate_uki'] is False,
            'no-op review contains a mutation')


def json_input(arguments, value):
    result = subprocess.run(['/usr/bin/distroctl', *arguments],
             input=json.dumps(value, separators=(',', ':')).encode(), capture_output=True, timeout=30,
             env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    require(len(result.stdout) + len(result.stderr) <= 2 * 1024 * 1024, 'submission output too large')
    return {'code': result.returncode, 'output': result.stdout.decode('utf-8', 'strict'),
            'error': result.stderr.decode('utf-8', 'replace')}


def envelope(name):
    value = json.loads((SHARE / name).read_text())
    require(isinstance(value, dict) and set(value) == {'schema_version', 'config', 'expected_plan'}
            and type(value['schema_version']) is int and value['schema_version'] == 1
            and re.fullmatch('sha256:[0-9a-f]{64}', value.get('expected_plan', '')), 'invalid reviewed test submission')
    return value


def idle_noop():
    value = envelope('submission-noop.json')
    status = json.loads(call('distroctl', 'system', 'status', '--json')['output'])
    active = status.get('active_operation')
    require(not active or active['state'] in ('succeeded', 'failed', 'rolled_back'), 'submission fixture requires an idle guest')
    require(value['config'] == status['configuration'], 'no-op configuration is not the current configuration')
    history = json.loads(call('distroctl', 'history', '--json')['output'])
    require(all(item['state'] in ('succeeded', 'failed', 'rolled_back') for item in history), 'pending transaction prevents fixture')
    units = call('systemctl', 'list-units', '--all', '--plain', '--no-legend', '--no-pager', 'astraeus-apply@*.service')['output']
    for line in units.splitlines():
        name = line.split()[0]
        require(re.fullmatch('astraeus-apply@[0-9a-f]{32}\\.service', name), 'unexpected worker unit')
        shown = call('systemctl', 'show', '--all', '--property=LoadState,ActiveState,Job', name)['output']
        require(unit_idle(shown), 'worker unit is not idle')
    planned = json_input(['system', 'plan', '--stdin', '--json'], value['config'])
    require(planned['code'] == 0, 'no-op revalidation failed')
    plan = json.loads(planned['output'])
    require_noop(plan)
    require(plan['plan_id'] == value['expected_plan'], 'reviewed no-op is stale')
    return value


def submission_fixture(config, kind):
    parent = Path('/var/log/astraeus')
    parent.mkdir(mode=0o755, exist_ok=True)
    info = parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & 0o022 == 0, 'untrusted test evidence directory')
    path = parent / ('phase42-submission-' + config['run_id'] + '-' + kind)
    path.mkdir(mode=0o700)
    sync_directory(parent)
    return path


def sync_directory(path):
    if os.name == 'posix':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def save_submission_evidence(fixture, record):
    descriptor = os.open(fixture / 'result.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(record, output, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    sync_directory(fixture)


def unlink_owned_symlink(path, identity, target):
    info = path.lstat()
    require(stat.S_ISLNK(info.st_mode) and (info.st_dev, info.st_ino) == identity
            and os.readlink(path) == str(target), 'owned test symlink changed; preserve it for inspection')
    path.unlink()


def guest_submission_symlink():
    config = guest_guard()
    value = idle_noop()
    request_dir = SUBMISSIONS / 'requests'
    require(not os.path.lexists(request_dir), 'symlink fixture requires absent request staging; never move existing requests')
    SUBMISSIONS.mkdir(mode=0o755, exist_ok=True)
    info = SUBMISSIONS.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & 0o022 == 0, 'untrusted submission parent')
    fixture = submission_fixture(config, 'symlink')
    canary = fixture / 'canary'
    canary.mkdir(mode=0o700)
    descriptor = os.open(canary / 'sentinel', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write(config['run_id'] + '\n')
        output.flush()
        os.fsync(output.fileno())
    sync_directory(canary)
    sync_directory(fixture)
    before = submission_inventory()
    original = directory_evidence(canary)
    request_dir.symlink_to(canary, target_is_directory=True)
    info = request_dir.lstat()
    identity = (info.st_dev, info.st_ino)
    record = {'passed': False, 'fixture': str(fixture), 'before': before, 'canary_before': original}
    try:
        record['reply'] = json_input(['system', 'submit', '--json'], value)
        record['canary_after'] = directory_evidence(canary)
        require(record['reply']['code'] != 0 and 'link or non-directory' in record['reply']['error'], 'symlink staging was not refused by its path guard')
        require(record['canary_after'] == original, 'submission wrote through the staging symlink; preserve canary evidence')
        unlink_owned_symlink(request_dir, identity, canary)
        identity = None
        record['after'] = submission_inventory()
        require(record['after'] == before, 'symlink refusal changed request, receipt, active or history inventory')
        record['passed'] = True
        return record
    finally:
        try:
            if identity is not None:
                unlink_owned_symlink(request_dir, identity, canary)
        except BaseException as error:
            record.update(passed=False, cleanup_error=str(error))
            raise
        finally:
            save_submission_evidence(fixture, record)


def worker_identity(marker):
    pid, expected = marker.get('worker_pid'), marker.get('worker_start_ticks')
    identifier = marker.get('operation_id', '')
    require(type(pid) is int and pid > 1 and type(expected) is int and expected > 0
            and re.fullmatch('[0-9a-f]{32}', identifier), 'invalid observed worker identity')
    process = Path('/proc', str(pid))
    args = [item for item in (process / 'cmdline').read_bytes().split(b'\0') if item]
    ticks = int((process / 'stat').read_text().rsplit(')', 1)[1].split()[19])
    require(ticks == expected and args[1:] == [b'system', b'worker', identifier.encode()]
            and os.path.samefile(process / 'exe', '/usr/bin/distroctl'), 'observed worker was replaced')
    unit = 'astraeus-apply@' + identifier + '.service'
    require(any(line.split(':', 2)[-1].rstrip().endswith('/' + unit)
                for line in (process / 'cgroup').read_text().splitlines()), 'worker unit differs from operation')
    return {'pid': pid, 'start_ticks': ticks, 'operation_id': identifier, 'unit': unit}


def guest_concurrent_submit(identifier):
    config = guest_guard()
    marker = guest_barrier()
    require(marker and marker['operation_id'] == identifier, 'concurrent test lacks its real worker barrier')
    value = envelope('concurrent-submission.json')
    operation = json.loads(call('distroctl', 'system', 'operation', identifier, '--json')['output'])
    require(operation['state'] == 'applying'
            and operation['transaction']['plan']['management']['after']['applied'] == value['config'], 'concurrent request differs from the applying plan')
    fixture = submission_fixture(config, 'concurrent')
    record = {'passed': False, 'fixture': str(fixture), 'worker_before': worker_identity(marker),
              'before': submission_inventory(), 'state_before': guest_observe()}
    try:
        record['reply'] = json_input(['system', 'submit', '--json'], value)
        record['worker_after'] = worker_identity(marker)
        record['after'] = submission_inventory()
        record['state_after'] = guest_observe()
        require(record['reply']['code'] != 0 and 'another system operation is queued or running' in record['reply']['error'], 'concurrent submission was not refused for its active worker')
        require(record['worker_before'] == record['worker_after'], 'concurrent submission replaced the actual worker')
        require(record['before'] == record['after'], 'concurrent submission changed durable request inventories')
        require(record['state_before'] == record['state_after'], 'concurrent submission changed package or management state')
        record['passed'] = True
        return record
    finally:
        save_submission_evidence(fixture, record)


def guest_worker_start_failure():
    config = guest_guard()
    value = idle_noop()
    require(not os.path.lexists(RUNTIME_MASK), 'runtime template override already exists; preserve it')
    parent = RUNTIME_MASK.parent.lstat()
    require(stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0 and parent.st_mode & 0o022 == 0, 'untrusted runtime unit directory')
    fixture = submission_fixture(config, 'worker-start')
    record = {'passed': False, 'fixture': str(fixture), 'before': submission_inventory(), 'state_before': guest_observe()}
    # Exclusive creation makes ownership of this one runtime mask unambiguous.
    RUNTIME_MASK.symlink_to('/dev/null')
    info = RUNTIME_MASK.lstat()
    identity = (info.st_dev, info.st_ino)
    try:
        call('systemctl', 'daemon-reload')
        require(call('systemctl', 'show', '--property=LoadState', '--value', 'astraeus-apply@' + config['run_id'] + '.service')['output'].strip() == 'masked', 'runtime worker template mask was not observed')
        record['reply'] = json_input(['system', 'submit', '--json'], value)
        require(record['reply']['code'] != 0 and 'worker did not start' in record['reply']['error']
                and 'masked' in record['reply']['error'].lower(), 'submission did not report the injected systemd start failure')
        identifier = (SUBMISSIONS / 'active').read_text().strip()
        require(re.fullmatch('[0-9a-f]{32}', identifier), 'failed start lacks an operation identity')
        operation = json.loads(call('runuser', '-u', config['user'], '--', 'distroctl', 'system', 'operation', identifier, '--json')['output'])
        require(operation['state'] == 'failed' and operation.get('transaction') is None
                and 'masked' in operation.get('error', '').lower(), 'failed-start receipt is not publicly inspectable and terminal')
        record['operation'] = operation
        after = submission_inventory()
        for field, suffix in [('requests', '.queued.json'), ('receipts', '.json')]:
            old = record['before'][field] or {}
            new = after[field] or {}
            require(set(new) - set(old) == {identifier + suffix}
                    and all(new.get(name) == details for name, details in old.items()), 'failed start changed unexpected ' + field)
        require(after['history'] == record['before']['history'], 'worker-start failure created a transaction')
        shown = call('systemctl', 'show', '--all', '--property=LoadState,ActiveState,Job', 'astraeus-apply@' + identifier + '.service')['output']
        require('LoadState=masked' in shown and unit_idle(shown, allow_masked=True), 'failed-start worker or job is still active')
        record['replay'] = call('distroctl', 'system', 'worker', identifier, check=False)
        require(record['replay']['code'] != 0 and 'replay refused' in record['replay']['error'], 'failed-start request was replayed')
        require(submission_inventory() == after, 'failed-start replay changed its inventory')
        record['after'] = after
        record['state_after'] = guest_observe()
        require(record['state_before'] == record['state_after'], 'failed start changed package or management state')
        record['passed'] = True
        return record
    finally:
        try:
            unlink_owned_symlink(RUNTIME_MASK, identity, '/dev/null')
            call('systemctl', 'daemon-reload')
        except BaseException as error:
            record.update(passed=False, cleanup_error=str(error))
            raise
        finally:
            save_submission_evidence(fixture, record)


def available(path):
    value = os.statvfs(path)
    return value.f_bavail * value.f_frsize


def space_paths(config, kind):
    token = config['run_id']
    paths = {'root-space': Path('/var/lib/astraeus-validation/phase42-space-' + token),
             'esp-space': Path('/efi/EFI/Astraeus/phase42-space-' + token + '.reserve'),
             'cache-space': Path('/run/astraeus-validation-space/filler')}
    require(kind in paths, 'unknown capacity fault')
    return Path('/run/astraeus-phase42-space-' + token + '.json'), paths[kind]


def capacity_target(kind, before, required):
    mib = 1024 * 1024
    require(type(before) is int and type(required) is int and before >= required + 64 * mib,
            'baseline already lacks capacity; cannot attribute failure to this fault')
    target = (384 if kind == 'esp-space' else 128) * mib
    require(target < required, 'capacity fixture would not violate the observed package policy')
    allocation = ((before - target) // mib) * mib
    require(0 < allocation <= (1024 if kind == 'esp-space' else 64 * 1024) * mib, 'capacity fixture exceeds its bound')
    return allocation


def reserve_btrfs(descriptor, allocation):
    # Unlike posix_fallocate, this direct wrapper does not emulate reservations
    # with zero writes on a filesystem that lacks native fallocate support.
    library = ctypes.CDLL(None, use_errno=True)
    library.fallocate.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_longlong, ctypes.c_longlong]
    library.fallocate.restype = ctypes.c_int
    require(library.fallocate(descriptor, 0, 0, allocation) == 0,
            'Btrfs reservation failed: errno ' + str(ctypes.get_errno()))


def guest_space_arm():
    config = guest_guard()
    intent = json.loads((SHARE / 'space-target.json').read_text())
    kind = intent['kind']
    record_path, filler = space_paths(config, kind)
    require(not record_path.exists() and not filler.exists(), 'capacity fixture already exists')
    target = {'root-space': '/', 'esp-space': '/efi', 'cache-space': '/var/cache/pacman/pkg'}[kind]
    expected_uuid = intent['esp_uuid'] if kind == 'esp-space' else intent['root_uuid']
    actual_uuid = call('findmnt', '-rn', '-T', target, '-o', 'UUID')['output'].strip()
    require(actual_uuid == expected_uuid, 'capacity fault is not on the observed validation filesystem')
    before = available(target)
    required = intent['required_bytes']
    allocation = capacity_target(kind, before, required)
    if kind == 'cache-space':
        require(not Path('/run/astraeus-validation-space').exists()
                and not Path('/var/cache/pacman/pkg.astraeus-validation-saved').exists(),
                'cache capacity staging already exists')
    record = {'schema_version': 1, 'kind': kind, 'run_id': config['run_id'], 'target': target,
              'path': str(filler), 'required_bytes': required, 'available_before': before,
              'filesystem_uuid': actual_uuid}
    with record_path.open('x') as stream:
        json.dump(record, stream)
        stream.flush()
        os.fsync(stream.fileno())
    record_path.chmod(0o600)
    if kind == 'cache-space':
        call('python3', SHARE / 'phase2-guest.py', 'fault', 'space')
        record.update(method='bounded-16MiB-tmpfs-cache', allocation_limit_bytes=16 * 1024 * 1024)
    else:
        filler.parent.mkdir(mode=0o700 if kind == 'root-space' else 0o755, parents=True, exist_ok=True)
        with filler.open('xb') as output:
            if kind == 'root-space':
                require(call('findmnt', '-rn', '-T', filler, '-o', 'FSTYPE')['output'].strip() == 'btrfs', 'root capacity fixture requires Btrfs')
                reserve_btrfs(output.fileno(), allocation)
                record['method'] = 'Btrfs-preallocation-without-data-writes'
            else:
                remaining = allocation
                block = bytes(1024 * 1024)
                while remaining:
                    count = min(remaining, len(block))
                    output.write(block[:count])
                    remaining -= count
                record['method'] = 'bounded-ESP-reservation'
            output.flush()
            os.fsync(output.fileno())
        filler.chmod(0o600)
        record['allocation_limit_bytes'] = allocation
    os.sync()
    record['available_after'] = available(target)
    record_path.write_text(json.dumps(record))
    require(record['available_after'] < required, 'fault did not create the required real capacity shortfall')
    return record


def guest_space_reset():
    config = guest_guard()
    intent = json.loads((SHARE / 'space-target.json').read_text())
    record_path, filler = space_paths(config, intent['kind'])
    if not record_path.exists():
        return {'cleanup': 'fixture-never-created'}
    record = json.loads(record_path.read_text())
    require(record['run_id'] == config['run_id'] and record['kind'] == intent['kind']
            and record['path'] == str(filler), 'capacity cleanup identity mismatch')
    if intent['kind'] == 'cache-space':
        cache = Path('/var/cache/pacman/pkg')
        if cache.is_symlink():
            call('python3', SHARE / 'phase2-guest.py', 'fault', 'space-reset')
        else:
            require(not Path('/var/cache/pacman/pkg.astraeus-validation-saved').exists(), 'partially staged cache fixture requires inspection')
            staging = Path('/run/astraeus-validation-space')
            if staging.exists():
                mounted = call('findmnt', '-rn', '-M', staging, '-o', 'FSTYPE', check=False)
                if mounted['code'] == 0:
                    require(mounted['output'].strip() == 'tmpfs', 'unexpected cache fixture filesystem')
                    call('umount', staging)
                staging.rmdir()
    elif filler.exists():
        observed = filler.lstat()
        require(stat.S_ISREG(observed.st_mode) and observed.st_uid == 0 and observed.st_nlink == 1, 'unsafe capacity fixture cleanup')
        filler.unlink()
    os.sync()
    after = available(record['target'])
    deadline = time.monotonic() + 30
    while after < record['required_bytes'] and time.monotonic() < deadline:
        time.sleep(0.25)
        os.sync()
        after = available(record['target'])
    require(after >= record['required_bytes'], 'capacity did not recover after fixture removal')
    return {'cleanup': 'only-owned-capacity-fixture-removed', 'available_after': after, 'kind': intent['kind']}


def guest_competing_writer(operation_id):
    config = guest_guard()
    require(re.fullmatch('[0-9a-f]{32}', operation_id), 'invalid operation ID')
    barrier = json.loads(barrier_paths(config)[2].read_text())
    require(barrier['operation_id'] == operation_id, 'barrier belongs to another worker')
    pid = barrier['worker_pid']
    require(type(pid) is int and pid > 1, 'invalid native worker PID')
    process = Path('/proc', str(pid))
    require(process.joinpath('exe').resolve() == Path('/usr/bin/distroctl'), 'worker PID no longer belongs to candidate')
    args = process.joinpath('cmdline').read_bytes().split(b'\0')
    require(args[1:4] == [b'system', b'worker', operation_id.encode()], 'worker invocation changed')
    lock = Path('/var/lib/pacman/db.lck')
    original = lock.stat()
    require(stat.S_ISREG(original.st_mode) and original.st_uid == 0 and original.st_nlink == 1, 'invalid live package lock')
    owned = []
    for descriptor in process.joinpath('fd').iterdir():
        try:
            info = descriptor.stat()
            flags = next(line.split()[1] for line in process.joinpath('fdinfo', descriptor.name).read_text().splitlines()
                         if line.startswith('flags:'))
            if (info.st_dev, info.st_ino) == (original.st_dev, original.st_ino) and int(flags, 8) & 3 in [1, 2]:
                owned.append(descriptor.name)
        except FileNotFoundError:
            continue
    require(owned, 'production coordinator does not hold the writable native package-lock descriptor')
    library = ctypes.CDLL('/usr/lib/libalpm.so.16')
    library.alpm_initialize.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
    library.alpm_initialize.restype = ctypes.c_void_p
    for name in ['alpm_trans_init', 'alpm_trans_release', 'alpm_release', 'alpm_errno']:
        getattr(library, name).argtypes = [ctypes.c_void_p] + ([ctypes.c_int] if name == 'alpm_trans_init' else [])
        getattr(library, name).restype = ctypes.c_int
    library.alpm_strerror.argtypes = [ctypes.c_int]
    library.alpm_strerror.restype = ctypes.c_char_p
    error = ctypes.c_int()
    handle = library.alpm_initialize(b'/', b'/var/lib/pacman', ctypes.byref(error))
    require(handle, 'competing native handle could not initialize')
    try:
        result = library.alpm_trans_init(handle, 0)
        detail = library.alpm_strerror(library.alpm_errno(handle)).decode()
        if result == 0:
            library.alpm_trans_release(handle)
        require(result != 0 and 'lock' in detail.lower(), 'competing package transaction was not refused for its lock')
    finally:
        library.alpm_release(handle)
    current = lock.stat()
    require((current.st_dev, current.st_ino) == (original.st_dev, original.st_ino), 'competing writer changed the live lock')
    return {'operation_id': operation_id, 'worker_pid': pid, 'writable_descriptors': owned,
            'device': original.st_dev, 'inode': original.st_ino, 'competing_result': result, 'diagnostic': detail}


def guest_inject_abandoned():
    config = guest_guard()
    envelope = json.loads((SHARE / 'orphan-submission.json').read_text())
    require(envelope.get('schema_version') == 1 and re.fullmatch('sha256:[0-9a-f]{64}', envelope.get('expected_plan', '')),
            'invalid reviewed orphan request')
    active = json.loads(call('distroctl', 'system', 'status', '--json')['output']).get('active_operation')
    require(not active or active['state'] in ['succeeded', 'failed', 'rolled_back'], 'another operation exists')
    operation_id = config['run_id']
    root = Path('/run/astraeus')
    requests = root / 'requests'
    receipts = Path('/var/log/astraeus/operations')
    for path, mode in [(root, 0o755), (requests, 0o700), (receipts.parent, 0o755), (receipts, 0o755)]:
        path.mkdir(mode=mode, exist_ok=True)
        require(not path.is_symlink() and path.stat().st_uid == 0, 'untrusted fault staging directory')
        path.chmod(mode)
    # Inject exactly the documented durable boundary, without claiming an actual submit process was killed.
    request = {'schema_version': 1, 'operation_id': operation_id, 'initiating_uid': 0, 'submission': envelope}
    receipt = {'schema_version': 1, 'operation_id': operation_id,
               'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'created_unix_seconds': int(time.time()) - 31, 'state': 'queued', 'transaction_id': None, 'error': None}
    for path, value, mode in [(requests / (operation_id + '.queued.json'), request, 0o600),
                              (receipts / (operation_id + '.json'), receipt, 0o644)]:
        with path.open('x') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(mode)
    active_path = root / 'active'
    require(not active_path.is_symlink(), 'untrusted active pointer')
    active_path.write_text(operation_id)
    active_path.chmod(0o644)
    os.sync()
    return {'method': 'injected-durable-submit-boundary', 'receipt': receipt,
            'request_sha256': digest(requests / (operation_id + '.queued.json'))}


def guest_recover(snapshot):
    config = guest_guard(live=True)
    require(re.fullmatch('[0-9-]{1,80}', snapshot), 'invalid snapshot ID')
    expected = json.loads((SHARE / 'recovery-target.json').read_text())
    require(expected['snapshot'] == snapshot and expected['run_id'] == config['run_id'], 'recovery target mismatch')
    source = '/dev/vda2'
    if config['encryption'] == 'LUKS2':
        require(call('cryptsetup', 'isLuks', '--type', 'luks2', source, check=False)['code'] == 0,
                'expected encrypted validation partition')
        require(Path('/dev/mapper/root').exists(), 'unlock only the disposable /dev/vda2 as root through private QMP')
        source = '/dev/mapper/root'
        status = call('cryptsetup', 'status', 'root')['output']
        require(re.search(r'^\s*device:\s*/dev/vda2\s*$', status, re.M), 'mapper is not the validation root partition')
    require(call('blkid', '-s', 'UUID', '-o', 'value', source)['output'].strip() == expected['root_uuid'], 'wrong root UUID')
    require(call('blkid', '-s', 'UUID', '-o', 'value', '/dev/vda1')['output'].strip() == expected['esp_uuid'], 'wrong ESP UUID')
    top, esp = Path('/mnt/astraeus-fault-root'), Path('/mnt/astraeus-fault-esp')
    require(not top.exists() and not esp.exists(), 'recovery mountpoints already exist')
    top.mkdir(mode=0o700)
    esp.mkdir(mode=0o700)
    mounted = []
    try:
        call('mount', '-t', 'btrfs', '-o', 'subvolid=5', source, top)
        mounted.append(top)
        call('mount', '-t', 'vfat', '-o', 'umask=0077', '/dev/vda1', esp)
        mounted.append(esp)
        require(digest(top / '@' / 'usr/bin/distroctl') == config['distroctl_sha256'], 'installed coordinator changed before recovery')
        common = ['--top-level', str(top), '--esp', str(esp), '--json']
        planned = json.loads(call('distroctl', 'rollback', snapshot, '--dry-run', *common, timeout=300)['output'])
        require(planned.get('execution_supported') is True and planned['target']['id'] == snapshot
                and planned['target']['schema_version'] == 2, 'offline rollback plan is not the correlated protocol-2 target')
        restored = json.loads(call('distroctl', 'rollback', snapshot, '--execute', *common, timeout=900)['output'])
        require(restored['plan']['target']['id'] == snapshot and restored.get('operation_id'), 'rollback did not return durable restoration evidence')
        require(not (top / '@' / 'var/lib/pacman/db.lck').exists(), 'saved native lock survived rollback')
        return {'plan': planned, 'restored': restored, 'firmware': firmware()}
    finally:
        for path in reversed(mounted):
            call('umount', path)


def guest_metadata_negative():
    guest_guard()
    trial = json.loads((SHARE / 'metadata-negative.json').read_text())
    require(type(trial.get('transaction_id')) is int and trial['transaction_id'] > 0, 'invalid metadata trial transaction')
    before, after = trial['before'], trial['after']
    actual = guest_observe()
    state_equal(before, actual)  # Never repair a failed rollback to make this negative control pass.
    require(before['packages'] == after['packages'] and before['reasons'] == after['reasons']
            and before['management'] != after['management'], 'negative control must change only valid management metadata')
    paths = [Path('/etc/astraeus/system.toml'), STATE.with_name('system.lock'), STATE]
    saved = [path.read_bytes() for path in paths]
    replacements = [after['config_toml'].encode(), json.dumps(after['system_lock']).encode(), json.dumps(after['management']).encode()]
    def write(values):
        for path, value in zip(paths, values):
            temporary = path.with_name(path.name + '.phase42-negative')
            with temporary.open('xb') as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o644)
            temporary.replace(path)
        os.sync()
    try:
        write(replacements)
        exported = json.loads(call('distroctl', 'system', 'export', '--json')['output'])
        require(exported['configuration'] == after['configuration'], 'negative control is not internally consistent')
        result = call('distroctl', 'finalize-rollback', str(trial['transaction_id']), check=False)
        require(result['code'] != 0 and 'booted applied configuration, ownership or package reasons differ' in result['error'],
                'wrong metadata was accepted after restoring equal package versions')
        return {'method': 'consistent-wrong-management-negative-control', 'rejected': True, 'diagnostic': result['error']}
    finally:
        write(saved)
        require([path.read_bytes() for path in paths] == saved, 'negative control did not restore its original bytes')


def guest(action, value):
    functions = {'home': guest_home, 'observe': guest_observe, 'arm': guest_arm_hook,
                 'barrier': guest_barrier, 'abandoned': guest_inject_abandoned,
                 'metadata-negative': guest_metadata_negative, 'space-arm': guest_space_arm,
                 'space-reset': guest_space_reset, 'submission-symlink': guest_submission_symlink,
                 'worker-start-failure': guest_worker_start_failure}
    if action in functions:
        result = functions[action]()
    elif action == 'compete':
        result = guest_competing_writer(value)
    elif action == 'recover':
        result = guest_recover(value)
    elif action == 'arm-failure':
        result = guest_arm_hook(value)
    elif action == 'concurrent-submit':
        result = guest_concurrent_submit(value)
    else:
        raise ValueError('unsupported guest fault action')
    print(json.dumps(result, sort_keys=True))


def host_modules():
    import phase42
    return phase42, phase42.p2


def stage_guest_scripts(share):
    for name in ['phase42-faults.py', 'phase2-guest.py', 'phase42_trust.py']:
        shutil.copyfile(Path(__file__).with_name(name), share / name)


def candidate_guard(args, manifest, firmware_sha256):
    phase42, _ = host_modules()
    phase42.candidate_matches(manifest, args.source_commit, args.image_sha256, firmware_sha256, args.encryption)
    require(manifest.get('kind') == 'phase42-fresh-candidate-payload' and manifest.get('source_commit') == args.source_commit,
            'faults require a fresh candidate baseline, never an earlier qualified OS')
    require(manifest.get('installed_binaries') == {'distroctl': args.distroctl_sha256,
                                                  'astraeus-control-center': args.desktop_sha256}, 'baseline binary pins disagree')
    require(re.fullmatch('[0-9a-f]{64}', manifest.get('signer_sha256', '')), 'baseline signer pin missing')
    require(manifest.get('public_fingerprints', {}).get('db') == manifest['signer_sha256'], 'baseline signer pins disagree')
    require(len(set(manifest.get('boot_ids', []))) >= 2, 'baseline lacks two accepted boots')
    firmware_provenance(manifest)


def firmware_provenance(manifest):
    installation = manifest.get('installation_firmware', {})
    management = manifest.get('management_firmware_required', {})
    require(isinstance(installation, dict) and installation.get('observed') is True
            and installation.get('source') == 'efivarfs-before-partition-write'
            and installation.get('SecureBoot') is False and installation.get('SetupMode') is True,
            'baseline lacks observed SetupMode installation provenance')
    require(isinstance(management, dict) and management.get('SecureBoot') is True
            and management.get('SetupMode') is False, 'baseline lacks enforcing management policy')
    return {'installation_firmware': dict(installation), 'management_firmware_required': dict(management)}


def recovery_guard(args, manifest, recovery):
    require(recovery.get('schema_version') == 1 and recovery.get('kind') == 'phase42-ram-verified-recovery', 'unsupported recovery manifest')
    require(recovery.get('source_commit') == args.source_commit and recovery.get('iso_sha256') == args.image_sha256,
            'recovery medium is not derived from this exact candidate')
    require(recovery.get('image') == args.recovery_image.name and recovery.get('image_sha256') == digest(args.recovery_image),
            'recovery image changed')
    require(recovery.get('image_bytes') == args.recovery_image.stat().st_size, 'recovery image size changed')
    require(recovery.get('certificate_sha256') == manifest['signer_sha256']
            and recovery.get('distroctl_sha256') == args.distroctl_sha256, 'recovery signer or coordinator differs')
    require(recovery.get('baseline_manifest_sha256') == digest(args.base / 'baseline.json'), 'recovery medium belongs to another baseline receipt')
    require(recovery.get('private_key_in_image') is False, 'recovery private-key audit missing')
    for name in ['rootfs_sha256', 'uki_sha256']:
        require(isinstance(recovery.get(name), str) and re.fullmatch('[0-9a-f]{64}', recovery[name]), 'invalid recovery pin ' + name)
    require(type(recovery.get('minimum_ram_gib')) is int and 4 <= recovery['minimum_ram_gib'] <= 64,
            'invalid recovery RAM budget')


def guest_command(vm, action, value=None, label=None):
    command = ['python3', (SHARE / 'phase42-faults.py').as_posix(), 'guest', action]
    if value is not None:
        command += [str(value)]
    return json.loads(vm.command(shlex.join(command), timeout=1000 if action == 'recover' else 180,
                                 label=label or action)['output'])


def state_equal(expected, actual):
    for field in ['packages', 'reasons', 'configuration', 'management', 'system_lock', 'config_toml',
                  'root_uuid', 'esp_uuid', 'firmware', 'home']:
        require(expected[field] == actual[field], 'restored state differs: ' + field)
    require(not actual['package_lock_present'], 'restored package lock is not clean')


def metadata_plan(plan, before):
    require(plan.get('executable') is True and not plan.get('blockers'), 'metadata request is not executable')
    inner = plan['plan']
    require(inner['packages']['changes'] == [] and inner['packages']['targets'] == [], 'metadata fixture unexpectedly changes packages')
    managed = inner['management']
    require(managed['before'] == before['management'] and managed['before_digest'] != managed['after_digest'], 'metadata intent was not bound')
    require(managed.get('reasons_before') == before['reasons'] and managed.get('reasons_after') == before['reasons'],
            'metadata fixture changes or mismatches the observed package reasons')
    require(inner['snapshot_required'] is True and inner['boot']['regenerate_uki'] is True, 'metadata mutation lacks recovery/boot requirements')


def transaction_boundary(record, post=False):
    phases = [event['state'] for event in record['events']]
    require('snapshot_created' in phases and 'applying' in phases and phases.index('snapshot_created') < phases.index('applying'),
            'mutation lacks a prior durable snapshot')
    require(record.get('snapshot'), 'pre-transaction snapshot missing')
    if post:
        require(record.get('post_snapshot') and record.get('boot_regenerated') is True, 'post-generation boot evidence missing')


def unit_idle(text, allow_failed=False, allow_masked=False):
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition('=')
        require(separator and key in ['LoadState', 'ActiveState', 'Job'] and key not in values, 'invalid worker unit observation')
        values[key] = value
    require(set(values) == {'LoadState', 'ActiveState', 'Job'}, 'incomplete worker unit observation')
    return (values['LoadState'] in (['loaded', 'not-found', 'masked'] if allow_masked else ['loaded', 'not-found'])
            and values['ActiveState'] in (['inactive', 'failed'] if allow_failed else ['inactive'])
            and values['Job'] in ['', '0'])


def wait_worker_exit(vm, identifier, timeout, allow_failed=False):
    require(re.fullmatch('[0-9a-f]{32}', identifier), 'invalid worker operation ID')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = vm.command(shlex.join(['systemctl', 'show', '--all', '--property=LoadState,ActiveState,Job',
                                       'astraeus-apply@' + identifier + '.service']), label='wait-worker-exit')
        if unit_idle(result['output'], allow_failed):
            return
        time.sleep(0.25)
    raise TimeoutError('worker/finalizer did not finish after its terminal transaction phase')


def installed_boot(vm, args, reboot=False):
    _, p2 = host_modules()
    previous = vm.boot_id if reboot else None
    if reboot:
        vm.shutdown()
    vm.start()
    p2.save(vm.out / 'attention.json', {'stage': 'installed-unlock', 'qmp': str(vm.monitor),
            'encryption': args.encryption, 'user': args.user,
            'instruction': 'Unlock this disposable guest through its private QMP console if encrypted. Credentials stay outside evidence.'})
    print('Installed guest started; current private QMP is recorded in ' + str(vm.out / 'attention.json'), flush=True)
    vm.ready()
    if previous is not None:
        require(vm.boot_id != previous, 'reboot reused the prior boot identity')
        p2.save(vm.session / 'reboot.json', {'previous': previous, 'current': vm.boot_id})


def start_recovery(vm, args, recovery):
    _, p2 = host_modules()
    vm.shutdown()
    original = p2.install.qemu_command
    def command(*values, **options):
        result = original(*values, **options)
        osdisk = 'virtio-blk-pci,drive=osdisk,bootindex=1'
        require(osdisk in result, 'unexpected VM system disk attachment')
        result[result.index(osdisk)] = 'virtio-blk-pci,drive=osdisk,bootindex=2'
        result[result.index('-m') + 1] = str(recovery['minimum_ram_gib'] * 1024)
        result += ['-drive', f'if=none,id=recovery,format=raw,readonly=on,file={args.recovery_image}',
                   '-device', 'usb-storage,drive=recovery,bootindex=1']
        return result
    p2.install.qemu_command = command
    try:
        vm.start()
    finally:
        p2.install.qemu_command = original
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        vm.alive()
        serial = vm.session / 'serial.log'
        if serial.exists():
            log = serial.read_text(errors='replace')
            if SECURE_LIVE_MARKER in log and LIVE_DESKTOP_MARKER in log:
                break
        time.sleep(1)
    else:
        raise TimeoutError('signed recovery did not attest its verified RAM root')
    bootstrap = 'sudo mkdir -p /mnt/astraeus-validation && sudo mount -t 9p -o trans=virtio,ro acceptance /mnt/astraeus-validation && sudo systemd-run --unit=astraeus-live-validation python3 /mnt/astraeus-validation/phase2-guest.py serve'
    if args.encryption == 'LUKS2':
        bootstrap = 'sudo cryptsetup open /dev/vda2 root && ' + bootstrap
    p2.save(vm.out / 'attention.json', {'stage': 'signed-live-recovery', 'qmp': str(vm.monitor),
            'command': bootstrap,
            'unlock': 'For LUKS2 only: sudo cryptsetup open /dev/vda2 root. Enter the test passphrase through private QMP only.'})
    print('Start the recovery command channel and unlock LUKS if needed through private QMP; see attention.json.', flush=True)
    vm.ready()


def offline_restore(vm, args, recovery, before, record, metadata_after=None):
    phase42, p2 = host_modules()
    _, old_history = phase42.json_command(vm, ['history', '--json'], label='before-offline-history')
    expected_ids = {item['id'] for item in old_history}
    p2.save(vm.share / 'recovery-target.json', {'run_id': args.run_id, 'snapshot': record['snapshot'],
                                              'root_uuid': before['root_uuid'], 'esp_uuid': before['esp_uuid']})
    start_recovery(vm, args, recovery)
    result = guest_command(vm, 'recover', record['snapshot'], label='offline-restore')
    p2.save(vm.out / 'offline-restore.json', result)
    installed_boot(vm, args, reboot=True)
    vm.command('systemctl start astraeus-confirm-boot.service', timeout=120, label='wait-automatic-confirmation')
    _, records = phase42.json_command(vm, ['history', '--json'], label='before-explicit-finalization')
    require(len(records) == len(expected_ids) and {item['id'] for item in records} == expected_ids,
            'recovery boot replayed or lost a durable transaction')
    restored_record = next(item for item in records if item['id'] == record['id'])
    require(restored_record['state'] == record['state'], 'offline restore falsely finalized a transaction')
    state_equal(before, guest_command(vm, 'observe', label='before-rollback-finalization'))
    if metadata_after is not None:
        p2.save(vm.share / 'metadata-negative.json', {'transaction_id': record['id'], 'before': before, 'after': metadata_after})
        negative = guest_command(vm, 'metadata-negative', label='wrong-metadata-finalization-refusal')
        p2.save(vm.out / 'wrong-metadata-finalization-refusal.json', negative)
    finalized = json.loads(vm.command(shlex.join(['distroctl', 'finalize-rollback', str(record['id'])]),
                                      label='finalize-rollback')['output'])
    require(finalized['state'] == 'rolled_back' and finalized.get('confirmation', {}).get('rollback') is True
            and finalized['confirmation'].get('error') is None, 'rollback lacked verified finalization')
    require(finalized['confirmation']['boot_id'] != record['update_boot_id'], 'rollback was finalized in the original boot')
    actual = guest_command(vm, 'observe', label='restored-state')
    state_equal(before, actual)
    vm.command('astraeus-secure-boot check-config', label='restored-signing-identity')
    _, snapshots = phase42.json_command(vm, ['snapshot', 'list', '--json'], label='restored-snapshots')
    require(record['snapshot'] in {item['id'] for item in snapshots}, 'recovery snapshot was lost')
    p2.healthy(p2.observe(vm, 'restored-health'), args.encryption)
    return finalized


def reviewed(vm, config, user, label):
    phase42, _ = host_modules()
    _, plan = phase42.json_command(vm, ['system', 'plan', '--stdin', '--json'], config, user, label=label)
    require(plan.get('executable') is True and not plan.get('blockers'), 'reviewed request is blocked: ' + json.dumps(plan.get('blockers')))
    return plan


def submitted(vm, config, plan, label):
    phase42, _ = host_modules()
    _, operation = phase42.json_command(vm, ['system', 'submit', '--json'],
                                       {'schema_version': 1, 'config': config, 'expected_plan': plan['plan_id']}, label=label)
    require(operation.get('state') == 'queued' and re.fullmatch('[0-9a-f]{32}', operation.get('operation_id', '')),
            'submission was not acknowledged')
    return operation['operation_id']


def reject_replay(vm, identifier, label):
    before = guest_command(vm, 'observe', label=label + '-before')
    result = vm.command(shlex.join(['distroctl', 'system', 'worker', identifier]), check=False, label=label)
    require(result['code'] != 0 and 'replay refused' in result['output'], 'started request was replayed')
    require(guest_command(vm, 'observe', label=label + '-after') == before, 'replay refusal changed the system')


def failed_mutation(record, expected_phase, diagnostic):
    require(record.get('state') == 'rollback_required' and record.get('failure', {}).get('at') == expected_phase,
            'failed mutation did not retain the correct recovery phase')
    transaction_boundary(record)
    require(diagnostic in record['failure']['message'] and not record.get('post_snapshot')
            and not record.get('boot_regenerated') and not record.get('confirmation'),
            'failed mutation was published as a complete candidate')


def failure_scenario(vm, args, recovery, gate, before):
    phase42, _ = host_modules()
    kind = args.active_scenario
    require(kind in ['failed-hook', 'signing-failure'] and args.package not in before['packages'], 'invalid failed-mutation fixture')
    gate('arm-' + kind, lambda: guest_command(vm, 'arm-failure', kind))
    desired = copy.deepcopy(before['configuration'])
    desired['packages'] = sorted([*desired['packages'], args.package])
    plan = gate(kind + '-plan', lambda: reviewed(vm, desired, args.user, kind + '-plan'))
    require(any(change.get('kind') == 'install' and change.get('name') == args.package for change in plan['plan']['packages']['changes']),
            'fault hook will not be triggered by the reviewed transaction')
    def apply():
        identifier = submitted(vm, desired, plan, kind + '-submit')
        operation = phase42.wait_operation(vm, identifier, args.timeout)
        wait_worker_exit(vm, identifier, args.timeout)
        record = operation.get('transaction')
        require(isinstance(record, dict), 'failed worker did not retain a durable transaction')
        failed_mutation(record, 'applying' if kind == 'failed-hook' else 'validating',
                        'package application' if kind == 'failed-hook' else 'boot artifact regeneration')
        injected = guest_command(vm, 'barrier', label=kind + '-actual-fault')
        require(injected and injected['operation_id'] == identifier and injected.get('fault') == kind, 'failure did not reach the injected condition')
        observed = guest_command(vm, 'observe', label=kind + '-resulting-state')
        if kind == 'failed-hook':
            require('hook' in record['failure']['message'].lower(), 'native package error is not the failed hook')
            state_equal(before, observed)
        else:
            require(injected.get('expected_private_key_missing') is True and args.package in observed['packages']
                    and observed['management'] == record['plan']['management']['after'], 'signing fault did not occur after real package/management application')
            probe = vm.command('astraeus-secure-boot check-config', check=False, label='actual-disabled-signing-provider')
            require(probe['code'] != 0 and 'db.key' in probe['output'], 'configured signer did not reject its missing private key')
        vm.command(shlex.join(['journalctl', '--no-pager', '--unit=astraeus-apply@' + identifier + '.service']), label=kind + '-worker-journal')
        return record
    record = gate(kind + '-durable-recovery', apply)
    gate(kind + '-no-replay', lambda: reject_replay(vm, record['operation_id'], kind + '-replay-refusal'))
    gate(kind + '-offline-rollback', lambda: offline_restore(vm, args, recovery, before, record))


def capacity_budget(plan, kind):
    if kind == 'esp-space':
        require(plan['plan']['boot']['regenerate_uki'] is True, 'ESP capacity case requires boot regeneration')
        return 512 * 1024 * 1024
    packages = plan['plan']['packages']
    return packages['download_bytes'] + sum(target['installed_bytes'] for target in packages['targets']) + 256 * 1024 * 1024


def capacity_failure(record, required):
    require(record.get('state') == 'failed' and record.get('failure', {}).get('at') == 'preparing', 'capacity refusal occurred after the safe preflight boundary')
    expected = f'package prerequisites: insufficient disk space: {required} bytes required'
    require(expected in record['failure']['message'] and not record.get('snapshot') and not record.get('post_snapshot')
            and not record.get('boot_regenerated') and not record.get('confirmation'), 'capacity refusal lacks its exact cause or mutated recovery/boot state')


def allocated_bytes(path):
    return path.stat().st_blocks * 512


def space_scenario(vm, args, recovery, gate, before):
    phase42, p2 = host_modules()
    kind = args.active_scenario
    require(args.package not in before['packages'], 'capacity package must start absent')
    desired = copy.deepcopy(before['configuration'])
    desired['packages'] = sorted([*desired['packages'], args.package])
    plan = gate(kind + '-plan', lambda: reviewed(vm, desired, args.user, kind + '-plan'))
    require(any(change.get('kind') == 'install' and change.get('name') == args.package for change in plan['plan']['packages']['changes']),
            'capacity fixture needs the nominated package installation')
    required = capacity_budget(plan, kind)
    p2.save(vm.share / 'space-target.json', {'kind': kind, 'required_bytes': required,
                                          'root_uuid': before['root_uuid'], 'esp_uuid': before['esp_uuid']})
    overlay = vm.out / 'disk.qcow2'
    allocated_before = allocated_bytes(overlay)
    growth_limit = (1024 if kind == 'esp-space' else 512) * 1024 * 1024
    require(shutil.disk_usage(vm.out).free >= growth_limit + 4 * 1024 ** 3, 'validator lacks safe physical headroom for this bounded capacity fixture')
    record = None
    try:
        injected = gate(kind + '-actual-shortfall', lambda: guest_command(vm, 'space-arm'))
        host_growth = max(0, allocated_bytes(overlay) - allocated_before)
        p2.save(vm.out / 'capacity-host-budget.json', {'allocated_before': allocated_before, 'allocation_growth': host_growth,
                                                     'growth_limit': growth_limit, 'free_after': shutil.disk_usage(vm.out).free})
        require(host_growth <= growth_limit and shutil.disk_usage(vm.out).free >= 4 * 1024 ** 3,
                'capacity fixture exceeded the validator physical-allocation budget')
        require(injected['available_after'] < required and injected['required_bytes'] == required, 'capacity evidence disagrees with actual native policy')
        def refused():
            identifier = submitted(vm, desired, plan, kind + '-submit')
            operation = phase42.wait_operation(vm, identifier, args.timeout)
            wait_worker_exit(vm, identifier, args.timeout)
            record = operation.get('transaction')
            require(isinstance(record, dict), 'capacity failure lacks a durable transaction')
            capacity_failure(record, required)
            state_equal(before, guest_command(vm, 'observe', label=kind + '-unchanged-state'))
            return record
        record = gate(kind + '-preflight-refusal', refused)
        gate(kind + '-no-replay', lambda: reject_replay(vm, record['operation_id'], kind + '-replay-refusal'))
    finally:
        gate(kind + '-remove-only-owned-fixture', lambda: guest_command(vm, 'space-reset'))
    def reboot_refusal():
        require(record is not None, 'capacity refusal did not finish')
        _, history = phase42.json_command(vm, ['history', '--json'], label=kind + '-history-before-reboot')
        installed_boot(vm, args, reboot=True)
        vm.command('systemctl start astraeus-confirm-boot.service', label=kind + '-boot-confirmation')
        _, after = phase42.json_command(vm, ['history', '--json'], label=kind + '-history-after-reboot')
        require(after == history, 'boot replayed or changed the rejected capacity transaction')
        state_equal(before, guest_command(vm, 'observe', label=kind + '-after-reboot-state'))
        p2.healthy(p2.observe(vm, kind + '-recovered-health'), args.encryption)
    gate(kind + '-reboot-without-replay', reboot_refusal)


def reject_same_boot(vm, record):
    phase42, _ = host_modules()
    reply = vm.command(shlex.join(['distroctl', 'confirm-boot', str(record['id'])]), check=False, label='reject-same-boot')
    require(reply['code'] != 0 and any(message in reply['output'] for message in [
        'different kernel boot', 'running boot entry is not a managed generation']),
        'same-boot confirmation did not report the expected boot-evidence refusal')
    _, records = phase42.json_command(vm, ['history', '--json'], label='same-boot-refusal-history')
    current = next(item for item in records if item['id'] == record['id'])
    require(current['state'] == 'awaiting_boot' and not any(
        event['state'] == 'succeeded' for event in current['events']),
        'same-boot confirmation blessed the transaction')


def metadata_scenario(vm, args, recovery, gate, before):
    phase42, p2 = host_modules()
    def no_op():
        _, plan = phase42.json_command(vm, ['system', 'plan', '--stdin', '--json'], before['configuration'], args.user, label='true-noop-plan')
        require(plan.get('executable') is False and not plan.get('blockers'), 'baseline is not a true no-op')
        inner = plan['plan']
        require(inner['packages']['changes'] == [] and inner['management']['before_digest'] == inner['management']['after_digest']
                and inner['management']['reasons_before'] == inner['management']['reasons_after']
                and inner['snapshot_required'] is False and inner['boot']['regenerate_uki'] is False, 'no-op flags disagree')
        state_equal(before, guest_command(vm, 'observe', label='after-noop-plan'))
    gate('true-noop', no_op)
    name = args.metadata_package
    require(name in before['packages'] and name not in before['configuration']['packages'], 'metadata package must be installed but not already explicitly selected')
    desired = copy.deepcopy(before['configuration'])
    desired['packages'] = sorted([*desired['packages'], name])
    def review_metadata():
        plan = reviewed(vm, desired, args.user, 'metadata-plan')
        metadata_plan(plan, before)
        return plan
    plan = gate('metadata-plan', review_metadata)
    def apply():
        identifier = submitted(vm, desired, plan, 'metadata-submit')
        operation = phase42.wait_operation(vm, identifier, args.timeout)
        require(operation['state'] == 'awaiting_boot', 'metadata transaction did not wait for a boot')
        wait_worker_exit(vm, identifier, args.timeout)
        record = operation['transaction']
        transaction_boundary(record, post=True)
        require(record['plan']['packages']['changes'] == [], 'metadata apply changed its reviewed package plan')
        observed = guest_command(vm, 'observe', label='metadata-applied')
        require(observed['packages'] == before['packages'] and observed['reasons'] == before['reasons'], 'metadata-only apply changed packages/reasons')
        require(observed['configuration'] == desired and observed['management'] == record['plan']['management']['after'], 'metadata state differs from reviewed intent')
        p2.save(vm.out / 'metadata-after-state.json', observed)
        reject_same_boot(vm, record)
        return record
    record = gate('metadata-apply-and-same-boot-refusal', apply)
    def confirm():
        installed_boot(vm, args, reboot=True)
        result = phase42.confirmed(vm, record['id'], min(args.timeout, 180))
        require(result['plan']['management']['after'] == guest_command(vm, 'observe', label='metadata-confirmed')['management'],
                'confirmed metadata does not match the booted root')
        return result
    record = gate('metadata-new-boot-confirmation', confirm)
    gate('metadata-offline-rollback', lambda: offline_restore(vm, args, recovery, before, record,
             json.loads((vm.out / 'metadata-after-state.json').read_text())))


def interruption_scenario(vm, args, recovery, gate, before):
    phase42, p2 = host_modules()
    require(args.package not in before['packages'], 'interruption package must start absent')
    _, noop = phase42.json_command(vm, ['system', 'plan', '--stdin', '--json'], before['configuration'], args.user, label='submission-noop-review')
    require_noop(noop)
    p2.save(vm.share / 'submission-noop.json', {'schema_version': 1, 'config': before['configuration'], 'expected_plan': noop['plan_id']})
    def symlink_refusal():
        result = guest_command(vm, 'submission-symlink', label='submission-symlink-refusal')
        require(result['passed'] is True, 'symlink submission fixture did not pass')
        state_equal(before, guest_command(vm, 'observe', label='after-submission-symlink'))
        return result
    gate('submission-refuses-symlinked-request-staging', symlink_refusal)
    gate('install-posttransaction-barrier', lambda: guest_command(vm, 'arm'))
    desired = copy.deepcopy(before['configuration'])
    desired['packages'] = sorted([*desired['packages'], args.package])
    def review_install():
        plan = reviewed(vm, desired, args.user, 'interrupted-install-plan')
        require(any(change.get('kind') == 'install' and change.get('name') == args.package for change in plan['plan']['packages']['changes']),
                'request does not install the nominated fault package')
        return plan
    plan = gate('interrupted-install-plan', review_install)
    p2.save(vm.share / 'concurrent-submission.json', {'schema_version': 1, 'config': desired, 'expected_plan': plan['plan_id']})
    identifier = submitted(vm, desired, plan, 'interrupted-install-submit')
    def at_barrier():
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            marker = guest_command(vm, 'barrier', label='wait-posttransaction-barrier')
            _, operation = phase42.json_command(vm, ['system', 'operation', identifier, '--json'], label='barrier-operation')
            if marker:
                require(marker['operation_id'] == identifier and operation['state'] == 'applying', 'barrier is not the real applying worker')
                transaction_boundary(operation['transaction'])
                require(args.package in guest_command(vm, 'observe', label='mutated-at-barrier')['packages'], 'post-transaction barrier ran before package mutation')
                return operation['transaction']
            require(operation['state'] not in phase42.TERMINAL, 'worker ended before reaching the interruption barrier')
            time.sleep(1)
        raise TimeoutError('real worker did not reach the post-transaction barrier')
    record = gate('real-applying-boundary', at_barrier)
    gate('concurrent-submit-preserves-applying-worker', lambda: guest_command(vm, 'concurrent-submit', identifier))
    gate('native-lock-excludes-competing-writer', lambda: guest_command(vm, 'compete', identifier))
    def kill():
        vm.command(shlex.join(['systemctl', 'kill', '--signal=SIGKILL', '--kill-whom=all', 'astraeus-apply@' + identifier + '.service']), label='sigkill-worker-service')
        operation = phase42.wait_operation(vm, identifier, args.timeout)
        require(operation['state'] == 'rollback_required' and operation['transaction']['failure']['interrupted'] is True,
                'killed mutation was not recorded as interrupted recovery-required')
        wait_worker_exit(vm, identifier, args.timeout, allow_failed=True)
        result = vm.command(shlex.join(['systemctl', 'show', '--all', '--property=Result,ExecMainCode,ExecMainStatus',
                                       'astraeus-apply@' + identifier + '.service']), check=False, label='killed-service-result')
        journal = vm.command(shlex.join(['journalctl', '--no-pager', '--output=json',
                                        '--unit=astraeus-apply@' + identifier + '.service']), label='killed-service-journal')
        entries = [json.loads(line) for line in journal['output'].splitlines() if line.strip()]
        require((result['code'] == 0 and 'ExecMainStatus=9' in result['output'])
                or any('code=killed, status=9/KILL' in entry.get('MESSAGE', '') for entry in entries),
                'service does not prove an actual SIGKILL')
        marker = guest_command(vm, 'barrier', label='killed-worker-identity')
        require(type(marker.get('worker_pid')) is int and marker['worker_pid'] > 1, 'killed worker identity unavailable')
        alive = vm.command('test -e ' + shlex.quote('/proc/' + str(marker['worker_pid'])), check=False, label='killed-worker-process-gone')
        require(alive['code'] == 1, 'original coordinator process survived the service SIGKILL')
        require(operation['transaction']['snapshot'] == record['snapshot'], 'interruption lost its recovery reference')
        return operation['transaction']
    record = gate('sigkill-durable-recovery', kill)
    def replay_refusal():
        before_replay = guest_command(vm, 'observe', label='before-worker-replay')
        result = vm.command(shlex.join(['distroctl', 'system', 'worker', identifier]), check=False, label='reject-worker-replay')
        require(result['code'] != 0 and 'replay refused' in result['output'], 'started request was replayed')
        after = guest_command(vm, 'observe', label='after-worker-replay')
        require(before_replay == after, 'replay refusal changed the system')
    gate('interrupted-request-is-not-replayed', replay_refusal)
    gate('interrupted-offline-rollback', lambda: offline_restore(vm, args, recovery, before, record))


def abandoned_scenario(vm, args, recovery, gate, before):
    phase42, p2 = host_modules()
    original = before['configuration']
    _, plan = phase42.json_command(vm, ['system', 'plan', '--stdin', '--json'], original, args.user, label='orphan-noop-review')
    require_noop(plan)
    p2.save(vm.share / 'submission-noop.json', {'schema_version': 1, 'config': original, 'expected_plan': plan['plan_id']})
    def start_failure():
        result = guest_command(vm, 'worker-start-failure', label='real-worker-start-failure')
        require(result['passed'] is True, 'worker-start failure fixture did not pass')
        state_equal(before, guest_command(vm, 'observe', label='after-worker-start-failure'))
        return result
    gate('systemd-start-failure-persists-failed-receipt', start_failure)
    p2.save(vm.share / 'orphan-submission.json', {'schema_version': 1, 'config': original, 'expected_plan': plan['plan_id']})
    injected = gate('abandoned-durable-boundary', lambda: guest_command(vm, 'abandoned'))
    identifier = injected['receipt']['operation_id']
    def observe_orphan():
        _, operation = phase42.json_command(vm, ['system', 'operation', identifier, '--json'], user=args.user, label='unprivileged-orphan-status')
        require(operation['state'] == 'failed' and 'will not be replayed' in operation.get('error', ''), 'orphan remains queued')
        state_equal(before, guest_command(vm, 'observe', label='after-orphan-inspection'))
    gate('orphan-reconciles-without-mutation', observe_orphan)
    def next_request():
        replacement = submitted(vm, original, plan, 'replacement-noop-submit')
        require(replacement != identifier, 'operation ID was reused')
        operation = phase42.wait_operation(vm, replacement, args.timeout)
        require(operation['state'] == 'succeeded' and operation['transaction']['plan']['packages']['changes'] == [],
                'orphan blocked the replacement no-op request')
        wait_worker_exit(vm, replacement, args.timeout)
        result = vm.command(shlex.join(['distroctl', 'system', 'worker', identifier]), check=False, label='reject-delayed-original-worker')
        require(result['code'] != 0 and 'not the current submitted request' in result['output'], 'delayed original request could claim a replacement')
        state_equal(before, guest_command(vm, 'observe', label='after-orphan-replacement'))
        return {'replacement_operation_id': replacement, 'old_operation_id': identifier}
    gate('replacement-request-and-old-claim-refusal', next_request)


def run(args):
    phase42, p2 = host_modules()
    require(sys.platform == 'linux' and os.geteuid() == 0 and Path('/dev/kvm').exists(), 'disposable Linux KVM host required')
    require(60 <= args.timeout <= 3600, 'timeout must be 60..3600 seconds')
    require(args.harness_commit is None or re.fullmatch('[0-9a-f]{40}', args.harness_commit), 'invalid harness commit')
    for name in ['base', 'output', 'ovmf_code', 'recovery_image', 'recovery_manifest']:
        setattr(args, name, p2.safe_path(getattr(args, name)))
    require(not args.output.exists(), 'evidence output must be new')
    require(not args.output.is_relative_to(args.base) and not args.base.is_relative_to(args.output), 'baseline and evidence must be separate')
    baseline = p2.verify_baseline(args.base)
    candidate_guard(args, baseline, digest(args.ovmf_code))
    recovery = json.loads(args.recovery_manifest.read_text())
    recovery_guard(args, baseline, recovery)
    config = configuration({'schema_version': 1, 'run_id': uuid.uuid4().hex, 'source_commit': args.source_commit,
            'image_sha256': args.image_sha256, 'distroctl_sha256': args.distroctl_sha256,
            'desktop_sha256': args.desktop_sha256, 'certificate_sha256': baseline['signer_sha256'],
            'encryption': args.encryption, 'user': args.user, 'package': args.package})
    require(re.fullmatch('[a-z0-9][a-z0-9@._+-]{0,127}', args.metadata_package), 'invalid metadata-only package')
    args.output.mkdir(mode=0o700)
    report = {'schema_version': 1, 'requested_run_passed': False, 'qualified': False,
              'physical_hardware_qualified': False, 'source_commit': args.source_commit,
              'image_sha256': args.image_sha256, 'started': p2.now(), 'scenarios': [],
              'recovery_manifest': recovery, 'harness_sha256': digest(__file__), 'harness_commit': args.harness_commit}
    report.update(firmware_provenance(baseline))
    p2.save(args.output / 'inputs.json', {'baseline': baseline, 'configuration': config,
            'recovery_manifest_sha256': digest(args.recovery_manifest),
            'harness_sha256': {Path(__file__).name: digest(__file__), 'phase42.py': digest(Path(phase42.__file__)),
                               'phase2.py': digest(Path(p2.__file__)), 'qmp.py': digest(p2.HERE / 'qmp.py'),
                               'phase42_trust.py': digest(p2.HERE / 'phase42_trust.py')}})
    try:
        for scenario in SCENARIOS if args.scenario == 'all' else [args.scenario]:
            args.active_scenario = scenario
            out = args.output / scenario
            out.mkdir(mode=0o700)
            p2.clone(args.base, out)
            share = out / 'share'
            share.mkdir(mode=0o700)
            stage_guest_scripts(share)
            args.run_id = uuid.uuid4().hex
            config['run_id'] = args.run_id
            p2.save(share / 'fault-config.json', config)
            vm = p2.VM(out, args.ovmf_code, share, args.timeout, secure_boot=True)
            def gate(name, function):
                row = {'scenario': scenario, 'id': name, 'status': 'RUNNING', 'started': p2.now(), 'evidence': [f'{scenario}/boot-{vm.number}/']}
                report['scenarios'].append(row)
                p2.save(args.output / 'matrix.json', report)
                try:
                    result = function()
                    row.update(status='PASS', detail='Actual assertions passed')
                    if result is not None:
                        p2.save(out / (name + '.json'), result)
                    return result
                except BaseException as error:
                    row.update(status='FAIL', detail=f'{type(error).__name__}: {error}')
                    raise
                finally:
                    row['finished'] = p2.now()
                    row['evidence'].append(f'{scenario}/boot-{vm.number}/')
                    p2.save(args.output / 'matrix.json', report)
            try:
                installed_boot(vm, args)
                gate('home-sentinel', lambda: guest_command(vm, 'home'))
                before = gate('candidate-identity-and-state', lambda: guest_command(vm, 'observe'))
                gate('baseline-health', lambda: p2.healthy(p2.observe(vm, scenario + '-baseline-health'), args.encryption))
                {'metadata': metadata_scenario, 'interruption': interruption_scenario,
                 'abandoned': abandoned_scenario, 'failed-hook': failure_scenario,
                 'signing-failure': failure_scenario, 'root-space': space_scenario,
                 'cache-space': space_scenario, 'esp-space': space_scenario}[scenario](vm, args, recovery, gate, before)
                vm.shutdown()
            finally:
                vm.stop()
                p2.verify_baseline(args.base)
        report['requested_run_passed'] = True
    except BaseException as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        preservation_error = None
        try:
            p2.verify_baseline(args.base)
            recovery_guard(args, baseline, recovery)
        except BaseException as error:
            report['requested_run_passed'] = False
            report['input_preservation_error'] = f'{type(error).__name__}: {error}'
            preservation_error = error
        report['finished'] = p2.now()
        p2.save(args.output / 'matrix.json', report)
        p2.save(args.output / 'evidence-sha256.json', {str(path.relative_to(args.output)): digest(path)
            for path in args.output.rglob('*') if path.is_file() and path.suffix not in ['.qcow2', '.fd']
            and path.name != 'evidence-sha256.json'})
        if preservation_error is not None:
            raise RuntimeError('validation inputs changed; this run cannot pass') from preservation_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    guest_parser = commands.add_parser('guest', help=argparse.SUPPRESS)
    guest_parser.add_argument('guest_action', choices=['home', 'observe', 'arm', 'barrier', 'compete', 'abandoned',
        'recover', 'metadata-negative', 'arm-failure', 'space-arm', 'space-reset',
        'submission-symlink', 'concurrent-submit', 'worker-start-failure'])
    guest_parser.add_argument('value', nargs='?')
    host = commands.add_parser('run')
    for name in ['base', 'output', 'ovmf-code', 'recovery-image', 'recovery-manifest']:
        host.add_argument('--' + name, type=Path, required=True)
    for name in ['source-commit', 'image-sha256', 'distroctl-sha256', 'desktop-sha256', 'user', 'package', 'metadata-package']:
        host.add_argument('--' + name, required=True)
    host.add_argument('--encryption', choices=['none', 'LUKS2'], required=True)
    host.add_argument('--scenario', choices=['all', *SCENARIOS], default='all')
    host.add_argument('--timeout', type=int, default=600)
    host.add_argument('--harness-commit', help='Validation-only commit, separate from the runtime candidate')
    args = parser.parse_args()
    if args.action == 'guest':
        guest(args.guest_action, args.value)
    else:
        run(args)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise InterruptedError(f'fault validation interrupted by signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    main()
