import copy
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import installer
import provision
import bootstrap
spec = importlib.util.spec_from_file_location("install_smoke", ROOT / "scripts/install-smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class InstallerTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "payload staging needs Unix symlinks")
    def test_payload_does_not_clone_live_accounts_or_boot_workarounds(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            profile = out / "profile"
            live = profile / "airootfs"
            values = dict(NAME="Test", ID="test", VERSION="0.1.0-dev", ARCHIVE="2026/10/01", EPOCH=1790812800, FINGERPRINT="A" * 40)
            installer.stage(live, values, bootstrap.write)
            bootstrap.write(live / "etc/shadow", "live::20000:0:99999:7:::\n")
            bootstrap.write(live / "etc/xdg/kdeglobals", "[General]\n")
            bootstrap.write(live / "etc/systemd/system/systemd-firstboot.service", "live-only mask fixture\n")
            bootstrap.write(live / "opt/distro/repo/distro.db", "signed repo fixture\n")
            bootstrap.write(live / "usr/share/distro/repository-key.asc", "public key fixture\n")
            calls = []
            def run(*args, **kwargs):
                calls.append(args)
                if args[0] == "pacstrap":
                    root = out / "installed-root"
                    bootstrap.write(root / "etc/shadow", "root:!:20100:0:99999:7:::\n")
                    bootstrap.write(root / "etc/resolv.conf", "temporary builder DNS\n")
                    bootstrap.write(root / "boot/initramfs-linux.img", "temporary build initramfs\n")
                    bootstrap.write(root / "var/cache/pacman/pkg/example.pkg.tar.zst", "cache\n")
                    bootstrap.write(root / "var/lib/pacman/local/example/desc", "%INSTALLDATE%\n123456\n")
            installer.build_payload(out, profile, values, run, bootstrap.write, bootstrap.render)
            root = out / "installed-root"
            self.assertNotIn("live:", (root / "etc/shadow").read_text())
            self.assertIn("20727", (root / "etc/shadow").read_text())
            self.assertFalse((root / "etc/systemd/system/systemd-firstboot.service").exists())
            self.assertFalse((root / "usr/share/distro/installer").exists())
            self.assertFalse((root / "boot/initramfs-linux.img").exists())
            self.assertFalse((root / "etc/pacman.d/gnupg").exists())
            self.assertEqual(os.readlink(root / "etc/resolv.conf"), "/run/NetworkManager/resolv.conf")
            self.assertIn("1790812800", (root / "var/lib/pacman/local/example/desc").read_text())
            self.assertIn("SigLevel = Required DatabaseRequired", (root / "etc/pacman.conf").read_text())
            self.assertNotIn("XferCommand", (root / "etc/pacman.conf").read_text())
            self.assertIn("-G", calls[0])
            self.assertEqual(calls[-1][:4], ("env", "-u", "SOURCE_DATE_EPOCH", "mksquashfs"))
            self.assertIn("-all-time", calls[-1])
            if shutil.which("mksquashfs"):
                command = [str(a) for a in calls[-1]]
                env = dict(os.environ, SOURCE_DATE_EPOCH=str(values["EPOCH"]))
                subprocess.run(command, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                first = Path(command[5])
                second = first.with_name("second.sfs")
                os.utime(root / "etc/shadow", (12345, 12345))
                command[5] = str(second)
                subprocess.run(command, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                self.assertEqual(bootstrap.digest(first), bootstrap.digest(second))

    def test_installed_boot_detaches_iso_and_preserves_disk_and_firmware(self):
        install = smoke.qemu_command("code.fd", "vars.fd", "disk.qcow2", "install.log", "qmp.sock", "live.iso")
        boot = smoke.qemu_command("code.fd", "vars.fd", "disk.qcow2", "boot1.log", "qmp.sock")
        self.assertIn("-cdrom", install)
        self.assertNotIn("-cdrom", boot)
        self.assertIn("if=virtio,format=qcow2,file=disk.qcow2", boot)
        self.assertIn("if=pflash,format=raw,file=vars.fd", boot)
        self.assertIn("q35,accel=kvm", boot)
        self.assertFalse(any("vnc" in argument for argument in boot))

    def test_generated_profile_and_account_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            values = {"NAME": "Test OS", "ID": "test-os", "VERSION": "0.1.0-dev"}
            installer.stage(root, values, bootstrap.write)
            settings = json.loads((root / "etc/calamares/settings.conf").read_text())
            branding_dir = root / "etc/calamares/branding/astraeus"
            branding = json.loads((branding_dir / "branding.desc").read_text())
            self.assertTrue(branding["slideshow"])
            self.assertIsInstance(branding["style"], dict)
            for image in branding["slideshow"]:
                self.assertTrue((branding_dir / image).is_file())
            self.assertEqual(settings["sequence"][1]["exec"][-2:], ["astraeus", "umount"])
            mount = json.loads((root / "etc/calamares/modules/mount.conf").read_text())
            self.assertEqual({s["subvolume"]: s["mountPoint"] for s in mount["btrfsSubvolumes"]}, installer.SUBVOLUMES)
            self.assertEqual(json.loads((root / "etc/calamares/modules/partition.conf").read_text())["luksGeneration"], "luks2")
            unpack = json.loads((root / "etc/calamares/modules/unpackfs.conf").read_text())["unpack"][0]
            self.assertEqual(unpack["source"], "/run/archiso/airootfs/opt/distro/install-root.sfs")
            self.assertIn("pkexec /usr/bin/calamares", (root / "usr/share/applications/astraeus-install.desktop").read_text())
            users = json.loads((root / "etc/calamares/modules/users.conf").read_text())
            self.assertFalse(users["doAutologin"])
            self.assertFalse(users["setRootPassword"])
            self.assertNotIn("nopasswdlogin", json.dumps(users))
            self.assertFalse((root / "etc/shadow").exists())

    def test_malformed_configuration_rejected(self):
        base = installer.configuration()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            for change in ["luks1", "duplicate", "missing", "ordering", "autologin"]:
                data = copy.deepcopy(base)
                if change == "luks1": data["modules"]["partition"]["luksGeneration"] = "luks1"
                elif change == "duplicate": data["modules"]["mount"]["btrfsSubvolumes"].append(data["modules"]["mount"]["btrfsSubvolumes"][0])
                elif change == "missing": data["modules"]["mount"]["btrfsSubvolumes"].pop()
                elif change == "ordering": data["settings"]["sequence"][1]["exec"].reverse()
                else: data["modules"]["users"]["doAutologin"] = True
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError): installer.configuration(path)
            path.write_text("{")
            with self.assertRaises(ValueError): installer.configuration(path)

    def test_kernel_parameters_and_uki_inputs(self):
        value = "12345678-1234-1234-1234-123456789abc"
        root = {"fs": "btrfs", "mountPoint": "/", "uuid": value}
        self.assertEqual(provision.kernel_command_line(root), f"root=UUID={value} rootflags=subvol=@ rw")
        root.update(luksMapperName="calamares-root", luksUuid=value)
        self.assertEqual(provision.kernel_command_line(root), f"rd.luks.name={value}=root root=/dev/mapper/root rootflags=subvol=@ rw")
        self.assertEqual(provision.crypttab(f"# root\ncalamares-root UUID={value} none luks\n", root), f"# root\nroot UUID={value} none luks\n")
        with self.assertRaises(ValueError): provision.crypttab("# missing root\n", root)
        for invalid in [None, "", "../disk", value + " quiet", "$(id)"]:
            root["luksUuid"] = invalid
            with self.assertRaises(ValueError): provision.kernel_command_line(root)
        root["fs"] = "ext4"
        with self.assertRaises(ValueError): provision.kernel_command_line(root)
        preset = bootstrap.render((ROOT / "distro/installed/linux.preset.in").read_text(), {"ID": "test"})
        self.assertIn('/efi/EFI/Linux/test-linux.efi', preset)
        self.assertIn('/etc/kernel/cmdline', preset)
        hooks = (ROOT / "distro/installed/mkinitcpio.conf").read_text()
        self.assertIn('keyboard sd-vconsole block sd-encrypt filesystems', hooks)
        self.assertNotIn('archiso', hooks)
        installed = set(bootstrap.packages("distro/installed/packages.x86_64"))
        self.assertTrue({"linux", "mkinitcpio", "systemd-ukify", "distroctl", "sddm", "wireplumber"} <= installed)
        self.assertTrue(installed.isdisjoint({"calamares", "mkinitcpio-archiso", "arch-install-scripts"}))


if __name__ == "__main__":
    unittest.main()
