#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Phase C1 of the Rungic rename (docs/70): the Android side of the phone from moto to Rungic names.

  rungic_cutover.py status            the layout, APKs, directories and grants as they are now
  rungic_cutover.py up [--apk APK]    APK dev.moto.plasma -> com.rungic.plasma, /data/adb/moto-* ->
                                      /data/adb/rungic-* (the rootfs image to /data/adb/rungic-lxc/images),
                                      new launcher, enter programs, cast tool and boot scripts
  rungic_cutover.py down              back to the moto layout and APK (files kept by `up`)
  rungic_cutover.py docker-up         /data/adb/moto-docker -> /data/adb/rungic-docker, SELinux types
                                      moto_docker* -> rungic_docker* (runtime tree and data image
                                      relabelled), the workloads' names (compose project, volume, tag)
  rungic_cutover.py docker-down       the reverse

The container release is not touched: the new launcher also mounts the state under the old names
(/var/lib/moto-*) and the APK links moto-gpu-alloc to its socket, so releases from before the rename
run on the new layout until phase D. Directory renames stay on one f2fs (O(1)). Every step is
recorded in .work/cutover/<time>-<action>/cutover.json; files that `up` replaces or retires are kept on
the phone in /data/adb/rungic-cutover/ (as `down` needs them) until phase D.

Needs: tools/build_enter.sh plasma and lxc, shared/android/rungic-cast/build.sh, plasma/build-apk.sh.
Magisk's su grant for the new APK is written with `magisk --sqlite "INSERT OR REPLACE ..."`, which returns
no rows (docs/39: never a query that can return SQL NULL on Magisk 31.0).
"""
import argparse
import datetime
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

import rungic_device
from rungic_device import WORKSPACE, adb, out, push, run

NEW_APK, OLD_APK = rungic_device.APK, rungic_device.FORMER_APK
KEEP = '/data/adb/rungic-cutover'           # files `up` retired or replaced, for `down`
TERMUX_LXC = '/data/data/com.termux/files/usr/bin/lxc'
LXC = '/runtime/var/lib/lxc'
# The directory renames, and inside them the image directory (toybox losetup: paths under 64 bytes,
# plasma/rootfs-image) and the state directories the container binds.
MOVES = [
    ('/data/adb/moto-plasma', '/data/adb/rungic-plasma'),
    ('/data/adb/moto-lxc', '/data/adb/rungic-lxc'),
    ('/data/adb/moto-wfd', '/data/adb/rungic-wfd'),
    (f'/data/adb/rungic-lxc{LXC}/plasma/images', '/data/adb/rungic-lxc/images'),
    (f'/data/adb/rungic-lxc{LXC}/plasma/state/moto-cores', f'/data/adb/rungic-lxc{LXC}/plasma/state/rungic-cores'),
    (f'/data/adb/rungic-lxc{LXC}/plasma/state/moto-apt', f'/data/adb/rungic-lxc{LXC}/plasma/state/rungic-apt'),
]
# Files under their old names (paths after MOVES); `up` keeps them in KEEP, `down` puts them back.
RETIRED = [
    '/data/adb/rungic-plasma/moto-plasma', '/data/adb/rungic-plasma/moto-plasma-enter',
    '/data/adb/rungic-lxc/moto-lxc', '/data/adb/rungic-lxc/moto-lxc-enter',
    '/data/adb/rungic-wfd/moto-cast', '/data/adb/rungic-wfd/moto-cast-watch', '/data/adb/rungic-wfd/moto-cast.jar',
    '/data/adb/service.d/moto-cast-watch.sh', '/data/adb/service.d/moto-wfd-sepolicy.sh',
]
BUILD = WORKSPACE / '.work/build'
# (source, path on the phone, mode); a file that exists is copied to KEEP first.
INSTALL = [
    ('plasma/rungic-plasma', '/data/adb/rungic-plasma/rungic-plasma', '755'),
    (BUILD / 'android/rungic-plasma-enter', '/data/adb/rungic-plasma/rungic-plasma-enter', '755'),
    ('plasma/android-audio', '/data/adb/rungic-plasma/android-audio', '755'),
    ('plasma/android-audio.pa', '/data/adb/rungic-plasma/android-audio.pa', '644'),
    ('plasma/rootfs-image', '/data/adb/rungic-plasma/rootfs-image', '755'),
    ('plasma/rootfs.sepolicy.rule', '/data/adb/rungic-plasma/rootfs.sepolicy.rule', '644'),
    ('plasma/rootfs-mount-hook', '/data/adb/rungic-plasma/rootfs-mount-hook', '755'),
    ('plasma/plasma.config', f'/data/adb/rungic-lxc{LXC}/plasma/config', '644'),
    ('lxc/rungic-lxc', '/data/adb/rungic-lxc/rungic-lxc', '755'),
    (BUILD / 'android/rungic-lxc-enter', '/data/adb/rungic-lxc/rungic-lxc-enter', '700'),
    ('lxc/alpine.config', f'/data/adb/rungic-lxc{LXC}/alpine/config', '664'),
    ('shared/android/rungic-cast/rungic-cast', '/data/adb/rungic-wfd/rungic-cast', '755'),
    ('shared/android/rungic-cast/rungic-cast-watch', '/data/adb/rungic-wfd/rungic-cast-watch', '755'),
    (BUILD / 'rungic-cast/rungic-cast.jar', '/data/adb/rungic-wfd/rungic-cast.jar', '644'),
    ('shared/android/wfd.sepolicy.rule', '/data/adb/rungic-wfd/wfd.sepolicy.rule', '644'),
    ('shared/android/rungic-cast-watch.sh', '/data/adb/service.d/rungic-cast-watch.sh', '755'),
    ('shared/android/rungic-wfd-sepolicy.sh', '/data/adb/service.d/rungic-wfd-sepolicy.sh', '755'),
]
DEFAULT_APK = WORKSPACE / '.work/refs/plasma-mobile-20260923/Rungic-2.0.apk'


def root(script, timeout=120, check=True):
    return run(script, 'root', timeout, check)


def layout():
    return out('[ -d /data/adb/rungic-plasma ] && echo rungic || echo moto').strip()


def packages():
    text = out('pm list packages -U', 'shell')
    found = {}
    for line in text.splitlines():
        parts = dict(p.split(':', 1) for p in line.split() if ':' in p)
        if parts.get('package') in (NEW_APK, OLD_APK):
            found[parts['package']] = int(parts.get('uid', 0))
    enabled = out('pm list packages -e', 'shell').split()
    return {name: {'uid': uid, 'enabled': f'package:{name}' in enabled} for name, uid in found.items()}


def status():
    state = {'layout': layout(), 'apks': packages()}
    state['adb'] = out('ls -la /data/adb /data/adb/service.d').splitlines()
    state['rootfs'] = root(f'{rungic_device.PLASMA} rootfs status', check=False).stdout.strip()
    state['container'] = root(f'{rungic_device.PLASMA} status | grep -m1 State', check=False).stdout.strip()
    return state


class Record:
    def __init__(self, action):
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        self.dir = WORKSPACE / f'.work/cutover/{stamp}-{action}'
        self.dir.mkdir(parents=True)
        self.log = {'action': action, 'steps': []}

    def step(self, name, **data):
        self.log['steps'].append({'step': name, 'time': datetime.datetime.now().isoformat(timespec='seconds'), **data})
        (self.dir / 'cutover.json').write_text(json.dumps(self.log, indent=1, ensure_ascii=False) + '\n')
        print(f'[{name}] ' + ', '.join(f'{k}={v}' for k, v in data.items() if not isinstance(v, (dict, list))),
              flush=True)

    def save(self, name, text):
        (self.dir / name).write_text(text)


def stop_all(launcher, lxc, cast_watch, apk, dm):
    """The desktop APK, the Plasma container with its image and audio, alpine and the cast watcher."""
    root(f'am force-stop {apk}', check=False)
    result = root(f'{launcher} stop', timeout=240, check=False)
    text = result.stdout + result.stderr
    if result.returncode:
        raise SystemExit(f'the container did not stop: {text}')
    root(f'[ "$({lxc} status | grep -m1 State | tr -s " " | cut -d" " -f2)" != RUNNING ] || {lxc} stop', timeout=60,
         check=False)
    # The watchers: the cast reconnect loop and the audio monitor (it ends once its flag is gone).
    # The cast watcher waits on a logcat pipeline and ends only once its children are gone.
    root(f'for p in $(pgrep -f {cast_watch}); do pkill -P $p; kill $p; done; pkill -f "android-audio watch"; true',
         check=False)
    left = root(f'dmctl getpath {dm} 2>/dev/null; pidof lxc-start; losetup -a | grep rootfs.img; true',
                check=False).stdout.strip()
    if left:
        raise SystemExit(f'still in use after stopping: {left}')
    return text.strip()


def keep(paths, recorder):
    """Copy (existing) paths to KEEP, keeping modes, owners and labels."""
    script = [f'mkdir -p {KEEP}']
    for path in paths:
        target = KEEP + path
        script.append(f'if [ -e {path} ] && [ ! -e {target} ]; then mkdir -p {shlex.quote(str(Path(target).parent))} '
                      f'&& cp -a {path} {target}; fi')
    root('\n'.join(script))
    recorder.step('keep', paths=paths)


def install_files(recorder):
    missing = [str(src) for src, _, _ in INSTALL if not (WORKSPACE / src).exists()]
    if missing:
        raise SystemExit(f'build these first: {missing}')
    keep([path for _, path, _ in INSTALL], recorder)
    for src, path, mode in INSTALL:
        remote = push(WORKSPACE / src, 'rungic-cutover-file')
        root(f'install -m {mode} {remote} {path}.new && mv {path}.new {path} && rm -f {remote}')
    # The Termux shortcut `lxc`: its own owner and label stay (the file is rewritten in place).
    remote = push(WORKSPACE / 'lxc/termux-lxc', 'rungic-cutover-file')
    root(f'[ ! -f {TERMUX_LXC} ] || cat {remote} > {TERMUX_LXC}; rm -f {remote}')
    recorder.step('install', files=[path for _, path, _ in INSTALL] + [TERMUX_LXC])


def grant(recorder, prefs_from):
    """Settings, permissions and the su grant of the old APK for the new one."""
    uid = packages()[NEW_APK]['uid']
    data = f'/data/data/{NEW_APK}'
    # The new app's files carry its data directory's label (its own MCS categories).
    root(f'''set -e
label=$(ls -dZ {data} | cut -d" " -f1)
mkdir -p {data}/shared_prefs
cp {prefs_from} {data}/shared_prefs/MainActivity.xml
chown {uid}:{uid} {data}/shared_prefs {data}/shared_prefs/MainActivity.xml
chmod 771 {data}/shared_prefs; chmod 660 {data}/shared_prefs/MainActivity.xml
chcon "$label" {data}/shared_prefs {data}/shared_prefs/MainActivity.xml''')
    for permission in ('android.permission.CAMERA', 'android.permission.RECORD_AUDIO'):
        root(f'pm grant {NEW_APK} {permission}')
    root(f'appops set {NEW_APK} SYSTEM_ALERT_WINDOW allow')
    root(f'magisk --sqlite "INSERT OR REPLACE INTO policies (uid,policy,until,logging,notification) '
         f'VALUES({uid},2,0,1,1)"')
    recorder.step('grant', uid=uid, prefs=bool(prefs_from))


def wait_ready(launcher, apk, recorder, timeout=180):
    root(f'am start --user 0 -n {apk}/.MainActivity')
    deadline = time.time() + timeout
    while time.time() < deadline:
        ready = root(f'{launcher} exec sh -c "test -f /run/user/1000/rungic-session.env && pidof kwin_wayland '
                     '>/dev/null && pidof plasmashell >/dev/null && echo ready"', check=False).stdout
        if 'ready' in ready:
            recorder.step('ready', seconds=round(timeout - (deadline - time.time())))
            return True
        time.sleep(3)
    recorder.step('not-ready', timeout=timeout)
    return False


def up(apk):
    if layout() != 'moto':
        raise SystemExit('the Android side already has the Rungic layout')
    apk = Path(apk)
    if not apk.exists():
        raise SystemExit(f'no APK at {apk}: plasma/build-apk.sh')
    recorder = Record('up')
    before = status()
    recorder.save('before.json', json.dumps(before, indent=1, ensure_ascii=False) + '\n')
    recorder.save('appops-before.txt', out(f'appops get {OLD_APK}', 'root'))
    recorder.save('package-before.txt', out(f'dumpsys package {OLD_APK}', 'root'))
    if 'state=none' not in before['rootfs']:
        raise SystemExit(f'the rootfs image has a snapshot or merge in progress: {before["rootfs"]}')
    recorder.step('record', rootfs=before['rootfs'], apks=before['apks'])
    # The new APK first (not started): installing it needs nothing of the old layout.
    subprocess.run(adb('install', '-r', str(apk)), check=True, capture_output=True, timeout=300)
    recorder.step('apk-installed', apk=apk.name)
    text = stop_all('/data/adb/moto-plasma/moto-plasma', '/data/adb/moto-lxc/moto-lxc',
                    '/data/adb/moto-wfd/moto-cast-watch', OLD_APK, 'moto-plasma-root')
    recorder.step('stopped', output=text[-300:])
    moves = '\n'.join(f'[ -e {new} ] && {{ echo "{new} exists" >&2; exit 1; }}; mv {old} {new}' for old, new in MOVES)
    root(f'set -e\n{moves}')
    recorder.step('moved', moves=MOVES)
    keep(RETIRED, recorder)
    root('rm -f ' + ' '.join(RETIRED))
    recorder.step('retired', paths=RETIRED)
    install_files(recorder)
    grant(recorder, f'/data/data/{OLD_APK}/shared_prefs/MainActivity.xml')
    root(f'pm disable-user --user 0 {OLD_APK}')
    recorder.step('old-apk-disabled')
    # What the boot scripts do, now: the cast policy is loaded already; the watcher starts.
    root('nohup /data/adb/rungic-wfd/rungic-cast-watch </dev/null >/dev/null 2>&1 &')
    ok = wait_ready('/data/adb/rungic-plasma/rungic-plasma', NEW_APK, recorder)
    recorder.save('after.json', json.dumps(status(), indent=1, ensure_ascii=False) + '\n')
    recorder.step('done', ok=ok, record=str(recorder.dir))
    return ok


def down():
    if layout() != 'rungic':
        raise SystemExit('the Android side already has the moto layout')
    recorder = Record('down')
    recorder.save('before.json', json.dumps(status(), indent=1, ensure_ascii=False) + '\n')
    text = stop_all('/data/adb/rungic-plasma/rungic-plasma', '/data/adb/rungic-lxc/rungic-lxc',
                    '/data/adb/rungic-wfd/rungic-cast-watch', NEW_APK, 'rungic-root')
    recorder.step('stopped', output=text[-300:])
    # Files `up` installed: the kept originals go back, the others go.
    for _, path, _ in INSTALL:
        root(f'if [ -e {KEEP}{path} ]; then cp -a {KEEP}{path} {path}.old && mv {path}.old {path}; else rm -f {path}; fi')
    root(f'[ ! -f {KEEP}{TERMUX_LXC} ] || cat {KEEP}{TERMUX_LXC} > {TERMUX_LXC}')
    for path in RETIRED:
        root(f'[ ! -e {KEEP}{path} ] || cp -a {KEEP}{path} {path}')
    recorder.step('restored', files=[path for _, path, _ in INSTALL] + RETIRED)
    root('set -e\n' + '\n'.join(f'mv {new} {old}' for old, new in reversed(MOVES)))
    recorder.step('moved', moves=[(new, old) for old, new in reversed(MOVES)])
    root(f'pm enable --user 0 {OLD_APK}; pm disable-user --user 0 {NEW_APK}')
    root(f'rm -rf {KEEP}')
    recorder.step('apks', enabled=OLD_APK, disabled=NEW_APK)
    root('nohup /data/adb/moto-wfd/moto-cast-watch </dev/null >/dev/null 2>&1 &')
    ok = wait_ready('/data/adb/moto-plasma/moto-plasma', OLD_APK, recorder)
    recorder.step('done', ok=ok, record=str(recorder.dir))
    return ok


# Docker (docs/19, docs/70): its own runtime, independent of the APK. Besides the directory, its
# SELinux types change: the runtime tree on f2fs and every file inside the ext4 data image carry
# moto_docker_file, the image itself moto_docker_image; the domain moto_docker is a process label.
DOCKER_OLD, DOCKER_NEW = '/data/adb/moto-docker', '/data/adb/rungic-docker'
DOCKER_TYPES = [('moto_docker_file', 'rungic_docker_file'), ('moto_docker_image', 'rungic_docker_image')]
DOCKER_RETIRED = [f'{DOCKER_NEW}/moto-docker', f'{DOCKER_NEW}/moto-docker-enter', f'{DOCKER_NEW}/moto-docker-enter-test',
                  '/data/adb/service.d/moto-docker.sh']
TERMUX_DOCKER = ['/data/data/com.termux/files/usr/bin/docker', '/data/data/com.termux/files/usr/bin/docker-service']
DOCKER_INSTALL = [
    ('docker/rungic-docker', f'{DOCKER_NEW}/rungic-docker', '755'),
    (BUILD / 'android/rungic-docker-enter', f'{DOCKER_NEW}/rungic-docker-enter', '755'),
    ('docker/network.sh', f'{DOCKER_NEW}/network.sh', '755'),
    ('docker/sepolicy.rule', f'{DOCKER_NEW}/sepolicy.rule', '644'),
    ('docker/boot-service.sh', '/data/adb/service.d/rungic-docker.sh', '755'),
    ('docker/compose.yaml', f'{DOCKER_NEW}/runtime/root/stacks/web/compose.yaml', '644'),
]
BUSYBOX = '/data/adb/magisk/busybox'
# The workloads' names: the compose project of the web stack (its volume's data is copied), a
# standalone bind volume, the example project on shared storage and an image tag. The old volumes
# and tag stay until phase D (docker-down uses them).
SHARED_DOCKER = '/sdcard/Docker'
WEB_STACK = '/root/stacks/web/compose.yaml'


def docker_stop(base, name, recorder):
    result = root(f'[ ! -x {base}/{name} ] || {base}/{name} stop', timeout=240, check=False)
    # The network watcher leaves within 15 s once `running` is gone; the data image's loop device goes too.
    root(f'pkill -f "{name} watch-network"\n'
         'for f in /sys/block/loop*/loop/backing_file; do\n'
         '  case "$(cat $f 2>/dev/null)" in */docker-data.ext4) d=${f#/sys/block/}; losetup -d /dev/block/${d%%/*} ;; esac\n'
         'done; true', check=False)
    left = root('pidof dockerd containerd bindfs; losetup -a | grep docker-data; true', check=False).stdout.strip()
    recorder.step('docker-stopped', ok=result.returncode == 0, output=(result.stdout + result.stderr)[-300:])
    if result.returncode or left:
        raise SystemExit(f'Docker did not stop: {result.stdout}{result.stderr} {left}')


def docker_relabel(base, pairs, recorder):
    """Every file of the runtime tree and of the data image with an old type gets the new one."""
    counts = {}
    for old, new in pairs:
        text = root(f'{BUSYBOX} find {base} -xdev -context u:object_r:{old}:s0 -exec chcon -h u:object_r:{new}:s0 {{}} + ; '
                    f'{BUSYBOX} find {base} -xdev -context u:object_r:{new}:s0 | wc -l', timeout=600).stdout
        counts[f'runtime:{new}'] = int(text.split()[-1])
    old, new = pairs[0]
    lib = f'{base}/runtime/var/lib/docker'
    # The image is mounted in a private namespace at its usual place; its root is the image's own inode.
    inner = (f'{BUSYBOX} mount --make-rprivate / && mount -t ext4 -o noatime $loop {lib} && '
             f'{BUSYBOX} find {lib} -xdev -context u:object_r:{old}:s0 -exec chcon -h u:object_r:{new}:s0 {{}} + ; '
             f'echo left \\$({BUSYBOX} find {lib} -xdev -context u:object_r:{old}:s0 | wc -l) '
             f'new \\$({BUSYBOX} find {lib} -xdev -context u:object_r:{new}:s0 | wc -l); umount {lib}')
    text = root(f'set -e\nloop=$(losetup -sf {base}/docker-data.ext4)\n'
                f'unshare -m sh -c "{inner}"\n# toybox attaches with autoclear: the umount usually released it already.\nlosetup -d $loop 2>/dev/null || true', timeout=1800).stdout.split()
    counts['image:left'], counts[f'image:{new}'] = int(text[1]), int(text[3])
    recorder.step('docker-relabeled', **counts)
    if counts['image:left']:
        raise SystemExit(f'files in the data image still labelled {old}: {counts["image:left"]}')
    return counts


def docker_cli(base, name, args, timeout=300, check=True):
    return root(f'{base}/{name} cli {args}', timeout=timeout, check=check)


def docker_up():
    if root(f'[ -d {DOCKER_OLD} ] && [ ! -e {DOCKER_NEW} ] && echo ok', check=False).stdout.strip() != 'ok':
        raise SystemExit(f'expected {DOCKER_OLD} and no {DOCKER_NEW}')
    missing = [str(src) for src, _, _ in DOCKER_INSTALL if not (WORKSPACE / src).exists()]
    if missing:
        raise SystemExit(f'build these first: {missing}')
    recorder = Record('docker-up')
    old = f'{DOCKER_OLD}/moto-docker'
    recorder.save('before.txt', root(f'{old} status; {old} cli ps -a; {old} cli volume ls; {old} cli images',
                                     check=False).stdout)
    docker_stop(DOCKER_OLD, 'moto-docker', recorder)
    root(f'mv {DOCKER_OLD} {DOCKER_NEW}')
    recorder.step('moved', moves=[(DOCKER_OLD, DOCKER_NEW)])
    keep(DOCKER_RETIRED + [path for _, path, _ in DOCKER_INSTALL] + TERMUX_DOCKER, recorder)
    root('rm -f ' + ' '.join(DOCKER_RETIRED))
    for src, path, mode in DOCKER_INSTALL:
        remote = push(WORKSPACE / src, 'rungic-cutover-file')
        root(f'install -m {mode} {remote} {path}.new && mv {path}.new {path} && rm -f {remote}')
    remote = push(WORKSPACE / 'docker/termux-docker', 'rungic-cutover-file')
    root(' ; '.join(f'[ ! -f {t} ] || cat {remote} > {t}' for t in TERMUX_DOCKER) + f'; rm -f {remote}')
    recorder.step('installed', files=[path for _, path, _ in DOCKER_INSTALL] + TERMUX_DOCKER)
    # The new types exist once the rule is loaded; the old ones stay in the live policy until a reboot.
    root(f'magiskpolicy --live --apply {DOCKER_NEW}/sepolicy.rule')
    docker_relabel(DOCKER_NEW, DOCKER_TYPES, recorder)
    started = root(f'{DOCKER_NEW}/rungic-docker start', timeout=240, check=False)
    recorder.step('docker-started', ok=started.returncode == 0, output=(started.stdout + started.stderr)[-400:])
    if started.returncode:
        raise SystemExit('Docker did not start: ' + started.stdout + started.stderr)
    # The workloads under their new names.
    cli = lambda args, **kw: docker_cli(DOCKER_NEW, 'rungic-docker', args, **kw)
    cli('compose -p moto-server down')
    cli(f'compose -f {WEB_STACK} create')
    cli("run --rm -v moto-server_webdata:/from:ro -v rungic-server_webdata:/to alpine:3.22 sh -c 'cp -a /from/. /to/'")
    cli(f'compose -f {WEB_STACK} up -d')
    cli('volume create --driver local -o type=none -o o=bind -o device=/sdcard/Docker/shared/named-example '
        'rungic-shared-example')
    cli('tag moto-alpine:3.22.6 rungic-alpine:3.22.6')
    remote = push(WORKSPACE / 'docker/shared-storage-readme.txt', 'rungic-cutover-file')
    root(f'cp {SHARED_DOCKER}/compose-example.yaml {KEEP}/compose-example.yaml\n'
         f"sed -i 's/^name: moto-storage-demo$/name: rungic-storage-demo/' {SHARED_DOCKER}/compose-example.yaml\n"
         f'cp {SHARED_DOCKER}/README.txt {KEEP}/README.txt; cat {remote} > {SHARED_DOCKER}/README.txt; rm -f {remote}')
    recorder.step('workloads', project='rungic-server', volume='rungic-shared-example', image='rungic-alpine:3.22.6')
    health = ''
    for _ in range(40):
        health = cli("inspect -f '{{.State.Health.Status}}' rungic-nginx", check=False).stdout.strip()
        if health == 'healthy':
            break
        time.sleep(3)
    new = f'{DOCKER_NEW}/rungic-docker'
    recorder.save('after.txt', root(f'{new} status; {new} cli volume ls; {new} cli images', check=False).stdout)
    recorder.step('done', ok=health == 'healthy', health=health, record=str(recorder.dir))
    return health == 'healthy'


def docker_down():
    if root(f'[ -d {DOCKER_NEW} ] && [ ! -e {DOCKER_OLD} ] && echo ok', check=False).stdout.strip() != 'ok':
        raise SystemExit(f'expected {DOCKER_NEW} and no {DOCKER_OLD}')
    recorder = Record('docker-down')
    docker_cli(DOCKER_NEW, 'rungic-docker', 'compose -p rungic-server down', check=False)
    docker_stop(DOCKER_NEW, 'rungic-docker', recorder)
    for _, path, _ in DOCKER_INSTALL:
        root(f'if [ -e {KEEP}{path} ]; then cp -a {KEEP}{path} {path}.old && mv {path}.old {path}; else rm -f {path}; fi')
    for path in DOCKER_RETIRED:
        root(f'[ ! -e {KEEP}{path} ] || cp -a {KEEP}{path} {path}')
    for path in TERMUX_DOCKER:
        root(f'[ ! -f {KEEP}{path} ] || cat {KEEP}{path} > {path}')
    root(f'[ ! -f {KEEP}/compose-example.yaml ] || cp {KEEP}/compose-example.yaml {SHARED_DOCKER}/compose-example.yaml; '
         f'[ ! -f {KEEP}/README.txt ] || cp {KEEP}/README.txt {SHARED_DOCKER}/README.txt')
    recorder.step('restored')
    # The old rule, restored above; its types are still in the live policy ("already exists").
    root(f'magiskpolicy --live --apply {DOCKER_NEW}/sepolicy.rule', check=False)
    docker_relabel(DOCKER_NEW, [(new, old) for old, new in DOCKER_TYPES], recorder)
    root(f'mv {DOCKER_NEW} {DOCKER_OLD}')
    started = root(f'{DOCKER_OLD}/moto-docker start', timeout=240, check=False)
    recorder.step('docker-started', ok=started.returncode == 0, output=(started.stdout + started.stderr)[-400:])
    # The old project again (its compose file restored above, its volume kept).
    docker_cli(DOCKER_OLD, 'moto-docker', f'compose -f {WEB_STACK} up -d', check=False)
    recorder.step('done', ok=started.returncode == 0, record=str(recorder.dir))
    return started.returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    p = sub.add_parser('up')
    p.add_argument('--apk', default=str(DEFAULT_APK))
    sub.add_parser('down')
    sub.add_parser('docker-up')
    sub.add_parser('docker-down')
    args = parser.parse_args()
    if args.action == 'status':
        print(json.dumps(status(), indent=1, ensure_ascii=False))
        return 0
    actions = {'up': lambda: up(args.apk), 'down': down, 'docker-up': docker_up, 'docker-down': docker_down}
    return 0 if actions[args.action]() else 1


if __name__ == '__main__':
    sys.exit(main())
