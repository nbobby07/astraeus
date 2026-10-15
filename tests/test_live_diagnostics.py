"""Collector fixtures and local process tests, never physical hardware acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('live_evidence', ROOT / 'scripts/collect-live-evidence.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def reply(data, code=0, outcome='ok'):
    return dict(exit_code=code, outcome=outcome, seconds=0), json.dumps(data).encode()


class CollectorTests(unittest.TestCase):
    def test_schema_projection_and_privacy(self):
        secrets = ['SERIAL-SECRET', 'aa:bb:cc:dd:ee:ff', 'PrivateWifi',
                   'private-user', 'private-host', 'TOKEN-SECRET', '/home/private-user']
        payload = dict(schema_version=1, hostname=secrets[4], serial=secrets[0],
                       mac=secrets[1], ssid=secrets[2], username=secrets[3],
                       secret=secrets[5], log=secrets[6],
                       cpu=dict(architecture='x86_64', logical_count=16,
                                physical_core_count=8, model='private-host'),
                       memory_bytes=32 * 1024**3, memory_available_bytes=20 * 1024**3,
                       gpus=[dict(vendor_id='0x10de', device_id='0x2f04', driver='nvidia',
                                  boot_vga=True, model='SERIAL-SECRET')],
                       capabilities=dict(uefi=True, virtual_machine=False),
                       issues=[dict(message='TOKEN-SECRET', source='/home/private-user')])
        missing = []
        data = collector.parse_json(json.dumps(payload).encode(), 'hardware', missing)
        self.assertEqual(missing, [])
        self.assertEqual(data['cpu']['logical_count'], 16)
        self.assertEqual(data['gpus'][0]['vendor_id'], '0x10de')
        for secret in secrets:
            self.assertNotIn(secret, json.dumps(data))
        for name in collector.SCHEMAS:
            raw = dict(payload, architecture=64 if name != 'probe32' else 32,
                       kernel='6.17.1-private-host', version='1.0-private-user',
                       identity=dict(version='0.1.0-dev', username='private-user'),
                       status='passed', devices=[dict(name='private-user', driver_info='TOKEN-SECRET',
                                                       device_type=4, rendering='passed')],
                       context=dict(kernel='6.17.1-private-host', renderer=secrets),
                       wayland=dict(compositor_gpu='/home/private-user'),
                       nvidia_module=dict(signer='private-user'))
            sanitized = collector.parse_json(json.dumps(raw).encode(), name, [])
            for secret in secrets:
                self.assertNotIn(secret, json.dumps(sanitized), name)

    def test_partial_and_malformed_fields(self):
        missing = []
        data = collector.parse_json(b'{"schema_version":1,"cpu":{"logical_count":true},"gpus":"bad"}',
                                    'hardware', missing)
        self.assertIsNone(data['cpu']['logical_count'])
        self.assertIsNone(data['gpus'])
        self.assertIn('data.cpu.logical_count', missing)
        for raw in (b'{', b'[]', b'{"schema_version":2}', b'{"schema_version":true}', b'\xff'):
            with self.assertRaises((ValueError, UnicodeError)):
                collector.parse_json(raw, 'hardware', [])
        with self.assertRaises(ValueError):
            collector.parse_json(b'{"schema_version":1,"architecture":32}', 'probe64', [])

    def test_probe_protocol_and_software_classification(self):
        payload = dict(schema_version=1, architecture=64, loader_version=1, status='passed',
                       devices=[dict(vendor_id=1, device_id=2, device_type=4, api_version=1,
                                     driver_version=1, driver_id=13, software=False, rendering='passed')])
        data = collector.parse_json(json.dumps(payload).encode(), 'probe64', [])
        self.assertTrue(data['devices'][0]['software'])
        for changes in (dict(architecture=True), dict(status='unknown'), dict(status='failed'),
                        dict(devices=[dict(device_type=9, rendering='passed')]),
                        dict(devices=[dict(device_type=1, rendering='invented')]),
                        dict(devices=payload['devices'] * 65)):
            with self.assertRaises(ValueError):
                collector.parse_json(json.dumps(dict(payload, **changes)).encode(), 'probe64', [])

    def test_packages_partial_nonzero_and_private_service_names(self):
        missing = []
        packages = collector.parse_packages(b'mesa 1:25.2.3-1\nlinux 6.17.arch1-1\n'
                                            b'distroctl 0.1.0.dev-1\nsecret-user 1.0\n'
                                            b'kwin 6.4-private-host\nbad partial row', missing)
        self.assertEqual(set(packages), {'mesa', 'linux', 'distroctl'})
        self.assertIn('packages.kwin', missing)
        services = collector.parse_services(
            b'sddm.service loaded failed failed Display manager\n'
            b'backup@private-user.service loaded failed failed TOKEN-SECRET\n'
            b'private-host.service not-found failed failed PrivateWifi\npartial', missing)
        self.assertEqual(services, dict(known_failed=['sddm.service'], withheld_names=2, malformed_rows=1))
        self.assertNotIn('private', json.dumps(services))

    def test_bundle_records_failures_without_raw_text(self):
        responses = [reply({'schema_version': 1}),
                     (dict(exit_code=None, outcome='missing_tool', seconds=0), b'private-user'),
                     (dict(exit_code=-9, outcome='timeout', seconds=30), b'TOKEN-SECRET'),
                     (dict(exit_code=0, outcome='ok', seconds=0), b'{partial'),
                     reply({'schema_version': 9}),
                     reply({'schema_version': 1, 'architecture': 64, 'loader_version': 1,
                            'status': 'failed', 'devices': []}, 1, 'nonzero_exit'),
                     (dict(exit_code=-9, outcome='output_limit', seconds=0), b'PrivateWifi'),
                     (dict(exit_code=1, outcome='nonzero_exit', seconds=0), b'mesa 25.2.3-1\n'),
                     (dict(exit_code=1, outcome='nonzero_exit', seconds=0), b'private-host')]
        with tempfile.TemporaryDirectory() as temp:
            output = collector.new_directory(str(Path(temp) / 'evidence'))
            with patch.object(collector, 'execute', side_effect=responses) as execute:
                report = collector.collect(output)
            self.assertEqual(execute.call_count, 9)
            checks = report['observations']
            for name, outcome in [('info', 'partial_output'), ('status', 'missing_tool'),
                                  ('hardware', 'timeout'), ('graphics', 'malformed_output'),
                                  ('performance', 'unsupported_schema'), ('probe64', 'nonzero_exit'),
                                  ('probe32', 'output_limit')]:
                self.assertEqual(checks[name]['outcome'], outcome)
            self.assertEqual(checks['probe64']['exit_code'], 1)
            self.assertEqual(checks['probe64']['data']['status'], 'failed')
            self.assertEqual(checks['packages']['data'], {'mesa': '25.2.3-1'})
            self.assertIsNone(checks['services']['data'])
            self.assertFalse(report['physical_acceptance'])
            self.assertEqual(set(p.name for p in output.iterdir()), {'private', 'public.json'})
            text = (output / 'public.json').read_text()
            for secret in ('private-user', 'TOKEN-SECRET', 'PrivateWifi', 'private-host', '{partial'):
                self.assertNotIn(secret, text)
            self.assertEqual(json.loads(text), report)

    def test_destination_validation_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            evidence = collector.new_directory(str(root / 'evidence'))
            sentinel = evidence / 'keep'
            sentinel.write_text('preserved')
            for path in (str(evidence), str(sentinel), 'relative',
                         str(root / 'missing' / 'evidence'), str(root / '..' / 'escape')):
                with self.assertRaises((ValueError, OSError)):
                    collector.new_directory(path)
            self.assertEqual(sentinel.read_text(), 'preserved')
            if os.name == 'posix':
                self.assertEqual(evidence.stat().st_mode & 0o777, 0o700)
                (root / 'link').symlink_to(evidence, target_is_directory=True)
                with self.assertRaises(ValueError):
                    collector.new_directory(str(root / 'link' / 'escape'))
                self.assertFalse((evidence / 'escape').exists())

    def test_cli_requires_output_and_valid_hashes_before_writing(self):
        script = str(ROOT / 'scripts/collect-live-evidence.py')
        for args in ([], ['--output', '/unused', '--image-source-commit', 'bad'],
                     ['--output', '/unused', '--image-sha256', 'bad']):
            result = subprocess.run([sys.executable, script, *args], capture_output=True)
            self.assertEqual(result.returncode, 2)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux CLI permissions and root guard')
    def test_cli_confinement_permissions_and_root_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / 'chosen'
            argv = ['collect-live-evidence', '--output', str(output)]
            with patch.object(sys, 'argv', argv), patch.object(os, 'geteuid', return_value=0):
                with self.assertRaises(SystemExit) as exit_result:
                    collector.main()
                self.assertEqual(exit_result.exception.code, 2)
                self.assertEqual(list(root.iterdir()), [])
            before_umask = os.umask(0o022)
            try:
                with patch.object(sys, 'argv', argv), patch.object(os, 'geteuid', return_value=1000), \
                        patch.object(collector, 'execute', return_value=reply({'schema_version': 1})):
                    collector.main()
            finally:
                os.umask(before_umask)
            self.assertEqual(list(root.iterdir()), [output])
            self.assertEqual((output / 'public.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual((output / 'private').stat().st_mode & 0o777, 0o700)

    def test_packaging_includes_collector_and_guide(self):
        spec = importlib.util.spec_from_file_location('bootstrap_diagnostics', ROOT / 'scripts/bootstrap.py')
        bootstrap = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(ROOT / 'scripts'))
        try:
            spec.loader.exec_module(bootstrap)
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as temp, patch.object(bootstrap, 'run'):
            output = Path(temp) / 'package'
            bootstrap.prepare_package(output)
            with tarfile.open(output / 'platform.tar.xz') as archive:
                for name in ('scripts/collect-live-evidence.py', 'docs/live-diagnostics.md'):
                    self.assertEqual(archive.extractfile('platform/' + name).read(), (ROOT / name).read_bytes())
        recipe = (ROOT / 'distro/packages/distroctl/PKGBUILD.in').read_text()
        self.assertIn('install -Dm755 scripts/collect-live-evidence.py', recipe)
        self.assertIn('install -Dm644 docs/live-diagnostics.md', recipe)


@unittest.skipUnless(sys.platform == 'linux', 'Linux pipe/process-group behavior')
class ProcessTests(unittest.TestCase):
    def run_child(self, code, **kwargs):
        with tempfile.TemporaryDirectory() as temp:
            return collector.execute([sys.executable, '-c', code], Path(temp), **kwargs)

    def test_real_exit_and_stderr_never_returned(self):
        result, raw = self.run_child('import sys; print("ok"); print("TOKEN-SECRET", file=sys.stderr); sys.exit(7)')
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['outcome'], 'nonzero_exit')
        self.assertEqual(raw, b'ok\n')

    def test_missing_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            result, raw = collector.execute(['/nonexistent-astraeus-fixture'], Path(temp))
        self.assertEqual(result['outcome'], 'missing_tool')
        self.assertIsNone(result['exit_code'])
        self.assertEqual(raw, b'')

    def test_cleanup_wait_is_bounded(self):
        with patch.object(subprocess.Popen, 'wait', side_effect=subprocess.TimeoutExpired('fixture', 2)):
            result, _ = self.run_child('print("ok")')
        self.assertEqual(result['outcome'], 'cleanup_timeout')
        self.assertIsNone(result['exit_code'])

    def test_child_writes_and_cache_paths_stay_in_selected_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = collector.new_directory(str(root / 'chosen'))
            (output / 'private').mkdir(mode=0o700)
            code = ('import os,pathlib; '
                    'assert os.getcwd() == os.path.dirname(os.environ["HOME"]); '
                    'assert os.environ["HOME"] == os.environ["XDG_CACHE_HOME"]; '
                    'assert os.environ["MESA_SHADER_CACHE_DISABLE"] == "true"; '
                    'assert os.environ["__GL_SHADER_DISK_CACHE"] == "0"; '
                    'pathlib.Path("relative-file").write_text("fixture"); '
                    '(pathlib.Path(os.environ["HOME"])/"cache").write_text("fixture")')
            result, _ = collector.execute([sys.executable, '-c', code], output)
            self.assertEqual(result['outcome'], 'ok')
            self.assertEqual(list(root.iterdir()), [output])
            self.assertEqual((output / 'relative-file').read_text(), 'fixture')
            self.assertEqual((output / 'private/cache').read_text(), 'fixture')

    def test_timeout_and_descendant_pipe_are_bounded(self):
        started = time.monotonic()
        result, raw = self.run_child('import os,time; p=os.fork(); '
                                     'print(p, flush=True); time.sleep(60) if p == 0 else None', timeout=0.2)
        self.assertEqual(result['outcome'], 'timeout')
        self.assertLess(time.monotonic() - started, 3)
        # A descendant holding stdout open must not outlive collection.
        pid = next(int(line) for line in raw.splitlines() if int(line) > 0)
        for _ in range(50):
            path = Path(f'/proc/{pid}/stat')
            if not path.exists() or path.read_text().split()[2] == 'Z':
                break
            time.sleep(0.01)
        else:
            os.kill(pid, signal.SIGKILL)
            self.fail('descendant remained running')

    def test_output_limit_counts_stderr_and_caps_stdout(self):
        for channel in ('stdout', 'stderr'):
            result, raw = self.run_child(f'import sys; sys.{channel}.write("x" * 100000); sys.{channel}.flush()', limit=1000)
            self.assertEqual(result['outcome'], 'output_limit')
            self.assertLessEqual(len(raw), 1000)


if __name__ == '__main__':
    unittest.main()
