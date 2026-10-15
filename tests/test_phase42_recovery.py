"""Builder/guard unit tests. No simulated result is firmware or recovery acceptance."""
import copy
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_recovery', ROOT / 'scripts/validate/phase42-recovery.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
sys.path.insert(0, str(ROOT / 'scripts/validate'))
checks_spec = importlib.util.spec_from_file_location('recovery_check', ROOT / 'scripts/validate/phase42-recovery-check.py')
checks = importlib.util.module_from_spec(checks_spec)
checks_spec.loader.exec_module(checks)
ANCHOR = '    img_loopdev="$(losetup --find --show --read-only -- "${img}")"'


def baseline():
    return {'schema_version': 1, 'kind': 'phase42-fresh-candidate-payload', 'accepted': True,
            'source_commit': 'a' * 40, 'inputs': {'source_commits': ['a' * 40], 'iso': {'sha256': 'b' * 64}},
            'signer_sha256': 'c' * 64, 'public_fingerprints': {'db': 'c' * 64},
            'installed_binaries': {'distroctl': 'd' * 64}}


def live_plan():
    return {'schema_version': 1, 'plan_id': 'sha256:' + 'a' * 64, 'executable': False,
            'blockers': ['Live sessions support inspection only; install the system before applying changes.'],
            'plan': {'schema_version': 2, 'desired': 'managed_system',
                     'management': {'after': {'applied': {'schema_version': 1, 'packages': ['kcalc'], 'gaming': [], 'providers': {}}}},
                     'packages': {'changes': [{'kind': 'install', 'name': 'kcalc', 'version': '1-1'}],
                                  'targets': [{'name': 'kcalc', 'version': '1-1'}]}}}


def live_replies(plan, refusal=None):
    return [({}, {'live': True, 'supported': True}), ({}, {'features': [{'id': 'tools'}]}),
            ({}, {'packages': [{'name': 'konsole'}]}), ({}, plan),
            (refusal or {'code': 1, 'output': 'live sessions cannot apply'}, None)]


class RecoveryBuilder(unittest.TestCase):
    def test_live_cli_resolves_nonempty_app_intent_and_submits_its_actual_digest_only_for_refusal(self):
        before = {'configuration': None, 'packages': 'konsole 1-1', 'files': {}}
        plan = live_plan()
        with patch.object(checks, 'management_fingerprint', side_effect=[before, copy.deepcopy(before)]), \
                patch.object(checks.phase42, 'json_command', side_effect=live_replies(plan)) as command:
            self.assertTrue(checks.live_cli(Mock())['passed'])
        request = command.call_args_list[3]
        self.assertEqual(request.args[2], {'schema_version': 1, 'packages': ['kcalc'], 'gaming': [], 'providers': {}})
        self.assertEqual(request.args[3], 'live')
        submit = command.call_args_list[4]
        self.assertEqual(submit.args[1], ['system', 'submit', '--json'])
        self.assertEqual(submit.args[2]['config'], request.args[2])
        self.assertEqual(submit.args[2]['expected_plan'], plan['plan_id'])
        self.assertNotIn('user', submit.kwargs)

    def test_live_blocker_cannot_hide_failed_resolution_or_missing_review_identity(self):
        for kind in ['null-plan', 'empty-plan', 'missing-id', 'empty-id', 'null-id', 'malformed-id',
                     'wrong-schema', 'wrong-intent', 'missing-change', 'missing-target', 'generic-live-blocker',
                     'unrelated-blocker', 'executable']:
            plan = live_plan()
            if kind == 'null-plan':
                plan['plan'] = None
                plan['blockers'].insert(0, 'package metadata unavailable')
            elif kind == 'empty-plan':
                plan['plan'] = {}
            elif kind == 'missing-id':
                del plan['plan_id']
            elif kind in ['empty-id', 'null-id', 'malformed-id']:
                plan['plan_id'] = {'empty-id': '', 'null-id': None, 'malformed-id': 'sha256:' + 'A' * 64}[kind]
            elif kind == 'wrong-schema':
                plan['plan']['schema_version'] = True
            elif kind == 'wrong-intent':
                plan['plan']['management']['after']['applied']['packages'] = []
            elif kind == 'missing-change':
                plan['plan']['packages']['changes'] = []
            elif kind == 'missing-target':
                plan['plan']['packages']['targets'] = []
            elif kind == 'generic-live-blocker':
                plan['blockers'] = ['live resolver failed']
            elif kind == 'unrelated-blocker':
                plan['blockers'].append('operation history unavailable')
            else:
                plan['executable'] = True
            with self.subTest(kind=kind), patch.object(checks, 'management_fingerprint', return_value={}), \
                    patch.object(checks.phase42, 'json_command', side_effect=live_replies(plan)) as command:
                with self.assertRaises(RuntimeError):
                    checks.live_cli(Mock())
                self.assertEqual(command.call_count, 4, 'unresolved intent reached submission')

    def test_live_cli_still_requires_explicit_apply_refusal_and_unchanged_managed_state(self):
        for refusal, after in [({'code': 0, 'output': 'live sessions cannot apply'}, {}),
                               ({'code': 1, 'output': 'unrelated resolver failure'}, {}),
                               ({'code': 1, 'output': 'live sessions cannot apply'}, {'changed': True})]:
            with self.subTest(refusal=refusal, after=after), \
                    patch.object(checks, 'management_fingerprint', side_effect=[{}, after]), \
                    patch.object(checks.phase42, 'json_command', side_effect=live_replies(live_plan(), refusal)):
                with self.assertRaises(RuntimeError):
                    checks.live_cli(Mock())

    def test_live_gui_receipt_requires_exact_observed_candidate_and_all_refusal_checks(self):
        manifest = {'distroctl_sha256': 'a' * 64, 'desktop_sha256': 'b' * 64}
        receipt = {'schema_version': 1, 'source_commit': 'c' * 40, 'live': True,
                   **manifest, 'firmware': {'SecureBoot': True, 'SetupMode': False},
                   'checks': {'inspection_visible': True, 'live_warning_visible': True,
                              'review_blocked': True, 'apply_disabled': True},
                   'evidence': [{'path': 'gui/overview.png', 'sha256': 'd' * 64}]}
        checks.validate_gui_receipt(receipt, manifest, 'c' * 40)
        for name, value in [('source_commit', 'e' * 40), ('schema_version', True), ('live', False),
                            ('desktop_sha256', 'e' * 64), ('firmware', {'SecureBoot': False, 'SetupMode': True}),
                            ('checks', {'inspection_visible': True}), ('evidence', []),
                            ('evidence', [{'path': '../private/password', 'sha256': 'd' * 64}])]:
            invalid = copy.deepcopy(receipt)
            invalid[name] = value
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                checks.validate_gui_receipt(invalid, manifest, 'c' * 40)

    def test_runtime_verdict_requires_actual_positive_or_refusal_evidence(self):
        for mode in checks.MODES:
            self.assertFalse(checks.observed_verdict(mode, 'timeout; firmware still running'))
        self.assertTrue(checks.observed_verdict('trusted', checks.VERIFIED + '\n' + checks.DESKTOP))
        self.assertFalse(checks.observed_verdict('trusted', checks.DESKTOP))
        self.assertFalse(checks.observed_verdict('trusted', checks.VERIFIED + checks.DESKTOP + checks.REFUSED))
        for mode in ['root-tampered', 'disabled']:
            self.assertTrue(checks.observed_verdict(mode, checks.REFUSED))
            self.assertFalse(checks.observed_verdict(mode, checks.REFUSED + checks.VERIFIED))
        for mode in ['unsigned', 'tampered', 'untrusted']:
            self.assertTrue(checks.observed_verdict(mode, 'BdsDxe: loading Boot0001: Access Denied'))
            self.assertFalse(checks.observed_verdict(mode, 'Access Denied\nLinux version 6.17'))
            self.assertFalse(checks.observed_verdict(mode, 'Security Violation\n' + checks.DESKTOP))

    def test_media_gate_attaches_no_installed_disk_and_only_readonly_raw_usb(self):
        command = checks.media_command(checks.p2.install.qemu_command, Path('/checked/recovery.img'), 8,
                    Path('/firmware/code'), Path('/private/vars'), Path('/never/open/disk.qcow2'),
                    Path('/out/serial.log'), Path('/out/qmp.sock'), secure_boot=True)
        self.assertFalse(any('qcow2' in item or '/never/open' in item for item in command))
        self.assertIn('if=none,id=osdisk,format=raw,readonly=on,file=' + str(Path('/checked/recovery.img')), command)
        self.assertIn('q35,accel=kvm,smm=on', command)
        self.assertLess(command.index('qemu-xhci'), command.index('usb-storage,drive=osdisk,bootindex=1'))
        self.assertEqual(command[command.index('-m') + 1], '8192')

    def test_requires_exact_accepted_candidate_and_baseline_signer(self):
        self.assertEqual(builder.baseline_identity(baseline(), 'a' * 40, 'b' * 64), ('c' * 64, 'd' * 64))
        for key, value in [('schema_version', 2), ('schema_version', True), ('accepted', False),
                           ('kind', 'phase3-integrated'), ('source_commit', 'e' * 40),
                           ('public_fingerprints', {'db': 'f' * 64}), ('installed_binaries', {}),
                           ('signer_sha256', 'UNKNOWN')]:
            invalid = baseline()
            invalid[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                builder.baseline_identity(invalid, 'a' * 40, 'b' * 64)
        for source, iso in [('e' * 40, 'b' * 64), ('a' * 40, 'e' * 64), ('a' * 12, 'b' * 64),
                            ('a' * 40, 'B' * 64)]:
            with self.assertRaises(ValueError):
                builder.baseline_identity(baseline(), source, iso)
        changed = copy.deepcopy(baseline())
        changed['inputs']['source_commits'] = ['e' * 40]
        with self.assertRaises(ValueError):
            builder.baseline_identity(changed, 'a' * 40, 'b' * 64)

    def test_image_fits_fat_files_and_aligned_capacity(self):
        self.assertEqual(builder.image_size(2 * 1024**3, 128 * 1024**2), 4 * 1024**3)
        size = builder.image_size(builder.FAT_FILE_LIMIT, 256 * 1024**2)
        self.assertEqual(size % builder.OFFSET, 0)
        self.assertGreaterEqual(size, builder.FAT_FILE_LIMIT + 256 * 1024**2 + 130 * builder.OFFSET)
        for rootfs, uki in [(0, 1), (1, 0), (builder.FAT_FILE_LIMIT + 1, 1),
                            (1, builder.FAT_FILE_LIMIT + 1), (True, 1)]:
            with self.assertRaises(ValueError):
                builder.image_size(rootfs, uki)

    def test_guard_rejects_unknown_hook_and_hash_injection(self):
        for original in ['', ANCHOR + '\n' + ANCHOR]:
            with self.assertRaises(ValueError):
                builder.guard_hook(original, 'a' * 64)
        for pin in ['a' * 63, 'A' * 64, "'; touch /tmp/escape; '"]:
            with self.assertRaises(ValueError):
                builder.guard_hook(ANCHOR, pin)
        hooked = builder.guard_hook(ANCHOR, 'a' * 64)
        self.assertLess(hooked.index('sha256sum -c -'), hooked.index('losetup --find'))
        self.assertLess(hooked.index('SetupMode-'), hooked.index('losetup --find'))
        self.assertIn('[ "${copytoram}" = y ]', hooked)
        self.assertIn('poweroff -f', hooked)
        self.assertNotIn('exec sh', hooked)

    def test_image_inputs_refuse_directories_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                builder.regular(root)
            ordinary = root / 'ordinary'
            ordinary.write_text('public input')
            self.assertEqual(builder.regular(ordinary), ordinary.resolve())
            if hasattr(Path, 'symlink_to'):
                link = root / 'link'
                try:
                    link.symlink_to(ordinary)
                except OSError:
                    return  # Windows may lack symlink privileges.
                with self.assertRaises(ValueError):
                    builder.regular(link)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'guard control-flow fixture needs native Bash')
    def test_guard_refuses_bad_root_disabled_secure_boot_and_wrong_ram_location(self):
        # Fake commands isolate shell control flow. These tests never mount or
        # power off anything and never stand in for actual enforcing OVMF boots.
        original = 'run_hook() {\n' + ANCHOR + '\n    echo ROOT_MOUNT_ALLOWED\n}\n'
        hooked = builder.guard_hook(original, 'a' * 64)
        stubs = '''
mkdir() { :; }
mountpoint() { return 0; }
sha256sum() { cat >/dev/null; [ "$HASH_OK" = 1 ]; }
busybox() {
    if [ "$1" = base64 ]; then cat; return; fi
    case "$4" in
        */SecureBoot-*) printf '%s' "$SB";;
        */SetupMode-*) printf '%s' "$SETUP";;
        *) return 1;;
    esac
}
losetup() { echo /dev/mock-loop; }
sleep() { :; }
poweroff() { echo POWER_OFF; exit 42; }
'''
        for setting in ['HASH_OK=0', 'SB=AA==', 'SETUP=AQ==', 'copytoram=n', 'img=/other/root.sfs']:
            script = hooked + stubs + '\nHASH_OK=1; SB=AQ==; SETUP=AA==; copytoram=y; img=/run/archiso/copytoram/airootfs.sfs\n'
            result = subprocess.run(['bash', '-c', script + setting + '\nrun_hook\n'], capture_output=True, text=True, timeout=5)
            with self.subTest(setting=setting):
                self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
                self.assertIn('ASTRAEUS_SECURE_LIVE_REFUSED', result.stdout)
                self.assertNotIn('ROOT_MOUNT_ALLOWED', result.stdout)
                self.assertNotIn('ASTRAEUS_SECURE_LIVE_OK', result.stdout)
        script = hooked + stubs + '\nHASH_OK=1; SB=AQ==; SETUP=AA==; copytoram=y; img=/run/archiso/copytoram/airootfs.sfs; run_hook\n'
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('ROOT_MOUNT_ALLOWED', result.stdout)
        self.assertIn('ASTRAEUS_SECURE_LIVE_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
