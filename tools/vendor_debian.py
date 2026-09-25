#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bring Ubuntu's Debian packaging into a vendored component (docs/61, vendor/README.md).

  vendor_debian.py import COMPONENT DSC     debian/ and quilt state (.pc) from an Ubuntu source
                  [--new-upstream V]        package; its distribution patches applied to vendor/
  vendor_debian.py changelog COMPONENT TEXT a +motoN changelog entry for this project's build

`import` is the "upstream import" step of the vendor rules: commit its result on its own,
before the project's changes. The source package's orig tarball must have the same content
as the vendored baseline (checked). Distribution patches that the vendored tree already
carries are recorded as applied, not applied twice.
"""
import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
MANIFEST = WORKSPACE / 'vendor/manifest.json'


def component_entry(manifest, path):
    items = manifest['components']
    for item in (items if isinstance(items, list) else items.values()):
        if item['path'] == path:
            return item
    raise SystemExit(f'{path} is not in vendor/manifest.json')


def import_debian(component, dsc, new_upstream=None):
    dsc = Path(dsc).resolve()
    vendor = WORKSPACE / 'vendor' / component
    if (vendor / 'debian').exists():
        raise SystemExit(f'{vendor}/debian exists already')
    work = Path(tempfile.mkdtemp(dir=WORKSPACE / '.work/cache', prefix=f'{component}-dsc-'))
    try:
        tree = work / 'src'
        subprocess.run(['dpkg-source', '--no-check', '-x', str(dsc), str(tree)], check=True, capture_output=True)
        # The vendored baseline must be the same upstream source.
        pristine = work / 'orig'
        pristine.mkdir()
        orig = next(p for p in dsc.parent.glob(f"{dsc.name.split('_')[0]}_*.orig.tar.*")
                    if not p.name.endswith('.asc'))
        subprocess.run(['tar', '-xf', str(orig), '-C', str(pristine), '--strip-components=1'], check=True)
        baseline = subprocess.run(['git', 'log', '--format=%H', '--diff-filter=A', '--reverse', '--',
                                   f'vendor/{component}'], cwd=WORKSPACE, capture_output=True, text=True,
                                  check=True).stdout.split()[0]
        base = work / 'base'
        base.mkdir()
        archive = subprocess.run(['git', 'archive', baseline, f'vendor/{component}'], cwd=WORKSPACE,
                                 capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', str(base), '--strip-components=2'], input=archive, check=True)
        diff = subprocess.run(['diff', '-rq', str(pristine), str(base)], capture_output=True, text=True).stdout
        if diff.strip() and not new_upstream:
            raise SystemExit(f'the orig tarball differs from the vendored baseline {baseline[:12]}:\n{diff[:2000]}')
        # Distribution patches onto the vendored (already customised) tree.
        series = (tree / 'debian/patches/series')
        applied, already = [], []
        for name in (series.read_text().split() if series.exists() else []):
            patch = tree / 'debian/patches' / name
            dry = subprocess.run(['patch', '-p1', '--dry-run', '--forward', '-s', '-d', str(vendor), '-i', str(patch)],
                                 capture_output=True, text=True)
            if dry.returncode == 0:
                subprocess.run(['patch', '-p1', '--forward', '-s', '-d', str(vendor), '-i', str(patch)], check=True)
                applied.append(name)
                continue
            reverse = subprocess.run(['patch', '-p1', '-R', '--dry-run', '-s', '-d', str(vendor), '-i', str(patch)],
                                     capture_output=True, text=True)
            if reverse.returncode == 0:
                already.append(name)
                continue
            raise SystemExit(f'{name} neither applies nor is already applied to vendor/{component}:\n'
                             f'{dry.stdout}{dry.stderr}')
        shutil.copytree(tree / 'debian', vendor / 'debian', symlinks=True)
        if (tree / '.pc').exists():
            shutil.copytree(tree / '.pc', vendor / '.pc', symlinks=True)
    finally:
        shutil.rmtree(work)
    manifest = json.loads(MANIFEST.read_text())
    entry = component_entry(manifest, f'vendor/{component}')
    version = re.search(r'^Version:\s*(\S+)', dsc.read_text(), re.M)[1]
    files = [dsc] + [dsc.parent / n for n in re.findall(r'^ [0-9a-f]{64} \d+ (\S+)$', dsc.read_text(), re.M)
                     if 'debian.tar' in n]
    entry['ubuntu_source'] = {
        'version': version,
        **({'packaging_only_for_upstream': new_upstream} if new_upstream else {}),
        'files': [{'name': f.name, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()} for f in files],
        'patches_applied_on_import': applied, 'patches_already_in_tree': already,
        'imported': datetime.date.today().isoformat(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n')
    return {'component': component, 'ubuntu_version': version, 'applied': applied, 'already_applied': already}


def changelog(component, text, distribution='resolute'):
    path = WORKSPACE / 'vendor' / component / 'debian/changelog'
    current = path.read_text()
    head = re.match(r'(\S+) \(([^)]+)\)', current)
    source, version = head[1], head[2]
    m = re.search(r'\+moto(\d+)$', version)
    new = f'{version[:m.start()]}+moto{int(m[1]) + 1}' if m else f'{version}+moto1'
    when = datetime.datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')
    body = '\n'.join(f'  * {line}' if i == 0 else f'    {line}' for i, line in enumerate(text.strip().splitlines()))
    entry = f'{source} ({new}) {distribution}; urgency=medium\n\n{body}\n\n -- range-dev <noreply@localhost>  {when}\n\n'
    path.write_text(entry + current)
    return {'component': component, 'version': new}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('import'); p.add_argument('component'); p.add_argument('dsc')
    p.add_argument('--new-upstream', metavar='VERSION', help='the vendored upstream is newer than the source '
                   "package's: take its packaging only (no content check)")
    p = sub.add_parser('changelog'); p.add_argument('component'); p.add_argument('text')
    a = parser.parse_args()
    result = (import_debian(a.component, a.dsc, a.new_upstream) if a.cmd == 'import'
              else changelog(a.component, a.text))
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
