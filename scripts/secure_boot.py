#!/usr/bin/python3 -I
"""Owner signing and generation artifact trust. Never enrolls firmware keys."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import subprocess
import sys
import uuid

POLICY = Path('/etc/astraeus/secure-boot/policy.json')
STATE = Path('/var/lib/astraeus/secure-boot')
UNSIGNED = STATE / 'unsigned.efi'
EFIVARS = Path('/sys/firmware/efi/efivars')
GLOBAL_GUID = '8be4df61-93ca-11d2-aa0d-00e098032b8c'
DB_GUID = 'd719b2cb-3d3a-4596-a3bc-dad00e67656f'
X509_GUID = uuid.UUID('a5c059a1-94e4-4aa7-87b5-ab155c2bf072').bytes_le
SHA256_GUID = uuid.UUID('c1c41626-504c-4092-aca9-41f936934328').bytes_le
FINGERPRINT = re.compile(r'[0-9a-f]{64}')
KINDS = ('uki', 'bootloader')
ESP = Path('/efi')
STORE = Path('/.snapshots/astraeus')
GENERATIONS = Path('/etc/astraeus/boot-generations')
UPDATE_LOCK = Path('/run/astraeus-update.lock')
MAINTENANCE = Path('EFI/Astraeus/maintenance.efi')
LOADER = Path('/usr/lib/systemd/boot/efi/systemd-bootx64.efi')
DISTROCTL = Path('/usr/bin/distroctl')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def absolute_path(value):
    if not isinstance(value, str) or not value.startswith('/') or value.startswith('//') or '\\' in value:
        raise ValueError('expected an absolute Linux path')
    path = PurePosixPath(value)
    if str(path) != value or '..' in path.parts or len(path.parts) < 2 or '\x00' in value:
        raise ValueError('path must be normalized')
    return Path(value)


def parse_policy(value):
    fields = {'schema_version', 'purpose', 'certificate', 'private_key',
              'certificate_sha256', 'revoked_certificate_sha256'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('unsupported signing policy fields')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('unsupported signing policy version')
    if value['purpose'] not in ('development', 'disposable-ovmf', 'machine-owner'):
        raise ValueError('unsupported signing identity purpose')
    pin, revoked = value['certificate_sha256'], value['revoked_certificate_sha256']
    if not isinstance(pin, str) or not FINGERPRINT.fullmatch(pin):
        raise ValueError('certificate fingerprint must be lowercase SHA-256 of DER')
    if (not isinstance(revoked, list) or any(not isinstance(v, str) or not FINGERPRINT.fullmatch(v)
                                           for v in revoked) or len(set(revoked)) != len(revoked)):
        raise ValueError('invalid local certificate revocation list')
    cert, key = absolute_path(value['certificate']), absolute_path(value['private_key'])
    if cert == key or key.parts[1] in ('efi', 'boot', 'usr'):
        raise ValueError('private key must be separate and outside boot/build artifacts')
    return value


def trusted(path, private=False, directory=False):
    """Privileged callers accept only root-owned, non-link paths and ancestry."""
    path = Path(path)
    if os.name != 'posix' or not path.is_absolute() or '..' in path.parts:
        raise ValueError('trusted paths require absolute POSIX paths')
    for entry in reversed((path, *path.parents)):
        info = entry.lstat()
        leaf = entry == path
        expected = stat.S_ISDIR if not leaf or directory else stat.S_ISREG
        if (not expected(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022
                or (leaf and not directory and info.st_nlink != 1)):
            raise ValueError('unsafe ownership, permissions, links or file type')
        if leaf and private and info.st_mode & 0o077:
            raise ValueError('private material requires owner-only permissions')
    return path


def command(program, *args):
    # Tool diagnostics may contain input data. Expose only the tool and exit code.
    try:
        result = subprocess.run(['/usr/bin/' + program, *map(str, args)],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=180,
                                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'LANG': 'C'})
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f'{program}: unavailable or timed out') from error
    if result.returncode:
        raise RuntimeError(f'{program}: failed (exit {result.returncode})')
    return result.stdout


def load_policy():
    trusted(POLICY)
    return parse_policy(json.loads(POLICY.read_bytes(), object_pairs_hook=unique_object))


def identity(policy, signing=False):
    cert = trusted(policy['certificate'])
    der = command('openssl', 'x509', '-in', cert, '-outform', 'DER')
    if hashlib.sha256(der).hexdigest() != policy['certificate_sha256']:
        raise ValueError('certificate does not match pinned signing identity')
    if policy['certificate_sha256'] in policy['revoked_certificate_sha256']:
        raise ValueError('signing identity is locally revoked')
    command('openssl', 'verify', '-check_ss_sig', '-no-CApath', '-no-CAstore', '-CAfile', cert, cert)
    if signing:
        key = trusted(policy['private_key'], private=True)
        trusted(key.parent, private=True, directory=True)
        public = command('openssl', 'pkey', '-in', key, '-passin', 'pass:', '-pubout')
        if public != command('openssl', 'x509', '-in', cert, '-pubkey', '-noout'):
            raise ValueError('private key does not match signing certificate')
    return der


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect_image(path, kind):
    if kind not in KINDS:
        raise ValueError('unsupported artifact kind')
    trusted(path)
    import pefile  # Already required by systemd-ukify.
    try:
        with pefile.PE(str(path), fast_load=True) as pe:
            if (pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20b
                    or pe.OPTIONAL_HEADER.Subsystem != 10):
                raise ValueError('expected an x86-64 PE32+ EFI application')
    except pefile.PEFormatError as error:
        raise ValueError('invalid PE image') from error
    sections = json.loads(command('ukify', '--config=/dev/null', '--json=short', '--all', 'inspect', path),
                          object_pairs_hook=unique_object)
    if not isinstance(sections, dict) or not sections:
        raise ValueError('image has no inspectable PE sections')
    if any(not isinstance(v, dict) or type(v.get('size')) is not int or v['size'] < 0
           or not FINGERPRINT.fullmatch(str(v.get('sha256', ''))) for v in sections.values()):
        raise ValueError('malformed, duplicate or multi-profile PE sections are unsupported')
    if kind == 'uki':
        required = {'.linux', '.initrd', '.cmdline', '.uname', '.osrel'}
        if not required <= sections.keys() or any(sections[name]['size'] == 0 for name in required):
            raise ValueError('missing required UKI sections')
        if not sections['.cmdline'].get('text', '').strip() or not sections['.uname'].get('text', '').strip():
            raise ValueError('empty UKI command line or kernel release')
    elif '.linux' in sections or '.text' not in sections or sections['.text']['size'] == 0:
        raise ValueError('expected a bootloader, not a UKI')
    return sections


def verify(path, kind, policy):
    identity(policy)
    sections = inspect_image(path, kind)
    command('sbverify', '--cert', policy['certificate'], path)
    return sections


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def copy_new(source, target):
    import shutil
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as dst:
        with Path(source).open('rb') as src:
            shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())


def require_root():
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ValueError('this operation requires Linux root')


@contextmanager
def signing_lock():
    import fcntl
    require_root()
    trusted(STATE, private=True, directory=True)
    path = STATE / 'signing.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'rb') as stream:
        trusted(path, private=True)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('another signer holds the lock') from error
        yield


def stage(kind, source, policy):
    """Publish only a complete candidate. Keep failed staging for diagnosis."""
    if kind not in KINDS:
        raise ValueError('unsupported artifact kind')
    with signing_lock():
        identity(policy, signing=True)
        source = trusted(source)
        candidate, pending = STATE / (kind + '.ready'), STATE / (kind + '.pending')
        if os.path.lexists(candidate) or os.path.lexists(pending):
            raise ValueError('candidate or incomplete staging exists; consumer/recovery must resolve it')
        pending.mkdir(mode=0o700)
        sync_directory(STATE)
        original = pending / 'input.efi'
        copy_new(source, original)
        sections = inspect_image(original, kind)
        signed = pending / 'artifact.efi'
        command('sbsign', '--key', policy['private_key'], '--cert', policy['certificate'],
                '--output', signed, original)
        os.chmod(signed, 0o600)
        with signed.open('rb') as stream:
            os.fsync(stream.fileno())
        if verify(signed, kind, policy) != sections:
            raise ValueError('signing changed PE section contents')
        receipt = {'schema_version': 1, 'kind': kind, 'purpose': policy['purpose'],
                   'certificate_sha256': policy['certificate_sha256'],
                   'input_sha256': digest(original), 'artifact_sha256': digest(signed),
                   'firmware_trust': 'not-evaluated'}
        write_new(pending / 'receipt.json', (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode())
        sync_directory(pending)
        pending.rename(candidate)
        sync_directory(STATE)
        return candidate


def verify_candidate(kind, policy):
    if kind not in KINDS:
        raise ValueError('unsupported artifact kind')
    candidate = trusted(STATE / (kind + '.ready'), private=True, directory=True)
    trusted(candidate / 'receipt.json', private=True)
    receipt = json.loads((candidate / 'receipt.json').read_bytes(), object_pairs_hook=unique_object)
    expected = {'schema_version', 'kind', 'purpose', 'certificate_sha256', 'input_sha256',
                'artifact_sha256', 'firmware_trust'}
    if (not isinstance(receipt, dict) or set(receipt) != expected
            or type(receipt['schema_version']) is not int or receipt['schema_version'] != 1
            or receipt['kind'] != kind or receipt['purpose'] != policy['purpose']
            or receipt['certificate_sha256'] != policy['certificate_sha256']
            or receipt['firmware_trust'] != 'not-evaluated'):
        raise ValueError('candidate receipt does not match signing policy')
    signed, original = candidate / 'artifact.efi', candidate / 'input.efi'
    sections = verify(signed, kind, policy)
    if (inspect_image(original, kind) != sections or digest(signed) != receipt['artifact_sha256']
            or digest(original) != receipt['input_sha256']):
        raise ValueError('candidate bytes do not match receipt and original sections')
    return receipt


def database_entries(data):
    """Read EFI_SIGNATURE_LIST framing without inferring trust from its presence."""
    entries = []
    while data:
        if len(data) < 28:
            raise ValueError('truncated EFI signature list')
        kind = data[:16]
        size, header, entry = struct.unpack_from('<III', data, 16)
        if size < 28 or size > len(data) or header > size - 28 or entry <= 16:
            raise ValueError('invalid EFI signature list sizes')
        payload = data[28 + header:size]
        if not payload or len(payload) % entry:
            raise ValueError('invalid EFI signature list entries')
        entries.extend((kind, header, payload[offset + 16:offset + entry])
                       for offset in range(0, len(payload), entry))
        data = data[size:]
    return entries


def database_certificates(data):
    entries = database_entries(data)
    return ([value for kind, header, value in entries if kind == X509_GUID and header == 0],
            any(kind != X509_GUID or header != 0 for kind, header, _ in entries))


def authenticode_hash(image):
    # efitools can exit zero on hashing failure; require its complete success output.
    output = command('hash-to-efi-sig-list', trusted(image), '/dev/null').decode().strip()
    match = re.fullmatch(r'HASH IS ([0-9a-f]{64})', output)
    if not match:
        raise ValueError('EFI tool did not establish the Authenticode image hash')
    return match[1]


def firmware(certificate=None):
    def read(name, guid):
        try:
            with (EFIVARS / (name + '-' + guid)).open('rb') as stream:
                raw = stream.read(1024 * 1024 + 5)
            if len(raw) < 4 or len(raw) > 1024 * 1024 + 4:
                return None
            return raw[4:]
        except OSError:
            return None
    result = {}
    for name in ('SecureBoot', 'SetupMode', 'AuditMode', 'DeployedMode'):
        raw = read(name, GLOBAL_GUID)
        result[name] = bool(raw[0]) if raw in (b'\x00', b'\x01') else None
    for name, guid in [('PK', GLOBAL_GUID), ('KEK', GLOBAL_GUID), ('db', DB_GUID), ('dbx', DB_GUID)]:
        raw = read(name, guid)
        info = {'readable': raw is not None, 'contains_signer_certificate': None,
                'other_signature_types': None, 'empty': None}
        if name == 'dbx':
            info['sha256_images'] = None
        if raw is not None:
            try:
                certs, other = database_certificates(raw)
                info.update(empty=not raw, contains_signer_certificate=certificate in certs if certificate else None,
                            other_signature_types=other)
                if name == 'dbx':
                    entries = database_entries(raw)
                    if all(kind == SHA256_GUID and header == 0 and len(value) == 32 for kind, header, value in entries):
                        info['sha256_images'] = [value.hex() for _, _, value in entries]
            except ValueError:
                info['malformed'] = True
        result[name] = info
    result['image_authorization'] = 'not-evaluated'
    return result


def check_enrollment(policy, image=None):
    observed = firmware(identity(policy))
    if observed['dbx']['contains_signer_certificate'] is True:
        raise ValueError('configured certificate is present in firmware dbx')
    if observed['db']['contains_signer_certificate'] is not True:
        raise ValueError('configured certificate not observed in firmware db; trust absent or unknown')
    # shortcut: certificate/TBS and unknown dbx formats remain refused pending qualification.
    if observed['dbx']['empty'] is not True:
        hashes = observed['dbx']['sha256_images']
        if image is None or hashes is None:
            raise ValueError('full dbx policy evaluation unavailable; a supported image revocation check is required')
        if authenticode_hash(image) in hashes:
            raise ValueError('image is revoked by firmware dbx')
    if observed['SecureBoot'] is not True or observed['SetupMode'] is not False:
        raise ValueError('firmware does not report SecureBoot enabled with SetupMode disabled')
    if observed['AuditMode'] is True:
        raise ValueError('firmware reports non-enforcing audit mode')
    return observed


def artifact_verdict(path, policy):
    before = digest(trusted(path))
    verify(path, 'uki', policy)
    check_enrollment(policy, path)
    if digest(path) != before:
        raise ValueError('artifact changed during verification')
    return {'schema_version': 1, 'sha256': before, 'signature_verified': True,
            'firmware_trusted': True}


def loader_payload(path):
    """Compare all loader bytes except Authenticode's checksum and certificate table."""
    import pefile
    data = bytearray(trusted(path).read_bytes())
    with pefile.PE(data=data, fast_load=True) as pe:
        security = pe.OPTIONAL_HEADER.DATA_DIRECTORY[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_SECURITY']]
        if security.VirtualAddress:
            end = max(s.PointerToRawData + s.SizeOfRawData for s in pe.sections)
            if security.VirtualAddress < end or security.VirtualAddress + security.Size != len(data):
                raise ValueError('unsupported loader certificate layout')
            del data[security.VirtualAddress:]
        for offset, size in [(pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 4),
                             (security.get_file_offset(), 8)]:
            data[offset:offset + size] = b'\0' * size
    return data


def clean_signing_state():
    for name in ('uki.pending', 'uki.ready', 'uki.publish.json', 'rebind.pending',
                 'bootloader.pending', 'bootloader.ready'):
        if os.path.lexists(STATE / name):
            raise ValueError('unfinished signing operation; preserve and inspect its journal')


def ready(esp, policy):
    require_root()
    trusted(esp, directory=True)
    trusted(STATE, private=True, directory=True)
    identity(policy, signing=True)
    clean_signing_state()
    version = command('bootctl', '--version').decode().split()
    if len(version) < 2 or not re.fullmatch(r'262(?:\.\S+)?', version[1]):
        raise ValueError('boot provider requires systemd 262')
    if (command('bootctl', '--print-esp-path').decode().strip() != str(esp)
            or command('bootctl', '--print-boot-path').decode().strip() != str(esp)):
        raise ValueError('running ESP or XBOOTLDR differs from the managed layout')
    installed = [esp / 'EFI/systemd/systemd-bootx64.efi', esp / 'EFI/BOOT/BOOTX64.EFI']
    if command('bootctl', '--print-loader-path').decode().strip() not in map(str, installed):
        raise ValueError('running loader is not one of the managed ESP copies')
    info = EFIVARS / 'LoaderInfo-4a67b082-0a4c-41cf-b6c7-440b29bb8c4f'
    if not re.fullmatch(r'systemd-boot 262(?:[.-]\S+)?', info.read_bytes()[4:].decode('utf-16-le').rstrip('\0')):
        raise ValueError('running loader version is not systemd-boot 262')
    inspect_image(LOADER, 'bootloader')
    expected = loader_payload(LOADER)
    for path in installed:
        before = digest(trusted(path))
        verify(path, 'bootloader', policy)
        check_enrollment(policy, path)
        actual = loader_payload(path)
        if (actual[:len(expected)] != expected or len(actual) - len(expected) not in range(8)
                or any(actual[len(expected):]) or digest(path) != before):
            raise ValueError('signed loader differs from packaged loader content')
    return {'schema_version': 1, 'systemd_version': 262,
            'loader_verified': True, 'firmware_trusted': True}


def rebind(source, cmdline, output, policy):
    """Change only the embedded selector in an authenticated, private UKI copy."""
    import pefile
    with signing_lock():
        clean_signing_state()
        identity(policy, signing=True)
        artifact_verdict(source, policy)
        before = verify(source, 'uki', policy)
        text = trusted(cmdline).read_text().strip()
        if not text or len(text) > 4096 or '\0' in text or '\n' in text or '\r' in text:
            raise ValueError('invalid embedded command line')
        trusted(output.parent, private=True, directory=True)
        if os.path.lexists(output):
            raise ValueError('rebind output already exists')
        pending = STATE / 'rebind.pending'
        pending.mkdir(mode=0o700)
        sync_directory(STATE)
        original = pending / 'input.efi'
        copy_new(source, original)
        command('sbattach', '--remove', original)
        with pefile.PE(str(original), fast_load=True) as pe:
            section, = [s for s in pe.sections if s.Name.rstrip(b'\0') == b'.cmdline']
            payload = text.encode() + b'\0'
            # shortcut: refuse selectors exceeding existing PE padding until UKI rebuilding is qualified.
            if len(payload) > section.SizeOfRawData:
                raise ValueError('new command line exceeds the existing UKI section capacity')
            pe.set_bytes_at_offset(section.PointerToRawData, payload.ljust(section.SizeOfRawData, b'\0'))
            section.Misc_VirtualSize = len(payload)
            pe.OPTIONAL_HEADER.CheckSum = pe.generate_checksum()
            unsigned = pending / 'unsigned.efi'
            write_new(unsigned, pe.write())
        signed = pending / 'artifact.efi'
        command('sbsign', '--key', policy['private_key'], '--cert', policy['certificate'],
                '--output', signed, unsigned)
        os.chmod(signed, 0o600)
        with signed.open('rb') as stream:
            os.fsync(stream.fileno())
        after = verify(signed, 'uki', policy)
        if (set(before) != set(after) or after['.cmdline']['text'].rstrip('\0') != text
                or any(after[name] != value for name, value in before.items() if name != '.cmdline')):
            raise ValueError('rebind changed protected UKI payload')
        verdict = artifact_verdict(signed, policy)
        copy_new(signed, output)
        if artifact_verdict(output, policy) != verdict:
            raise ValueError('rebind output changed during publication')
        sync_directory(output.parent)
        write_new(pending / 'receipt.json', (json.dumps(verdict, sort_keys=True) + '\n').encode())
        sync_directory(pending)
        pending.rename(STATE / ('rebind.consumed.' + str(uuid.uuid4())))
        sync_directory(STATE)


def coordinator():
    """Hooks must descend from the distroctl process holding BOTH mutation locks."""
    require_root()
    ancestors = set()
    pid = os.getppid()
    while pid > 1 and pid not in ancestors:
        ancestors.add(pid)
        pid = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[1])
    executable = trusted(DISTROCTL)
    paths = [trusted(path, private=True) for path in (UPDATE_LOCK, STORE / 'lock')]
    owners = []
    for ancestor in ancestors:
        proc = Path(f'/proc/{ancestor}')
        if not os.path.samefile(proc / 'exe', executable):
            continue
        held = set()
        for descriptor in (proc / 'fdinfo').iterdir():
            try:
                matches = [path for path in paths if os.path.samefile(proc / 'fd' / descriptor.name, path)]
                if not matches:
                    continue
                # Btrfs st_dev is per subvolume; /proc/locks uses the superblock device.
                for line in descriptor.read_text().splitlines():
                    fields = line.split()
                    if (len(fields) == 9 and fields[:1] == ['lock:']
                            and fields[2:5] == ['FLOCK', 'ADVISORY', 'WRITE']
                            and fields[5] == str(ancestor) and fields[-2:] == ['0', 'EOF']):
                        held.update(matches)
            except FileNotFoundError:
                continue
        if held == set(paths):
            owners.append(ancestor)
    if len(owners) != 1:
        raise ValueError('signed boot writes require the locked Astraeus update coordinator')
    if trusted(GENERATIONS).read_text() != '1\n':
        raise ValueError('signed updates require enabled boot generations')
    selection = json.loads(trusted(STORE / 'generations/selection.json').read_bytes(), object_pairs_hook=unique_object)
    if (set(selection) != {'schema_version', 'current', 'previous'}
            or type(selection['schema_version']) is not int or selection['schema_version'] != 1
            or selection['current'] is not None or not re.fullmatch(r'[0-9]+-[0-9]+-[0-9]+', str(selection['previous']))):
        raise ValueError('no exclusively selected retained recovery generation')
    # The Rust owner checks authoritative history, pending journals, root identity and signatures.
    command('distroctl', 'boot', 'verify', selection['previous'], '--json')


def publish_maintenance(policy):
    with signing_lock():
        coordinator()
        receipt = verify_candidate('uki', policy)
        source = STATE / 'uki.ready/artifact.efi'
        verdict = artifact_verdict(source, policy)
        if verdict['sha256'] != receipt['artifact_sha256']:
            raise ValueError('candidate receipt hash mismatch')
        target = trusted(ESP / MAINTENANCE)
        pending = STATE / 'uki.publish.json'
        write_new(pending, (json.dumps({'schema_version': 1, 'sha256': verdict['sha256'],
                                       'target': str(target)}, sort_keys=True) + '\n').encode())
        sync_directory(STATE)
        temporary = target.with_name('.maintenance.next')
        copy_new(source, temporary)
        if artifact_verdict(temporary, policy) != verdict:
            raise ValueError('staged maintenance artifact changed')
        sync_directory(target.parent)
        os.replace(temporary, target)
        sync_directory(target.parent)
        if artifact_verdict(target, policy) != verdict:
            raise ValueError('published maintenance artifact changed')
        archive = STATE / ('uki.consumed.' + str(uuid.uuid4()))
        (STATE / 'uki.ready').rename(archive)
        pending.rename(archive / 'publication.json')
        sync_directory(archive)
        sync_directory(STATE)


def provider_main(argv=None):
    parser = argparse.ArgumentParser(description='Astraeus generation trust provider')
    parser.add_argument('--policy-root', type=absolute_path)
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('ready').add_argument('esp', type=absolute_path)
    sub.add_parser('verify').add_argument('image', type=absolute_path)
    binding = sub.add_parser('rebind')
    for name in ('source', 'cmdline', 'output'):
        binding.add_argument(name, type=absolute_path)
    args = parser.parse_args(argv)
    require_root()
    if args.policy_root:
        if args.operation != 'verify':
            raise ValueError('offline policy is read-only and supports artifact verification only')
        root = trusted(args.policy_root, directory=True)
        path = trusted(root / POLICY.relative_to('/'))
        policy = parse_policy(json.loads(path.read_bytes(), object_pairs_hook=unique_object))
        policy = dict(policy, certificate=str(root / Path(policy['certificate']).relative_to('/')))
    else:
        policy = load_policy()
    if args.operation == 'ready':
        print(json.dumps(ready(args.esp, policy), sort_keys=True))
    elif args.operation == 'verify':
        print(json.dumps(artifact_verdict(args.image, policy), sort_keys=True))
    else:
        rebind(args.source, args.cmdline, args.output, policy)


def signing_required():
    # Retaining state prevents deleting a missing/broken policy from enabling an unsigned fallback.
    for path in (POLICY, STATE, GENERATIONS):
        try:
            path.lstat()
            return True
        except FileNotFoundError:
            pass
    return firmware()['SecureBoot'] is True


def status():
    result = {'schema_version': 1, 'policy': 'absent', 'signing_key_present': None,
              'identity': 'unavailable', 'artifacts': {}, 'enrollment_readiness': 'not-ready'}
    der = None
    try:
        policy = load_policy()
        result['policy'] = 'configured'
        result['certificate_sha256'] = policy['certificate_sha256']
        try:
            trusted(policy['private_key'], private=True)
            result['signing_key_present'] = True
        except FileNotFoundError:
            result['signing_key_present'] = False
        except (OSError, ValueError):
            pass
        der = identity(policy)
        result['identity'] = 'valid'
        product = json.loads(Path('/usr/share/distro/installer-identity.json').read_bytes())['id']
        if not isinstance(product, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', product):
            raise ValueError('invalid installed product identity')
        paths = {'uki': ESP / 'EFI/Linux' / (product + '-linux.efi'),
                 'bootloader': ESP / 'EFI/systemd/systemd-bootx64.efi',
                 'fallback_bootloader': ESP / 'EFI/BOOT/BOOTX64.EFI'}
        if (STORE / 'generations/selection.json').exists():
            paths['uki'] = ESP / MAINTENANCE
            try:
                running = absolute_path(command('bootctl', '--print-stub-path').decode().strip())
                if running.parent != ESP / 'EFI/Astraeus' or not re.fullmatch(r'[0-9]+-[0-9]+-[0-9]+\.efi', running.name):
                    raise ValueError('unexpected running UKI path')
                paths['running_uki'] = running
            except (OSError, ValueError, RuntimeError):
                result['artifacts']['running_uki'] = {'signature': 'unavailable', 'path': None, 'sha256': None}
        for name, path in paths.items():
            artifact = {'path': str(path), 'sha256': None, 'signature': 'unavailable'}
            result['artifacts'][name] = artifact
            try:
                verify(path, 'uki' if name in ('uki', 'running_uki') else 'bootloader', policy)
                artifact.update(signature='valid-for-configured-certificate', sha256=digest(path))
            except FileNotFoundError:
                artifact['signature'] = 'missing'
            except (OSError, ValueError, RuntimeError):
                artifact['signature'] = 'invalid-or-unavailable'
        if all(v['signature'] == 'valid-for-configured-certificate' for v in result['artifacts'].values()):
            result['enrollment_readiness'] = 'manual-firmware-review-required'
    except FileNotFoundError:
        pass
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        result['policy'] = 'invalid-or-unavailable'
    result['firmware'] = firmware(der)
    if result['firmware']['dbx']['contains_signer_certificate'] is True:
        result['enrollment_readiness'] = 'blocked-by-firmware-certificate-revocation'
    return result


def prepare_test_keys(destination):
    require_root()
    destination = absolute_path(str(destination))
    if destination.parts[1] in ('efi', 'boot', 'usr'):
        raise ValueError('test keys must be outside boot/build artifacts')
    trusted(destination.parent, directory=True)
    destination.mkdir(mode=0o700)
    sync_directory(destination.parent)
    # No enrollment is done here. PK, KEK and db are deliberately distinct keys.
    for name in ('PK', 'KEK', 'db'):
        key, cert = destination / (name + '.key'), destination / (name + '.crt')
        command('openssl', 'req', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256',
                '-days', '30', '-subj', '/CN=Astraeus disposable OVMF ' + name,
                '-keyout', key, '-out', cert)
        os.chmod(key, 0o600)
        os.chmod(cert, 0o600)
        der = command('openssl', 'x509', '-in', cert, '-outform', 'DER')
        write_new(destination / (name + '.cer'), der)
        command('cert-to-efi-sig-list', '-g', str(uuid.uuid4()), cert, destination / (name + '.esl'))
    pin = hashlib.sha256((destination / 'db.cer').read_bytes()).hexdigest()
    policy = {'schema_version': 1, 'purpose': 'disposable-ovmf',
              'certificate': str(destination / 'db.crt'), 'private_key': str(destination / 'db.key'),
              'certificate_sha256': pin, 'revoked_certificate_sha256': []}
    write_new(destination / 'policy.json', (json.dumps(policy, indent=2) + '\n').encode())
    for file in destination.iterdir():
        os.chmod(file, 0o600)
        with file.open('rb') as stream:
            os.fsync(stream.fileno())
    write_new(destination / 'DISPOSABLE-OVMF-ONLY', b'No firmware has been modified. Never enroll these keys on real hardware.\n')
    sync_directory(destination)
    sync_directory(destination.parent)
    return {'certificate_sha256': pin, 'enrolled': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    commands.add_parser('status').add_argument('--json', action='store_true')
    commands.add_parser('check-config')
    commands.add_parser('check-enrollment')
    commands.add_parser('guard-legacy')
    commands.add_parser('guard-update')
    commands.add_parser('uki-output').add_argument('legacy', type=absolute_path)
    signer = commands.add_parser('stage')
    signer.add_argument('kind', choices=KINDS)
    signer.add_argument('input', type=Path)
    verifier = commands.add_parser('verify')
    verifier.add_argument('kind', choices=KINDS)
    verifier.add_argument('artifact', type=Path)
    commands.add_parser('verify-candidate').add_argument('kind', choices=KINDS)
    hook = commands.add_parser('post-uki')
    hook.add_argument('kernel')
    hook.add_argument('initramfs')
    hook.add_argument('uki', type=Path)
    test = commands.add_parser('prepare-test-keys')
    test.add_argument('directory', type=Path)
    test.add_argument('--disposable-ovmf-only', required=True, action='store_true')
    args = parser.parse_args(argv)
    if args.operation == 'uki-output':
        print(UNSIGNED if signing_required() else args.legacy)
        return
    if args.operation == 'guard-legacy':
        if signing_required():
            raise ValueError('Secure Boot requires boot-generation integration; legacy boot writes refused')
        return
    if args.operation == 'guard-update':
        if signing_required():
            coordinator()
            ready(ESP, load_policy())
        return
    if args.operation == 'status':
        print(json.dumps(status(), indent=2, sort_keys=True))
        return
    if args.operation == 'prepare-test-keys':
        print(json.dumps(prepare_test_keys(args.directory)))
        return
    if args.operation == 'post-uki' and args.uki != UNSIGNED and not signing_required():
        return
    policy = load_policy()
    if args.operation == 'check-config':
        identity(policy, signing=True)
        print('Signing identity and private key verified; firmware trust not evaluated.')
    elif args.operation == 'check-enrollment':
        print(json.dumps(check_enrollment(policy), sort_keys=True))
    elif args.operation == 'verify':
        verify(args.artifact, args.kind, policy)
        print('Signature verified for configured certificate; firmware trust not evaluated.')
    elif args.operation == 'verify-candidate':
        print(json.dumps(verify_candidate(args.kind, policy), sort_keys=True))
    else:
        if args.operation == 'post-uki':
            if args.uki != UNSIGNED:
                raise ValueError('Secure Boot post hook requires the private unsigned staging path')
            candidate = stage('uki', args.uki, policy)
            if GENERATIONS.exists():
                publish_maintenance(policy)
                candidate = ESP / MAINTENANCE
        else:
            candidate = stage(args.kind, args.input, policy)
        print(candidate)


if __name__ == '__main__':
    try:
        if Path(sys.argv[0]).name == 'astraeus-boot-artifact':
            provider_main()
        else:
            main()
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f'astraeus-secure-boot: {error}', file=sys.stderr)
        sys.exit(1)
