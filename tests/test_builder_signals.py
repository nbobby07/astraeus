import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class BuilderSignalTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "requires Bash signal handling")
    def test_interruption_cannot_be_recorded_as_success(self):
        script = Path(__file__).resolve().parents[1] / "scripts/validate/arch-builder.sh"
        # Execute the actual script's reporting/signal handlers without provisioning a VM.
        handlers = "\n".join(line for line in script.read_text().splitlines() if line.startswith("trap "))
        with tempfile.TemporaryDirectory() as evidence:
            result = subprocess.run(["bash", "-c", 'evidence="$1"\n' + handlers + '\nkill -TERM $$',
                                     "signal-check", evidence])
            self.assertEqual(result.returncode, 143)
            self.assertEqual((Path(evidence) / "exit-code").read_text().strip(), "143")
