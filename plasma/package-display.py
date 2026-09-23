#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Run in Ubuntu after building KWin moto5 and the KScreen display module."""
from pathlib import Path
import hashlib
import re
import shutil
import subprocess

DEST = Path('/root/moto-display-packages')
DEST.mkdir(exist_ok=True)

def repack(original, replacements, version):
    name = subprocess.check_output(['dpkg-deb', '-f', str(original), 'Package'], text=True).strip()
    arch = subprocess.check_output(['dpkg-deb', '-f', str(original), 'Architecture'], text=True).strip()
    stage = DEST / (name + '-stage')
    if stage.exists():
        shutil.rmtree(stage)
    subprocess.run(['dpkg-deb', '-R', str(original), str(stage)], check=True)
    for source, destination in replacements:
        target = stage / destination.lstrip('/')
        target.unlink(missing_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        script = DEST / 'remove-rpath.cmake'
        script.write_text(f'file(RPATH_REMOVE FILE "{target}")\n')
        subprocess.run(['cmake', '-P', str(script)], check=True)
        subprocess.run(['strip', '--strip-unneeded', str(target)], check=True)
    files = [p for p in sorted(stage.rglob('*')) if p.is_file() and not p.is_symlink()
             and 'DEBIAN' not in p.relative_to(stage).parts]
    control = stage / 'DEBIAN/control'
    text = control.read_text().replace('+moto4', '+moto5')
    text = re.sub(r'^Version:.*$', 'Version: ' + version, text, flags=re.M)
    size = sum((p.stat().st_size + 1023) // 1024 for p in files)
    text = re.sub(r'^Installed-Size:.*$', 'Installed-Size: ' + str(size), text, flags=re.M)
    control.write_text(text)
    (stage / 'DEBIAN/md5sums').write_text(''.join(
        hashlib.md5(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(stage)) + '\n' for p in files))
    output = DEST / f'{name}_{version.split(":")[-1]}_{arch}.deb'
    subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(stage), str(output)], check=True)

for name in ['libkwin6', 'kwin-common', 'kwin-data', 'kwin-wayland', 'kwin-dev']:
    original, = Path('/root').glob(name + '_6.6.6-0ubuntu0.1+moto4_*.deb')
    replacements = []
    if name == 'libkwin6':
        replacements = [('/root/kwin-6.6.6/obj-aarch64-linux-gnu/bin/libkwin.so.6.6.6',
                         '/usr/lib/aarch64-linux-gnu/libkwin.so.6.6.6')]
    repack(original, replacements, '4:6.6.6-0ubuntu0.1+moto5')

original, = Path('/var/cache/apt/archives').glob('kscreen_*6.6.5-0ubuntu0.1_arm64.deb')
plugin, = Path('/root/kscreen-moto/build').rglob('kcm_kscreen.so')
repack(original, [(plugin,
                   '/usr/lib/aarch64-linux-gnu/qt6/plugins/plasma/kcms/systemsettings/kcm_kscreen.so')],
       '4:6.6.5-0ubuntu0.1+moto2')
