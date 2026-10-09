"""Graphics package policy tests; no host package changes or hardware claims."""
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("graphics_installer", ROOT / "scripts/installer.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
spec = importlib.util.spec_from_file_location("graphics_packages", ROOT / "scripts/check-graphics-packages.py")
package_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_check)


class GraphicsPackages(unittest.TestCase):
    def test_metadata_check_rejects_changed_dependencies_and_database_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "distro/repo").mkdir(parents=True)
            (root / "distro/graphics").mkdir()
            metadata = dict(repository="core", version="1-1", depends=["glibc"], provides=[],
                            conflicts=[], sha256="a" * 64, filename="fixture.pkg.tar.zst")
            fields = dict(NAME="fixture", VERSION="1-1", DEPENDS="glibc", SHA256SUM="a" * 64,
                          FILENAME="fixture.pkg.tar.zst")
            data = "".join(f"%{key}%\n{value}\n\n" for key, value in fields.items()).encode()
            with tarfile.open(root / "core.db", "w:gz") as archive:
                member = tarfile.TarInfo("fixture-1-1/desc")
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            lock = dict(archive_date="2026/10/01", databases={"core": hashlib.sha256((root / "core.db").read_bytes()).hexdigest()},
                        direct_packages={"fixture": "1-1"})
            (root / "distro/repo/archive.lock.json").write_text(json.dumps(lock))
            graphics = dict(archive_date="2026/10/01", packages={"fixture": metadata})
            path = root / "distro/graphics/packages.lock.json"
            path.write_text(json.dumps(graphics))
            (root / "distro/graphics/bundles.json").write_text("{}")
            with patch.object(package_check, "ROOT", root):
                self.assertEqual(package_check.check(root)["verified_packages"], 1)
                metadata["depends"] = ["wrong-dependency"]
                path.write_text(json.dumps(graphics))
                with self.assertRaisesRegex(ValueError, "metadata mismatch"):
                    package_check.check(root)
                (root / "core.db").write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    package_check.check(root)

    def test_bundle_selection_and_multilib_are_coherent(self):
        bundles = json.loads((ROOT / "distro/graphics/bundles.json").read_text())
        archive = json.loads((ROOT / "distro/repo/archive.lock.json").read_text())
        graphics = json.loads((ROOT / "distro/graphics/packages.lock.json").read_text())
        self.assertEqual(archive["archive_date"], graphics["archive_date"])
        self.assertEqual(set(archive["databases"]), {"core", "extra", "multilib"})
        self.assertEqual(set(installer.graphics_packages([])), set(bundles["base"]))
        self.assertNotIn("vulkan-intel", installer.graphics_packages([]))
        selected = installer.graphics_packages(["amd", "intel", "amd"])
        self.assertEqual(selected, sorted(set(bundles["base"] + bundles["bundles"]["amd"] + bundles["bundles"]["intel"])))
        self.assertNotIn("nvidia-utils", selected)
        for name, metadata in graphics["packages"].items():
            self.assertEqual(archive["direct_packages"][name], metadata["version"])
        for family in ("intel", "radeon", "nouveau", "virtio", "swrast"):
            self.assertEqual(graphics["packages"]["vulkan-" + family]["version"], graphics["packages"]["lib32-vulkan-" + family]["version"])
        self.assertNotIn("vulkan-swrast", installer.graphics_packages(["virtio"]))
        self.assertIn("lib32-vulkan-swrast", installer.graphics_packages(["software"]))

    def test_gaming_image_selection_preserves_optional_and_mutation_boundaries(self):
        self.assertEqual(installer.gaming_packages([]), [])
        core = installer.gaming_packages(["core", "core"])
        self.assertIn("steam", core)
        self.assertNotIn("gamescope", core)
        tools = installer.gaming_packages(["tools"])
        self.assertNotIn("steam", tools)
        self.assertIn("lib32-mangohud", tools)
        self.assertEqual(installer.gaming_packages(["core", "tools"]), sorted(set(core + tools)))
        for feature in ["heroic", "unknown", "core\nSigLevel=Never"]:
            with self.assertRaises(ValueError):
                installer.gaming_packages([feature])

    def test_nvidia_activation_and_unknown_bundles_are_refused(self):
        for name in ["nvidia-open", "nvidia", "unknown", "amd\nSigLevel=Never"]:
            with self.assertRaisesRegex(ValueError, "unsupported graphics bundle"):
                installer.graphics_packages([name])
        support = json.loads((ROOT / "distro/graphics/nvidia-open.json").read_text())
        self.assertEqual(support["version"], "615.71.09")
        self.assertIn("0x1e04", support["device_ids"])
        self.assertNotIn("0x1b80", support["device_ids"])
        self.assertEqual(len(support["device_ids"]), len(set(support["device_ids"])))

    def test_live_installed_and_signature_boundaries(self):
        live = (ROOT / "distro/archiso/packages.x86_64").read_text().split()
        installed = (ROOT / "distro/installed/packages.x86_64").read_text().split()
        self.assertIn("vulkan-nouveau", live)
        self.assertNotIn("vulkan-nouveau", installed)
        self.assertIn("lib32-vulkan-icd-loader", installed)
        config = (ROOT / "distro/archiso/pacman.conf.in").read_text()
        self.assertEqual(config.count("https://archive.archlinux.org/repos/@@ARCHIVE@@/$repo/os/$arch"), 3)
        self.assertIn("SigLevel = Required DatabaseRequired", config)
        self.assertIn("LocalFileSigLevel = Required", config)
        self.assertNotIn("TrustAll", config)

    @unittest.skipUnless(os.name == "posix" and shutil.which("cc") and Path("/usr/include/vulkan/vulkan.h").exists(),
                         "requires C compiler and Vulkan headers; isolated native check also documented")
    def test_native_probe_build_and_protocol(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "probe"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(ROOT / "scripts/graphics-probe.c"), "-ldl", "-o", str(binary)], check=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True, timeout=25)
            report = json.loads(result.stdout)
            self.assertEqual(report["schema_version"], 1)
            self.assertEqual(report["architecture"], 64)
            self.assertIn(report["status"], ["passed", "failed", "absent", "unsupported"])
            for device in report["devices"]:
                if device["device_type"] == 4:
                    self.assertTrue(device["software"])
                self.assertIn(device["rendering"], ["passed", "failed", "unsupported"])
