import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import unittest

spec = importlib.util.spec_from_file_location("qmp", Path(__file__).resolve().parents[1] / "scripts/validate/qmp.py")
qmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qmp)


class QmpTests(unittest.TestCase):
    def test_stdin_text_is_validated_without_echoing_the_input(self):
        text = "Fixture!Text"
        result = subprocess.run([sys.executable, str(spec.origin), "missing.sock", "--text-stdin"],
                                input=text + "\n", text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported character", result.stderr)
        self.assertNotIn(text, result.stdout + result.stderr)

    def test_text_is_validated_before_sending_any_keys(self):
        self.assertEqual(qmp.key_codes("A_0 /"), [["shift", "a"], ["shift", "minus"], ["0"], ["spc"], ["slash"]])
        self.assertEqual(qmp.key_codes("?&*"), [["shift", "slash"], ["shift", "7"], ["shift", "8"]])
        self.assertEqual(qmp.key_codes("[],"), [["bracket_left"], ["bracket_right"], ["comma"]])
        self.assertEqual(qmp.key_codes("{}"), [["shift", "bracket_left"], ["shift", "bracket_right"]])
        self.assertEqual(qmp.key_codes("@"), [["shift", "2"]])
        with self.assertRaises(ValueError):
            qmp.key_codes("sudo\n")

    def test_events_cannot_be_mistaken_for_command_success(self):
        self.assertEqual(qmp.reply(io.BytesIO(b'{"event":"RESUME"}\n{"return":{"enabled":true}}\n')),
                         {"enabled": True})
        with self.assertRaises(RuntimeError):
            qmp.reply(io.BytesIO(b'{"error":{"class":"GenericError","desc":"KVM failed"}}\n'))
        with self.assertRaises(ConnectionError):
            qmp.reply(io.BytesIO(b'{"event":"SHUTDOWN"}\n'))
