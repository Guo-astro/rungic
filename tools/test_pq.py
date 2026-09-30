#!/usr/bin/env python3
"""tools/pq.py without docker or network: patch headers, lint rules, download checks and the
patch/test matrix (docs/71)."""
import hashlib
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pq

GOOD = """From: Someone <someone@example.org>
Date: Fri, 25 Sep 2026 01:22:16 +0900
Subject: A minimum size above the maximum no longer disconnects
 the client

Why it is needed.

Forwarded: no
Last-Update: 2026-09-26
X-Rungic-Status: Pending
X-Rungic-Tests: L3:session.ready; L1:xdgshellwindow_test (to write)
X-Rungic-Docs: docs/42
---
 src/x.cpp | 1 +
diff --git a/src/x.cpp b/src/x.cpp
"""


class PackageTree(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name, value in (('PACKAGES', self.root / 'packages'), ('SOURCES', self.root / 'sources')):
            p = patch.object(pq, name, value)
            p.start()
            self.addCleanup(p.stop)

    def package(self, patches, series=None, recipe=None):
        base = self.root / 'packages/demo/debian/patches'
        (base / 'rungic').mkdir(parents=True)
        for name, text in patches.items():
            (base / name).write_text(text)
        (base / 'series').write_text('\n'.join(series if series is not None else patches) + '\n')
        (self.root / 'packages/demo/recipe.json').write_text(json.dumps(recipe or {'files': {}}))


class HeaderTests(unittest.TestCase):
    def test_fields_and_continuation_lines(self):
        fields = pq.header(GOOD)
        self.assertEqual(fields['Subject'], 'A minimum size above the maximum no longer disconnects the client')
        self.assertEqual(fields['X-Rungic-Status'], 'Pending')
        self.assertEqual(fields['Last-Update'], '2026-09-26')
        self.assertNotIn('diff', ''.join(fields))

    def test_plain_dep3(self):
        fields = pq.header('Description: fix it\nAuthor: A <a@b>\nForwarded: not-needed\n\n--- a/x\n+++ b/x\n')
        self.assertEqual(fields['Description'], 'fix it')
        self.assertEqual(fields['Forwarded'], 'not-needed')


class LintTests(PackageTree):
    def test_good_package(self):
        self.package({'ubuntu.patch': 'Description: theirs\n---\n', 'rungic/a.patch': GOOD})
        self.assertEqual(pq.lint_package('demo'), [])

    def test_missing_fields_series_and_bad_values(self):
        bad = GOOD.replace('Forwarded: no\n', '').replace('2026-09-26', '26.9.2026').replace(
            'X-Rungic-Status: Pending', 'X-Rungic-Status: Maybe')
        submitted = GOOD.replace('X-Rungic-Status: Pending', 'X-Rungic-Status: Submitted')
        self.package({'rungic/a.patch': bad, 'rungic/b.patch': submitted, 'rungic/c.patch': GOOD},
                     series=['rungic/a.patch', 'rungic/b.patch', 'rungic/gone.patch'])
        problems = '\n'.join(pq.lint_package('demo'))
        for expected in ('series names a missing patch: rungic/gone.patch', 'rungic/c.patch is not in series',
                         'rungic/a.patch: no Forwarded', "Last-Update '26.9.2026'", "X-Rungic-Status 'Maybe'",
                         'rungic/b.patch: Submitted but Forwarded has no URL'):
            self.assertIn(expected, problems)


class MatrixTests(PackageTree):
    def test_planned_tests_do_not_count(self):
        gap = GOOD.replace('X-Rungic-Tests: L3:session.ready; L1:xdgshellwindow_test (to write)',
                           'X-Rungic-Tests: none (gap: needs a TV)')
        self.package({'rungic/a.patch': GOOD, 'rungic/b.patch': gap})
        rows = {r['patch']: r for r in pq.test_matrix(['demo'])}
        self.assertEqual(rows['a.patch']['tests'], ['L3:session.ready'])
        self.assertEqual(rows['a.patch']['planned'], ['L1:xdgshellwindow_test'])
        self.assertEqual(rows['b.patch']['tests'], [])


class FetchTests(PackageTree):
    def test_checks_sha256_and_keeps_nothing_on_mismatch(self):
        data = b'upstream source'
        self.package({}, recipe={'fetch': 'https://example.org/{file}',
                                 'files': {'demo.orig.tar.xz': hashlib.sha256(data).hexdigest(),
                                           'demo.dsc': hashlib.sha256(b'other').hexdigest()}})
        opener = lambda url: io.BytesIO(data)
        with self.assertRaises(SystemExit) as failure:
            pq.fetch('demo', opener=opener)
        self.assertIn('demo.dsc', str(failure.exception))
        cache = self.root / 'sources/demo'
        self.assertEqual((cache / 'demo.orig.tar.xz').read_bytes(), data)
        self.assertEqual(sorted(p.name for p in cache.iterdir()), ['demo.orig.tar.xz'])


class OverlayTests(PackageTree):
    def setUp(self):
        super().setUp()
        p = patch.object(pq, 'WORKSPACE', self.root)
        p.start()
        self.addCleanup(p.stop)
        (self.root / 'shared').mkdir()
        (self.root / 'shared/ours.cpp').write_text('ours\n')
        self.tree = self.root / 'tree'
        (self.tree / 'src').mkdir(parents=True)
        (self.tree / 'src/theirs.cpp').write_text('theirs\n')

    def overlay(self, entries):
        self.package({}, recipe={'files': {}, 'overlay': entries})
        pq.add_overlay('demo', self.tree)

    def test_new_file(self):
        self.overlay({'src/new.cpp': 'shared/ours.cpp'})
        self.assertEqual((self.tree / 'src/new.cpp').read_text(), 'ours\n')

    def test_upstream_file_needs_its_hash(self):
        with self.assertRaisesRegex(SystemExit, 'exists in the upstream tree'):
            self.overlay({'src/theirs.cpp': 'shared/ours.cpp'})

    def test_replaces_upstream_file_with_the_recorded_hash(self):
        digest = hashlib.sha256(b'theirs\n').hexdigest()
        self.overlay({'src/theirs.cpp': {'from': 'shared/ours.cpp', 'replaces': digest}})
        self.assertEqual((self.tree / 'src/theirs.cpp').read_text(), 'ours\n')

    def test_refuses_once_upstream_changed(self):
        with self.assertRaisesRegex(SystemExit, 'upstream src/theirs.cpp changed'):
            self.overlay({'src/theirs.cpp': {'from': 'shared/ours.cpp', 'replaces': '0' * 64}})

    def test_refuses_when_the_replaced_file_is_gone(self):
        with self.assertRaisesRegex(SystemExit, 'which is gone'):
            self.overlay({'src/gone.cpp': {'from': 'shared/ours.cpp', 'replaces': '0' * 64}})


class VerifyTests(PackageTree):
    def test_unresolvable_symlink_is_a_difference(self):
        mine, ref = self.root / 'mine', self.root / 'ref'
        mine.mkdir()
        ref.mkdir()
        (mine / 'f').write_text('x')
        (ref / 'f').symlink_to('../nowhere/f')
        with patch.object(pq, 'source', return_value=mine):
            ok, text = pq.verify('demo', ref)
        self.assertFalse(ok)
        self.assertIn('No such file', text)


class GitSubtreeTests(PackageTree):
    """Exercise real git archives, subtree hashes and extraction without network/Docker."""
    def setUp(self):
        super().setUp()
        self.repo = self.root / 'upstream'
        self.repo.mkdir()
        self.git('init', '-q')
        for name, content in {'outside': 'not a build input', 'native/src/main.rs': 'host',
                              'native/logs/debug.txt': 'generated', 'other/main.rs': 'other'}.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'baseline')
        self.info = {'kind': 'git', 'git': str(self.repo), 'commit': self.git('rev-parse', 'HEAD'),
                     'tree': self.git('rev-parse', 'HEAD:native'), 'subdir': 'native', 'files': {}}
        self.output = self.root / 'output'

    def git(self, *args):
        env = dict(os.environ, GIT_AUTHOR_DATE='2001-01-01T00:00:00Z', GIT_COMMITTER_DATE='2001-01-01T00:00:00Z')
        return subprocess.check_output(['git', *args], cwd=self.repo, text=True, env=env).strip()

    def write_recipe(self):
        path = self.root / 'packages/demo/recipe.json'
        if path.exists():
            path.write_text(json.dumps(self.info))
        else:
            self.package({}, recipe=self.info)

    def test_subtree_is_selected_and_exclusions_are_applied(self):
        self.info['exclude'] = ['logs']
        self.write_recipe()
        pq.source('demo', self.output)
        self.assertEqual((self.output / 'src/main.rs').read_text(), 'host')
        self.assertFalse((self.output / 'outside').exists())
        self.assertFalse((self.output / 'logs').exists())
        with tarfile.open(pq.orig_tarball('demo')) as archive:
            self.assertEqual({m.mtime for m in archive.getmembers()}, {978307200})

    def test_whole_commit_archive_keeps_existing_layout_and_timestamp(self):
        self.info.pop('subdir')
        self.info['tree'] = self.git('rev-parse', 'HEAD^{tree}')
        self.write_recipe()
        pq.source('demo', self.output)
        self.assertTrue((self.output / 'outside').exists())
        with tarfile.open(pq.orig_tarball('demo')) as archive:
            self.assertEqual(archive.pax_headers['comment'], self.info['commit'])
            self.assertEqual({m.mtime for m in archive.getmembers()}, {978307200})

    def test_changed_subtree_does_not_reuse_previous_archive(self):
        self.write_recipe()
        pq.source('demo', self.output)
        self.info.update(subdir='other', tree=self.git('rev-parse', 'HEAD:other'))
        self.write_recipe()
        pq.source('demo', self.output)
        self.assertEqual((self.output / 'main.rs').read_text(), 'other')
        self.assertFalse((self.output / 'src').exists())

    def test_wrong_tree_hash_rejects_source_even_after_previous_fetch(self):
        self.write_recipe()
        pq.fetch('demo')
        self.info['tree'] = '0' * 40
        self.write_recipe()
        with self.assertRaisesRegex(SystemExit, 'recipe says'):
            pq.fetch('demo')

    def test_missing_exclusion_requires_review(self):
        self.info['exclude'] = ['removed-in-new-version']
        self.write_recipe()
        with self.assertRaisesRegex(SystemExit, 'no longer exists'):
            pq.source('demo', self.output)

    def test_paths_cannot_escape_selected_tree(self):
        for value in ('../outside', '/outside', '.'):
            with self.subTest(value=value), self.assertRaisesRegex(SystemExit, 'invalid source path'):
                pq.relative_source_path(value)


if __name__ == '__main__':
    unittest.main()
