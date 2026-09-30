"""Exercise cache hits, invalidation, corruption and publication with real builds."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_artifact as b


class BuildCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'source').write_text('first')
        (self.root / 'tool').write_text('tool1')
        (self.root / 'dep').write_text('library1')
        self.cache = self.root / 'cache'
        self.recipe = dict(schema=1, component='test', target='test-arch', sources=['source'],
                           tools={'compiler': {'path': str(self.root / 'tool')}},
                           dependencies={'library': {'path': str(self.root / 'dep')}},
                           command=[sys.executable, '-c',
                                    'from pathlib import Path; Path("{output}/artifact").write_text(Path("{repo}/source").read_text())'],
                           outputs=['artifact'])

    def build(self, recipe=None):
        return b.execute(recipe or self.recipe, self.cache, self.root)

    def test_same_inputs_reuse_across_unrelated_edit(self):
        first = self.build()
        (self.root / 'README').write_text('unrelated docs')
        second = self.build()
        self.assertFalse(first['reused'])
        self.assertTrue(second['reused'])
        self.assertEqual(first['directory'], second['directory'])

    def test_changed_source_dependency_tool_parameters_architecture(self):
        baseline = b.inputs(self.recipe, self.root)
        for field in ('source', 'dep', 'tool'):
            path = self.root / field
            old = path.read_text()
            path.write_text(old + 'changed')
            self.assertNotEqual(baseline, b.inputs(self.recipe, self.root), field)
            path.write_text(old)
        for field, value in [('target', 'other'), ('parameters', {'feature': True}),
                             ('environment', {'CFLAGS': '-O0'})]:
            recipe = copy.deepcopy(self.recipe); recipe[field] = value
            self.assertNotEqual(baseline, b.inputs(recipe, self.root), field)

    def test_content_change_builds_new_cache_entry(self):
        first = self.build()
        (self.root / 'source').write_text('second')
        second = self.build()
        self.assertFalse(second['reused'])
        self.assertNotEqual(first['directory'], second['directory'])
        self.assertEqual((Path(second['directory']) / 'artifact').read_text(), 'second')

    def test_corrupt_output_cannot_hit(self):
        result = self.build()
        (Path(result['directory']) / 'artifact').write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.build()

    def test_missing_record_cannot_hit(self):
        result = self.build()
        (Path(result['directory']) / 'build.json').unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()

    def test_input_mutation_during_build_never_publishes(self):
        self.recipe['command'][-1] += '; Path("{repo}/source").write_text("changed")'
        key = b.digest(b.inputs(self.recipe, self.root))
        with self.assertRaisesRegex(ValueError, 'changed during build'):
            self.build()
        self.assertFalse((self.cache / 'test' / key).exists())

    def test_failed_build_never_publishes(self):
        self.recipe['command'] = [sys.executable, '-c', 'raise SystemExit(7)']
        key = b.digest(b.inputs(self.recipe, self.root))
        with self.assertRaisesRegex(ValueError, 'build failed'):
            self.build()
        self.assertFalse((self.cache / 'test' / key).exists())

    def test_pinned_binary_mismatch_rejected(self):
        self.recipe['dependencies']['library']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'pinned dependency'):
            self.build()

    def test_input_locations_do_not_change_identity(self):
        before = b.inputs(self.recipe, self.root)
        other = self.root / 'elsewhere'; other.write_bytes((self.root / 'dep').read_bytes())
        self.recipe['dependencies']['library']['path'] = str(other)
        self.assertEqual(before, b.inputs(self.recipe, self.root))

    def test_source_mode_and_symlink_changes_invalidate(self):
        before = b.inputs(self.recipe, self.root)
        (self.root / 'source').chmod(0o755)
        self.assertNotEqual(before, b.inputs(self.recipe, self.root))
        (self.root / 'source').unlink(); (self.root / 'source').symlink_to('dep')
        self.assertNotEqual(before, b.inputs(self.recipe, self.root))

    def test_forged_record_and_output_traversal_rejected(self):
        report = self.build()['report']
        report['inputs']['target'] = 'different'
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            b.validate_record(report)
        self.recipe['outputs'] = ['../outside']
        with self.assertRaisesRegex(ValueError, 'relative path'):
            self.build()


if __name__ == '__main__':
    unittest.main()
