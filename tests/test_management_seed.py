"""Installed-image ownership comes from staged package observations, never adoption guesses."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bootstrap
import installer


def package(root, name, reason="0", version="1-1"):
    bootstrap.write(root / "var/lib/pacman/local" / name / "desc",
                    f"%NAME%\n{name}\n\n%VERSION%\n{version}\n\n%REASON%\n{reason}\n")


def fake_resolution(_root, packages):
    return {"extra": "sha256:" + "a" * 64}, {
        name: {"version": value["version"], "repository": "extra", "sha256": "b" * 64}
        for name, value in packages.items()}


class ManagementSeedTests(unittest.TestCase):
    def test_seed_preserves_base_and_shared_packages_and_records_new_feature_closure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("mesa", "lib32-mesa", "gamemode"):
                package(root, name, "1")
            before = installer.installed_state(root)
            for name in set(installer.gaming_packages(["tools", "mangohud"])) - before.keys():
                package(root, name)
            package(root, "tool-library", "1")
            with patch.object(installer, "locked_packages", side_effect=fake_resolution):
                installer.seed_management(root, before, ["software"], ["tools", "mangohud"], bootstrap.write, "fixture config\n")
                state = json.loads((root / "var/lib/astraeus/management/state.json").read_text())
                lock = json.loads((root / "var/lib/astraeus/management/system.lock").read_text())
                self.assertEqual(state["protected"], sorted(before))
                self.assertNotIn("gamemode", state["packages"])
                self.assertEqual(state["packages"]["mangohud"]["owners"], ["gaming:mangohud", "gaming:tools"])
                self.assertEqual(state["packages"]["tool-library"], {"version": "1-1", "reason": "dependency", "owners": []})
                self.assertEqual(lock["packages"], state["resolution"])
                digest = hashlib.sha256(json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
                self.assertEqual(lock["management_sha256"], "sha256:" + digest)
                self.assertEqual(list(state), ["schema_version", "applied", "packages", "protected", "repositories", "resolution", "resolved_providers"])
                self.assertEqual(lock["providers"], {})
                self.assertEqual(lock["configured_providers"], {})
                self.assertEqual(state["repositories"]["pacman-config"], "sha256:" + hashlib.sha256(b"fixture config\n").hexdigest())
                files = [root / "var/lib/astraeus/management/state.json", root / "var/lib/astraeus/management/system.lock", root / "etc/astraeus/system.toml"]
                first = [path.read_bytes() for path in files]
                installer.seed_management(root, before, ["software"], ["mangohud", "tools", "tools"], bootstrap.write, "fixture config\n")
                self.assertEqual([path.read_bytes() for path in files], first)

    def test_changed_base_and_incomplete_gaming_abort_before_seeding(self):
        for fault in ("base-version", "base-reason", "missing-feature"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                package(root, "mesa")
                before = installer.installed_state(root)
                if fault == "base-version":
                    package(root, "mesa", version="2-1")
                elif fault == "base-reason":
                    package(root, "mesa", reason="1")
                with self.assertRaises(ValueError):
                    installer.seed_management(root, before, [], ["core"], bootstrap.write, "fixture config\n")
                self.assertFalse((root / "var/lib/astraeus/management").exists())

    def test_installed_observation_defaults_explicit_but_rejects_duplicate_and_invalid_reasons(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package(root, "mesa")
            desc = root / "var/lib/pacman/local/mesa/desc"
            valid = desc.read_text()
            desc.write_text(valid.replace("%REASON%\n0", ""))
            self.assertEqual(installer.installed_state(root)["mesa"]["reason"], "explicit")
            for invalid in (valid.replace("%REASON%\n0", "%REASON%\n2"),
                            valid + "\n%REASON%\n1\n", valid + "\n%NAME%\nmesa\n"):
                desc.write_text(invalid)
                with self.assertRaises(ValueError):
                    installer.installed_state(root)

    def test_resolution_binds_exact_installed_versions_to_verified_database_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            root, source = directory / "root", directory / "source"
            sync = root / "var/lib/pacman/sync"
            sync.mkdir(parents=True)
            for name in ("distro", "core", "extra", "multilib"):
                with tarfile.open(sync / (name + ".db"), "w") as archive:
                    if name == "extra":
                        data = ("%NAME%\nmesa\n\n%VERSION%\n1-1\n\n%SHA256SUM%\n" + "b" * 64 + "\n").encode()
                        member = tarfile.TarInfo("mesa-1-1/desc")
                        member.size = len(data)
                        archive.addfile(member, io.BytesIO(data))
            hashes = {name: hashlib.sha256((sync / (name + ".db")).read_bytes()).hexdigest()
                      for name in ("core", "extra", "multilib")}
            bootstrap.write(source / "distro/repo/archive.lock.json", json.dumps({"databases": hashes}))
            installed = {"mesa": {"version": "1-1", "reason": "explicit"}}
            with patch.object(installer, "ROOT", source):
                repositories, resolved = installer.locked_packages(root, installed)
                self.assertEqual(resolved["mesa"], {"version": "1-1", "repository": "extra", "sha256": "b" * 64})
                self.assertEqual(repositories["extra"], "sha256:" + hashes["extra"])
                with self.assertRaisesRegex(ValueError, "exact approved"):
                    installer.locked_packages(root, {"mesa": {"version": "2-1"}})
                with (sync / "extra.db").open("ab") as stream:
                    stream.write(b"tampered")
                with self.assertRaisesRegex(ValueError, "approved archive"):
                    installer.locked_packages(root, installed)


if __name__ == "__main__":
    unittest.main()
