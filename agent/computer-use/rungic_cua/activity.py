"""What the assistant is doing on its screen, for whoever shows it (docs/88).

One small JSON file in the runtime directory, replaced atomically on every change:

  {"state": "working" | "done" | "question" | "failed" | "stopped",
   "text": "Open the Render menu",  what is happening now (a caption, in the desktop's language)
   "task": "...",                   the task it is part of, if any
   "image": "/run/user/…/x.jpg",    optional: a live picture of the work (a render's latest pass, docs/90)
   "progress": 0.44,                optional: how far, 0..1
   "time": 1790000000.0}            when it was written (seconds since the epoch)

The assistant screen's floating window shows `text` as a caption over the picture while
"working", and the outcome for a moment after; the voice agent speaks it as progress. A
"working" state older than STALE_S means the writer went away (a tool call killed with Codex).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .i18n import _

STALE_S = 120
PATH = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}') / 'rungic-agent-screen' / 'activity.json'


def report(text: str, *, state: str = 'working', task: str = '', image: str = '', progress: float | None = None) -> None:
    """Say what is happening now. Never fails the caller: the caption is a courtesy."""
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {'state': state, 'text': ' '.join(str(text).split())[:80], 'task': ' '.join(str(task).split())[:120],
                'time': time.time()}
        if image:
            data['image'] = str(image)
        if progress is not None:
            data['progress'] = max(0.0, min(1.0, float(progress)))
        temporary = PATH.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False))
        os.replace(temporary, PATH)
    except OSError:
        pass


def read() -> dict:
    """The latest report, or {} when there is none or it went stale."""
    try:
        data = json.loads(PATH.read_text())
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
