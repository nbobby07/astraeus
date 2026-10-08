"""Run with python -m unittest discover -s tests -v."""
import importlib.util
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap", ROOT / "scripts/bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def database(version="1-1", package=b"fixture"):
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w:gz") as tar:
        desc = (f"%NAME%\nfixture\n\n%VERSION%\n{version}\n\n"
                "%FILENAME%\nfixture.pkg.tar.zst\n\n%ARCH%\nx86_64\n\n"
                f"%CSIZE%\n{len(package)}\n\n%ISIZE%\n20\n\n"
                f"%SHA256SUM%\n{hashlib.sha256(package).hexdigest()}\n").encode()
        entry = tarfile.TarInfo(f"fixture-{version}/desc")
        entry.size = len(desc)
        tar.addfile(entry, io.BytesIO(desc))
    return content.getvalue()


class BootstrapTests(unittest.TestCase):
    def test_package_archive_contains_generation_gate_and_recovery_guide(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(bootstrap, "run"):
            output = Path(temp) / "package"
            bootstrap.prepare_package(output)
            with tarfile.open(output / "platform.tar.xz") as archive:
                for name in ["distro/installed/astraeus-bless-boot.conf", "docs/boot-generations.md",
                             "crates/snapshots/src/system/generations.rs"]:
                    self.assertEqual(archive.extractfile("platform/" + name).read(), (ROOT / name).read_bytes())

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
                self.assertIn(f"Server = {(output / 'archive').as_uri()}", build_config)
                self.assertNotIn("\nServer = https://archive.archlinux.org", build_config)
                self.assertIn("\nCacheServer = https://archive.archlinux.org", build_config)
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

    def archive_fixture(self, root, content):
        lock = dict(archive_date=bootstrap.project()["build"]["archive_date"],
                    databases={"core": hashlib.sha256(content).hexdigest()},
                    direct_packages={"fixture": "1-1"})
        bootstrap.write(root / "distro/repo/archive.lock.json", bootstrap.json.dumps(lock))

    def test_archive_retains_only_verified_bytes_and_checks_consumed_hash(self):
        content = database()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.archive_fixture(root, content)

            def download(*args, **kwargs):
                if args == ("curl", "--version"):
                    return SimpleNamespace(stdout="curl 8.4.0")
                self.assertIn("--max-filesize", args)
                self.assertIn("--max-time", args)
                self.assertEqual(kwargs["timeout"], 65)
                Path(args[args.index("--output") + 1]).write_bytes(content)

            with patch.object(bootstrap, "ROOT", root), \
                    patch.object(bootstrap, "upstream_packages", return_value={"fixture"}), \
                    patch.object(bootstrap, "run", side_effect=download) as run:
                hashes = bootstrap.check_archive(root / "archive")
                self.assertEqual(run.call_count, 2)
                bootstrap.verify_archive_files(root / "archive", hashes)
                target = root / "archive/core.db"
                self.assertEqual(target.read_bytes(), content)
                target.chmod(0o644)
                target.write_bytes(database("2-1"))
                with self.assertRaisesRegex(ValueError, "changed"):
                    bootstrap.verify_archive_files(root / "archive", hashes)
                self.archive_fixture(root, b"wrong digest")
                with self.assertRaisesRegex(ValueError, "changed"):
                    bootstrap.check_archive(root / "rejected")
                self.assertFalse((root / "rejected/core.db").exists())

    @unittest.skipUnless(shutil.which("curl"), "requires curl")
    def test_archive_download_rejects_declared_streamed_and_slow_responses(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                if self.path == "/declared":
                    self.send_header("Content-Length", "2048")
                self.end_headers()
                try:
                    for _ in range(300):
                        self.wfile.write(b"x" * (1 if self.path == "/slow" else 128))
                        self.wfile.flush()
                        time.sleep(0.01)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for kind in ["declared", "streamed", "slow"]:
                with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    self.archive_fixture(root, database())

                    def download(*args, **kwargs):
                        if args == ("curl", "--version"):
                            return subprocess.run(args, check=True, **kwargs)
                        # Exercise real curl limits against loopback HTTP, with a short test deadline.
                        command = [str(arg) for arg in args]
                        command = ["=http" if arg == "=https" else arg for arg in command]
                        command[command.index("--max-time") + 1] = "0.2"
                        command[-1] = f"http://127.0.0.1:{server.server_port}/{kind}"
                        return subprocess.run(command, check=True, capture_output=True, **kwargs)

                    with patch.object(bootstrap, "ROOT", root), \
                            patch.object(bootstrap, "ARCHIVE_DB_LIMIT", 1024), \
                            patch.object(bootstrap, "upstream_packages", return_value={"fixture"}), \
                            patch.object(bootstrap, "run", side_effect=download):
                        start = time.monotonic()
                        with self.assertRaises(subprocess.CalledProcessError) as caught:
                            bootstrap.check_archive(root / "archive")
                        self.assertEqual(caught.exception.returncode, 28 if kind == "slow" else 63)
                        self.assertLess(time.monotonic() - start, 3)
                        self.assertFalse((root / "archive/core.db").exists())
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    @unittest.skipUnless(os.name != "nt" and shutil.which("pacman") and os.geteuid() == 0,
                         "requires Linux pacman as root for isolated database sync")
    def test_pacman_resolves_both_roots_from_verified_local_metadata(self):
        requests = []
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            info = b"pkgname = fixture\npkgver = 1-1\npkgdesc = test\narch = x86_64\nsize = 20\n"
            entry = tarfile.TarInfo(".PKGINFO")
            entry.size = len(info)
            tar.addfile(entry, io.BytesIO(info))
        package = buffer.getvalue()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(package if self.path == "/fixture.pkg.tar.zst" else database("9-9"))

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                archive = root / "archive"
                archive.mkdir()
                content = database(package=package)
                (archive / "core.db").write_bytes(content)
                remote = f"https://archive.archlinux.org/repos/{bootstrap.project()['build']['archive_date']}/$repo/os/$arch"
                config = bootstrap.pinned_archive_config(
                    "[options]\nArchitecture = x86_64\nSigLevel = Never\n"
                    "XferCommand = /usr/bin/curl -fL -o %o %u\n"
                    f"[core]\nServer = {remote}\n", archive)
                config = config.replace(remote, f"http://127.0.0.1:{server.server_port}")
                (root / "pacman.conf").write_text(config)
                for name in ["payload", "iso"]:
                    db = root / name
                    db.mkdir()
                    cache = db / "cache"
                    cache.mkdir()
                    command = ["pacman", "--config", str(root / "pacman.conf"),
                               "--dbpath", str(db), "--cachedir", str(cache),
                               "--logfile", str(root / "pacman.log")]
                    subprocess.run([*command, "-Sy"], check=True, capture_output=True)
                    self.assertEqual((db / "sync/core.db").read_bytes(), content)
                    result = subprocess.run([*command, "-Sp", "--print-format", "%v", "fixture"],
                                            check=True, capture_output=True, text=True)
                    self.assertEqual(result.stdout.strip(), "1-1")
                    result = subprocess.run([*command, "-Sw", "--noconfirm", "fixture"],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((cache / "fixture.pkg.tar.zst").read_bytes(), package)
                self.assertEqual(requests, ["/fixture.pkg.tar.zst"] * 2,
                                 "remote packages remain usable without fetching remote metadata")
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
