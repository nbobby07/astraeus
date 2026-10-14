"""Exercise the profile's actual image tools against different build timestamps."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name != "nt" and os.geteuid() == 0
                     and shutil.which("mksquashfs") and shutil.which("xorriso"),
                     "requires root Linux image tools")
class ImageDeterminismTests(unittest.TestCase):
    def test_cache_and_build_time_do_not_change_image_bytes(self):
        profile = Path(__file__).resolve().parents[1] / "distro/archiso/profiledef.sh.in"
        with tempfile.TemporaryDirectory() as temp:
            outputs = []
            for index in range(2):
                out = Path(temp) / str(index)
                root = out / "root"
                cache = root / "var/cache/ldconfig/aux-cache"
                cache.parent.mkdir(parents=True)
                cache.write_text(f"build-specific cache {index}\n")
                (root / "payload").write_text("same payload\n")
                # Model ArchISO after cleanup: local records remain, sync is absent,
                # and verified public metadata lives outside the image source.
                (root / "var/lib/pacman/local").mkdir(parents=True)
                seed = out / "profile/pacman-sync"
                seed.mkdir(parents=True)
                checks = []
                for name in ["core.db", "distro.db", "distro.db.sig", "extra.db", "multilib.db"]:
                    content = (name + " fixture\n").encode()
                    (seed / name).write_bytes(content)
                    checks.append(hashlib.sha256(content).hexdigest() + "  " + name + "\n")
                (seed / "SHA256SUMS").write_text("".join(checks))
                for path in [root, *root.rglob("*")]:
                    os.utime(path, (1790812800 + index + 10,) * 2)
                result = subprocess.run(["bash", "-euc", 'declare -A file_permissions; source "$1"; '
                                'profile="$2/profile"; pacstrap_dir="$2/root"; '
                                'mksquashfs "$2/root" "$2/root.sfs" -noappend -no-progress -processors 1; '
                                'touch -m -d "@$3" "$2/root.sfs"; '
                                'xorriso -as mkisofs -quiet -r -o "$2/test.iso" "$2/root.sfs"',
                                "test", str(profile), str(out), str(1790812810 + index)],
                               env=dict(os.environ, SOURCE_DATE_EPOCH="1790812800"),
                               capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                outputs.append((out / "test.iso").read_bytes())
            self.assertEqual(*outputs)
