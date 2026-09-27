#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a patch-queue component (packages/<name>, docs/71) natively in the phone's Ubuntu ARM64 container.

The source tree (tools/pq.py source: upstream + debian/ with the patches applied) is copied into a persistent
/root/rungic-build/<component>/src with `rsync --checksum`, so unchanged files
keep their timestamps and the kept obj-aarch64-linux-gnu tree rebuilds only
what changed.

  full         dpkg-buildpackage -b (clean configure; first build or packaging change)
  incremental  make in the existing obj dir, then `debian/rules binary` (skips
               configure/build through debhelper's stamp) to produce .debs
  targets      for trees without Debian packaging (recipe kind upstream/git): configure once in
               <component>/build (Ninja, /usr prefix) and build --target T...;
               a meson tree (Mesa) is configured with plasma/<component>-meson-options
  status       state of the build unit and the log tail
  install      dpkg -i the .debs of the last build (version from debian/changelog)
  collect      the last build's .debs and .ddebs into the release repository pool (rungic_release.py)
  divert       install built files over distribution ones with dpkg-divert
               (--file BUILT=INSTALLED, repeatable); the original stays as .distrib

Builds run as the transient system unit rungic-build-<component>, so they
survive adb disconnects; the log is /root/rungic-build/<component>/build.log.
"""
import argparse
import json
import subprocess
import tarfile
import time

import rungic_device
from rungic_device import WORKSPACE, out, run

BASE = '/root/rungic-build'
# Line tables only (-g1): enough for symbolized backtraces (docs/61) at a fraction of -g2's
# compile memory; debhelper strips the packages and puts the symbols into -dbgsym packages
# for the release repository.
DEBUG_FLAGS = 'DEB_CFLAGS_MAINT_APPEND=-g1 DEB_CXXFLAGS_MAINT_APPEND=-g1'


def stage(component):
    if not (WORKSPACE / 'packages' / component / 'recipe.json').exists():
        raise SystemExit(f'{component}: no packages/{component}/recipe.json (docs/71)')
    # A patch-queue component (docs/71): pinned upstream + packages/<name>/debian, patches applied.
    import pq
    source = str(pq.source(component))
    archive = WORKSPACE / f'.work/cache/{component}-stage.tar'
    with tarfile.open(archive, 'w') as tar:
        tar.add(source, arcname='src')
        tar.add(WORKSPACE / 'plasma/build-shims', arcname='cmake-shims')
        options = WORKSPACE / f'plasma/{component}-meson-options'
        if options.exists():
            tar.add(options, arcname='meson-options')
    return archive


def sync(component):
    work = f'{BASE}/{component}'
    rungic_device.run(f'rm -rf {work}/incoming', 'container')
    rungic_device.extract_in_container(stage(component), f'{work}/incoming')
    # Keep obj-* (build output) and debhelper state; everything else mirrors the stage.
    print(out(f'''set -e
chown -R root:root {work}/incoming
mkdir -p {work}/src
rsync -a --checksum --delete --itemize-changes --exclude '/obj-*' --exclude '/debian/.debhelper' \\
  --exclude '/debian/*-build-stamp' --exclude '/debian/files' --exclude '/debian/*.substvars' \\
  --exclude '/debian/tmp' {work}/incoming/src/ {work}/src/ | grep -v '^\\.' | head -40
rm -rf {BASE}/cmake-shims && mv {work}/incoming/cmake-shims {BASE}/cmake-shims
if [ -f {work}/incoming/meson-options ]; then mv {work}/incoming/meson-options {work}/meson-options; fi
rm -rf {work}/incoming
''', 'container', timeout=600))


def component_uses_meson(component):
    return (WORKSPACE / f'plasma/{component}-meson-options').exists()


def arch_only(component):
    """A patch-queue component whose recipe sets build_arch_only: its architecture-independent
    packages (documentation, examples) are neither built nor installed (docs/73)."""
    recipe = WORKSPACE / 'packages' / component / 'recipe.json'
    return recipe.exists() and bool(json.loads(recipe.read_text()).get('build_arch_only'))


def start(component, mode, jobs, targets=(), lto=True, cmake_args=()):
    work = f'{BASE}/{component}'
    maint = '' if lto else ' DEB_BUILD_MAINT_OPTIONS=optimize=-lto'
    obj = f'{work}/src/obj-aarch64-linux-gnu'
    if mode == 'targets' and component_uses_meson(component):
        build = f'{work}/build'
        steps = (f"cd {work} && (test -f {build}/build.ninja || meson setup {build} src \\$(cat {work}/meson-options)) && "
                 f"ninja -C {build} -j {jobs} {' '.join(targets)}")
    elif mode == 'targets':
        build = f'{work}/build'
        steps = (f"cd {work} && (test -f {build}/build.ninja || cmake -S src -B {build} -G Ninja "
                 f"-DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF {' '.join(cmake_args)}) && "
                 f"cmake --build {build} -j {jobs} --target {' '.join(targets)}")
    elif mode == 'full':
        steps = (f"export DEB_BUILD_OPTIONS='nocheck parallel={jobs}' {DEBUG_FLAGS}{maint}; "
                 f"cd {work}/src && dpkg-buildpackage {'-B' if arch_only(component) else '-b'} -uc -us")
    else:
        steps = (f"export DEB_BUILD_OPTIONS='nocheck parallel={jobs}' {DEBUG_FLAGS}{maint}; "
                 f"cd {work}/src && test -d {obj} && make -C {obj} -j{jobs} && debian/rules binary")
    run(f'''set -e
# RemainAfterExit keeps the last build's result and MemoryPeak readable until the next one.
systemctl stop rungic-build-{component} 2>/dev/null || true
systemctl reset-failed rungic-build-{component} 2>/dev/null || true
systemd-run --unit=rungic-build-{component} --nice=10 --property=IOSchedulingClass=idle --property=MemoryAccounting=yes \\
  --property=RemainAfterExit=yes \\
  --setenv=HOME=/root --property=StandardOutput=truncate:{work}/build.log --property=StandardError=inherit \\
  /bin/sh -c "{steps}"
''', 'container')
    print(f'started rungic-build-{component} ({mode}); follow with: build_on_device.py {component} status')


def status(component):
    return out(f'''systemctl show -p ActiveState -p SubState -p Result -p ExecMainStartTimestamp -p ExecMainExitTimestamp \
  -p ExecMainStatus -p MemoryPeak -p CPUUsageNSec rungic-build-{component}
grep -E '^\\[ *[0-9]+%\\]|^\\[[0-9]+/[0-9]+\\]|error|Error|warning: unused|dpkg-deb: building' {BASE}/{component}/build.log 2>/dev/null | tail -n 8 | cut -c1-200
ls -1t {BASE}/{component}/*.deb 2>/dev/null | head -12''', 'container')


def install(component):
    version = out(f"dpkg-parsechangelog -l {BASE}/{component}/src/debian/changelog -S Version | sed 's/^[0-9]*://'",
                  'container').strip()
    return out(f'''set -e
cd {BASE}/{component}
debs=$(ls *_{version}_*.deb | grep -v -e -dbgsym)
echo "installing: $debs"
dpkg -i $debs   # apt holds on these packages stay in place; dpkg ignores them
''', 'container', timeout=600)


def build_deps(component):
    """apt-get build-dep for the staged Debian source (full builds)."""
    return out(f'''set -e
[ -r /etc/profile.d/proxy.sh ] && . /etc/profile.d/proxy.sh
cd {BASE}/{component}/src
dpkg-checkbuilddeps {'-B ' if arch_only(component) else ''}2>/dev/null || DEBIAN_FRONTEND=noninteractive apt-get build-dep -y -q {'--arch-only ' if arch_only(component) else ''}. | tail -2
''', 'container', timeout=3600)


def collect(component):
    """The last build's .debs (and .ddeb debug symbols, renamed .deb for the index) into the release
    repository pool (docs/61)."""
    import rungic_release
    from pathlib import Path
    version = out(f"dpkg-parsechangelog -l {BASE}/{component}/src/debian/changelog -S Version | sed 's/^[0-9]*://'",
                  'container').strip()
    names = out(f"cd {BASE}/{component} && ls *_{version}_*.deb *_{version}_*.ddeb 2>/dev/null || true", 'container').split()
    incoming = WORKSPACE / '.work/apt/incoming'
    incoming.mkdir(parents=True, exist_ok=True)
    for name in names:
        target = incoming / (name[:-5] + '.deb' if name.endswith('.ddeb') else name)
        rungic_device.from_container(f'{BASE}/{component}/{name}', target)
    added = rungic_release.import_debs(sorted(incoming.glob('*.deb')))
    for path in incoming.glob('*.deb'):
        path.unlink()
    rungic_release.index()
    return f'{version}: {len(names)} files, added {added}'


def divert(component, files):
    lines = ['set -e']
    for spec in files:
        built, installed = spec.split('=', 1)
        lines.append(f'''[ -e {installed}.distrib ] || dpkg-divert --local --add --rename --divert {installed}.distrib {installed}
install -m644 {BASE}/{component}/build/{built} {installed}
echo "{installed} <- {built}"''')
    return out('\n'.join(lines), 'container')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('component')
    parser.add_argument('action', choices=['full', 'incremental', 'targets', 'status', 'install', 'divert', 'wait',
                                           'collect'])
    parser.add_argument('--target', action='append', default=[], help='CMake target (targets mode)')
    parser.add_argument('--file', action='append', default=[], help='BUILT=INSTALLED (divert mode)')
    parser.add_argument('--cmake-arg', action='append', default=[], help='extra configure argument (targets mode)')
    parser.add_argument('--jobs', type=int, default=4, help='compile jobs; 8 cores, ~7 GiB RAM, and builds push '
                        'the phone to thermal throttling, so more jobs gain little')
    parser.add_argument('--no-lto', action='store_true', help='development build: skip Ubuntu\'s default LTO '
                        '(much faster link; do not use for performance measurements)')
    args = parser.parse_args()
    if args.action in ('full', 'incremental', 'targets'):
        if args.action == 'targets' and not args.target and not component_uses_meson(args.component):
            parser.error('targets mode needs --target (a meson tree builds everything without one)')
        sync(args.component)
        if args.action == 'full':
            print(build_deps(args.component))
        start(args.component, args.action, args.jobs, args.target, not args.no_lto, args.cmake_arg)
    elif args.action == 'divert':
        print(divert(args.component, args.file))
    elif args.action == 'status':
        print(status(args.component))
    elif args.action == 'collect':
        print(collect(args.component))
    elif args.action == 'wait':
        while 'SubState=running' in (text := status(args.component)) or 'ActiveState=activating' in text:
            time.sleep(30)
        print(text)
    else:
        print(install(args.component))


if __name__ == '__main__':
    main()
