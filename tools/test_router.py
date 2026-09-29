"""rungic_cua.router (docs/research/91): where the agent's desktop tools act.

The platform bridge and the per-session children are stand-ins: nothing starts."""
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'plasma/cua'))
from rungic_cua import router  # noqa: E402


class FakeChild:
    made = []

    def __init__(self, env):
        self.env = env
        self.calls = []
        FakeChild.made.append(self)

    def alive(self):
        return True

    def request(self, method, params):
        self.calls.append(params['name'])
        return {'content': [{'type': 'text', 'text': '{}'}]}

    def close(self):
        pass


WORKSPACE_ENV = {'WAYLAND_DISPLAY': 'wayland-ws-1', 'RUNGIC_WORKSPACE': '1', 'DISPLAY': ':0',
                 'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/tmp/ws-bus', 'XDG_RUNTIME_DIR': '/run/user/1000',
                 'RUNGIC_USER_WAYLAND_DISPLAY': 'wayland-0',
                 'RUNGIC_USER_DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus'}


def routed(desktop_state, name='desktop_launch', setting=None):
    FakeChild.made.clear()
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value=desktop_state):
        r = router.Router(WORKSPACE_ENV)
        told = r.call('desktop_where', {'target': setting}) if setting else None
        result = r.call(name, {'app': 'Kalk'})
    # desktop_where already said where; the next call adds nothing then.
    note = json.loads((told or result)['content'][-1]['text'])
    return FakeChild.made[-1], note


def test_desktop_mode_on_works_on_the_users_desktop():
    child, note = routed({'enabled': True, 'tv': False})
    assert note['where'] == 'desktop' and 'desktop mode is on' in note['why']
    assert child.env['WAYLAND_DISPLAY'] == 'wayland-0'
    assert child.env['DBUS_SESSION_BUS_ADDRESS'] == 'unix:path=/run/user/1000/bus'
    assert 'RUNGIC_WORKSPACE' not in child.env and 'DISPLAY' not in child.env


def test_a_tv_showing_the_desktop_works_there():
    _, note = routed({'enabled': False, 'tv': True})
    assert note['where'] == 'desktop' and 'TV' in note['why']


def test_otherwise_its_own_workspace():
    child, note = routed({'enabled': False, 'tv': False})
    assert note['where'] == 'workspace'
    assert child.env['WAYLAND_DISPLAY'] == 'wayland-ws-1' and child.env['RUNGIC_WORKSPACE'] == '1'


def test_the_users_word_wins():
    child, note = routed({'enabled': True, 'tv': False}, setting='workspace')
    assert note['where'] == 'workspace' and note['why'] == 'the user said so'
    assert child.env['WAYLAND_DISPLAY'] == 'wayland-ws-1'
    child, note = routed({'enabled': False, 'tv': False}, setting='desktop')
    assert note['where'] == 'desktop' and child.env['WAYLAND_DISPLAY'] == 'wayland-0'


def test_no_bridge_means_the_workspace():
    FakeChild.made.clear()
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', side_effect=OSError('no socket')):
        r = router.Router(WORKSPACE_ENV)
        assert r.where()[0] == 'workspace'


def test_the_where_note_comes_only_when_it_changes():
    FakeChild.made.clear()
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}):
        r = router.Router(WORKSPACE_ENV)
        first = r.call('desktop_screenshot', {})
        second = r.call('desktop_screenshot', {})
    assert len(first['content']) == 2 and len(second['content']) == 1
