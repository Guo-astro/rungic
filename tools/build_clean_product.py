#!/usr/bin/env python3
"""Build the conservative W1WAA36 product image from a verified extraction.

All source files stay untouched. Only explicit preload directories and their
dedicated installer files are excluded. Original inode ownership, modes,
timestamps, symlinks and SELinux labels are restored during the build.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from apk_manifest_info import manifest_info

APPS = {
    'Amap': ('高德地图', 'com.autonavi.minimap'),
    'BaiduSearch': ('百度', 'com.baidu.searchbox'),
    'CT_XCC': ('星小辰', 'com.teleagi.xxc'),
    'Douyin': ('抖音', 'com.ss.android.ugc.aweme'),
    'FanqieNovel': ('番茄小说', 'com.dragon.read'),
    'IQiyi': ('爱奇艺', 'com.qiyi.video'),
    'KuaishouVideo': ('快手', 'com.smile.gifmaker'),
    'Meituxiuxiu': ('美图秀秀', 'com.mt.mtxx.mtxx'),
    'NetEaseCloudMusic': ('网易云音乐', 'com.netease.cloudmusic'),
    'NewsArticle': ('今日头条', 'com.ss.android.article.news'),
    'QQMusic': ('QQ 音乐', 'com.tencent.qqmusic'),
    'RedBook': ('小红书', 'com.xingin.xhs'),
    'Weibo': ('微博', 'com.sina.weibo'),
    'Youku': ('优酷', 'com.youku.phone'),
    'iBiliPlayer': ('哔哩哔哩', 'tv.danmaku.bili'),
}
EXTRA = ['etc/packagemanager/preinstall-CT_XCC.xml',
         'etc/preinstall/lenovo_aweme_183_pre_install.config']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work', type=Path)
    parser.add_argument('--tools', type=Path, default=Path(
        '/home/kevinzhow/android-kernel/prebuilts/kernel-build-tools/linux-x86/bin'))
    args = parser.parse_args()
    work = args.work.resolve()
    root = work / 'product-root'
    entries = json.loads((work / 'product-inodes.json').read_text())
    excludes = ['preinstall/' + name for name in APPS] + EXTRA
    paths = {e['path'] for e in entries}
    assert all(p in paths for p in excludes), 'expected preload path missing'
    actual = {str(p.relative_to(root)) for p in root.rglob('*')} | {''}
    assert actual == paths, 'extraction differs from original image inventory'
    removed = []
    for app, (label, package) in APPS.items():
        apk = root / 'preinstall' / app / (app + '.apk')
        info = manifest_info(apk)
        assert info['manifest']['package'] == package, (app, info)
        members = [e for e in entries if e['path'] == 'preinstall/' + app or
                   e['path'].startswith('preinstall/' + app + '/')]
        removed.append(dict(app=label, package=package, directory='preinstall/' + app,
                            bytes=sum(e['size'] for e in members if stat.S_ISREG(e['mode']))))

    kept = [e for e in entries if not any(e['path'] == p or e['path'].startswith(p + '/')
                                         for p in excludes)]
    configs, contexts = [], []
    for e in kept:
        assert set(e['xattrs']) == {'security.selinux'}, 'unexpected xattrs require preservation'
        label = base64.b64decode(e['xattrs']['security.selinux']).decode().rstrip('\0')
        path = 'product' + ('/' + e['path'] if e['path'] else '')
        assert not any(c.isspace() for c in path), 'unsupported path whitespace'
        attrs = f"{e['uid']} {e['gid']} {e['mode'] & 0o7777:04o} capabilities=0"
        configs.append(f"{path} {attrs}")
        # Android erofs-utils also looks up the image root as an empty path;
        # canned_fs_config represents it with '/'. Support relative lookups.
        configs.append(f"{e['path'] or '/'} {attrs}")
        contexts.append(f'/{re.escape(path)} {label}')
    (work / 'product-fs-config.txt').write_text('\n'.join(configs) + '\n')
    (work / 'product-file-contexts.txt').write_text('\n'.join(contexts) + '\n')
    (work / 'removed-apps.json').write_text(json.dumps(removed, ensure_ascii=False, indent=2) + '\n')
    (work / 'product-excludes.json').write_text(json.dumps(excludes, indent=2) + '\n')
    # fsck.erofs cannot always restore the timestamp of an absolute symlink.
    for e in sorted(kept, key=lambda e: e['path'].count('/'), reverse=True):
        p = root / e['path']
        t = e['mtime'] * 1_000_000_000 + e['mtime_ns']
        os.utime(p, ns=(t, t), follow_symlinks=False)
    output = work / 'product-clean.img'
    assert not output.exists(), 'refusing to overwrite an existing build'
    command = [str(args.tools / 'mkfs.erofs'), '--quiet', '-z', 'lz4hc,9', '-C', '4096',
               '--preserve-mtime', '--mount-point=/product',
               '--fs-config-file=' + str(work / 'product-fs-config.txt'),
               '--file-contexts=' + str(work / 'product-file-contexts.txt')]
    command += ['--exclude-path=' + p for p in excludes]
    command += [str(output), str(root)]
    (work / 'product-build-command.json').write_text(json.dumps(command, indent=2) + '\n')
    subprocess.run(command, check=True)
    print(json.dumps(dict(removed_apps=len(removed), kept_entries=len(kept),
                          removed_file_bytes=sum(a['bytes'] for a in removed),
                          image_bytes=output.stat().st_size), indent=2))


if __name__ == '__main__':
    main()
