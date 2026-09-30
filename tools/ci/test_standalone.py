"""Independent payload corruption and wrong-device checks; no ADB operations."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from standalone import FILES, digest, preflight, verify


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in FILES:
            (self.root / name).write_text('fixture')
        self.manifest = {'schema': 1, 'kind': 'rungic-standalone', 'release': 'test.1',
                         'files': {n: {'bytes': 7, 'sha256': digest(self.root / n)} for n in FILES}}
        self.save()

    def save(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))

    def test_valid_payload(self):
        self.assertEqual(verify(self.root, digest(self.root / 'manifest.json'))['release'], 'test.1')

    def test_wrong_trusted_manifest_rejected(self):
        with self.assertRaisesRegex(ValueError, 'trusted'):
            verify(self.root, '0' * 64)

    def test_corrupt_or_truncated_component_rejected(self):
        for contents in ('fixturE', ''):
            (self.root / 'host-seed.tar.gz').write_text(contents)
            with self.assertRaisesRegex(ValueError, 'host-seed'):
                verify(self.root)

    def test_file_symlink_rejected(self):
        p = self.root / 'rungic.apk'
        p.unlink(); p.symlink_to(self.root / 'termux.apk')
        with self.assertRaisesRegex(ValueError, 'rungic.apk'):
            verify(self.root)

    def test_traversal_inventory_rejected(self):
        self.manifest['files']['../outside'] = self.manifest['files'].pop('rungic.apk')
        self.save()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            verify(self.root)

    def test_shell_release_rejected(self):
        self.manifest['release'] = 'a;touch /tmp/bad'
        self.save()
        with self.assertRaisesRegex(ValueError, 'release'):
            verify(self.root)

    def test_wrong_device_and_kernel_rejected_before_boot_read(self):
        manifest = dict(fingerprint='expected', product='vantage', kernel_release='6.12',
                        minimum_battery_percent=30, boot_bytes=4096, boot_sha256='good')
        class Fake:
            def __init__(self, fields): self.fields, self.calls = fields, 0
            def shell(self, *args, **kwargs):
                self.calls += 1
                return '\n'.join(self.fields) if self.calls == 1 else 'good  -'
        fields = ['0', 'expected', 'vantage', '6.12', 'Enforcing', '_a', '80']
        self.assertEqual(preflight(Fake(fields), manifest)['slot'], '_a')
        for i, bad in [(0, '2000'), (1, 'wrong'), (2, 'portov'), (3, '6.6'), (4, 'Permissive'), (5, '../bad'), (6, '10')]:
            wrong = fields.copy(); wrong[i] = bad; device = Fake(wrong)
            with self.subTest(field=i), self.assertRaises(ValueError):
                preflight(device, manifest)
            self.assertEqual(device.calls, 1)
        manifest['boot_sha256'] = 'different'
        with self.assertRaisesRegex(ValueError, 'boot image'):
            preflight(Fake(fields), manifest)


class BootCompatibilityTests(unittest.TestCase):
    def test_old_product_caller_selects_managed_release_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            managed = root / 'rungic-install'
            payload = managed / 'payload'
            payload.mkdir(parents=True)
            legacy = root / 'rungic-install-legacy'
            legacy.mkdir()
            (legacy / 'firstboot.sh').write_text('echo legacy\n')
            (payload / 'firstboot.sh').write_text('echo managed\n')
            script = Path(__file__).with_name('rungic-install-boot-dispatch.sh').read_text()
            script = script.replace('/system/bin/sh', '/bin/sh').replace('/data/adb', str(root))
            def invoke():
                return subprocess.run(['/bin/sh'], input=script, text=True, capture_output=True)
            self.assertEqual(invoke().stdout.strip(), 'legacy')
            (managed / 'active.env').write_text('RELEASE_ID=test.1\n')
            self.assertEqual(invoke().stdout.strip(), 'managed')
            (payload / 'firstboot.sh').unlink()
            failed = invoke()
            self.assertNotEqual(failed.returncode, 0)
            self.assertNotIn('legacy', failed.stdout)



if __name__ == '__main__':
    unittest.main()
