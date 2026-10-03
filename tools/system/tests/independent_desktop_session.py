# SPDX-License-Identifier: MIT
"""The independent desktop's session (desktop mode's workspace 0, docs/research/97 §19), as
rungic-workspace@0.service runs it: the real rungic-workspace 0 with its own headless KWin
(--virtual, as on the phone), its own session bus, its settings mirror (rungic-desktop-dirs) and
its helpers. What the test container lacks is a stand-in first on PATH, recording what it is given:
plasmashell (Plasma's desktop shell is not installed here: the stand-in is a Wayland client of the
workspace's KWin that ends when that KWin goes, as the shell does) and rungic-clipboard (the
Android clipboard bridge; its Android end is tools/system/tests/desktop_clipboard.py's).

Checked: the desktop shell, not the mobile one, starts in the workspace's KWin and bus and starts
again after it ended; the programs of the desktop (the shell, and what rungic-workspace-env 0 starts
from the phone's session) have none of the phone's form factor and say RUNGIC_WORKSPACE=0 (what
Firefox's desktop-session patch reads); the clipboard bridge starts again a few seconds after it
ended; no keeper (which freezes and closes idle workspaces) runs for 0; stopped as systemd stops the
unit (SIGTERM to every process of it), every process of it is gone within seconds, without SIGKILL,
and the unit ends cleanly."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import harness

UNIT = Path('/src/agent/workspace/rungic-workspace@.service')
PHONE_SESSION = {'PLASMA_PLATFORM': 'phone:handset', 'QT_QUICK_CONTROLS_MOBILE': 'true',
                 'PLASMA_DEFAULT_SHELL': 'org.kde.plasma.mobileshell'}
FORM_FACTOR = tuple(PHONE_SESSION)

SHELL = r'''#!/usr/bin/python3
# The stand-in of Plasma's desktop shell: records how it was started, ends at once the first time
# (a crash), later stays a client of the KWin it was given until that KWin goes.
import json, os, socket, subprocess, sys, time
log = os.environ['WS0_STUB_LOG']
n = len([f for f in os.listdir(log) if f.startswith('plasmashell-') and f.endswith('.json')])
kwin = subprocess.run(['dbus-send', '--session', '--print-reply', '--dest=org.freedesktop.DBus', '/org/freedesktop/DBus',
                       'org.freedesktop.DBus.NameHasOwner', 'string:org.kde.KWin'], capture_output=True, text=True).stdout
path = os.path.join(os.environ['XDG_RUNTIME_DIR'], os.environ.get('WAYLAND_DISPLAY', ''))
client = socket.socket(socket.AF_UNIX)
client.connect(path)
with open(os.path.join(log, f'plasmashell-{n}.json'), 'w') as out:
    json.dump({'argv': sys.argv[1:], 'env': dict(os.environ), 'started': time.time(),
               'kwin_on_bus': 'boolean true' in kwin}, out)
if n == 0:
    time.sleep(1)
    with open(os.path.join(log, 'plasmashell-0.ended'), 'w') as out:
        out.write(str(time.time()))
    sys.exit(1)
while client.recv(4096):
    pass
'''

CLIPBOARD = r'''#!/bin/sh
# The stand-in of the Android clipboard bridge: records its start and ends (its bridge gone).
echo "$(date +%s.%N) $WAYLAND_DISPLAY" >> "$WS0_STUB_LOG/clipboard.starts"
sleep 0.5
exit 1
'''


def processes():
    return {int(e.name) for e in Path('/proc').iterdir() if e.name.isdigit()}


def alive(pid):
    try:
        state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state != 'Z'


def name(pid):
    try:
        return Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace').strip()
    except OSError:
        return '?'


# covers[system]: desktop-mode.independent-desktop/E1 desktop-mode.independent-desktop/E4
# covers[system]: desktop-mode.independent-desktop/E6 desktop-mode.clipboard/E2
def test():
    steps = []

    def check(condition, what):
        steps.append(what)
        if not condition:
            raise harness.Failed(f'{what}: not so')

    runtime = Path(f'/tmp/rt-{os.getuid()}')
    runtime.mkdir(mode=0o700, exist_ok=True)
    home = Path.home()
    stubs = Path('/tmp/ws0-stubs')
    log = Path('/tmp/ws0-log')
    for d in (stubs, log):
        d.mkdir(exist_ok=True)
    (stubs / 'plasmashell').write_text(SHELL)
    (stubs / 'rungic-clipboard').write_text(CLIPBOARD)
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    (home / '.config').mkdir(exist_ok=True)
    (home / '.config/kdeglobals').write_text('[General]\nColorScheme=BreezeDark\n')
    # Started as the unit starts it, from the user manager, whose environment is the phone's session's.
    env = {**os.environ, **PHONE_SESSION, 'XDG_RUNTIME_DIR': str(runtime), 'WS0_STUB_LOG': str(log),
           'PATH': f'{stubs}:/usr/local/bin:/usr/bin:/bin', 'LIBGL_ALWAYS_SOFTWARE': '1',
           'KWIN_WAYLAND_NO_PERMISSION_CHECKS': '1', 'WAYLAND_DISPLAY': 'wayland-0'}
    out = open('/tmp/rungic-workspace-0.log', 'w')
    # What runs before it is the test's: everything that appears after is the unit's (its cgroup holds
    # them all, the services its bus starts too, whose parent is not the workspace).
    before = processes()
    workspace = subprocess.Popen(['/usr/bin/rungic-workspace', '0'], env=env, stdout=out, stderr=subprocess.STDOUT,
                                 start_new_session=True)
    state = home / '.local/state/rungic-workspaces/0'
    try:
        wait = lambda condition, timeout, what: _wait(condition, timeout, what, workspace)
        wait(lambda: (runtime / 'wayland-ws-0').exists() and (state / 'bus').exists()
             and (runtime / 'remote-surface/screens.d/ws-0.json').exists(), 30, "the desktop's KWin and bus")
        bus = (state / 'bus').read_text().strip()
        check(bus == f'unix:path={runtime}/rungic-workspace-0.bus', 'the desktop has a session bus of its own')
        screen = json.loads((runtime / 'remote-surface/screens.d/ws-0.json').read_text())
        check(screen['kind'] == 'desktop' and screen['wayland'] == f'{runtime}/wayland-ws-0',
              'it is listed for remote viewing as the computer desktop')

        # ---- the desktop shell: Plasma's desktop, in the workspace, again after it ended ---------------
        wait(lambda: (log / 'plasmashell-1.json').exists(), 30, 'the desktop shell started a second time')
        first = json.loads((log / 'plasmashell-0.json').read_text())
        second = json.loads((log / 'plasmashell-1.json').read_text())
        check(first['argv'][:2] == ['-p', 'org.kde.plasma.desktop'], "the shell started is Plasma's desktop shell")
        shell_env = first['env']
        check(shell_env['WAYLAND_DISPLAY'] == 'wayland-ws-0' and shell_env['DBUS_SESSION_BUS_ADDRESS'] == bus
              and first['kwin_on_bus'], "it is a client of the desktop's KWin, on the bus where that KWin is")
        ended = float((log / 'plasmashell-0.ended').read_text())
        check(second['started'] - ended < 5 and second['argv'] == first['argv'],
              f'after the shell ended it was started again ({second["started"] - ended:.1f} s)')

        # ---- the desktop's programs are a desktop's -----------------------------------------------------
        check(not any(k in shell_env for k in FORM_FACTOR) and shell_env.get('RUNGIC_WORKSPACE') == '0',
              "the shell's environment has none of the phone's form factor, and RUNGIC_WORKSPACE=0")
        check(shell_env['XDG_CONFIG_HOME'] == str(state / 'config')
              and (state / 'config/kdeglobals').resolve() == home / '.config/kdeglobals',
              "its settings directory is the desktop's own, the user's settings linked in")
        started = subprocess.run(['rungic-workspace-env', '0', 'env'], capture_output=True, text=True, check=True,
                                 env={**env, 'PATH': '/usr/local/bin:/usr/bin:/bin'}).stdout
        app_env = dict(line.split('=', 1) for line in started.splitlines() if '=' in line)
        check(not any(k in app_env for k in FORM_FACTOR) and app_env.get('RUNGIC_WORKSPACE') == '0'
              and app_env.get('WAYLAND_DISPLAY') == 'wayland-ws-0' and app_env.get('DBUS_SESSION_BUS_ADDRESS') == bus,
              "a program started in it from the phone's session is the desktop's, without the phone's form factor")

        # ---- the clipboard bridge again after it ended ---------------------------------------------------
        wait(lambda: len((log / 'clipboard.starts').read_text().splitlines()) >= 3
             if (log / 'clipboard.starts').exists() else False, 20, 'the clipboard bridge started three times')
        starts = [line.split() for line in (log / 'clipboard.starts').read_text().splitlines()]
        gaps = [float(b[0]) - float(a[0]) for a, b in zip(starts, starts[1:])]
        check(all(s[1] == 'wayland-ws-0' for s in starts) and max(gaps) < 5,
              f"the clipboard bridge of the desktop's display starts again after it ended ({', '.join(f'{g:.1f}' for g in gaps)} s apart)")

        # ---- never frozen or closed for being idle --------------------------------------------------------
        tree = [p for p in processes() - before if alive(p) and p != os.getpid()]
        check(not any('rungic-workspace-keeper' in name(p) for p in tree),
              'no keeper (it freezes and closes idle workspaces) runs for the desktop')

        # ---- stopped as systemd stops the unit: everything goes ---------------------------------------------
        unit = UNIT.read_text()
        check('KillMode=' not in unit, "the unit's processes are all signalled on stop (KillMode control-group)")
        tree = [p for p in processes() - before if alive(p) and p != os.getpid()]
        names = {p: name(p) for p in tree}
        check(any('kwin_wayland' in n for n in names.values()) and any('dbus-daemon' in n for n in names.values())
              and any('rungic-desktop-dirs watch' in n for n in names.values())
              and any('plasmashell' in n for n in names.values()),
              f'the desktop runs: {len(tree)} processes, KWin, its bus, the settings mirror and the shell among them')
        stopped = time.monotonic()
        for pid in tree:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        status = workspace.wait(timeout=15)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(alive(p) for p in tree):
            time.sleep(0.1)
        left = [names[p] for p in tree if alive(p)]
        check(not left, f'all {len(tree)} processes of the desktop are gone {time.monotonic() - stopped:.1f} s after the stop'
              + (f'; left: {left}' if left else ''))
        check(status == 0, f'the unit ends cleanly on its stop (exit {status})')
        return steps
    finally:
        if workspace.poll() is None:
            for pid in processes() - before - {os.getpid()}:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        out.close()


def _wait(condition, timeout, what, workspace):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline or workspace.poll() is not None:
            state = Path.home() / '.local/state/rungic-workspaces/0'
            shell = (state / 'plasmashell.log').read_text()[-800:] if (state / 'plasmashell.log').exists() else '-'
            raise harness.Failed(f'timed out waiting for {what} (rungic-workspace: {workspace.poll()}); stand-ins: '
                                 f'{sorted(os.listdir("/tmp/ws0-log"))}; shell log: {shell}; '
                                 f"processes: {subprocess.run(['ps', '-eo', 'pid,ppid,stat,args'], capture_output=True, text=True).stdout}")
        time.sleep(0.2)


if __name__ == '__main__':
    harness.run('independent_desktop_session', test)
