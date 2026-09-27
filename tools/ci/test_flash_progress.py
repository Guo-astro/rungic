#!/usr/bin/env python3
"""Check live fastboot output and timeouts without touching a device."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

spec = importlib.util.spec_from_file_location("flash_release", Path(__file__).with_name("flash_release.py"))
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)


class ProgressTest(unittest.TestCase):
    def setUp(self):
        work = Path(__file__).resolve().parents[2] / ".work/tests"
        work.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="flash-progress-", dir=work)
        self.root = Path(self.temp.name)
        (self.root / "bin").mkdir()
        executable = self.root / "bin/fastboot"
        executable.write_text("""#!/usr/bin/env python3
import sys,time
mode=sys.argv[3]
if mode=='getvar':
 print('(bootloader) version-bootloader[0]: abc')
 print('(bootloader) version-bootloader[1]: def')
elif mode=='fail':
 print('FAILED (device refused)',flush=True)
 sys.exit(1)
else:
 print('Sending part 1/2',flush=True)
 time.sleep(1 if mode=='stream' else 30)
 print('Writing OKAY',flush=True)
""")
        executable.chmod(0o755)
        self.device = flash.Device(self.root, "TEST", {}, "abcdef")

    def tearDown(self):
        self.device.log.close()
        self.temp.cleanup()

    def test_stream_is_visible_before_process_finishes(self):
        results = []
        thread = threading.Thread(target=lambda: results.append(self.device.run("stream", timeout=3)))
        thread.start()
        deadline = time.monotonic() + .8
        while "Sending part" not in (self.root / "flash.log").read_text() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIn("Sending part", (self.root / "flash.log").read_text())
        self.assertTrue(thread.is_alive())
        thread.join(3)
        self.assertIn("Writing OKAY", results[0])

    def test_timeout_and_device_failure_stop_the_command(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.device.run("slow", timeout=.15)
        with self.assertRaises(RuntimeError):
            self.device.run("fail", timeout=3)

    def test_segmented_identity_remains_parseable(self):
        self.assertEqual(self.device.var("version-bootloader"), "abcdef")


if __name__ == "__main__":
    unittest.main()
