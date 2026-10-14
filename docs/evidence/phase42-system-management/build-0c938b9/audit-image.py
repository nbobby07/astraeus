#!/usr/bin/env python3
"""Task-local audit of actual candidate media and signed package contents.

Streams file contents without a full filesystem extraction. Never prints key
material, copies guest disks, or provisions an installed/live filesystem.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading

KEY_BLOCK = re.compile(
    rb'-----BEGIN ((?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----\r?\n'
    rb'(?:[A-Za-z0-9+/=: .-]*\r?\n){1,4000}?-----END \1-----')
FORBIDDEN = ('var/lib/astraeus/keys', 'var/lib/astraeus/secure-boot',
             'etc/astraeus/secure-boot', 'var/lib/astraeus-validation',
             'mnt/astraeus-validation', 'run/astraeus', 'var/log/astraeus/operations')
FORBIDDEN_NAMES = {'private-keys-v1.d', 'secring.gpg', 'db.key', 'PK.key', 'KEK.key',
                   'phase2-guest.py', 'integrated-guest.py', 'phase42-faults.py',
                   'phase42-baseline.py', 'desktop-session.py', 'gui-barrier.py'}
WORKER = 'usr/lib/systemd/system/astraeus-apply@.service'
POLICY = 'usr/share/polkit-1/actions/org.astraeus.system.policy'
BINARIES = ('usr/bin/distroctl', 'usr/bin/astraeus-control-center')
SYNC = 'var/lib/pacman/sync'
ARCHIVE_DATABASES = {'core', 'extra', 'multilib'}
SYNC_DATABASES = {name + '.db' for name in ARCHIVE_DATABASES} | {'distro.db', 'distro.db.sig'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def capture(*arguments, limit=64 * 1024 * 1024):
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
        result = subprocess.run([str(x) for x in arguments], stdout=output, stderr=error, timeout=1800)
        require(result.returncode == 0, f'{arguments[0]} failed with exit {result.returncode}')
        require(output.tell() <= limit, f'{arguments[0]} output exceeds its limit')
        output.seek(0)
        return output.read()


def chunks(stream):
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            return
        yield chunk


def inspect_stream(stream):
    result = hashlib.sha256()
    tail = b''
    total = 0
    for chunk in chunks(stream):
        result.update(chunk)
        total += len(chunk)
        combined = tail + chunk
        require(KEY_BLOCK.search(combined) is None, 'complete private-key block found in audited content')
        tail = combined[-256 * 1024:]
    return {'bytes': total, 'sha256': result.hexdigest(), 'private_key_blocks': 0}


def process_scan(arguments, handler=inspect_stream):
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([str(x) for x in arguments], stdout=subprocess.PIPE, stderr=errors)
        timer = threading.Timer(1800, process.kill)
        timer.start()
        try:
            value = handler(process.stdout)
            require(process.wait(timeout=30) == 0, f'{arguments[0]} stream audit failed')
            return value
        finally:
            timer.cancel()
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()


def normalized(value):
    while value.startswith('./'):
        value = value[2:]
    path = PurePosixPath(value.rstrip('/'))
    require(not path.is_absolute() and '..' not in path.parts, 'unsafe archive path')
    return str(path)


def inventory_check(paths):
    for path in paths:
        require(not any(path == prefix or path.startswith(prefix + '/') for prefix in FORBIDDEN),
                'owner or validation state found at ' + path)
        require(not any(part in FORBIDDEN_NAMES for part in PurePosixPath(path).parts),
                'private key or validation agent path found at ' + path)
        require('astraeus-validation' not in path and 'phase42-barrier' not in path,
                'validation instrumentation found at ' + path)
        if path.startswith(('etc/systemd/', 'usr/lib/systemd/')) and ('/wants/' in path or '/requires/' in path
                or any(part.endswith(('.wants', '.requires')) for part in PurePosixPath(path).parts)):
            require('astraeus-apply@' not in path, 'background worker is enabled in the image')
        require(not (path.startswith('etc/systemd/system/') and 'astraeus-apply@' in path),
                'unexpected installed worker override or instance')


def audit_accounts(passwd, kind):
    users = []
    for line in passwd.decode('utf-8').splitlines():
        fields = line.split(':')
        require(len(fields) == 7, 'malformed passwd entry')
        name, uid = fields[0], int(fields[2])
        require(name not in {'tester', 'builder', 'test', 'astraeus-validation'}, 'test account found')
        require(uid != 0 or name == 'root', 'additional privileged account found')
        if 1000 <= uid < 65534:
            require(kind == 'live' and name == 'live', 'unexpected human account in payload')
        require(kind != 'installed' or name != 'live', 'installed payload includes live account')
        users.append({'name': name, 'uid': uid})
    require(any(user['name'] == 'root' for user in users), 'root account missing')
    require(kind != 'live' or any(user['name'] == 'live' for user in users), 'live account missing')
    return users


def scan_sfs_stream(stream, regular_paths, classifications):
    """Scan every regular-file payload and bind public test constants to exact files."""
    records = []
    hardlinks = {}
    header_bytes = 0
    header_tail = b''
    stream_hash = hashlib.sha256()
    def filename(raw):
        value = re.sub(r'\\(.)', r'\1', raw.decode('utf-8'), flags=re.DOTALL)
        return normalized(value)
    while True:
        line = stream.readline(1024 * 1024)
        require(line and len(line) < 1024 * 1024, 'missing or oversized pseudo metadata')
        header_bytes += len(line)
        require(header_bytes < 64 * 1024 * 1024, 'pseudo metadata exceeds bound')
        stream_hash.update(line)
        header_tail = (header_tail + line)[-256 * 1024:]
        require(KEY_BLOCK.search(header_tail) is None, 'private-key block found in filesystem metadata')
        if line == b'# START OF DATA - DO NOT MODIFY\n':
            closing = stream.readline(1024)
            require(closing == b'#\n', 'invalid pseudo data boundary')
            stream_hash.update(closing)
            break
        match = re.fullmatch(rb'(.*) R -?\d+ [0-7]+ \d+ \d+ (\d+) (\d+) \d+\n', line)
        if match:
            records.append((filename(match[1]), int(match[2]), int(match[3])))
        else:
            match = re.fullmatch(rb'(.*) L (.*)\n', line)
            if match:
                path = filename(match[1])
                require(path not in hardlinks, 'duplicate pseudo hardlink')
                hardlinks[path] = filename(match[2])
    paths = [item[0] for item in records]
    require(len(set(paths)) == len(paths), 'duplicate pseudo regular-file record')
    require(set(paths) | (set(hardlinks) & regular_paths) == regular_paths,
            'pseudo stream does not cover the complete regular-file inventory')
    position = 0
    retained = {}
    for name, size, offset in records:
        require(offset == position, 'non-contiguous pseudo data offsets')
        digest = hashlib.sha256()
        tail = b''
        consumed = 0
        blocks = {}
        while consumed < size:
            chunk = stream.read(min(1024 * 1024, size - consumed))
            require(chunk, 'truncated regular-file data')
            digest.update(chunk)
            stream_hash.update(chunk)
            combined = tail + chunk
            for match in KEY_BLOCK.finditer(combined):
                at = consumed - len(tail) + match.start()
                blocks[at] = {'offset': at, 'bytes': match.end() - match.start(),
                              'sha256': hashlib.sha256(match[0]).hexdigest()}
            consumed += len(chunk)
            tail = combined[-256 * 1024:]
        found = [blocks[key] for key in sorted(blocks)]
        if name in classifications:
            known = classifications[name]
            require(digest.hexdigest() == known['sha256'] and size == known['bytes'],
                    'classified public-test file changed: ' + name)
            expected_blocks = [{key: block[key] for key in ('offset', 'bytes', 'sha256')}
                               for block in known['blocks']]
            require(found == expected_blocks, 'classified public-test blocks changed: ' + name)
            require(not any(target == name for target in hardlinks.values()),
                    'classified public-test file has an unexpected hardlink')
            retained[name] = {'package': known['package'], 'sha256': known['sha256'],
                              'bytes': size, 'private_key_blocks': found,
                              'classification': 'public upstream benchmark/self-test constants'}
        else:
            require(not found, 'unclassified private-key block found in ' + name)
        position += size
    require(stream.read(1) == b'', 'unexpected bytes after regular-file payloads')
    return {'bytes': position, 'sha256': stream_hash.hexdigest(),
            'regular_payload_records': len(records), 'regular_inventory_paths': len(regular_paths),
            'unclassified_private_key_blocks': 0, 'classified_public_test_material': retained}


def sync_database_contract(build_inputs, approved_archive, repository, fingerprint):
    require(isinstance(approved_archive, dict) and set(approved_archive) == ARCHIVE_DATABASES,
            'approved archive metadata must contain core, extra and multilib')
    require(all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                for value in approved_archive.values()), 'invalid approved archive database hash')
    require(build_inputs.get('archive_databases') == approved_archive,
            'build input archive metadata differs from approved hashes')
    require(build_inputs.get('repository_key') == fingerprint and repository.get('fingerprint') == fingerprint,
            'build input repository signer differs from verified repository')
    expected = {name + '.db': value for name, value in approved_archive.items()}
    for name in ('distro.db', 'distro.db.sig'):
        receipt = repository.get('files', {}).get(name)
        value = build_inputs.get('repository', {}).get(name)
        require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                and isinstance(receipt, dict) and receipt.get('sha256') == value,
                'build input signed metadata differs from verified repository: ' + name)
        expected[name] = value
    return expected


def audit_sync_metadata(image, entries, access, expected):
    require(isinstance(expected, dict) and set(expected) == SYNC_DATABASES
            and all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                    for value in expected.values()), 'incomplete sync metadata contract')
    actual = {path.removeprefix(SYNC + '/') for path in entries if path.startswith(SYNC + '/')}
    require(actual == SYNC_DATABASES, 'sync metadata inventory differs from approved five files')
    paths = ['', 'var', 'var/lib', 'var/lib/pacman', SYNC]
    observed_access = {}
    for path in paths + [SYNC + '/' + name for name in sorted(expected)]:
        record = access.get(path)
        require(record is not None, 'sync metadata access record missing: ' + (path or '/'))
        mode, owner = record
        is_directory = path in paths
        require(len(mode) == 10 and mode[0] == ('d' if is_directory else '-') and owner == '0/0',
                'sync metadata path is not a root-owned regular file or directory: ' + (path or '/'))
        require(mode[5] != 'w' and mode[8] != 'w', 'sync metadata path is publicly writable: ' + (path or '/'))
        require(mode[9] == 'x' if is_directory else mode[7] == 'r',
                'sync metadata is inaccessible to ordinary users: ' + (path or '/'))
        observed_access[path or '/'] = {'mode': mode, 'owner': owner}
    observed = {}
    for name, expected_hash in sorted(expected.items()):
        path = SYNC + '/' + name
        require(entries.get(path) == '-', 'sync metadata is missing or not regular: ' + path)
        actual_hash = hashlib.sha256(capture('unsquashfs', '-cat', image, path)).hexdigest()
        require(actual_hash == expected_hash, 'sync metadata hash differs: ' + path)
        observed[name] = actual_hash
    return {'files': observed, 'access': observed_access, 'ordinary_user_accessible': True,
            'matches_approved_build_inputs_and_verified_repository': True}


def audit_install_inputs(entries, access):
    prefix = 'usr/share/distro/install-inputs'
    required = {prefix, *(prefix + '/' + name for name in ('graphics.json', 'gaming.json', 'management.json'))}
    require(required <= set(entries), 'installed trust inputs are incomplete')
    paths = ['', 'usr', 'usr/share', 'usr/share/distro'] + sorted(
        path for path in entries if path == prefix or path.startswith(prefix + '/'))
    observed = {}
    for path in paths:
        record = access.get(path)
        require(record is not None, 'installed trust input access record missing')
        mode, owner = record
        require(owner == '0/0' and mode[0] in 'd-', 'installed trust input is not root-owned regular data: ' + path)
        require(mode[5] != 'w' and mode[8] != 'w', 'installed trust input is publicly writable: ' + path)
        require(mode[7] == 'r' and (mode[0] != 'd' or mode[9] == 'x'),
                'installed trust input is inaccessible to ordinary users: ' + path)
        observed[path or '/'] = {'mode': mode, 'owner': owner}
    return {'access': observed, 'root_owned_nonwritable_and_readable': True}


def audit_sfs(image, kind, expected, repository, sync_expected, classifications=None):
    listing = capture('unsquashfs', '-lln', image).decode('utf-8')
    entries = {}
    access = {}
    for line in listing.splitlines():
        if ' squashfs-root' not in line:
            continue
        metadata, path = line.split(' squashfs-root', 1)
        if path and not path.startswith('/'):
            continue
        path = path.removeprefix('/').split(' -> ', 1)[0]
        fields = metadata.split()
        require(len(fields) >= 2, 'malformed SquashFS access metadata')
        access[normalized(path) if path else ''] = (fields[0], fields[1])
        if not path:
            continue
        entries[normalized(path)] = line[0]
    require(entries, 'empty SquashFS inventory')
    inventory_check(entries)
    sync_metadata = audit_sync_metadata(image, entries, access, sync_expected)
    install_inputs = audit_install_inputs(entries, access) if kind == 'installed' else None
    regular_paths = {path for path, kind in entries.items() if kind == '-'}
    content = process_scan(['unsquashfs', '-processors', '2', '-pf', '-', image],
                           lambda stream: scan_sfs_stream(stream, regular_paths, classifications or {}))
    observed = {}
    for path, expected_hash in expected.items():
        require(entries.get(path) == '-', 'expected packaged file is missing or not regular: ' + path)
        actual = hashlib.sha256(capture('unsquashfs', '-cat', image, path)).hexdigest()
        require(actual == expected_hash, 'packaged identity differs: ' + path)
        observed[path] = actual
    worker = capture('unsquashfs', '-cat', image, WORKER).decode('utf-8')
    require('[Install]' not in worker and 'ExecStart=/usr/bin/systemd-inhibit ' in worker
            and '/usr/bin/distroctl system worker %i' in worker and 'User=root' in worker,
            'worker does not have the approved one-shot service contract')
    accounts = audit_accounts(capture('unsquashfs', '-cat', image, 'etc/passwd'), kind)
    embedded = {path.removeprefix('opt/distro/repo/'): path for path, entry_type in entries.items()
                if path.startswith('opt/distro/repo/') and entry_type != 'd'}
    require(set(embedded) == set(repository['files']), 'embedded repository inventory differs')
    for relative, path in embedded.items():
        observed_repo = process_scan(['unsquashfs', '-cat', image, path])
        require(observed_repo == repository['files'][relative], 'embedded signed repository bytes differ')
    return {'sha256': digest(image), 'bytes': image.stat().st_size,
            'inventory_sha256': hashlib.sha256(listing.encode()).hexdigest(),
            'entry_count': len(entries), 'stream_content_audit': content, 'identities': observed,
            'accounts': accounts, 'worker_enabled': False, 'owner_and_validation_state_absent': True,
            'embedded_repository_matches_verified_archives': True, 'sync_metadata': sync_metadata, 'installed_trust_inputs': install_inputs}


def primary_fingerprints(text):
    values, waiting = [], False
    for line in text.splitlines():
        fields = line.split(':')
        if fields[0] == 'pub':
            waiting = True
        elif fields[0] == 'fpr' and waiting:
            values.append(fields[9])
            waiting = False
    return values


def audit_repo(repo, fingerprint, scratch, expected):
    keyring = scratch / 'public-keyring'
    keyring.mkdir(mode=0o700)
    gpg = ['gpg', '--homedir', keyring, '--batch', '--no-auto-key-retrieve', '--no-autostart']
    key = repo / 'repository-key.asc'
    require(key.is_file() and not key.is_symlink(), 'public repository certificate missing')
    shown = capture(*gpg, '--with-colons', '--show-keys', key).decode()
    require(primary_fingerprints(shown) == [fingerprint], 'repository public certificate identity differs')
    require(not any(line.startswith(('sec:', 'ssb:')) for line in shown.splitlines()), 'secret repository certificate found')
    capture(*gpg, '--import', key)
    require(not capture(*gpg, '--with-colons', '--list-secret-keys').strip(), 'repository import contains private key')
    files = {}
    for path in sorted(repo.rglob('*')):
        relative = path.relative_to(repo).as_posix()
        inventory_check([relative])
        require(path.resolve(strict=True).is_relative_to(repo), 'repository link escapes audited directory')
        if path.is_file():
            with path.open('rb') as stream:
                files[relative] = inspect_stream(stream)
    packages = sorted(repo.glob('*.pkg.tar.zst'))
    require(packages, 'signed repository contains no packages')
    observed = {}
    members = {}
    for artifact in [repo / 'distro.db', *packages]:
        require(artifact.is_file() and Path(str(artifact) + '.sig').is_file(), 'repository signature missing')
        status = capture(*gpg, '--status-fd', '1', '--verify', str(artifact) + '.sig', artifact).decode()
        valid = [line.split() for line in status.splitlines() if line.startswith('[GNUPG:] VALIDSIG ')]
        require(len(valid) == 1 and (valid[0][2] == fingerprint or valid[0][-1] == fingerprint),
                'repository artifact signed by an unexpected certificate')
    for package in packages:
        def inspect_tar(stream):
            count = 0
            with tarfile.open(fileobj=stream, mode='r|') as archive:
                for member in archive:
                    path = normalized(member.name)
                    inventory_check([path])
                    require(not member.isdev() and not member.isfifo(), 'unexpected package special file')
                    if member.isfile():
                        result = inspect_stream(archive.extractfile(member))
                        count += 1
                        if path in expected:
                            require(path not in observed, 'duplicate packaged identity: ' + path)
                            require(result['sha256'] == expected[path], 'repository packaged identity differs: ' + path)
                            observed[path] = result['sha256']
            return count
        members[package.name] = process_scan(['zstd', '-dc', package], inspect_tar)
    require(observed == expected, 'signed repository lacks one or more required packaged identities')
    return {'fingerprint': fingerprint, 'signatures_verified': len(packages) + 1,
            'files': files, 'package_member_counts': members, 'identities': observed,
            'private_key_blocks': 0, 'private_key_paths_absent': True}


def main():
    def interrupted(_signal, _frame):
        raise InterruptedError('image audit interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['iso', 'repo', 'output', 'expected', 'build-inputs']:
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ['iso-sha256', 'distroctl-sha256', 'desktop-sha256', 'repository-fingerprint', 'source-commit']:
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--public-test-material', type=Path)
    args = parser.parse_args()
    require(os.name == 'posix', 'run on the disposable Linux builder host')
    for name in ['iso_sha256', 'distroctl_sha256', 'desktop_sha256']:
        require(re.fullmatch('[0-9a-f]{64}', getattr(args, name)), 'full lowercase SHA256 required')
    require(re.fullmatch('[A-F0-9]{40}', args.repository_fingerprint), 'full uppercase signing fingerprint required')
    require(re.fullmatch('[0-9a-f]{40}', args.source_commit), 'full runtime source commit required')
    iso, repo = args.iso.resolve(strict=True), args.repo.resolve(strict=True)
    out = args.output.absolute()
    require(not out.exists() and not iso.is_relative_to(out) and not repo.is_relative_to(out)
            and not out.is_relative_to(repo), 'audit output must be new and separate from inputs')
    require(digest(iso) == args.iso_sha256, 'candidate ISO digest differs')
    fixed = json.loads(args.expected.read_text(encoding='utf-8-sig'))
    require(fixed['source_commit'] == args.source_commit, 'wrong runtime candidate')
    require(digest(args.build_inputs) == fixed['build_inputs_sha256'], 'build input receipt digest differs')
    build_inputs = json.loads(args.build_inputs.read_text(encoding='utf-8-sig'))
    classifications = {}
    proof = None
    if 'public_test_material_sha256' in fixed:
        require(args.public_test_material is not None, 'public-test provenance is required')
        require(digest(args.public_test_material) == fixed['public_test_material_sha256'],
                'public-test provenance digest differs')
        proof = json.loads(args.public_test_material.read_text())
        classifications = proof['files']
        source = proof['public_source']
        require(source['signature_report']['exit'] == 0 and source['report']['missing'] == [],
                'official source verification incomplete')
        require(source['report']['signed_package_proof_sha256'] == proof['package_evidence_sha256'],
                'source proof is not bound to package proof')
        require({item['sha256'] for item in source['report']['matches']} ==
                {block['sha256'] for item in classifications.values() for block in item['blocks']},
                'source constants do not cover the exact classified block set')
        require(classifications and all(item['same_as_approved_signed_package'] for item in classifications.values()),
                'public-test material is not bound to approved package bytes')
        require(all(package['signature']['gpgv_verified'] and package['signature']['matches_approved_database_embedded_bytes']
                    for package in proof['packages'].values()), 'public-test package signature provenance missing')
        require(all(not block['matches_repository_signer'] for item in classifications.values() for block in item['blocks']),
                'public-test key matches repository signer')
        require(proof['repository_public_keys'][0]['fingerprint'] == args.repository_fingerprint,
                'public-test proof uses a different repository signer')
    expected = dict(fixed['packaged_files'], **{BINARIES[0]: args.distroctl_sha256, BINARIES[1]: args.desktop_sha256})
    require(set(expected) == {WORKER, POLICY, *BINARIES}, 'unexpected expected-file contract')
    out.mkdir(mode=0o700, parents=True)
    scratch = out / 'scratch'
    scratch.mkdir(mode=0o700)
    result = {'schema_version': 1, 'passed': False, 'source_commit': fixed['source_commit'],
              'iso_sha256': args.iso_sha256, 'auditor_sha256': digest(Path(__file__)),
              'expectations_sha256': digest(args.expected), 'build_inputs_sha256': digest(args.build_inputs),
              'payloads': {}}
    if proof is not None:
        result['public_test_material_provenance_sha256'] = digest(args.public_test_material)
        result['public_test_material_packages'] = proof['packages']
        result['public_test_material_source'] = proof['public_source']
    try:
        # Two compressed filesystem copies only; never extract their full trees.
        require(shutil.disk_usage(scratch).free > iso.stat().st_size * 2 + 3 * 1024**3,
                'insufficient free space for bounded compressed-payload audit')
        result['repository'] = audit_repo(repo, args.repository_fingerprint, scratch, expected)
        sync_expected = sync_database_contract(build_inputs, fixed['archive_databases'],
                                               result['repository'], args.repository_fingerprint)
        live, installed = scratch / 'live.sfs', scratch / 'installed.sfs'
        capture('xorriso', '-osirrox', 'on', '-indev', iso, '-extract', '/arch/x86_64/airootfs.sfs', live)
        with installed.open('xb') as output, tempfile.TemporaryFile() as errors:
            process = subprocess.run(['unsquashfs', '-cat', str(live), 'opt/distro/install-root.sfs'],
                                     stdout=output, stderr=errors, timeout=1800)
            require(process.returncode == 0, 'nested installed payload extraction failed')
        for kind, image in [('live', live), ('installed', installed)]:
            result['payloads'][kind] = audit_sfs(image, kind, expected, result['repository'], sync_expected, classifications)
        require(digest(iso) == args.iso_sha256, 'original image changed during audit')
        result['passed'] = True
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        require(scratch.resolve().parent == out.resolve() and not scratch.is_symlink(), 'audit scratch ownership changed')
        shutil.rmtree(scratch)
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'result': str(out / 'result.json')}))


if __name__ == '__main__':
    main()
