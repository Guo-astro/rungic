"""A team's journal (docs/research/91, "实时看到团队讨论"): what its agents say, in plain text.

Codex keeps the messages between a lead and its sub-agents encrypted: nobody but the model reads
them. So every agent of a team says what matters itself, through the desktop tools' `team_post`:
its review of the brief, the lead's decisions, progress, a blocker, a question, done. Each post is

  {"time": 1790000000.0, "role": "art", "kind": "review", "text": "…", "workspace": 3,
   "thread": "…", "parent": "…"}

appended to <project>/.team/journal.jsonl (the team's record, kept with its work) and, for a member
with a workspace, its latest state written to <runtime>/rungic-agent-screen/team-wsN.json and told to
the Android app: the director's tiles show the member's role, state and latest words (phone and TV).
An agent that ends without saying done, blocked or failed gets "ended" posted for it.
"""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

KINDS = ('brief', 'review', 'decision', 'progress', 'blocked', 'question', 'done', 'failed', 'ended')
FINAL = ('done', 'blocked', 'failed', 'ended')
TEXT_MAX = 80

TOOL = {
    'name': 'team_post',
    'description': ("Working in a team (the rungic-agent-team skill): tell the user and the team, in one short "
                    "sentence in the user's language (at most 80 characters), what matters now. kind: 'brief' the lead's "
                    "brief is written; 'review' a member's review of the brief (one post with its main point and how many "
                    "points); 'decision' the lead's decisions (what was accepted or rejected); 'progress' a step of the "
                    "work done (at most every half minute); 'blocked' cannot go on, and why; 'question' needs an answer; "
                    "'done' the part is finished (what was made). role: your role in the team (e.g. 'art', 'lead'); "
                    "project: the team's folder. The user watches these live on the screens and the TV."),
    'inputSchema': {'type': 'object', 'required': ['role', 'kind', 'text'], 'properties': {
        'role': {'type': 'string'}, 'kind': {'type': 'string', 'enum': [k for k in KINDS if k != 'ended']},
        'text': {'type': 'string'}, 'project': {'type': 'string'}}},
    'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False},
}


def _runtime() -> Path:
    return Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')


def state_path(slot) -> Path:
    return _runtime() / 'rungic-agent-screen' / f'team-ws{slot}.json'


def post(entry: dict, project: str = '') -> dict:
    """Append `entry` to the project's journal, show it on the member's tile. Never raises."""
    entry = {**entry, 'time': entry.get('time') or time.time(),
             'text': ' '.join(str(entry.get('text', '')).split())[:TEXT_MAX]}
    written = None
    if project:
        try:
            journal = Path(project).expanduser() / '.team' / 'journal.jsonl'
            journal.parent.mkdir(parents=True, exist_ok=True)
            with journal.open('a') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            written = str(journal)
        except OSError:
            pass
    slot = entry.get('workspace')
    if slot:
        try:
            target = state_path(slot)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(entry, ensure_ascii=False))
            os.replace(temporary, target)
        except OSError:
            pass
        tell_app(int(slot), entry)
    return {'posted': True, 'journal': written}


def tell_app(slot: int, entry: dict) -> None:
    """The member's state to the Android app, for the director's tiles it draws (best effort)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(0.5)
            conn.connect('/mnt/android-wayland/platform.sock')
            member = {'slot': slot, 'role': entry.get('role', ''), 'kind': entry.get('kind', ''), 'text': entry.get('text', '')}
            conn.sendall(json.dumps({'op': 'director', 'member': member}, ensure_ascii=False).encode() + b'\n')
            conn.recv(4096)
    except (OSError, ValueError):
        pass


def clear(slot) -> None:
    """The workspace is given back: its tile no longer names a member."""
    try:
        state_path(slot).unlink(missing_ok=True)
    except OSError:
        pass
    tell_app(int(slot), {'role': '', 'kind': '', 'text': ''})
