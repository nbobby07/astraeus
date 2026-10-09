import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/validate'))
import phase2
import phase3
import phase3_guest


def signature_list(cert=b'test-certificate'):
    return phase3.X509 + struct.pack('<III', 44 + len(cert), 0, 16 + len(cert)) + bytes(16) + cert


def transcript():
    data = signature_list().hex()
    lines = ['SecureBoot 0000000000000000 00000006 01', 'SetupMode 0000000000000000 00000006 00']
    lines += [f'{name} 0000000000000000 00000027 {data}' for name in ['PK', 'KEK', 'db']]
    lines += ['trusted LOAD 0000000000000000', 'PAYLOAD_EXECUTED', 'trusted START 0000000000000000']
    for name in ['unsigned', 'untrusted', 'tampered']:
        lines += [f'{name} LOAD {phase3.REFUSED}',
                  f'DENIED_IMAGE {"00000000" if name == "unsigned" else "00000003"} PciRoot/\\EFI\\tests\\{name}.efi']
    lines += ['COMPLETE']
    return '\n'.join('P3 nonce ' + line for line in lines)


def pe_image():
    data = bytearray(8192)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<H', data, 70, 1)
    struct.pack_into('<H', data, 84, 0)
    data[88:96] = b'.linux\0\0'
    struct.pack_into('<II', data, 104, 4096, 4096)
    return data


class Phase3Tests(unittest.TestCase):
    def test_launch_reuses_harness_and_enforces_smm_and_flash(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = phase2.VM(Path(temp), Path('code'), None, 10, secure_boot=True)
            with patch.object(phase2.subprocess, 'Popen') as popen:
                popen.return_value.pid = 42
                vm.start()
            command = popen.call_args.args[0]
            self.assertIn('q35,accel=kvm,smm=on', command)
            self.assertIn('driver=cfi.pflash01,property=secure,value=on', command)
            self.assertNotIn('-daemonize', command)
            self.assertFalse(any('installiso' in arg for arg in command))

    def test_real_refusal_predicate_requires_status_and_authentication_record(self):
        result = phase3.firmware_result(transcript(), 'nonce', b'test-certificate')
        self.assertTrue(result['trusted']['executed'])
        self.assertFalse(result['unsigned']['executed'])
        for replacement in ['0000000000000000', '800000000000000e', '8000000000000003']:
            with self.subTest(replacement=replacement), self.assertRaises(RuntimeError):
                phase3.firmware_result(transcript().replace(phase3.REFUSED, replacement), 'nonce', b'test-certificate')
        with self.assertRaisesRegex(RuntimeError, 'authentication refusal'):
            phase3.firmware_result(transcript().replace('DENIED_IMAGE 00000003', 'DENIED_IMAGE 00000005'),
                                   'nonce', b'test-certificate')

    def test_disabled_enforcement_wrong_keys_and_replayed_markers_fail(self):
        for text, nonce, cert in [
            (transcript().replace('00000006 01', '00000006 00'), 'nonce', b'test-certificate'),
            (transcript().replace('SetupMode 0000000000000000 00000006 00',
                                  'SetupMode 0000000000000000 00000006 01'), 'nonce', b'test-certificate'),
            (transcript(), 'nonce', b'wrong-certificate'),
            (transcript(), 'other-run', b'test-certificate'),
            (transcript() + '\nP3 nonce COMPLETE', 'nonce', b'test-certificate'),
            (transcript() + '\nP3 nonce unsigned START 0000000000000000', 'nonce', b'test-certificate'),
            (transcript() + '\nP3 nonce PAYLOAD_EXECUTED', 'nonce', b'test-certificate'),
        ]:
            with self.subTest(text=text[-80:]), self.assertRaises(RuntimeError):
                phase3.firmware_result(text, nonce, cert)

    def test_signature_list_rejects_extra_trust_and_malformed_lengths(self):
        self.assertEqual(phase3.signature_certificates(signature_list()), [b'test-certificate'])
        for data in [b'', signature_list() + signature_list(b'other')]:
            self.assertNotEqual(phase3.signature_certificates(data), [b'test-certificate'])
        for data in [signature_list()[:20], signature_list()[:-1], bytes(28)]:
            with self.assertRaises(RuntimeError):
                phase3.signature_certificates(data)

    def test_tampering_changes_section_bytes_and_retains_pe_structure(self):
        data = pe_image()
        self.assertEqual(phase3.section_offset(data, b'.linux'), 4096)
        damaged = copy.copy(data)
        damaged[phase3.section_offset(data, b'.linux')] ^= 1
        self.assertEqual(damaged[:4096], data[:4096])
        self.assertEqual(sum(a != b for a, b in zip(data, damaged)), 1)
        for bad in [b'not PE', data[:100], data[:8191]]:
            with self.assertRaises(RuntimeError):
                phase3.section_offset(bad, b'.linux')
        with self.assertRaisesRegex(RuntimeError, 'missing signed section'):
            phase3.section_offset(data, b'.cmdline')

    def test_faults_are_guarded_and_record_exact_artifact_changes(self):
        for kind in ['tampered', 'missing', 'partial-esp-write']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'uki.efi'
                path.write_bytes(pe_image())
                with patch.object(phase3_guest, 'guard') as guard, \
                     patch.object(phase3_guest, 'uki_path', return_value=path), \
                     patch.object(phase3_guest.os, 'sync', create=True), \
                     patch.object(phase3_guest.Path, 'write_text') as log, \
                     patch('builtins.print'):
                    phase3_guest.fault(kind, path)
                guard.assert_called_once()
                receipt = json.loads(log.call_args.args[0])
                self.assertEqual(receipt['fault'], kind)
                self.assertTrue(receipt['injected'])
                if kind == 'missing':
                    self.assertFalse(path.exists())
                    self.assertIsNone(receipt['after_sha256'])
                elif kind == 'partial-esp-write':
                    self.assertEqual(path.stat().st_size, 4096)
                else:
                    self.assertEqual(path.read_bytes()[4096], 1)
                self.assertNotEqual(receipt['before_sha256'], receipt['after_sha256'])

    def test_guard_refusal_prevents_artifact_access(self):
        with patch.object(phase3_guest, 'guard', side_effect=RuntimeError('not disposable')), \
             patch.object(phase3_guest, 'uki_path') as target:
            with self.assertRaisesRegex(RuntimeError, 'not disposable'):
                phase3_guest.fault('tampered', Path('host.efi'))
            target.assert_not_called()

    def test_changed_baseline_or_firmware_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for name in ['disk.qcow2', 'vars.fd', 'code.fd']:
                (base / name).write_bytes(name.encode())
            manifest = dict(accepted=True, kind='phase3-firmware-fixture', public_sha256={},
                            sha256={n: phase2.digest(base / n) for n in ['disk.qcow2', 'vars.fd']},
                            ovmf_code=dict(sha256=phase2.digest(base / 'code.fd')))
            phase2.save(base / 'baseline.json', manifest)
            phase3.verify_inputs(base, base / 'code.fd')
            (base / 'code.fd').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'CODE changed'):
                phase3.verify_inputs(base, base / 'code.fd')
            (base / 'disk.qcow2').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'baseline changed'):
                phase3.verify_inputs(base, base / 'code.fd')

    def test_host_command_records_actual_failure_and_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            result = Mock(returncode=7, stdout='', stderr='failure')
            with patch.object(phase3.subprocess, 'run', return_value=result), \
                 self.assertRaisesRegex(RuntimeError, 'exit 7'):
                phase3.execute(out, ['false'])
            self.assertEqual(json.loads((out / 'host-001.json').read_text())['code'], 7)
            with patch.object(phase3.subprocess, 'run', side_effect=phase3.subprocess.TimeoutExpired('cmd', 1)), \
                 self.assertRaises(phase3.subprocess.TimeoutExpired):
                phase3.execute(out, ['cmd'], timeout=1)
            record = json.loads((out / 'host-002.json').read_text())
            self.assertIsNone(record['code'])
            self.assertEqual(record['error'], 'timeout after 1s')

    def test_load_only_probe_cannot_claim_payload_execution(self):
        text = '\n'.join(line for line in transcript().splitlines() if 'PAYLOAD_EXECUTED' not in line and ' START ' not in line)
        result = phase3.firmware_result(text, 'nonce', b'test-certificate', load_only=True)
        self.assertFalse(result['trusted']['executed'])
        with self.assertRaises(RuntimeError):
            phase3.firmware_result(text, 'nonce', b'test-certificate')

    def test_power_cut_requires_matching_blocked_product_barrier_and_records_exit(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(phase3.signal, 'SIGKILL', 9, create=True):
            vm = Mock(timeout=1, boot_id='current', session=Path(temp))
            root_uuid = 'f15dfa26-1d54-46f0-9df9-49d5983fe6b8'
            identities = ('B', root_uuid, 'a' * 64)
            barrier = dict(checkpoint='uki-staging', boot_id='current', generation='B', root_uuid=root_uuid,
                           uki_sha256='a' * 64, blocked=True)
            vm.command.return_value = dict(code=0, output=json.dumps(barrier))
            vm.child.wait.return_value = -9
            phase3.cut_at_barrier(vm, 'uki-staging', *identities)
            vm.child.kill.assert_called_once()
            self.assertEqual(json.loads((Path(temp) / 'powercut.json').read_text())['code'], -9)
            for changed in [dict(boot_id='stale'), dict(blocked=False), dict(checkpoint='health-confirmation'),
                            dict(generation='A'), dict(root_uuid='other-root'), dict(uki_sha256='b' * 64)]:
                vm.child.kill.reset_mock()
                vm.command.return_value = dict(code=0, output=json.dumps(barrier | changed))
                with self.assertRaisesRegex(RuntimeError, 'invalid or stale'):
                    phase3.cut_at_barrier(vm, 'uki-staging', *identities)
                vm.child.kill.assert_not_called()
            vm.command.return_value = dict(code=77, error=None, output='unsupported')
            with self.assertRaisesRegex(RuntimeError, 'inspection failed'):
                phase3.cut_at_barrier(vm, 'uki-staging', *identities)
            vm.child.kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
