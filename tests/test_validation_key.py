import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

spec = importlib.util.spec_from_file_location(
    "validation_key", Path(__file__).resolve().parents[1] / "scripts/validate/repository-key.py"
)
key = importlib.util.module_from_spec(spec)
spec.loader.exec_module(key)
FINGERPRINT = "A" * 40
NOW = 1_800_000_000


def listing(*, validity="-", created=NOW - 60, expires=NOW + 7 * 86400, capabilities="scSC"):
    fields = ["pub", validity, "255", "22", "A" * 16, str(created), str(expires), "", "", "", "", capabilities]
    return ":".join(fields) + f":\nfpr:::::::::{FINGERPRINT}:\n"


class ValidationKeyTests(unittest.TestCase):
    def test_finite_signer_covers_the_test_window(self):
        result = key.inspect(listing(), FINGERPRINT, NOW)
        self.assertEqual(result["expires_unix"], NOW + 7 * 86400)
        self.assertEqual(result["minimum_remaining_seconds"], 72 * 3600)

    def test_expired_short_lived_future_disabled_and_non_signing_keys_fail(self):
        for fields in [
            {"expires": NOW - 1}, {"expires": NOW + 86400},
            {"expires": NOW + 72 * 3600}, {"expires": 0}, {"created": NOW + 1},
            {"validity": "r"}, {"validity": "e"}, {"validity": "d"}, {"validity": "i"},
            {"capabilities": "scSCD"}, {"capabilities": "cSC"},
        ]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                key.inspect(listing(**fields), FINGERPRINT, NOW)

    def test_wrong_ambiguous_secret_and_subkey_identities_fail(self):
        for text, fingerprint in [
            (listing(), "B" * 40), (listing(), "a" * 40),
            (listing() + listing(), FINGERPRINT),
            (listing().replace("pub:", "sec:"), FINGERPRINT),
            (listing() + listing().replace("pub:", "sub:"), FINGERPRINT),
            ("pub:\n", FINGERPRINT), (listing().replace(str(NOW - 60), "invalid"), FINGERPRINT),
        ]:
            with self.subTest(text=text, fingerprint=fingerprint), self.assertRaises(ValueError):
                key.inspect(text, fingerprint, NOW)

    @unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgconf"), "requires GnuPG")
    def test_real_export_is_read_without_importing_into_the_operator_keyring(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "signer"
            home.mkdir(mode=0o700)
            command = ["gpg", "--homedir", str(home), "--no-options", "--batch"]
            try:
                subprocess.run(command + ["--pinentry-mode", "loopback", "--passphrase", "",
                    "--quick-generate-key", "Astraeus disposable preflight test", "ed25519", "sign", "7d"],
                    check=True, capture_output=True, timeout=30)
                result = subprocess.run(command + ["--with-colons", "--list-keys"],
                    check=True, capture_output=True, text=True, timeout=30)
                fingerprint = next(line.split(":")[9] for line in result.stdout.splitlines() if line.startswith("fpr:"))
                exported = Path(directory) / "public.asc"
                exported.write_bytes(subprocess.run(command + ["--armor", "--export", fingerprint],
                    check=True, capture_output=True, timeout=30).stdout)
                now = int(time.time())
                self.assertEqual(key.check(exported, fingerprint, now)["fingerprint"], fingerprint)
                with self.assertRaisesRegex(ValueError, "72 hours"):
                    key.check(exported, fingerprint, now + 5 * 86400)
            finally:
                subprocess.run(["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"],
                    check=False, capture_output=True, timeout=15)
