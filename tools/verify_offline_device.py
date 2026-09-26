#!/usr/bin/env python3
"""Check offline first-boot Magisk integration and retained debloat on the phone."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time

from build_clean_product import APPS
import rungic_device

OUT = Path('/home/kevinzhow/moto-clean-W1WAA36/offline-v3')
# The phone may be rebooting, so use its USB serial instead of resolving a transport.
ADB = [rungic_device.adb_path(), '-s', rungic_device.config().get('MOTO_TRANSPORT', rungic_device.serial())]


def shell(cmd, timeout=30):
    r = subprocess.run(ADB + ['shell', cmd], text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=timeout)
    assert r.returncode == 0, (cmd, r.stdout)
    return r.stdout.strip()


def root(cmd):
    return shell('su -c ' + shlex.quote(cmd))


def main():
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        r = subprocess.run(ADB + ['get-state'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        if r.returncode == 0:
            break
        time.sleep(3)
    else:
        raise RuntimeError('ADB did not return')
    while time.monotonic() < deadline:
        if shell('getprop sys.boot_completed') == '1':
            break
        time.sleep(3)
    else:
        raise RuntimeError('Android boot did not complete')
    # Magisk's own boot-complete installer installs the preserved full APK.
    deadline = time.monotonic() + 90
    path = ''
    while time.monotonic() < deadline:
        query = subprocess.run(ADB + ['shell', 'pm path com.topjohnwu.magisk'],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, timeout=15)
        # PackageManager returns 1 while the first-boot install is still pending.
        path = query.stdout.strip() if query.returncode == 0 else ''
        if path.startswith('package:/data/app/'):
            break
        time.sleep(2)
    result = dict(boot_completed=shell('getprop sys.boot_completed'),
                  boot_id=shell('cat /proc/sys/kernel/random/boot_id'),
                  airplane_mode=shell('settings get global airplane_mode_on'),
                  wifi_status=shell('cmd wifi status'),
                  full_manager_path=path, root_id=root('id'), version=root('magisk -v'),
                  selinux=shell('getenforce'),
                  runtime_seed_log=root('cat /data/adb/moto-magisk-bootstrap.log'),
                  userdata_marker=shell('cat /data/local/tmp/moto-offline-v2-userdata-marker'),
                  storage=shell('df -h /data'))
    assert path.startswith('package:/data/app/'), result
    assert result['airplane_mode'] == '1', result
    assert 'uid=0(root)' in result['root_id'] and result['version'].startswith('31.0:'), result
    assert result['selinux'] == 'Enforcing'
    result['system_package_query'] = shell('pm list packages -s com.topjohnwu.magisk')
    result['user_package_query'] = shell('pm list packages -3 com.topjohnwu.magisk')
    assert not result['system_package_query'], 'Magisk still has the SYSTEM flag'
    assert result['user_package_query'] == 'package:com.topjohnwu.magisk'
    result['package_details'] = shell('dumpsys package com.topjohnwu.magisk')
    assert 'UPDATED_SYSTEM_APP' not in result['package_details'], 'Magisk still has UPDATED_SYSTEM_APP flag'
    assert result['userdata_marker'] == 'offline-v2-userdata-preserved'
    app_path = path.removeprefix('package:')
    apk_hashes = shell('sha256sum /product/etc/magisk/Magisk.apk ' + shlex.quote(app_path))
    want_apk = '2c8a488b9a5293e578e95ae4f07e3c57aba4feec4a52ca4dd852a2692d6dd4e8'
    assert all(line.split()[0] == want_apk for line in apk_hashes.splitlines())
    result['apk_hashes'] = apk_hashes
    result['env_check'] = root('export MAGISKBIN=/data/adb/magisk MAGISKTMP=/debug_ramdisk; '
                               '. /product/etc/magisk-prebuilt/app_functions.sh; '
                               'env_check 31.0 31000; r=$?; echo env_check_exit=$r; exit $r')
    assert result['env_check'] == 'env_check_exit=0'
    installed = set(shell('pm list packages').splitlines())
    result['removed_packages_absent'] = [package for _, package in APPS.values()
                                          if 'package:' + package not in installed]
    assert len(result['removed_packages_absent']) == len(APPS)
    expected_boot = json.loads((OUT / 'package/images.json').read_text())['init_boot.img']
    result['boot_partition_sha256'] = root('sha256sum /dev/block/by-name/init_boot_a').split()[0]
    assert result['boot_partition_sha256'] == expected_boot
    result['bootstrap_file_stats'] = root('stat -c "%n %Y %s" /data/adb/moto-magisk-*.log')
    result['status'] = 'PASS'
    (OUT / 'device-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'package_details'},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
