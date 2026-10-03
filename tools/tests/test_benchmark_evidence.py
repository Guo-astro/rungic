#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""benchmarks/: every set of benchmark data says where it comes from and carries the checksums of its
files, which still match (the raw data has not been rewritten); large traces stay in .work and are
known only by TRACES-SHA256SUMS."""
import hashlib
import re
import unittest
from pathlib import Path

BENCHMARKS = Path(__file__).resolve().parents[2] / 'benchmarks'
CHECKSUMS = ('SHA256SUMS', 'TRACES-SHA256SUMS', 'REPRO-SHA256SUMS')


def sums(path):
    entries = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        assert match, f'{path}: malformed line {line!r}'
        entries[match[2]] = match[1]
    return entries


class BenchmarkEvidenceTests(unittest.TestCase):
    def sets(self):
        found = sorted(p for p in BENCHMARKS.iterdir() if p.is_dir())
        self.assertGreaterEqual(len(found), 8)
        return found

    # covers: delivery.benchmark-evidence/E1
    def test_every_set_says_where_it_comes_from(self):
        readme = (BENCHMARKS / 'README.md').read_text()
        for folder in self.sets():
            self.assertIn(f'`{folder.name}/`', readme, f'{folder.name} is not described in benchmarks/README.md')

    # covers: delivery.benchmark-evidence/E1
    def test_every_file_of_a_set_matches_its_checksum(self):
        for folder in self.sets():
            with self.subTest(folder.name):
                recorded = sums(folder / 'SHA256SUMS')
                present = {p.relative_to(folder).as_posix() for p in folder.rglob('*')
                           if p.is_file() and p.name not in CHECKSUMS}
                self.assertEqual(set(recorded), present, 'SHA256SUMS lists exactly the set\'s files')
                for name, digest in recorded.items():
                    self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest, name)

    # covers: delivery.benchmark-evidence/E1
    def test_traces_stay_in_work_and_are_known_by_their_checksum(self):
        traced = [folder for folder in self.sets() if (folder / 'TRACES-SHA256SUMS').exists()]
        self.assertTrue(traced)
        for folder in traced:
            for name in sums(folder / 'TRACES-SHA256SUMS'):
                # As recorded (zero-copy's lines keep the absolute path they were collected at).
                self.assertTrue(name.startswith('.work/') or '/.work/' in name, f'{folder.name}: {name}')
        self.assertEqual([p for p in BENCHMARKS.rglob('*') if p.suffix in ('.pftrace', '.perfetto-trace', '.trace')], [])


if __name__ == '__main__':
    unittest.main()
