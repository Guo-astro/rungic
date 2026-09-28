#!/usr/bin/env python3
"""Prevent host Python cache paths from reserving logins in release images."""
import tempfile
import unittest
from pathlib import Path
from arm64_chroot import guest_environment
from build_rootfs_image import check_home_layout, check_fresh_account

class RootfsIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'home/rungic').mkdir(parents=True)

    def seed_accounts(self):
        (self.root / 'etc').mkdir()
        (self.root / 'etc/passwd').write_text('root:x:0:0::/root:/bin/sh\nrungic:x:1000:1000::/home/rungic:/bin/sh\n')
        (self.root / 'etc/shadow').write_text('root:*:0::::::\nrungic:!:0::::::\n')

    def test_clean_identity(self):
        self.seed_accounts()
        check_fresh_account(self.root)

    def test_unlocked_account_rejected_without_hash_in_error(self):
        self.seed_accounts()
        (self.root / 'etc/shadow').write_text('root:*:0::::::\nrungic:secret-hash:0::::::\n')
        with self.assertRaisesRegex(ValueError, 'passwords must be locked') as error:
            check_fresh_account(self.root)
        self.assertNotIn('secret-hash', str(error.exception))

    def test_old_account_marker_rejected(self):
        self.seed_accounts()
        marker = self.root / 'var/lib/rungic-host/account.json'
        marker.parent.mkdir(parents=True)
        marker.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'completion marker'):
            check_fresh_account(self.root)

    def test_auth_credentials_rejected(self):
        self.seed_accounts()
        token = self.root / 'home/rungic/.codex/auth.json'
        token.parent.mkdir()
        token.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'credentials'):
            check_fresh_account(self.root)

    def test_extra_personal_account_rejected(self):
        self.seed_accounts()
        with (self.root / 'etc/passwd').open('a') as f:
            f.write('builder:x:1001:1001::/home/builder:/bin/sh\n')
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            check_fresh_account(self.root)

    def test_clean_template(self):
        check_home_layout(self.root, '/home/rungic')

    def test_host_cache_home_rejected(self):
        cache = self.root / 'home/builder/project/.work/cache/python'
        cache.mkdir(parents=True)
        (cache / 'module.pyc').write_bytes(b'cache')
        with self.assertRaisesRegex(ValueError, 'builder'):
            check_home_layout(self.root, '/home/rungic')

    def test_legacy_alias(self):
        alias = self.root / 'home/linux'
        for target in ('rungic', '/home/rungic'):
            alias.symlink_to(target)
            check_home_layout(self.root, '/home/rungic')
            alias.unlink()

    def test_unrelated_alias_rejected(self):
        (self.root / 'home/linux').symlink_to('/outside')
        with self.assertRaisesRegex(ValueError, 'linux'):
            check_home_layout(self.root, '/home/rungic')

    def test_template_cannot_escape_tree(self):
        home = self.root / 'home/rungic'
        home.rmdir()
        home.symlink_to('/tmp')
        with self.assertRaisesRegex(ValueError, 'real directory'):
            check_home_layout(self.root, '/home/rungic')

    def test_host_python_settings_removed_without_losing_proxy(self):
        host = {'PYTHONPYCACHEPREFIX': '/home/builder/.cache',
                'PYTHONPATH': '/host/modules', 'PYTHONHOME': '/host/python',
                'HOME': '/home/builder', 'https_proxy': 'http://proxy.invalid:6152'}
        env = guest_environment(host)
        self.assertFalse(any(key.startswith('PYTHON') for key in env))
        self.assertEqual(env['HOME'], '/root')
        self.assertEqual(env['https_proxy'], host['https_proxy'])
        self.assertIn('PYTHONPYCACHEPREFIX', host)

if __name__ == '__main__':
    unittest.main()
