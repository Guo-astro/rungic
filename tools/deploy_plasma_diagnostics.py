#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install plasma/diagnostics (core capture, session journal) and the Android moto-plasma entry.

Idempotent. Does not restart the desktop unless --restart-session is given;
core limits and the session's journal output apply to processes started after
that restart. See docs/55-agent-native-debugging.md.
"""
import argparse
import io
import tarfile

import moto_device
from moto_device import PLASMA, PLASMA_ROOTFS, WORKSPACE, out, push, run

STAGE = '/var/tmp/moto-diagnostics'   # inside the container; /tmp may be a tmpfs there


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restart-session', action='store_true')
    args = parser.parse_args()
    bundle = io.BytesIO()
    with tarfile.open(fileobj=bundle, mode='w') as tar:
        for path in sorted((WORKSPACE / 'plasma/diagnostics').iterdir()):
            tar.add(path, arcname=path.name)
        tar.add(WORKSPACE / 'plasma/moto-plasma-session.service', arcname='moto-plasma-session.service')
    local = moto_device.WORKSPACE / '.work/cache/moto-diagnostics.tar'
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(bundle.getvalue())
    remote_tar = push(local)
    remote_entry = push(WORKSPACE / 'plasma/moto-plasma', 'moto-plasma.new')
    print(out(f'''
set -e
rm -rf {PLASMA_ROOTFS}{STAGE}; mkdir -p {PLASMA_ROOTFS}{STAGE}
tar -xf {remote_tar} -C {PLASMA_ROOTFS}{STAGE}
rm -f {remote_tar}
install -m 755 {remote_entry} {PLASMA}.new && mv {PLASMA}.new {PLASMA} && rm -f {remote_entry}
chcon u:object_r:adb_data_file:s0 {PLASMA}
'''))
    print(out(f'chown -R root:root {STAGE}; sh {STAGE}/install.sh; rm -rf {STAGE}', 'container', timeout=180))
    if args.restart_session:
        print(run(f'{PLASMA} restart-session', 'root', timeout=240).stdout)


if __name__ == '__main__':
    main()
