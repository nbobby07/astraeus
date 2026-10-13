"""Removal requires full file content evidence, even when size and mtime were retained."""
import gzip
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "crates/transactions/src/package_integrity.py"
SPEC = importlib.util.spec_from_file_location("package_integrity", SOURCE)
integrity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(integrity)


class PackageIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.owner = patch.object(integrity, "METADATA_UID", getattr(os, "getuid", lambda: 0)())
        self.owner.start()
        self.addCleanup(self.owner.stop)
        self.local = self.root / "var/lib/pacman/local/fixture-1-1"
        self.payload = self.write("usr/share/fixture", b"original")
        self.write("var/lib/pacman/local/fixture-1-1/desc", b"%NAME%\nfixture\n\n%VERSION%\n1-1\n")
        self.write("var/lib/pacman/local/fixture-1-1/files", b"%FILES%\nusr/share/fixture\n")
        self.mtree()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        parent = path.parent
        while parent != self.root:
            parent.chmod(0o755)
            parent = parent.parent
        path.write_bytes(content)
        path.chmod(0o644)
        return path

    def mtree(self, body=None):
        digest = hashlib.sha256(b"original").hexdigest()
        body = body or f"/set type=file uid=0 gid=0 mode=644\n./usr/share/fixture size=8 sha256digest={digest}\n"
        self.write("var/lib/pacman/local/fixture-1-1/mtree", gzip.compress(("#mtree\n" + body).encode(), mtime=0))

    def inspect(self, check=lambda _name, _deadline: None):
        return integrity.inspect_package(self.root, "fixture", "1-1", check=check)

    def test_same_size_content_change_with_restored_mtime_is_retained(self):
        first = self.inspect()
        self.assertTrue(first["removable"], first)
        before = self.payload.stat()
        self.payload.write_bytes(b"modified")
        os.utime(self.payload, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.payload.stat().st_size, before.st_size)
        self.assertEqual(self.payload.stat().st_mtime_ns, before.st_mtime_ns)
        changed = self.inspect()
        self.assertFalse(changed["removable"])
        self.assertIn("content changed", changed["detail"])
        self.assertNotEqual(first["digest"], changed["digest"])
        self.assertEqual(changed, self.inspect())

    def test_missing_malformed_incomplete_and_hashless_mtree_preserve_package(self):
        mtree = self.local / "mtree"
        for content in (None, b"not gzip", gzip.compress(b"not mtree"), gzip.compress(b"#mtree\n"),
                        gzip.compress(b"#mtree\n./usr/share/fixture type=file size=8\n")):
            with self.subTest(content=content):
                if content is None:
                    mtree.unlink()
                else:
                    mtree.write_bytes(content)
                result = self.inspect()
                self.assertFalse(result["removable"], result)

    def test_mtree_must_cover_all_files_and_duplicate_entries_are_refused(self):
        path = self.local / "files"
        path.write_text("%FILES%\nusr/share/fixture\nusr/share/unrecorded\n")
        self.assertIn("complete installed file list", self.inspect()["detail"])
        path.write_text("%FILES%\nusr/share/fixture\nusr/share/fixture\n")
        self.assertIn("invalid installed file list", self.inspect()["detail"])
        path.write_text("%FILES%\nusr/share/fixture\n")
        self.mtree("./usr/share/fixture type=file\n./usr/share/fixture type=file\n")
        self.assertIn("duplicate", self.inspect()["detail"])

    def test_changed_database_identity_and_failed_pacman_check_are_retained(self):
        def fail(_name, _deadline):
            raise ValueError("pacman reported a file mode change")
        result = self.inspect(check=fail)
        self.assertFalse(result["removable"])
        self.assertIn("mode change", result["detail"])
        (self.local / "desc").write_text("%NAME%\nother\n\n%VERSION%\n1-1\n")
        self.assertIn("identity changed", self.inspect()["detail"])

    def test_metadata_change_during_inspection_invalidates_evidence(self):
        def change(_name, _deadline):
            with (self.local / "desc").open("ab") as output:
                output.write(b"\n%DESC%\nchanged\n")
        result = self.inspect(check=change)
        self.assertFalse(result["removable"])
        self.assertIn("metadata changed", result["detail"])

    @unittest.skipUnless(os.name == "posix", "POSIX ownership and modes")
    def test_root_and_unprivileged_preview_use_public_access_eligibility(self):
        for path, mode in ((self.payload, 0o600), (self.payload, 0o666),
                           (self.local / "mtree", 0o600), (self.local, 0o700),
                           (self.payload.parent, 0o775)):
            with self.subTest(path=path, mode=mode):
                original = path.stat().st_mode & 0o777
                path.chmod(mode)
                try:
                    self.assertFalse(self.inspect()["removable"])
                finally:
                    path.chmod(original)
        self.assertTrue(self.inspect()["removable"])

    @unittest.skipUnless(os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0, "root owner check")
    def test_payload_owned_by_another_user_is_preserved(self):
        os.chown(self.payload, 12345, -1)
        self.assertIn("externally owned", self.inspect()["detail"])

    def test_symlinks_are_checked_but_never_followed(self):
        link = self.root / "usr/share/link"
        try:
            link.symlink_to("fixture")
        except OSError as error:
            self.skipTest(str(error))
        with (self.local / "files").open("a") as files:
            files.write("usr/share/link\n")
        digest = hashlib.sha256(b"original").hexdigest()
        self.mtree(f"./usr/share/fixture type=file sha256digest={digest}\n./usr/share/link type=link link=fixture\n")
        self.assertTrue(self.inspect()["removable"])
        link.unlink()
        link.symlink_to("elsewhere")
        self.assertIn("symlink changed", self.inspect()["detail"])
        link.unlink()
        self.payload.unlink()
        self.payload.symlink_to("elsewhere")
        self.assertFalse(self.inspect()["removable"])

    def test_unsafe_mtree_paths_and_expired_work_are_retained(self):
        for path in ("../outside", "/etc/passwd", "usr/../outside", "usr//outside"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                integrity.mtree_entries(gzip.compress(f"#mtree\n{path} type=file\n".encode()))
        result = integrity.inspect_package(self.root, "fixture", "1-1", deadline=time.monotonic() - 1)
        self.assertFalse(result["removable"])
        self.assertIn("time limit", result["detail"])

    def test_octally_escaped_file_names_are_verified(self):
        path = self.root / "usr/share/a file"
        self.payload.rename(path)
        (self.local / "files").write_text("%FILES%\nusr/share/a file\n")
        digest = hashlib.sha256(b"original").hexdigest()
        self.mtree(f"./usr/share/a\\040file type=file sha256digest={digest}\n")
        self.assertTrue(self.inspect()["removable"])


if __name__ == "__main__":
    unittest.main()
