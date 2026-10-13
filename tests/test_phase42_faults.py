"""Fault harness guard/adapter tests. These tests are not installed-VM acceptance."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/validate'))
SPEC = importlib.util.spec_from_file_location('phase42_faults', ROOT / 'scripts/validate/phase42-faults.py')
faults = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(faults)


def baseline():
    return {'accepted': True, 'kind': 'phase42-fresh-candidate-payload', 'source_commit': 'a' * 40,
            'encryption': 'none', 'signer_sha256': 'd' * 64, 'public_fingerprints': {'db': 'd' * 64},
            'boot_ids': ['first', 'second'],
            'installed_binaries': {'distroctl': 'e' * 64, 'astraeus-control-center': 'f' * 64},
            'inputs': {'source_commits': ['a' * 40], 'iso': {'sha256': 'b' * 64},
                       'ovmf_code': {'sha256': 'c' * 64}}}


def arguments(**changes):
    values = dict(source_commit='a' * 40, image_sha256='b' * 64, distroctl_sha256='e' * 64,
                  desktop_sha256='f' * 64, encryption='none', timeout=1)
    values.update(changes)
    return SimpleNamespace(**values)


def observation():
    return dict(packages={'app': '1'}, reasons={'app': 'explicit'}, configuration={'packages': []},
                management={'schema_version': 1}, system_lock={'schema_version': 1}, config_toml='schema_version=1\n',
                root_uuid='root', esp_uuid='esp', firmware={'SecureBoot': True, 'SetupMode': False},
                home={'sha256': 'user-data', 'uid': 1000}, package_lock_present=False, boot_id='first')


class Phase42FaultsTests(unittest.TestCase):
    def test_only_fresh_exact_candidate_baseline_is_accepted(self):
        manifest = baseline()
        faults.candidate_guard(arguments(), manifest, 'c' * 64)
        for field, value in [('kind', 'phase3-qualified'), ('source_commit', '9' * 40),
                             ('accepted', False), ('boot_ids', ['first', 'first']),
                             ('signer_sha256', '8' * 64), ('installed_binaries', {'distroctl': 'e' * 64})]:
            changed = copy.deepcopy(manifest)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                faults.candidate_guard(arguments(), changed, 'c' * 64)
        with self.assertRaises(RuntimeError):
            faults.candidate_guard(arguments(), manifest, '9' * 64)

    def test_recovery_medium_binds_origin_actual_bytes_coordinator_and_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / 'recovery.img'
            image.write_bytes(b'test raw image')
            manifest = baseline()
            (root / 'baseline.json').write_text(json.dumps(manifest))
            args = arguments(base=root, recovery_image=image)
            recovery = dict(schema_version=1, kind='phase42-ram-verified-recovery', source_commit='a' * 40,
                            iso_sha256='b' * 64, image='recovery.img', image_sha256=faults.digest(image),
                            image_bytes=image.stat().st_size, certificate_sha256='d' * 64, distroctl_sha256='e' * 64,
                            baseline_manifest_sha256=faults.digest(root / 'baseline.json'), private_key_in_image=False,
                            rootfs_sha256='0' * 64, uki_sha256='1' * 64, minimum_ram_gib=8)
            faults.recovery_guard(args, manifest, recovery)
            for field, value in [('source_commit', '2' * 40), ('iso_sha256', '2' * 64), ('image_sha256', '2' * 64),
                                 ('certificate_sha256', '2' * 64), ('distroctl_sha256', '2' * 64),
                                 ('private_key_in_image', True), ('minimum_ram_gib', 0), ('minimum_ram_gib', True),
                                 ('baseline_manifest_sha256', '2' * 64), ('rootfs_sha256', '')]:
                changed = dict(recovery, **{field: value})
                with self.subTest(field=field), self.assertRaises(RuntimeError):
                    faults.recovery_guard(args, manifest, changed)
            image.write_bytes(b'tampered bytes')
            with self.assertRaises(RuntimeError):
                faults.recovery_guard(args, manifest, recovery)

    def test_restoration_must_match_metadata_reasons_files_and_home(self):
        before = observation()
        after = copy.deepcopy(before)
        after['boot_id'] = 'new-boot'
        faults.state_equal(before, after)
        for field in ['packages', 'reasons', 'configuration', 'management', 'system_lock', 'config_toml',
                      'root_uuid', 'esp_uuid', 'firmware', 'home']:
            bad = copy.deepcopy(after)
            bad[field] = 'changed'
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, field):
                faults.state_equal(before, bad)
        after['package_lock_present'] = True
        with self.assertRaisesRegex(RuntimeError, 'lock'):
            faults.state_equal(before, after)

    def test_metadata_only_plan_requires_real_intent_and_boot_boundary(self):
        before = observation()
        plan = {'executable': True, 'blockers': [], 'plan': {'packages': {'changes': [], 'targets': []},
                'management': {'before': before['management'], 'before_digest': 'old', 'after_digest': 'new'},
                'snapshot_required': True, 'boot': {'regenerate_uki': True}}}
        faults.metadata_plan(plan, before)
        for kind in ['package', 'target', 'same-state', 'snapshot', 'uki', 'blocked']:
            bad = copy.deepcopy(plan)
            if kind in ['package', 'target']:
                bad['plan']['packages']['changes' if kind == 'package' else 'targets'] = [{'name': 'other'}]
            elif kind == 'same-state':
                bad['plan']['management']['after_digest'] = 'old'
            elif kind == 'snapshot':
                bad['plan']['snapshot_required'] = False
            elif kind == 'uki':
                bad['plan']['boot']['regenerate_uki'] = False
            else:
                bad['blockers'] = ['previous operation']
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                faults.metadata_plan(bad, before)

    def test_snapshot_evidence_must_precede_actual_mutation(self):
        record = {'snapshot': 'pre', 'post_snapshot': 'post', 'boot_regenerated': True,
                  'events': [{'state': 'snapshot_created'}, {'state': 'applying'}]}
        faults.transaction_boundary(record, post=True)
        record['events'].reverse()
        with self.assertRaises(RuntimeError):
            faults.transaction_boundary(record)
        record['events'].reverse()
        record['post_snapshot'] = None
        with self.assertRaises(RuntimeError):
            faults.transaction_boundary(record, post=True)

    def test_terminal_transaction_waits_for_actual_worker_and_finalizer_exit(self):
        self.assertTrue(faults.unit_idle('LoadState=not-found\nActiveState=inactive\nJob=\n'))
        self.assertFalse(faults.unit_idle('LoadState=loaded\nActiveState=active\nJob=\n'))
        self.assertFalse(faults.unit_idle('LoadState=loaded\nActiveState=deactivating\nJob=\n'))
        self.assertFalse(faults.unit_idle('LoadState=loaded\nActiveState=inactive\nJob=23 start\n'))
        self.assertFalse(faults.unit_idle('LoadState=loaded\nActiveState=failed\nJob=\n'))
        self.assertTrue(faults.unit_idle('LoadState=loaded\nActiveState=failed\nJob=\n', allow_failed=True))
        for value in ['LoadState=not-found\n', 'LoadState=not-found\nActiveState=inactive\nJob=\nJob=1\n']:
            with self.assertRaises(RuntimeError):
                faults.unit_idle(value)

    def test_guest_invocations_are_fixed_and_quoted(self):
        vm = Mock()
        vm.command.return_value = {'output': '{}'}
        faults.guest_command(vm, 'recover', '123-456')
        command = vm.command.call_args.args[0]
        self.assertEqual(command, 'python3 /mnt/astraeus-validation/phase42-faults.py guest recover 123-456')
        self.assertEqual(vm.command.call_args.kwargs['timeout'], 1000)

    def test_real_package_hook_uses_posttransaction_worker_ancestor_and_durable_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = root / 'runtime', root / 'hooks/fault.hook', root / 'logs/barrier.json'
            with patch.object(faults, 'guest_guard', return_value={'run_id': 'a' * 32, 'package': 'hello'}), \
                    patch.object(faults, 'barrier_paths', return_value=paths), patch.object(faults.os, 'sync', create=True):
                result = faults.guest_arm_barrier()
            self.assertEqual(result['when'], 'PostTransaction')
            self.assertIn('Target = hello', paths[1].read_text())
            self.assertIn('When = PostTransaction', paths[1].read_text())
            source = (paths[0] / 'barrier.py').read_text()
            compile(source, 'barrier.py', 'exec')
            self.assertIn("args[1:3]==[b'system',b'worker']", source)
            self.assertIn('os.fsync', source)
            self.assertIn('time.sleep(3600)', source)

    def test_recovery_attach_is_readonly_secondary_and_does_not_change_firmware(self):
        _, p2 = faults.host_modules()
        original = p2.install.qemu_command
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / 'boot-1'
            session.mkdir()
            (session / 'serial.log').write_text(faults.SECURE_LIVE_MARKER + '\n' + faults.LIVE_DESKTOP_MARKER)
            vm = Mock(session=session, out=root, monitor=root / 'qmp.sock')
            def start():
                vm.actual_command = p2.install.qemu_command(root / 'secure.fd', root / 'vars.fd', root / 'disk.qcow2',
                                                            root / 'serial.log', root / 'qmp.sock', secure_boot=True)
            vm.start.side_effect = start
            faults.start_recovery(vm, arguments(recovery_image=root / 'recovery.img'), {'minimum_ram_gib': 8})
            self.assertIs(p2.install.qemu_command, original)
            self.assertIn('virtio-blk-pci,drive=osdisk,bootindex=2', vm.actual_command)
            self.assertIn('usb-storage,drive=recovery,bootindex=1', vm.actual_command)
            self.assertTrue(any('id=recovery,format=raw,readonly=on' in part for part in vm.actual_command))
            self.assertEqual(vm.actual_command[vm.actual_command.index('-m') + 1], '8192')
            self.assertIn('q35,accel=kvm,smm=on', vm.actual_command)
            vm.ready.assert_called_once()
            vm.start.side_effect = RuntimeError('launch failed')
            with self.assertRaisesRegex(RuntimeError, 'launch failed'):
                faults.start_recovery(vm, arguments(recovery_image=root / 'recovery.img'), {'minimum_ram_gib': 8})
            self.assertIs(p2.install.qemu_command, original)

    def test_guest_actions_refuse_an_ordinary_host_before_running_commands(self):
        with patch.object(faults.sys, 'platform', 'linux'), patch.object(faults.os, 'geteuid', return_value=0, create=True), \
                patch.object(faults, 'Path') as path, patch.object(faults, 'call') as call:
            path.return_value.exists.return_value = False
            with self.assertRaisesRegex(RuntimeError, 'dedicated KVM'):
                faults.guest_guard()
            call.assert_not_called()

    def test_configuration_rejects_paths_and_shell_arguments_as_identifiers(self):
        config = dict(schema_version=1, run_id='a' * 32, source_commit='b' * 40, distroctl_sha256='c' * 64,
                      desktop_sha256='d' * 64, certificate_sha256='e' * 64, image_sha256='f' * 64,
                      user='tester', package='hello', encryption='none')
        faults.configuration(config)
        for field, value in [('user', 'root'), ('package', '--config=/bad'), ('run_id', '../outside'),
                             ('distroctl_sha256', 'unknown'), ('encryption', 'luks1')]:
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                faults.configuration(dict(config, **{field: value}))

    def test_command_help_does_not_start_a_vm(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate/phase42-faults.py'), 'run', '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ['--metadata-package', '--recovery-image', '--recovery-manifest', '--harness-commit']:
            self.assertIn(option, result.stdout)


if __name__ == '__main__':
    unittest.main()
