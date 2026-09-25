#!/usr/bin/python3
"""Package the entire KGSL Mesa runtime coherently, retaining Ubuntu GLVND."""
from pathlib import Path
import shutil
import subprocess
import os

root = Path(__file__).resolve().parent.parent
stage = Path(os.environ.get('MOTO_MESA_STAGE', root / '.work/stage/mesa'))
output = Path(os.environ.get('MOTO_MESA_PACKAGES', root / '.work/packages/mesa'))
version = os.environ.get('MOTO_MESA_VERSION', '26.3.0~devel20260824+moto1')
# The Mesa source the stage was built from (its docs/license.rst) and its commit, for the package docs.
source = Path(os.environ.get('MOTO_MESA_SOURCE', root / 'vendor/mesa'))
commit = os.environ.get('MOTO_MESA_COMMIT', 'unknown')
packages = ('mesa-libgallium', 'libegl-mesa0', 'libglx-mesa0', 'libgbm1',
            'libgbm-dev', 'libgl1-mesa-dri', 'mesa-vulkan-drivers')
external = ('libc6 (>= 2.43), libdrm2 (>= 2.4.125), libexpat1, libelf1t64, '
            'libgcc-s1, libstdc++6, libzstd1, zlib1g, libvulkan1, '
            'libwayland-client0, libwayland-server0, libx11-6, libx11-xcb1, '
            'libxcb1, libxcb-dri3-0, libxcb-present0, '
            'libxcb-randr0, libxcb-shm0, libxcb-sync1, libxcb-xfixes0, '
            'libxcb-glx0, libxext6, libxfixes3, libxshmfence1, libxxf86vm1, '
            'libxcb-keysyms1, libdisplay-info3, libudev1')
same = lambda name: f'{name} (= {version})'
deps = {
    'mesa-libgallium': external,
    'libegl-mesa0': same('mesa-libgallium') + ', ' + same('libgbm1'),
    'libglx-mesa0': same('mesa-libgallium') + ', ' + same('libgl1-mesa-dri'),
    'libgbm1': same('mesa-libgallium'),
    'libgbm-dev': same('libgbm1'),
    'libgl1-mesa-dri': same('mesa-libgallium') + ', ' + same('libgbm1'),
    'mesa-vulkan-drivers': external,
}


def owner(path):
    name = path.name
    if name.startswith('libgallium-') or '/gbm/' in str(path):
        return 'mesa-libgallium'
    if name == 'gbm.h' or name == 'gbm.pc' or name == 'libgbm.so':
        return 'libgbm-dev'
    if name.startswith('libgbm.so.'):
        return 'libgbm1'
    if name.startswith('libEGL_mesa.so') or name == '50_mesa.json':
        return 'libegl-mesa0'
    if name.startswith('libGLX_mesa.so'):
        return 'libglx-mesa0'
    if '/dri/' in str(path):
        return 'libgl1-mesa-dri'
    if name.startswith('libvulkan_') or '/vulkan/icd.d/' in str(path):
        return 'mesa-vulkan-drivers'
    return None


output.mkdir(parents=True, exist_ok=True)
counts = {name: 0 for name in packages}
for name in packages:
    directory = output / name
    if directory.exists():
        shutil.rmtree(directory)
    (directory / 'DEBIAN').mkdir(parents=True)
    control = (f'Package: {name}\nVersion: {version}\nArchitecture: arm64\n'
               'Section: libs\nPriority: optional\nMulti-Arch: same\n'
               'Maintainer: Moto Linux integration <local@localhost>\n'
               f'Depends: {deps[name]}\n'
               'Description: Coherent Mesa KGSL build for the Moto Plasma container\n'
               ' Built from the pinned Mesa for Android container source archive.\n')
    (directory / 'DEBIAN/control').write_text(control)
    sonames = {'libgbm1': 'libgbm 1', 'libegl-mesa0': 'libEGL_mesa 0',
               'libglx-mesa0': 'libGLX_mesa 0'}
    if name in sonames:
        (directory / 'DEBIAN/shlibs').write_text(
            f'{sonames[name]} {name} (>= {version})\n')
    if name != 'libgbm-dev':
        (directory / 'DEBIAN/triggers').write_text('activate-noawait ldconfig\n')
    if name == 'mesa-libgallium':
        # docs/61: libgallium was installed over +moto1's with a local diversion
        # (build_on_device.py divert); this package carries that build.
        preinst = directory / 'DEBIAN/preinst'
        preinst.write_text('''#!/bin/sh
set -e
if [ "$1" = install ] || [ "$1" = upgrade ]; then
    for f in /usr/lib/aarch64-linux-gnu/libgallium-*.so; do
        if dpkg-divert --list "$f" | grep -q '^local diversion'; then
            rm -f "$f"
            dpkg-divert --local --rename --remove "$f" >/dev/null
        fi
    done
fi
''')
        preinst.chmod(0o755)

ignored = []
for path in sorted(stage.rglob('*')):
    if path.is_dir():
        continue
    relative = path.relative_to(stage)
    package = owner(relative)
    if package is None:
        ignored.append(str(relative))
        continue
    target = output / package / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        target.symlink_to(path.readlink())
    else:
        shutil.copy2(path, target)
        if path.read_bytes()[:4] == b'\x7fELF':
            subprocess.run(['strip', '--strip-unneeded', str(target)], check=True)
    counts[package] += 1

for name in packages:
    if counts[name] == 0:
        raise SystemExit('Empty runtime package: ' + name)
    doc = output / name / 'usr/share/doc' / name
    doc.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'docs/license.rst', doc / 'copyright')
    (doc / 'moto-build.txt').write_text(
        f'Built from vendor/mesa of range-dev {commit} (KGSL branch 98f3d6229d61, vendor/manifest.json),\n'
        'natively for Ubuntu glibc. GLVND dispatchers remain distribution packages.\n')
    subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(output / name),
                    str(output / f'{name}_{version}_arm64.deb')], check=True)
(output / 'excluded-development-files.txt').write_text('\n'.join(ignored) + '\n')
print(counts)
