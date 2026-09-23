#!/usr/bin/env python3
"""Flash the offline Magisk/debloated product update on matching stock Android 16."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import time

FINGERPRINT = 'motorola/mumba_cn/mumba:16/W1WAA36.48-23-10/1c41a-29619:user/release-keys'
PRODUCT_SIZE = 7613104128


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True)
    p.add_argument('--flash', action='store_true', required=True)
    p.add_argument('--factory-reset', action='store_true', help='Explicitly erase ALL user data after flashing')
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    assert shutil.which('adb') and shutil.which('fastboot'), 'Android platform-tools required in PATH'
    log = (root / ('install-' + time.strftime('%Y%m%d-%H%M%S') + '.log')).open('w', buffering=1)

    def run(tool, *a, timeout=240):
        cmd = [tool, '-s', args.serial, *map(str, a)]
        line = '\n' + time.strftime('%Y-%m-%dT%H:%M:%S%z') + ' $ ' + ' '.join(cmd)
        print(line, flush=True)
        log.write(line + '\n')
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        print(r.stdout, end='', flush=True)
        log.write(r.stdout)
        assert r.returncode == 0, 'Command failed: stopping remaining writes/reset steps'
        return r.stdout

    manifest = json.loads((root / 'images.json').read_text())
    for name, expected in manifest.items():
        with (root / name).open('rb') as f:
            actual = hashlib.file_digest(f, 'sha256').hexdigest()
        assert actual == expected, ('image hash mismatch', name)
    with (root / 'product.img').open('rb') as f:
        hdr = struct.unpack('<IHHHHIIII', f.read(28))
    assert hdr[0] == 0xed26ff3a and hdr[5] * hdr[6] == PRODUCT_SIZE
    assert run('adb', 'shell', 'getprop ro.build.fingerprint').strip() == FINGERPRINT
    assert run('adb', 'shell', 'getprop ro.boot.slot_suffix').strip() == '_a'
    assert run('adb', 'shell', 'getprop ro.boot.flash.locked').strip() == '0'
    assert run('adb', 'shell', 'getprop ro.product.device').strip() == 'mumba'
    battery = run('adb', 'shell', 'dumpsys battery')
    levels = [int(line.split(':')[1]) for line in battery.splitlines() if line.strip().startswith('level:')]
    assert levels and levels[0] >= 30, 'Charge battery to at least 30 percent'
    run('adb', 'reboot', 'bootloader')
    assert 'flashing_unlocked' in run('fastboot', 'getvar', 'securestate')
    assert 'current-slot: a' in run('fastboot', 'getvar', 'current-slot')
    run('fastboot', 'oem', 'fb_mode_clear')
    run('fastboot', 'flash', 'vbmeta_a', root / 'vbmeta.img')
    run('fastboot', 'flash', 'vbmeta_system_a', root / 'vbmeta_system.img')
    run('fastboot', 'reboot', 'fastboot')
    assert 'is-userspace: yes' in run('fastboot', 'getvar', 'is-userspace')
    assert 'unlocked: yes' in run('fastboot', 'getvar', 'unlocked')
    assert 'current-slot: a' in run('fastboot', 'getvar', 'current-slot')
    assert '0x1c5c6c000' in run('fastboot', 'getvar', 'partition-size:product_a').lower()
    run('fastboot', '-S', '256M', 'flash', 'product_a', root / 'product.img', timeout=600)
    assert '0x1c5c6c000' in run('fastboot', 'getvar', 'partition-size:product_a').lower()
    run('fastboot', 'reboot', 'bootloader')
    assert 'is-userspace: no' in run('fastboot', 'getvar', 'is-userspace')
    assert 'current-slot: a' in run('fastboot', 'getvar', 'current-slot')
    run('fastboot', 'flash', 'init_boot_a', root / 'init_boot.img')
    if args.factory_reset:
        run('fastboot', 'erase', 'userdata')
        run('fastboot', 'erase', 'metadata')
    run('fastboot', 'oem', 'fb_mode_clear')
    run('fastboot', 'reboot')
    result = dict(serial=args.serial, image_hashes=manifest, factory_reset=args.factory_reset,
                  partitions_written=['vbmeta_a', 'vbmeta_system_a', 'product_a', 'init_boot_a'],
                  reboot_sent=True, boot_and_root_verification='pending')
    (root / 'last-install.json').write_text(json.dumps(result, indent=2) + '\n')
    print('Flash complete. Verify Android boot and Magisk before considering installation validated.', flush=True)


if __name__ == '__main__':
    main()
