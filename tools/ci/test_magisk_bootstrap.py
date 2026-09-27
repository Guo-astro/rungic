#!/usr/bin/env python3
"""Exercise first-boot write/reboot boundaries in a temporary path sandbox.

Android labels and the init service still require the full-wipe device test.
Only absolute platform paths and platform utilities are substituted here.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "rungic-magisk-bootstrap.sh"


class BootstrapTest(unittest.TestCase):
    def test_clean_data_and_existing_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = root / "bin"
            binaries.mkdir()
            for name, body in {
                "chown": ":", "chcon": ":", "sync": ":",
                "getprop": 'echo "${TEST_BOOT_COMPLETED:-0}"',
                "setprop": 'printf "%s\\n" "$*" >> "$TEST_REBOOTS"',
            }.items():
                p = binaries / name
                p.write_text("#!/bin/sh\n" + body + "\n")
                p.chmod(0o755)
            seed = root / "product/etc/magisk-prebuilt"
            seed.mkdir(parents=True)
            names = ("busybox", "magiskboot", "magiskinit", "magiskpolicy",
                     "util_functions.sh", "boot_patch.sh")
            for name in names:
                (seed / name).write_text("seed-" + name)
            service = root / "product/etc/rungic/firstboot-service.sh"
            service.parent.mkdir()
            service.write_text("#!/system/bin/sh\nexit 0\n")
            script = root / "tmpfs/bootstrap.sh"
            script.parent.mkdir()
            text = SOURCE.read_text().replace(
                "export PATH=/system/bin:/system/xbin",
                f"export PATH={binaries}:/usr/bin:/bin")
            for prefix in ("/product/", "/data/", "/dev/kmsg"):
                text = text.replace(prefix, str(root) + prefix)
            (root / "dev").mkdir()
            script.write_text(text)
            reboots = root / "reboots"
            env = dict(os.environ, TEST_REBOOTS=str(reboots))

            def run(stage, completed="0"):
                return subprocess.run(["sh", str(script), stage],
                                      env=dict(env, TEST_BOOT_COMPLETED=completed),
                                      capture_output=True, text=True)

            self.assertEqual(run("early").returncode, 0)
            self.assertFalse((root / "data").exists(), "early stage wrote to clean data")
            self.assertFalse(reboots.exists())
            self.assertNotEqual(run("late").returncode, 0)
            self.assertFalse((root / "data").exists(), "late stage ignored boot completion")
            manager = root / "data/app/random/com.topjohnwu.magisk-test/base.apk"
            manager.parent.mkdir(parents=True)
            manager.touch()
            late = run("late", "1")
            self.assertEqual(late.returncode, 0, late.stderr)
            self.assertEqual(reboots.read_text().splitlines(), ["sys.powerctl reboot"])
            self.assertTrue((root / "data/adb/service.d/00-rungic-firstboot.sh").exists())
            self.assertEqual(run("late", "1").returncode, 0)
            runtime = root / "data/adb/magisk"
            (runtime / "busybox").write_text("upgraded-runtime")
            (runtime / "magiskboot").unlink()
            self.assertEqual(run("early").returncode, 0)
            self.assertEqual((runtime / "busybox").read_text(), "upgraded-runtime")
            self.assertEqual((runtime / "magiskboot").read_text(), "seed-magiskboot")
            self.assertEqual(run("late", "1").returncode, 0)
            self.assertEqual(len(reboots.read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
