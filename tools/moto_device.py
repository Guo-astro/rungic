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


# Files between this computer and the container (docs/61 §7). The container's rootfs may be an image
# mounted only in the container's namespace, so nothing is read or written under PLASMA_ROOTFS from
# Android: files pass through state/host/transfer, bind-mounted at /var/lib/moto-host/transfer.
HOST_TRANSFER = '/data/adb/moto-lxc/runtime/var/lib/lxc/plasma/state/host/transfer'
CONTAINER_TRANSFER = '/var/lib/moto-host/transfer'


_transfer_host = None


def _host_transfer():
    """Android path of the transfer directory: state/host when it is bind-mounted (image rootfs, or after
    the release that adds the mount), else the same directory inside a directory rootfs."""
    global _transfer_host
    if _transfer_host is None:
        mounted = run('mountpoint -q /var/lib/moto-host', 'container', check=False).returncode == 0
        _transfer_host = HOST_TRANSFER if mounted else PLASMA_ROOTFS + CONTAINER_TRANSFER
    return _transfer_host


def _transfer_name(hint):
    import secrets
    return f'{secrets.token_hex(6)}-{Path(hint).name}'


def to_container(src, dest=None, mode=None, timeout=600):
    """Copy a local file into the container: to `dest` (installed root-owned, `mode` if given), or,
    without dest, only into the transfer directory; returns the container path."""
    name = _transfer_name(src)
    remote = push(src, name, timeout)
    host = _host_transfer()
    run(f'mkdir -p {host} && cp {remote} {host}/{name} && chmod 644 {host}/{name}; rm -f {remote}', 'root', timeout)
    staged = f'{CONTAINER_TRANSFER}/{name}'
    if dest is None:
        return staged
    install = f'install -o 0 -g 0 -m {mode} ' if mode else 'install -o 0 -g 0 '
    run(f'mkdir -p "$(dirname {dest})" && {install}{staged} {dest}; rm -f {staged}', 'container', timeout)
    return dest


def from_container(path, target, timeout=1800):
    """Copy a file from the container to a local path."""
    name = _transfer_name(path)
    run(f'mkdir -p {CONTAINER_TRANSFER} && cp {path} {CONTAINER_TRANSFER}/{name} && '
        f'chmod 644 {CONTAINER_TRANSFER}/{name}', 'container', timeout)
    stage = f'/data/local/tmp/{name}'
    try:
        run(f'cp {_host_transfer()}/{name} {stage} && chmod 644 {stage}', 'root', timeout)
        subprocess.run(adb('pull', stage, str(target)), check=True, capture_output=True, timeout=timeout,
                       stdin=subprocess.DEVNULL)
    finally:
        run(f'rm -f {stage} {_host_transfer()}/{name}', 'root', check=False)


def extract_in_container(archive, directory, timeout=1800):
    """Unpack a local tar into a container directory (root-owned files)."""
    staged = to_container(archive, timeout=timeout)
    run(f'mkdir -p {directory} && tar -xf {staged} -C {directory} --no-same-owner; rc=$?; rm -f {staged}; exit $rc',
        'container', timeout)


if __name__ == '__main__':
    print(f'adb={adb_path()} serial={serial()} transport={transport()}')
