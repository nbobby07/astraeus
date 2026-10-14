"""Fresh-install adapter boundary tests; these are not VM acceptance evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/validate'))
spec = importlib.util.spec_from_file_location('phase42_baseline', ROOT / 'scripts/validate/phase42-baseline.py')
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
import phase42


def config():
    return dict(schema_version=1, source_commit='a' * 40, image_sha256='b' * 64,
                distroctl_sha256='c' * 64, desktop_sha256='d' * 64,
                certificate_sha256='e' * 64, serial='AS42' + 'f' * 16, encryption='LUKS2', user='tester')


class FreshCandidateBaseline(unittest.TestCase):
    def test_install_intent_rejects_ambiguous_or_unsafe_identity(self):
        baseline.configuration(config())
        for field, value in [('schema_version', True), ('schema_version', 2), ('source_commit', 'a' * 12),
                             ('image_sha256', None), ('serial', 'vda'), ('serial', 'AS42' + 'f' * 17),
                             ('encryption', 'luks1'), ('user', 'root'), ('user', 'live'), ('user', 'name;id')]:
            invalid = config()
            invalid[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                baseline.configuration(invalid)
        invalid = config()
        invalid['disk'] = '/dev/nvme0n1'
        with self.assertRaises(RuntimeError):
            baseline.configuration(invalid)

    def test_only_exact_blank_serial_pinned_disk_can_be_partitioned(self):
        serial = config()['serial']
        disk = dict(path='/dev/vda', type='disk', size=baseline.DISK_BYTES, serial=serial, mountpoints=[None])
        baseline.blank_disk({'blockdevices': [disk]}, {'signatures': []}, serial)
        for field, value in [('path', '/dev/sda'), ('type', 'part'), ('size', baseline.DISK_BYTES - 1),
                             ('serial', 'AS42' + '0' * 16), ('mountpoints', ['/']), ('mountpoints', None),
                             ('children', [{'path': '/dev/vda1'}])]:
            invalid = dict(disk, **{field: value})
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                baseline.blank_disk({'blockdevices': [invalid]}, {'signatures': []}, serial)
        for signatures in [{}, {'signatures': [{'type': 'gpt'}]}, {'signatures': None}]:
            with self.assertRaises(RuntimeError):
                baseline.blank_disk({'blockdevices': [disk]}, signatures, serial)
        for disks in [[], [disk, disk]]:
            with self.assertRaises(RuntimeError):
                baseline.blank_disk({'blockdevices': disks}, {'signatures': []}, serial)

    def test_disk_guard_failure_precedes_every_mutating_command(self):
        commands = []

        def observed(*args, **_kwargs):
            commands.append(args)
            if args[0] == 'blockdev':
                return '0'
            if args[0] == 'lsblk':
                return json.dumps({'blockdevices': [{'path': '/dev/sda'}]})
            if args[0] == 'wipefs':
                return '{"signatures":[]}'
            self.fail('mutation reached before disk validation: ' + repr(args))

        with patch.object(baseline, 'guest_guard', return_value=config()), patch.object(baseline, 'run', side_effect=observed):
            with self.assertRaises(RuntimeError):
                baseline.guest_install()
        self.assertEqual([command[0] for command in commands], ['blockdev', 'lsblk', 'wipefs'])

    def test_secure_boot_requires_observed_enforcement_and_matching_enrollment(self):
        status = {'certificate_sha256': 'e' * 64, 'firmware': {'SecureBoot': True, 'SetupMode': False,
                  'AuditMode': False, 'db': {'contains_signer_certificate': True},
                  'dbx': {'contains_signer_certificate': False}}}
        baseline.enforced(status, 'e' * 64)
        for field, value in [('SecureBoot', False), ('SecureBoot', None), ('SetupMode', True),
                             ('SetupMode', None), ('AuditMode', True), ('db', {}),
                             ('dbx', {'contains_signer_certificate': True}), ('dbx', {})]:
            invalid = copy.deepcopy(status)
            invalid['firmware'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                baseline.enforced(invalid, 'e' * 64)
        with self.assertRaises(RuntimeError):
            baseline.enforced(status, 'f' * 64)

    def test_initial_firmware_is_read_from_real_variable_bytes_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(baseline, 'EFIVARS', Path(directory)), \
                patch.object(baseline, 'run', return_value='efivarfs'):
            paths = {name: Path(directory) / (name + '-' + baseline.EFI_GLOBAL_GUID)
                     for name in ('SecureBoot', 'SetupMode')}
            values = {'SecureBoot': b'\x07\0\0\0\0', 'SetupMode': b'\x07\0\0\0\x01'}
            for name, value in values.items():
                paths[name].write_bytes(value)
            observed = baseline.installation_firmware()
            self.assertEqual(observed, {'SecureBoot': False, 'SetupMode': True, 'observed': True,
                                        'source': 'efivarfs-before-partition-write'})
            self.assertEqual(baseline.MANAGEMENT_FIRMWARE, {'SecureBoot': True, 'SetupMode': False})
            for name in paths:
                for invalid in (b'', b'\x01', b'\x07\0\0\0\x02', values[name] + b'\0',
                                values[name][:4] + bytes([1 - values[name][4]])):
                    paths[name].write_bytes(invalid)
                    with self.subTest(name=name, invalid=invalid), self.assertRaises(RuntimeError):
                        baseline.installation_firmware()
                paths[name].unlink()
                with self.assertRaisesRegex(RuntimeError, 'firmware variable ' + name + ' is absent'):
                    baseline.installation_firmware()
                paths[name].write_bytes(values[name])

    def test_initial_firmware_requires_readable_efivarfs_without_mounting_or_inventing_values(self):
        for filesystem in ('tmpfs', 'sysfs', ''):
            with self.subTest(filesystem=filesystem), patch.object(baseline, 'run', return_value=filesystem) as command, \
                    patch.object(Path, 'read_bytes') as read:
                with self.assertRaisesRegex(RuntimeError, 'requires mounted efivarfs'):
                    baseline.installation_firmware()
                read.assert_not_called()
                command.assert_called_once_with('findmnt', '-rn', '-M', baseline.EFIVARS, '-o', 'FSTYPE', timeout=10)
        with patch.object(baseline, 'run', side_effect=RuntimeError('findmnt exited 1')), \
                patch.object(Path, 'read_bytes') as read:
            with self.assertRaisesRegex(RuntimeError, 'cannot inspect efivarfs mount'):
                baseline.installation_firmware()
            read.assert_not_called()
        with patch.object(baseline, 'run', return_value='efivarfs'), \
                patch.object(Path, 'read_bytes', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(RuntimeError, 'cannot read initial firmware variable: SecureBoot'):
                baseline.installation_firmware()

    def test_bootstrap_rejects_different_firmware_before_writes_and_requests_smm_for_matching_code(self):
        p2 = phase42.p2
        exists = Path.exists
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            paths = {name: root / name for name in ('iso', 'code', 'setup', 'vars')}
            for name, path in paths.items():
                path.write_bytes(name.encode())
            args = SimpleNamespace(output=root / 'out', private_directory=root / 'private',
                iso=paths['iso'], ovmf_code=paths['code'], setup_ovmf_code=paths['setup'], ovmf_vars=paths['vars'],
                source_commit='a' * 40, image_sha256=baseline.sha256(paths['iso']), distroctl_sha256='c' * 64,
                desktop_sha256='d' * 64, encryption='none', user='tester', timeout=60)

            def owner(private, public):
                baseline.write(private / 'db.key', 'non-key fixture', 0o600)
                baseline.write(public / 'db.crt', 'non-certificate fixture')
                return {'db': 'e' * 64}

            with patch.object(baseline.sys, 'platform', 'linux'), \
                    patch.object(baseline.os, 'geteuid', return_value=0, create=True), \
                    patch.object(baseline.shutil, 'which', return_value='fixture-tool'), \
                    patch.object(Path, 'exists', lambda path: True if path == Path('/dev/kvm') else exists(path)), \
                    patch.object(baseline, 'make_owner', side_effect=owner) as make_owner, \
                    patch.object(p2, 'host') as host, patch.object(p2, 'VM') as factory:
                with self.assertRaisesRegex(RuntimeError, 'same Secure Boot-capable OVMF code'):
                    baseline.host_run(args)
                self.assertFalse(args.output.exists())
                self.assertFalse(args.private_directory.exists())
                make_owner.assert_not_called()
                host.assert_not_called()
                factory.assert_not_called()
                paths['setup'].write_bytes(paths['code'].read_bytes())
                factory.return_value.start.side_effect = RuntimeError('stop before guest launch')
                with self.assertRaisesRegex(RuntimeError, 'stop before guest launch'):
                    baseline.host_run(args)
                factory.assert_called_once_with(args.output, paths['setup'], args.private_directory / 'share',
                                                args.timeout, secure_boot=True)
                self.assertEqual((args.output / 'vars.fd').read_bytes(), paths['vars'].read_bytes())
                factory.return_value.stop.assert_called_once_with()

    def test_firmware_refusal_precedes_every_partition_or_installation_write(self):
        commands = []
        serial = config()['serial']

        def observed(*args, **_kwargs):
            commands.append(args)
            if args[0] == 'blockdev':
                return '0'
            if args[0] == 'lsblk':
                return json.dumps({'blockdevices': [dict(path='/dev/vda', type='disk',
                                  size=baseline.DISK_BYTES, serial=serial, mountpoints=[None])]})
            if args[0] == 'wipefs':
                return '{"signatures":[]}'
            self.fail('mutation reached before firmware validation: ' + repr(args))

        with patch.object(baseline, 'guest_guard', return_value=config()), \
                patch.object(baseline, 'run', side_effect=observed), \
                patch.object(baseline, 'installation_firmware', side_effect=RuntimeError('firmware unavailable')) as firmware:
            with self.assertRaisesRegex(RuntimeError, 'firmware unavailable'):
                baseline.guest_install()
        firmware.assert_called_once_with()
        self.assertEqual([command[0] for command in commands], ['blockdev', 'lsblk', 'wipefs'])

    def test_credentials_only_travel_in_stdin(self):
        with patch.object(baseline.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as call:
            credential = b'a' * 48
            baseline.run('cryptsetup', 'open', '--key-file', '-', '/dev/vda2', 'root', data=credential)
            self.assertNotIn(credential.decode(), ' '.join(call.call_args.args[0]))
            self.assertEqual(call.call_args.kwargs['input'], credential)
        with tempfile.TemporaryDirectory() as directory, patch.object(baseline, 'SHARE', Path(directory)):
            password = Path(directory) / 'login-password'
            password.write_bytes(b'a' * 48)
            self.assertEqual(baseline.secret('login-password'), b'a' * 48)
            for invalid in [b'', b'a' * 100, b'a' * 48 + b'\n', b'a' * 47 + b';']:
                password.write_bytes(invalid)
                with self.assertRaises(RuntimeError):
                    baseline.secret('login-password')

    def test_desktop_smoke_keeps_private_share_inaccessible_to_user(self):
        source = (ROOT / 'tests/boot/installed-smoke.sh').read_bytes()
        marker = 'DISTRO_INSTALL_OK: uefi uki LUKS2 btrfs sddm plasma wayland network audio status'
        status = json.dumps({'configuration_available': True, 'drift': [],
                             'recovery_required': False, 'live': False})
        with tempfile.TemporaryDirectory() as directory, patch.object(baseline, 'SHARE', Path(directory)):
            (Path(directory) / 'installed-smoke.sh').write_bytes(source)
            with patch.object(baseline, 'guest_guard', return_value=config()), \
                    patch.object(baseline, 'desktop_environment', return_value={'USER': 'tester'}), \
                    patch.object(baseline, 'run', side_effect=[marker, status]) as command, \
                    patch.object(baseline, 'sha256', side_effect=['c' * 64, 'd' * 64]), \
                    patch.object(baseline, 'write'), patch('builtins.print'):
                baseline.guest_desktop(initial=True)
            smoke = command.call_args_list[0]
            self.assertEqual(smoke.args, ('runuser', '-u', 'tester', '--', 'env', 'USER=tester',
                                          'bash', '-s', '--', 'LUKS2'))
            self.assertEqual(smoke.kwargs['data'], source)
            self.assertNotIn(directory, ' '.join(smoke.args))

    def test_fresh_manifest_contract_is_consumable_without_claiming_calamares(self):
        manifest = {'accepted': True, 'kind': 'phase42-fresh-candidate-payload', 'calamares_ui': False,
                    'encryption': 'LUKS2', 'inputs': {'source_commits': ['a' * 40],
                    'iso': {'sha256': 'b' * 64}, 'ovmf_code': {'sha256': 'c' * 64}}}
        phase42.candidate_matches(manifest, 'a' * 40, 'b' * 64, 'c' * 64, 'LUKS2')
        self.assertFalse(manifest['calamares_ui'])
        manifest['accepted'] = False
        with self.assertRaises(RuntimeError):
            phase42.candidate_matches(manifest, 'a' * 40, 'b' * 64, 'c' * 64, 'LUKS2')

    def test_host_has_no_existing_disk_or_baseline_argument(self):
        help_text = subprocess.check_output([sys.executable, str(ROOT / 'scripts/validate/phase42-baseline.py'),
                                             'run', '--help'], text=True)
        for forbidden in ['--base ', '--disk ', '--installed-disk']:
            self.assertNotIn(forbidden, help_text)
        for required in ['--image-sha256', '--private-directory', '--source-commit', '--encryption']:
            self.assertIn(required, help_text)


if __name__ == '__main__':
    unittest.main()
