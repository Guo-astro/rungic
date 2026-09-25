"""Computer use with GPT-6 Luna (docs/68): the model sees the screen and decides where to act.

Plan one of moto-cua (the default). No accessibility tree and no OCR: every step is a screenshot of
the window the task is about, as KWin renders it (with its open popups and dialogs; the whole
assistant's screen when there is no window or the model asks for it: `Screen`), sent to the
Responses API with the `computer` tool, and the model answers
with a batch of mouse and keyboard actions in that screenshot's pixels. They are carried out with
the same input as everywhere in moto-cua (the RemoteDesktop portal; text through KWin's input-method
commit, so any script types) and the next screenshot goes back, until the model stops.

API (checked 2026-09-25, developers.openai.com guides/tools-computer-use and -integration):
  tools [{"type": "computer"}]; output items `computer_call` with `actions` (click, double_click,
  drag, move, scroll, keypress, type, wait, screenshot; mouse actions may carry held `keys`);
  answered by `computer_call_output` {"type": "computer_screenshot", "image_url", "detail":
  "original"} with previous_response_id. gpt-6-luna lists computer use as supported.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from .portal import BTN_LEFT, BTN_RIGHT, KEYSYMS

logger = logging.getLogger('moto-cua.luna')
MODEL = os.environ.get('MOTO_CUA_MODEL', 'gpt-6-luna')
EFFORT = os.environ.get('MOTO_CUA_EFFORT', 'low')
API = 'https://api.openai.com/v1/responses'
KEY_FILE = Path.home() / '.config/moto-voice-agent/openai-api-key'
SCREENSHOT = os.environ.get('MOTO_SCREENSHOT', '/usr/local/libexec/moto-screenshot')
ABORT_FILE = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'moto-clicker' / 'abort'
SETTLE_S = 0.5          # after a batch, before the screenshot: animations and repaints
BTN_MIDDLE, BTN_FORWARD, BTN_BACK = 0x112, 0x115, 0x116
RAW_MODES = {4: 'BGRX', 5: 'BGRA', 6: 'BGRA', 16: 'RGBX', 17: 'RGBA', 18: 'RGBA'}   # moto-screenshot's QImage formats
KEYSYM_EXTRA = {'SUPER': 0xffeb, 'CAPSLOCK': 0xffe5, 'INSERT': 0xff63, 'PRINTSCREEN': 0xff61}
KEY_ALIASES = {
    'RETURN': 'ENTER', 'ESC': 'ESCAPE', 'CONTROL': 'CTRL', 'OPTION': 'ALT', 'META': 'SUPER', 'CMD': 'SUPER',
    'COMMAND': 'SUPER', 'WIN': 'SUPER', 'WINDOWS': 'SUPER', 'ARROWUP': 'ARROW_UP', 'ARROWDOWN': 'ARROW_DOWN',
    'ARROWLEFT': 'ARROW_LEFT', 'ARROWRIGHT': 'ARROW_RIGHT', 'UP': 'ARROW_UP', 'DOWN': 'ARROW_DOWN',
    'LEFT': 'ARROW_LEFT', 'RIGHT': 'ARROW_RIGHT', 'PAGEUP': 'PAGE_UP', 'PAGEDOWN': 'PAGE_DOWN', 'DEL': 'DELETE',
    'SPACEBAR': 'SPACE',
}

INSTRUCTIONS = """You operate a Linux desktop (KDE Plasma) for the user through the computer tool. The screen \
you see is the assistant's own screen, 1920x1080; the user watches it. Coordinates are pixels of the \
screenshot you were given.

- The screenshots show the window you work in (with its open menus and dialogs), not the whole \
screen; call view_whole_screen when you need the taskbar, the desktop or another window. The image \
size changes when the view does; always use the pixels of the latest screenshot.
- Work like a careful person: look, act, look again. Keep each batch of actions short; after anything \
that changes the screen (opening, clicking a list item, sending), look before going on.
- `type` writes the text into the focused field in any language (Chinese included); click the field \
first. Use keypress for Enter, shortcuts and navigation.
- Names of people come from speech recognition and may be written with wrong characters of the same \
sound (周凯文 for 周楷雯). Search contacts by the name's pinyin without tones or spaces (zhoukaiwen), \
then take the person whose name sounds the same. If two different people fit, or none, stop and ask.
- Do only what the task asks. Send, pay, delete or change accounts only when the task says so \
explicitly (the user has confirmed it). Never type passwords; if one is needed, stop and ask.
- When you stop, reply with one short message that begins with DONE, ASK or FAILED: DONE and what the \
screen now shows about the task; ASK and the one question only the user can answer; FAILED and why."""


class Aborted(RuntimeError):
    pass


def api_key() -> str:
    if os.environ.get('OPENAI_API_KEY'):
        return os.environ['OPENAI_API_KEY']
    return KEY_FILE.read_text().strip()


def keysym_for(name: str) -> int:
    """OpenAI key names (ENTER, CTRL, ARROWUP, a, ...) to X keysyms, for the portal."""
    if len(name) == 1:
        return ord(name.lower()) if name.isalpha() else ord(name)
    key = name.upper().replace(' ', '')
    key = KEY_ALIASES.get(key, key)
    if key in KEYSYMS:
        return KEYSYMS[key]
    if key in KEYSYM_EXTRA:
        return KEYSYM_EXTRA[key]
    if key.startswith('F') and key[1:].isdigit():
        return 0xffbe + int(key[1:]) - 1
    raise ValueError(f'unsupported key {name!r}')


class Screen:
    """What the model sees and where its pixels are: the window it works in, rendered by KWin
    alone (CaptureWindow; whatever covers it), with its open popups and dialogs when there are
    some (CaptureArea over them all: they are separate windows in Wayland), or the whole output.
    The window follows the task: when it closes or another app's window becomes active on this
    output (a system dialog, a second app), that one is the window."""

    def __init__(self, backend, output_name: str, window_id: str | None = None) -> None:
        self.backend = backend
        self.output_name = output_name
        self.window_id = window_id      # None: the active window on this output
        self.whole = False              # the model asked for the whole screen
        self.origin = (0.0, 0.0)        # the image's top-left, global logical
        self.scale = 1.0                # image pixels per logical point
        self.clip = (0.0, 0.0, 1.0, 1.0)  # the output: where a click may land
        self.scope = ''                 # what the image shows, told to the model when it changes

    def _region(self) -> tuple[list[str], tuple[float, float, float, float], str]:
        kwin = self.backend.kwin
        info = kwin.target(self.window_id or '')
        outputs = {o['name']: o for o in info['outputs']}
        if self.output_name not in outputs:
            raise RuntimeError(f"no output {self.output_name} (is the assistant's screen on?)")
        screen = tuple(outputs[self.output_name]['geometry'])
        self.clip = screen
        self.output_scale = float(outputs[self.output_name].get('scale') or 1.0)
        target, active = info['target'], info['active']
        usable = lambda w: bool(w) and not w['minimized'] and w['output'] == self.output_name \
            and (w['normal'] or w['dialog'])
        if usable(active) and (not usable(target) or active['pid'] != target['pid']):
            self.window_id = active['id']            # the task moved to another window
            info = kwin.target(self.window_id)
            target = info['target']
        if self.whole or not usable(target):
            return ['screen', self.output_name], screen, 'the whole screen'
        name = target['caption'] or target['resource_class']
        if not info['related']:
            return ['window', target['id']], tuple(target['frame']), f'only the "{name}" window'
        frames = [target['frame']] + [w['frame'] for w in info['related']]
        x1 = max(min(f[0] for f in frames), screen[0])
        y1 = max(min(f[1] for f in frames), screen[1])
        x2 = min(max(f[0] + f[2] for f in frames), screen[0] + screen[2])
        y2 = min(max(f[1] + f[3] for f in frames), screen[1] + screen[3])
        x1, y1, x2, y2 = int(x1), int(y1), int(x2 + 0.999), int(y2 + 0.999)
        return (['area', str(x1), str(y1), str(x2 - x1), str(y2 - y1)], (x1, y1, x2 - x1, y2 - y1),
                f'the "{name}" window with its open menus and dialogs')

    def capture(self) -> tuple[str, Image.Image, bool]:
        """The image as a data URL, the image, and whether what it shows changed."""
        args, region, scope = self._region()
        done = subprocess.run([SCREENSHOT, *args], capture_output=True, timeout=15)
        if done.returncode != 0:
            raise RuntimeError(f'moto-screenshot: {done.stderr.decode(errors="replace").strip()}')
        end = done.stdout.index(b'\n')
        header = json.loads(done.stdout[:end])
        mode = RAW_MODES.get(header.get('format'))
        if mode is None:
            raise RuntimeError(f"unsupported capture format {header.get('format')}")
        image = Image.frombuffer('RGBA', (header['width'], header['height']), done.stdout[end + 1:], 'raw', mode,
                                 header['stride'], 1).convert('RGB')
        # CaptureArea renders at the largest scale of all outputs (the phone's 3): back to this
        # output's own pixels, or the model would pay for 3x as many for nothing.
        wanted = (round(region[2] * self.output_scale), round(region[3] * self.output_scale))
        if image.width > wanted[0] * 1.05:
            image = image.resize(wanted, Image.LANCZOS)
        self.origin = (float(region[0]), float(region[1]))
        self.scale = image.width / region[2]
        changed = scope != self.scope
        self.scope = scope
        # JPEG q85 without chroma subsampling (docs/68): 190 KB against 1.3 MB of PNG for the whole
        # screen, 26 ms to encode on the phone, requests about half as long; accuracy no worse.
        buffer = io.BytesIO()
        image.save(buffer, 'JPEG', quality=85, subsampling=0)
        return 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode(), image, changed

    def point(self, x: float, y: float) -> tuple[float, float]:
        gx, gy = self.origin[0] + x / self.scale, self.origin[1] + y / self.scale
        cx, cy, cw, ch = self.clip
        if not (cx <= gx < cx + cw and cy <= gy < cy + ch):
            raise ValueError(f'({x}, {y}) is outside the screen')
        return gx, gy

    def note(self) -> str:
        return (f'(This screenshot shows {self.scope}; coordinates are pixels of it. '
                'Call view_whole_screen to see everything.)' if not self.whole else
                '(This screenshot shows the whole screen; coordinates are pixels of it.)')


VIEW_WHOLE_SCREEN = {
    'type': 'function', 'name': 'view_whole_screen',
    'description': ('The screenshots show only the window you work in (with its open menus and dialogs). Call this '
                    'to see the whole screen instead: the taskbar, the desktop or other windows.'),
    'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
}
TOOLS = [{'type': 'computer'}, VIEW_WHOLE_SCREEN]


class ComputerUse:
    def __init__(self, backend, output_name: str, window_id: str | None = None) -> None:
        self.backend = backend
        self.screen = Screen(backend, output_name, window_id)

    # ---- the model ----------------------------------------------------------------------
    def _respond(self, body: dict) -> dict:
        request = urllib.request.Request(API, data=json.dumps(body).encode(), headers={
            'Authorization': 'Bearer ' + api_key(), 'Content-Type': 'application/json'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                detail = error.read().decode(errors='replace')[:600]
                if error.code >= 500 and attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                raise RuntimeError(f'Responses API {error.code}: {detail}') from error
            except urllib.error.URLError as error:
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
                raise RuntimeError(f'Responses API unreachable: {error.reason}') from error
        raise RuntimeError('Responses API failed')

    # ---- actions ------------------------------------------------------------------------
    def _hold(self, keys, pressed: bool) -> None:
        for key in (keys or []) if pressed else reversed(keys or []):
            self.backend.input.key(keysym_for(key), pressed)

    def execute(self, action: dict) -> str:
        """Carry out one action; returns a short description for the step log."""
        kind = action.get('type')
        source = self.backend.input
        keys = action.get('keys') if kind != 'keypress' else None
        if kind in ('click', 'double_click', 'move', 'scroll', 'drag'):
            self._hold(keys, True)
        try:
            if kind in ('click', 'double_click'):
                button = {'left': BTN_LEFT, 'right': BTN_RIGHT, 'wheel': BTN_MIDDLE, 'middle': BTN_MIDDLE,
                          'back': BTN_BACK, 'forward': BTN_FORWARD}[action.get('button') or 'left']
                source.click(*self.screen.point(action['x'], action['y']), button=button,
                             count=2 if kind == 'double_click' else 1)
                return f"{kind} {action.get('button') or 'left'} ({action['x']}, {action['y']})"
            if kind == 'move':
                source.glide(*self.screen.point(action['x'], action['y']))
                return f"move ({action['x']}, {action['y']})"
            if kind == 'drag':
                path = [(p['x'], p['y']) if isinstance(p, dict) else tuple(p) for p in action['path']]
                if len(path) < 2:
                    raise ValueError('drag needs two points')
                source.press(*self.screen.point(*path[0]))
                for point in path[1:]:
                    source.glide(*self.screen.point(*point))
                source.release()
                return f'drag {path[0]} -> {path[-1]}'
            if kind == 'scroll':
                source.glide(*self.screen.point(action['x'], action['y']))
                for axis, delta in ((0, action.get('scroll_y') or 0), (1, action.get('scroll_x') or 0)):
                    if delta:
                        # About 100 px a wheel notch, as the guide's desktop handler counts.
                        notches = max(1, round(abs(delta) / 100))
                        source._notify('NotifyPointerAxisDiscrete', 'ui', axis, notches if delta > 0 else -notches)
                return f"scroll ({action.get('scroll_x', 0)}, {action.get('scroll_y', 0)})"
            if kind == 'keypress':
                syms = [keysym_for(k) for k in action['keys']]
                for sym in syms:
                    source.key(sym, True)
                    time.sleep(0.02)
                for sym in reversed(syms):
                    source.key(sym, False)
                    time.sleep(0.01)
                return 'keys ' + '+'.join(action['keys'])
            if kind == 'type':
                self.backend._no_virtual_keyboard()
                self.backend.kwin.commit_text(action['text'])
                time.sleep(0.15)
                return f"type {action['text']!r}"
            if kind == 'wait':
                time.sleep(2)
                return 'wait'
            if kind == 'screenshot':
                return 'look'
            raise ValueError(f'unsupported action {kind!r}')
        finally:
            if kind in ('click', 'double_click', 'move', 'scroll', 'drag'):
                self._hold(keys, False)

    # ---- the loop -------------------------------------------------------------------------
    def run(self, task: str, *, max_steps: int = 40, timeout_s: float = 280, stop=None, gate=None) -> dict:
        """Work on `task` until the model stops. `stop()` returning true ends the run early
        (a caller's own completion signal); the abort file ends it too (the user said stop).
        `gate` (a threading.Event): the model may look and decide meanwhile, but no action is
        carried out before it is set (a voice message's send waits for the speech to end)."""
        started = time.monotonic()
        steps: list[dict] = []
        self.screen.whole = False
        image_url, _, _ = self.screen.capture()
        body = {'model': MODEL, 'tools': TOOLS, 'instructions': INSTRUCTIONS,
                'reasoning': {'effort': EFFORT}, 'truncation': 'auto',
                'input': [{'role': 'user', 'content': [
                    {'type': 'input_text', 'text': f'{task}\n\n{self.screen.note()}'},
                    {'type': 'input_image', 'image_url': image_url, 'detail': 'original'}]}]}
        model_s = 0.0

        def elapsed() -> float:
            return round(time.monotonic() - started, 1)

        while True:
            t0 = time.monotonic()
            response = self._respond(body)
            model_s += time.monotonic() - t0
            output = response.get('output', [])
            calls = [item for item in output if item.get('type') == 'computer_call']
            functions = [item for item in output if item.get('type') == 'function_call']
            text = ' '.join(c.get('text', '') for item in output if item.get('type') == 'message'
                            for c in item.get('content', []) if c.get('type') == 'output_text').strip()
            if not calls and not functions:
                return self._result(text, steps, started, model_s)
            follow: list[dict] = []
            for function in functions:
                if function.get('name') == 'view_whole_screen':
                    self.screen.whole = True
                    steps.append({'actions': ['view whole screen']})
                follow.append({'type': 'function_call_output', 'call_id': function['call_id'],
                               'output': 'The next screenshots show the whole screen; take one to look.'})
            call = calls[0] if calls else None
            if call and call.get('pending_safety_checks'):
                # The API wants the user to confirm this action; we cannot ask mid-run.
                return {'outcome': 'question', 'question': '; '.join(c.get('message', '') for c in call['pending_safety_checks']),
                        'safety_checks': call['pending_safety_checks'], 'steps': steps, 'elapsed_s': elapsed()}
            if call:
                done_actions = []
                actions = call.get('actions') or ([call['action']] if call.get('action') else [])
                for action in actions:
                    if gate is not None and action.get('type') != 'screenshot':
                        gate.wait(timeout_s)
                    if ABORT_FILE.exists():
                        ABORT_FILE.unlink(missing_ok=True)
                        return {'outcome': 'stopped', 'steps': steps, 'elapsed_s': elapsed()}
                    try:
                        done_actions.append(self.execute(action))
                    except (ValueError, KeyError) as error:
                        done_actions.append(f'{action.get("type")}: skipped ({error})')
                    if stop and stop():
                        steps.append({'actions': done_actions})
                        return {'outcome': 'signalled', 'steps': steps, 'elapsed_s': elapsed()}
                steps.append({'actions': done_actions, 'note': text} if text else {'actions': done_actions})
            if len(steps) >= max_steps or time.monotonic() - started > timeout_s:
                return {'outcome': 'unfinished', 'note': f'stopped after {len(steps)} steps', 'steps': steps,
                        'elapsed_s': elapsed()}
            if not call:
                # Only view_whole_screen was called: after the first request the API takes images only
                # as computer_call_output, so the model asks for the screenshot next.
                body = {'model': MODEL, 'tools': TOOLS, 'instructions': INSTRUCTIONS, 'reasoning': {'effort': EFFORT},
                        'truncation': 'auto', 'previous_response_id': response['id'], 'input': follow}
                continue
            time.sleep(SETTLE_S)
            if stop and stop():
                return {'outcome': 'signalled', 'steps': steps, 'elapsed_s': elapsed()}
            image_url, image, changed = self.screen.capture()
            steps[-1]['saw'] = f'{self.screen.scope} {image.width}x{image.height}' if steps else ''
            screenshot = {'type': 'computer_screenshot', 'image_url': image_url, 'detail': 'original'}
            items = list(follow)
            if call:
                items.insert(0, {'type': 'computer_call_output', 'call_id': call['call_id'], 'output': screenshot})
                if changed:
                    items.append({'role': 'user', 'content': [{'type': 'input_text', 'text': self.screen.note()}]})
            body = {'model': MODEL, 'tools': TOOLS, 'instructions': INSTRUCTIONS,
                    'reasoning': {'effort': EFFORT}, 'truncation': 'auto', 'previous_response_id': response['id'],
                    'input': items}

    @staticmethod
    def _result(text: str, steps: list, started: float, model_s: float) -> dict:
        match = re.match(r'\s*(DONE|ASK|FAILED)\b\s*[:：,，.。\-—–]*\s*(.*)', text, re.S | re.I)
        word = match.group(1).upper() if match else 'DONE'
        outcome = {'DONE': 'done', 'ASK': 'question', 'FAILED': 'failed'}[word]
        body = match.group(2).strip() if match else text
        result = {'outcome': outcome, 'achieved': outcome == 'done', 'steps': steps,
                  'elapsed_s': round(time.monotonic() - started, 1), 'model_s': round(model_s, 1)}
        result['question' if outcome == 'question' else 'answer'] = body
        return result
