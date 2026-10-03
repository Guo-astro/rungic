#!/usr/bin/env python3
"""tools/ci/preflight.py against a stand-in phone: the real device spec (G100, portov_cn), an audited
stock extraction made to match it, and adb answers that match or differ in one field. A mismatch
stops before the report is written; only reading commands are ever sent to the phone."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import preflight

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / 'profiles/devices/motorola/portov_cn/W1VT36H.1-51-8.json'
SERIAL = 'ZY32TEST'
READING = {'getprop', 'uname', 'getenforce', 'dumpsys'}


class Preflight(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        spec = json.loads(SPEC.read_text())
        stock = self.root / 'stock'
        stock.mkdir()
        (stock / 'boot.img').write_bytes(b'stock boot')
        spec['stock']['boot_sha256'] = hashlib.sha256(b'stock boot').hexdigest()
        spec['release_requirements']['minimum_host_free_gib'] = 0
        self.spec_data = spec
        identity = spec['identity']
        (stock / 'manifest.json').write_text(json.dumps({
            'archive_sha256': spec['stock']['archive_sha256'], 'fingerprint': identity['fingerprint'],
            'device': identity['device'], 'files': {'boot.img': {'sha256': spec['stock']['boot_sha256']}}}))
        manifest_sha = hashlib.sha256((stock / 'manifest.json').read_bytes()).hexdigest()
        (stock / 'verification.json').write_text(json.dumps({
            'stock_manifest_sha256': manifest_sha, 'super_sha256': spec['stock']['super_sha256'],
            'avb_public_key_sha1': spec['stock']['avb_public_key_sha1'], 'flashed': False, 'device_tested': False}))
        self.stock = stock
        self.output = self.root / 'out/preflight.json'
        self.phone = {
            'state': 'device',
            'ro.product.device': identity['product'], 'ro.boot.hardware.sku': identity['sku'],
            'ro.build.fingerprint': identity['fingerprint'], 'ro.bootloader': identity['bootloader'],
            'ro.build.version.sdk': str(spec['release_requirements']['android_api']),
            'ro.boot.flash.locked': '0', 'ro.boot.verifiedbootstate': 'orange', 'ro.boot.slot_suffix': '_b',
            'uname': spec['kernel']['stock_release'], 'getenforce': 'Enforcing', 'battery': '80'}
        self.sent = []

    def adb(self, argv, check=True, capture_output=True, text=True, timeout=None):
        self.assertEqual(argv[:3], ['adb', '-P', '5037'])
        if argv[3] == 'devices':
            out = f"List of devices attached\n{SERIAL}\t{self.phone['state']}\n"
        else:
            self.assertEqual(argv[3:6], ['-s', SERIAL, 'shell'])
            command = argv[6:]
            self.sent.append(command)
            out = {'getprop': lambda: self.phone[command[1]], 'uname': lambda: self.phone['uname'],
                   'getenforce': lambda: self.phone['getenforce'],
                   'dumpsys': lambda: f"Current Battery Service state:\n  level: {self.phone['battery']}\n"}[command[0]]()
        return subprocess.CompletedProcess(argv, 0, out + '\n', '')

    def preflight(self):
        spec = self.root / 'spec.json'
        spec.write_text(json.dumps(self.spec_data))
        argv = ['preflight.py', str(spec), str(self.stock), '--serial', SERIAL, '--output', str(self.output)]
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(preflight.subprocess, 'run', self.adb), \
                mock.patch('builtins.print'):
            preflight.main()
        return json.loads(self.output.read_text())

    # covers: install.device-spec/E2
    def test_matching_phone_passes_with_only_reading_commands(self):
        report = self.preflight()
        self.assertEqual(report['result'], 'source-and-device-preflight-passed')
        self.assertEqual(report['observed']['properties']['ro.boot.slot_suffix'], '_b')
        self.assertEqual(report['observed']['battery_percent'], 80)
        self.assertTrue(self.sent)
        self.assertLessEqual({c[0] for c in self.sent}, READING, 'nothing but reading is sent to the phone')

    # covers: install.device-spec/E2
    def test_any_difference_stops_without_a_report(self):
        cases = {'state': 'unauthorized', 'ro.product.device': 'mumba', 'ro.boot.hardware.sku': 'XT2537-4',
                 'ro.build.fingerprint': 'motorola/portov_cn/portov:16/OTHER/x:user/release-keys',
                 'ro.bootloader': 'MBM-other', 'ro.build.version.sdk': '35', 'ro.boot.flash.locked': '1',
                 'ro.boot.verifiedbootstate': 'green', 'ro.boot.slot_suffix': '', 'uname': '6.6.0-other',
                 'getenforce': 'Permissive', 'battery': '29'}
        good = dict(self.phone)
        for field, bad in cases.items():
            with self.subTest(field=field):
                self.phone = dict(good, **{field: bad})
                self.sent = []
                self.output.unlink(missing_ok=True)
                with self.assertRaises(ValueError):
                    self.preflight()
                self.assertFalse(self.output.exists())
                self.assertLessEqual({c[0] for c in self.sent}, READING)

    # covers: install.device-spec/E2
    def test_too_little_host_space_stops(self):
        self.spec_data['release_requirements']['minimum_host_free_gib'] = 10 ** 9
        with self.assertRaisesRegex(ValueError, 'host free space'):
            self.preflight()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
