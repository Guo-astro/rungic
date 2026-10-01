"""An agent workspace's lifetime (docs/research/91, "工作区的生命周期"): what runs in it ends with it.

As systemd's desktop conventions have it (docs/DESKTOP_ENVIRONMENTS.md): the workspace's own
processes are its unit, rungic-workspace@N; each app it starts is a scope
app-rungicwsN-<app id>-<random>.scope in the workspace's slice app-rungicwsN.slice (under
app.slice), bound to the unit (BindsTo, After: GNOME binds its apps to the session the same way).
When the workspace stops, systemd stops its apps first.

Stopping alone would end the apps as a signal does, losing what is unsaved. So closing goes in two
phases, as Plasma's logout does (ksmserver, KWin's closeWaylandWindows): every window is asked to
close as its title bar's close button does, and an app saves or asks; one that does not go is
reported and the workspace stays (Plasma logs out anyway after two minutes; nothing here does
unless forced). Only then the unit stops. Windows of programs started otherwise (a command in the
agent's shell) are asked the same way. An X11 program without WM_DELETE_WINDOW would be killed by
KWin's close: it is not asked, it is reported.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

CLOSE_TIMEOUT_S = 20.0


def user_env() -> dict:
    """For systemctl and systemd-run: the user's session bus, also from inside a workspace (its own
    bus has no systemd: `freeze` failed there with "Failed to add reference to unit")."""
    runtime = os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
    return dict(os.environ, DBUS_SESSION_BUS_ADDRESS=os.environ.get('RUNGIC_USER_DBUS_SESSION_BUS_ADDRESS')
                or f'unix:path={runtime}/bus')


def unit(slot: int | str) -> str:
    return f'rungic-workspace@{slot}.service'


def slice_name(slot: int | str) -> str:
    return f'app-rungicws{slot}.slice'


def scope_name(slot: int | str, app_id: str, random: str) -> str:
    """app-<launcher>-<app id>-<random>.scope, the launcher being the workspace."""
    return f'app-rungicws{slot}-{app_id}-{random}.scope'


def scope_properties(slot: int | str) -> list[str]:
    """systemd-run options that put an app's scope in the workspace's slice, tied to the workspace:
    stopped with it, before it."""
    # Stopped after the apps were asked to close (close): a signal, then SIGKILL 10 s later rather than
    # systemd's 90 (GNOME gives its apps 5).
    return [f'--slice={slice_name(slot)}', '-p', f'BindsTo={unit(slot)}', '-p', f'After={unit(slot)}',
            '-p', 'TimeoutStopSec=10']


def closing_marker(slot) -> Path:
    """While it exists the workspace is being closed: its keeper freezes nothing (a frozen app
    neither answers the close request nor ends on a signal)."""
    return _runtime() / f'rungic-workspace-{slot}.closing'


def _state(slot) -> Path:
    return Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'rungic-workspaces' / str(slot)


def _runtime() -> Path:
    return Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')


def thaw(slot, run=subprocess.run) -> bool:
    """Its apps running again if its keeper froze them (rungic-workspace-keeper): before anything
    reaches them (a frozen app answers nothing). True if they were frozen."""
    uid = os.getuid()
    events = Path(f'/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/'
                  f'{slice_name(slot)}/cgroup.events')
    try:
        frozen = 'frozen 1' in events.read_text()
    except OSError:
        return False
    if frozen:
        run(['systemctl', '--user', 'thaw', slice_name(slot)], capture_output=True, timeout=15, env=user_env())
    return frozen


def dismissed(slot) -> bool:
    """The user closed the assistant's screen while the agent was at work (rungic-agent-screen
    dismiss): not brought back during this task."""
    return (_runtime() / f'rungic-agent-screen-dismissed-{slot}').exists()


def running(slot, run=subprocess.run) -> bool:
    return run(['systemctl', '--user', 'is-active', '--quiet', unit(slot)], timeout=10, env=user_env()).returncode == 0


def ready(slot) -> bool:
    """Its bus and display are up (what rungic-workspace-env needs)."""
    try:
        bus = (_state(slot) / 'bus').read_text().strip()
    except OSError:
        return False
    return bool(bus) and (_runtime() / f'wayland-ws-{slot}').exists()


def ensure(slot, wait: float = 10.0, run=subprocess.run) -> bool:
    """Start the workspace unless it runs; True once it is ready."""
    deadline = time.monotonic() + wait
    started = False
    while not ready(slot):
        if not started:
            run(['systemctl', '--user', 'start', '--no-block', unit(slot)], capture_output=True, timeout=10,
                env=user_env())
            started = True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.2)
    return True


def own_pids(slot, run=subprocess.run) -> set[int]:
    """The workspace's own processes (KWin, Xwayland, its desktop, stream and input helpers)."""
    group = run(['systemctl', '--user', 'show', '-p', 'ControlGroup', '--value', unit(slot)],
                capture_output=True, text=True, timeout=10, env=user_env()).stdout.strip()
    pids: set[int] = set()
    if not group:
        return pids
    root = Path('/sys/fs/cgroup') / group.lstrip('/')
    for procs in root.rglob('cgroup.procs') if root.is_dir() else []:
        try:
            pids.update(int(p) for p in procs.read_text().split())
        except (OSError, ValueError):
            pass
    return pids


def summary(window: dict, dialog: bool) -> dict:
    return {'caption': window.get('caption', ''), 'app': window.get('resource_class', ''),
            'pid': window.get('pid'), 'dialog': dialog}


def x11_without_close(run=subprocess.run) -> set:
    """X11 windows (this workspace's Xwayland, $DISPLAY) that do not take WM_DELETE_WINDOW: KWin's
    close would kill them (x11window.cpp, closeWindow). Their process ids, and their WM_CLASS
    classes (lower case) for those that set no _NET_WM_PID (xmessage sets none)."""
    if not os.environ.get('DISPLAY'):
        return set()
    try:
        listing = run(['xprop', '-root', '_NET_CLIENT_LIST'], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    found: set = set()
    for wid in [w.strip(' ,') for w in listing.partition('#')[2].split()]:
        try:
            props = run(['xprop', '-id', wid, 'WM_PROTOCOLS', '_NET_WM_PID', 'WM_CLASS'], capture_output=True,
                        text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if 'WM_DELETE_WINDOW' in props:
            continue
        pid = klass = None
        for line in props.splitlines():
            if line.startswith('_NET_WM_PID') and '=' in line:
                try:
                    pid = int(line.split('=')[1])
                except ValueError:
                    pass
            elif line.startswith('WM_CLASS') and '=' in line:
                names = [n.strip().strip('"') for n in line.split('=', 1)[1].split(',')]
                klass = names[-1].lower() if names else None
        if pid is not None:
            found.add(pid)
        elif klass:
            found.add(klass)
    return found


def _unaskable(window: dict, unaskable) -> bool:
    return window.get('pid') in unaskable or str(window.get('resource_class', '')).lower() in unaskable


def close_windows(kwin, keep: set[int], timeout: float = CLOSE_TIMEOUT_S, clock=time.monotonic,
                  sleep=time.sleep, unaskable: set = frozenset()) -> list[dict]:
    """Ask each app window in this KWin (not the workspace's own) to close, once; wait until none
    are left or `timeout`. The windows and dialogs still there: an app asking about its unsaved
    work, one that ignores the request, or one in `unaskable` (never asked: closing it would kill
    it)."""
    asked: set[str] = set()
    deadline = clock() + timeout
    while True:
        listing = kwin.windows()
        windows = [w for w in listing.get('windows', []) if w and w.get('pid') not in keep]
        dialogs = [w for w in listing.get('dialogs', []) if w and w.get('pid') not in keep]
        if not windows and not dialogs:
            return []
        for window in windows:
            # Dialogs are left alone: closing one would answer it (often "cancel").
            if window['id'] not in asked and not _unaskable(window, unaskable):
                asked.add(window['id'])
                try:
                    kwin.window_action(window['id'], 'close')
                except (RuntimeError, ValueError):
                    pass
        # Nothing left to wait for: only windows that are never asked.
        waiting = dialogs or any(not _unaskable(w, unaskable) for w in windows)
        if clock() > deadline or not waiting:
            remaining = []
            for w, dialog in [(w, False) for w in windows] + [(w, True) for w in dialogs]:
                item = summary(w, dialog)
                if not dialog and _unaskable(w, unaskable):
                    item['not_asked'] = 'an X11 program that would be killed by a close request'
                remaining.append(item)
            return remaining
        sleep(0.5)


def close(slot, *, timeout: float = CLOSE_TIMEOUT_S, force: bool = False, run=subprocess.run) -> dict:
    """Close workspace `slot`: its apps asked to close, then the workspace stopped. Not stopped
    while an app is still open, unless `force` (what is unsaved is lost)."""
    if not running(slot, run):
        return {'closed': True, 'was_running': False}
    marker = closing_marker(slot)
    try:
        marker.touch()
    except OSError:
        pass
    try:
        return _close(slot, timeout, force, run)
    finally:
        marker.unlink(missing_ok=True)


def _close(slot, timeout: float, force: bool, run) -> dict:
    thaw(slot, run)
    remaining: list[dict] = []
    # Apps switched over from the user's session (switch.py) go back there, not away.
    run(['rungic-cua', 'restore-apps', str(slot)], capture_output=True, timeout=60)
    if ready(slot):
        # The window phase talks to the workspace's KWin on its own bus: run inside it.
        done = run(['rungic-workspace-env', str(slot), 'rungic-cua', 'close-windows', str(timeout)],
                   capture_output=True, text=True, timeout=timeout + 30)
        try:
            remaining = json.loads(done.stdout or '{}').get('remaining') or []
        except ValueError:
            remaining = []
        if done.returncode != 0 and not force:
            return {'closed': False, 'error': (done.stderr or done.stdout).strip()[-500:]}
    if remaining and not force:
        return {'closed': False, 'remaining': remaining,
                'note': 'These apps are still open, most likely asking about unsaved work. Save or discard as '
                        'the user wants, then close again; force=true closes anyway and loses what is unsaved.'}
    thaw(slot, run)      # its keeper stays off while the marker is there; frozen otherwise, nothing ends
    run(['systemctl', '--user', 'stop', unit(slot)], capture_output=True, timeout=120, env=user_env())
    # Its slice (what was bound is already gone), and apps launched before scopes were bound and named
    # this way (app-rungic-wsN-…, until 2026-10-01).
    run(['systemctl', '--user', 'stop', slice_name(slot), f'app-rungic-ws{slot}-*.scope'], capture_output=True,
        timeout=120, env=user_env())
    result = {'closed': True, 'was_running': True}
    if remaining:
        result['closed_unsaved'] = remaining
    return result


# ---- a sub-agent's own workspace (docs/research/91, "由 Codex 当组长") ------------------------------
# Codex starts the desktop tools once per thread, a sub-agent's like its parent's, with the same
# environment. Each sub-agent's takes a workspace of its own at its first desktop call: the claim,
# rungic-workspace-N.busy, says an agent is at work there (its keeper neither freezes nor closes
# it, its window's close button only hides it). It names the process holding it and is touched at
# every call: a claim whose process ended, or untouched for CLAIM_STALE_S, is free again.
CLAIM_STALE_S = 20 * 60


def slots() -> list[int]:
    """The workspaces the host offers (APK: ws-1 to ws-4)."""
    return sorted(int(path.name[3:]) for path in Path('/mnt/android-wayland').glob('ws-*') if path.name[3:].isdigit())


def claim_path(slot) -> Path:
    return _runtime() / f'rungic-workspace-{slot}.busy'


def claim_holder(slot, clock=time.time) -> dict | None:
    """Who holds workspace `slot` now: the claim's record, or None. A claim without a record (a
    runner's empty file, tools/team) holds until removed."""
    path = claim_path(slot)
    try:
        text = path.read_text().strip()
        age = clock() - path.stat().st_mtime
    except OSError:
        return None
    if not text:
        return {'pid': None}
    try:
        record = json.loads(text)
        pid = int(record['pid'])
    except (ValueError, KeyError, TypeError):
        return {'pid': None}
    if age > CLAIM_STALE_S or not Path(f'/proc/{pid}').exists():
        return None
    return record


def claim(record: dict, exclude=(), run=subprocess.run, clock=time.time) -> int | None:
    """Take a free workspace for `record` (its pid, the thread): one not running first, else one
    nobody holds. None: all are held."""
    import fcntl
    with open(_runtime() / 'rungic-workspace-claims.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        free = [slot for slot in slots() if slot not in {int(s) for s in exclude} and claim_holder(slot, clock) is None]
        if not free:
            return None
        slot = next((slot for slot in free if not running(slot, run)), free[0])
        claim_path(slot).write_text(json.dumps({**record, 'since': round(clock())}))
        return slot


def touch_claim(slot) -> None:
    try:
        os.utime(claim_path(slot))
    except OSError:
        pass


def release(slot, pid: int) -> None:
    """Give the workspace back, if this process still holds it."""
    holder = claim_holder(slot)
    if holder and holder.get('pid') == pid:
        claim_path(slot).unlink(missing_ok=True)
