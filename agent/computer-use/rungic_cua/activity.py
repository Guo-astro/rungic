"""What the assistant is doing on its screen, for whoever shows it (docs/88).

One small JSON file per screen in the runtime directory, replaced atomically on every change:
activity.json for the user's desktop, activity-wsN.json for agent workspace N (docs/research/91: each
workspace's floating window shows its own agent's work). The writer's RUNGIC_WORKSPACE picks it.

  {"state": "working" | "done" | "question" | "failed" | "stopped",
   "text": "Open the Render menu",  what is happening now (a caption, in the desktop's language)
   "task": "...",                   the task it is part of, if any
   "image": "/run/user/…/x.jpg",    optional: a live picture of the work (a render's latest pass, docs/90)
   "progress": 0.44,                optional: how far, 0..1
   "time": 1790000000.0}            when it was written (seconds since the epoch)

The assistant screen's floating window shows `text` as a caption over the picture while
"working", and the outcome for a moment after; the voice agent speaks it as progress. A
workspace's report also goes to the Android app (platform bridge op "director", `caption`): the
director's tiles on the TV and fullscreen, which the app draws, show it as well (docs/58). A
"working" state older than STALE_S means the writer went away (a tool call killed with Codex).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .i18n import _

STALE_S = 120
DIR = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}') / 'rungic-agent-screen'


def path(workspace=None) -> Path:
    """The file for workspace N (default: this process's RUNGIC_WORKSPACE), or the user's desktop's."""
    slot = os.environ.get('RUNGIC_WORKSPACE') if workspace is None else workspace
    return DIR / (f'activity-ws{slot}.json' if slot else 'activity.json')


def report(text: str, *, state: str = 'working', task: str = '', image: str = '', progress: float | None = None,
           workspace=None) -> None:
    """Say what is happening now. Never fails the caller: the caption is a courtesy."""
    target = path(workspace)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {'state': state, 'text': ' '.join(str(text).split())[:80], 'task': ' '.join(str(task).split())[:120],
                'time': time.time()}
        if image:
            data['image'] = str(image)
        if progress is not None:
            data['progress'] = max(0.0, min(1.0, float(progress)))
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False))
        os.replace(temporary, target)
    except OSError:
        pass
    slot = os.environ.get('RUNGIC_WORKSPACE') if workspace is None else workspace
    if slot:
        tell_app(int(slot), state, data['text'] if 'data' in locals() else str(text)[:80])


def tell_app(slot: int, state: str, text: str) -> None:
    """The caption to the Android app, for the director's tiles it draws (best effort, quick)."""
    import socket
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(0.5)
            conn.connect(os.environ.get('RUNGIC_PLATFORM_SOCKET', '/mnt/android-wayland/platform.sock'))
            conn.sendall(json.dumps({'op': 'director', 'caption': {'slot': slot, 'state': state, 'text': text}},
                                    ensure_ascii=False).encode() + b'\n')
            conn.recv(4096)
    except (OSError, ValueError):
        pass


def read(workspace=None) -> dict:
    """The latest report, or {} when there is none or it went stale."""
    try:
        data = json.loads(path(workspace).read_text())
    except (OSError, ValueError):
        return {}
    if data.get('state') == 'working' and time.time() - float(data.get('time') or 0) > STALE_S:
        return {}
    return data


def describe(action: dict) -> str:
    """A caption for one computer-use action when the model gave none (desktop's language)."""
    kind = action.get('type')
    if kind == 'type':
        text = ' '.join(str(action.get('text', '')).split())
        return _('Type “{text}”').format(text=text[:24] + ('…' if len(text) > 24 else ''))
    if kind == 'keypress':
        keys = '+'.join(str(k).upper() for k in action.get('keys') or [])
        named = {'ENTER': _('Press Enter'), 'ESCAPE': _('Press Esc'), 'TAB': _('Press Tab')}
        return named.get(keys) or _('Press {keys}').format(keys=keys)
    return {'click': _('Click'), 'double_click': _('Double-click'), 'drag': _('Drag'), 'move': _('Move the pointer'),
            'scroll': _('Scroll the page'), 'wait': _('Wait for the screen to update'),
            'screenshot': _('Look at the screen')}.get(kind) or _('Operate the screen')
