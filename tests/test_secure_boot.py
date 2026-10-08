"""Signature tests use disposable keys and synthetic UKIs, never host firmware."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import secure_boot as sb


def policy():
    return {'schema_version': 1, 'purpose': 'machine-owner', 'certificate': '/etc/astraeus/db.crt',
            'private_key': '/var/lib/astraeus/keys/db.key', 'certificate_sha256': 'a' * 64,
            'revoked_certificate_sha256': []}


def esl(cert, kind=sb.X509_GUID):
    entry = b'\x00' * 16 + cert
    return kind + struct.pack('<III', 28 + len(entry), 0, len(entry)) + entry


class PolicyTests(unittest.TestCase):
    def test_policy_rejects_ambiguity_and_unsafe_key_selection(self):
        self.assertEqual(sb.parse_policy(policy()), policy())
        changes = [('schema_version', True), ('schema_version', 2), ('purpose', 'production'),
                   ('certificate_sha256', 'AA:' * 32), ('certificate_sha256', None),
                   ('revoked_certificate_sha256', ['x']), ('revoked_certificate_sha256', ['a' * 64] * 2),
                   ('private_key', '/efi/db.key'), ('private_key', '/boot/db.key'),
                   ('private_key', '/usr/share/db.key'), ('private_key', '../db.key'),
                   ('private_key', '/root/../db.key'), ('private_key', '/root//db.key'),
                   ('private_key', '/'), ('private_key', '/root/key\x00'),
                   ('private_key', '/etc/astraeus/db.crt')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                value_policy = dict(policy(), **{key: value})
                with self.assertRaises(ValueError):
                    sb.parse_policy(value_policy)
        with self.assertRaises(ValueError):
            sb.parse_policy(dict(policy(), ignored='unsafe'))
        with self.assertRaises(ValueError):
            json.loads('{"schema_version":1,"schema_version":2}', object_pairs_hook=sb.unique_object)

    def test_firmware_framing_rejects_truncation_and_tracks_unknown_types(self):
        cert = b'public certificate fixture'
        self.assertEqual(sb.database_certificates(esl(cert)), ([cert], False))
        self.assertEqual(sb.database_certificates(esl(cert, b'\x00' * 16)), ([], True))
        for data in [b'x', esl(cert)[:-1], b'\x00' * 28,
                     sb.X509_GUID + struct.pack('<III', 30, 0, 16) + b'xx']:
            with self.assertRaises(ValueError):
                sb.database_certificates(data)

    def test_unknown_firmware_is_not_disabled_or_enforced(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sb, 'EFIVARS', Path(directory)):
            result = sb.firmware(b'cert')
            self.assertIsNone(result['SecureBoot'])
            self.assertIsNone(result['SetupMode'])
            self.assertIsNone(result['db']['contains_signer_certificate'])
            self.assertEqual(result['image_authorization'], 'not-evaluated')
            root = Path(directory)
            (root / ('SecureBoot-' + sb.GLOBAL_GUID)).write_bytes(b'\x07\0\0\0\x01')
            (root / ('SetupMode-' + sb.GLOBAL_GUID)).write_bytes(b'\x07\0\0\0\x00')
            (root / ('db-' + sb.DB_GUID)).write_bytes(b'\x07\0\0\0' + esl(b'cert'))
            (root / ('dbx-' + sb.DB_GUID)).write_bytes(b'\x07\0\0\0' + esl(b'cert'))
            result = sb.firmware(b'cert')
            self.assertTrue(result['SecureBoot'])
            self.assertFalse(result['SetupMode'])
            self.assertTrue(result['db']['contains_signer_certificate'])
            self.assertTrue(result['dbx']['contains_signer_certificate'])
            self.assertEqual(result['image_authorization'], 'not-evaluated')
            (root / ('SecureBoot-' + sb.GLOBAL_GUID)).write_bytes(b'\x07\0\0\0\x02')
            self.assertIsNone(sb.firmware()['SecureBoot'])
            (root / ('db-' + sb.DB_GUID)).write_bytes(b'\x07\0\0\0bad')
            self.assertTrue(sb.firmware()['db']['malformed'])

    def test_error_diagnostics_never_echo_tool_output_or_key_contents(self):
        output = subprocess.CompletedProcess([], 9, b'PRIVATE SECRET', b'PRIVATE SECRET')
        with patch.object(sb.subprocess, 'run', return_value=output) as run:
            with self.assertRaises(RuntimeError) as caught:
                sb.command('sbsign', '--key', '/private/file.key')
        self.assertNotIn('PRIVATE SECRET', str(caught.exception))
        self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertNotIn('OPENSSL_CONF', run.call_args.kwargs['env'])

    def test_removed_revoked_and_unknown_firmware_trust_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sb, 'EFIVARS', Path(directory)), \
                patch.object(sb, 'identity', return_value=b'cert'):
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'absent or unknown'):
                sb.check_enrollment(policy())
            for name, value in [('SecureBoot', b'\x01'), ('SetupMode', b'\x00')]:
                (root / (name + '-' + sb.GLOBAL_GUID)).write_bytes(b'\x07\0\0\0' + value)
            db, dbx = root / ('db-' + sb.DB_GUID), root / ('dbx-' + sb.DB_GUID)
            db.write_bytes(b'\x07\0\0\0' + esl(b'cert'))
            with self.assertRaisesRegex(ValueError, 'dbx policy'):
                sb.check_enrollment(policy())
            dbx.write_bytes(b'\x07\0\0\0')
            self.assertTrue(sb.check_enrollment(policy())['SecureBoot'])
            db.write_bytes(b'\x07\0\0\0' + esl(b'other cert'))
            with self.assertRaisesRegex(ValueError, 'absent or unknown'):
                sb.check_enrollment(policy())
            db.write_bytes(b'\x07\0\0\0' + esl(b'cert'))
            dbx.write_bytes(b'\x07\0\0\0' + esl(b'cert'))
            with self.assertRaisesRegex(ValueError, 'present in firmware dbx'):
                sb.check_enrollment(policy())
            dbx.write_bytes(b'\x07\0\0\0' + esl(b'image hash', b'\x00' * 16))
            with self.assertRaisesRegex(ValueError, 'dbx policy'):
                sb.check_enrollment(policy())

    def test_status_is_read_only_when_policy_is_absent(self):
        with patch.object(sb, 'load_policy', side_effect=FileNotFoundError), \
                patch.object(sb, 'firmware', return_value={'SecureBoot': None, 'dbx': {'contains_signer_certificate': None}}), \
                patch.object(sb, 'command') as command:
            observed = sb.status()
            self.assertEqual(observed['policy'], 'absent')
            self.assertEqual(observed['enrollment_readiness'], 'not-ready')
            self.assertIsNone(observed['signing_key_present'])
            command.assert_not_called()

    def test_post_hook_rejects_active_esp_input(self):
        with patch.object(sb, 'load_policy', return_value=policy()), patch.object(sb, 'stage') as stage, \
                patch.object(sb, 'signing_required', return_value=True):
            with self.assertRaisesRegex(ValueError, 'private unsigned staging'):
                sb.main(['post-uki', '/boot/vmlinuz-linux', '', '/efi/EFI/Linux/astraeus-dev-linux.efi'])
            stage.assert_not_called()

    def test_legacy_preset_uses_guarded_output_and_secure_preset_cannot_activate(self):
        self.assertIn('/efi/EFI/Linux/@@ID@@-linux.efi', (ROOT / 'distro/installed/linux.preset.in').read_text())
        secure = (ROOT / 'distro/installed/secure-boot/linux.preset').read_text()
        self.assertIn(sb.UNSIGNED.as_posix(), secure)
        self.assertNotIn('/efi/', secure)
        self.assertIn('exec /usr/bin/astraeus-secure-boot post-uki "${1-}" "${2-}" "${3-}"',
                      (ROOT / 'distro/installed/secure-boot/95-astraeus-sign').read_text())

    def test_signing_expectation_survives_deleted_policy_and_unknown_firmware(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(sb, 'POLICY', root / 'policy.json'), patch.object(sb, 'STATE', root / 'state'), \
                    patch.object(sb, 'firmware', return_value={'SecureBoot': None}):
                self.assertFalse(sb.signing_required())
                (root / 'state').mkdir()
                self.assertTrue(sb.signing_required())
                with self.assertRaisesRegex(ValueError, 'boot-generation integration'):
                    sb.main(['guard-legacy'])
                (root / 'state').rmdir()
                (root / 'policy.json').write_text('invalid policy')
                self.assertTrue(sb.signing_required())
                (root / 'policy.json').unlink()
                with patch.object(sb, 'firmware', return_value={'SecureBoot': True}):
                    self.assertTrue(sb.signing_required())

    def test_unconfigured_legacy_post_hook_is_a_noop(self):
        with patch.object(sb, 'signing_required', return_value=False), patch.object(sb, 'load_policy') as load:
            sb.main(['post-uki', '/boot/vmlinuz-linux', '/boot/initrd', ''])
            sb.main(['guard-legacy'])
            load.assert_not_called()

    def test_preset_output_never_falls_back_when_signing_is_required(self):
        for required in [True, False]:
            output = io.StringIO()
            with patch.object(sb, 'signing_required', return_value=required), patch('sys.stdout', output):
                sb.main(['uki-output', '/efi/EFI/Linux/astraeus-dev-linux.efi'])
            expected = sb.UNSIGNED if required else Path('/efi/EFI/Linux/astraeus-dev-linux.efi')
            self.assertEqual(output.getvalue().strip(), str(expected))
        output = io.StringIO()
        with patch.object(sb, 'signing_required', side_effect=PermissionError), patch('sys.stdout', output):
            with self.assertRaises(PermissionError):
                sb.main(['uki-output', '/efi/EFI/Linux/astraeus-dev-linux.efi'])
        self.assertEqual(output.getvalue(), '')

    def test_package_source_excludes_adjacent_private_keys_and_is_deterministic(self):
        import bootstrap
        data = bootstrap.project()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'input'
            files = ['Cargo.toml', 'Cargo.lock', 'distro/branding/project.toml', 'scripts/secure_boot.py',
                     'distro/packages/distroctl/PKGBUILD.in', 'docs/secure-boot.md',
                     'distro/installed/80-astraeus-secure-boot.hook',
                     'distro/installed/secure-boot/linux.preset',
                     'distro/installed/secure-boot/95-astraeus-sign', 'docs/adr/0003-owner-secure-boot.md']
            for name in files:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            (root / 'distro/packages/calamares').mkdir(parents=True)
            private = root / 'scripts/db.key'
            outputs = []
            for index in range(2):
                private.write_text('PRIVATE SIGNING MATERIAL ' + str(index))
                out = Path(directory) / ('package' + str(index))
                with patch.object(bootstrap, 'ROOT', root), \
                        patch.object(bootstrap, 'MANIFEST', root / 'distro/branding/project.toml'), \
                        patch.object(bootstrap, 'project', return_value=data), \
                        patch.object(bootstrap, 'run'), patch('sys.stdout', io.StringIO()):
                    bootstrap.prepare_package(out)
                archive = out / 'platform.tar.xz'
                with tarfile.open(archive) as source:
                    self.assertIn('platform/scripts/secure_boot.py', source.getnames())
                    self.assertFalse(any(name.endswith('.key') for name in source.getnames()))
                    for member in source:
                        self.assertNotIn(b'PRIVATE SIGNING MATERIAL', source.extractfile(member).read())
                outputs.append(archive.read_bytes())
            self.assertEqual(outputs[0], outputs[1])


NATIVE = (os.name == 'posix' and os.geteuid() == 0
          and all(shutil.which(tool) for tool in ['openssl', 'sbsign', 'sbverify', 'ukify', 'cert-to-efi-sig-list'])
          and Path('/usr/lib/systemd/boot/efi/linuxx64.efi.stub').exists())


@unittest.skipUnless(NATIVE, 'requires Linux root, sbsigntools, efitools, ukify and systemd EFI images')
class NativeSigningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='astraeus-signature-tests-', dir='/root')
        cls.root = Path(cls.temp.name)
        cls.keys = cls.root / 'keys'
        sb.prepare_test_keys(cls.keys)
        cls.policy = json.loads((cls.keys / 'policy.json').read_bytes())
        cls.uki = cls.root / 'unsigned.efi'
        initrd = cls.root / 'initrd'
        initrd.write_bytes(b'initramfs test payload')
        sb.command('ukify', '--config=/dev/null', 'build',
                   '--linux=/usr/lib/systemd/boot/efi/linuxx64.efi.stub', '--initrd=' + str(initrd),
                   '--uname=fixture-kernel', '--cmdline=root=UUID=fixture rootflags=subvol=@ rw',
                   '--os-release=ID=astraeus-dev\n', '--output=' + str(cls.uki))
        cls.loader = Path('/usr/lib/systemd/boot/efi/systemd-bootx64.efi')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=self.root)
        self.state = Path(self.work.name)
        self.state_patch = patch.object(sb, 'STATE', self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.addCleanup(self.work.cleanup)

    def test_sign_uki_and_bootloader_and_reverify_candidates(self):
        for kind, source in [('uki', self.uki), ('bootloader', self.loader)]:
            before = source.read_bytes()
            candidate = sb.stage(kind, source, self.policy)
            receipt = sb.verify_candidate(kind, self.policy)
            self.assertEqual(receipt['artifact_sha256'], sb.digest(candidate / 'artifact.efi'))
            self.assertEqual(receipt['input_sha256'], hashlib.sha256(before).hexdigest())
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(receipt['firmware_trust'], 'not-evaluated')
            self.assertEqual(candidate.stat().st_mode & 0o777, 0o700)
            for file in candidate.iterdir():
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)
                self.assertNotIn(b'PRIVATE KEY', file.read_bytes())
            with self.assertRaisesRegex(ValueError, 'candidate or incomplete'):
                sb.stage(kind, source, self.policy)

    def test_wrong_pin_revocation_missing_key_and_wrong_private_key(self):
        variations = [dict(self.policy, certificate_sha256='a' * 64),
                      dict(self.policy, revoked_certificate_sha256=[self.policy['certificate_sha256']]),
                      dict(self.policy, private_key=str(self.keys / 'missing.key')),
                      dict(self.policy, private_key=str(self.keys / 'PK.key'))]
        for value in variations:
            with self.subTest(value=value['private_key']):
                with self.assertRaises((ValueError, OSError)):
                    sb.stage('uki', self.uki, value)
                self.assertFalse((self.state / 'uki.ready').exists())
                self.assertFalse((self.state / 'uki.pending').exists())

    def test_expired_certificate_is_rejected_by_openssl(self):
        call = sb.command
        def future_clock(program, *args):
            if program == 'openssl' and args[0] == 'verify':
                args = (args[0], '-attime', str(int(time.time()) + 31 * 86400), *args[1:])
            return call(program, *args)
        with patch.object(sb, 'command', side_effect=future_clock):
            with self.assertRaisesRegex(RuntimeError, 'openssl: failed'):
                sb.stage('uki', self.uki, self.policy)
        self.assertFalse((self.state / 'uki.ready').exists())
        self.assertFalse((self.state / 'uki.pending').exists())

    def test_unsigned_wrong_signer_and_tampered_images_are_rejected(self):
        with self.assertRaises(RuntimeError):
            sb.verify(self.uki, 'uki', self.policy)
        signed = self.state / 'wrong.efi'
        sb.command('sbsign', '--key', self.keys / 'PK.key', '--cert', self.keys / 'PK.crt',
                   '--output', signed, self.uki)
        with self.assertRaises(RuntimeError):
            sb.verify(signed, 'uki', self.policy)
        candidate = sb.stage('uki', self.uki, self.policy)
        artifact = candidate / 'artifact.efi'
        data = artifact.read_bytes()
        self.assertIn(b'initramfs test payload', data)
        artifact.write_bytes(data.replace(b'initramfs test payload', b'initramfs evil payload'))
        with self.assertRaises(RuntimeError):
            sb.verify_candidate('uki', self.policy)

    def test_missing_artifact_and_receipt_tampering_cannot_be_consumed(self):
        candidate = sb.stage('uki', self.uki, self.policy)
        receipt = candidate / 'receipt.json'
        saved = receipt.read_bytes()
        changed = json.loads(saved)
        changed['artifact_sha256'] = '0' * 64
        receipt.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            sb.verify_candidate('uki', self.policy)
        receipt.write_bytes(saved)
        (candidate / 'artifact.efi').unlink()
        with self.assertRaises(FileNotFoundError):
            sb.verify_candidate('uki', self.policy)

    def test_signer_failure_and_interruption_keep_input_and_prior_artifacts(self):
        original = self.uki.read_bytes()
        prior = self.state / 'prior-known-good.efi'
        prior.write_bytes(b'retained prior generation')
        call = sb.command
        def fail(program, *args):
            if program == 'sbsign':
                (self.state / 'uki.pending/artifact.efi').write_bytes(b'incomplete')
                raise KeyboardInterrupt()
            return call(program, *args)
        with patch.object(sb, 'command', side_effect=fail):
            with self.assertRaises(KeyboardInterrupt):
                sb.stage('uki', self.uki, self.policy)
        self.assertFalse((self.state / 'uki.ready').exists())
        self.assertTrue((self.state / 'uki.pending').exists())
        self.assertEqual(self.uki.read_bytes(), original)
        self.assertEqual(prior.read_bytes(), b'retained prior generation')
        with self.assertRaisesRegex(ValueError, 'incomplete staging'):
            sb.stage('uki', self.uki, self.policy)

    def test_invalid_signer_output_never_becomes_ready(self):
        call = sb.command
        def unsigned_output(program, *args):
            if program == 'sbsign':
                shutil.copyfile(args[-1], args[args.index('--output') + 1])
                return b''
            return call(program, *args)
        with patch.object(sb, 'command', side_effect=unsigned_output):
            with self.assertRaises(RuntimeError):
                sb.stage('uki', self.uki, self.policy)
        self.assertFalse((self.state / 'uki.ready').exists())
        self.assertTrue((self.state / 'uki.pending/input.efi').exists())

    def test_receipt_write_failure_leaves_no_eligible_candidate(self):
        with patch.object(sb, 'write_new', side_effect=OSError('fixture disk full')):
            with self.assertRaises(OSError):
                sb.stage('uki', self.uki, self.policy)
        self.assertFalse((self.state / 'uki.ready').exists())
        self.assertTrue((self.state / 'uki.pending/artifact.efi').exists())

    def test_nonzero_signing_hook_failure_is_retained(self):
        call = sb.command
        def failure(program, *args):
            if program == 'sbsign':
                raise RuntimeError('sbsign: failed (exit 1)')
            return call(program, *args)
        with patch.object(sb, 'command', side_effect=failure):
            with self.assertRaisesRegex(RuntimeError, 'sbsign: failed'):
                sb.stage('uki', self.uki, self.policy)
        self.assertFalse((self.state / 'uki.ready').exists())
        self.assertFalse((self.state / 'uki.pending/artifact.efi').exists())
        self.assertTrue((self.state / 'uki.pending/input.efi').exists())

    def test_symlink_hardlink_unsafe_permissions_and_concurrent_signer_refused(self):
        import fcntl
        for mode in [0o644, 0o620, 0o666]:
            key = self.state / 'private.key'
            key.write_bytes((self.keys / 'db.key').read_bytes())
            key.chmod(mode)
            with self.assertRaises(ValueError):
                sb.identity(dict(self.policy, private_key=str(key)), signing=True)
            key.unlink()
        link = self.state / 'link'
        link.symlink_to(self.uki)
        with self.assertRaises(ValueError):
            sb.stage('uki', link, self.policy)
        link.unlink()
        os.link(self.uki, link)
        with self.assertRaises(ValueError):
            sb.stage('uki', link, self.policy)
        link.unlink()
        self.state.chmod(0o777)
        with self.assertRaises(ValueError):
            sb.stage('uki', self.uki, self.policy)
        self.state.chmod(0o700)
        with (self.state / 'signing.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'another signer'):
                sb.stage('uki', self.uki, self.policy)

    def test_structurally_wrong_images_and_bootloader_wrong_key(self):
        with self.assertRaises(ValueError):
            sb.stage('uki', self.loader, self.policy)
        signed = self.state / 'loader-wrong.efi'
        sb.command('sbsign', '--key', self.keys / 'KEK.key', '--cert', self.keys / 'KEK.crt',
                   '--output', signed, self.loader)
        with self.assertRaises(RuntimeError):
            sb.verify(signed, 'bootloader', self.policy)

    def test_wrong_architecture_or_non_efi_subsystem_cannot_be_signed(self):
        source = self.state / 'wrong.efi'
        original = self.uki.read_bytes()
        pe_offset = struct.unpack_from('<I', original, 0x3c)[0]
        for offset, value in [(pe_offset + 4, 0x14c), (pe_offset + 24 + 68, 3)]:
            data = bytearray(original)
            struct.pack_into('<H', data, offset, value)
            source.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'EFI application'):
                sb.inspect_image(source, 'uki')

    def test_policy_and_keys_cannot_be_controlled_by_an_unprivileged_user(self):
        key = self.state / 'owner.key'
        key.write_bytes((self.keys / 'db.key').read_bytes())
        key.chmod(0o600)
        os.chown(key, 65534, 65534)
        with self.assertRaisesRegex(ValueError, 'ownership'):
            sb.identity(dict(self.policy, private_key=str(key)), signing=True)
        config = self.state / 'policy.json'
        config.write_text(json.dumps(self.policy))
        config.chmod(0o666)
        with patch.object(sb, 'POLICY', config):
            with self.assertRaisesRegex(ValueError, 'permissions'):
                sb.load_policy()
        if shutil.which('setpriv'):
            result = subprocess.run(['setpriv', '--reuid=65534', '--regid=65534', '--clear-groups',
                                     'cat', str(self.keys / 'db.key')], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b'')

    def test_test_keys_are_distinct_private_and_never_enrolled(self):
        pins = [hashlib.sha256((self.keys / (name + '.cer')).read_bytes()).hexdigest()
                for name in ('PK', 'KEK', 'db')]
        self.assertEqual(len(set(pins)), 3)
        for name in ('PK', 'KEK', 'db'):
            certs, other = sb.database_certificates((self.keys / (name + '.esl')).read_bytes())
            self.assertEqual(certs, [(self.keys / (name + '.cer')).read_bytes()])
            self.assertFalse(other)
            self.assertEqual((self.keys / (name + '.key')).stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.keys / 'DISPOSABLE-OVMF-ONLY').exists())
        with self.assertRaises(FileExistsError):
            sb.prepare_test_keys(self.keys)

    def test_post_hook_failure_is_nonzero_with_no_unsigned_fallback(self):
        with patch.object(sb, 'POLICY', self.keys / 'policy.json'), patch.object(sb, 'UNSIGNED', self.uki):
            sb.main(['post-uki', '/boot/vmlinuz-linux', '', str(self.uki)])
            with self.assertRaisesRegex(ValueError, 'candidate or incomplete'):
                sb.main(['post-uki', '/boot/vmlinuz-linux', '', str(self.uki)])
        # The installed shell hook uses exec, preserving the helper's failure code.
        hook = (ROOT / 'distro/installed/secure-boot/95-astraeus-sign').read_text()
        failed = subprocess.run(['sh', '-c', hook.replace('/usr/bin/astraeus-secure-boot', '/usr/bin/false')])
        self.assertNotEqual(failed.returncode, 0)


if __name__ == '__main__':
    unittest.main()
