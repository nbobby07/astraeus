import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/validate'))
import phase4

if sys.platform == 'linux':
    import phase4_guest as guest
    import phase4_gamescope as gamescope
    import phase4_proton as proton


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
            vm.command.return_value = dict(code=2, output='Steam absent', error='timeout')
            self.assertEqual(phase4.hooks(vm, path)['missing-steam']['status'], 'FAIL')
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
    def test_gamemode_observation_is_read_only_and_keeps_missing_capability_explicit(self):
        user = guest.pwd.getpwuid(os.getuid()).pw_name
        before = guest.gamemode_settings(user)
        after = guest.gamemode_settings(user)
        self.assertEqual(before, after)
        self.assertEqual(before['cpu_governor'], 'PRESENT' if before['governor_paths'] else 'UNSUPPORTED')
        self.assertFalse(before['errors'])

    def test_proton_requires_the_fixture_child_exit_and_exact_window_lifecycle(self):
        log = ('1:0020:0024:trace:process:NtCreateUserProcess L"Z:\\windows-smoke.exe" pid 0040 tid 0044 handles 0x1/0x2\n'
               '2:0040:0044:trace:win:NtUserCreateWindowEx ex_style 0, window_name L"Astraeus Proton smoke"\n'
               '3:0040:0044:trace:win:NtUserCreateWindowEx hwnd 0x10 cs 0,0 320x160\n'
               '4:0040:0044:trace:win:NtUserCreateWindowEx created window 0x10\n'
               '5:0040:0044:trace:win:destroy_window 0x10\n'
               '6:0040:0044:trace:process:NtTerminateProcess handle 0xffffffffffffffff, exit_code 0, process_exiting 1.\n')
        self.assertTrue(proton.completion(log, 0)['verified'])
        self.assertFalse(proton.completion(log, 2)['verified'])
        self.assertFalse(proton.completion(log.replace('6:0040:', '6:0080:'), 0)['verified'])
        self.assertFalse(proton.completion(log + log, 0)['verified'])
        self.assertTrue(proton.window_lifecycle(log, '0040')['verified'])
        self.assertFalse(proton.window_lifecycle(log.replace('destroy_window 0x10', 'destroy_window 0x20'), '0040')['verified'])
        self.assertFalse(proton.window_lifecycle(log.replace('destroy_window 0x10', 'destroy_window 0x100'), '0040')['verified'])
        self.assertFalse(proton.window_lifecycle(log, '0080')['verified'])
        for path in ['/tmp/test&whoami', '/tmp/%PATH%', '/tmp/test name']:
            with self.assertRaises(ValueError):
                proton.windows_path(path)

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'probe must run unprivileged')
    def test_gamescope_cli_refusal_exits_and_never_starts_unsupported_device(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            document = {'Device Properties and Extensions': {'GPU0': {
                'VkPhysicalDeviceProperties': {'deviceName': 'controlled fixture'}, 'Device Extensions': {}}}}
            query = root / 'vulkaninfo'
            query.write_text('#!' + sys.executable + '\nimport pathlib,sys\n'
                             'pathlib.Path(sys.argv[2], "vulkaninfo.json").write_text(' + repr(json.dumps(document)) + ')\n')
            sentinel = root / 'launched'
            for name in ['gamescope', 'vkcube']:
                tool = root / name
                tool.write_text('#!' + sys.executable + '\nimport pathlib\npathlib.Path(' + repr(str(sentinel)) + ').touch()\n')
                tool.chmod(0o755)
            query.chmod(0o755)
            env = {**os.environ, 'PATH': str(root), 'WAYLAND_DISPLAY': 'controlled-fixture'}
            command = [sys.executable, str(ROOT / 'scripts/validate/phase4_gamescope.py')]
            for options, expected in [([], 77), (['--backend', 'drm'], 77), (['--bad-option'], 2)]:
                reply = subprocess.run(command + options, env=env, text=True, capture_output=True, timeout=10)
                self.assertEqual(reply.returncode, expected, reply.stderr)
                self.assertFalse(json.loads(reply.stdout)['launched'])
                self.assertFalse(sentinel.exists())
            (root / 'gamescope').unlink()
            reply = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(reply.returncode, 77)
            self.assertIn('Missing optional tool', json.loads(reply.stdout)['reason'])

    def test_gamescope_capabilities_do_not_invent_device_support(self):
        software = {'VkPhysicalDeviceProperties': {'deviceName': 'llvmpipe'}, 'Device Extensions': {}}
        hardware = {'VkPhysicalDeviceProperties': {'deviceName': 'test GPU'},
                    'Device Extensions': {'VK_EXT_physical_device_drm': {}},
                    'VkPhysicalDeviceDrmPropertiesEXT': {'hasRender': True}}
        def check(devices):
            return gamescope.capabilities({'Device Properties and Extensions': devices})
        self.assertEqual(check({'GPU0': software})['code'], 77)
        self.assertEqual(check({'GPU0': hardware})['code'], 0)
        self.assertEqual(check({'GPU0': software, 'GPU1': hardware})['code'], 77)
        hardware['VkPhysicalDeviceDrmPropertiesEXT']['hasRender'] = False
        self.assertEqual(check({'GPU0': hardware})['code'], 77)
        hardware['VkPhysicalDeviceDrmPropertiesEXT']['hasRender'] = 'false'
        with self.assertRaises(ValueError):
            check({'GPU0': hardware})
        with self.assertRaises(ValueError):
            check({})

    def test_gamescope_refuses_before_launch_and_keeps_query_crashes_failed(self):
        with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-test'}), \
                patch.object(gamescope.shutil, 'which', return_value=None), \
                patch.object(gamescope, 'execute') as execute:
            result = gamescope.smoke()
            self.assertEqual(result['code'], 77)
            self.assertIn('Missing optional tool', result['reason'])
            execute.assert_not_called()
            self.assertEqual(gamescope.smoke('drm')['code'], 77)
        with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-test'}), \
                patch.object(gamescope.shutil, 'which', return_value='/test/tool'), \
                patch.object(gamescope, 'execute', return_value=dict(code=134, error=None, output='aborted')):
            result = gamescope.smoke()
            self.assertEqual(result['status'], 'FAIL')
            self.assertEqual(result['query']['code'], 134)
            self.assertFalse(result['launched'])

    def test_session_preserves_xauthority_without_exporting_other_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'comm').write_text('plasmashell\n')
            (root / 'environ').write_bytes(b'XDG_SESSION_TYPE=wayland\0XDG_CURRENT_DESKTOP=KDE\0'
                b'DISPLAY=:0\0XAUTHORITY=/run/user/1000/xauth-test\0UNRELATED_SECRET=private\0')
            proc = MagicMock()
            proc.stat.return_value.st_uid = 1000
            proc.__truediv__.side_effect = lambda name: root / name
            directory = Mock()
            directory.glob.return_value = [proc]
            with patch.object(guest, 'Path', return_value=directory), \
                    patch.object(guest.pwd, 'getpwnam', return_value=Mock(pw_uid=1000)):
                command, environment = guest.session('tester')
            self.assertIn('XAUTHORITY=/run/user/1000/xauth-test', command)
            self.assertEqual(environment['XAUTHORITY'], '/run/user/1000/xauth-test')
            self.assertNotIn('UNRELATED_SECRET', environment)
            self.assertFalse(any('private' in value for value in command))

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
        self.assertEqual(guest.verdict({**reply, 'code': 127}), 'NOT RUN')
        self.assertEqual(guest.verdict({**reply, 'code': 77}), 'UNSUPPORTED')
        self.assertEqual(guest.verdict({**reply, 'output': ''}, 'PHASE4_VULKAN_OK pixels=256'), 'FAIL')

    def test_no_root_desktop(self):
        with self.assertRaises(ValueError):
            guest.session('root')


if __name__ == '__main__':
    unittest.main()
