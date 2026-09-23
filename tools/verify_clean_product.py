#!/usr/bin/env python3
"""Compare the rebuilt product image against every retained original file."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys

from erofs_inventory import Erofs


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    work = Path(sys.argv[1]).resolve()
    excludes = json.loads((work / 'product-excludes.json').read_text())
    original = json.loads((work / 'product-inodes.json').read_text())
    expected = {e['path']: e for e in original if not any(
        e['path'] == p or e['path'].startswith(p + '/') for p in excludes)}
    actual = {e['path']: e for e in Erofs(work / 'product-clean.img').walk()}
    assert expected.keys() == actual.keys(), dict(
        missing=sorted(expected.keys() - actual.keys()), extra=sorted(actual.keys() - expected.keys()))
    keys = ('mode', 'uid', 'gid', 'mtime', 'mtime_ns', 'xattrs')
    for path, e in expected.items():
        for key in keys:
            assert e[key] == actual[path][key], (path, key, e[key], actual[path][key])
        if stat.S_ISREG(e['mode']):
            assert e['size'] == actual[path]['size'], (path, 'size')
        if stat.S_ISLNK(e['mode']):
            assert e['target'] == actual[path]['target'], (path, 'symlink')
    extracted = work / 'product-clean-verified'
    assert not extracted.exists(), 'use a fresh verification extraction'
    subprocess.run([
        '/home/kevinzhow/android-kernel/prebuilts/kernel-build-tools/linux-x86/bin/fsck.erofs',
        '--extract=' + str(extracted), '--no-preserve', str(work / 'product-clean.img')], check=True)
    files, total = 0, 0
    for path, e in expected.items():
        if stat.S_ISREG(e['mode']):
            assert digest(work / 'product-root' / path) == digest(extracted / path), (path, 'sha256')
            files += 1
            total += e['size']
    result = dict(status='PASS', retained_entries=len(expected),
                  retained_regular_files=files, compared_file_bytes=total,
                  removed_entries=len(original)-len(expected), excluded_paths=excludes,
                  image_sha256=digest(work / 'product-clean.img'),
                  image_bytes=(work / 'product-clean.img').stat().st_size,
                  checked_metadata=list(keys) + ['symlink target'], boot_tested=False)
    (work / 'product-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
