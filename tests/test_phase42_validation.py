"""Evidence-adapter tests. No mock result is installed-OS acceptance."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/validate'))
import phase42


class Phase42Validation(unittest.TestCase):
    def test_matrix_does_not_claim_unrun_or_other_target_gates(self):
        result = phase42.matrix()
        self.assertFalse(result['qualified'])
        self.assertFalse(result['physical_hardware_qualified'])
        self.assertTrue(all(row['status'] == 'NOT RUN' for row in result['scenarios']))
        for name in ['fresh-install-plain', 'fresh-install-luks2', 'gui-polkit', 'gui-crash-survival',
                     'offline-recovery', 'signed-boot-generations', 'image-reproducibility']:
            self.assertIn(name, {row['id'] for row in result['scenarios']})

    def test_candidate_guard_rejects_older_source_iso_and_wrong_encryption(self):
        manifest = {'accepted': True, 'encryption': 'none', 'inputs': {
            'source_commits': ['a' * 40], 'iso': {'sha256': 'b' * 64}, 'ovmf_code': {'sha256': 'c' * 64}}}
        phase42.candidate_matches(manifest, 'a' * 40, 'b' * 64, 'c' * 64, 'none')
        for source, image, code, encryption in [('d' * 40, 'b' * 64, 'c' * 64, 'none'),
                                                ('a' * 40, 'd' * 64, 'c' * 64, 'none'),
                                                ('a' * 40, 'b' * 64, 'd' * 64, 'none'),
                                                ('a' * 40, 'b' * 64, 'c' * 64, 'LUKS2')]:
            with self.assertRaises(RuntimeError):
                phase42.candidate_matches(manifest, source, image, code, encryption)

    def test_guest_request_is_quoted_and_keeps_legacy_arrays(self):
        vm = Mock()
        vm.command.return_value = {'code': 0, 'output': json.dumps({'schema_version': 1})}
        phase42.json_command(vm, ['system', 'parse', '--stdin', '--json'], "text='$(touch /bad)'", 'tester')
        command = vm.command.call_args.args[0]
        self.assertIn("printf '%s'", command)
        self.assertIn('/usr/bin/runuser -u tester -- /usr/bin/distroctl', command)
        self.assertIn("'\"'\"'", command)
        vm.command.return_value = {'code': 0, 'output': '[]'}
        self.assertEqual(phase42.json_command(vm, ['history', '--json'])[1], [])
        self.assertEqual(phase42.json_command(vm, ['snapshot', 'list', '--json'])[1], [])
        with self.assertRaises(RuntimeError):
            phase42.json_command(vm, ['system', 'status', '--json'])

    def test_snapshot_must_precede_real_package_mutation(self):
        record = {'state': 'awaiting_boot', 'snapshot': 'pre', 'post_snapshot': 'post', 'boot_regenerated': True,
                  'events': [{'state': 'snapshot_created'}, {'state': 'applying'}],
                  'plan': {'management': {'after': {}}, 'packages': {'changes': [{'kind': 'install', 'name': 'hello'}]}}}
        phase42.check_transaction(record, 'install', 'hello')
        record['events'].reverse()
        with self.assertRaisesRegex(RuntimeError, 'snapshot'):
            phase42.check_transaction(record, 'install', 'hello')
        record['events'].reverse()
        record['state'] = 'succeeded'
        with self.assertRaisesRegex(RuntimeError, 'awaiting boot'):
            phase42.check_transaction(record, 'install', 'hello')

    def test_matrix_command_refuses_to_overwrite_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'matrix.json'
            command = [sys.executable, str(ROOT / 'scripts/validate/phase42.py'), 'matrix', '--output', str(output)]
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(json.loads(output.read_text())['schema_version'], 1)
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
