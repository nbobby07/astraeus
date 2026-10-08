#!/usr/bin/python3 -I
"""Owner signing and read-only firmware observations. Never activates or enrolls."""
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
FINGERPRINT = re.compile(r'[0-9a-f]{64}')
KINDS = ('uki', 'bootloader')


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


def database_certificates(data):
    """Read EFI_SIGNATURE_LIST framing, not signature or firmware policy validation."""
    certificates, other_types = [], False
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
        if kind == X509_GUID:
            certificates.extend(payload[offset + 16:offset + entry] for offset in range(0, len(payload), entry))
        else:
            other_types = True
        data = data[size:]
    return certificates, other_types


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
        if raw is not None:
            try:
                certs, other = database_certificates(raw)
                info.update(empty=not raw, contains_signer_certificate=certificate in certs if certificate else None,
                            other_signature_types=other)
            except ValueError:
                info['malformed'] = True
        result[name] = info
    result['image_authorization'] = 'not-evaluated'
    return result


def check_enrollment(policy):
    observed = firmware(identity(policy))
    if observed['dbx']['contains_signer_certificate'] is True:
        raise ValueError('configured certificate is present in firmware dbx')
    if observed['db']['contains_signer_certificate'] is not True:
        raise ValueError('configured certificate not observed in firmware db; trust absent or unknown')
    # ponytail: nonempty dbx needs firmware image/TBS revocation validation before this gate can accept it.
    if observed['dbx']['empty'] is not True:
        raise ValueError('full dbx policy evaluation unavailable; firmware validation required')
    if observed['SecureBoot'] is not True or observed['SetupMode'] is not False:
        raise ValueError('firmware does not report SecureBoot enabled with SetupMode disabled')
    return observed


def signing_required():
    # Retaining state prevents deleting a missing/broken policy from enabling an unsigned fallback.
    for path in (POLICY, STATE):
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
        paths = {'uki': Path('/efi/EFI/Linux') / (product + '-linux.efi'),
                 'bootloader': Path('/efi/EFI/systemd/systemd-bootx64.efi'),
                 'fallback_bootloader': Path('/efi/EFI/BOOT/BOOTX64.EFI')}
        for name, path in paths.items():
            try:
                verify(path, 'uki' if name == 'uki' else 'bootloader', policy)
                result['artifacts'][name] = 'valid-for-configured-certificate'
            except FileNotFoundError:
                result['artifacts'][name] = 'missing'
            except (OSError, ValueError, RuntimeError):
                result['artifacts'][name] = 'invalid-or-unavailable'
        if all(v == 'valid-for-configured-certificate' for v in result['artifacts'].values()):
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
        else:
            candidate = stage(args.kind, args.input, policy)
        print(candidate)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f'astraeus-secure-boot: {error}', file=sys.stderr)
        sys.exit(1)
