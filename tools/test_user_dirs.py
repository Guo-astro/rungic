#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'system/user-dirs'

class UserDirsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.mountpoint = self.bin / 'mountpoint'
        self.mountpoint.write_text('#!/bin/sh\nexit 0\n')
        self.mountpoint.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / '.config'),
                        LC_ALL='C', PATH=str(self.bin) + ':/usr/bin:/bin')

    def run_helper(self, success=True):
        result = subprocess.run([str(SCRIPT)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def test_fresh_home_and_repeat(self):
        self.run_helper()
        first = (self.home / '.config/user-dirs.dirs').read_text()
        self.run_helper()
        self.assertEqual(first, (self.home / '.config/user-dirs.dirs').read_text())
        for name in ('Downloads', 'Music', 'Pictures', 'Videos', 'Templates', 'Public'):
            self.assertEqual(os.readlink(self.home / name), 'Shared/' + name)
            self.assertTrue((self.home / name).is_dir())
        for name in ('Desktop', 'Documents'):
            self.assertTrue((self.home / name).is_dir())
            self.assertFalse((self.home / name).is_symlink())
        self.assertIn('XDG_PICTURES_DIR="$HOME/Pictures"', first)
        self.assertEqual(sum(line.startswith('XDG_') for line in first.splitlines()), 8)

    def test_existing_content_and_link_preserved(self):
        (self.home / 'Downloads').mkdir()
        (self.home / 'Downloads/keep.txt').write_text('user data')
        (self.home / 'Albums').mkdir()
        (self.home / 'Pictures').symlink_to('Albums')
        self.run_helper()
        self.assertEqual((self.home / 'Downloads/keep.txt').read_text(), 'user data')
        self.assertFalse((self.home / 'Downloads').is_symlink())
        self.assertEqual(os.readlink(self.home / 'Pictures'), 'Albums')

    def test_unmounted_storage_refused_without_false_directories(self):
        self.mountpoint.write_text('#!/bin/sh\nexit 1\n')
        self.run_helper(False)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_conflicting_file_is_not_deleted(self):
        (self.home / 'Pictures').write_text('keep')
        self.run_helper(False)
        self.assertEqual((self.home / 'Pictures').read_text(), 'keep')

if __name__ == '__main__':
    unittest.main()
