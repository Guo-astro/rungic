#!/usr/bin/env python3
"""One-time conversion of a vendored component's history into a patch queue (docs/71).

Reads a plan (tools/pq-history/<package>.json) naming, in order, the steps that turned the pristine
upstream tree (the vendor import commit) into today's vendor/<component>: historical patch files
and repository commits. Builds .work/pq/<package> as git-buildpackage expects (the Ubuntu source
with patches unapplied on the packaging branch, `gbp pq import` for the distribution's patches),
adds one patch-queue commit per step with the plan's DEP-3 and X-Rungic-* trailers, and checks
that the result equals the vendored tree. `tools/pq.py export` then writes debian/patches.

Symlinks into the repository (shared headers) are replaced by the file they point to at that
commit: a patch cannot carry a symlink. Paths in the recipe's 'overlay' (shared files placed into
the tree by tools/pq.py) are left out of the steps: the base already has them. A step marked
"distribution" is a change the distribution's own patches make (applied on import to the vendored
tree): it is recorded but not repeated. A plan with "reference_lacks_distribution_patches" compares the
result with the vendored tree plus the distribution's patches (a vendored plain upstream whose
libraries were swapped into the distribution's binary packages).

  pq_import_history.py kwin [--ref C]  build .work/pq/kwin and verify against C:vendor/kwin (default
                                      HEAD; the vendored trees are gone after their migration commit)
"""
import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import io
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
IMAGE = 'rungic-pq:26.04'


def git(*args, cwd=WORKSPACE, input=None, check=True):
    return subprocess.run(['git', *args], cwd=cwd, input=input, capture_output=True, check=check).stdout


def tool(work, *argv):
    """Run a packaging tool from the pinned toolchain image (tools/pq/Dockerfile) in `work`."""
    result = subprocess.run(['docker', 'run', '--rm', '-u', f'{uid()}:{gid()}', '-e', 'HOME=/tmp',
                             '-v', f'{work}:/w', '-w', '/w', IMAGE, *argv], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f'{argv[0]} failed:\n{result.stdout}\n{result.stderr}')
    return result.stdout


def uid():
    import os
    return os.getuid()


def gid():
    import os
    return os.getgid()


def tree_at(commit, path, dest):
    """Extract commit:path into dest, with symlinks into the repository replaced by their target."""
    data = git('archive', commit, path)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter='tar')
    root = Path(dest) / path
    for link in [p for p in root.rglob('*') if p.is_symlink()]:
        target = (Path(path) / link.relative_to(root)).parent / link.readlink()
        resolved = Path(subprocess.run(['realpath', '-m', '--relative-to', '.', str(target)], cwd=WORKSPACE,
                                       capture_output=True, text=True).stdout.strip())
        content = git('show', f'{commit}:{resolved}')
        link.unlink()
        link.write_bytes(content)
    return root


def trailers(step):
    lines = [f'{key}: {value}' for key, value in step.get('dep3', {}).items()]
    lines.append('Gbp-Pq: Topic rungic')
    lines.append(f"Gbp-Pq: Name {step['name']}.patch")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('package')
    parser.add_argument('--ref', default='HEAD', help='commit whose vendor/<component> the result must equal')
    args = parser.parse_args()
    plan = json.loads((WORKSPACE / 'tools/pq-history' / f'{args.package}.json').read_text())
    component = plan['vendor']                       # e.g. vendor/kwin
    sources = WORKSPACE / '.work/sources' / args.package
    work = WORKSPACE / '.work/pq' / args.package
    scratch = WORKSPACE / '.work/pq-history' / args.package
    for d in (work, scratch):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)

    sys.path.insert(0, str(WORKSPACE / 'tools'))
    import pq
    shutil.rmtree(work)
    if 'dsc' in plan:
        # Packaging branch: the Ubuntu source as git-ubuntu imports it (patches unapplied).
        subprocess.run(['docker', 'run', '--rm', '-u', f'{uid()}:{gid()}', '-v', f'{sources}:/src:ro',
                        '-v', f'{work.parent}:/w', '-w', '/w', IMAGE, 'dpkg-source', '-q', '--skip-patches', '-x',
                        f"/src/{plan['dsc']}", f'{args.package}.x'], capture_output=True, check=True)
        (work.parent / f'{args.package}.x').rename(work)
    else:
        # An upstream one of this project's packages builds: its tarball, and an empty series for gbp.
        unpack = scratch / 'upstream'
        with tarfile.open(pq.orig_tarball(args.package)) as tar:
            tar.extractall(unpack, filter='tar')
        [top] = list(unpack.iterdir())
        top.rename(work)
        (work / 'debian/patches').mkdir(parents=True)
        (work / 'debian/patches/series').write_text('')
        pq.gbp_stub(args.package, work)
    overlay = pq.overlay(args.package)
    pq.add_overlay(args.package, work)
    git('init', '-q', '-b', 'rungic', cwd=work)
    git('add', '-A', cwd=work)
    git('-c', 'user.name=Rungic', '-c', 'user.email=noreply@rungic.invalid', 'commit', '-q', '-m',
        f"{args.package} {plan['version']} ({'Ubuntu source' if 'dsc' in plan else 'upstream'}, patches unapplied"
        + (', shared overlay files' if overlay else '') + ')', cwd=work)
    tool(work, 'gbp', 'pq', 'import')

    # One commit per step, each the difference its step made to the vendored tree: every state is
    # committed in a scratch repository so the diffs have plain relative paths.
    hist = scratch / 'hist'
    hist.mkdir()
    git('init', '-q', cwd=hist)

    def record(tree, label):
        for entry in hist.iterdir():
            if entry.name != '.git':
                shutil.rmtree(entry) if entry.is_dir() and not entry.is_symlink() else entry.unlink()
        shutil.copytree(tree, hist, symlinks=True, dirs_exist_ok=True)
        git('add', '-A', cwd=hist)
        git('-c', 'user.name=h', '-c', 'user.email=h@h', 'commit', '-q', '--allow-empty', '-m', label, cwd=hist)

    previous = tree_at(plan['base'], component, scratch / 'base')
    record(previous, 'base')
    for i, step in enumerate(plan['steps']):
        after = scratch / f'step{i}'
        if 'patch' in step:
            shutil.copytree(previous, after, symlinks=True)
            subprocess.run(['patch', '-s', '-p1', '--no-backup-if-mismatch', '-d', str(after),
                            '-i', str(WORKSPACE / step['patch'])], check=True)
            new = after
        else:
            new = tree_at(step['commit'], component, after)
        record(new, step['name'])
        diff = git('diff', '--binary', 'HEAD~1', 'HEAD', '--', '.', ':!debian',
                   *[f':!{path}' for path in overlay], cwd=hist)
        previous = new
        if step.get('distribution'):
            print(f"{step['name']}: made by the distribution's patches, not repeated")
            continue
        if not diff.strip():
            print(f"{step['name']}: no change outside debian/")
            continue
        subprocess.run(['git', 'apply', '--whitespace=nowarn', '-'], cwd=work, input=diff, check=True)
        git('add', '-A', cwd=work)
        message = f"{step['subject']}\n\n{step.get('description', '').strip()}\n\n{trailers(step)}\n"
        git('-c', 'user.name=' + step.get('author_name', 'Rungic'), '-c',
            'user.email=' + step.get('author_email', 'noreply@rungic.invalid'), 'commit', '-q', '-m', message,
            '--date', step.get('date', '2026-09-23T00:00:00'), cwd=work)

    # The patch queue applied must be the vendored tree (debian/ is compared separately).
    final = tree_at(args.ref, component, scratch / 'head') / ''
    if plan.get('reference_lacks_distribution_patches'):
        # The vendored tree was the plain upstream plus ours (its libraries were swapped into the
        # distribution's binary packages): compare it with the distribution's patches applied.
        patches = work / 'debian/patches'
        for line in (patches / 'series').read_text().splitlines():
            name = line.split('#')[0].strip()
            if name and not name.startswith('rungic/'):
                subprocess.run(['patch', '-s', '-p1', '--no-backup-if-mismatch', '-d', str(final), '-i',
                                str(patches / name)], check=True)
                print(f'reference: {name} (distribution) applied')
    lines = pq.tree_diff(work, final, ('.pc', 'debian', '.git'))

    def overlay_only(line):
        # Files the overlay adds (not replacing an upstream file) are ours, not in the vendored tree.
        prefix = f'Only in {work}'
        if not line.startswith(prefix):
            return False
        where, _, name = line[len(prefix):].partition(': ')
        rel = (where.strip('/') + '/' + name).strip('/')
        return any(path == rel or path.startswith(rel + '/') for path in overlay)
    lines = [line for line in lines if not overlay_only(line)]
    print('\n'.join(lines) or f'{args.package}: patch queue reproduces {args.ref}:{component} (debian/ and .pc aside)')
    return 1 if lines else 0


if __name__ == '__main__':
    sys.exit(main())
