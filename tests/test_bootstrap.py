"""Run with python -m unittest discover -s tests -v."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap", ROOT / "scripts/bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def test_templates_and_live_contract(self):
        project = bootstrap.project()
        self.assertEqual(project["identity"]["version"],
                         bootstrap.tomllib.loads((ROOT / "Cargo.toml").read_text())["workspace"]["package"]["version"])
        values = dict(ID="test", NAME="Test", VERSION="0.0.1", ARCHIVE="2026/10/01",
                      KEYRING="/build/keyring", REPO="/build/repo", FINGERPRINT="A" * 40,
                      SHA256="0" * 64, RUST_VERSION="1.98.1")
        for template in (ROOT / "distro").rglob("*.in"):
            self.assertNotIn("@@", bootstrap.render(template.read_text(), values))
        with self.assertRaises(ValueError):
            bootstrap.render("@@MISSING@@", {})
        profile = (ROOT / "distro/archiso/profiledef.sh.in").read_text()
        self.assertIn("bootmodes=('uefi.systemd-boot')", profile)
        self.assertNotIn("bios.", profile)
        packages = bootstrap.packages()
        self.assertEqual(len(packages), len(set(packages)))
        self.assertTrue({"plasma-workspace", "ghostty", "konsole", "distroctl", "mkinitcpio-archiso"} <= set(packages))
        conf = (ROOT / "distro/archiso/pacman.conf.in").read_text()
        self.assertLess(conf.index("[distro]"), conf.index("[core]"))
        self.assertIn("SigLevel = Required DatabaseRequired", conf)
        self.assertNotIn("TrustAll", conf)
        locker = (ROOT / "distro/archiso/airootfs/etc/xdg/kscreenlockerrc").read_text()
        self.assertIn("[Daemon]\nAutolock=false\nLockOnResume=false", locker)
        lock = bootstrap.json.loads((ROOT / "distro/repo/archive.lock.json").read_text())
        self.assertEqual(lock["direct_packages"]["archiso"], project["build"]["archiso_version"])
        self.assertEqual(set(lock["direct_packages"]), bootstrap.upstream_packages())

    @unittest.skipIf(os.name == "nt", "profile staging needs Linux symlinks")
    def test_profile_generation_and_fingerprint_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = bootstrap.new_directory(root / "repo")
            for name in ["distro.db", "distro.db.sig", "repository-key.asc"]:
                bootstrap.write(repo / name, "test fixture\n")
            fingerprint = "A" * 40
            result = SimpleNamespace(stdout=f"pub:::::::::\nfpr:::::::::{fingerprint}:\n")
            with patch.object(bootstrap, "run", return_value=result) as run:
                output = bootstrap.new_directory(root / "success")
                profile = bootstrap.create_profile(output, repo, fingerprint)
                live = profile / "airootfs"
                self.assertIn("file:///opt/distro/repo", (live / "etc/pacman.conf").read_text())
                self.assertNotIn(str(output), (live / "etc/pacman.conf").read_text())
                self.assertNotIn("XferCommand", (live / "etc/pacman.conf").read_text())
                build_config = (profile / "pacman.conf").read_text()
                self.assertIn("--retry 3 --retry-all-errors --connect-timeout 20 --max-time 300", build_config)
                self.assertIn("SigLevel = Required DatabaseRequired", build_config)
                self.assertEqual(os.readlink(live / "etc/systemd/system/display-manager.service"),
                                 "/usr/lib/systemd/system/sddm.service")
                self.assertEqual(os.readlink(live / "etc/localtime"), "/usr/share/zoneinfo/UTC")
                self.assertEqual(os.readlink(live / "etc/systemd/system/systemd-firstboot.service"), "/dev/null")
                self.assertEqual((live / "etc/vconsole.conf").read_text().strip(), "KEYMAP=us")
                keyring_unit = (live / "etc/systemd/system/live-keyring.service").read_text()
                self.assertIn("ExecStartPre=/usr/bin/install -d -m 0755 /etc/pacman.d/gnupg", keyring_unit)
                self.assertNotIn("ConditionPathExists=", keyring_unit)
                self.assertEqual(list(profile.rglob("*.in")), [])
                self.assertTrue((live / "usr/local/libexec/live-smoke.sh").is_file())
                self.assertEqual(run.call_count, 5)
                run.reset_mock()
                with self.assertRaisesRegex(ValueError, "fingerprint"):
                    bootstrap.create_profile(bootstrap.new_directory(root / "rejected"), repo, "B" * 40)
                self.assertEqual(run.call_count, 1)  # No import or local trust after mismatch.

    def test_source_archive_is_deterministic_and_refuses_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = bootstrap.new_directory(root / "source")
            bootstrap.write(source / "nested/b.txt", "second\n")
            bootstrap.write(source / "a.txt", "first\n")
            bootstrap.archive(source, root / "one.tar.xz", 1000)
            os.utime(source / "a.txt", (9999, 9999))
            bootstrap.archive(source, root / "two.tar.xz", 1000)
            self.assertEqual(bootstrap.digest(root / "one.tar.xz"), bootstrap.digest(root / "two.tar.xz"))
            with self.assertRaises(FileExistsError):
                bootstrap.new_directory(source)
            (source / "a.txt").write_text("changed")
            bootstrap.archive(source, root / "three.tar.xz", 1000)
            self.assertNotEqual(bootstrap.digest(root / "one.tar.xz"), bootstrap.digest(root / "three.tar.xz"))


if __name__ == "__main__":
    unittest.main()
