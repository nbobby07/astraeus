"""Validation-helper boundaries, not installed-VM acceptance evidence."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('phase5_validation', Path(__file__).resolve().parents[1] / 'scripts/validate/phase5.py')
phase5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase5)


def stream(state='completed', code=0):
    report = dict(schema_version=1, id='a' * 32, state=state)
    rows = [dict(schema_version=1, event='started', data=dict(id='a' * 32)),
            dict(schema_version=1, event='result', data=report)]
    return SimpleNamespace(stdout='\n'.join(map(json.dumps, rows)), stderr='', returncode=code)


class PerformanceValidation(unittest.TestCase):
    def test_completed_stream_requires_matching_boundaries_and_exit(self):
        self.assertEqual(phase5.events(stream())['state'], 'completed')
        for result in [stream('cancelled', 1), stream('completed', 1),
                       SimpleNamespace(stdout='', stderr='', returncode=0)]:
            with self.assertRaises(RuntimeError):
                phase5.events(result)
        bad = stream()
        rows = [json.loads(line) for line in bad.stdout.splitlines()]
        rows[-1]['data']['id'] = 'b' * 32
        bad.stdout = '\n'.join(map(json.dumps, rows))
        with self.assertRaises(RuntimeError):
            phase5.events(bad)

    def test_runner_uses_fixed_executable_arguments_and_bounded_output(self):
        with patch.object(phase5.subprocess, 'run', return_value=stream()) as run:
            phase5.run('record', '--duration', '2')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/distroctl', 'performance', 'record', '--duration', '2', '--json'])
            self.assertNotIn('shell', run.call_args.kwargs)
        with patch.object(phase5.subprocess, 'run', return_value=SimpleNamespace(stdout=' ' * (16 * 1024 ** 2 + 1))):
            with self.assertRaises(RuntimeError):
                phase5.run('status')


if __name__ == '__main__':
    unittest.main()
