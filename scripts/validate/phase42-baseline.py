#!/usr/bin/env python3
"""Fresh candidate payload installations in disposable KVM guests, never host disks.

Default mode exercises the payload/provisioner; --calamares-ui waits for a real UI install.
QMP login/unlock remains explicit. Secrets live only in a separate private directory.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import shutil
import subprocess
import sys
import time
import uuid
from phase42_trust import enforced, verify_maintained_uki

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SHARE = Path('/mnt/astraeus-validation')
TARGET = Path('/mnt/astraeus-phase42-target')
DISK_BYTES = 32 * 1024 ** 3
SUBVOLUMES = [('/', '/@'), ('/home', '/@home'), ('/.snapshots', '/@snapshots'),
              ('/var/log', '/@log'), ('/var/cache', '/@cache'), ('/var/lib/containers', '/@containers')]
LIVE_MARKER = 'DISTRO_BOOT_OK: uefi plasma wayland pipewire networkmanager distroctl'
EFIVARS = Path('/sys/firmware/efi/efivars')
EFI_GLOBAL_GUID = '8be4df61-93ca-11d2-aa0d-00e098032b8c'
MANAGEMENT_FIRMWARE = {'SecureBoot': True, 'SetupMode': False}


def installed_fstab(source, esp_uuid):
    text = ''.join(f'{source} {destination} btrfs defaults,noatime,compress=zstd:1,subvol={subvolume} 0 0\n'
                   for destination, subvolume in SUBVOLUMES)
    text += f'UUID={esp_uuid} /efi vfat defaults,umask=0077 0 2\n'
    return text + 'tmpfs /tmp tmpfs defaults,nosuid,nodev,mode=1777 0 0\n'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(*arguments, data=None, timeout=1800):
    """Never log stdin, which can contain a disposable password or LUKS key."""
    result = subprocess.run([str(value) for value in arguments], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    require(result.returncode == 0, f'{arguments[0]} failed ({result.returncode}): '
            + result.stderr.decode('utf-8', 'replace')[-4096:])
    return result.stdout.decode('utf-8', 'strict').strip()


def write(path, value, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8', newline='\n')
    path.chmod(mode)


def configuration(value):
    expected = {'schema_version', 'source_commit', 'image_sha256', 'distroctl_sha256',
                'desktop_sha256', 'serial', 'encryption', 'user', 'certificate_sha256'}
    require(isinstance(value, dict) and set(value) in [expected, expected | {'preexisting_package'}]
            and type(value['schema_version']) is int and value['schema_version'] == 1,
            'invalid fresh-install configuration schema')
    require(isinstance(value['source_commit'], str) and re.fullmatch('[0-9a-f]{40}', value['source_commit']),
            'full candidate source commit required')
    for name in ['image_sha256', 'distroctl_sha256', 'desktop_sha256', 'certificate_sha256']:
        require(isinstance(value[name], str) and re.fullmatch('[0-9a-f]{64}', value[name]),
                f'invalid candidate identity: {name}')
    require(isinstance(value['serial'], str) and re.fullmatch('AS42[0-9a-f]{16}', value['serial']),
            'invalid dedicated virtual disk serial')
    require(value['encryption'] in ['none', 'LUKS2'], 'unsupported encryption')
    require(isinstance(value['user'], str) and re.fullmatch('[a-z_][a-z0-9_-]{0,30}', value['user'])
            and value['user'] not in ['root', 'live'], 'ordinary installed user required')
    require(value.get('preexisting_package') in [None, 'tree'], 'unsupported pre-existing application fixture')
    return value


def blank_disk(inventory, signatures, serial):
    """All checks happen before the first partition write; never accepts a reused disk."""
    disks = inventory.get('blockdevices', [])
    require(len(disks) == 1, 'expected exactly one nominated virtual disk')
    disk = disks[0]
    require(disk.get('path') == '/dev/vda' and disk.get('type') == 'disk'
            and disk.get('serial') == serial and disk.get('size') == DISK_BYTES,
            'disk identity differs from the new 32 GiB validation disk')
    require(not disk.get('children') and isinstance(disk.get('mountpoints'), list)
            and not any(disk['mountpoints']),
            'validation disk already has partitions or mounts')
    require(signatures.get('signatures') == [], 'validation disk is not blank')


def guest_guard(live):
    require(sys.platform == 'linux' and os.geteuid() == 0, 'root Linux guest required')
    require(Path('/dev/virtio-ports/org.astraeus.validation').exists()
            and run('systemd-detect-virt') == 'kvm', 'dedicated disposable KVM channel required')
    require(Path('/sys/firmware/efi').is_dir(), 'UEFI guest required')
    require(Path('/run/archiso').exists() == live, 'unexpected live/installed environment')
    return configuration(json.loads((SHARE / 'installation.json').read_text()))


def secret(name):
    value = (SHARE / name).read_bytes()
    require(re.fullmatch(b'[a-zA-Z0-9]{32,64}', value) is not None, 'invalid private test credential')
    return value


def installation_firmware():
    """Observe this bootstrap's real firmware before permitting a partition write."""
    try:
        filesystem = run('findmnt', '-rn', '-M', EFIVARS, '-o', 'FSTYPE', timeout=10)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise RuntimeError('cannot inspect efivarfs mount for initial firmware observation') from error
    require(filesystem == 'efivarfs', 'initial firmware observation requires mounted efivarfs at ' + str(EFIVARS))
    observed = {'observed': True, 'source': 'efivarfs-before-partition-write'}
    for name in ('SecureBoot', 'SetupMode'):
        try:
            value = (EFIVARS / (name + '-' + EFI_GLOBAL_GUID)).read_bytes()
        except FileNotFoundError as error:
            raise RuntimeError('firmware variable ' + name + ' is absent; initial SetupMode observation '
                               'requires Secure Boot-capable firmware') from error
        except OSError as error:
            raise RuntimeError('cannot read initial firmware variable: ' + name) from error
        require(len(value) == 5 and value[4] in (0, 1), 'invalid firmware Boolean: ' + name)
        observed[name] = bool(value[4])
    require(observed['SecureBoot'] is False and observed['SetupMode'] is True,
            'initial bootstrap requires observed SetupMode; enforcing installation is not this adapter\'s scope')
    return observed


def preexisting_application(root, config):
    if config.get('preexisting_package') is None:
        return None
    require(config['preexisting_package'] == 'tree', 'unsupported pre-existing application fixture')
    for name in ['etc/astraeus/secure-boot/policy.json', 'var/lib/astraeus/secure-boot', 'etc/astraeus/boot-generations']:
        require(not (root / name).exists(), 'pre-existing app fixture must run before initial signing')
    paths = [root / name for name in ['etc/astraeus/system.toml', 'var/lib/astraeus/management/state.json',
                                     'var/lib/astraeus/management/system.lock']]
    original = {str(path.relative_to(root)): path.read_bytes() for path in paths}
    state = json.loads(paths[1].read_text())
    require('tree' not in state['packages'] and 'tree' not in state['protected'], 'fixture application is already tracked')
    def installed():
        return dict(line.split() for line in run('arch-chroot', root, 'pacman', '-Q').splitlines())
    before = installed()
    explicit_before = set(run('arch-chroot', root, 'pacman', '-Qqe').splitlines())
    require('tree' not in before, 'pre-existing fixture application must initially be absent')
    # Setup only, before enrollment: retain normal signature, dependency and hook checks.
    run('arch-chroot', root, 'pacman', '-S', '--noconfirm', '--needed', 'tree')
    after = installed()
    require(set(after) - set(before) == {'tree'} and all(after.get(k) == v for k, v in before.items()),
            'pre-existing fixture changed packages outside its single declared application')
    require(set(run('arch-chroot', root, 'pacman', '-Qqe').splitlines()) == explicit_before | {'tree'},
            'pre-existing fixture changed existing installation reasons')
    require(all(path.read_bytes() == original[str(path.relative_to(root))] for path in paths),
            'pre-existing app fixture changed management state or removal ownership')
    return {'name': 'tree', 'version': after['tree'], 'reason': 'explicit', 'unmanaged': True,
            'installed_before_initial_signing': True,
            'management_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in original.items()}}


def initial_signing(root, config):
    certificate = SHARE / 'db.crt'
    der = subprocess.check_output(['openssl', 'x509', '-in', str(certificate), '-outform', 'DER'])
    require(hashlib.sha256(der).hexdigest() == config['certificate_sha256'], 'signing certificate changed')
    policy = root / 'etc/astraeus/secure-boot/policy.json'
    state = root / 'var/lib/astraeus/secure-boot'
    require(not policy.exists() and not state.exists(), 'payload already has a signing identity')
    state.mkdir(mode=0o700, parents=True)
    keys = root / 'var/lib/astraeus/keys'
    keys.mkdir(mode=0o700)
    run('install', '-m600', SHARE / 'db.key', keys / 'db.key')
    policy.parent.mkdir(mode=0o755, parents=True)
    run('install', '-m644', certificate, policy.parent / 'db.crt')
    write(policy, json.dumps({'schema_version': 1, 'purpose': 'disposable-ovmf',
          'certificate': '/etc/astraeus/secure-boot/db.crt', 'private_key': '/var/lib/astraeus/keys/db.key',
          'certificate_sha256': config['certificate_sha256'], 'revoked_certificate_sha256': []}) + '\n')
    product = json.loads((root / 'usr/share/distro/installer-identity.json').read_text())['id']
    require(re.fullmatch('[a-z][a-z0-9-]*', product), 'invalid product boot identity')
    uki = f'/efi/EFI/Linux/{product}-linux.efi'
    receipts = {}
    for kind, source, destinations in [
            ('bootloader', '/usr/lib/systemd/boot/efi/systemd-bootx64.efi',
             ['/efi/EFI/systemd/systemd-bootx64.efi', '/efi/EFI/BOOT/BOOTX64.EFI']),
            ('uki', uki, [uki])]:
        run('arch-chroot', root, 'astraeus-secure-boot', 'stage', kind, source)
        receipt = json.loads(run('arch-chroot', root, 'astraeus-secure-boot', 'verify-candidate', kind))
        candidate = state / (kind + '.ready')
        for destination in destinations:
            target = root / destination.lstrip('/')
            run('install', '-m600', candidate / 'artifact.efi', target)
            require(sha256(target) == receipt['artifact_sha256'], 'published signed artifact differs')
        candidate.rename(state / (kind + '.consumed.initial'))
        receipts[kind] = receipt
    return receipts


def finish_install(config, firmware, method, storage_sha256=None):
    preexisting = preexisting_application(TARGET, config)
    receipts = initial_signing(TARGET, config)
    # Test instrumentation only, not an installed-smoke acceptance marker.
    write(TARGET / 'var/lib/astraeus-validation/guest.py', (SHARE / 'phase2-guest.py').read_text())
    write(TARGET / 'etc/systemd/system/astraeus-validation.service', '''[Unit]
Description=Disposable candidate validation command channel
ConditionPathExists=/dev/virtio-ports/org.astraeus.validation
After=local-fs.target
[Service]
ExecStart=/usr/bin/python3 /var/lib/astraeus-validation/guest.py serve
Restart=on-failure
RestartSec=1
[Install]
WantedBy=multi-user.target
''')
    run('arch-chroot', TARGET, 'systemctl', 'enable', 'astraeus-validation.service')
    exported = json.loads(run('arch-chroot', TARGET, 'distroctl', 'system', 'export', '--json'))
    require(exported.get('schema_version') == 1 and exported.get('configuration'), 'seeded configuration unreadable')
    result = {'schema_version': 1, 'method': method, 'calamares_ui': method == 'calamares-ui',
              'payload_sha256': sha256('/opt/distro/install-root.sfs'),
              'provision_sha256': sha256('/usr/share/distro/installer/provision.py'),
              'configuration': exported['configuration'], 'signing': receipts, 'disk_serial': config['serial'],
              'preexisting_application': preexisting, 'installation_firmware': firmware,
              'management_firmware_required': MANAGEMENT_FIRMWARE}
    if storage_sha256 is not None:
        result['calamares_storage_sha256'] = storage_sha256
        result['provisioner_replayed'] = False
    write(TARGET / 'var/log/installer/phase42-adapter.json', json.dumps(result, indent=2) + '\n')
    os.sync()
    print(json.dumps(result))


def installed_disk(inventory, config):
    """Only the just-installed, serial-pinned disposable disk can receive test keys."""
    disks = inventory.get('blockdevices', [])
    require(len(disks) == 1, 'expected one installed validation disk')
    disk = disks[0]
    require(disk.get('path') == '/dev/vda' and disk.get('type') == 'disk'
            and disk.get('serial') == config['serial'] and disk.get('size') == DISK_BYTES
            and disk.get('mountpoints') in ([], [None]), 'installed disk identity or mounts differ')
    parts = disk.get('children', [])
    require([part.get('path') for part in parts] == ['/dev/vda1', '/dev/vda2'], 'unexpected installed partitions')
    require(all(part.get('type') == 'part' and part.get('mountpoints') in ([], [None]) for part in parts),
            'installed partitions remain mounted')
    esp, root = parts
    require(esp.get('fstype') == 'vfat' and not esp.get('children'), 'unexpected ESP')
    expected = 'crypto_LUKS' if config['encryption'] == 'LUKS2' else 'btrfs'
    require(root.get('fstype') == expected, 'installed encryption differs')
    children = root.get('children', [])
    if not children:
        return None if expected == 'crypto_LUKS' else '/dev/vda2'
    require(expected == 'crypto_LUKS' and len(children) == 1, 'unexpected root mapping')
    child = children[0]
    require(child.get('type') == 'crypt' and child.get('fstype') == 'btrfs'
            and child.get('mountpoints') in ([], [None]) and not child.get('children')
            and re.fullmatch(r'/dev/mapper/[a-zA-Z0-9_-]+', child.get('path', '')),
            'unexpected or mounted encrypted root')
    return child['path']


def guest_adopt_ui():
    config = guest_guard(live=True)
    firmware = installation_firmware()
    require(subprocess.run(['pgrep', '-x', 'calamares'], capture_output=True).returncode == 1,
            'close Calamares after observing its successful finished page')
    inventory = json.loads(run('lsblk', '--tree', '--json', '--bytes', '--output',
                               'PATH,TYPE,SIZE,SERIAL,MOUNTPOINTS,FSTYPE', '/dev/vda'))
    device = installed_disk(inventory, config)
    require(not TARGET.exists(), 'adoption target already exists; do not retry on a modified disk')
    opened, mounted = False, False
    try:
        if config['encryption'] == 'LUKS2':
            run('cryptsetup', 'isLuks', '--type', 'luks2', '/dev/vda2')
            metadata = json.loads(run('cryptsetup', 'luksDump', '--dump-json-metadata', '/dev/vda2'))
            slots = metadata.get('keyslots', {})
            require(slots and all(slot.get('kdf', {}).get('type') == 'argon2id' for slot in slots.values()),
                    'installed LUKS2 keyslots must use Argon2id')
            if device is None:
                device = '/dev/mapper/astraeus-validation-root'
                require(not Path(device).exists(), 'validation mapper already exists')
                run('cryptsetup', 'open', '--key-file', '-', '/dev/vda2', 'astraeus-validation-root',
                    data=secret('luks-passphrase'))
                opened = True
        TARGET.mkdir(mode=0o700)
        run('mount', '-o', 'subvol=@', device, TARGET)
        mounted = True
        for destination, subvolume in SUBVOLUMES[1:]:
            run('mount', '-o', 'subvol=' + subvolume.lstrip('/'), device, TARGET / destination.lstrip('/'))
        run('mount', '-o', 'umask=0077', '/dev/vda1', TARGET / 'efi')
        for destination, subvolume in SUBVOLUMES:
            require(run('findmnt', '-rn', '-M', TARGET / destination.lstrip('/'), '-o', 'FSTYPE,FSROOT')
                    == 'btrfs ' + subvolume, 'installed subvolume differs')
        storage_path = TARGET / 'var/log/installer/storage.json'
        storage = json.loads(storage_path.read_text())
        root = storage['root']
        # Calamares records the containing LUKS device's UUID for encrypted roots.
        require(root['device'] == '/dev/vda2' and root['fs'] == 'btrfs' and root['mountPoint'] == '/'
                and root['uuid'] == run('blkid', '-s', 'UUID', '-o', 'value', '/dev/vda2'),
                'Calamares storage receipt differs from installed root')
        require(storage['subvolumes'] == [{'mountPoint': point, 'subvolume': sub} for point, sub in SUBVOLUMES],
                'Calamares subvolume receipt differs')
        if config['encryption'] == 'LUKS2':
            require(root['luksUuid'] == storage['luks']['uuid'] == run('cryptsetup', 'luksUUID', '/dev/vda2'),
                    'Calamares LUKS identity differs')
        else:
            require(storage['luks'] is None and root['luksUuid'] is None, 'unexpected encrypted storage receipt')
        for name, expected in [('distroctl', config['distroctl_sha256']),
                               ('astraeus-control-center', config['desktop_sha256'])]:
            require(sha256(TARGET / 'usr/bin' / name) == expected, 'Calamares installed binary differs: ' + name)
        require(run('arch-chroot', TARGET, 'id', '-u', config['user']) == '1000', 'Calamares user differs')
        # Do not replay provisioning or repair the UI installation before acceptance.
        finish_install(config, firmware, 'calamares-ui', sha256(storage_path))
    finally:
        if mounted:
            run('umount', '--recursive', TARGET)
        if opened:
            run('cryptsetup', 'close', 'astraeus-validation-root')


def ui_evidence(out, config):
    value = json.loads((out / 'calamares-ui.json').read_text())
    require(value.get('schema_version') == 1 and value.get('observed_finished') is True
            and all(value.get(name) == config[name] for name in ['source_commit', 'image_sha256', 'encryption', 'serial']),
            'UI observation is not bound to this fresh installation')
    files = value.get('sha256', {})
    require(set(files) == {'calamares-welcome.png', 'calamares-summary.png', 'calamares-finished.png', 'calamares.log'},
            'UI observation requires native pages and installer log')
    for name, digest in files.items():
        path = out / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size > 0 and sha256(path) == digest,
                'UI evidence missing or changed: ' + name)
        if name.endswith('.png'):
            with path.open('rb') as stream:
                require(stream.read(8) == b'\x89PNG\r\n\x1a\n', 'UI capture is not PNG')
    # These hashes bind operator-observed UI evidence; they do not independently prove UI interaction.
    return value


def guest_install():
    config = guest_guard(live=True)
    require(run('blockdev', '--getro', '/dev/vda') == '0', 'validation disk is read-only')
    inventory = json.loads(run('lsblk', '--tree', '--json', '--bytes', '--output', 'PATH,TYPE,SIZE,SERIAL,MOUNTPOINTS', '/dev/vda'))
    blank_disk(inventory, json.loads(run('wipefs', '--no-act', '--json', '/dev/vda')), config['serial'])
    firmware = installation_firmware()
    require(not TARGET.exists(), 'installation target already exists; retries require a new blank VM')
    payload = Path('/opt/distro/install-root.sfs')
    require(payload.is_file() and not payload.is_symlink(), 'candidate ISO payload missing')
    installer = Path('/usr/share/distro/installer')
    installed_config = json.loads((installer / 'config.json').read_text())
    mounts = [(entry['mountPoint'], entry['subvolume'])
              for entry in installed_config['modules']['mount']['btrfsSubvolumes']]
    require(mounts == SUBVOLUMES, 'candidate installer storage layout changed; update this adapter explicitly')
    password = secret('login-password')
    passphrase = secret('luks-passphrase') if config['encryption'] == 'LUKS2' else None
    run('sfdisk', '/dev/vda', data=b'label: gpt\nsize=1GiB,type=U,name="EFI"\ntype=L,name="Astraeus"\n')
    run('udevadm', 'settle')
    run('mkfs.fat', '-F32', '-n', 'EFI', '/dev/vda1')
    root_device = '/dev/vda2'
    if passphrase is not None:
        run('cryptsetup', 'luksFormat', '--type', 'luks2', '--pbkdf', 'argon2id', '--batch-mode',
            '--key-file', '-', root_device, data=passphrase)
        run('cryptsetup', 'open', '--key-file', '-', root_device, 'root', data=passphrase)
        root_device = '/dev/mapper/root'
    run('mkfs.btrfs', '-L', 'Astraeus', root_device)
    TARGET.mkdir(mode=0o700)
    mounted = False
    try:
        run('mount', root_device, TARGET)
        mounted = True
        for _, subvolume in SUBVOLUMES:
            run('btrfs', 'subvolume', 'create', TARGET / subvolume.lstrip('/'))
        run('umount', TARGET)
        mounted = False
        run('mount', '-o', 'defaults,noatime,compress=zstd:1,subvol=@', root_device, TARGET)
        mounted = True
        for destination, subvolume in SUBVOLUMES[1:]:
            mount = TARGET / destination.lstrip('/')
            mount.mkdir(parents=True, exist_ok=True)
            run('mount', '-o', 'defaults,noatime,compress=zstd:1,subvol=' + subvolume.lstrip('/'), root_device, mount)
        (TARGET / 'efi').mkdir()
        run('mount', '-o', 'umask=0077', '/dev/vda1', TARGET / 'efi')
        run('unsquashfs', '-f', '-d', TARGET, payload, timeout=1800)
        for name, expected in [('distroctl', config['distroctl_sha256']),
                               ('astraeus-control-center', config['desktop_sha256'])]:
            require(sha256(TARGET / 'usr/bin' / name) == expected, 'candidate installed binary differs: ' + name)
        root_uuid = run('blkid', '-s', 'UUID', '-o', 'value', root_device)
        partition = {'device': '/dev/vda2', 'fs': 'btrfs', 'mountPoint': '/', 'uuid': root_uuid}
        if passphrase is not None:
            partition.update(luksMapperName='root', luksUuid=run('cryptsetup', 'luksUUID', '/dev/vda2'))
        source = '/dev/mapper/root' if passphrase is not None else 'UUID=' + root_uuid
        write(TARGET / 'etc/fstab', installed_fstab(source, run('blkid', '-s', 'UUID', '-o', 'value', '/dev/vda1')))
        write(TARGET / 'etc/crypttab', 'root UUID=' + partition['luksUuid'] + ' none luks\n' if passphrase else '')
        write(TARGET / 'etc/locale.gen', 'en_US.UTF-8 UTF-8\n')
        write(TARGET / 'etc/locale.conf', 'LANG=en_US.UTF-8\n')
        write(TARGET / 'etc/vconsole.conf', 'KEYMAP=us\n')
        write(TARGET / 'etc/hostname', 'astraeus-validation\n')
        write(TARGET / 'etc/hosts', '127.0.0.1 localhost\n::1 localhost\n127.0.1.1 astraeus-validation\n')
        run('arch-chroot', TARGET, 'ln', '-sf', '/usr/share/zoneinfo/UTC', '/etc/localtime')
        run('arch-chroot', TARGET, 'locale-gen')
        run('arch-chroot', TARGET, 'systemd-machine-id-setup')
        run('arch-chroot', TARGET, 'useradd', '-m', '-U', '-G', 'wheel', '-s', '/bin/bash', config['user'])
        run('arch-chroot', TARGET, 'chmod', '700', '/home/' + config['user'])
        run('arch-chroot', TARGET, 'chpasswd', data=config['user'].encode() + b':' + password + b'\n')
        run('arch-chroot', TARGET, 'passwd', '--lock', 'root')
        write(TARGET / 'etc/sudoers.d/10-wheel', '%wheel ALL=(ALL:ALL) ALL\n', 0o440)
        run('arch-chroot', TARGET, 'visudo', '-cf', '/etc/sudoers.d/10-wheel')
        # Import the candidate ISO's production finalizer, not a copied host version.
        spec = importlib.util.spec_from_file_location('candidate_provision', installer / 'provision.py')
        provision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(provision)
        provision.provision(str(TARGET), [partition], keyboard=('us', ''), username=config['user'])
        finish_install(config, firmware, 'candidate-payload-and-production-provision')
    finally:
        if mounted:
            run('umount', '--recursive', TARGET)
        if passphrase is not None:
            run('cryptsetup', 'close', 'root')


def desktop_environment(user, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(['pgrep', '-u', user, '-x', 'plasmashell'], capture_output=True, text=True)
        for pid in result.stdout.split():
            try:
                env = dict(item.decode().split('=', 1) for item in Path('/proc', pid, 'environ').read_bytes().split(b'\0') if b'=' in item)
                if env.get('USER') == user and env.get('XDG_SESSION_TYPE') == 'wayland' and 'KDE' in env.get('XDG_CURRENT_DESKTOP', ''):
                    session = env.get('XDG_SESSION_ID', '')
                    require(re.fullmatch('[a-zA-Z0-9]+', session), 'desktop lacks an observed logind session')
                    details = dict(line.split('=', 1) for line in run('loginctl', 'show-session', session).splitlines() if '=' in line)
                    require(details.get('Name') == user and details.get('Service') == 'sddm'
                            and details.get('Type') == 'wayland' and details.get('Class') == 'user'
                            and details.get('Remote') == 'no' and details.get('State') == 'active',
                            'desktop did not come from an active local SDDM user login')
                    return {name: env[name] for name in ['USER', 'HOME', 'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP',
                                                       'XDG_RUNTIME_DIR', 'XDG_SESSION_ID', 'DBUS_SESSION_BUS_ADDRESS']}
            except (FileNotFoundError, KeyError):
                pass
        time.sleep(1)
    raise TimeoutError('real SDDM/Plasma login was not observed through the private console')


def guest_desktop(initial):
    config = guest_guard(live=False)
    env = desktop_environment(config['user'])
    prefix = ['runuser', '-u', config['user'], '--', 'env', *[key + '=' + value for key, value in env.items()]]
    # `boot enable` records opt-in; the first later transaction creates the first
    # managed generation. Both baseline cold boots still use the installed UKI.
    # The read-only share stays root-private because it also served setup secrets.
    # Run the original script as the desktop user without granting share access.
    output = run(*prefix, 'bash', '-s', '--', config['encryption'],
                 data=(SHARE / 'installed-smoke.sh').read_bytes())
    marker = f'DISTRO_INSTALL_OK: uefi uki {config["encryption"]} btrfs sddm plasma wayland network audio status'
    require(marker in output.splitlines(), 'original installed smoke did not pass')
    log = 'installed-acceptance.log' if initial else 'installed-second-acceptance.log'
    write(Path('/var/lib/astraeus-validation') / log, output + '\n')
    status = json.loads(run(*prefix, 'distroctl', 'system', 'status', '--json'))
    require(status.get('configuration_available') is True and not status.get('drift')
            and not status.get('recovery_required') and not status.get('live'), 'installed management state is not healthy')
    for name, expected in [('distroctl', config['distroctl_sha256']), ('astraeus-control-center', config['desktop_sha256'])]:
        require(sha256(Path('/usr/bin') / name) == expected, 'booted candidate binary changed: ' + name)
    print(output)
    print(json.dumps({'schema_version': 1, 'desktop': 'actual-sddm-plasma-wayland-session',
                      'original_installed_smoke': True, 'initial_boot': initial, 'management': status}))


def installed_boot_trust(vm, pin):
    return verify_maintained_uki(lambda *args: vm.command(shlex.join(args), label='installed-boot-trust')['output'],
                                 pin, require_ready=True)


def make_owner(private, public):
    public.mkdir()
    pins = {}
    for name in ['PK', 'KEK', 'db']:
        run('openssl', 'req', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-days', '14',
            '-subj', '/CN=Astraeus disposable Phase42 ' + name, '-keyout', private / (name + '.key'),
            '-out', public / (name + '.crt'))
        (private / (name + '.key')).chmod(0o600)
        run('openssl', 'x509', '-in', public / (name + '.crt'), '-outform', 'DER', '-out', public / (name + '.cer'))
        pins[name] = sha256(public / (name + '.cer'))
    return pins


def host_run(args):
    import phase2 as p2
    require(sys.platform == 'linux' and os.geteuid() == 0 and Path('/dev/kvm').exists(),
            'run only as root on the disposable Linux KVM validator')
    for tool in ['qemu-img', 'qemu-system-x86_64', 'openssl', 'virt-fw-vars']:
        require(shutil.which(tool), 'missing validator tool: ' + tool)
    out, private = p2.safe_path(args.output), p2.safe_path(args.private_directory)
    require(not private.is_relative_to(REPO) and not private.is_relative_to(out) and not out.is_relative_to(private),
            'private test keys/credentials must stay outside source and public evidence')
    iso, code, setup_code, variables = [p2.safe_path(path).resolve(strict=True)
                                      for path in [args.iso, args.ovmf_code, args.setup_ovmf_code, args.ovmf_vars]]
    config = configuration(dict(schema_version=1, source_commit=args.source_commit, image_sha256=args.image_sha256,
                                distroctl_sha256=args.distroctl_sha256, desktop_sha256=args.desktop_sha256,
                                serial='AS42' + secrets.token_hex(8), encryption=args.encryption, user=args.user,
                                certificate_sha256='0' * 64,
                                **({'preexisting_package': args.preexisting_package} if getattr(args, 'preexisting_package', None) else {})))
    require(sha256(iso) == args.image_sha256, 'candidate ISO differs from the reviewed build identity')
    require(sha256(setup_code) == sha256(code),
            'initial SetupMode boot requires the same Secure Boot-capable OVMF code as enforcing boots')
    require(60 <= args.timeout <= 3600, 'timeout must be 60..3600 seconds')
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    private.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(private, 0o700)
    result = dict(schema_version=1, accepted=False, calamares_ui=False, started=p2.now(),
                  installation_firmware=None, management_firmware_required=MANAGEMENT_FIRMWARE)
    vm = None
    share = private / 'share'
    share.mkdir(mode=0o700)
    try:
        pins = make_owner(private, out / 'public-owner')
        config['certificate_sha256'] = pins['db']
        for name in ['login-password', 'luks-passphrase']:
            credential = secrets.token_hex(24)
            write(private / name, credential, 0o600)
            write(share / name, credential, 0o600)
        for name in ['phase2-guest.py', 'phase42-baseline.py', 'phase42_trust.py']:
            shutil.copyfile(HERE / name, share / name)
        shutil.copyfile(REPO / 'tests/boot/installed-smoke.sh', share / 'installed-smoke.sh')
        shutil.copyfile(private / 'db.key', share / 'db.key')
        (share / 'db.key').chmod(0o600)
        shutil.copyfile(out / 'public-owner/db.crt', share / 'db.crt')
        p2.save(share / 'installation.json', config)
        inputs = dict(source_commits=[args.source_commit], iso=dict(path=str(iso), sha256=args.image_sha256),
                      ovmf_code=dict(path=str(code), sha256=sha256(code)),
                      setup_ovmf_code=dict(path=str(setup_code), sha256=sha256(setup_code)),
                      pristine_ovmf_vars=dict(path=str(variables), sha256=sha256(variables)))
        p2.save(out / 'inputs.json', inputs)
        p2.save(out / 'installation.json', config)
        p2.host(['qemu-img', 'create', '-f', 'qcow2', out / 'disk.qcow2', '32G'])
        shutil.copyfile(variables, out / 'vars.fd')
        # SMM and protected pflash expose authenticated variables; pristine VARS still boot in SetupMode.
        vm = p2.VM(out, setup_code, share, args.timeout, secure_boot=True)
        original = p2.install.qemu_command

        def command(*positional, **keywords):
            value = original(*positional, **keywords)
            device = next(item for item in value if item.startswith('virtio-blk-pci,drive=osdisk,'))
            value[value.index(device)] = device + ',serial=' + config['serial']
            value[value.index('-m') + 1] = '8192'
            return value

        p2.install.qemu_command = command
        try:
            vm.start(iso)
        finally:
            p2.install.qemu_command = original
        deadline = time.monotonic() + args.timeout
        while True:
            vm.alive()
            serial = vm.session / 'serial.log'
            if serial.exists() and LIVE_MARKER in serial.read_text(errors='replace'):
                break
            require(time.monotonic() < deadline, 'candidate live desktop did not pass its packaged smoke')
            time.sleep(1)
        p2.save(out / 'attention.json', dict(stage='live-command-channel', qmp=str(vm.monitor),
                command='sudo mkdir -p /mnt/astraeus-validation; sudo mount -t 9p -o trans=virtio,ro acceptance /mnt/astraeus-validation; sudo systemd-run --unit=astraeus-live-validation python3 /mnt/astraeus-validation/phase2-guest.py serve'))
        print('Start the test command channel from the actual live desktop; see attention.json and private QMP.', flush=True)
        vm.ready()
        observed = vm.command('python3 /mnt/astraeus-validation/phase42-baseline.py guest-firmware',
                              label='installation-firmware-before-writes')
        result['installation_firmware'] = json.loads(observed['output'])
        p2.save(out / 'result.json', result)
        method = 'candidate-payload-and-production-provision'
        action = 'guest-install'
        if getattr(args, 'calamares_ui', False):
            vm.command('python3 /mnt/astraeus-validation/phase42-baseline.py guest-ui-ready', label='blank-ui-disk')
            p2.save(out / 'attention.json', dict(stage='calamares-ui', qmp=str(vm.monitor),
                    credentials=str(private), user=args.user, encryption=args.encryption,
                    instruction='Complete Calamares through its native UI, capture welcome/summary/finished and log, '
                                'close without rebooting, then write calamares-ui.json with observation and SHA256s.'))
            deadline = time.monotonic() + args.timeout
            while not (out / 'calamares-ui.json').exists():
                vm.alive()
                require(time.monotonic() < deadline, 'Calamares UI observation timed out')
                time.sleep(1)
            result['calamares_observation'] = ui_evidence(out, config)
            method, action = 'calamares-ui', 'guest-adopt-ui'
        reply = vm.command('python3 /mnt/astraeus-validation/phase42-baseline.py ' + action,
                           timeout=3600, label='fresh-installation')
        installed = json.loads(reply['output'].splitlines()[-1])
        require(installed.get('method') == method and installed.get('calamares_ui') == (method == 'calamares-ui')
                and installed.get('disk_serial') == config['serial'], 'fresh installation receipt differs')
        require(installed.get('installation_firmware') == result['installation_firmware']
                and installed.get('management_firmware_required') == MANAGEMENT_FIRMWARE,
                'installation firmware observations differ')
        p2.save(out / 'fresh-installation.json', installed)
        result['calamares_ui'] = installed['calamares_ui']
        vm.shutdown()
        # Remove guest-accessible copies. Originals remain outside the evidence tree.
        for name in ['db.key', 'login-password', 'luks-passphrase']:
            (share / name).unlink()
        owner = str(uuid.uuid4())
        run('virt-fw-vars', '--input', variables, '--output', out / 'vars.enrolled.fd',
            '--set-pk', owner, out / 'public-owner/PK.crt', '--add-kek', owner, out / 'public-owner/KEK.crt',
            '--add-db', owner, out / 'public-owner/db.crt', '--secure-boot')
        shutil.copyfile(out / 'vars.enrolled.fd', out / 'vars.fd')
        vm.code, vm.secure_boot = code, True
        boots = []
        for number in [1, 2]:
            vm.start()
            p2.save(out / 'attention.json', dict(stage='unlock-and-sddm-login', boot=number,
                    qmp=str(vm.monitor), credentials=str(private), user=args.user, encryption=args.encryption))
            print(f'Enforced boot {number}: unlock if needed and log in through private QMP; see attention.json.', flush=True)
            vm.ready()
            require(vm.boot_id not in boots, 'cold boots reused one boot identity')
            boots.append(vm.boot_id)
            p2.save(out / f'maintained-uki-trust-{number}.json', installed_boot_trust(vm, pins['db']))
            vm.command('systemctl start NetworkManager-wait-online.service', timeout=120, label='network-online')
            p2.healthy(p2.observe(vm, 'fresh-installed-' + str(number), product=False), args.encryption)
            vm.command('python3 /mnt/astraeus-validation/phase42-baseline.py guest-desktop'
                       + (' --initial' if number == 1 else ''), timeout=900, label='actual-desktop-' + str(number))
            if number == 1:
                vm.command('distroctl boot enable', timeout=300, label='enable-managed-generations')
            vm.shutdown()
        manifest = dict(schema_version=1, kind='phase42-fresh-candidate-payload', accepted=True,
                        method=installed['method'], calamares_ui=installed['calamares_ui'], encryption=args.encryption,
                        source_commit=args.source_commit, inputs=inputs, signer_sha256=pins['db'],
                        public_fingerprints=pins, boot_ids=boots, created=p2.now(),
                        preexisting_application=installed.get('preexisting_application'),
                        installation_firmware=installed['installation_firmware'],
                        management_firmware_required=MANAGEMENT_FIRMWARE,
                        installed_binaries={'distroctl': args.distroctl_sha256, 'astraeus-control-center': args.desktop_sha256},
                        sha256={name: sha256(out / name) for name in ['disk.qcow2', 'vars.fd']})
        p2.save(out / 'baseline.json', manifest)
        for name in ['disk.qcow2', 'vars.fd']:
            (out / name).chmod(0o444)
        result.update(accepted=True, boot_ids=boots)
        p2.save(out / 'attention.json', dict(stage='complete'))
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if vm:
            vm.stop()
        for name in ['db.key', 'login-password', 'luks-passphrase']:
            (share / name).unlink(missing_ok=True)
        result['finished'] = p2.now()
        p2.save(out / 'result.json', result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('guest-install')
    commands.add_parser('guest-ui-ready')
    commands.add_parser('guest-adopt-ui')
    commands.add_parser('guest-firmware')
    commands.add_parser('guest-desktop').add_argument('--initial', action='store_true')
    host = commands.add_parser('run')
    for name in ['output', 'private-directory', 'iso', 'ovmf-code', 'ovmf-vars']:
        host.add_argument('--' + name, required=True, type=Path)
    host.add_argument('--setup-ovmf-code', required=True, type=Path,
                      help='must match --ovmf-code; pristine VARS provide the initial SetupMode boot')
    for name in ['source-commit', 'image-sha256', 'distroctl-sha256', 'desktop-sha256']:
        host.add_argument('--' + name, required=True)
    host.add_argument('--encryption', choices=['none', 'LUKS2'], required=True)
    host.add_argument('--calamares-ui', action='store_true', help='wait for observed native UI installation before test signing')
    host.add_argument('--preexisting-package', choices=['tree'], help='disposable GUI fixture installed before initial signing, outside management ownership')
    host.add_argument('--user', default='tester')
    host.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    if args.action == 'guest-install':
        guest_install()
    elif args.action == 'guest-ui-ready':
        config = guest_guard(live=True)
        inventory = json.loads(run('lsblk', '--tree', '--json', '--bytes', '--output', 'PATH,TYPE,SIZE,SERIAL,MOUNTPOINTS', '/dev/vda'))
        blank_disk(inventory, json.loads(run('wipefs', '--no-act', '--json', '/dev/vda')), config['serial'])
        print(json.dumps(installation_firmware()))
    elif args.action == 'guest-adopt-ui':
        guest_adopt_ui()
    elif args.action == 'guest-firmware':
        guest_guard(live=True)
        print(json.dumps(installation_firmware()))
    elif args.action == 'guest-desktop':
        guest_desktop(args.initial)
    else:
        def interrupted(_signal, _frame):
            raise InterruptedError('fresh baseline validation interrupted')
        signal.signal(signal.SIGTERM, interrupted)
        host_run(args)


if __name__ == '__main__':
    main()
