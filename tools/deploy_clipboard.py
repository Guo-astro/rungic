#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deploy the clipboard backend to an explicitly selected, already configured Plasma phone.

Keep that phone's controller baseline: add only clipboard start/stop hooks. An older G100
account-setup does not support the current controller's --status (see clipboard-background.md).
The APK, host helper and Linux script form one protocol change; keep backups for rollback.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def controller_with_clipboard(source):
    for anchor, addition in (
        ('    if [ "$action" = stop ]; then\n', '      "$BASE/android-clipboard" stop 9>&-\n'),
        ('    "$BASE/android-audio" start 9>&-\n', '    "$BASE/android-clipboard" start 9>&-\n'),
    ):
        if addition.strip() in source:
            continue
        if source.count(anchor) != 1:
            raise ValueError('Unrecognized controller lifecycle; inspect before deploying')
        source = source.replace(anchor, anchor + addition)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--port', type=int, default=5037)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    adb = ['adb', '-P', str(args.port), '-s', args.serial]
    ctl = '/data/adb/rungic-plasma/rungic-plasma'

    def run(*parts, **kw):
        return subprocess.check_output(adb + list(parts), timeout=180, **kw).decode()

    def root(script):
        return run('shell', 'su', '-c', 'sh', input=('set -e\n' + script).encode())

    identity = root('id\ngetprop ro.build.fingerprint\ngetenforce\n')
    if 'uid=0(' not in identity:
        raise RuntimeError('Magisk Shell root required')
    (args.output / 'identity.txt').write_text(identity)
    before = root('cat ' + ctl)
    (args.output / 'controller.before').write_text(before)
    controller = controller_with_clipboard(before)
    (args.output / 'controller.incremental').write_text(controller)
    current = run('shell', 'pm', 'path', 'com.rungic.plasma').splitlines()[0].removeprefix('package:')
    run('pull', current, str(args.output / 'before.apk'))
    (args.output / 'clipboard.before.py').write_text(root(ctl + ' exec cat /usr/bin/rungic-clipboard'))
    (args.output / 'helper.before').write_text(root('if [ -f /data/adb/rungic-plasma/android-clipboard ]; then cat /data/adb/rungic-plasma/android-clipboard; fi'))
    files = [(args.output / 'controller.incremental', ctl),
             (ROOT / 'system/android-clipboard', '/data/adb/rungic-plasma/android-clipboard'),
             (ROOT / 'shared/platform/clipboard.py', '/usr/bin/rungic-clipboard')]
    remote = '/data/local/tmp/rungic-clipboard-' + str(time.time_ns())
    run('shell', 'mkdir', '-p', remote)
    for index, (local, _) in enumerate(files[:2]):
        run('push', str(local), remote + '/' + str(index))
    # Install in Android shell context, not Magisk root's Binder context.
    root('if [ -x /data/adb/rungic-plasma/android-clipboard ]; then /data/adb/rungic-plasma/android-clipboard stop; fi\n')
    print(run('install', '--no-incremental', '-r', str(args.apk)))
    # Rename complete files: overwriting an executing shell script can corrupt its next read.
    for index, (_, dest) in enumerate(files[:2]):
        root('cp ' + remote + '/' + str(index) + ' ' + dest + '.new\n'
             'chmod 755 ' + dest + '.new\nmv ' + dest + '.new ' + dest + '\n')
    content = (ROOT / 'shared/platform/clipboard.py').read_bytes()
    code = "import base64,pathlib;p=pathlib.Path('/usr/bin/rungic-clipboard.new');p.write_bytes(base64.b64decode(" + repr(base64.b64encode(content).decode()) + "));p.chmod(0o755);p.replace('/usr/bin/rungic-clipboard')"
    root(shlex.join([ctl, 'exec', 'python3', '-c', code]))
    root('/data/adb/rungic-plasma/android-clipboard start\n' + ctl + ' user-exec systemctl --user restart rungic-plasma-clipboard.service\n')
    print(run('shell', 'am', 'start', '-n', 'com.rungic.plasma/.MainActivity'))
    root('rm -rf ' + shlex.quote(remote))
    (args.output / 'deployment.json').write_text(json.dumps({
        'serial': args.serial, 'port': args.port, 'kind': 'incremental-files-not-release-image',
        'apk_sha256': hashlib.sha256(args.apk.read_bytes()).hexdigest(),
        'files': {dest: hashlib.sha256(local.read_bytes()).hexdigest() for local, dest in files},
        'acceptance': 'Run independent Android copy/paste, fullscreen and backend recovery checks separately',
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
