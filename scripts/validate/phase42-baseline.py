#!/usr/bin/env python3
"""Fresh candidate payload installations in disposable KVM guests, never host disks.

This exercises the shipped payload and production provision.py, not Calamares UI.
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
import signal
import shutil
import subprocess
import sys
import time
import uuid

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
    require(isinstance(value, dict) and set(value) == expected
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
    observed = {'observed': True, 'source': 'efivarfs-before-partition-write'}
    for name in ('SecureBoot', 'SetupMode'):
        value = (EFIVARS / (name + '-' + EFI_GLOBAL_GUID)).read_bytes()
        require(len(value) == 5 and value[4] in (0, 1), 'invalid firmware Boolean: ' + name)
        observed[name] = bool(value[4])
    require(observed['SecureBoot'] is False and observed['SetupMode'] is True,
            'initial bootstrap requires observed SetupMode; enforcing installation is not this adapter\'s scope')
    return observed


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


def guest_install():
    config = guest_guard(live=True)
    require(run('blockdev', '--getro', '/dev/vda') == '0', 'validation disk is read-only')
    inventory = json.loads(run('lsblk', '--json', '--bytes', '--output', 'PATH,TYPE,SIZE,SERIAL,MOUNTPOINTS', '/dev/vda'))
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
        fstab = ''.join(f'{source} {destination} btrfs defaults,noatime,compress=zstd:1,subvol={subvolume.lstrip("/")} 0 0\n'
                        for destination, subvolume in SUBVOLUMES)
        fstab += 'UUID=' + run('blkid', '-s', 'UUID', '-o', 'value', '/dev/vda1') + ' /efi vfat defaults,umask=0077 0 2\n'
        fstab += 'tmpfs /tmp tmpfs defaults,nosuid,nodev,mode=1777 0 0\n'
        write(TARGET / 'etc/fstab', fstab)
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
        receipts = initial_signing(TARGET, config)
        # This is test instrumentation only, not an installed-smoke acceptance marker.
        agent = TARGET / 'var/lib/astraeus-validation/guest.py'
        write(agent, (SHARE / 'phase2-guest.py').read_text())
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
        result = {'schema_version': 1, 'method': 'candidate-payload-and-production-provision', 'calamares_ui': False,
                  'payload_sha256': sha256(payload), 'provision_sha256': sha256(installer / 'provision.py'),
                  'configuration': exported['configuration'], 'signing': receipts, 'disk_serial': config['serial'],
                  'installation_firmware': firmware, 'management_firmware_required': MANAGEMENT_FIRMWARE}
        write(TARGET / 'var/log/installer/phase42-adapter.json', json.dumps(result, indent=2) + '\n')
        os.sync()
        print(json.dumps(result))
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
    output = run(*prefix, 'bash', SHARE / 'installed-smoke.sh', config['encryption'])
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


def enforced(status, pin):
    firmware = status.get('firmware', {})
    require(status.get('certificate_sha256') == pin and firmware.get('SecureBoot') is True
            and firmware.get('SetupMode') is False and firmware.get('AuditMode') is not True,
            'candidate did not boot with the intended owner and enforcing Secure Boot')
    require(firmware.get('db', {}).get('contains_signer_certificate') is True
            and firmware.get('dbx', {}).get('contains_signer_certificate') is False,
            'candidate signer enrollment or revocation evidence is incomplete')


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
                                certificate_sha256='0' * 64))
    require(sha256(iso) == args.image_sha256, 'candidate ISO differs from the reviewed build identity')
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
        for name in ['phase2-guest.py', 'phase42-baseline.py']:
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
        vm = p2.VM(out, setup_code, share, args.timeout)
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
        reply = vm.command('python3 /mnt/astraeus-validation/phase42-baseline.py guest-install',
                           timeout=3600, label='fresh-payload-install')
        installed = json.loads(reply['output'].splitlines()[-1])
        require(installed.get('method') == 'candidate-payload-and-production-provision'
                and installed.get('disk_serial') == config['serial'], 'fresh installation receipt differs')
        require(installed.get('installation_firmware') == result['installation_firmware']
                and installed.get('management_firmware_required') == MANAGEMENT_FIRMWARE,
                'installation firmware observations differ')
        p2.save(out / 'fresh-installation.json', installed)
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
            security = json.loads(vm.command('astraeus-secure-boot status --json', label='enforcing-security')['output'])
            enforced(security, pins['db'])
            vm.command('astraeus-secure-boot check-enrollment', label='owner-enrollment')
            vm.command('systemctl start NetworkManager-wait-online.service', timeout=120, label='network-online')
            p2.healthy(p2.observe(vm, 'fresh-installed-' + str(number), product=False), args.encryption)
            vm.command('python3 /mnt/astraeus-validation/phase42-baseline.py guest-desktop'
                       + (' --initial' if number == 1 else ''), timeout=900, label='actual-desktop-' + str(number))
            vm.command('astraeus-boot-artifact ready /efi', label='signed-provider-ready')
            if number == 1:
                vm.command('distroctl boot enable', timeout=300, label='enable-managed-generations')
            vm.shutdown()
        manifest = dict(schema_version=1, kind='phase42-fresh-candidate-payload', accepted=True,
                        method=installed['method'], calamares_ui=False, encryption=args.encryption,
                        source_commit=args.source_commit, inputs=inputs, signer_sha256=pins['db'],
                        public_fingerprints=pins, boot_ids=boots, created=p2.now(),
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
    commands.add_parser('guest-firmware')
    commands.add_parser('guest-desktop').add_argument('--initial', action='store_true')
    host = commands.add_parser('run')
    for name in ['output', 'private-directory', 'iso', 'ovmf-code', 'setup-ovmf-code', 'ovmf-vars']:
        host.add_argument('--' + name, required=True, type=Path)
    for name in ['source-commit', 'image-sha256', 'distroctl-sha256', 'desktop-sha256']:
        host.add_argument('--' + name, required=True)
    host.add_argument('--encryption', choices=['none', 'LUKS2'], required=True)
    host.add_argument('--user', default='tester')
    host.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    if args.action == 'guest-install':
        guest_install()
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
