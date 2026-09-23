#!/usr/bin/env python3
"""Verify every rebuilt file/metadata item, then prepare fastbootd images."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from erofs_inventory import Erofs


def main():
    base = Path('/home/kevinzhow/moto-clean-W1WAA36/offline-v3')
    tools = Path('/home/kevinzhow/android-kernel/prebuilts/kernel-build-tools/linux-x86/bin')
    expected = json.loads((base / 'expected-inodes.json').read_text())
    actual = {e['path']: e for e in Erofs(base / 'product-offline.img').walk()}
    assert set(actual) == {e['path'] for e in expected}
    assert 'app/Magisk' not in actual and 'priv-app/Magisk' not in actual
    assert 'etc/magisk/Magisk.apk' in actual
    for e in expected:
        keys = ['uid', 'gid', 'mode', 'mtime', 'mtime_ns', 'xattrs']
        if 'target' in e:
            keys.append('target')
        for key in keys:
            assert e[key] == actual[e['path']][key], (e['path'], key)
    verified = base / 'product-verified'
    assert not verified.exists()
    subprocess.run([str(tools / 'fsck.erofs'), '--extract=' + str(verified),
                    '--no-preserve', str(base / 'product-offline.img')], check=True)
    hashes = json.loads((base / 'expected-file-hashes.json').read_text())
    for path, want in hashes.items():
        with (verified / path).open('rb') as f:
            assert hashlib.file_digest(f, 'sha256').hexdigest() == want, path
    print(f'PASS: {len(hashes)} file hashes and {len(expected)} inode metadata entries.', flush=True)
    kit = base / 'package'
    kit.mkdir(exist_ok=True)
    padded = base / 'product-offline-padded.img'
    subprocess.run(['cp', '--reflink=auto', '--sparse=always', str(base / 'product-offline.img'), str(padded)], check=True)
    with padded.open('r+b') as f:
        f.truncate(7613104128)
    subprocess.run([str(tools / 'img2simg'), str(padded), str(kit / 'product.img')], check=True)
    for src, name in [(base / 'init_boot-offline.img', 'init_boot.img'),
                      (base.parent / 'package/vbmeta.img', 'vbmeta.img'),
                      (base.parent / 'package/vbmeta_system.img', 'vbmeta_system.img'),
                      (Path(__file__).parent / 'install_offline_v2.py', 'install.py')]:
        shutil.copyfile(src, kit / name)
    manifest = {}
    for name in ['product.img', 'init_boot.img', 'vbmeta.img', 'vbmeta_system.img']:
        with (kit / name).open('rb') as f:
            manifest[name] = hashlib.file_digest(f, 'sha256').hexdigest()
    (kit / 'images.json').write_text(json.dumps(manifest, indent=2) + '\n')
    result = dict(status='PASS', regular_files=len(hashes), metadata_entries=len(expected), images=manifest)
    (base / 'product-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
