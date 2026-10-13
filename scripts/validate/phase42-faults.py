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

SHARE = Path('/mnt/astraeus-validation')
STATE = Path('/var/lib/astraeus/management/state.json')
SCENARIOS = ('metadata', 'interruption', 'abandoned')
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
        policy = json.loads(Path('/etc/astraeus/secure-boot/policy.json').read_text())
        require(policy.get('certificate_sha256') == config['certificate_sha256'], 'installed signing policy differs from the baseline')
        call('astraeus-secure-boot', 'check-enrollment')
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
            'home': {'sha256': digest(home), 'uid': home.stat().st_uid} if home.exists() else None,
            'package_lock_present': Path('/var/lib/pacman/db.lck').exists(),
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def barrier_paths(config):
    token = config['run_id']
    return (Path('/run/astraeus-phase42-' + token),
            Path('/etc/pacman.d/hooks/00-astraeus-phase42-' + token + '.hook'),
            Path('/var/log/astraeus/phase42-barrier-' + token + '.json'))


def guest_arm_barrier():
    config = guest_guard()
    runtime, hook, marker = barrier_paths(config)
    require(not runtime.exists() and not hook.exists() and not marker.exists(), 'fault fixture already exists')
    runtime.mkdir(mode=0o700)
    hook.parent.mkdir(mode=0o755, exist_ok=True)
    marker.parent.mkdir(mode=0o755, exist_ok=True)
    script = runtime / 'barrier.py'
    script.write_text('''import json,os,pathlib,time
pid=os.getppid()
chain=[]
while pid>1:
    path=pathlib.Path('/proc',str(pid))
    args=path.joinpath('cmdline').read_bytes().split(b'\\0')
    chain.append({'pid':pid,'argv':[v.decode() for v in args if v]})
    if len(args)>=4 and args[1:3]==[b'system',b'worker']:
        record={'worker_pid':pid,'operation_id':args[3].decode(),'ancestors':chain}
        break
    pid=int(next(line.split()[1] for line in path.joinpath('status').read_text().splitlines() if line.startswith('PPid:')))
else: raise RuntimeError('production worker ancestor missing')
path=pathlib.Path(''' + repr(str(marker)) + ''')
with path.open('x') as output:
    json.dump(record,output);output.flush();os.fsync(output.fileno())
os.sync()
time.sleep(3600)
''')
    script.chmod(0o600)
    hook.write_text('[Trigger]\nOperation = Install\nType = Package\nTarget = ' + config['package']
                    + '\n[Action]\nDescription = Disposable Phase 4.2 interruption barrier\nWhen = PostTransaction\n'
                    + 'Exec = /usr/bin/python3 ' + str(script) + '\n')
    hook.chmod(0o644)
    os.sync()
    return {'hook': str(hook), 'hook_sha256': digest(hook), 'marker': str(marker), 'when': 'PostTransaction'}


def guest_barrier():
    config = guest_guard()
    marker = barrier_paths(config)[2]
    return json.loads(marker.read_text()) if marker.exists() else None


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
    functions = {'home': guest_home, 'observe': guest_observe, 'arm': guest_arm_barrier,
                 'barrier': guest_barrier, 'abandoned': guest_inject_abandoned,
                 'metadata-negative': guest_metadata_negative}
    if action in functions:
        result = functions[action]()
    elif action == 'compete':
        result = guest_competing_writer(value)
    elif action == 'recover':
        result = guest_recover(value)
    else:
        raise ValueError('unsupported guest fault action')
    print(json.dumps(result, sort_keys=True))


def host_modules():
    import phase42
    return phase42, phase42.p2


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
    require(inner['snapshot_required'] is True and inner['boot']['regenerate_uki'] is True, 'metadata mutation lacks recovery/boot requirements')


def transaction_boundary(record, post=False):
    phases = [event['state'] for event in record['events']]
    require('snapshot_created' in phases and 'applying' in phases and phases.index('snapshot_created') < phases.index('applying'),
            'mutation lacks a prior durable snapshot')
    require(record.get('snapshot'), 'pre-transaction snapshot missing')
    if post:
        require(record.get('post_snapshot') and record.get('boot_regenerated') is True, 'post-generation boot evidence missing')


def unit_idle(text, allow_failed=False):
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition('=')
        require(separator and key in ['LoadState', 'ActiveState', 'Job'] and key not in values, 'invalid worker unit observation')
        values[key] = value
    require(set(values) == {'LoadState', 'ActiveState', 'Job'}, 'incomplete worker unit observation')
    return (values['LoadState'] in ['loaded', 'not-found']
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
        reply = vm.command(shlex.join(['distroctl', 'confirm-boot', str(record['id'])]), check=False, label='reject-same-boot')
        require(reply['code'] != 0 and 'different kernel boot' in reply['output'], 'metadata transaction accepted same-boot confirmation')
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
    gate('install-posttransaction-barrier', lambda: guest_command(vm, 'arm'))
    desired = copy.deepcopy(before['configuration'])
    desired['packages'] = sorted([*desired['packages'], args.package])
    def review_install():
        plan = reviewed(vm, desired, args.user, 'interrupted-install-plan')
        require(any(change.get('kind') == 'install' and change.get('name') == args.package for change in plan['plan']['packages']['changes']),
                'request does not install the nominated fault package')
        return plan
    plan = gate('interrupted-install-plan', review_install)
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
    require(not plan['blockers'] and plan['plan']['management']['before_digest'] == plan['plan']['management']['after_digest'],
            'abandoned boundary requires an unchanged baseline')
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
    p2.save(args.output / 'inputs.json', {'baseline': baseline, 'configuration': config,
            'recovery_manifest_sha256': digest(args.recovery_manifest),
            'harness_sha256': {Path(__file__).name: digest(__file__), 'phase42.py': digest(Path(phase42.__file__)),
                               'phase2.py': digest(Path(p2.__file__)), 'qmp.py': digest(p2.HERE / 'qmp.py')}})
    try:
        for scenario in SCENARIOS if args.scenario == 'all' else [args.scenario]:
            out = args.output / scenario
            out.mkdir(mode=0o700)
            p2.clone(args.base, out)
            share = out / 'share'
            share.mkdir(mode=0o700)
            shutil.copyfile(__file__, share / 'phase42-faults.py')
            shutil.copyfile(p2.HERE / 'phase2-guest.py', share / 'phase2-guest.py')
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
                 'abandoned': abandoned_scenario}[scenario](vm, args, recovery, gate, before)
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
    guest_parser.add_argument('guest_action', choices=['home', 'observe', 'arm', 'barrier', 'compete', 'abandoned', 'recover', 'metadata-negative'])
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
