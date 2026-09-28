#!/usr/bin/env python3
"""Run firstboot's optional casting install (docs/58) in a temporary path sandbox.

The archive holds the host seed's rungic-wfd entries as build_host_seed.py lays
them out. Only absolute platform paths and platform utilities are substituted;
SELinux labels and the Magisk service.d start still need the full-wipe device test.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_host_seed  # noqa: E402

FIRSTBOOT = HERE / "rungic-firstboot.sh"


def cast_section():
    text = FIRSTBOOT.read_text()
    match = re.search(r"# Casting \(docs/58\).*?install failed \(optional\)'; fi\nfi\n", text, re.S)
    if not match:
        raise AssertionError("casting section not found in rungic-firstboot.sh")
    return match.group(0)


class FirstbootCastTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        stubs = self.root / "bin"
        stubs.mkdir()
        for name in ("chcon", "restorecon"):
            (stubs / name).write_text("#!/bin/sh\n:\n")
            (stubs / name).chmod(0o755)
        busybox = self.root / "data/adb/magisk/busybox"
        busybox.parent.mkdir(parents=True)
        busybox.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$TEST_STARTS"\n')
        busybox.chmod(0o755)
        self.starts = self.root / "starts"
        self.env = dict(os.environ, PATH=f"{stubs}:{os.environ['PATH']}", TEST_STARTS=str(self.starts))

    def tearDown(self):
        self.directory.cleanup()

    def seed(self, with_jar=True):
        tree = self.root / "seed-tree"
        for source, dest, mode in build_host_seed.ANDROID_FILES:
            if not dest.startswith("rungic-wfd/"):
                continue
            target = tree / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((build_host_seed.ROOT / source).read_bytes())
            target.chmod(mode)
        if with_jar:
            (tree / "rungic-wfd/rungic-cast.jar").write_bytes(b"dex")
        archive = self.root / "product/etc/rungic/host-seed.tar.gz"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(tree / "rungic-wfd", arcname="rungic-wfd")
        return archive.parent

    def run_section(self, seed):
        body = cast_section().replace("/data/adb/", f"{self.root}/data/adb/").replace("/system/bin/sh", "sh")
        script = f"set -eu\nseed={seed}\n{body}wait\necho section-done\n"
        return subprocess.run(["sh", "-c", script], env=self.env, capture_output=True, text=True)

    def test_clean_data(self):
        result = self.run_section(self.seed())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("casting installed", result.stdout)
        wfd = self.root / "data/adb/rungic-wfd"
        self.assertTrue(os.access(wfd / "rungic-cast", os.X_OK))
        self.assertTrue(os.access(wfd / "rungic-cast-watch", os.X_OK))
        self.assertTrue((wfd / "rungic-cast.jar").is_file())
        self.assertTrue((wfd / "wfd.sepolicy.rule").is_file())
        self.assertFalse((wfd / "service.d").exists())
        for script in ("rungic-wfd-sepolicy.sh", "rungic-cast-watch.sh"):
            self.assertTrue(os.access(self.root / "data/adb/service.d" / script, os.X_OK))
        self.assertFalse((self.root / "data/adb/.rungic-wfd-stage").exists())
        self.assertEqual(self.starts.read_text().split(), ["setsid"])

    def test_partial_install_keeps_state(self):
        wfd = self.root / "data/adb/rungic-wfd"
        (wfd / "run").mkdir(parents=True)
        (wfd / "last-sink").write_text("66:57:25:45:fd:a5\nTV\n")
        result = self.run_section(self.seed())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((wfd / "last-sink").read_text(), "66:57:25:45:fd:a5\nTV\n")
        self.assertTrue(os.access(wfd / "rungic-cast", os.X_OK))

    def test_incomplete_seed_is_optional(self):
        result = self.run_section(self.seed(with_jar=False))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("casting install failed (optional)", result.stdout)
        self.assertIn("section-done", result.stdout)
        self.assertFalse((self.root / "data/adb/rungic-wfd").exists())
        self.assertFalse(self.starts.exists())

    def test_installed_is_left_alone(self):
        seed = self.seed()
        self.assertEqual(self.run_section(seed).returncode, 0)
        self.starts.unlink()
        watch = self.root / "data/adb/rungic-wfd/rungic-cast-watch"
        watch.write_text("local change\n")
        result = self.run_section(seed)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("casting", result.stdout)
        self.assertEqual(watch.read_text(), "local change\n")
        self.assertFalse(self.starts.exists())


if __name__ == "__main__":
    unittest.main()
