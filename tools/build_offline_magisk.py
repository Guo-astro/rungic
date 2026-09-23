#!/usr/bin/env python3
"""Add the official full Magisk APK and first-boot runtime seed to clean product."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import zipfile

from erofs_inventory import Erofs

BASE = Path('/home/kevinzhow/moto-clean-W1WAA36')
OUT = BASE / 'offline-v3'
ROOT = OUT / 'product-root'
APK = BASE / 'package/Magisk-v31.0.apk'
TOOLS = Path('/home/kevinzhow/android-kernel/prebuilts/kernel-build-tools/linux-x86/bin')


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    assert digest(APK) == '2c8a488b9a5293e578e95ae4f07e3c57aba4feec4a52ca4dd852a2692d6dd4e8'
    entries = list(Erofs(BASE / 'work/product-clean.img').walk())
    paths = {e['path'] for e in entries}
    assert {str(p.relative_to(ROOT)) for p in ROOT.rglob('*')} | {''} == paths
    # Keep the APK outside PackageManager's system-app scan paths. Magisk's
    # own boot-complete installer will install it as an ordinary user app.
    (ROOT / 'etc/magisk').mkdir()
    shutil.copyfile(APK, ROOT / 'etc/magisk/Magisk.apk')
    runtime = ROOT / 'etc/magisk-prebuilt'
    runtime.mkdir()
    with zipfile.ZipFile(APK) as z:
        for name in z.namelist():
            if name.startswith('lib/arm64-v8a/lib') and name.endswith('.so'):
                dest = runtime / Path(name).name[3:-3]
            elif name.startswith('assets/') and not name.endswith('/') and not name.startswith('assets/dexopt/'):
                dest = runtime / name[len('assets/'):]
            else:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(name))
    assert (runtime / 'busybox').stat().st_size > 1000000
    # No 32-bit userspace exists on this device (ro.product.cpu.abilist32 is empty).
    additions = []
    for p in sorted(ROOT.rglob('*')):
        rel = str(p.relative_to(ROOT))
        if rel in paths:
            continue
        mode = (stat.S_IFDIR | 0o755) if p.is_dir() else (stat.S_IFREG | (0o755 if p.is_relative_to(runtime) else 0o644))
        additions.append(dict(path=rel, uid=0, gid=0, mode=mode, mtime=1230768000,
                              mtime_ns=0, xattrs={'security.selinux': base64.b64encode(b'u:object_r:system_file:s0').decode()}))
    expected = entries + additions
    configs, contexts = [], []
    for e in expected:
        path = 'product' + ('/' + e['path'] if e['path'] else '')
        attrs = f"{e['uid']} {e['gid']} {e['mode'] & 0o7777:04o} capabilities=0"
        configs += [f'{path} {attrs}', f"{e['path'] or '/'} {attrs}"]
        label = base64.b64decode(e['xattrs']['security.selinux']).decode().rstrip('\0')
        contexts.append(f'/{re.escape(path)} {label}')
    (OUT / 'fs-config.txt').write_text('\n'.join(configs) + '\n')
    (OUT / 'file-contexts.txt').write_text('\n'.join(contexts) + '\n')
    (OUT / 'expected-inodes.json').write_text(json.dumps(expected, indent=2) + '\n')
    hashes = {e['path']: digest(ROOT / e['path']) for e in expected if stat.S_ISREG(e['mode'])}
    (OUT / 'expected-file-hashes.json').write_text(json.dumps(hashes, indent=2) + '\n')
    for e in sorted(expected, key=lambda e: e['path'].count('/'), reverse=True):
        t = e['mtime'] * 1000000000 + e['mtime_ns']
        os.utime(ROOT / e['path'], ns=(t, t), follow_symlinks=False)
    output = OUT / 'product-offline.img'
    assert not output.exists()
    subprocess.run([str(TOOLS / 'mkfs.erofs'), '--quiet', '-z', 'lz4hc,9', '-C', '4096',
                    '--preserve-mtime', '--mount-point=/product',
                    '--fs-config-file=' + str(OUT / 'fs-config.txt'),
                    '--file-contexts=' + str(OUT / 'file-contexts.txt'), str(output), str(ROOT)], check=True)
    actual = {e['path']: e for e in Erofs(output).walk()}
    assert set(actual) == {e['path'] for e in expected}
    for e in expected:
        for k in ['uid', 'gid', 'mode', 'mtime', 'mtime_ns', 'xattrs'] + (['target'] if stat.S_ISLNK(e['mode']) else []):
            assert actual[e['path']][k] == e[k], (e['path'], k, actual[e['path']][k], e[k])
    print(json.dumps(dict(image_bytes=output.stat().st_size, original_entries=len(entries),
                         added_entries=len(additions), metadata_verified=True), indent=2), flush=True)


if __name__ == '__main__':
    main()
