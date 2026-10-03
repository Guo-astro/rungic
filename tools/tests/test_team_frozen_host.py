#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""A team goes on while the Rungic app is frozen (the phone asleep, docs/research/97): the platform
bridge's socket takes connections and never answers, as Motorola's freezer leaves it. A lead and two
members go through a whole team with the real router, team journal and board: none of their calls
waits on the app for long, each member works in a workspace of its own (never the user's desktop),
the journal and the board follow the team to the end, and the workspaces are given back.

What only the phone shows (the workspaces' KWin running headless while the app is frozen: the system
test workspace_headless; Android's network and the wakelock while the screen is off) is not here.
The members' sessions are stand-ins (no child processes start)."""
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'agent/computer-use'))
from rungic_cua import router  # noqa: E402

PARENT = {'threadId': 'lead', 'x-codex-turn-metadata': {'thread_source': 'user', 'thread_id': 'lead'}}


def member(thread):
    return {'threadId': thread, 'x-codex-turn-metadata': {
        'thread_source': 'subagent', 'thread_id': thread, 'parent_thread_id': 'lead'}}


class Child:
    """A session's desktop tools (rungic-cua in the workspace): answers at once."""
    made = []

    def __init__(self, env):
        self.env = env
        Child.made.append(self)

    def alive(self):
        return True

    def request(self, method, params):
        return {'content': [{'type': 'text', 'text': '{}'}]}

    def close(self):
        pass


class FrozenHostTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rungic-team-frozen-')
        tmp = Path(self.tmp.name)
        self.runtime = tmp / 'runtime'
        self.runtime.mkdir()
        self.project = tmp / 'picnic'
        # The frozen app: its socket listens, nothing is ever accepted or answered.
        self.socket_path = str(tmp / 'platform.sock')
        self.frozen = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.frozen.bind(self.socket_path)
        self.frozen.listen(64)
        self.popen = mock.MagicMock()
        self.patches = [
            mock.patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.runtime), RUNGIC_PLATFORM_SOCKET=self.socket_path),
            mock.patch.object(router, 'PLATFORM', self.socket_path),
            mock.patch.object(router, 'Child', Child),
            mock.patch.object(router.workspace, 'slots', lambda: [1, 2, 3, 4]),
            mock.patch.object(router.workspace, 'running', lambda slot, run=None: False),
            mock.patch.object(router.workspace, 'ensure', return_value=True),   # headless: up without the app
            mock.patch.object(router.workspace, 'thaw', return_value=True),
            mock.patch.object(router.workspace, 'close', return_value={'closed': True}),
            mock.patch.object(router, 'workspace_env', lambda env, slot: {**env, 'RUNGIC_WORKSPACE': str(slot)}),
            mock.patch.object(router.team, 'Murmur', mock.MagicMock()),
            mock.patch.object(router.team.subprocess, 'Popen', self.popen),    # rungic-agent-screen team
        ]
        for p in self.patches:
            p.start()
        Child.made.clear()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.frozen.close()
        self.tmp.cleanup()

    def timed(self, r, name, arguments, meta, limit=2.0):
        started = time.monotonic()
        result = r.call(name, arguments, meta)
        took = time.monotonic() - started
        self.assertLess(took, limit, f'{name} waited {took:.1f} s on the frozen app')
        return result

    # covers: agent.team/E6
    def test_a_team_goes_on_while_the_app_is_frozen(self):
        env = {'RUNGIC_WORKSPACE': '1', 'XDG_RUNTIME_DIR': str(self.runtime)}
        lead = router.Router(env)
        # The lead asks where it works: the app does not answer (one wait of the bridge's timeout),
        # so it works in its own workspace, not on the user's desktop.
        where = json.loads(self.timed(lead, 'desktop_where', {}, PARENT, limit=4.0)['content'][-1]['text'])
        self.assertEqual((where['where'], where['workspace']), ('workspace', 1))
        project = str(self.project)
        self.timed(lead, 'team_post', {'role': 'lead', 'kind': 'brief', 'text': 'Picnic card', 'project': project}, PARENT)
        art, sound = router.Router(env), router.Router(env)
        for r, role, thread in ((art, 'art', 'm-art'), (sound, 'sound', 'm-sound')):
            self.timed(r, 'team_post', {'role': role, 'kind': 'review', 'text': f'{role}: 2 points', 'project': project},
                       member(thread))
        self.timed(lead, 'team_post', {'role': 'lead', 'kind': 'decision', 'text': 'Accepted 3 of 4'}, PARENT)
        for r, role, thread in ((art, 'art', 'm-art'), (sound, 'sound', 'm-sound')):
            self.timed(r, 'desktop_launch', {'app': 'Krita'}, member(thread))
            self.timed(r, 'team_post', {'role': role, 'kind': 'done', 'text': f'{role} made'}, member(thread))
            closed = json.loads(self.timed(r, 'desktop_close_workspace', {}, member(thread))['content'][0]['text'])
            self.assertTrue(closed['closed'])
            r.close()
        self.timed(lead, 'team_post', {'role': 'lead', 'kind': 'done', 'text': 'Card handed over'}, PARENT)
        lead.close()

        # Each member in a workspace of its own, none on the user's desktop (workspace 0) or the lead's.
        slots = sorted(int(c.env['RUNGIC_WORKSPACE']) for c in Child.made)
        self.assertEqual(slots, [2, 3])
        journal = [json.loads(line) for line in (self.project / '.team/journal.jsonl').read_text().splitlines()]
        self.assertEqual([(e['role'], e['kind']) for e in journal],
                         [('lead', 'brief'), ('art', 'review'), ('sound', 'review'), ('lead', 'decision'),
                          ('art', 'done'), ('sound', 'done'), ('lead', 'done')])
        board = json.loads((self.runtime / 'rungic-agent-screen/team-board.json').read_text())
        self.assertEqual(board['phase'], 'done')
        self.assertEqual(board['result'], 'Card handed over')
        # The workspaces are given back: another team could take them.
        self.assertEqual([p.name for p in self.runtime.glob('rungic-workspace-*.busy')], [])


if __name__ == '__main__':
    unittest.main()
