#!/usr/bin/env python3
"""Upstream components as pinned sources plus patch queues (docs/71).

A component is packages/<name>/: recipe.json (the pinned upstream: files and their sha256) and
debian/ (the complete packaging; our changes are debian/patches/rungic/*.patch in DEP-3 form,
listed in debian/patches/series after the distribution's own). Upstream sources are cached in
.work/sources/<name>/; packaging tools run from the pinned toolchain image (tools/pq/Dockerfile).

  pq.py fetch NAME            download the recipe's files, check their sha256
  pq.py source NAME [--output DIR]
                              upstream + debian/ with every patch applied (quilt state kept):
                              the tree tools/build_on_device.py builds
  pq.py prepare NAME          .work/pq/NAME: git tree with one patch-queue commit per patch
                              (gbp pq import); edit there, then `export`
  pq.py export NAME           gbp pq export; our patches and series back into packages/NAME
  pq.py lint [NAME...]        series and DEP-3/X-Rungic-* fields of every patch of ours
  pq.py verify NAME --against DIR
                              the patched source equals DIR (debian/patches aside)
  pq.py tests [NAME...] [--gaps]
                              which tests cover which patch; --gaps: patches without any
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
PACKAGES = WORKSPACE / 'packages'
SOURCES = WORKSPACE / '.work/sources'
IMAGE = 'rungic-pq:26.04'
TOPIC = 'rungic'
STATUSES = ('Pending', 'Submitted', 'Backport', 'Denied', 'Inactive-Upstream', 'Inappropriate')
REQUIRED = ('Forwarded', 'Last-Update', 'X-Rungic-Status', 'X-Rungic-Tests', 'X-Rungic-Docs')


def recipe(name):
    path = PACKAGES / name / 'recipe.json'
    if not path.exists():
        raise SystemExit(f'no recipe: {path}')
    return json.loads(path.read_text())


def names():
    return sorted(p.parent.name for p in PACKAGES.glob('*/recipe.json'))


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch(name, opener=urllib.request.urlopen):
    info = recipe(name)
    cache = SOURCES / name
    cache.mkdir(parents=True, exist_ok=True)
    for file, want in info['files'].items():
        target = cache / file
        if target.exists() and sha256(target) == want:
            continue
        partial = target.with_suffix(target.suffix + '.part')
        with opener(info['fetch'].format(file=file)) as response, open(partial, 'wb') as out:
            shutil.copyfileobj(response, out)
        have = sha256(partial)
        if have != want:
            partial.unlink()
            raise SystemExit(f'{file}: sha256 {have}, recipe says {want}')
        partial.rename(target)
    return cache


def docker(workdir, *argv, env=()):
    command = ['docker', 'run', '--rm', '-u', f'{os.getuid()}:{os.getgid()}', '-e', 'HOME=/tmp',
               *[a for e in env for a in ('-e', e)], '-v', f'{workdir}:/w', '-w', '/w', IMAGE, *argv]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"{' '.join(argv)}: {result.stdout}{result.stderr}")
    return result.stdout


def orig_tarball(name):
    info = recipe(name)
    tars = [f for f in info['files'] if '.orig.tar.' in f]
    if len(tars) != 1:
        raise SystemExit(f'{name}: recipe needs exactly one .orig.tar.* file')
    return fetch(name) / tars[0]


def source(name, output=None):
    """Upstream with packages/NAME/debian and every patch applied, quilt state (.pc) kept."""
    output = Path(output or WORKSPACE / f'.work/build/pq/{name}/source').resolve()
    if output.exists():
        shutil.rmtree(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    unpack = output.parent / (output.name + '.unpack')
    shutil.rmtree(unpack, ignore_errors=True)
    unpack.mkdir()
    with tarfile.open(orig_tarball(name)) as tar:
        tar.extractall(unpack, filter='tar')
    [top] = list(unpack.iterdir())
    top.rename(output)
    unpack.rmdir()
    shutil.rmtree(output / 'debian', ignore_errors=True)
    shutil.copytree(PACKAGES / name / 'debian', output / 'debian', symlinks=True)
    if (output / 'debian/patches/series').exists():
        docker(output, 'quilt', 'push', '-a', '-q', env=('QUILT_PATCHES=debian/patches',))
    return output


def prepare(name):
    """git tree for editing: upstream + debian/ on branch rungic, patches as commits (gbp pq)."""
    work = WORKSPACE / '.work/pq' / name
    tree = source(name, WORKSPACE / f'.work/pq/{name}.src')
    docker(tree, 'quilt', 'pop', '-a', '-q', env=('QUILT_PATCHES=debian/patches',))
    shutil.rmtree(tree / '.pc', ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    tree.rename(work)
    for args in (('init', '-q', '-b', 'rungic'), ('add', '-A'),
                 ('-c', 'user.name=Rungic', '-c', 'user.email=noreply@rungic.invalid', 'commit', '-q', '-m',
                  f"{name} {recipe(name)['version']} with packages/{name}/debian (patches unapplied)")):
        subprocess.run(['git', *args], cwd=work, check=True, capture_output=True)
    docker(work, 'gbp', 'pq', 'import')
    return work


def export(name):
    """gbp pq export; only our topic and the series go back (the distribution's patches keep their
    original form, which gbp would rewrite)."""
    work = WORKSPACE / '.work/pq' / name
    docker(work, 'gbp', 'pq', 'export')
    dest = PACKAGES / name / 'debian/patches'
    shutil.rmtree(dest / TOPIC, ignore_errors=True)
    shutil.copytree(work / 'debian/patches' / TOPIC, dest / TOPIC)
    shutil.copy2(work / 'debian/patches/series', dest / 'series')
    return sorted(p.name for p in (dest / TOPIC).glob('*.patch'))


def header(text):
    """DEP-3 fields of a patch (git format-patch or plain DEP-3), up to the diff or '---'."""
    fields, key = {}, None
    for line in text.splitlines():
        if line.startswith(('---', 'diff ', 'Index: ')):
            break
        match = re.match(r'^([A-Za-z][A-Za-z0-9-]*): ?(.*)$', line)
        if match:
            key = match[1]
            fields[key] = match[2]
        elif line.startswith(' ') and key:
            fields[key] += ' ' + line.strip()
        else:
            key = None
    return fields


def lint_package(name):
    problems = []
    patches = PACKAGES / name / 'debian/patches'
    series = [l.split()[0] for l in (patches / 'series').read_text().splitlines()
              if l.strip() and not l.startswith('#')] if (patches / 'series').exists() else []
    ours = sorted(str(p.relative_to(patches)) for p in (patches / TOPIC).glob('*.patch'))
    for entry in series:
        if not (patches / entry).exists():
            problems.append(f'series names a missing patch: {entry}')
    for entry in ours:
        if entry not in series:
            problems.append(f'{entry} is not in series')
    for entry in ours:
        fields = header((patches / entry).read_text(errors='replace'))
        for key in REQUIRED:
            if not fields.get(key):
                problems.append(f'{entry}: no {key}')
        if not (fields.get('Subject') or fields.get('Description')):
            problems.append(f'{entry}: no Subject/Description')
        if not (fields.get('From') or fields.get('Author') or fields.get('Origin')):
            problems.append(f'{entry}: no From/Author/Origin')
        if fields.get('Last-Update') and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', fields['Last-Update']):
            problems.append(f"{entry}: Last-Update {fields['Last-Update']!r} is not YYYY-MM-DD")
        status = fields.get('X-Rungic-Status', '')
        if status and status.split()[0].rstrip(';') not in STATUSES:
            problems.append(f'{entry}: X-Rungic-Status {status!r} is not one of {", ".join(STATUSES)}')
        if status.startswith('Submitted') and not fields.get('Forwarded', '').startswith('http'):
            problems.append(f'{entry}: Submitted but Forwarded has no URL')
    return problems


def verify(name, against):
    tree = source(name)
    result = subprocess.run(['diff', '-r', '-q', '-x', '.pc', '-x', 'patches', '-x', '.git', str(tree), str(against)],
                            capture_output=True, text=True)
    return result.returncode == 0, result.stdout


def test_matrix(selected):
    rows = []
    for name in selected:
        patches = PACKAGES / name / 'debian/patches'
        for patch in sorted((patches / TOPIC).glob('*.patch')):
            fields = header(patch.read_text(errors='replace'))
            tests = fields.get('X-Rungic-Tests', '')
            covered, planned = [], []
            for segment in re.split(r'[;]', tests):
                ids = re.findall(r'\b(?:L[0-3]|probe):[^\s,;()]+', segment)
                # "(to write)", "(to extend)": a test that does not exist yet does not cover the patch
                (planned if re.search(r'\(to (?:write|extend)\)', segment) else covered).extend(ids)
            rows.append({'package': name, 'patch': patch.name, 'status': fields.get('X-Rungic-Status', ''),
                         'tests': covered, 'planned': planned, 'note': tests})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('fetch', 'prepare', 'export'):
        sub.add_parser(command).add_argument('name')
    p = sub.add_parser('source')
    p.add_argument('name')
    p.add_argument('--output')
    p = sub.add_parser('lint')
    p.add_argument('names', nargs='*')
    p = sub.add_parser('verify')
    p.add_argument('name')
    p.add_argument('--against', required=True)
    p = sub.add_parser('tests')
    p.add_argument('names', nargs='*')
    p.add_argument('--gaps', action='store_true')
    args = parser.parse_args()
    if args.command == 'fetch':
        print(fetch(args.name))
    elif args.command == 'source':
        print(source(args.name, args.output))
    elif args.command == 'prepare':
        print(prepare(args.name))
    elif args.command == 'export':
        print('\n'.join(export(args.name)))
    elif args.command == 'lint':
        problems = {n: lint_package(n) for n in (args.names or names())}
        for name, items in problems.items():
            for item in items:
                print(f'{name}: {item}')
        return 1 if any(problems.values()) else 0
    elif args.command == 'verify':
        ok, text = verify(args.name, args.against)
        print(text or f'{args.name}: patched source equals {args.against}')
        return 0 if ok else 1
    elif args.command == 'tests':
        rows = test_matrix(args.names or names())
        for row in rows:
            if args.gaps and row['tests']:
                continue
            planned = f"  planned: {', '.join(row['planned'])}" if row['planned'] else ''
            print(f"{row['package']}/{row['patch']}: {', '.join(row['tests']) or '-'}  [{row['status'].split(' [')[0]}]{planned}"
                  + (f"  {row['note']}" if args.gaps or not row['tests'] else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
