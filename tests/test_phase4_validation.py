import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/validate'))
import phase4

if sys.platform == 'linux':
    import phase4_guest as guest


class MatrixTests(unittest.TestCase):
    def test_matrix_never_passes_unexecuted_scenarios(self):
        result = phase4.matrix()
        self.assertEqual([r['id'] for r in result['scenarios']], list('ABCDEFGHIJKLMNOP'))
        for row in result['scenarios']:
            self.assertEqual(row['status'], 'NOT RUN')
            self.assertTrue(set(['expected_behavior', 'actual_result', 'environment', 'relevant_hardware',
                                 'evidence_path', 'exit_code', 'status']) <= set(row))
        self.assertFalse(result['gaming_validated'])
        self.assertFalse(result['physical_gpu_qualified'])

    def test_packages_and_enumeration_do_not_pass_execution(self):
        rows = {r['id']: r for r in phase4.matrix(checks={
            'gaming-packages': dict(status='PASS', code=0), 'dependencies': dict(status='PASS', code=0),
            'vulkan-enumeration': dict(status='PASS', code=0)})['scenarios']}
        self.assertEqual(rows['B']['status'], 'PASS')
        self.assertEqual(rows['D']['status'], 'NOT RUN')
        self.assertEqual(rows['E']['status'], 'NOT RUN')
        self.assertEqual(rows['P']['status'], 'NOT RUN')

    def test_failures_and_partial_results_remain_visible(self):
        result = phase4.matrix(checks={'vulkan-64': dict(status='FAIL', code=1, output='No ICD')})
        row = result['scenarios'][3]
        self.assertEqual(row['status'], 'FAIL')
        self.assertEqual(row['exit_code']['vulkan-64'], 1)
        self.assertEqual(row['actual_result']['vulkan-64']['detail'], 'No ICD')
        with self.assertRaisesRegex(RuntimeError, 'unknown result'):
            phase4.matrix(checks={'vulkan-64': dict(status='UNVERIFIED')})

    def test_hooks_require_exact_exit_and_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'hooks.json'
            vm = Mock()
            path.write_text(json.dumps({'missing-steam': dict(command='guest-only', exit_code=2, marker='Steam absent')}))
            vm.command.return_value = dict(code=2, output='Steam absent')
            self.assertEqual(phase4.hooks(vm, path)['missing-steam']['status'], 'PASS')
            vm.command.return_value = dict(code=139, output='Steam absent')
            self.assertEqual(phase4.hooks(vm, path)['missing-steam']['status'], 'FAIL')
            path.write_text(json.dumps({'missing-steam': dict(command='guest-only', exit_code=139, marker='Steam absent')}))
            with self.assertRaises(RuntimeError):
                phase4.hooks(vm, path)
            path.write_text(json.dumps({'invented': {}}))
            with self.assertRaises(RuntimeError):
                phase4.hooks(vm, path)

    def test_matrix_cli_exclusive_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'matrix.json'
            cmd = [sys.executable, str(ROOT / 'scripts/validate/phase4.py'), 'matrix', '--output', str(path)]
            subprocess.run(cmd, check=True, capture_output=True)
            self.assertEqual(json.loads(path.read_text())['schema_version'], 1)
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)


@unittest.skipUnless(sys.platform == 'linux', 'Linux process groups and desktop users')
class GuestTests(unittest.TestCase):
    def test_real_command_timeout_exit_and_output_limit(self):
        self.assertEqual(guest.execute(['bash', '-c', 'exit 7'])['code'], 7)
        self.assertEqual(guest.execute(['bash', '-c', 'sleep 10'], timeout=0.1)['error'], 'timeout')
        with patch.object(guest.p2guest, 'LIMIT', 20):
            self.assertEqual(guest.execute(['bash', '-c', 'printf %100s x'])['error'], 'output limit')
        self.assertEqual(guest.execute(['/no/such/executable'])['code'], 127)

    def test_software_device_never_qualifies_physical_gpu(self):
        for text in ['renderer=llvmpipe (LLVM)\ndevice_type=4', 'renderer=lavapipe', 'renderer=Software']:
            self.assertTrue(guest.renderer(text)['software'])
            self.assertFalse(guest.renderer(text)['physical_qualified'])
        self.assertFalse(guest.renderer('renderer=NVIDIA RTX 5070\ndevice_type=2')['physical_qualified'])
        self.assertEqual(guest.gpu_classification('00:01 VGA compatible controller: Red Hat Virtio GPU')['classification'], 'virtual')
        self.assertEqual(guest.gpu_classification('00:01 VGA compatible controller: NVIDIA')['classification'], 'unqualified')
        self.assertEqual(guest.gpu_classification('')['classification'], 'unqualified')

    def test_runtime_needs_marker_exit_architecture_and_no_timeout(self):
        reply = dict(code=0, output='PHASE4_VULKAN_OK pixels=256\narchitecture_bits=64', error=None)
        self.assertEqual(guest.verdict(reply, 'PHASE4_VULKAN_OK pixels=256', 64), 'PASS')
        self.assertEqual(guest.verdict(reply, 'PHASE4_VULKAN_OK pixels=256', 32), 'FAIL')
        self.assertEqual(guest.verdict({**reply, 'error': 'timeout'}), 'FAIL')
        self.assertEqual(guest.verdict({**reply, 'code': 1}), 'FAIL')
        self.assertEqual(guest.verdict({**reply, 'output': ''}, 'PHASE4_VULKAN_OK pixels=256'), 'FAIL')

    def test_no_root_desktop(self):
        with self.assertRaises(ValueError):
            guest.session('root')


if __name__ == '__main__':
    unittest.main()
