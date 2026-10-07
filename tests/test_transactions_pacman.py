"""Optional real-pacman contract checks, entirely inside a temporary database.

Set ASTRAEUS_TEST_PACMAN and ASTRAEUS_TEST_PACMAN_CONF to extracted/test binaries,
or run on an Arch host. These tests never refresh or mutate a package database.
"""
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

PACMAN = os.environ.get("ASTRAEUS_TEST_PACMAN") or shutil.which("pacman")
CONF = os.environ.get("ASTRAEUS_TEST_PACMAN_CONF") or shutil.which("pacman-conf")


def desc(**fields):
    return "".join(f"%{key}%\n{value}\n\n" for key, value in fields.items())


@unittest.skipUnless(os.name == "posix" and PACMAN and CONF, "requires real pacman and pacman-conf")
class PacmanContractTests(unittest.TestCase):
    def test_print_resolution_and_expanded_trust_policy_are_read_only(self):
        with tempfile.TemporaryDirectory(prefix="astraeus-pacman-") as directory:
            root = Path(directory)
            for name in ["root", "db/local/linux-1:1-1", "db/sync", "cache", "gpg", "hooks"]:
                (root / name).mkdir(parents=True)
            (root / "db/local/ALPM_DB_VERSION").write_text("9\n")
            (root / "db/local/linux-1:1-1/desc").write_text(desc(NAME="linux", VERSION="1:1-1", SIZE=10, REASON=0, ARCH="any"))
            (root / "db/local/linux-1:1-1/files").write_text("%FILES%\n\n")
            with tarfile.open(root / "db/sync/core.db", "w:gz") as archive:
                for name, version, fields in [
                    ("linux", "1:2-1", {"DEPENDS": "mesa>=3"}),
                    ("mesa", "3-1", {}),
                ]:
                    data = desc(NAME=name, VERSION=version, FILENAME=f"{name}.pkg.tar.zst", ARCH="any",
                                CSIZE=20, ISIZE=30, SHA256SUM="a" * 64, **fields).encode()
                    member = tarfile.TarInfo(f"{name}-{version}/desc")
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            config = root / "pacman.conf"
            config.write_text(f"[options]\nRootDir = {root}/root\nDBPath = {root}/db\n"
                              f"CacheDir = {root}/cache\nGPGDir = {root}/gpg\nLogFile = {root}/pacman.log\n"
                              f"HookDir = {root}/hooks\nArchitecture = x86_64\n"
                              f"SigLevel = Required DatabaseOptional\n[core]\nServer = file://{root}/repo\n")
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            def run(tool, *args):
                result = subprocess.run([tool, "--config", str(config), *args], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result
            query = run(PACMAN, "--query")
            self.assertEqual(query.stdout, "linux 1:1-1\n")
            output = run(PACMAN, "--sync", "--sysupgrade", "--print-format", "%n\t%v\t%r\t%s\t%h\t%H\t%R", "--noconfirm")
            rows = {r.split("\t")[0]: r.split("\t") for r in output.stdout.splitlines()}
            self.assertEqual(set(rows), {"linux", "mesa"})
            self.assertEqual(rows["linux"], ["linux", "1:2-1", "core", "20", "a" * 64, "", ""])
            policy = run(CONF, "--repo", "core", "SigLevel").stdout.split()
            self.assertEqual(policy, [])  # Empty output means global inheritance.
            policy = run(CONF, "SigLevel").stdout.split()
            self.assertIn("PackageRequired", policy)
            self.assertIn("PackageTrustedOnly", policy)
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
