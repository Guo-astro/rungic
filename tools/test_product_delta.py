#!/usr/bin/env python3
"""Check reconstruction correctness and failure handling without any device."""
import contextlib
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from product_delta import restore_product


class DeltaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'stock').mkdir()
        (self.root / 'delta').mkdir()
        for i in range(34):
            (self.root / 'stock' / ('super.img_sparsechunk.' + str(i))).write_bytes(b'abcdef')
        self.expected = b'bcNEW\0\0def'
        self.sha = hashlib.sha256(self.expected).hexdigest()
        self.recipe = dict(format='moto-block-delta-v1', output_bytes=len(self.expected),
                           output_sha256=self.sha,
                           operations=[['copy', 0, 1, 2], ['literal', 3], ['zero', 2], ['copy', 33, 3, 3]])
        self.write_recipe()
        self.write_literals(b'NEW')

    def write_recipe(self):
        with gzip.open(self.root / 'delta/product.recipe.json.gz', 'wt') as f:
            json.dump(self.recipe, f)

    def write_literals(self, data):
        with gzip.open(self.root / 'delta/product.literals.gz', 'wb') as f:
            f.write(data)

    def restore(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return restore_product(self.root, self.sha, len(self.expected))

    def assert_no_output(self):
        self.assertFalse((self.root / 'images/product.img').exists())
        self.assertFalse((self.root / 'images/product.img.partial').exists())

    def test_restores_copy_literal_zero_and_reuses_verified_cache(self):
        target = self.restore()
        self.assertEqual(target.read_bytes(), self.expected)
        before = target.stat().st_mtime_ns
        self.restore()
        self.assertEqual(target.stat().st_mtime_ns, before)

    def test_corrupt_source_fails_hash_and_leaves_no_flashable_output(self):
        (self.root / 'stock/super.img_sparsechunk.0').write_bytes(b'XXXXXX')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.restore()
        self.assert_no_output()

    def test_truncated_or_extra_literals_are_rejected(self):
        for data in [b'NE', b'NEWextra']:
            with self.subTest(data=data):
                self.write_literals(data)
                with self.assertRaises(ValueError):
                    self.restore()
                self.assert_no_output()

    def test_bad_copy_bounds_rejected_before_creating_output(self):
        for op in [['copy', -1, 0, 2], ['copy', 34, 0, 2], ['copy', 0, -1, 2], ['copy', 0, 5, 2]]:
            with self.subTest(op=op):
                self.recipe['operations'][0] = op
                self.write_recipe()
                with self.assertRaises(ValueError):
                    self.restore()
                self.assert_no_output()

    def test_low_disk_space_stops_before_output(self):
        class Disk:
            free = 0
        with patch('product_delta.shutil.disk_usage', return_value=Disk()):
            with self.assertRaisesRegex(ValueError, '空间不足'):
                self.restore()
        self.assert_no_output()

    def test_replaces_corrupt_cache_and_removes_stale_partial(self):
        (self.root / 'images').mkdir()
        (self.root / 'images/product.img').write_bytes(b'x' * len(self.expected))
        (self.root / 'images/product.img.partial').write_bytes(b'stale')
        self.assertEqual(self.restore().read_bytes(), self.expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
