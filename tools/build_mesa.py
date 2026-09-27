#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build and package Mesa on the phone from its patch queue (packages/mesa, docs/73).

  build_mesa.py            meson build (build_on_device.py mesa targets, options from
                           plasma/mesa-meson-options), install into a stage, assemble the
                           packages with plasma/package-mesa.py, collect them into the release pool

The version is the first entry of packages/mesa/debian/changelog. The build runs in the phone's
container like any build_on_device.py build (a transient unit; its log is build.log).
"""
import re
import subprocess
import sys

import rungic_device
from rungic_device import WORKSPACE, run

BASE = '/root/rungic-build/mesa'


def step(*argv, timeout):
    result = subprocess.run([sys.executable, str(WORKSPACE / 'tools/build_on_device.py'), 'mesa', *argv],
                            capture_output=True, text=True, timeout=timeout)
    print((result.stdout + result.stderr).strip()[-1500:])
    if result.returncode:
        raise SystemExit(f'build_on_device.py mesa {" ".join(argv)} failed')


def main():
    changelog = (WORKSPACE / 'packages/mesa/debian/changelog').read_text()
    version = re.match(r'^\S+ \(([^)]+)\)', changelog)[1]
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=WORKSPACE, capture_output=True, text=True).stdout.strip()
    step('targets', timeout=3600)
    step('wait', timeout=4 * 3600)
    script = rungic_device.to_container(WORKSPACE / 'plasma/package-mesa.py', f'{BASE}/package-mesa.py', '755')
    print(run(f'''set -e
rm -rf {BASE}/stage {BASE}/*.deb {BASE}/debs
DESTDIR={BASE}/stage meson install -C {BASE}/build >/dev/null
RUNGIC_MESA_STAGE={BASE}/stage RUNGIC_MESA_PACKAGES={BASE}/debs RUNGIC_MESA_VERSION={version} \\
RUNGIC_MESA_SOURCE={BASE}/src RUNGIC_MESA_COMMIT={commit} python3 {script}
mv {BASE}/debs/*.deb {BASE}/
ls {BASE}/*.deb''', 'container', timeout=1800).stdout)
    step('collect', timeout=900)


if __name__ == '__main__':
    main()
