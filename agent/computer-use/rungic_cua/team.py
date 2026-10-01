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


def update_state(entry: dict) -> None:
    """A member's state changed without words (inferred, e.g. at work after its review): its tile
    only, not the journal."""
    slot = entry.get('workspace')
    if not slot:
        return
    try:
        target = state_path(slot)
        previous = json.loads(target.read_text()) if target.exists() else {}
        merged = {**previous, **entry, 'text': previous.get('text', '')}
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(merged, ensure_ascii=False))
        os.replace(temporary, target)
    except (OSError, ValueError):
        pass
    tell_app(int(slot), {**entry, 'text': ''})


# ---- the murmur: what an agent is doing, from its own session log ------------------------------
# Codex writes each thread's items to ~/.codex/sessions/YYYY/MM/DD/rollout-…-<thread>.jsonl as they
# happen. The words between agents are encrypted there, the tool calls are not: each one becomes a
# short line on the agent's tile (activity.report), so a member at work in its shell (writing a
# script, running it) is seen at work too, not only its desktop actions.
import re as _re
import threading as _threading

from . import activity as _activity
from .i18n import _

_CALL = _re.compile(r'tools\.([A-Za-z0-9_]+)\(\s*\{')
_FIELD = r'{key}\s*:\s*"((?:[^"\\]|\\.)*)"'
MURMUR_EVERY_S = 1.5


def _field(source: str, key: str, start: int = 0) -> str:
    found = _re.compile(_FIELD.format(key=key)).search(source, start)
    if not found:
        return ''
    try:
        return json.loads('"' + found.group(1) + '"')
    except ValueError:
        return found.group(1)


def _name(path: str) -> str:
    return os.path.basename(path.strip().strip('\'"').rstrip('/')) or path


def describe_command(command: str) -> str:
    """A shell command as a few words: what it does to which file."""
    line = command.strip().splitlines()[0] if command.strip() else ''
    words = line.split()
    while words and ('=' in words[0] and not words[0].startswith('-')):
        words = words[1:]                                   # VAR=value prefixes
    if len(words) > 2 and words[0] == 'rungic-workspace-env':
        words = words[2:]
    if not words:
        return ''
    program = _name(words[0])
    rest = [w for w in words[1:] if not w.startswith('-')]
    written = _re.search(r'(?:cat|tee)\s+>{0,2}\s*([^\s<>|;&]+)', line) if ('>' in line or program == 'tee') else None
    if program == 'cat' and '>' in line:
        written = _re.search(r'>\s*([^\s<>|;&]+)', line)
    if written:
        return _('Write {name}').format(name=_name(written.group(1)))
    if program in ('cat', 'sed', 'head', 'tail', 'less', 'jq', 'grep', 'rg') and rest:
        return _('Read {name}').format(name=_name(rest[-1]))
    if program.startswith('python') or program in ('node', 'bash', 'sh'):
        script = next((w for w in rest if not w.startswith('<')), '')
        return _('Run {name}').format(name=_name(script)) if script and script != '-' else _('Run a script')
    if program in ('mkdir',):
        return _('Make the folder {name}').format(name=_name(rest[-1])) if rest else ''
    if program in ('ls', 'find', 'tree', 'stat', 'file'):
        return _('Look at the files')
    if program in ('ffmpeg', 'ffprobe', 'sox'):
        return _('Process the audio with {tool}').format(tool=program)
    if program in ('cp', 'mv', 'ln'):
        return _('Copy {name}').format(name=_name(rest[-1])) if rest else ''
    return _('Run {name}').format(name=program)


def describe_call(name: str, arguments: str) -> list[str]:
    """Lines for one logged tool call (code mode's `exec` holds several `tools.x({...})`)."""
    out = []
    if name == 'exec':
        for found in _CALL.finditer(arguments):
            tool, at = found.group(1), found.end()
            if tool == 'exec_command':
                out.append(describe_command(_field(arguments, 'cmd', at)))
            elif tool.endswith('desktop_goal'):
                out.append(_field(arguments, 'goal', at))
            elif tool.endswith('desktop_launch'):
                out.append(_('Open {app}').format(app=_field(arguments, 'app', at) or _('an app')))
            elif tool.endswith('desktop_screenshot'):
                out.append(_('Look at the screen'))
            elif tool.endswith('desktop_windows'):
                out.append(_('Look at the windows'))
    elif name == 'exec_command':
        try:
            out.append(describe_command(json.loads(arguments).get('cmd', '')))
        except (ValueError, AttributeError):
            pass
    elif name == 'send_message':
        out.append(_('Report to the lead'))
    elif name == 'spawn_agent':
        out.append(_('Start a team member'))
    return [' '.join(line.split())[:TEXT_MAX] for line in out if line]


class Murmur:
    """Follow thread `thread`'s session log; say each new tool call on workspace `slot`'s tile."""

    def __init__(self, thread: str, slot: int) -> None:
        self.thread, self.slot = thread, slot
        self.stop = _threading.Event()
        self.pending = ''
        self.last_said = 0.0
        _threading.Thread(target=self.follow, daemon=True, name=f'murmur-{slot}').start()

    def log(self) -> Path | None:
        home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'sessions'
        found = sorted(home.glob(f'*/*/*/rollout-*-{self.thread}.jsonl'))
        return found[-1] if found else None

    def follow(self) -> None:
        path = None
        while not self.stop.is_set() and path is None:
            path = self.log()
            if path is None:
                self.stop.wait(2)
        if path is None:
            return
        with path.open() as f:
            f.seek(0, os.SEEK_END)               # what happens from now
            while not self.stop.is_set():
                line = f.readline()
                if not line:
                    self.flush()
                    self.stop.wait(0.5)
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                payload = entry.get('payload') or {}
                if entry.get('type') == 'response_item' and payload.get('type') in ('function_call', 'custom_tool_call'):
                    arguments = payload.get('arguments') or payload.get('input') or ''
                    for said in describe_call(payload.get('name', ''), arguments if isinstance(arguments, str) else json.dumps(arguments)):
                        self.pending = said
                    self.flush()

    def flush(self) -> None:
        """At most one line every MURMUR_EVERY_S: the latest one, the rest skipped."""
        if self.pending and time.time() - self.last_said >= MURMUR_EVERY_S:
            _activity.report(self.pending, workspace=self.slot)
            self.pending, self.last_said = '', time.time()

    def close(self) -> None:
        self.stop.set()
