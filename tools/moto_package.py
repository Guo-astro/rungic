#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build this project's own Debian packages (moto-*) from plasma/packaging/<name>/ (docs/61).

Each package directory holds:
  package.json  name, architecture (all|arm64), build (host|device), paths (repository paths
                the package is built from: a change there means a rebuild), depends,
                build_depends (installed on the phone before a device build), description,
                obsolete (files of the old manual installs that postinst removes once the
                package's own copies are in place), units {system: [...], user: [...]} to enable,
                conffiles are every file under /etc
  build.sh      POSIX sh, run with DESTDIR (the package root) and SRC (the repository tree);
                installs the files into $DESTDIR
  preinst, postinst, prerm, postrm   optional maintainer script bodies; the generated
                postinst removes 'obsolete', reloads systemd and enables 'units' first

Host packages are built here (reproducibly: SOURCE_DATE_EPOCH is the commit time); device
packages are built in the phone's container, in a transient unit, with dpkg-shlibdeps adding
library dependencies. Versions are 0.<commit count>, with +bN when a rebuild of the same
commit differs. Built packages go to the release pool (.work/apt/repo) and are recorded in
.work/apt/project-builds.json with the git tree hash of their paths, so an unchanged
package is not rebuilt.

  moto_package.py list                    packages and whether they are current
  moto_package.py build NAME... | --all   build what changed (--force: even if current)
"""
import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import moto_device
from moto_device import PLASMA_ROOTFS, WORKSPACE, push, run
import moto_release

PACKAGING = WORKSPACE / 'plasma/packaging'
BUILDS = moto_release.APT / 'project-builds.json'
DEVICE_BASE = '/root/moto-packages'
MAINTAINER = 'range-dev <noreply@localhost>'


def definitions():
    result = {}
    for spec in sorted(PACKAGING.glob('*/package.json')):
        data = json.loads(spec.read_text())
        data['dir'] = spec.parent
        result[data['name']] = data
    return result


def git(*args):
    return subprocess.run(['git', *args], cwd=WORKSPACE, capture_output=True, text=True, check=True).stdout.strip()


def tree_hash(pkg):
    """Content identity of a package: the git trees/blobs of its paths and its own directory."""
    paths = sorted(set(pkg['paths']) | {str(pkg['dir'].relative_to(WORKSPACE))})
    dirty = git('status', '--porcelain', '--', *paths)
    if dirty:
        raise SystemExit(f"{pkg['name']}: uncommitted changes in its paths:\n{dirty}")
    ids = [f"{p}={git('rev-parse', f'HEAD:{p}')}" for p in paths]
    return hashlib.sha256('\n'.join(ids).encode()).hexdigest()[:16]


def builds():
    return json.loads(BUILDS.read_text()) if BUILDS.exists() else {}


def current(pkg):
    record = builds().get(pkg['name'])
    return bool(record) and record['tree'] == tree_hash(pkg) and \
        (moto_release.POOL / record['file']).exists()


def maintainer_scripts(pkg, root):
    """DEBIAN/{preinst,postinst,prerm,postrm} and conffiles."""
    debian = root / 'DEBIAN'
    units = pkg.get('units', {})
    obsolete = pkg.get('obsolete', [])
    post = ['#!/bin/sh', 'set -e', '']
    if obsolete:
        post += ['# Files of the manual installation this package replaces (docs/61).',
                 'if [ "$1" = configure ]; then',
                 # Patterns with * expand; other paths are quoted.
                 '  for f in ' + ' '.join(p if '*' in p else shlex.quote(p) for p in obsolete) + '; do',
                 '    if [ -L "$f" ] || [ -f "$f" ]; then rm -f "$f"; elif [ -d "$f" ]; then rm -rf "$f"; fi',
                 '  done',
                 'fi', '']
    if units.get('system') or units.get('user') or pkg.get('user_systemd'):
        post += ['if [ -d /run/systemd/system ]; then systemctl daemon-reload || true; fi']
    if units.get('user') or pkg.get('user_systemd'):
        # Running user managers keep the unit files and drop-ins they loaded; a session restart
        # would otherwise start the old (possibly deleted) command lines.
        post += ['for dir in /run/user/*; do',
                 '  uid=${dir##*/}; [ -S "$dir/systemd/private" ] || continue',
                 '  name=$(getent passwd "$uid" | cut -d: -f1); [ -n "$name" ] || continue',
                 '  runuser -u "$name" -- env XDG_RUNTIME_DIR="$dir" systemctl --user daemon-reload || true',
                 'done']
    for unit in units.get('system', []):
        post += [f'if [ "$1" = configure ] && [ -z "$2" ]; then systemctl enable {unit} || true; fi']
    for unit in units.get('user', []):
        post += [f'if [ "$1" = configure ]; then systemctl --global enable {unit} || true; fi']
    custom = pkg['dir'] / 'postinst'
    if custom.exists():
        post += ['', custom.read_text().replace('#!/bin/sh\n', '')]
    scripts = {'postinst': '\n'.join(post) + '\n'}
    prerm = ['#!/bin/sh', 'set -e']
    for unit in units.get('system', []):
        prerm += [f'if [ "$1" = remove ]; then systemctl disable {unit} || true; fi']
    for unit in units.get('user', []):
        prerm += [f'if [ "$1" = remove ]; then systemctl --global disable {unit} || true; fi']
    if (pkg['dir'] / 'prerm').exists():
        prerm += [(pkg['dir'] / 'prerm').read_text().replace('#!/bin/sh\n', '')]
    scripts['prerm'] = '\n'.join(prerm) + '\n'
    for name in ('preinst', 'postrm'):
        if (pkg['dir'] / name).exists():
            scripts[name] = (pkg['dir'] / name).read_text()
    for name, text in scripts.items():
        path = debian / name
        path.write_text(text)
        path.chmod(0o755)
    etc = root / 'etc'
    conffiles = sorted('/' + str(p.relative_to(root)) for p in etc.rglob('*')
                       if (p.is_file() or p.is_symlink()) and not p.is_symlink()) if etc.exists() else []
    if conffiles:
        (debian / 'conffiles').write_text('\n'.join(conffiles) + '\n')


def control(pkg, version, root, extra_depends=''):
    size = sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink()) // 1024 + 1
    depends = ', '.join(d for d in (pkg.get('depends', ''), extra_depends) if d)
    fields = {'Package': pkg['name'], 'Version': version, 'Architecture': pkg['architecture'],
              'Maintainer': MAINTAINER, 'Installed-Size': str(size), 'Section': 'misc', 'Priority': 'optional'}
    for key, name in (('depends', 'Depends'), ('recommends', 'Recommends'), ('conflicts', 'Conflicts'),
                      ('replaces', 'Replaces'), ('breaks', 'Breaks'), ('provides', 'Provides')):
        value = depends if key == 'depends' else pkg.get(key)
        if value:
            fields[name] = value
    summary, _, body = pkg['description'].partition('\n')
    text = ''.join(f'{k}: {v}\n' for k, v in fields.items())
    text += f'Description: {summary}\n'
    for line in (body.strip() or summary).splitlines():
        text += f' {line.strip() or "."}\n'
    (root / 'DEBIAN/control').write_text(text)


def next_version(name, file_bytes=None):
    base = f"0.{git('rev-list', '--count', 'HEAD')}"
    have = moto_release.pool_debs().get(name, {})
    if base not in have:
        return base
    if file_bytes is not None and have[base].read_bytes() == file_bytes:
        return base
    n = 1
    while f'{base}+b{n}' in have:
        n += 1
    return f'{base}+b{n}'


def record(pkg, version, deb, tree):
    data = builds()
    data[pkg['name']] = {'version': version, 'file': deb.name, 'tree': tree, 'commit': git('rev-parse', 'HEAD'),
                         'built': time.strftime('%Y-%m-%dT%H:%M:%S')}
    BUILDS.parent.mkdir(parents=True, exist_ok=True)
    BUILDS.write_text(json.dumps(data, indent=1, sort_keys=True) + '\n')


def build_host(pkg, tree):
    epoch = git('log', '-1', '--format=%ct')
    work = Path(tempfile.mkdtemp(dir=WORKSPACE / '.work/cache', prefix=f"{pkg['name']}-"))
    try:
        root = work / 'root'
        (root / 'DEBIAN').mkdir(parents=True)
        env = dict(os.environ, DESTDIR=str(root), SRC=str(WORKSPACE), SOURCE_DATE_EPOCH=epoch, LC_ALL='C.UTF-8')
        subprocess.run(['sh', '-eu', str(pkg['dir'] / 'build.sh')], cwd=WORKSPACE, env=env, check=True)
        maintainer_scripts(pkg, root)
        for path in [root, *root.rglob('*')]:   # normalized modes and times: reproducible output
            if not path.is_symlink():
                mode = path.stat().st_mode
                path.chmod(0o755 if path.is_dir() or mode & 0o111 else 0o644)
            os.utime(path, (int(epoch), int(epoch)), follow_symlinks=False)
        tmp = work / 'out.deb'

        def pack(version):
            control(pkg, version, root)
            os.utime(root / 'DEBIAN/control', (int(epoch), int(epoch)))
            subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(root), str(tmp)],
                           check=True, capture_output=True, env=env)
            return tmp.read_bytes()

        # 0.<commit count>, unless the pool has that version with other contents: then +bN.
        base = f"0.{git('rev-list', '--count', 'HEAD')}"
        existing = moto_release.pool_debs().get(pkg['name'], {}).get(base)
        version = base
        if existing is not None and pack(base) != existing.read_bytes():
            version = next_version(pkg['name'])
        pack(version)
        target = moto_release.POOL / f"{pkg['name']}_{version}_{pkg['architecture']}.deb"
        if not target.exists():
            shutil.copy2(tmp, target)
        record(pkg, version, target, tree)
        return target
    finally:
        shutil.rmtree(work)


def stage_sources(pkg):
    """The tracked files of the package's paths (symlinks resolved, so shared files come along) as a
    tar for the phone. Only tracked files: local build trees never reach a package build."""
    archive = WORKSPACE / f".work/cache/{pkg['name']}-src.tar"
    paths = sorted(set(pkg['paths']) | {str(pkg['dir'].relative_to(WORKSPACE))})
    files = subprocess.run(['git', 'ls-files', '-z', '--', *paths], cwd=WORKSPACE, capture_output=True,
                           check=True).stdout.decode().split('\0')
    with tarfile.open(archive, 'w', dereference=True) as tar:
        for name in filter(None, files):
            tar.add(WORKSPACE / name, arcname=name, recursive=False)
    return archive


def build_device(pkg, tree, jobs=4):
    name = pkg['name']
    base = f'{DEVICE_BASE}/{name}'
    if pkg.get('build_depends'):
        missing = run('dpkg-query -W -f \'${db:Status-Abbrev} ${Package}\\n\' '
                      + ' '.join(pkg['build_depends']) + ' 2>&1 | grep -v "^ii" || true', 'container').stdout
        if missing.strip():
            print(f'installing build dependencies of {name}: {" ".join(pkg["build_depends"])}', flush=True)
            run('DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends '
                + ' '.join(pkg['build_depends']), 'container', timeout=3600)
    remote = push(stage_sources(pkg), f'{name}-src.tar', timeout=1800)
    run(f'''set -e
rm -rf {PLASMA_ROOTFS}{base}/src {PLASMA_ROOTFS}{base}/root
mkdir -p {PLASMA_ROOTFS}{base}/src
tar -xf {remote} -C {PLASMA_ROOTFS}{base}/src --no-same-owner
rm -f {remote}''', 'root', timeout=600)
    work = WORKSPACE / f'.work/cache/{name}-device'
    shutil.rmtree(work, ignore_errors=True)
    (work / 'DEBIAN').mkdir(parents=True)
    maintainer_scripts(pkg, work)          # conffiles are listed after the build, on the phone
    for script in (work / 'DEBIAN').iterdir():
        if script.name != 'conffiles':
            run(f'mkdir -p {base}/debian-scripts', 'container')
            r = push(script, f'{name}-{script.name}')
            run(f'install -m755 {r} {PLASMA_ROOTFS}{base}/debian-scripts/{script.name} && rm -f {r}', 'root')
    shutil.rmtree(work)
    epoch = git('log', '-1', '--format=%ct')
    unit = f'moto-package-{name}'
    script = f'''set -e
cd {base}
export DESTDIR={base}/root SRC={base}/src SOURCE_DATE_EPOCH={epoch} JOBS={jobs} LC_ALL=C.UTF-8
rm -rf "$DESTDIR"; mkdir -p "$DESTDIR/DEBIAN"
sh -eu "$SRC/{pkg['dir'].relative_to(WORKSPACE)}/build.sh"
cp debian-scripts/* "$DESTDIR/DEBIAN/"
# Debug information to {base}/dbgsym by build-id (for NAME-dbgsym), then strip (docs/61).
rm -rf {base}/dbgsym
find "$DESTDIR" -type f ! -path "$DESTDIR/DEBIAN/*" | while read -r f; do
  head -c4 "$f" | grep -q ELF || continue
  case "$(readelf -h "$f" 2>/dev/null | sed -n 's/^ *Type: *\\([A-Z]*\\).*/\\1/p')" in EXEC|DYN) ;; *) continue ;; esac
  id=$(readelf -n "$f" 2>/dev/null | sed -n 's/.*Build ID: \\([0-9a-f]*\\).*/\\1/p' | head -n1)
  if [ -n "$id" ] && readelf -S "$f" 2>/dev/null | grep -q '\\.debug_info'; then
    d={base}/dbgsym/usr/lib/debug/.build-id/$(echo "$id" | cut -c1-2)
    mkdir -p "$d"
    objcopy --only-keep-debug --compress-debug-sections "$f" "$d/$(echo "$id" | cut -c3-).debug"
  fi
  strip --strip-unneeded "$f"
done
if [ -d "$DESTDIR/etc" ]; then (cd "$DESTDIR" && find etc -type f | sort | sed 's|^|/|') > "$DESTDIR/DEBIAN/conffiles"; fi
[ -s "$DESTDIR/DEBIAN/conffiles" ] || rm -f "$DESTDIR/DEBIAN/conffiles"
# Library dependencies of the ELF files, as dpkg-shlibdeps computes them.
elves=$(find "$DESTDIR" -type f ! -path "$DESTDIR/DEBIAN/*" -exec sh -c 'head -c4 "$1" | grep -q ELF && echo "$1"' _ {{}} \\;)
rm -rf shlibs; mkdir -p shlibs/debian; printf 'Source: x\\n\\nPackage: {name}\\nArchitecture: any\\n' > shlibs/debian/control
if [ -n "$elves" ]; then
  # Libraries the package ships itself (private FFmpeg, plugins) resolve inside DESTDIR.
  libdirs=$(find "$DESTDIR" -name '*.so*' ! -path "$DESTDIR/DEBIAN/*" -printf '-l%h\n' | sort -u)
  (cd shlibs && dpkg-shlibdeps -O --ignore-missing-info $libdirs $elves 2>shlibs.err | sed -n 's/^shlibs:Depends=//p') > shlibs.txt || true
  [ ! -s shlibs/shlibs.err ] || sed 's/^/shlibdeps: /' shlibs/shlibs.err | head -5
else
  : > shlibs.txt
fi
find "$DESTDIR" -newermt "@$SOURCE_DATE_EPOCH" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {{}} + 2>/dev/null || true
du -sk --exclude=DEBIAN "$DESTDIR" | cut -f1 > size.txt
'''
    run(f'mkdir -p {base} && cat > {base}/build-run.sh <<\'MOTO_EOF\'\n{script}MOTO_EOF', 'container')
    result = run(f'''systemctl reset-failed {unit} 2>/dev/null || true
systemd-run --unit={unit} --wait --pipe --collect --quiet -p TimeoutStartSec=14400 --nice=10 \\
  -p IOSchedulingClass=idle --setenv=HOME=/root sh -eu {base}/build-run.sh > {base}/build.log 2>&1; echo "exit=$?"; tail -30 {base}/build.log''',
                 'container', timeout=14500, check=False)
    if 'exit=0' not in result.stdout:
        raise SystemExit(f'{name}: device build failed\n{result.stdout[-4000:]}{result.stderr[-1000:]}')
    shlibs = run(f'cat {base}/shlibs.txt', 'container').stdout.strip()
    # Control file with the version, built here, then the .deb on the phone.
    version = next_version(name)
    ctl = WORKSPACE / f'.work/cache/{name}-control'
    fake = WORKSPACE / f'.work/cache/{name}-ctlroot'
    shutil.rmtree(fake, ignore_errors=True)
    (fake / 'DEBIAN').mkdir(parents=True)
    control(pkg, version, fake, shlibs)
    size = run(f'cat {base}/size.txt', 'container').stdout.strip()
    text = (fake / 'DEBIAN/control').read_text()
    text = '\n'.join(f'Installed-Size: {size}' if l.startswith('Installed-Size:') else l
                     for l in text.splitlines()) + '\n'
    ctl.write_text(text)
    shutil.rmtree(fake)
    r = push(ctl, f'{name}-control')
    deb_name = f'{name}_{version}_{pkg["architecture"]}.deb'
    run(f'install -m644 {r} {PLASMA_ROOTFS}{base}/root/DEBIAN/control && rm -f {r}', 'root')
    run(f'cd {base} && dpkg-deb --root-owner-group -Zxz --build root {deb_name} >/dev/null', 'container',
        timeout=1800)
    ctl.unlink()
    debs = [deb_name]
    # Debug symbols, when there are any: NAME-dbgsym at the same version, in the release repository
    # for moto-crash-symbols; never a dependency of the release.
    dbg_name = f'{name}-dbgsym_{version}_{pkg["architecture"]}.deb'
    dbg_control = (f'Package: {name}-dbgsym\nVersion: {version}\nArchitecture: {pkg["architecture"]}\n'
                   f'Maintainer: {MAINTAINER}\nSection: debug\nPriority: optional\n'
                   f'Depends: {name} (= {version})\nDescription: debug symbols for {name}\n')
    made = run(f'''cd {base}
[ -d dbgsym/usr/lib/debug ] || exit 3
mkdir -p dbgsym/DEBIAN && printf '%s' {shlex.quote(dbg_control)} > dbgsym/DEBIAN/control
dpkg-deb --root-owner-group -Zxz --build dbgsym {dbg_name} >/dev/null''', 'container', timeout=1800, check=False)
    if made.returncode == 0:
        debs.append(dbg_name)
    for deb in debs:
        local = WORKSPACE / f'.work/cache/{deb}'
        moto_release.pull(f'{PLASMA_ROOTFS}{base}/{deb}', local)
        shutil.move(local, moto_release.POOL / deb)
    target = moto_release.POOL / deb_name
    record(pkg, version, target, tree)
    return target


def build(names, force=False, jobs=4):
    defs = definitions()
    done = []
    for name in names:
        pkg = defs.get(name) or sys.exit(f'no package {name} in {PACKAGING}')
        tree = tree_hash(pkg)
        if not force and current(pkg):
            done.append({'package': name, 'version': builds()[name]['version'], 'built': False})
            continue
        print(f'building {name} ({pkg["build"]})', flush=True)
        deb = build_host(pkg, tree) if pkg['build'] == 'host' else build_device(pkg, tree, jobs)
        done.append({'package': name, 'version': builds()[name]['version'], 'built': True, 'file': deb.name})
    moto_release.index()
    return done


def listing():
    rows = []
    recorded = builds()
    for name, pkg in definitions().items():
        try:
            state = 'current' if current(pkg) else 'stale' if name in recorded else 'never built'
        except SystemExit as error:
            state = f'uncommitted: {error}'.splitlines()[0]
        rows.append({'package': name, 'build': pkg['build'], 'architecture': pkg['architecture'],
                     'version': recorded.get(name, {}).get('version'), 'state': state})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list')
    p = sub.add_parser('build'); p.add_argument('names', nargs='*'); p.add_argument('--all', action='store_true')
    p.add_argument('--force', action='store_true'); p.add_argument('--jobs', type=int, default=4)
    a = parser.parse_args()
    if a.cmd == 'list':
        result = listing()
    else:
        names = list(definitions()) if a.all else a.names
        if not names:
            parser.error('name packages or pass --all')
        result = build(names, a.force, a.jobs)
    print(json.dumps(result, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
