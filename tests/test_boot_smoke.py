import argparse
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("boot_smoke", Path(__file__).resolve().parents[1] / "scripts/boot-smoke.py")
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class AccelerationTests(unittest.TestCase):
    def test_acceleration_is_explicit_and_never_falls_back(self):
        args = argparse.Namespace(iso=Path("test.iso"), ovmf_code=Path("code.fd"), log=Path("serial.log"), accel="kvm", gpu="virtio-vga")
        command = boot.qemu_command(args, Path("vars.fd"))
        self.assertIn("q35,accel=kvm", command)
        self.assertIn("host", command)
        self.assertFalse(any("tcg" in part for part in command))
        args.accel = "tcg"
        command = boot.qemu_command(args, Path("vars.fd"))
        self.assertIn("q35,accel=tcg", command)
        self.assertNotIn("host", command)
        args.gpu = "VGA"
        command = boot.qemu_command(args, Path("vars.fd"))
        self.assertEqual(command[command.index("-device") + 1], "VGA")
