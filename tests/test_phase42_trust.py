"""Public image-trust contract checks; not firmware or installed-VM acceptance."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/validate'))
import phase42_trust as trust

PIN = 'd' * 64
HASH = 'e' * 64


def security(path='/efi/EFI/Astraeus/maintenance.efi'):
    return {'schema_version': 1, 'policy': 'configured', 'identity': 'valid', 'certificate_sha256': PIN,
            'signing_key_present': False, 'enrollment_readiness': 'not-ready',
            'firmware': {'SecureBoot': True, 'SetupMode': False, 'AuditMode': None,
                         'db': {'contains_signer_certificate': True},
                         'dbx': {'contains_signer_certificate': False, 'empty': False,
                                 'sha256_images': ['e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855']}},
            'artifacts': {'uki': {'path': path, 'sha256': HASH, 'signature': 'valid-for-configured-certificate'},
                          'running_uki': {'path': None, 'sha256': None, 'signature': 'unavailable'}}}


def verdict():
    return {'schema_version': 1, 'sha256': HASH, 'signature_verified': True, 'firmware_trusted': True}


def ready():
    return {'schema_version': 1, 'systemd_version': 262, 'loader_verified': True, 'firmware_trusted': True}


class Phase42Trust(unittest.TestCase):
    def test_public_guard_verifies_observed_maintained_image_without_requiring_signing_key_or_running_generation(self):
        for path in ['/efi/EFI/Linux/astraeus-dev-linux.efi', '/efi/EFI/Astraeus/maintenance.efi']:
            with self.subTest(path=path):
                command = Mock(side_effect=[json.dumps(security(path)), json.dumps(verdict())])
                result = trust.verify_maintained_uki(command, PIN)
                self.assertEqual(result['scope'], 'maintained-installed-uki')
                self.assertEqual(result['path'], path)
                self.assertFalse(result['provider_readiness_checked'])
                self.assertEqual([call.args for call in command.call_args_list],
                                 [('astraeus-secure-boot', 'status', '--json'), ('astraeus-boot-artifact', 'verify', path)])

    def test_baseline_requires_valid_ready_result_as_well_as_image_verdict(self):
        command = Mock(side_effect=[json.dumps(security()), json.dumps(ready()), json.dumps(verdict())])
        self.assertTrue(trust.verify_maintained_uki(command, PIN, require_ready=True)['provider_readiness_checked'])
        self.assertEqual(command.call_args_list[1].args, ('astraeus-boot-artifact', 'ready', '/efi'))
        for field, value in [('schema_version', True), ('systemd_version', 261), ('loader_verified', False),
                             ('firmware_trusted', 1), ('unknown', True)]:
            with self.subTest(field=field):
                command = Mock(side_effect=[json.dumps(security()), json.dumps(dict(ready(), **{field: value}))])
                with self.assertRaises(RuntimeError):
                    trust.verify_maintained_uki(command, PIN, require_ready=True)
                self.assertEqual(command.call_count, 2)

    def test_bad_security_identity_enforcement_and_paths_are_rejected_before_provider_verification(self):
        cases = [(('schema_version',), True), (('schema_version',), 2), (('certificate_sha256',), 'f' * 64),
                 (('policy',), 'invalid-or-unavailable'), (('identity',), 'unavailable'),
                 (('firmware',), []), (('firmware', 'SecureBoot'), False), (('firmware', 'SecureBoot'), 1),
                 (('firmware', 'SetupMode'), True), (('firmware', 'AuditMode'), True), (('firmware', 'AuditMode'), 0),
                 (('firmware', 'db'), {}), (('firmware', 'dbx'), {}),
                 (('firmware', 'dbx', 'contains_signer_certificate'), True), (('artifacts',), []),
                 (('artifacts', 'uki'), None), (('artifacts', 'uki', 'signature'), 'invalid-or-unavailable'),
                 (('artifacts', 'uki', 'sha256'), 'f' * 63)]
        cases += [(('artifacts', 'uki', 'path'), path) for path in [None, '/tmp/approved.efi',
                  '/efi/EFI/Linux/../other-linux.efi', '/efi//EFI/Linux/astraeus-dev-linux.efi',
                  '/efi/EFI/Astraeus/1-2-3.efi', '/efi/EFI/Linux/$(id)-linux.efi', 'C:/efi/test.efi']]
        for keys, value in cases:
            with self.subTest(keys=keys, value=value):
                status = security()
                nested = status
                for key in keys[:-1]:
                    nested = nested[key]
                nested[keys[-1]] = value
                command = Mock(return_value=json.dumps(status))
                with self.assertRaises(RuntimeError):
                    trust.verify_maintained_uki(command, PIN)
                self.assertEqual(command.call_count, 1)

    def test_bad_verdicts_and_revocation_errors_cannot_pass_on_command_success_alone(self):
        for field, value in [('schema_version', True), ('schema_version', 2), ('sha256', 'f' * 64),
                             ('signature_verified', False), ('signature_verified', 1),
                             ('firmware_trusted', False), ('firmware_trusted', None), ('revoked', True)]:
            with self.subTest(field=field, value=value):
                command = Mock(side_effect=[json.dumps(security()), json.dumps(dict(verdict(), **{field: value}))])
                with self.assertRaises(RuntimeError):
                    trust.verify_maintained_uki(command, PIN)
        command = Mock(side_effect=[json.dumps(security()), RuntimeError('image is revoked by firmware dbx')])
        with self.assertRaisesRegex(RuntimeError, 'image is revoked'):
            trust.verify_maintained_uki(command, PIN)

    def test_malformed_duplicate_or_missing_provider_json_fails_closed(self):
        for text in ['', '{', '[]', 'null', 'true', '{"schema_version":1,"schema_version":1}',
                     '{"schema_version":1,"ignored":NaN}', '{}', ' ' * (1024 * 1024 + 1)]:
            for stage in ['status', 'verdict']:
                with self.subTest(text=text[:64], stage=stage):
                    command = Mock(side_effect=[text] if stage == 'status' else [json.dumps(security()), text])
                    with self.assertRaises(RuntimeError):
                        trust.verify_maintained_uki(command, PIN)


if __name__ == '__main__':
    unittest.main()
