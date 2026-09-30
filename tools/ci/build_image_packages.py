#!/usr/bin/env python3
"""Build the desktop casting package and matching release metadata from source.

The rest of the explicitly selected package baseline is unchanged. The outer
build recipe fingerprints this baseline and the packaging tools before execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import rungic_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--cast-version', required=True)
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    pkg = rungic_package.definitions()['rungic-cast']
    root = out / 'cast-package'
    (root / 'DEBIAN').mkdir(parents=True)
    subprocess.run(['sh', '-eu', str(pkg['dir'] / 'build.sh')], check=True,
                   env=dict(os.environ, SRC=str(ROOT), DESTDIR=str(root)))
    rungic_package.maintainer_scripts(pkg, root)
    rungic_package.control(pkg, args.cast_version, root)
    def pack(tree, path):
        (tree / 'DEBIAN/md5sums').write_text(''.join(
            hashlib.md5(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(tree)) + '\n'
            for p in sorted(tree.rglob('*')) if p.is_file() and not p.is_symlink()
            and 'DEBIAN' not in p.relative_to(tree).parts))
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(tree), str(path)], check=True)
    pack(root, out / f'rungic-cast_{args.cast_version}_all.deb')
    baseline = json.loads(args.baseline.read_text())
    # Old Android-path annotations and ad-hoc fix records do not describe this build.
    release = {key: baseline[key] for key in ('packages', 'coupled', 'session_restart', 'service_restart') if key in baseline}
    release.update(version=args.version, baseline_sha256=hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
                   note='Fingerprint-checked image composition; unchanged package versions are pinned binary inputs.')
    release['packages']['rungic-cast'] = args.cast_version
    (out / 'release.json').write_text(json.dumps(release, indent=2) + '\n')
    meta = out / 'release-package'
    (meta / 'DEBIAN').mkdir(parents=True)
    (meta / 'usr/share/rungic').mkdir(parents=True)
    (meta / 'usr/share/rungic/release.json').write_bytes((out / 'release.json').read_bytes())
    dependencies = ', '.join(f'{name} (= {version})' for name, version in sorted(release['packages'].items()))
    (meta / 'DEBIAN/control').write_text(f'Package: rungic-release\nVersion: {args.version}\nArchitecture: all\n'
        f'Maintainer: range-dev <noreply@localhost>\nDepends: {dependencies}\n'
        'Description: Rungic pinned system package set\n')
    pack(meta, out / f'rungic-release_{args.version}_all.deb')


if __name__ == '__main__':
    main()
