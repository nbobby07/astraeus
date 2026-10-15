"""Desktop distribution and authorization boundaries; never starts a root worker."""
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("desktop_bootstrap", ROOT / "scripts/bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class ControlCenterPackaging(unittest.TestCase):
    def test_packaged_sources_contain_native_app_and_privilege_assets(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bootstrap, "run"):
            output = Path(directory) / "package"
            bootstrap.prepare_package(output)
            with tarfile.open(output / "platform.tar.xz") as archive:
                for relative in ["apps/control-center/CMakeLists.txt", "apps/control-center/Main.qml",
                                 "apps/control-center/controller.cpp", "apps/control-center/tests/controller_test.cpp",
                                 "apps/control-center/tests/tst_control.qml", "apps/control-center/State.js",
                                 "distro/installed/astraeus-apply@.service", "distro/installed/org.astraeus.system.policy",
                                 "docs/control-center.md", "docs/performance.md",
                                 "apps/control-center/PerformancePage.qml", "apps/control-center/performance.cpp",
                                 "apps/control-center/performance.h", "apps/control-center/tests/performance_test.cpp"]:
                    self.assertEqual(archive.extractfile("platform/" + relative).read(), (ROOT / relative).read_bytes())
                for rust in (ROOT / "crates").rglob("*.rs"):
                    for embedded in re.findall(r'include_(?:str|bytes)!\(\s*"([^"\n]+)"\s*\)', rust.read_text()):
                        path = (rust.parent / embedded).resolve()
                        relative = path.relative_to(ROOT).as_posix()
                        with self.subTest(rust=rust.relative_to(ROOT), embedded=relative):
                            self.assertEqual(archive.extractfile("platform/" + relative).read(), path.read_bytes())
            recipe = (output / "PKGBUILD").read_text()
            self.assertIn("package_astraeus-control-center()", recipe)
            self.assertIn("--features native-alpm", recipe)
            self.assertIn("ctest --test-dir target/control-center", recipe)

    def test_packaged_sources_run_the_rust_installer_seed_fixture(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bootstrap, "run"):
            output = Path(directory) / "package"
            bootstrap.prepare_package(output)
            with tarfile.open(output / "platform.tar.xz") as archive:
                archive.extractall(Path(directory) / "extracted", filter="data")
            source = Path(directory) / "extracted/platform"
            test = (source / "crates/transactions/src/generation_tests.rs").read_text()
            fixture = re.search(r'fn installed_image_seed_is_accepted_by_the_actual_rust_management_reader\(\).*?let script = r#"(.*?)"#;', test, re.S)
            self.assertIsNotNone(fixture, "run the exact fixture used by the Rust management-reader test")
            result = subprocess.run([sys.executable, "-I", "-c", fixture.group(1),
                                     str(source / "scripts"), str(Path(directory) / "seed")],
                                    cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_authentication_is_active_session_only_and_never_cached(self):
        policy = ET.parse(ROOT / "distro/installed/org.astraeus.system.policy").getroot()
        action, = policy.findall("action")
        defaults = action.find("defaults")
        self.assertEqual(defaults.findtext("allow_any"), "no")
        self.assertEqual(defaults.findtext("allow_inactive"), "no")
        self.assertEqual(defaults.findtext("allow_active"), "auth_admin")
        annotations = {item.attrib["key"]: item.text for item in action.findall("annotate")}
        self.assertEqual(annotations, {"org.freedesktop.policykit.exec.path": "/usr/bin/distroctl",
                                       "org.freedesktop.policykit.exec.argv1": "system"})
        service = (ROOT / "distro/installed/astraeus-apply@.service").read_text()
        self.assertIn("/usr/bin/distroctl system worker %i", service)
        self.assertIn("Restart=no", service)
        self.assertNotIn("[Install]", service)
        desktop = (ROOT / "apps/control-center/org.astraeus.ControlCenter.desktop").read_text()
        self.assertIn("Exec=astraeus-control-center", desktop)
        self.assertNotIn("pkexec", desktop)

    def test_image_inputs_include_app_without_changing_archive(self):
        for manifest in ["distro/archiso/packages.x86_64", "distro/installed/packages.x86_64"]:
            self.assertEqual(bootstrap.packages(manifest).count("astraeus-control-center"), 1)
        self.assertIn("astraeus-control-center", bootstrap.CUSTOM_PACKAGES)
        lock = bootstrap.json.loads((ROOT / "distro/repo/archive.lock.json").read_text())
        self.assertEqual(set(lock["direct_packages"]), bootstrap.upstream_packages())
        self.assertEqual(lock["archive_date"], bootstrap.project()["build"]["archive_date"])


if __name__ == "__main__":
    unittest.main()
