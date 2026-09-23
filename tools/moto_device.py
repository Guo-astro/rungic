#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Locate the development phone and run commands on Android, in LXC or as the desktop user.

Machine-specific values stay outside the repository:

  MOTO_ADB        adb executable (default: PATH, then common SDK locations)
  MOTO_SERIAL     hardware serial, ro.serialno (default ZY32MVJS25)
  MOTO_TRANSPORT  adb transport id to use as-is, e.g. 10.77.0.16:44995

The same keys may be written as KEY=VALUE lines in .work/device.env; the
environment wins. Without MOTO_TRANSPORT the phone is found by ro.serialno, so
a changing wireless-debugging port needs no edits.

Scripts are sent on stdin instead of being nested inside `adb shell su -c`
quoting. The exit status of the script is returned.
"""
import functools
import os
import shutil
import subprocess
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
DEFAULT_SERIAL = 'ZY32MVJS25'
PLASMA = '/data/adb/moto-plasma/moto-plasma'
PLASMA_ROOTFS = '/data/adb/moto-lxc/runtime/var/lib/lxc/plasma/rootfs'


class DeviceError(RuntimeError):
    pass


@functools.cache
def config():
    values = {}
    env_file = WORKSPACE / '.work/device.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"\'')
    for key in ('MOTO_ADB', 'MOTO_SERIAL', 'MOTO_TRANSPORT'):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


@functools.cache
def adb_path():
    candidates = [config().get('MOTO_ADB'), shutil.which('adb'),
                  str(Path.home() / 'Android/Sdk/platform-tools/adb'),
                  str(Path.home() / 'android-sdk/platform-tools/adb')]
    for candidate in candidates:
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    raise DeviceError('adb not found; set MOTO_ADB')


def serial():
    return config().get('MOTO_SERIAL', DEFAULT_SERIAL)


@functools.cache
def transport():
    """Return the adb transport id of the phone whose ro.serialno matches."""
    if config().get('MOTO_TRANSPORT'):
        return config()['MOTO_TRANSPORT']
    # stdin=DEVNULL: adb shell otherwise consumes the caller's stdin (e.g. an MCP stdio stream).
    out = subprocess.run([adb_path(), 'devices'], capture_output=True, text=True, timeout=15,
                         stdin=subprocess.DEVNULL).stdout
    devices = [line.split()[0] for line in out.splitlines()[1:]
               if line.strip() and line.split()[-1] == 'device']
    if serial() in devices:
        return serial()
    for device in devices:
        try:
            found = subprocess.run([adb_path(), '-s', device, 'shell', 'getprop', 'ro.serialno'],
                                   capture_output=True, text=True, timeout=10,
                                   stdin=subprocess.DEVNULL).stdout.strip()
        except subprocess.TimeoutExpired:
            continue
        if found == serial():
            return device
    raise DeviceError(f'Phone {serial()} not among adb devices {devices}; '
                      'connect it or set MOTO_TRANSPORT')


def adb(*args):
    """adb argv prefix bound to the phone."""
    return [adb_path(), '-s', transport(), *args]


def _run(argv, script, timeout, check):
    try:
        result = subprocess.run(argv, input=script, capture_output=True, text=True,
                                timeout=timeout, errors='replace')
    except subprocess.TimeoutExpired as error:
        raise DeviceError(f'Timed out after {timeout}s: {argv[-1]}') from error
    if check and result.returncode:
        raise DeviceError(f'Exit {result.returncode}: {result.stderr.strip() or result.stdout.strip()[-2000:]}')
    return result


# Each level runs a POSIX sh script read from stdin.
LEVELS = {
    'shell': 'sh',                                  # Android shell user
    'root': 'su -c sh',                             # Android root (Magisk)
    'container': f'su -c "{PLASMA} exec sh"',       # LXC root
    'user': f'su -c "{PLASMA} user-exec sh"',       # desktop user, session environment
}


def run(script, level='root', timeout=60, check=True):
    """Run a shell script at one of LEVELS; returns CompletedProcess."""
    return _run(adb('shell', LEVELS[level]), script, timeout, check)


def out(script, level='root', timeout=60):
    return run(script, level, timeout).stdout


def push(src, name=None, timeout=300):
    """adb push a local file to /data/local/tmp; returns the remote path for a following root script."""
    remote = '/data/local/tmp/' + (name or Path(src).name)
    subprocess.run(adb('push', str(src), remote), check=True, capture_output=True, timeout=timeout,
                   stdin=subprocess.DEVNULL)
    return remote


if __name__ == '__main__':
    print(f'adb={adb_path()} serial={serial()} transport={transport()}')
