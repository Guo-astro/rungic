"""rungic_cua.router (docs/research/91): where the agent's desktop tools act.

The platform bridge and the per-session children are stand-ins: nothing starts."""
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'agent/computer-use'))
from rungic_cua import router  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def workspace_up():
    """The workspace counts as running (workspace.ensure would start it)."""
    with mock.patch.object(router.workspace, 'ensure', return_value=True):
        yield


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



def test_the_users_session_gets_its_own_values_back():
    """The workspace sets these as Plasma's desktop session has them (docs/103); the user's session
    gets its own values back, and loses one it never had."""
    workspace = {'WAYLAND_DISPLAY': 'wayland-ws-1', 'RUNGIC_WORKSPACE': '1', 'PLASMA_INTEGRATION_USE_PORTAL': '0',
                 'QT_QPA_PLATFORMTHEME': ''}
    env = router.user_session_env({**workspace, 'RUNGIC_USER_PLASMA_INTEGRATION_USE_PORTAL': '1',
                                   'RUNGIC_USER_QT_QPA_PLATFORMTHEME': 'KDE'})
    assert (env['PLASMA_INTEGRATION_USE_PORTAL'], env['QT_QPA_PLATFORMTHEME']) == ('1', 'KDE')
    assert not any(k.startswith('RUNGIC_USER_') for k in env)
    env = router.user_session_env(workspace)
    assert 'PLASMA_INTEGRATION_USE_PORTAL' not in env and 'QT_QPA_PLATFORMTHEME' not in env


# ---- a sub-agent's own workspace (docs/research/91, "由 Codex 当组长") -----------------------------
SUBAGENT_META = {'threadId': 'child-a', 'x-codex-turn-metadata': {
    'thread_source': 'subagent', 'thread_id': 'child-a', 'parent_thread_id': 'parent'}}
PARENT_META = {'threadId': 'parent', 'x-codex-turn-metadata': {'thread_source': 'user', 'thread_id': 'parent'}}


@pytest.fixture
def host(tmp_path, monkeypatch):
    """Four host workspaces, claims in a temporary runtime directory, none running."""
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setattr(router.workspace, 'slots', lambda: [1, 2, 3, 4])
    monkeypatch.setattr(router.workspace, 'running', lambda slot, run=None: False)
    monkeypatch.setattr(router, 'workspace_env',
                        lambda env, slot: {**env, 'RUNGIC_WORKSPACE': str(slot), 'WAYLAND_DISPLAY': f'wayland-ws-{slot}'})
    return tmp_path


def sub_router(meta=SUBAGENT_META):
    r = router.Router(WORKSPACE_ENV)
    return r, json.loads(r.call('desktop_where', {}, meta)['content'][-1]['text'])


def test_a_subagent_takes_a_workspace_of_its_own(host):
    FakeChild.made.clear()
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': True, 'tv': False}):
        r, note = sub_router()
        # Not the parent's (1), and not the user's desktop although desktop mode is on.
        assert note['where'] == 'workspace' and note['workspace'] == 2
        assert note['shell'] == 'rungic-workspace-env 2 COMMAND' and 'yours' in note
        r.call('desktop_launch', {'app': 'Krita'}, SUBAGENT_META)
    assert FakeChild.made[-1].env['RUNGIC_WORKSPACE'] == '2'
    record = json.loads((host / 'rungic-workspace-2.busy').read_text())
    assert record['thread'] == 'child-a' and record['parent'] == 'parent' and record['pid'] > 0


def test_subagents_get_different_workspaces_and_the_parent_keeps_its_own(host):
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}):
        _, a = sub_router()
        # Another process's claim: workspace 2 is held while that process lives.
        (host / 'rungic-workspace-2.busy').write_text(json.dumps({'pid': 1}))
        _, b = sub_router()
        _, parent = sub_router(PARENT_META)
    assert (a['workspace'], b['workspace'], parent['workspace']) == (2, 3, 1)
    assert 'yours' not in parent


def test_a_claim_of_an_ended_process_is_free_again(host):
    (host / 'rungic-workspace-2.busy').write_text(json.dumps({'pid': 999999999}))
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}):
        _, note = sub_router()
    assert note['workspace'] == 2


def test_closing_gives_the_workspace_back(host):
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}), \
            mock.patch.object(router.workspace, 'close', return_value={'closed': True}) as close:
        r, note = sub_router()
        r.call('desktop_close_workspace', {}, SUBAGENT_META)
    close.assert_called_once_with(2, force=False)
    assert not (host / 'rungic-workspace-2.busy').exists()


def test_all_taken(host):
    for slot in (2, 3, 4):
        (host / f'rungic-workspace-{slot}.busy').write_text('')     # runners' claims (tools/team)
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}):
        r = router.Router(WORKSPACE_ENV)
        with pytest.raises(RuntimeError, match='every agent workspace is taken'):
            r.call('desktop_launch', {'app': 'Krita'}, SUBAGENT_META)


# ---- the team journal (team.py, docs/research/91 "实时看到团队讨论") --------------------------------
def test_a_members_post_goes_to_the_journal_and_its_tile(host, tmp_path, monkeypatch):
    told = []
    monkeypatch.setattr(router.team, 'tell_app', lambda slot, entry: told.append((slot, entry['kind'])))
    project = tmp_path / 'game'
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}):
        r = router.Router(WORKSPACE_ENV)
        r.call('team_post', {'role': 'art', 'kind': 'review', 'text': 'Style is missing: pixel art?',
                             'project': str(project)}, SUBAGENT_META)
        r.call('team_post', {'role': 'art', 'kind': 'progress', 'text': 'Bird drawn'}, SUBAGENT_META)
    lines = [json.loads(line) for line in (project / '.team/journal.jsonl').read_text().splitlines()]
    assert [(e['role'], e['kind'], e['workspace']) for e in lines] == [('art', 'review', 2), ('art', 'progress', 2)]
    assert lines[0]['parent'] == 'parent'
    tile = json.loads((host / 'rungic-agent-screen/team-ws2.json').read_text())
    assert tile['text'] == 'Bird drawn' and told == [(2, 'review'), (2, 'progress')]


def test_a_member_ending_silent_gets_ended(host, tmp_path, monkeypatch):
    monkeypatch.setattr(router.team, 'tell_app', lambda slot, entry: None)
    project = tmp_path / 'game'
    with mock.patch.object(router, 'Child', FakeChild), \
            mock.patch.object(router, 'bridge', return_value={'enabled': False, 'tv': False}):
        r = router.Router(WORKSPACE_ENV)
        r.call('team_post', {'role': 'sound', 'kind': 'progress', 'text': 'Seeds made', 'project': str(project)},
               SUBAGENT_META)
        r.close()
    kinds = [json.loads(line)['kind'] for line in (project / '.team/journal.jsonl').read_text().splitlines()]
    assert kinds == ['progress', 'ended']


def test_the_leads_post_has_no_tile(host, tmp_path, monkeypatch):
    monkeypatch.setattr(router.team, 'tell_app', lambda slot, entry: (_ for _ in ()).throw(AssertionError('no tile')))
    project = tmp_path / 'game'
    with mock.patch.object(router, 'Child', FakeChild):
        r = router.Router(WORKSPACE_ENV)
        r.call('team_post', {'role': 'lead', 'kind': 'decision', 'text': 'Pixel art, 3 frames', 'project': str(project)},
               PARENT_META)
    entry = json.loads((project / '.team/journal.jsonl').read_text())
    assert entry['kind'] == 'decision' and 'workspace' not in entry
