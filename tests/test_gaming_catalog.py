import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gaming_catalog", ROOT / "scripts/gaming_catalog.py")
gaming = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gaming)


class GamingCatalogTests(unittest.TestCase):
    def test_snapshot_and_optional_boundaries(self):
        catalog = json.loads(gaming.CATALOG.read_text())
        base = json.loads((ROOT / "distro/repo/archive.lock.json").read_text())
        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(catalog["archive_date"], base["archive_date"])
        self.assertTrue(base["databases"].items() <= catalog["databases"].items())
        self.assertEqual({name for profile in catalog["profiles"].values() for name in profile},
                         catalog["packages"].keys())
        for name, record in catalog["packages"].items():
            self.assertRegex(record["sha256"], r"^[a-f0-9]{64}$")
            self.assertIn(record["repository"], catalog["databases"])
        for optional in ["gamescope", "lutris", "obs-studio", "mangohud", "gamemode"]:
            self.assertNotIn(optional, catalog["profiles"]["core"])
            for manifest in ["distro/installed/packages.x86_64", "distro/archiso/packages.x86_64"]:
                self.assertNotIn(optional, (ROOT / manifest).read_text().splitlines())

    def test_verifier_rejects_drift_missing_and_tampering(self):
        raw = io.BytesIO()
        desc = b"%NAME%\nsteam\n\n%VERSION%\n1-1\n\n%SHA256SUM%\nabc\n\n%DEPENDS%\nlib32-glibc\n"
        with tarfile.open(fileobj=raw, mode="w:gz") as archive:
            member = tarfile.TarInfo("steam-1-1/desc")
            member.size = len(desc)
            archive.addfile(member, io.BytesIO(desc))
        data = raw.getvalue()
        catalog = {"databases": {"multilib": hashlib.sha256(data).hexdigest()}, "packages": {
            "steam": {"repository": "multilib", "version": "1-1", "sha256": "abc",
                      "depends": ["lib32-glibc"], "provides": []}}}
        self.assertEqual(gaming.verify_database(data, "multilib", catalog), 1)
        with self.assertRaises(ValueError):
            gaming.verify_database(data + b"tampered", "multilib", catalog)
        catalog["packages"]["steam"]["version"] = "2-1"
        with self.assertRaises(ValueError):
            gaming.verify_database(data, "multilib", catalog)
        catalog["packages"]["missing"] = catalog["packages"].pop("steam")
        with self.assertRaises(ValueError):
            gaming.verify_database(data, "multilib", catalog)

    def test_source_package_includes_embedded_catalog(self):
        spec = importlib.util.spec_from_file_location("gaming_bootstrap", ROOT / "scripts/bootstrap.py")
        bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp, patch.object(bootstrap, "run"):
            target = Path(temp) / "source"
            bootstrap.prepare_package(target)
            with tarfile.open(target / "platform.tar.xz") as archive:
                self.assertEqual(archive.extractfile("platform/crates/distroctl/src/gaming/catalog.json").read(),
                                 gaming.CATALOG.read_bytes())
