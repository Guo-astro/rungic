# SPDX-License-Identifier: MIT
# system-test: as root
"""A new desktop session after the previous one (the Rungic app restarting, docs/96): desktop/session,
run as the desktop account (uid 1000) the way rungic-plasma-session.service runs it, starts Plasma
Mobile (startplasmamobile) only once the previous session's startplasma-wayland has quit, which puts
the user manager's environment back as it found it (it once removed PLASMA_DEFAULT_SHELL after the
new session had set it: plasmashell came up as the desktop shell), and once the previous session's
units have stopped; a previous session that does not quit is killed. The one-time migrations
(rungic.upd, by KDE's kconf_update) are done before Plasma Mobile starts KWin, so KWin reads the
migrated input method at once.

Root installs what the phone's packages and the Android host would provide: the Android display's
socket, rungic.upd, and stand-ins for programs the session calls (startplasmamobile records when it
started and what KWin would read; systemctl records calls and reports the previous session's stop jobs)."""
import atexit
import os
import pwd
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import harness

SRC = Path('/src')
LOG = Path('/tmp/session-test')
OLD_IM = '/usr/local/share/applications/moto-plasma-rime.desktop'
NEW_IM = '/usr/share/applications/rungic-plasma-rime.desktop'
BIN = LOG / 'bin'    # stand-ins found on PATH, ahead of the system's (the container is shared with other tests)
PATH = f'{BIN}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'

STANDINS = {
    '/usr/libexec/rungic-user-dirs': '#!/bin/sh\nexit 0\n',
    '/usr/libexec/rungic-rebrand-user': '#!/bin/sh\nexit 0\n',
    f'{BIN}/kbuildsycoca6': '#!/bin/sh\nexit 0\n',
    # The user manager: calls are recorded; list-jobs shows the previous session's stop job while it lasts.
    f'{BIN}/systemctl': f'''#!/bin/sh
echo "$(date +%s.%N) $*" >> {LOG}/systemctl.log
case "$*" in *list-jobs*) [ ! -e {LOG}/stop-job ] || echo "12 plasma-plasmashell.service stop running" ;; esac
exit 0
''',
    # Plasma Mobile's start: when, what KWin would read, whether a previous session is still there.
    '/usr/bin/startplasmamobile': f'''#!/bin/sh
{{ echo "start=$(date +%s.%N)"
   echo "im=$(kreadconfig6 --file kwinrc --group Wayland --key InputMethod)"
   echo "old=$(pgrep -u "$(id -u)" -f '^(/usr/bin/)?startplasma-wayland' | wc -l)"
   echo "theme=${{QT_QPA_PLATFORMTHEME:-}}"
   echo "autolock=$(kreadconfig6 --file kscreenlockerrc --group Daemon --key Autolock)"
   echo "lockonresume=$(kreadconfig6 --file kscreenlockerrc --group Daemon --key LockOnResume)"; }} > {LOG}/new-start
''',
}


def prepare(user):
    shutil.rmtree(LOG, ignore_errors=True)
    LOG.mkdir(mode=0o777)
    LOG.chmod(0o777)
    for path, text in STANDINS.items():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text)
        Path(path).chmod(0o755)
    run_dir = Path('/run/user') / str(user.pw_uid)
    run_dir.mkdir(parents=True, exist_ok=True)
    os.chown(run_dir, user.pw_uid, user.pw_gid)
    run_dir.chmod(0o700)
    android = Path('/mnt/android-wayland')
    android.mkdir(parents=True, exist_ok=True)
    if not (android / 'wayland-0').exists():
        socket.socket(socket.AF_UNIX).bind(str(android / 'wayland-0'))
        # A stand-in of the host's socket, for this test only: the tests after it in the same
        # container are headless (workspace_headless took it for an Android host).
        atexit.register((android / 'wayland-0').unlink, missing_ok=True)
    # rungic-plasma-config's migrations, where the package puts them.
    # rungic-plasma-config's fixed screen locker settings.
    shutil.copy(SRC / 'system/config/etc/xdg/kscreenlockerrc', '/etc/xdg/kscreenlockerrc')
    Path('/usr/share/kconf_update').mkdir(parents=True, exist_ok=True)
    for item in (SRC / 'system/config/usr/share/kconf_update').iterdir():
        shutil.copy(item, Path('/usr/share/kconf_update') / item.name)


def as_user(user, command):
    return ['runuser', '-u', user.pw_name, '--', 'env', '-i', f'PATH={PATH}', 'LANG=C.UTF-8', 'bash', '-c', command]


def previous_session(user, then):
    """A previous session's startplasma-wayland that runs `then` and quits (as plasma-workspace's does)."""
    inner = then.replace("'", "'\\''")
    return subprocess.Popen(as_user(user, f"exec -a startplasma-wayland bash -c '{inner}'"))


def session(user):
    started = time.time()
    run = subprocess.run(as_user(user, f'sh {SRC}/desktop/session'), capture_output=True, text=True, timeout=60)
    if run.returncode:
        raise harness.Failed(f'desktop/session failed: {run.stdout[-800:]} {run.stderr[-1500:]}')
    record = dict(line.split('=', 1) for line in (LOG / 'new-start').read_text().splitlines())
    return started, float(record.pop('start')), record, run.stdout + run.stderr


# covers[system]: desktop.session/E3 desktop.session/E5 desktop.settings-migration/E4
def test():
    steps = []

    def check(condition, what):
        steps.append(what)
        if not condition:
            raise harness.Failed(f'{what}: not so; systemctl calls: '
                                 f'{(LOG / "systemctl.log").read_text()[-1500:] if (LOG / "systemctl.log").exists() else "-"}')

    user = pwd.getpwuid(1000)
    try:
        prepare(user)
        return restarts(user, check, steps)
    finally:
        for path in STANDINS:
            Path(path).unlink(missing_ok=True)
        for item in (SRC / 'system/config/usr/share/kconf_update').iterdir():
            (Path('/usr/share/kconf_update') / item.name).unlink(missing_ok=True)
        Path('/etc/xdg/kscreenlockerrc').unlink(missing_ok=True)


def restarts(user, check, steps):
    check(shutil.which('pgrep') is not None, 'the image has pgrep (procps), as the phone does')
    # The user's input method from before the move to /usr; kconf_update has not run for them yet.
    config = Path(user.pw_dir) / '.config'
    config.mkdir(exist_ok=True)
    (config / 'kwinrc').write_text(f'[Wayland]\nInputMethod={OLD_IM}\n')
    (config / 'kconf_updaterc').unlink(missing_ok=True)
    # A screen locker setting of the user's own (from before, or set by hand) that would lock Linux.
    (config / 'kscreenlockerrc').write_text('[Daemon]\nAutolock=true\nLockOnResume=true\nTimeout=1\n')
    subprocess.run(['chown', '-R', f'{user.pw_uid}:{user.pw_gid}', str(config)], check=True)

    # The previous session's startplasma-wayland quits 2.5 s from now.
    old = previous_session(user, f'sleep 2.5; date +%s.%N > {LOG}/old-quit; '
                                 'systemctl --user unset-environment PLASMA_DEFAULT_SHELL')
    time.sleep(0.5)
    began, start, record, output = session(user)
    old.wait(5)
    quit_at = float((LOG / 'old-quit').read_text())
    check(start > quit_at, 'Plasma Mobile starts only after the previous startplasma-wayland has quit')
    check(record['old'] == '0', 'no previous startplasma-wayland is left when it starts')
    unset = [l for l in (LOG / 'systemctl.log').read_text().splitlines() if 'unset-environment PLASMA_DEFAULT_SHELL' in l]
    check(unset and float(unset[0].split()[0]) < start,
          "the previous session's clean-up of the user manager's environment comes before the new session's start")
    check(record['autolock'] == 'false' and record['lockonresume'] == 'false',
          "the session's screen locker neither locks on idle nor on resume, whatever the user's file says: Android locks")
    check(record['theme'] == '', 'no platform theme forced by an earlier session reaches the new one')
    check(record['im'] == NEW_IM, 'the one-time migrations ran before Plasma Mobile started KWin: it reads the new input method')
    log = (LOG / 'systemctl.log').read_text()
    check('import-environment' in log and 'unset-environment QT_QPA_PLATFORMTHEME' in log,
          "the session's environment goes into the user manager")

    # The previous session has quit, but its units are still stopping for another 2 s.
    for name in ('new-start', 'systemctl.log'):
        (LOG / name).unlink(missing_ok=True)
    (LOG / 'stop-job').touch()
    stopped = []
    timer = threading.Timer(2, lambda: ((LOG / 'stop-job').unlink(), stopped.append(time.time())))
    timer.start()
    began, start, record, output = session(user)
    timer.join()
    check(stopped and start > stopped[0] and 'Waited' in output,
          "Plasma Mobile starts only after the previous session's units have stopped")

    # A previous session that does not quit is killed, and the new one still starts.
    for name in ('new-start', 'systemctl.log'):
        (LOG / name).unlink(missing_ok=True)
    stuck = subprocess.Popen(as_user(user, 'exec -a startplasma-wayland sleep 120'))
    time.sleep(0.5)
    began, start, record, output = session(user)
    check(stuck.wait(5) is not None, 'a previous session that does not quit is killed')
    check(record['old'] == '0' and 9 <= start - began <= 25,
          f'Plasma Mobile starts once it is gone, after waiting about 10 s ({start - began:.1f} s)')
    return steps


if __name__ == '__main__':
    harness.run('session_restart', test)
