import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/validate'))
import phase2
import qmp

spec = importlib.util.spec_from_file_location('phase2_guest', ROOT / 'scripts/validate/phase2-guest.py')
guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guest)


def evidence(value):
    return dict(code=0, error=None, output=json.dumps(value))


def transaction_evidence():
    before = dict(history=evidence([]), snapshots=evidence([]))
    record = dict(schema_version=1, id=7, state='awaiting_boot', outcome='awaiting_boot', snapshot='snap-7',
                  plan=dict(current=dict(packages={'fixture': '1-1'}), packages=dict(changes=[dict(kind='upgrade', name='fixture', to='2-1')])),
                  events=[dict(state=s) for s in ['planned', 'snapshot_created', 'applying', 'awaiting_boot']],
                  health_checks=[dict(required=True, status='pass')], boot_regenerated=True)
    snapshot = dict(id='snap-7', reason='pre-update', transaction_id='7', root=dict(read_only=True))
    after = dict(history=evidence([record]), snapshots=evidence([snapshot]), packages=dict(code=0, error=None, output='fixture 2-1'))
    return before, after


class ValidationTests(unittest.TestCase):
    def test_complete_success_and_rollback_scenarios_reject_lost_home_data(self):
        for scenario in ['update-success', 'rollback']:
            for lost_home in [False, True]:
                with self.subTest(scenario=scenario, lost_home=lost_home), tempfile.TemporaryDirectory() as temp:
                    before, changed = transaction_evidence()
                    before.update(root=dict(code=0, output='version-A'), packages=dict(code=0, output='fixture 1-1'))
                    changed['root'] = dict(code=0, output='version-B')
                    final = copy.deepcopy(changed)
                    record = json.loads(final['history']['output'])[0]
                    record['state'] = record['outcome'] = 'succeeded' if scenario == 'update-success' else 'rolled_back'
                    final['history'] = evidence([record])
                    if scenario == 'rollback':
                        final['root']['output'] = 'version-A'
                        final['packages']['output'] = 'fixture 1-1'
                    final['persistent'] = dict(code=0, output='token' if lost_home else 'token-after-snapshot')
                    vm = Mock(out=Path(temp))
                    vm.command.return_value = dict(code=0, output='version-A')
                    args = SimpleNamespace(scenario=scenario, encryption='LUKS2', iso=Path('recovery.iso'))
                    with patch.object(phase2, 'observe', side_effect=[before, changed, final, final]), \
                         patch.object(phase2, 'healthy'), \
                         patch.object(phase2.uuid, 'uuid4', return_value=SimpleNamespace(hex='token')), \
                         patch.object(phase2, 'adapter', return_value={'code': 0}) as adapter:
                        if lost_home:
                            with self.assertRaisesRegex(RuntimeError, 'sentinels'):
                                phase2.scenario(vm, args)
                            self.assertFalse(any(c.args[1] in ['confirm-boot', 'finalize-rollback'] for c in adapter.call_args_list))
                        else:
                            phase2.scenario(vm, args)
                            actions = [c.args[1] for c in adapter.call_args_list]
                            self.assertIn('confirm-boot' if scenario == 'update-success' else 'finalize-rollback', actions)
                            vm.shutdown.assert_called()

    def test_acceptance_requires_an_exact_complete_line(self):
        marker = 'DISTRO_INSTALL_OK: test'
        self.assertTrue(phase2.marker_present('log\n' + marker + '\n', marker))
        for text in ['echo ' + marker, marker + ' trailing', marker[:-1]]:
            self.assertFalse(phase2.marker_present(text, marker))

    def test_corrupt_or_unaccepted_baseline_refused_before_cloning(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for name in ['disk.qcow2', 'vars.fd']:
                (base / name).write_bytes(b'baseline')
            manifest = dict(accepted=True, sha256={name: phase2.digest(base / name) for name in ['disk.qcow2', 'vars.fd']})
            phase2.save(base / 'baseline.json', manifest)
            phase2.verify_baseline(base)
            (base / 'disk.qcow2').write_bytes(b'modified')
            with patch.object(phase2, 'host') as command:
                with self.assertRaisesRegex(RuntimeError, 'baseline changed'):
                    phase2.clone(base, base / 'run')
                command.assert_not_called()

    def test_clone_uses_backing_disk_and_copies_vars(self):
        with tempfile.TemporaryDirectory() as temp:
            base, out = Path(temp) / 'base', Path(temp) / 'run'
            base.mkdir()
            out.mkdir()
            (base / 'vars.fd').write_bytes(b'firmware')
            with patch.object(phase2, 'verify_baseline', return_value={'accepted': True}), patch.object(phase2, 'host') as run:
                phase2.clone(base, out)
            self.assertEqual(run.call_args.args[0], ['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', base / 'disk.qcow2', out / 'disk.qcow2'])
            (out / 'vars.fd').write_bytes(b'mutated')
            self.assertEqual((base / 'vars.fd').read_bytes(), b'firmware')

    def test_snapshot_and_transaction_gates_reject_false_success(self):
        before, after = transaction_evidence()
        self.assertEqual(phase2.transaction(before, after, ['awaiting_boot'])['id'], 7)
        mutations = [
            lambda r: r.update(state='succeeded'),
            lambda r: r.update(snapshot=None),
            lambda r: r['plan']['packages'].update(changes=[]),
            lambda r: r.update(events=[dict(state='applying'), dict(state='snapshot_created')]),
            lambda r: r.update(health_checks=[]),
            lambda r: r['health_checks'][0].update(status='unavailable'),
            lambda r: r.update(boot_regenerated=False),
        ]
        for mutation in mutations:
            broken = copy.deepcopy(after)
            records = json.loads(broken['history']['output'])
            mutation(records[0])
            broken['history'] = evidence(records)
            with self.assertRaises(RuntimeError):
                phase2.transaction(before, broken, ['awaiting_boot'])
        before['snapshots'] = copy.deepcopy(after['snapshots'])
        with self.assertRaisesRegex(RuntimeError, 'stale'):
            phase2.transaction(before, after, ['awaiting_boot'])

    def test_failed_probe_cannot_be_used_as_evidence(self):
        with self.assertRaisesRegex(RuntimeError, 'missing evidence'):
            phase2.value({'history': dict(code=77, error=None, output='[]')}, 'history', True)

    def test_package_mismatch_and_outcome_disagreement_fail(self):
        before, after = transaction_evidence()
        after['packages']['output'] = 'fixture 1-1'
        with self.assertRaisesRegex(RuntimeError, 'package'):
            phase2.transaction(before, after, ['awaiting_boot'])
        before, after = transaction_evidence()
        record = json.loads(after['history']['output'])[0]
        record['outcome'] = 'succeeded'
        after['history'] = evidence([record])
        with self.assertRaisesRegex(RuntimeError, 'outcome'):
            phase2.transaction(before, after, ['awaiting_boot'])

    def test_observation_keeps_other_artifacts_when_one_command_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Mock(out=Path(temp))
            def command(text, **kwargs):
                if text == 'pacman -Dk':
                    raise TimeoutError('database timeout')
                return dict(code=0, error=None, output='kept')
            vm.command.side_effect = command
            result = phase2.observe(vm, 'failure')
            self.assertIsNone(result['database']['code'])
            self.assertEqual(result['snapshots']['output'], 'kept')
            self.assertEqual(json.loads((Path(temp) / 'failure.json').read_text()), result)

    @unittest.skipIf(os.name == 'nt', 'guest process cleanup uses Linux process groups')
    def test_timeout_kills_the_child_group_before_delayed_side_effect(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / 'should-not-exist'
            result = guest.run(f'(sleep 0.3; touch {marker}) & wait', 0.05)
            self.assertEqual(result['error'], 'timeout')
            time.sleep(0.4)
            self.assertFalse(marker.exists())

    def test_qmp_events_and_deadline(self):
        self.assertEqual(qmp.reply(io.BytesIO(b'{"event":"RESET"}\n{"return":{}}\n')), {})
        with self.assertRaises(TimeoutError):
            qmp.reply(io.BytesIO(b'{"return":{}}\n'), time.monotonic() - 1)
        with self.assertRaises(RuntimeError):
            qmp.reply(io.BytesIO(b'{"error":{"desc":"failure"}}\n'))

    def test_launch_is_foreground_disk_only_and_readonly_share(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = phase2.VM(Path(temp), Path('code.fd'), Path('test-share'), 10)
            with patch.object(phase2.subprocess, 'Popen') as popen:
                popen.return_value.pid = 42
                vm.start()
                command = popen.call_args.args[0]
            self.assertNotIn('-daemonize', command)
            self.assertIn('-no-reboot', command)
            self.assertFalse(any('installiso' in arg for arg in command))
            self.assertIn('local,path=test-share,mount_tag=acceptance,security_model=none,readonly=on', command)

    def test_shutdown_timeout_and_cleanup_target_only_owned_process(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = phase2.VM(Path(temp), None, None, 10)
            vm.session, vm.monitor = Path(temp), Path(temp) / 'qmp.sock'
            vm.child = Mock()
            vm.child.poll.return_value = None
            vm.child.returncode = -9
            vm.child.wait.side_effect = [subprocess.TimeoutExpired('qemu', 60), subprocess.TimeoutExpired('qemu', 10), 0]
            with patch.object(qmp, 'execute', return_value={}):
                with self.assertRaises(subprocess.TimeoutExpired):
                    vm.shutdown()
            vm.stop()
            vm.child.terminate.assert_called_once()
            vm.child.kill.assert_called_once()
            self.assertFalse(json.loads((Path(temp) / 'shutdown.json').read_text())['graceful'])

    def test_reboot_requires_new_boot_identity(self):
        vm = phase2.VM(Path('.'), None, None, 1)
        vm.boot_id = 'same'
        vm.shutdown = vm.start = vm.ready = Mock()
        with self.assertRaisesRegex(RuntimeError, 'boot ID'):
            vm.reboot()

    def test_ready_timeout_never_passes(self):
        vm = phase2.VM(Path('.'), None, None, 0.01)
        vm.alive = Mock()
        vm.command = Mock(side_effect=socket.timeout())
        with self.assertRaises(TimeoutError):
            vm.ready()

    @unittest.skipIf(os.name == 'nt', 'guest execution requires Linux process groups and Bash')
    def test_guest_exit_timeout_output_limit_and_pipeline_failure(self):
        self.assertEqual(guest.run('printf hello', 2)['output'], 'hello')
        self.assertEqual(guest.run('exit 7', 2)['code'], 7)
        self.assertNotEqual(guest.run('false | cat', 2)['code'], 0)
        result = guest.run('sleep 10 & wait', 0.1)
        self.assertEqual(result['error'], 'timeout')
        self.assertNotEqual(result['code'], 0)
        with patch.object(guest, 'LIMIT', 100):
            result = guest.run('head -c 1000 /dev/zero', 2)
            self.assertEqual(result['error'], 'output limit')
            self.assertEqual(len(result['output']), 100)

    @unittest.skipIf(os.name == 'nt', 'Unix socket integration runs on Linux')
    def test_qmp_handshake_and_command_through_real_socket(self):
        with tempfile.TemporaryDirectory() as temp, socket.socket(socket.AF_UNIX) as server:
            path = str(Path(temp) / 'qmp.sock')
            server.bind(path)
            server.listen()
            server.settimeout(3)
            requests, errors = [], []
            def respond():
                try:
                    connection, _ = server.accept()
                    connection.settimeout(3)
                    with connection, connection.makefile('rb') as stream:
                        connection.sendall(b'{"QMP":{}}\n')
                        for response in [{}, {'status': 'running'}]:
                            requests.append(json.loads(stream.readline()))
                            connection.sendall(b'{"event":"RESUME"}\n' + json.dumps({'return': response}).encode() + b'\n')
                except Exception as error:
                    errors.append(str(error))
            thread = threading.Thread(target=respond, daemon=True)
            thread.start()
            self.assertEqual(qmp.execute(path, {'execute': 'query-status'}), {'status': 'running'})
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(requests, [{'execute': 'qmp_capabilities'}, {'execute': 'query-status'}])

    @unittest.skipIf(os.name == 'nt', 'Unix socket integration runs on Linux')
    def test_real_guest_channel_correlates_reply_and_preserves_failure_output(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = phase2.VM(Path(temp), None, None, 2)
            vm.session, vm.channel = Path(temp), Path(temp) / 'guest.sock'
            vm.child = Mock()
            vm.child.poll.return_value = None
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(vm.channel))
                server.listen()
                def reply():
                    connection, _ = server.accept()
                    with connection, connection.makefile('rb') as stream:
                        request = json.loads(stream.readline())
                        connection.sendall(b'{"id":"stale","code":0,"output":"PASS"}\n')
                        result = guest.run(request['command'], request['timeout'])
                        result.update(id=request['id'], boot_id='boot-2')
                        connection.sendall(json.dumps(result).encode() + b'\n')
                thread = threading.Thread(target=reply, daemon=True)
                thread.start()
                with self.assertRaisesRegex(RuntimeError, 'exited 7'):
                    vm.command('echo evidence; exit 7', label='failed')
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            saved = json.loads(next(Path(temp).glob('*-failed.json')).read_text())
            self.assertEqual(saved['result']['output'], 'evidence\n')
            self.assertEqual(saved['result']['code'], 7)

    @unittest.skipUnless(shutil.which('qemu-img'), 'optional real qcow2 test needs qemu-img')
    def test_real_qcow2_overlay_and_baseline_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            base, out = Path(temp) / 'base', Path(temp) / 'run'
            base.mkdir()
            out.mkdir()
            phase2.host(['qemu-img', 'create', '-f', 'qcow2', base / 'disk.qcow2', '16M'])
            (base / 'vars.fd').write_bytes(b'vars')
            phase2.save(base / 'baseline.json', dict(accepted=True, sha256={n: phase2.digest(base / n) for n in ['disk.qcow2', 'vars.fd']}))
            phase2.clone(base, out)
            info = json.loads(phase2.host(['qemu-img', 'info', '--output=json', out / 'disk.qcow2']))
            self.assertEqual(Path(info['full-backing-filename']), base / 'disk.qcow2')
            phase2.host(['qemu-img', 'resize', out / 'disk.qcow2', '32M'])
            phase2.verify_baseline(base)


if __name__ == '__main__':
    unittest.main()
