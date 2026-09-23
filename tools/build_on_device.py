#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build a vendored Debian package natively in the phone's Ubuntu ARM64 container.

The staged tree (tools/stage_vendor.py) is copied into a persistent
/root/moto-build/<component>/src with `rsync --checksum`, so unchanged files
keep their timestamps and the kept obj-aarch64-linux-gnu tree rebuilds only
what changed.

  full         dpkg-buildpackage -b (clean configure; first build or packaging change)
  incremental  make in the existing obj dir, then `debian/rules binary` (skips
               configure/build through debhelper's stamp) to produce .debs
  targets      for vendor trees without Debian packaging: configure once in
               <component>/build (Ninja, /usr prefix) and build --target T...
  status       state of the build unit and the log tail
  install      dpkg -i the .debs of the last build (version from debian/changelog)
  divert       install built files over distribution ones with dpkg-divert
               (--file BUILT=INSTALLED, repeatable); the original stays as .distrib

Builds run as the transient system unit moto-build-<component>, so they
survive adb disconnects; the log is /root/moto-build/<component>/build.log.
"""
import argparse
import subprocess
import tarfile
import time

import moto_device
from moto_device import PLASMA_ROOTFS, WORKSPACE, out, push, run

BASE = '/root/moto-build'


def stage(component):
    source = subprocess.run(['python3', str(WORKSPACE / 'tools/stage_vendor.py'), component],
                            check=True, capture_output=True, text=True).stdout.strip()
    archive = WORKSPACE / f'.work/cache/{component}-stage.tar'
    with tarfile.open(archive, 'w') as tar:
        tar.add(source, arcname='src')
        tar.add(WORKSPACE / 'plasma/build-shims', arcname='cmake-shims')
    return archive


def sync(component):
    remote = push(stage(component), f'moto-{component}-stage.tar')
    work = f'{BASE}/{component}'
    out(f'''set -e
mkdir -p {PLASMA_ROOTFS}{work}/incoming
rm -rf {PLASMA_ROOTFS}{work}/incoming/src
tar -xf {remote} -C {PLASMA_ROOTFS}{work}/incoming
rm -f {remote}
''')
    # Keep obj-* (build output) and debhelper state; everything else mirrors the stage.
    print(out(f'''set -e
chown -R root:root {work}/incoming
mkdir -p {work}/src
rsync -a --checksum --delete --itemize-changes --exclude '/obj-*' --exclude '/debian/.debhelper' \\
  --exclude '/debian/*-build-stamp' --exclude '/debian/files' --exclude '/debian/*.substvars' \\
  --exclude '/debian/tmp' {work}/incoming/src/ {work}/src/ | grep -v '^\\.' | head -40
rm -rf {BASE}/cmake-shims && mv {work}/incoming/cmake-shims {BASE}/cmake-shims
rm -rf {work}/incoming
''', 'container', timeout=600))


def start(component, mode, jobs, targets=(), lto=True, cmake_args=()):
    work = f'{BASE}/{component}'
    maint = '' if lto else ' DEB_BUILD_MAINT_OPTIONS=optimize=-lto'
    obj = f'{work}/src/obj-aarch64-linux-gnu'
    if mode == 'targets':
        build = f'{work}/build'
        steps = (f"cd {work} && (test -f {build}/build.ninja || cmake -S src -B {build} -G Ninja "
                 f"-DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF {' '.join(cmake_args)}) && "
                 f"cmake --build {build} -j {jobs} --target {' '.join(targets)}")
    elif mode == 'full':
        steps = (f"export DEB_BUILD_OPTIONS='nocheck nostrip parallel={jobs}' DEB_CXXFLAGS_MAINT_APPEND=-g0{maint}; "
                 f"cd {work}/src && dpkg-buildpackage -b -uc -us")
    else:
        steps = (f"export DEB_BUILD_OPTIONS='nocheck nostrip parallel={jobs}' DEB_CXXFLAGS_MAINT_APPEND=-g0{maint}; "
                 f"cd {work}/src && test -d {obj} && make -C {obj} -j{jobs} && debian/rules binary")
    run(f'''set -e
systemctl reset-failed moto-build-{component} 2>/dev/null || true
systemd-run --unit=moto-build-{component} --nice=10 --property=IOSchedulingClass=idle \\
  --setenv=HOME=/root --property=StandardOutput=truncate:{work}/build.log --property=StandardError=inherit \\
  /bin/sh -c "{steps}"
''', 'container')
    print(f'started moto-build-{component} ({mode}); follow with: build_on_device.py {component} status')


def status(component):
    return out(f'''systemctl show -p ActiveState -p Result -p ExecMainStartTimestamp -p ExecMainExitTimestamp moto-build-{component}
grep -E '^\\[ *[0-9]+%\\]|error|Error|warning: unused|dpkg-deb: building' {BASE}/{component}/build.log 2>/dev/null | tail -n 8 | cut -c1-200
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
    parser.add_argument('action', choices=['full', 'incremental', 'targets', 'status', 'install', 'divert', 'wait'])
    parser.add_argument('--target', action='append', default=[], help='CMake target (targets mode)')
    parser.add_argument('--file', action='append', default=[], help='BUILT=INSTALLED (divert mode)')
    parser.add_argument('--cmake-arg', action='append', default=[], help='extra configure argument (targets mode)')
    parser.add_argument('--jobs', type=int, default=4, help='compile jobs; 8 cores, ~7 GiB RAM, and builds push '
                        'the phone to thermal throttling, so more jobs gain little')
    parser.add_argument('--no-lto', action='store_true', help='development build: skip Ubuntu\'s default LTO '
                        '(much faster link; do not use for performance measurements)')
    args = parser.parse_args()
    if args.action in ('full', 'incremental', 'targets'):
        if args.action == 'targets' and not args.target:
            parser.error('targets mode needs --target')
        sync(args.component)
        start(args.component, args.action, args.jobs, args.target, not args.no_lto, args.cmake_arg)
    elif args.action == 'divert':
        print(divert(args.component, args.file))
    elif args.action == 'status':
        print(status(args.component))
    elif args.action == 'wait':
        while 'ActiveState=active' in (text := status(args.component)) or 'ActiveState=activating' in text:
            time.sleep(30)
        print(text)
    else:
        print(install(args.component))


if __name__ == '__main__':
    main()
