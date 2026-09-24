"""moto-cua: desktop computer use for Codex, as an MCP server or a CLI (docs/60).

The voice agent's Codex runs commands in a sandbox that cannot reach D-Bus or
Wayland. Codex starts MCP servers outside that sandbox, so desktop operations
(AT-SPI, KWin, the RemoteDesktop portal) and the JEV network calls live here.

  moto-cua mcp                 MCP server on stdio (newline-delimited JSON-RPC)
  moto-cua windows|observe     print JSON
  moto-cua launch APP | activate WINDOW_ID | window WINDOW_ID ACTION
  moto-cua run '<subtask json>'
  moto-cua goal '{"goal": ..., "app": ...}'   whole task, JEV per step (moto-clicker)
"""
from __future__ import annotations

import json
import logging
import os
import select
import subprocess
import sys
import threading
import time
from pathlib import Path

from arc_cua import DesktopExecutor, RuntimeConfig, result_to_dict, subtask_from_dict
from arc_cua.policies import TypeSafeJevPolicy

from . import a11y, names, speech
from .backend import LinuxAtspiBackend

logger = logging.getLogger('moto-cua')
KEY_FILES = (Path.home() / '.config/moto-cua/typesafe-api-key',
             Path.home() / '.config/moto-voice-agent/typesafe-api-key')
MAX_ELEMENTS_SHOWN = 150

SUBTASK_SCHEMA = {
    'type': 'object',
    'properties': {
        'goal': {'type': 'string', 'description': 'What to achieve in the active window, one concrete UI step sequence.'},
        'verification': {'type': 'array', 'items': {'type': 'string'},
                         'description': 'Observable conditions that mean the goal is done.'},
        'inputs': {'type': 'object', 'additionalProperties': {'type': ['string', 'number', 'boolean']},
                   'description': 'Named literal values the executor may type or set; it never invents text.'},
        'constraints': {'type': 'array', 'items': {'type': 'string'}},
        'shortcuts': {'type': 'object', 'additionalProperties': {'type': 'string'},
                      'description': 'Extra keyboard chords allowed, e.g. {"CTRL+L": "focus the address bar"}.'},
        'max_actions': {'type': 'integer', 'minimum': 1, 'maximum': 40},
        'timeout_s': {'type': 'number', 'minimum': 5, 'maximum': 300},
    },
    'required': ['goal', 'verification'],
}

TOOLS = [
    {'name': 'desktop_windows',
     'description': 'List the open desktop windows (phone screen WL-0, TV CAST-n) and which one is active.',
     'inputSchema': {'type': 'object', 'properties': {}}, 'annotations': {'readOnlyHint': True}},
    {'name': 'desktop_activate',
     'description': 'Bring a window (id from desktop_windows) to the front and make it active.',
     'inputSchema': {'type': 'object', 'properties': {'window_id': {'type': 'string'}}, 'required': ['window_id']},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'desktop_window',
     'description': ('Window management through the window manager (use this, not desktop_run, for these): '
                     'close (like the title-bar close button; the app may still ask to save), minimize, maximize, '
                     'restore, to_phone, to_tv (move to that screen).'),
     'inputSchema': {'type': 'object', 'properties': {
         'window_id': {'type': 'string'},
         'action': {'type': 'string', 'enum': ['close', 'minimize', 'maximize', 'restore', 'to_phone', 'to_tv']}},
         'required': ['window_id', 'action']},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'desktop_launch',
     'description': ('Open an application by desktop-file id or name (e.g. "org.kde.dolphin", "Firefox", "系统设置") '
                     'on the TV while casting (else the phone); an app already open is moved there and activated. '
                     'Returns its window id and screen. screen "agent": the assistant\'s screen (floating '
                     'window or TV), where desktop_goal works.'),
     'inputSchema': {'type': 'object', 'properties': {
         'app': {'type': 'string'},
         'screen': {'type': 'string', 'enum': ['auto', 'agent', 'tv', 'phone'],
                    'description': "auto (default): the assistant's screen or the TV when one is on, else the phone."}},
         'required': ['app']},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'desktop_observe',
     'description': 'Accessibility snapshot of the active window: controls with role, name, value and state.',
     'inputSchema': {'type': 'object', 'properties': {}}, 'annotations': {'readOnlyHint': True}},
    {'name': 'desktop_run',
     'description': ('Operate the ACTIVE window with the fast JEV executor until the verification holds: clicks, '
                     'text entry, keys, scrolling. Give literal text only through `inputs`. Returns status '
                     '(SUBTASK_COMPLETE, BLOCKED or NEEDS_AGENT), the actions taken and the final UI state. '
                     'Activate or launch the target app first.'),
     'inputSchema': SUBTASK_SCHEMA,
     # UI operation on the user's behalf, inside this device. Codex would otherwise ask for approval on
     # every call, which the voice assistant cannot answer; the agent prompt makes it confirm deletions,
     # sending and payments with the user first.
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'desktop_goal',
     'description': ('Do a whole task on the desktop: every step (what to click, type, scroll, when it is done) is '
                     'chosen by JEV from the screen (OCR + accessibility), text is written only when needed. Give '
                     'the goal as the user would say it, with every literal value (names, message text) in it. '
                     'With `app`, that application is opened or brought forward first. Returns outcome, achieved, '
                     'answer (what the screen shows about the goal) and the steps taken. Outcome "question": the '
                     'task needs information only the user has; ask the user `question` and call again with the '
                     'same goal and the reply in `replies`. Sending, paying or deleting still needs the user\'s OK '
                     'before you call this. Runs on the assistant\'s screen, which it turns on: the user watches it '
                     'in a floating window (or on the TV) while the phone stays theirs.'),
     'inputSchema': {'type': 'object', 'properties': {
         'goal': {'type': 'string'},
         'app': {'type': 'string', 'description': 'Application to open or activate first (as for desktop_launch).'},
         'replies': {'type': 'array', 'items': {'type': 'object', 'properties': {
             'question': {'type': 'string'}, 'answer': {'type': 'string'}}, 'required': ['question', 'answer']},
             'description': "The user's answers to questions earlier runs of this goal asked."},
         'steps': {'type': 'integer', 'minimum': 1, 'maximum': 60, 'description': 'Most actions to take (default 25).'}},
         'required': ['goal']},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'desktop_find_name',
     'description': ('Find a person, chat or item in the ACTIVE window (and its open popups, e.g. search results) '
                     'by how the name SOUNDS: speech recognition often writes a Chinese name with wrong characters '
                     'of the same sound (周凯文 for 周楷雯). Returns `search_text` (the pinyin; type it into the '
                     'app\'s search field to list same-sounding contacts) and the visible names ranked by sound: '
                     '1.0 same sound, 0.9 same apart from accent-type confusions (zh/z, n/l, an/ang ...). Each element '
                     'has the `section` heading above it: use people and chats (e.g. "Contacts", the chat list), '
                     'not search suggestions ("Internet search results"). If more than one different person '
                     'scores 0.9 or more, ask the user which one.'),
     'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
     'annotations': {'readOnlyHint': True}},
    {'name': 'desktop_voice_message',
     'description': ('Record and send a voice message in the ACTIVE window (a chat already open), spoken by the '
                     'assistant: the app\'s microphone is switched to the Linux microphone for the recording only, '
                     'the text is spoken into it, then the send control is pressed. `start` / `finish` are control '
                     'names from desktop_observe (WeChat: start "Send Voice", finish "Send voice message"). With '
                     '`hold`, `start` is held down while speaking and released to send (hold-to-talk apps). The '
                     'user\'s real microphone is never recorded: if the app does not start recording through the '
                     'Linux microphone, nothing is spoken and the recording is cancelled.'),
     'inputSchema': {'type': 'object', 'properties': {
         'text': {'type': 'string', 'description': 'What the voice message says.'},
         'start': {'type': 'string', 'description': 'Control that starts recording.'},
         'finish': {'type': 'string', 'description': 'Control that sends the recording (omit with hold).'},
         'cancel': {'type': 'string', 'description': 'Control that discards a recording (WeChat: "Cancel").'},
         'hold': {'type': 'boolean'},
         'voice': {'type': 'string', 'description': 'TTS voice, default marin.'}},
         'required': ['text', 'start']},
     # Sends a message on the user's behalf; the agent prompt makes it get the user's OK first.
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
]


def localized_names(info) -> set[str]:
    """Name and GenericName in every language of the .desktop file: the request may
    be in Chinese while this process runs in another locale."""
    names: set[str] = set()
    path = info.get_filename() if hasattr(info, 'get_filename') else None
    if not path:
        return names
    try:
        section = False
        for line in open(path, encoding='utf-8', errors='replace'):
            line = line.strip()
            if line.startswith('['):
                section = line == '[Desktop Entry]'
            elif section and (line.startswith('Name') or line.startswith('GenericName')) and '=' in line:
                names.add(line.split('=', 1)[1].strip().casefold())
    except OSError:
        pass
    return names


def find_application(query: str) -> dict | None:
    """Installed .desktop entry by id or (localized) name, with the names its window may carry."""
    from gi.repository import Gio
    query_folded = query.casefold().removesuffix('.desktop')
    best = None
    for info in Gio.AppInfo.get_all():
        if not info.should_show():
            continue
        app_id = (info.get_id() or '').removesuffix('.desktop')
        names = {app_id.casefold(), (info.get_name() or '').casefold(), (info.get_display_name() or '').casefold()}
        names |= localized_names(info)
        classes = {app_id.casefold(), app_id.split('.')[-1].casefold(),
                   os.path.basename(info.get_executable() or '').casefold()}
        if isinstance(info, Gio.DesktopAppInfo) and info.get_startup_wm_class():
            classes.add(info.get_startup_wm_class().casefold())
        entry = {'id': app_id, 'name': info.get_display_name(), 'classes': sorted(c for c in classes if c)}
        if query_folded in names:
            return entry
        if best is None and any(query_folded in n for n in names if n):
            best = entry
    return best


def api_key() -> str:
    if os.environ.get('TYPESAFE_API_KEY'):
        return os.environ['TYPESAFE_API_KEY']
    for path in KEY_FILES:
        if path.exists():
            return path.read_text().strip()
    raise RuntimeError('No JEV (TypeSafe) API key: put it in ~/.config/moto-cua/typesafe-api-key')


IDLE_A11Y_OFF_S = 600
GOAL_TIMEOUT_S = 290  # inside Codex's tool timeout (320 s, install.sh)


class Cua:
    def __init__(self) -> None:
        self._backend: LinuxAtspiBackend | None = None
        self._policy: TypeSafeJevPolicy | None = None
        self._idle: threading.Timer | None = None

    def _touch(self) -> None:
        """Accessibility costs every registered app: switch it off after a quiet period."""
        if self._idle:
            self._idle.cancel()
        self._idle = threading.Timer(IDLE_A11Y_OFF_S, self._idle_off)
        self._idle.daemon = True
        self._idle.start()

    def _idle_off(self) -> None:
        if self._backend is not None and self._backend.enabled_by_us:
            self._backend.set_accessibility(False)

    @property
    def backend(self) -> LinuxAtspiBackend:
        if self._backend is None:
            self._backend = LinuxAtspiBackend()
        return self._backend

    def windows(self) -> dict:
        info = self.backend.kwin.windows()
        active = (info.get('active') or {}).get('id')
        screens = info.get('screens', [])
        return {'casting': any(s.startswith('CAST') for s in screens), 'screens': screens,
                'windows': [{'id': w['id'], 'caption': w['caption'], 'app': w['resource_class'], 'screen': w['output'],
                             'active': w['id'] == active, 'minimized': w['minimized']} for w in info['windows']]}

    def window(self, window_id: str, action: str) -> dict:
        result = self.backend.kwin.window_action(window_id, action)
        if not result.get('found'):
            raise ValueError(f'No window {window_id}; list them with desktop_windows')
        time.sleep(0.5)
        still_open = any(w['id'] == window_id for w in self.backend.kwin.windows()['windows'])
        result['still_open'] = still_open
        if action == 'close' and still_open:
            result['note'] = 'The window is still open: it may be asking something (e.g. to save); observe it.'
        return result

    def activate(self, window_id: str) -> dict:
        ok = self.backend.kwin.activate(window_id)
        time.sleep(0.3)
        return {'activated': ok}

    def launch(self, app: str, screen: str = 'auto') -> dict:
        """Open `app` on the TV while casting (else the phone), or bring its open window there."""
        entry = find_application(app)
        if entry is None:
            raise ValueError(f'No installed application matches {app!r}')
        classes = entry.pop('classes')
        kwin = self.backend.kwin
        info = kwin.windows()
        casting = any(s.startswith('CAST') for s in info.get('screens', []))
        # The assistant's screen (docs/65) and the TV are the same output, CAST-n.
        to_tv = screen in ('tv', 'agent') or (screen == 'auto' and casting)
        prefix = 'CAST' if to_tv else 'WL'
        target_screen = next((n for n in info.get('screens', []) if n.startswith(prefix)), prefix)
        existing = next((w for w in info['windows'] if (w['resource_class'] or '').casefold() in classes), None)
        if existing:
            if not existing['output'].startswith(prefix):
                kwin.window_action(existing['id'], 'to_tv' if to_tv else 'to_phone')
            kwin.activate(existing['id'])
            time.sleep(0.3)
            return {'launched': entry, 'already_open': True,
                    'window': {'id': existing['id'], 'caption': existing['caption'], 'screen': target_screen}}
        placed = kwin.place_next(classes, prefix, lambda: subprocess.Popen(
            ['kstart', '--application', entry['id']], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True), timeout=25)
        if placed is None:
            return {'launched': entry, 'window': None,
                    'note': ('No window within 25 s. Check desktop_windows once; do not start the app from the '
                             'shell (its window would open on the phone). Tell the user if it did not start.')}
        time.sleep(0.3)
        return {'launched': entry, 'window': {'id': placed['id'], 'screen': placed['screen']}}

    def observe(self) -> dict:
        snapshot = self.backend.observe()
        data = snapshot.compact()
        data.pop('revision', None)
        if len(data['elements']) > MAX_ELEMENTS_SHOWN:
            data['elements_truncated'] = len(data['elements']) - MAX_ELEMENTS_SHOWN
            data['elements'] = data['elements'][:MAX_ELEMENTS_SHOWN]
        return data

    def run(self, payload: dict) -> dict:
        payload = dict(payload)
        timeout = float(payload.pop('timeout_s', 120))
        payload.setdefault('max_actions', 20)
        subtask = subtask_from_dict(payload)
        if self._policy is None:
            self._policy = TypeSafeJevPolicy(api_key=api_key())
        executor = DesktopExecutor(self.backend, self._policy, config=RuntimeConfig(timeout_s=timeout))
        started = time.perf_counter()
        result = result_to_dict(executor.run(subtask))
        result['elapsed_ms'] = round((time.perf_counter() - started) * 1000)
        final = result.pop('final_snapshot')
        elements = final.get('elements', [])
        result['final_window'] = {'application': final.get('application'), 'window': final.get('window'),
                                  'elements': elements[:MAX_ELEMENTS_SHOWN]}
        for record in result['history']:
            for key in ('before_revision', 'after_revision', 'target_bounds'):
                record.pop(key, None)
        return result

    def goal(self, args: dict) -> dict:
        """A whole task through moto-clicker (typesafe-computer-use, JEV per step; docs/64), on the
        assistant's screen (docs/65): turned on first, and the app opened there."""
        screen = subprocess.run(['moto-agent-screen', 'on'], capture_output=True, text=True, timeout=30)
        if screen.returncode != 0:
            raise RuntimeError(f'assistant screen: {screen.stderr.strip() or screen.stdout.strip()}')
        if args.get('app'):
            self.launch(str(args['app']), 'agent')
            time.sleep(0.8)
        command = ['moto-clicker', 'run', str(args['goal']), '--steps', str(int(args.get('steps') or 25))]
        for reply in args.get('replies') or []:
            command += ['--reply', f"{reply['question']}={reply['answer']}"]
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=GOAL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            subprocess.run(['moto-clicker', 'stop'], capture_output=True, timeout=30)
            return {'outcome': 'timeout', 'note': f'Stopped after {GOAL_TIMEOUT_S} s; check the screen.'}
        if done.returncode != 0:
            raise RuntimeError(f'moto-clicker failed: {done.stderr.strip()[-800:]}')
        return json.loads(done.stdout)

    def press_control(self, binary: str, names: list[str]) -> dict:
        """Click the first control named one of `names` in any window of the app
        (e.g. a call window's hang-up button), whichever window is active."""
        backend = self.backend
        bus = backend.bus
        windows = [w for w in backend.kwin.windows()['windows']
                   if os.path.basename(os.readlink(f"/proc/{w['pid']}/exe")) == binary]
        for app in bus.applications():
            pid = bus.pid(app[0])
            if not pid or pid not in {w['pid'] for w in windows}:
                continue
            for window in bus.windows(app):
                if not window.state(a11y.SHOWING):
                    continue
                origin = bus.origin(window)
                target = next((w for w in windows if w['pid'] == pid and w['caption'] == window.name), None)
                if origin is None or target is None:
                    continue
                for node in bus.tree(window, max_nodes=400):
                    if not node.name or not any(node.name == n or node.name.startswith(n) for n in names):
                        continue
                    extents = bus.extents(node, origin)
                    if extents is None:
                        continue
                    cx, cy = target['client'][0], target['client'][1]
                    x, y, w, h = extents
                    backend.kwin.activate(target['id'])
                    backend.input.click(cx + x + w / 2, cy + y + h / 2)
                    return {'pressed': node.name, 'window': target['caption']}
        return {'pressed': None, 'looked_for': names, 'windows': [w['caption'] for w in windows]}

    def focus_showing(self, binary: str, text: str) -> dict:
        """Activate the app's window that shows `text` as a label or heading (e.g.
        the chat header of a contact): chats may be open in several windows."""
        backend = self.backend
        bus = backend.bus
        windows = [w for w in backend.kwin.windows()['windows']
                   if os.path.basename(os.readlink(f"/proc/{w['pid']}/exe")) == binary]
        for app in bus.applications():
            pid = bus.pid(app[0])
            if not pid or pid not in {w['pid'] for w in windows}:
                continue
            for window in bus.windows(app):
                if not window.state(a11y.SHOWING):
                    continue
                target = next((w for w in windows if w['pid'] == pid and w['caption'] == window.name), None)
                if target is None:
                    continue
                if any(n.name == text and n.role in ('label', 'heading', 'text', 'filler')
                       for n in bus.tree(window, max_nodes=400)):
                    backend.kwin.activate(target['id'])
                    backend._root = None
                    return {'activated': target['id'], 'window': target['caption']}
        return {'activated': None, 'looked_for': text}

    def find_name(self, name: str) -> dict:
        snapshot = self.backend.observe()
        found: dict[str, list] = {}
        section: dict[str, str] = {}      # element id -> heading above it in the same list
        heading: dict[str | None, str] = {}
        for element in snapshot.elements:
            first = (element.name or '').split('\n')[0].strip()
            # Result lists group items under one-line headings without a sound match
            # ("Contacts", "Group Chats", "Internet search results").
            if first and '\n' not in (element.name or '') and names.score(name, first) < 0.5:
                heading[element.parent_id] = first
            section[element.id] = heading.get(element.parent_id, '')
            if first:
                found.setdefault(first, []).append(element)
        ranked = names.rank(name, list(found))
        return {'search_text': names.search_text(name), 'window': snapshot.window,
                'matches': [{'name': n, 'score': score,
                             'elements': [{'id': e.id, 'role': e.role, 'section': section[e.id], 'name': e.name[:80]}
                                          for e in found[n][:3]]}
                            for n, score in ranked]}

    def voice_message(self, args: dict) -> dict:
        """Speak `text` into the active app's recording (docs/62)."""
        text = str(args['text']).strip()
        start, finish = str(args['start']), args.get('finish')
        cancel, hold = str(args.get('cancel') or 'Cancel'), bool(args.get('hold'))
        if not text or (not hold and not finish):
            raise ValueError('voice message needs text and a finish control (or hold)')
        audio = speech.synthesize(text, voice=str(args.get('voice') or 'marin'))
        backend = self.backend
        snapshot = backend.observe()
        pid = backend._window['pid']
        binary = os.path.basename(os.readlink(f'/proc/{pid}/exe'))

        def control(snap, name):
            match = next((e for e in snap.elements if e.name == name), None) \
                or next((e for e in snap.elements if e.name.startswith(name)), None)
            if match is None:
                raise ValueError(f'No control named {name!r} in {snap.window!r}')
            return backend._global_center(backend._nodes[match.id])

        start_at = control(snapshot, start)
        router = subprocess.Popen(['moto-audio-route', '--binary', binary, '--microphone'], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True)
        routed = False
        try:
            if router.stdout.readline().strip() != 'ready':
                raise RuntimeError('audio routing did not start')
            if hold:
                backend.input.press(*start_at)
            else:
                backend.input.click(*start_at)
            # The recording stream appears when recording starts; speak only once it
            # records from the Linux microphone.
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and not routed:
                ready = select.select([router.stdout], [], [], 0.2)[0]
                if ready:
                    routed = router.stdout.readline().startswith('routed source-output')
            if not routed:
                if hold:
                    backend.input.release()
                raise RuntimeError(f'{binary} did not start recording through the Linux microphone; nothing was spoken')
            time.sleep(0.2)
            subprocess.run(['pacat', '--device=linux_microphone_input', '--raw', '--format=s16le',
                            f'--rate={speech.RATE}', '--channels=1', '--latency-msec=30'], input=audio,
                           check=True, timeout=120)
            time.sleep(0.4)
            if hold:
                backend.input.release()
            else:
                backend._root = None
                backend.input.click(*control(backend.observe(), str(finish)))
        except Exception:
            if routed and not hold:
                try:   # never leave a recording that could be sent later
                    backend._root = None
                    backend.input.click(*control(backend.observe(), cancel))
                except Exception:  # noqa: BLE001
                    pass
            raise
        finally:
            router.stdin.close()
            try:
                router.wait(5)
            except subprocess.TimeoutExpired:
                router.kill()
        time.sleep(1)
        backend._root = None
        after = backend.observe()
        return {'sent': True, 'app': binary, 'seconds': round(len(audio) / 2 / speech.RATE, 1),
                'window': after.window,
                'recording_controls_left': [e.name for e in after.elements if e.name in (finish, cancel)]}

    def call(self, name: str, arguments: dict) -> dict:
        self.backend.set_accessibility(True)
        self._touch()
        if name == 'desktop_windows':
            return self.windows()
        if name == 'desktop_activate':
            return self.activate(str(arguments['window_id']))
        if name == 'desktop_window':
            return self.window(str(arguments['window_id']), str(arguments['action']))
        if name == 'desktop_launch':
            return self.launch(str(arguments['app']), str(arguments.get('screen') or 'auto'))
        if name == 'desktop_observe':
            return self.observe()
        if name == 'desktop_run':
            return self.run(arguments)
        if name == 'desktop_voice_message':
            return self.voice_message(arguments)
        if name == 'desktop_goal':
            return self.goal(arguments)
        if name == 'desktop_find_name':
            return self.find_name(str(arguments['name']))
        raise ValueError(f'Unknown tool {name}')


def serve() -> None:
    """MCP over stdio: one JSON-RPC message per line."""
    cua = Cua()
    out = sys.stdout

    def send(message: dict) -> None:
        out.write(json.dumps(message, ensure_ascii=False) + '\n')
        out.flush()

    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        method, rid = request.get('method'), request.get('id')
        if rid is None:
            continue  # notifications (initialized, cancelled)
        try:
            if method == 'initialize':
                version = request.get('params', {}).get('protocolVersion', '2025-06-18')
                result = {'protocolVersion': version, 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'moto-cua', 'version': '0.1.0'}}
            elif method == 'tools/list':
                result = {'tools': TOOLS}
            elif method == 'tools/call':
                params = request.get('params', {})
                try:
                    data = cua.call(params.get('name', ''), params.get('arguments') or {})
                    result = {'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}]}
                except Exception as error:  # reported to the model, not a protocol error
                    logger.exception('tool %s failed', params.get('name'))
                    result = {'content': [{'type': 'text', 'text': f'{type(error).__name__}: {error}'}],
                              'isError': True}
            elif method == 'ping':
                result = {}
            else:
                send({'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': f'Unknown method {method}'}})
                continue
            send({'jsonrpc': '2.0', 'id': rid, 'result': result})
        except Exception as error:
            send({'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32603, 'message': str(error)}})


def import_session_environment() -> None:
    """Codex starts MCP servers with a handful of variables. Take the graphical
    session's environment from the systemd user manager, as the desktop does when
    it launches apps: without MOZ_ENABLE_WAYLAND/GDK_BACKEND, Firefox started from
    here found no display and never showed a window."""
    try:
        out = subprocess.run(['busctl', '--user', '-j', 'get-property', 'org.freedesktop.systemd1',
                              '/org/freedesktop/systemd1', 'org.freedesktop.systemd1.Manager', 'Environment'],
                             capture_output=True, text=True, timeout=5).stdout
        for item in json.loads(out)['data']:
            key, _, value = item.partition('=')
            os.environ.setdefault(key, value)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        logger.warning('session environment unavailable: %s', error)


def main() -> None:
    import_session_environment()
    logging.basicConfig(level=os.environ.get('MOTO_CUA_LOG', 'WARNING'), stream=sys.stderr,
                        format='%(asctime)s %(name)s %(message)s')
    command = sys.argv[1] if len(sys.argv) > 1 else 'mcp'
    if command == 'mcp':
        serve()
        return
    cua = Cua()
    if command == 'windows':
        data = cua.windows()
    elif command == 'observe':
        data = cua.observe()
    elif command == 'activate':
        data = cua.activate(sys.argv[2])
    elif command == 'launch':
        data = cua.launch(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'auto')
    elif command == 'window':
        data = cua.window(sys.argv[2], sys.argv[3])
    elif command == 'run':
        data = cua.run(json.loads(sys.argv[2]))
    elif command == 'voice':
        data = cua.voice_message(json.loads(sys.argv[2]))
    elif command == 'find-name':
        data = cua.find_name(sys.argv[2])
    elif command == 'press-control':
        data = cua.press_control(sys.argv[2], sys.argv[3:])
    elif command == 'goal':
        data = cua.goal(json.loads(sys.argv[2]))
    elif command == 'focus-showing':
        data = cua.focus_showing(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
    print(json.dumps(data, ensure_ascii=False, indent=1))
    if cua._backend is not None:
        cua._backend.set_accessibility(False)  # only if this run switched it on
