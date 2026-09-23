#!/usr/bin/env python3
"""Exercise destructive-operation ordering with a simulated transport only."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from oneclick_flash import BOOTLOADER, BOOT_PARTS, SUPER_CHUNKS, Flasher, FlashError, sha256, verify_payload, main


class FakeDevice(Flasher):
    def __init__(self, fail=None, bad=None, android=False):
        self.root = Path('/fixture')
        self.serial = None
        self.log_path = Path('/fixture/test.log')
        self.commands = []
        self.userspace = False
        self.fail = fail
        self.bad = bad or {}
        self.android = android

    def run(self, tool, *args, **kwargs):
        args = tuple(map(str, args))
        self.commands.append((tool,) + args)
        if self.fail and self.fail(args):
            raise FlashError('simulated write failure')
        if args == ('devices',):
            return ('ZX device\n' if self.android else '') if tool == 'adb' else ('' if self.android else 'ZX fastboot\n')
        if args[:1] == ('getvar',):
            key = args[1]
            values = {'is-userspace': 'yes' if self.userspace else 'no', 'product': 'mumba',
                      'sku': 'XT2537-4', 'securestate': 'flashing_unlocked', 'version-bootloader': BOOTLOADER,
                      'battery-voltage': '4400', 'current-slot': 'a', 'unlocked': 'yes',
                      'partition-size:product_a': '0x1C5C6C000'}
            values.update(self.bad)
            if key == 'version-bootloader' and key not in self.bad:
                return '(bootloader) version-bootloader[0]: ' + BOOTLOADER[:40] + '\n(bootloader) version-bootloader[1]: ' + BOOTLOADER[40:] + '\nversion-bootloader: Done\n'
            return key + ': ' + values[key] + '\n'
        if args == ('reboot', 'fastboot'):
            self.userspace = True
        elif args == ('reboot', 'bootloader'):
            self.userspace = False
        return 'OKAY\n'


class FlashTests(unittest.TestCase):
    def test_full_restores_original_chunks_then_product_then_root_then_wipe(self):
        d = FakeDevice()
        d.prepare('full')
        d.flash('full')
        c = d.commands
        supers = [x for x in c if x[1:3] == ('flash', 'super')]
        self.assertEqual([Path(x[3]).name for x in supers], SUPER_CHUNKS)
        product = next(i for i,x in enumerate(c) if 'product_a' in x and 'flash' in x)
        root = next(i for i,x in enumerate(c) if x[1:3] == ('flash', 'init_boot_a'))
        erases = [i for i,x in enumerate(c) if x[1:2] == ('erase',)]
        self.assertLess(c.index(supers[-1]), product)
        self.assertLess(product, root)
        self.assertTrue(all(root < i for i in erases))
        self.assertEqual([c[i][2] for i in erases], ['userdata', 'metadata'])
        self.assertFalse(any('partition' in x or 'modemst1' in x or 'modemst2' in x for x in c))

    def test_update_does_not_write_stock_or_erase(self):
        d = FakeDevice(); d.serial = 'ZX'; d.flash('update')
        self.assertFalse(any('erase' in x or any('/stock/' in y for y in x) for x in d.commands))

    def test_product_write_failure_prevents_root_write_and_erase(self):
        d = FakeDevice(fail=lambda a: 'flash' in a and 'product_a' in a); d.serial = 'ZX'
        with self.assertRaises(FlashError): d.flash('full')
        self.assertFalse(any('erase' in x or 'init_boot_a' in x for x in d.commands))

    def test_root_write_failure_prevents_erase(self):
        d = FakeDevice(fail=lambda a: a[:2] == ('flash', 'init_boot_a')); d.serial = 'ZX'
        with self.assertRaises(FlashError): d.flash('full')
        self.assertFalse(any('erase' in x for x in d.commands))

    def test_wrong_device_or_locked_or_new_bootloader_prevents_writes(self):
        for bad in [{'sku':'XT0000'}, {'securestate':'locked'}, {'version-bootloader':'newer'}]:
            with self.subTest(bad=bad):
                d=FakeDevice(bad=bad)
                with self.assertRaises(FlashError): d.prepare('full')
                self.assertFalse(any('flash' in x or 'erase' in x or 'set_active' in x for x in d.commands))

    def test_wrong_partition_size_prevents_product_and_erase(self):
        d = FakeDevice(bad={'partition-size:product_a':'0x1234'}); d.serial = 'ZX'
        with self.assertRaises(FlashError): d.flash('update')
        self.assertFalse(any('erase' in x or ('product_a' in x and 'flash' in x) for x in d.commands))

    def test_update_refuses_unverifiable_fastboot_only_start(self):
        d = FakeDevice()
        with self.assertRaises(FlashError): d.prepare('update')
        self.assertFalse(any('flash' in x or 'erase' in x for x in d.commands))

    def test_payload_corruption_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = ['stock/'+n+'.img' for n in BOOT_PARTS]+['stock/'+n for n in SUPER_CHUNKS]
            names += ['images/'+n for n in ['product.img','init_boot.img','vbmeta.img','vbmeta_system.img']]
            names += ['tools/linux-x86_64/'+n for n in ['adb','fastboot','NOTICE.txt','source.properties']]
            manifest = {}
            for n in names:
                p=root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture');manifest[n]=sha256(p)
            (root/'payload-sha256.json').write_text(json.dumps(manifest))
            (root/'images/product.img').write_bytes(b'corrupted')
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(FlashError): verify_payload(root)

    def test_reconstruction_failure_prevents_device_connection(self):
        with patch('sys.argv', ['flash.py']), patch('oneclick_flash.verify_payload'), \
             patch('oneclick_flash.prepare_product', side_effect=ValueError('corrupt delta')), \
             patch('oneclick_flash.Flasher') as flasher, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                main()
            flasher.assert_not_called()

    def test_prepare_only_never_connects_device(self):
        with patch('sys.argv', ['flash.py', '--prepare-only']), patch('oneclick_flash.verify_payload'), \
             patch('oneclick_flash.prepare_product') as prepare, patch('oneclick_flash.Flasher') as flasher, \
             contextlib.redirect_stdout(io.StringIO()):
            main()
            prepare.assert_called_once()
            flasher.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
