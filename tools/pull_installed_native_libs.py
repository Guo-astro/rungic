#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract lib/ from the desktop APK installed on the phone, for Java-only APK rebuilds.

Use when this machine has no Rust/NDK build of packages/android-host: the installed
APK's native libraries are reused unchanged. Writes SHA256SUMS next to them so
the reused binaries stay identifiable.
"""
import argparse
import hashlib
import subprocess
import zipfile
from pathlib import Path

import rungic_device

DEFAULT = rungic_device.WORKSPACE / '.work/refs/plasma-mobile-20260923/native-libs'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path, nargs='?', default=DEFAULT)
    args = parser.parse_args()
    remote = rungic_device.out(f'pm path {rungic_device.apk()}', 'shell').splitlines()[0].split(':', 1)[1]
    apk = rungic_device.WORKSPACE / '.work/cache/installed-plasma.apk'
    apk.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(rungic_device.adb('pull', remote, str(apk)), check=True, capture_output=True,
                   stdin=subprocess.DEVNULL, timeout=600)
    sums = []
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            if name.startswith('lib/') and not name.endswith('/'):
                target = args.out / name
                target.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(name)
                target.write_bytes(data)
                sums.append(f'{hashlib.sha256(data).hexdigest()}  {name}')
    (args.out / 'SHA256SUMS').write_text('\n'.join(sums) + '\n')
    print(f'{len(sums)} native libraries from {remote} -> {args.out}')


if __name__ == '__main__':
    main()
