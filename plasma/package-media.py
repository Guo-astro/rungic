#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Repackage the exact installed Ubuntu packages with reviewed shared-library fixes.
Run inside the Ubuntu container after building; originals remain in APT cache.
"""
from pathlib import Path
import hashlib, shutil, subprocess
ROOT=Path('/root/rungic-media-packages')
ROOT.mkdir(exist_ok=True)

def package(name, original, version, replacements, dependencies=None, extra=None, assets=()):
    stage=ROOT/(name+'-stage')
    if stage.exists():shutil.rmtree(stage)
    subprocess.run(['dpkg-deb','-R',str(original),str(stage)],check=True)
    control=stage/'DEBIAN/control'
    text=control.read_text()
    import re
    text=re.sub(r'^Version:.*$', 'Version: '+version,text,flags=re.M)
    for old,new in (dependencies or {}).items():text=text.replace(old,new)
    if extra:text=re.sub(r'^Depends: (.*)$',lambda m:'Depends: '+m[1]+', '+extra,text,flags=re.M)
    control.write_text(text)
    for src,dest in replacements:
        target=stage/dest.lstrip('/')
        if target.exists() or target.is_symlink():target.unlink()
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,target)
        subprocess.run(['strip','--strip-unneeded',str(target)],check=True)
    for src,dest in assets:
        target=stage/dest.lstrip('/')
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,target)
    sums=[]
    for path in sorted(stage.rglob('*')):
        if path.is_file() and not path.is_symlink() and 'DEBIAN' not in path.relative_to(stage).parts:
            sums.append(hashlib.md5(path.read_bytes()).hexdigest()+'  '+str(path.relative_to(stage)))
    (stage/'DEBIAN/md5sums').write_text('\n'.join(sums)+'\n')
    output=ROOT/(name+'_'+version+'_arm64.deb')
    subprocess.run(['dpkg-deb','--root-owner-group','-Zxz','--build',str(stage),str(output)],check=True)
    return output
cache=Path('/var/cache/apt/archives')
camver='0.7.0-1ubuntu2+moto1'
qtver='6.10.2-2+moto1'
camlibs=Path('/root/libcamera-stage/usr/lib/aarch64-linux-gnu')
package('libcamera0.7',cache/'libcamera0.7_0.7.0-1ubuntu2_arm64.deb',camver,
 [(camlibs/n,'/usr/lib/aarch64-linux-gnu/'+n) for n in ['libcamera.so.0.7.0','libcamera-base.so.0.7.0']],
 extra='libgstreamer-plugins-base1.0-0 (>= 1.28), libgstreamer1.0-0 (>= 1.28), libjpeg-turbo8, gstreamer1.0-pipewire, gstreamer1.0-plugins-base',
 assets=[('/root/rungic-media-config/virtual.yaml','/usr/share/libcamera/pipeline/virtual/virtual.yaml')])
package('libcamera-dev',cache/'libcamera-dev_0.7.0-1ubuntu2_arm64.deb',camver,[],
 {'libcamera0.7 (= 0.7.0-1ubuntu2)':'libcamera0.7 (= '+camver+')'})
package('libqt6multimedia6',cache/'libqt6multimedia6_6.10.2-2_arm64.deb',qtver,
 [('/root/qtmultimedia-6.10.2/build/lib/aarch64-linux-gnu/libQt6Multimedia.so.6.10.2','/usr/lib/aarch64-linux-gnu/libQt6Multimedia.so.6.10.2')])
package('qt6-multimedia-dev',cache/'qt6-multimedia-dev_6.10.2-2_arm64.deb',qtver,[],
 {'libqt6multimedia6 (= 6.10.2-2)':'libqt6multimedia6 (= '+qtver+')'})
package('plasma-camera',cache/'plasma-camera_2.1.1-2build1_arm64.deb','2.1.1-2build1+moto1',
 [('/root/plasma-camera-moto/build/bin/plasma-camera','/usr/bin/plasma-camera')])
