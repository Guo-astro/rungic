"""rungic_cua.workspace (docs/research/91): what runs in a workspace ends with it, and closing it asks
its apps first. systemctl, rungic-workspace-env and KWin are stand-ins: nothing starts or stops."""
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'agent/computer-use'))
from rungic_cua import router, workspace  # noqa: E402


class FakeKWin:
    """Windows that go when asked, except those in `stubborn`."""

    def __init__(self, windows, dialogs=(), stubborn=()):
        self.open = {w['id']: w for w in windows}
        self.dialogs = list(dialogs)
        self.stubborn = set(stubborn)
        self.asked = []

    def windows(self):
        return {'windows': list(self.open.values()), 'dialogs': self.dialogs}

    def window_action(self, window_id, action):
        assert action == 'close'
        self.asked.append(window_id)
        if window_id not in self.stubborn:
            self.open.pop(window_id)
        return {'found': True}


def window(wid, pid, app='ardour'):
    return {'id': wid, 'pid': pid, 'caption': f'{app} window', 'resource_class': app}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


# covers: agent.workspace-lifecycle/E3
def test_apps_are_named_and_grouped_as_systemd_has_it_and_bound_to_the_workspace():
    assert workspace.scope_name(2, 'org.kde.kalk', '123') == 'app-rungicws2-org.kde.kalk-123.scope'
    assert workspace.scope_properties(2) == ['--slice=app-rungicws2.slice', '-p', 'BindsTo=rungic-workspace@2.service',
                                             '-p', 'After=rungic-workspace@2.service', '-p', 'TimeoutStopSec=10']


# covers: agent.workspace-lifecycle/E2
def test_apps_are_asked_once_and_the_workspaces_own_windows_stay():
    kwin = FakeKWin([window('a', 10), window('b', 11, 'blender'), window('own', 5, 'rungic-workspace-desktop')])
    clock = Clock()
    assert workspace.close_windows(kwin, keep={5}, clock=clock, sleep=clock.sleep) == []
    assert sorted(kwin.asked) == ['a', 'b']


# covers: agent.workspace-lifecycle/E2
def test_an_app_asking_about_unsaved_work_is_reported_not_answered():
    kwin = FakeKWin([window('a', 10)], dialogs=[window('d', 10)], stubborn={'a'})
    clock = Clock()
    remaining = workspace.close_windows(kwin, keep=set(), timeout=5, clock=clock, sleep=clock.sleep)
    assert kwin.asked == ['a']                     # asked once; the dialog is not closed (it would answer it)
    assert [(r['app'], r['dialog']) for r in remaining] == [('ardour', False), ('ardour', True)]


# covers: agent.workspace-lifecycle/E4
def test_an_x11_program_without_wm_delete_window_is_reported_not_closed():
    kwin = FakeKWin([window('x', 20, 'xterm'), window('a', 10)])
    clock = Clock()
    remaining = workspace.close_windows(kwin, keep=set(), clock=clock, sleep=clock.sleep, unaskable={20})
    assert kwin.asked == ['a']                   # KWin would have killed 20 instead of asking it
    assert remaining == [{'caption': 'xterm window', 'app': 'xterm', 'pid': 20, 'dialog': False,
                          'not_asked': 'an X11 program that would be killed by a close request'}]
    assert clock.now < 1                         # nothing left to wait for


# covers: agent.workspace-lifecycle/E4
def test_an_x11_program_without_a_pid_is_known_by_its_class():
    kwin = FakeKWin([window('x', 0, 'XOld'), window('a', 10)])
    clock = Clock()
    remaining = workspace.close_windows(kwin, keep=set(), clock=clock, sleep=clock.sleep, unaskable={'xold'})
    assert kwin.asked == ['a'] and remaining[0]['app'] == 'XOld' and 'not_asked' in remaining[0]


# covers: agent.workspace-lifecycle/E4
def test_x11_windows_are_read_with_xprop():
    replies = {
        ('-root', '_NET_CLIENT_LIST'): '_NET_CLIENT_LIST(WINDOW): window id # 0x200001, 0x400003, 0x600005\n',
        ('-id', '0x200001'): 'WM_PROTOCOLS(ATOM): protocols  WM_DELETE_WINDOW, _NET_WM_PING\n_NET_WM_PID(CARDINAL) = 30\n',
        ('-id', '0x400003'): 'WM_PROTOCOLS:  not found.\n_NET_WM_PID(CARDINAL) = 31\n',
        ('-id', '0x600005'): 'WM_PROTOCOLS:  not found.\n_NET_WM_PID:  not found.\nWM_CLASS(STRING) = "xold", "XOld"\n',
    }

    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, replies[tuple(args[1:3])], '')
    with mock.patch.dict(workspace.os.environ, {'DISPLAY': ':1'}):
        assert workspace.x11_without_close(run) == {31, 'xold'}
    with mock.patch.dict(workspace.os.environ, {}, clear=True):
        assert workspace.x11_without_close(run) == set()


def runner(active=True, close_windows=None):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[:3] == ['systemctl', '--user', 'is-active']:
            return subprocess.CompletedProcess(args, 0 if active else 3, '', '')
        if args[0] == 'rungic-workspace-env':
            return subprocess.CompletedProcess(args, 0, json.dumps({'remaining': close_windows or []}), '')
        return subprocess.CompletedProcess(args, 0, '', '')
    return run, calls


def stops(calls):
    return [c[3] for c in calls if c[:3] == ['systemctl', '--user', 'stop']]


# covers: agent.workspace-lifecycle/E2
def test_a_workspace_that_is_not_running_is_closed():
    run, calls = runner(active=False)
    assert workspace.close(1, run=run) == {'closed': True, 'was_running': False}
    assert stops(calls) == []


# covers: agent.workspace-lifecycle/E2
def test_closing_gives_switched_apps_back_then_closes_windows_then_stops():
    run, calls = runner()
    with mock.patch.object(workspace, 'ready', return_value=True):
        result = workspace.close(1, run=run)
    assert result == {'closed': True, 'was_running': True}
    order = [c[0] if c[0] != 'systemctl' else f'{c[2]} {c[-1]}' for c in calls]
    assert order == ['is-active rungic-workspace@1.service', 'rungic-cua', 'rungic-workspace-env',
                     'stop rungic-workspace@1.service', 'stop app-rungic-ws1-*.scope']
    assert calls[-1][3:] == ['app-rungicws1.slice', 'app-rungic-ws1-*.scope']
    assert calls[1] == ['rungic-cua', 'restore-apps', '1']
    assert calls[2][:5] == ['rungic-workspace-env', '1', 'rungic-cua', 'close-windows', '20.0']


# covers: agent.workspace-lifecycle/E2
def test_an_open_app_keeps_the_workspace_unless_forced():
    still = [{'caption': 'Save changes?', 'app': 'ardour', 'pid': 10, 'dialog': True}]
    run, calls = runner(close_windows=still)
    with mock.patch.object(workspace, 'ready', return_value=True):
        result = workspace.close(1, run=run)
    assert result['closed'] is False and result['remaining'] == still
    assert stops(calls) == []
    run, calls = runner(close_windows=still)
    with mock.patch.object(workspace, 'ready', return_value=True):
        result = workspace.close(1, force=True, run=run)
    assert result == {'closed': True, 'was_running': True, 'closed_unsaved': still}
    assert stops(calls) == ['rungic-workspace@1.service', 'app-rungicws1.slice']


class FakeChild:
    def __init__(self, env):
        self.env = env
        self.closed = False

    def alive(self):
        return not self.closed

    def request(self, method, params):
        return {'content': [{'type': 'text', 'text': '{}'}]}

    def close(self):
        self.closed = True


ENV = {'WAYLAND_DISPLAY': 'wayland-ws-1', 'RUNGIC_WORKSPACE': '1', 'XDG_RUNTIME_DIR': '/run/user/1000',
       'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/tmp/ws-bus', 'RUNGIC_USER_WAYLAND_DISPLAY': 'wayland-0',
       'RUNGIC_USER_DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus'}


# covers: agent.workspace-lifecycle/E1
def test_the_agent_closes_its_workspace_and_the_next_call_starts_it_again():
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}), \
            mock.patch.object(workspace, 'ensure', return_value=True) as ensure, \
            mock.patch.object(workspace, 'close', return_value={'closed': True, 'was_running': True}) as close:
        r = router.Router(ENV)
        r.call('desktop_windows', {})
        first = r.children['workspace']
        result = r.call('desktop_close_workspace', {'force': True})
        assert json.loads(result['content'][0]['text'])['closed'] is True
        close.assert_called_once_with(1, force=True)
        assert first.closed and 'workspace' not in r.children
        r.call('desktop_windows', {})
        assert r.children['workspace'] is not first and ensure.call_count == 2


# covers: agent.workspaces/E3
def test_a_workspace_that_does_not_start_is_an_error():
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}), \
            mock.patch.object(workspace, 'ensure', return_value=False):
        r = router.Router(ENV)
        try:
            r.call('desktop_windows', {})
        except RuntimeError as error:
            assert 'did not start' in str(error)
        else:
            raise AssertionError('no error')


# covers: agent.workspace-lifecycle/E1
def test_a_frozen_workspace_is_thawed_before_a_tool_reaches_it():
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}), \
            mock.patch.object(workspace, 'ensure', return_value=True), \
            mock.patch.object(workspace, 'thaw', return_value=True) as thaw:
        router.Router(ENV).call('desktop_windows', {})
    thaw.assert_called_once_with(1)
    # Desktop mode on is the independent desktop running (docs/research/97 §19), not the app's switch.
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'desktop_running', return_value=True), \
            mock.patch.object(router, 'workspace_env', side_effect=lambda env, slot: dict(env)), \
            mock.patch.object(workspace, 'thaw') as thaw:
        router.Router(ENV).call('desktop_windows', {})      # on the user's desktop: nothing to thaw
    thaw.assert_not_called()


# covers: agent.workspace-lifecycle/E5
def test_closing_thaws_first():
    run, calls = runner()
    with mock.patch.object(workspace, 'ready', return_value=True), \
            mock.patch.object(workspace, 'thaw') as thaw:
        workspace.close(1, run=run)
    assert thaw.call_count == 2           # at the start, and again right before the stop


# covers: agent.workspace-lifecycle/E5
def test_the_keeper_is_told_while_a_workspace_closes(tmp_path):
    run, calls = runner()
    seen = []
    with mock.patch.dict(workspace.os.environ, {'XDG_RUNTIME_DIR': str(tmp_path)}), \
            mock.patch.object(workspace, 'ready', return_value=True), \
            mock.patch.object(workspace, 'thaw', side_effect=lambda *a: seen.append(workspace.closing_marker(1).exists())):
        workspace.close(1, run=run)
        assert not workspace.closing_marker(1).exists()
    assert seen == [True, True]          # thawed at the start and right before the stop, the marker there


# ---- the phone asleep: the Rungic app frozen (docs/research/97) -------------------------------------
# covers: agent.workspaces/E3
def test_a_start_that_failed_ends_the_wait_at_once_and_says_why(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    started = []

    def run(argv, **kwargs):
        started.append(argv)
        workspace.failure_path(3).write_text('the Android host is not responding\n')
        return subprocess.CompletedProcess(argv, 0, '', '')
    with mock.patch.object(workspace, 'ready', return_value=False):
        assert workspace.ensure(3, wait=30, run=run) is False
    assert started and workspace.failure(3) == 'the Android host is not responding'


# covers: agent.workspaces/E3
def test_the_agent_hears_why_its_workspace_did_not_start(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    workspace.failure_path(1).write_text('the Android host is not responding')
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}), \
            mock.patch.object(workspace, 'ensure', return_value=False):
        r = router.Router(ENV)
        try:
            r.call('desktop_windows', {})
        except RuntimeError as error:
            assert 'not responding' in str(error)
        else:
            raise AssertionError('no error')
