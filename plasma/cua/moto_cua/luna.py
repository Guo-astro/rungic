"""Computer use with GPT-6 Luna (docs/68): the model sees the screen and decides where to act.

Plan one of moto-cua (the default). No accessibility tree and no OCR: every step is a screenshot of
the assistant's screen sent to the Responses API with the `computer` tool, and the model answers
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
    """One output: screenshots in native pixels, and those pixels as global logical points."""

    def __init__(self, backend, output_name: str) -> None:
        self.backend = backend
        self.output_name = output_name
        self.geometry = (0.0, 0.0, 1.0, 1.0)
        self.scale = 1.0

    def capture(self) -> tuple[str, Image.Image]:
        outputs = {o['name']: o for o in self.backend.kwin.windows().get('outputs', [])}
        if self.output_name not in outputs:
            raise RuntimeError(f'no output {self.output_name} (is the assistant\'s screen on?)')
        self.geometry = tuple(outputs[self.output_name]['geometry'])
        done = subprocess.run([SCREENSHOT, 'screen', self.output_name], capture_output=True, timeout=15)
        if done.returncode != 0:
            raise RuntimeError(f'moto-screenshot: {done.stderr.decode(errors="replace").strip()}')
        end = done.stdout.index(b'\n')
        header = json.loads(done.stdout[:end])
        mode = RAW_MODES.get(header.get('format'))
        if mode is None:
            raise RuntimeError(f"unsupported capture format {header.get('format')}")
        image = Image.frombuffer('RGBA', (header['width'], header['height']), done.stdout[end + 1:], 'raw', mode,
                                 header['stride'], 1).convert('RGB')
        self.scale = image.width / self.geometry[2]
        # JPEG q85 without chroma subsampling (docs/68): 190 KB against 1.3 MB of PNG, 26 ms to encode
        # on the phone, requests about half as long; reading and click accuracy were no worse.
        buffer = io.BytesIO()
        image.save(buffer, 'JPEG', quality=85, subsampling=0)
        return 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode(), image

    def point(self, x: float, y: float) -> tuple[float, float]:
        ox, oy, w, h = self.geometry
        gx, gy = ox + x / self.scale, oy + y / self.scale
        if not (ox <= gx < ox + w and oy <= gy < oy + h):
            raise ValueError(f'({x}, {y}) is outside the screenshot')
        return gx, gy


class ComputerUse:
    def __init__(self, backend, output_name: str) -> None:
        self.backend = backend
        self.screen = Screen(backend, output_name)

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
        image_url, _ = self.screen.capture()
        body = {'model': MODEL, 'tools': [{'type': 'computer'}], 'instructions': INSTRUCTIONS,
                'reasoning': {'effort': EFFORT}, 'truncation': 'auto',
                'input': [{'role': 'user', 'content': [
                    {'type': 'input_text', 'text': task},
                    {'type': 'input_image', 'image_url': image_url, 'detail': 'original'}]}]}
        model_s = 0.0
        while True:
            t0 = time.monotonic()
            response = self._respond(body)
            model_s += time.monotonic() - t0
            calls = [item for item in response.get('output', []) if item.get('type') == 'computer_call']
            text = ' '.join(c.get('text', '') for item in response.get('output', []) if item.get('type') == 'message'
                            for c in item.get('content', []) if c.get('type') == 'output_text').strip()
            if not calls:
                return self._result(text, steps, started, model_s)
            call = calls[0]
            if call.get('pending_safety_checks'):
                # The API wants the user to confirm this action; we cannot ask mid-run.
                return {'outcome': 'question', 'question': '; '.join(c.get('message', '') for c in call['pending_safety_checks']),
                        'safety_checks': call['pending_safety_checks'], 'steps': steps,
                        'elapsed_s': round(time.monotonic() - started, 1)}
            done_actions = []
            actions = call.get('actions') or ([call['action']] if call.get('action') else [])
            for action in actions:
                if gate is not None and action.get('type') != 'screenshot':
                    gate.wait(timeout_s)
                if ABORT_FILE.exists():
                    ABORT_FILE.unlink(missing_ok=True)
                    return {'outcome': 'stopped', 'steps': steps, 'elapsed_s': round(time.monotonic() - started, 1)}
                try:
                    done_actions.append(self.execute(action))
                except (ValueError, KeyError) as error:
                    done_actions.append(f'{action.get("type")}: skipped ({error})')
                if stop and stop():
                    steps.append({'actions': done_actions})
                    return {'outcome': 'signalled', 'steps': steps, 'elapsed_s': round(time.monotonic() - started, 1)}
            steps.append({'actions': done_actions, 'note': text} if text else {'actions': done_actions})
            if len(steps) >= max_steps or time.monotonic() - started > timeout_s:
                return {'outcome': 'unfinished', 'note': f'stopped after {len(steps)} steps', 'steps': steps,
                        'elapsed_s': round(time.monotonic() - started, 1)}
            time.sleep(SETTLE_S)
            if stop and stop():
                return {'outcome': 'signalled', 'steps': steps, 'elapsed_s': round(time.monotonic() - started, 1)}
            image_url, _ = self.screen.capture()
            body = {'model': MODEL, 'tools': [{'type': 'computer'}], 'instructions': INSTRUCTIONS,
                    'reasoning': {'effort': EFFORT}, 'truncation': 'auto', 'previous_response_id': response['id'],
                    'input': [{'type': 'computer_call_output', 'call_id': call['call_id'], 'output': {
                        'type': 'computer_screenshot', 'image_url': image_url, 'detail': 'original'}}]}

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
