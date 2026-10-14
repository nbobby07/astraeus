import hashlib
import copy
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('audit', Path(__file__).with_name('audit-image.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ImageAudit(unittest.TestCase):
    def test_sync_contract_binds_approved_build_inputs_and_verified_signed_repository(self):
        fingerprint = 'A' * 40
        approved = {name: hashlib.sha256(name.encode()).hexdigest() for name in audit.ARCHIVE_DATABASES}
        signed = {name: hashlib.sha256(name.encode()).hexdigest() for name in ('distro.db', 'distro.db.sig')}
        inputs = {'archive_databases': approved, 'repository_key': fingerprint, 'repository': signed}
        repository = {'fingerprint': fingerprint, 'files': {name: {'sha256': value} for name, value in signed.items()}}
        expected = {name + '.db': value for name, value in approved.items()} | signed
        self.assertEqual(audit.sync_database_contract(inputs, approved, repository, fingerprint), expected)
        for mutation in ('missing-upstream', 'changed-upstream', 'wrong-signer', 'missing-db', 'changed-db',
                         'missing-signature', 'changed-signature'):
            bad = copy.deepcopy(inputs)
            if mutation == 'missing-upstream':
                del bad['archive_databases']['extra']
            elif mutation == 'changed-upstream':
                bad['archive_databases']['extra'] = '0' * 64
            elif mutation == 'wrong-signer':
                bad['repository_key'] = 'B' * 40
            elif mutation.startswith('missing-'):
                del bad['repository']['distro.db' if mutation.endswith('-db') else 'distro.db.sig']
            else:
                bad['repository']['distro.db' if mutation.endswith('-db') else 'distro.db.sig'] = '0' * 64
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                audit.sync_database_contract(bad, approved, repository, fingerprint)
        for bad_approved in ({}, {'core': '0' * 64}, approved | {'unexpected': '0' * 64}, approved | {'core': 'BAD'}):
            with self.assertRaises(RuntimeError):
                audit.sync_database_contract(inputs, bad_approved, repository, fingerprint)

    def test_private_key_content_rejected_without_exposing_bytes(self):
        key = b'-----BEGIN PRIVATE KEY-----\n' + b'A' * 64 + b'\n-----END PRIVATE KEY-----\n'
        for content in [key, b'x' * (1024 * 1024 - 20) + key]:
            with self.assertRaisesRegex(RuntimeError, 'private-key block') as caught:
                audit.inspect_stream(io.BytesIO(content))
            self.assertNotIn('AAAA', str(caught.exception))
        data = b'-----BEGIN PUBLIC KEY-----\n' + b'A' * 64 + b'\n-----END PUBLIC KEY-----\n'
        self.assertEqual(audit.inspect_stream(io.BytesIO(data))['sha256'], hashlib.sha256(data).hexdigest())

    def test_owners_agents_and_enabled_worker_rejected(self):
        for path in ['var/lib/astraeus/keys/db.key', 'root/.gnupg/private-keys-v1.d/secret',
                     'tmp/phase2-guest.py', 'etc/systemd/system/multi-user.target.wants/astraeus-apply@abc.service',
                     'etc/systemd/system/astraeus-apply@.service.d/override.conf']:
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                audit.inventory_check([path])
        audit.inventory_check([audit.WORKER, audit.POLICY])

    def test_installed_accounts_and_archive_paths_fail_closed(self):
        root = b'root:x:0:0:root:/root:/bin/bash\n'
        audit.audit_accounts(root, 'installed')
        audit.audit_accounts(root + b'live:x:1000:1000:live:/home/live:/bin/bash\n', 'live')
        for addition in [b'tester:x:1000:1000:t:/home/tester:/bin/bash\n',
                         b'live:x:1000:1000:l:/home/live:/bin/bash\n',
                         b'other:x:0:0:o:/root:/bin/bash\n']:
            with self.assertRaises(RuntimeError):
                audit.audit_accounts(root + addition, 'installed')
        for path in ['/etc/passwd', '../secret', 'usr/../../secret']:
            with self.assertRaises(RuntimeError):
                audit.normalized(path)

    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('mksquashfs'), 'native SquashFS tools required')
    def test_real_squashfs_stream_and_packaged_file_identity(self):
        with tempfile.TemporaryDirectory(prefix='phase42-audit-') as directory:
            root = Path(directory) / 'root'
            files = {audit.WORKER: b'[Service]\nUser=root\nExecStart=/usr/bin/systemd-inhibit /usr/bin/distroctl system worker %i\n',
                     audit.POLICY: b'<policyconfig/>', 'usr/bin/distroctl': b'candidate-cli',
                     'usr/bin/astraeus-control-center': b'candidate-gui', 'etc/passwd': b'root:x:0:0:root:/root:/bin/bash\n'}
            files.update({'usr/share/distro/install-inputs/' + name: b'{}'
                          for name in ('graphics.json', 'gaming.json', 'management.json')})
            sync = {name: ('approved:' + name).encode() for name in audit.SYNC_DATABASES}
            files.update({audit.SYNC + '/' + name: value for name, value in sync.items()})
            sync_expected = {name: hashlib.sha256(value).hexdigest() for name, value in sync.items()}
            for path, contents in files.items():
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(contents)
            image = Path(directory) / 'root.sfs'
            subprocess.run(['mksquashfs', str(root), str(image), '-noappend', '-all-root', '-processors', '1', '-quiet'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            expected = {path: hashlib.sha256(files[path]).hexdigest() for path in [audit.WORKER, audit.POLICY, *audit.BINARIES]}
            result = audit.audit_sfs(image, 'installed', expected, {'files': {}}, sync_expected)
            self.assertEqual(result['identities'], expected)
            self.assertFalse(result['worker_enabled'])
            self.assertEqual(result['sync_metadata']['files'], sync_expected)
            self.assertTrue(result['sync_metadata']['ordinary_user_accessible'])
            expected['usr/bin/distroctl'] = '0' * 64
            with self.assertRaisesRegex(RuntimeError, 'identity differs'):
                audit.audit_sfs(image, 'installed', expected, {'files': {}}, sync_expected)

    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('mksquashfs'), 'native SquashFS tools required')
    def test_final_compressed_live_and_installed_sync_metadata_missing_or_tampered_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='phase42-sync-audit-') as directory:
            root = Path(directory) / 'root'
            sync = {name: ('approved:' + name).encode() for name in audit.SYNC_DATABASES}
            expected = {name: hashlib.sha256(value).hexdigest() for name, value in sync.items()}
            for name, value in sync.items():
                destination = root / audit.SYNC / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(value)
            # Recreate each compressed output after mutation. No mock reads can mask
            # ArchISO cleanup or a database changed at the last compression boundary.
            index = 0
            def run_audit(kind):
                nonlocal index
                index += 1
                image = Path(directory) / f'fixture-{index}.sfs'
                subprocess.run(['mksquashfs', str(root), str(image), '-noappend', '-all-root', '-processors', '1', '-quiet'],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return audit.audit_sfs(image, kind, {}, {'files': {}}, expected)
            for kind in ('live', 'installed'):
                for name, value in sync.items():
                    target = root / audit.SYNC / name
                    target.unlink()
                    with self.subTest(kind=kind, name=name, mutation='missing'), self.assertRaisesRegex(RuntimeError, 'sync metadata inventory'):
                        run_audit(kind)
                    target.write_bytes(value[:-1] + bytes([value[-1] ^ 1]))
                    with self.subTest(kind=kind, name=name, mutation='tampered'), self.assertRaisesRegex(RuntimeError, 'sync metadata hash differs'):
                        run_audit(kind)
                    target.write_bytes(value)
            for target, mode in [(root / 'var', 0o700), (root / audit.SYNC, 0o700),
                                 (root / audit.SYNC / 'distro.db', 0o600),
                                 (root / audit.SYNC / 'distro.db.sig', 0o600),
                                 (root / audit.SYNC, 0o777), (root / audit.SYNC / 'core.db', 0o666)]:
                original = target.stat().st_mode & 0o777
                target.chmod(mode)
                try:
                    with self.subTest(path=target.relative_to(root), mode=oct(mode)), self.assertRaisesRegex(RuntimeError, 'ordinary users|publicly writable'):
                        run_audit('live')
                finally:
                    target.chmod(original)
            target = root / audit.SYNC / 'distro.db'
            target.unlink()
            target.symlink_to('core.db')
            with self.assertRaisesRegex(RuntimeError, 'root-owned regular file'):
                run_audit('live')

    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('mksquashfs'), 'native SquashFS tools required')
    def test_compressed_installed_inputs_reject_archive_modes_ownership_and_symlinks(self):
        with tempfile.TemporaryDirectory(prefix='phase42-input-audit-') as directory:
            root = Path(directory) / 'root'
            inputs = root / 'usr/share/distro/install-inputs'
            inputs.mkdir(parents=True)
            for name in ('graphics.json', 'gaming.json', 'management.json'):
                (inputs / name).write_bytes(b'{}')
            index = 0

            def check(uid=0):
                nonlocal index
                index += 1
                image = Path(directory) / f'inputs-{index}.sfs'
                subprocess.run(['mksquashfs', str(root), str(image), '-noappend', '-force-uid', str(uid),
                                '-force-gid', '0', '-processors', '1', '-quiet'],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                entries, access = {}, {}
                for line in audit.capture('unsquashfs', '-lln', image).decode().splitlines():
                    if ' squashfs-root' not in line:
                        continue
                    metadata, path = line.split(' squashfs-root', 1)
                    path = path.removeprefix('/').split(' -> ', 1)[0]
                    fields = metadata.split()
                    access[path] = fields[0], fields[1]
                    if path:
                        entries[path] = fields[0][0]
                return audit.audit_install_inputs(entries, access)

            self.assertTrue(check()['root_owned_nonwritable_and_readable'])
            for target, mode in [(inputs, 0o775), (inputs / 'graphics.json', 0o664),
                                 (inputs, 0o700), (inputs / 'gaming.json', 0o600)]:
                original = target.stat().st_mode & 0o777
                target.chmod(mode)
                try:
                    with self.subTest(mode=oct(mode)), self.assertRaisesRegex(RuntimeError, 'publicly writable|inaccessible'):
                        check()
                finally:
                    target.chmod(original)
            with self.assertRaisesRegex(RuntimeError, 'root-owned'):
                check(uid=1000)
            (inputs / 'graphics.json').unlink()
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                check()
            (inputs / 'graphics.json').symlink_to('gaming.json')
            with self.assertRaisesRegex(RuntimeError, 'root-owned regular data'):
                check()

    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('gpg') and shutil.which('zstd'),
                         'native GPG and zstd tools required')
    def test_real_signed_repository_stream_matches_packaged_identities(self):
        with tempfile.TemporaryDirectory(prefix='phase42-audit-repo-') as directory:
            root = Path(directory)
            private, repo, scratch = [root / name for name in ('private', 'repo', 'scratch')]
            for path in (private, repo, scratch):
                path.mkdir(mode=0o700)
            gpg = ['gpg', '--homedir', private, '--batch', '--pinentry-mode', 'loopback', '--passphrase', '']
            try:
                audit.capture(*gpg, '--quick-generate-key', 'Temporary audit fixture', 'ed25519', 'sign', '1d')
                fingerprint = audit.primary_fingerprints(audit.capture(*gpg, '--with-colons', '--list-keys').decode())[0]
                (repo / 'repository-key.asc').write_bytes(audit.capture(*gpg, '--armor', '--export', fingerprint))
                files = {path: ('fixture:' + path).encode() for path in [audit.WORKER, audit.POLICY, *audit.BINARIES]}
                with tarfile.open(root / 'fixture.tar', 'w') as archive:
                    for name, content in files.items():
                        member = tarfile.TarInfo(name)
                        member.size = len(content)
                        archive.addfile(member, io.BytesIO(content))
                package = repo / 'fixture-1-1-any.pkg.tar.zst'
                package.write_bytes(audit.capture('zstd', '-c', root / 'fixture.tar'))
                (repo / 'distro.db').write_bytes(b'disposable database bytes')
                for path in (package, repo / 'distro.db'):
                    audit.capture(*gpg, '--detach-sign', path)
                expected = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
                result = audit.audit_repo(repo, fingerprint, scratch, expected)
                self.assertEqual(result['identities'], expected)
                self.assertEqual(result['signatures_verified'], 2)
                package.write_bytes(package.read_bytes() + b'changed')
                second = root / 'scratch2'
                second.mkdir()
                with self.assertRaisesRegex(RuntimeError, 'gpg failed'):
                    audit.audit_repo(repo, fingerprint, second, expected)
            finally:
                subprocess.run(['gpgconf', '--homedir', str(private), '--kill', 'gpg-agent'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    def test_public_test_material_requires_exact_file_bytes_and_location(self):
        key = b'-----BEGIN PRIVATE KEY-----\n' + b'A' * 64 + b'\n-----END PRIVATE KEY-----'
        def pseudo(files, link=b''):
            header = b''
            data = b''
            for path, content in files.items():
                header += path.encode() + b' R 0 644 0 0 ' + str(len(content)).encode() + b' ' + str(len(data)).encode() + b' 0\n'
                data += content
            return io.BytesIO(header + link + b'#\n# START OF DATA - DO NOT MODIFY\n#\n' + data)
        for path in ('usr/bin/gnutls-cli', 'usr/lib/libgnutls.so.30.42.0', 'usr/lib32/libgnutls.so.30.42.0'):
            known = {path: {'package': 'public-fixture', 'bytes': len(key),
                           'sha256': hashlib.sha256(key).hexdigest(),
                           'blocks': [{'offset': 0, 'bytes': len(key), 'sha256': hashlib.sha256(key).hexdigest()}]}}
            clean = audit.scan_sfs_stream(pseudo({path: key}), {path}, known)
            self.assertIn(path, clean['classified_public_test_material'])
            for changed in (key + b'\n' + key, key.replace(b'AAAA', b'BAAA', 1)):
                with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'classified public-test file changed'):
                    audit.scan_sfs_stream(pseudo({path: changed}), {path}, known)
            with self.assertRaisesRegex(RuntimeError, 'unclassified private-key block'):
                audit.scan_sfs_stream(pseudo({path: key, 'elsewhere': key}), {path, 'elsewhere'}, known)
            with self.assertRaisesRegex(RuntimeError, 'unexpected hardlink'):
                audit.scan_sfs_stream(pseudo({path: key}, b'elsewhere L ' + path.encode() + b'\n'),
                                      {path, 'elsewhere'}, known)
            with self.assertRaisesRegex(RuntimeError, 'complete regular-file inventory'):
                audit.scan_sfs_stream(pseudo({path: key}), {path, 'missing'}, known)

    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('mksquashfs'), 'native SquashFS tools required')
    def test_real_squashfs_changed_public_test_file_rejected(self):
        key = b'-----BEGIN PRIVATE KEY-----\n' + b'A' * 64 + b'\n-----END PRIVATE KEY-----'
        with tempfile.TemporaryDirectory(prefix='phase42-public-test-') as directory:
            root = Path(directory) / 'root'
            paths = ('usr/bin/gnutls-cli', 'usr/lib/libgnutls.so.30.42.0', 'usr/lib32/libgnutls.so.30.42.0')
            known = {}
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(key)
                known[path] = {'package': 'public-fixture', 'bytes': len(key), 'sha256': hashlib.sha256(key).hexdigest(),
                               'blocks': [{'offset': 0, 'bytes': len(key), 'sha256': hashlib.sha256(key).hexdigest()}]}
            def scan(index):
                image = Path(directory) / ('fixture-' + str(index) + '.sfs')
                subprocess.run(['mksquashfs', str(root), str(image), '-noappend', '-processors', '1', '-quiet'],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return audit.process_scan(['unsquashfs', '-processors', '1', '-pf', '-', image],
                                          lambda stream: audit.scan_sfs_stream(stream, set(paths), known))
            self.assertEqual(len(scan(0)['classified_public_test_material']), 3)
            for index, path in enumerate(paths, 1):
                for mutation, changed in enumerate((key + b'\n' + key, key.replace(b'AAAA', b'BAAA', 1))):
                    (root / path).write_bytes(changed)
                    with self.subTest(path=path, mutation=mutation), self.assertRaisesRegex(RuntimeError, 'classified public-test file changed'):
                        scan(index * 10 + mutation)
                (root / path).write_bytes(key)


if __name__ == '__main__':
    unittest.main()
