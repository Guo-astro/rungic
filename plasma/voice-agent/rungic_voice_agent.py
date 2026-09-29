#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Voice assistant service (docs/59).

A session D-Bus service (com.rungic.VoiceAgent) that owns `codex app-server`.
Each conversation is a Codex thread. While a conversation is open, a GPT
Realtime session runs on it: push-to-talk audio from the phone microphone goes
in, the spoken reply comes out of the speaker, and the realtime model hands
work to the Codex agent with its `background_agent` tool. Everything that
happens (speech, agent progress, commands, approvals) is sent to the UI as
JSON events and kept per conversation for the chat history.

  rungic-voice-agent --service            D-Bus service (systemd user unit)
  rungic-voice-agent --audio-file F.pcm   one test turn: F (S16LE 24 kHz mono) as speech

Realtime runs over WebSocket so all traffic goes through the proxy that the
`codex` wrapper sets; Codex needs an API key for that (OPENAI_API_KEY from the
key file, rungic_cua.keys, docs/87), while the agent itself uses Codex's
own sign-in (a ChatGPT account, or the same key).
"""
import argparse
import array
import base64
import io
import itertools
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import urllib.request

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gio, GLib, Gst

# The call proxy (docs/63) lives next to this script's shared files; the key-file
# module (docs/87) comes with rungic-cua.
import sys
sys.path.insert(0, '/usr/lib/rungic-voice-agent')
sys.path.insert(1, '/usr/lib/rungic-cua')
import shutil
import socket
import task_state

RATE = 24000                 # PCM format of the Realtime API
CHUNK_MS = 100
MIC = 'android_microphone'
PHONE_SINK = 'android_phone'     # always the phone itself (shared/media/media-bridge.py)
END_SILENCE_MS = 900         # after release, so the server VAD sees the end of speech
# Codex fixes the realtime session's turn detection to server VAD with 500 ms of
# silence (codex-api realtime_websocket/methods_v2.rs). A pause while the button is
# still held would end the user's turn and the model would answer half a sentence.
# While held, pauses are shortened so the server never sees 500 ms of silence.
PAUSE_KEEP_MS = 200          # the start of a pause is sent as is
PAUSE_PREROLL_MS = 140       # and the end of a longer one, before speech resumes
IDLE_STOP_S = 600            # stop an unused realtime session (cost)
# Hands-free (docs/67): a hold released before anything was said keeps listening,
# and the turn ends by itself after speech and then this much quiet.
HANDS_FREE_END_MS = 900
HANDS_FREE_NO_SPEECH_S = 8   # nothing said by then: stop listening, send nothing
HANDS_FREE_MAX_S = 60
# The voice (Realtime API): Codex's default is gpt-realtime-1.5. The emotion of
# the voice is chosen by the model per response from prompts/realtime.md; the
# API has no emotion parameter, it follows instructions.
REALTIME_MODEL = 'gpt-realtime-2.1-mini'
# The agent (Codex): the fast model; tasks here are short device operations.
AGENT_MODEL = 'gpt-6-sol'
AGENT_EFFORT = 'medium'
# The agent's own workspace (docs/research/91): a KWin of its own on the Android host, where
# everything the agent opens appears and nothing reaches the user's phone. A second agent
# would get 2, and so on (the host offers ws-1 .. ws-4).
WORKSPACE = 1
# Spoken progress while the agent works: Codex hands agent updates to the voice
# model as context only (no response), so it would stay silent until the end.
# Spoken progress (docs/89): by events, not by the clock. The screen shows every step; the
# voice says the milestones, and more of them when nobody looks at the screen.
PROGRESS_AFTER_S = 8         # quick tasks get no progress update
GAP_AWAY_S = 8               # least silence between two updates when nobody looks
GAP_WATCHED_S = 20           # ... and when the user looks at the chat or the assistant's screen
LONG_STEP_S = 40             # one step this long gets a word on how far it is
LONG_AGAIN_AWAY_S = 45       # ... and again after this much silence (at most twice per step)
LONG_AGAIN_WATCHED_S = 90
STILL_AFTER_S = 25           # nothing at all was said yet: one "still working"
APOLOGY_AFTER_S = 90         # a long wait earns one short apology
WATCHERS_FRESH_S = 3         # how long the phone's foreground state is trusted
DATA = Path.home() / '.local/share/rungic-voice-agent'
CONFIG = Path.home() / '.config/rungic-voice-agent'
PROMPTS = Path('/usr/share/rungic-voice-agent/prompts')
BUS_NAME = 'com.rungic.VoiceAgent'
OBJECT_PATH = '/com/rungic/VoiceAgent'
INTERFACE = '''
<node>
  <interface name="com.rungic.VoiceAgent">
    <method name="ListConversations"><arg type="s" direction="out"/></method>
    <method name="OpenConversation"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
    <method name="CloseConversation"><arg type="s" direction="in"/></method>
    <method name="OpenAssistant"><arg type="s" direction="out"/></method>
    <method name="AssistantTalk"><arg type="s" direction="in"/></method>
    <method name="ReleaseTalking"/>
    <method name="CancelTalking"/>
    <method name="StartListening"><arg type="s" direction="in"/></method>
    <method name="DeleteConversation"><arg type="s" direction="in"/></method>
    <method name="StartTalking"><arg type="s" direction="in"/></method>
    <method name="StopTalking"/>
    <method name="Interrupt"/>
    <method name="StopTask"/>
    <method name="Approve"><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
    <method name="State"><arg type="s" direction="out"/></method>
    <method name="StartCall"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
    <method name="CallCommand"><arg type="s" direction="in"/></method>
    <method name="SendText"><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
    <method name="TalkToText"><arg type="s" direction="out"/></method>
    <method name="ReadAloud"><arg type="s" direction="in"/></method>
    <method name="Setup"><arg type="s" direction="out"/></method>
    <method name="SetApiKey"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
    <method name="TestApiKey"><arg type="s" direction="out"/></method>
    <method name="RemoveApiKey"><arg type="s" direction="out"/></method>
    <method name="CodexLogin"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
    <method name="InstallCodex"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
    <method name="CancelInstall"><arg type="s" direction="out"/></method>
    <method name="SetPreferences"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
    <method name="SetWatching"><arg type="b" direction="in"/></method>
    <method name="Use"><arg type="s" direction="in"/></method>
    <signal name="Event"><arg type="s"/></signal>
  </interface>
</node>
'''


def workspace_env(slot=WORKSPACE, wait=10.0):
    """Start agent workspace `slot` if it is not running and return what puts a program in it
    (the variables rungic-workspace-env sets), or None: the host offers no workspaces (APK
    before 2.14) or it did not come up in time. The user's own display and bus go along as
    RUNGIC_USER_*, for what belongs on the phone (the assistant screen's floating window)."""
    if not Path(f'/mnt/android-wayland/ws-{slot}').exists():
        return None
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'rungic-workspaces' / str(slot)
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
    deadline = time.monotonic() + wait
    started = False
    while True:
        try:
            bus = (state / 'bus').read_text().strip()
        except OSError:
            bus = ''
        if bus and (runtime / f'wayland-ws-{slot}').exists():
            break
        if not started:
            subprocess.run(['systemctl', '--user', 'start', '--no-block', f'rungic-workspace@{slot}.service'],
                           capture_output=True, timeout=10)
            started = True
        if time.monotonic() > deadline:
            log(f'workspace {slot}: not up after {wait:.0f} s')
            return None
        time.sleep(0.2)
    env = {'WAYLAND_DISPLAY': f'wayland-ws-{slot}', 'DBUS_SESSION_BUS_ADDRESS': bus, 'RUNGIC_WORKSPACE': str(slot),
           'QT_QPA_PLATFORM': 'wayland', 'XDG_SESSION_TYPE': 'wayland', 'XDG_CURRENT_DESKTOP': 'KDE',
           'RUNGIC_USER_WAYLAND_DISPLAY': os.environ.get('WAYLAND_DISPLAY', 'wayland-0'),
           'RUNGIC_USER_DBUS_SESSION_BUS_ADDRESS': os.environ.get('DBUS_SESSION_BUS_ADDRESS', f'unix:path={runtime}/bus')}
    try:
        env['DISPLAY'] = (state / 'display').read_text().strip()
    except OSError:
        pass
    return env


def openai_key() -> str:
    """The OpenAI API key, or ''."""
    from rungic_cua import keys
    return keys.read('openai-api-key')


# The app's choices that change what this service does (docs/87).
PREFERENCES = {'homeHold': True, 'speak': True, 'handsFreeAutoSend': True}


def preferences() -> dict:
    try:
        saved = json.loads((CONFIG / 'preferences.json').read_text())
    except (OSError, ValueError):
        saved = {}
    return {k: bool(saved.get(k, v)) for k, v in PREFERENCES.items()}


def log(*args):
    print(time.strftime('%H:%M:%S'), *args, flush=True)


def prompt(name, fallback=''):
    for base in (PROMPTS, Path(__file__).resolve().parent / 'prompts'):
        path = base / name
        if path.exists():
            return path.read_text()
    return fallback


class AppServer:
    """JSON-RPC 2.0 over stdio with `codex app-server`."""

    def __init__(self, on_notification, on_request):
        env = dict(os.environ)
        key = openai_key()
        if key:
            env['OPENAI_API_KEY'] = key
        # The official install script puts codex in ~/.local/bin (docs/87).
        codex = shutil.which('codex', path=os.environ.get('PATH', '') + ':' + str(Path.home() / '.local/bin'))
        if not codex:
            raise FileNotFoundError('codex')
        self.proc = subprocess.Popen([codex, 'app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=0, env=env)
        self.ids = itertools.count(1)
        self.pending = {}
        self.lock = threading.Lock()
        self.on_notification = on_notification
        self.on_request = on_request
        threading.Thread(target=self.read, daemon=True).start()

    def send(self, message):
        data = (json.dumps(message, ensure_ascii=False) + '\n').encode()
        with self.lock:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def call(self, method, params, timeout=60):
        request_id = next(self.ids)
        done = threading.Event()
        self.pending[request_id] = [done, None]
        self.send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        if not done.wait(timeout):
            self.pending.pop(request_id, None)
            raise TimeoutError(method)
        reply = self.pending.pop(request_id)[1]
        if 'error' in reply:
            raise RuntimeError(f'{method}: {reply["error"].get("message", reply["error"])}')
        return reply.get('result')

    def notify(self, method, params=None):
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            message['params'] = params
        self.send(message)

    def respond(self, request_id, result):
        self.send({'jsonrpc': '2.0', 'id': request_id, 'result': result})

    def read(self):
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if 'id' in message and 'method' not in message:
                slot = self.pending.get(message['id'])
                if slot:
                    slot[1] = message
                    slot[0].set()
            elif 'id' in message:
                # Answered later (approvals wait for the user).
                self.on_request(message['id'], message['method'], message.get('params') or {})
            else:
                self.on_notification(message['method'], message.get('params') or {})
        log('codex app-server exited')
        os._exit(1)


class Store:
    """Chat history per conversation (JSON lines) and the conversation index."""

    def __init__(self):
        (DATA / 'conversations').mkdir(parents=True, exist_ok=True)
        self.index_path = DATA / 'index.json'
        try:
            self.index = json.loads(self.index_path.read_text())
        except (OSError, ValueError):
            self.index = {}

    def save_index(self):
        tmp = self.index_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.index, ensure_ascii=False))
        os.replace(tmp, self.index_path)

    def touch(self, thread_id, title=None):
        entry = self.index.setdefault(thread_id, {'title': '新对话', 'created': time.time()})
        if title and entry.get('title') in (None, '', '新对话'):
            entry['title'] = title[:40]
        entry['updated'] = time.time()
        self.save_index()

    def append(self, thread_id, event):
        with open(DATA / 'conversations' / f'{thread_id}.jsonl', 'a') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')

    def history(self, thread_id):
        path = DATA / 'conversations' / f'{thread_id}.jsonl'
        if not path.exists():
            return []
        events = []
        for line in path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        return events

    def delete(self, thread_id):
        self.index.pop(thread_id, None)
        self.save_index()
        (DATA / 'conversations' / f'{thread_id}.jsonl').unlink(missing_ok=True)

    def preview(self, thread_id):
        """The conversation's last word for the list (docs/59): the latest message, or
        how its latest call ended. Read from the file's tail only."""
        path = DATA / 'conversations' / f'{thread_id}.jsonl'
        try:
            with open(path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 65536))
                lines = f.read().decode('utf-8', 'replace').splitlines()
        except OSError:
            return ''
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('type') == 'message' and event.get('text'):
                return event['text'].strip().split('\n')[0][:80]
            if event.get('type') == 'call-ended':
                return '通话结束'
        return ''

    def listing(self, assistant=None):
        items = [dict(id=k, **v, preview=self.preview(k), assistant=k == assistant) for k, v in self.index.items()]
        return sorted(items, key=lambda e: e.get('updated', 0), reverse=True)


class PauseGate:
    """Shortens pauses in push-to-talk audio (see PAUSE_KEEP_MS).

    A 20 ms frame counts as a pause when it is quieter than the press's noise
    floor (a low percentile of the levels so far) by less than 10 dB, and at
    least 12 dB below its loudest speech. Only the middle of a pause is dropped:
    its first PAUSE_KEEP_MS and its last PAUSE_PREROLL_MS (soft onsets) are sent.
    """
    FRAME = RATE * 2 * 20 // 1000

    def __init__(self):
        self.levels = []
        self.peak = -120.0
        self.quiet_ms = 0
        self.held = []           # dropped frames kept for the preroll
        self.dropped_ms = 0
        self.rest = b''

    @staticmethod
    def level(frame):
        samples = array.array('h', frame)
        rms = math.sqrt(sum(x * x for x in samples) / max(1, len(samples)))
        return 20 * math.log10(max(rms, 1.0) / 32768)

    def quiet(self, db):
        self.levels.append(db)
        if len(self.levels) > 500:           # the last 10 s
            del self.levels[0]
        self.peak = max(self.peak, db)
        ordered = sorted(self.levels)
        floor = ordered[len(ordered) // 5]
        return db < min(max(floor + 10, -55.0), self.peak - 12)

    def feed(self, data):
        """Audio to send for this input (possibly less, possibly held frames first)."""
        data = self.rest + data
        cut = len(data) - len(data) % self.FRAME
        self.rest = data[cut:]
        out = []
        for i in range(0, cut, self.FRAME):
            frame = data[i:i + self.FRAME]
            if not self.quiet(self.level(frame)):
                out.extend(self.held)
                self.held = []
                self.quiet_ms = 0
                out.append(frame)
                continue
            self.quiet_ms += 20
            if self.quiet_ms <= PAUSE_KEEP_MS:
                out.append(frame)
            else:
                self.held.append(frame)
                if len(self.held) > PAUSE_PREROLL_MS // 20:
                    self.held.pop(0)
                    self.dropped_ms += 20
        return b''.join(out)

    def finish(self):
        """At release: the rest of the input; the pause that follows ends the turn."""
        rest, self.rest, self.held = self.rest, b'', []
        return rest


class Endpointer:
    """Whether speech has been heard, and whether it has ended (hands-free).

    A 20 ms frame is speech when it is at least 12 dB above the noise floor (a low
    percentile of the levels so far) and above -50 dBFS: absolute, unlike PauseGate,
    so that a press that began in silence tells noise from speech.
    """
    FRAME = RATE * 2 * 20 // 1000

    def __init__(self):
        self.levels = []
        self.speech_ms = 0
        self.quiet_ms = 0
        self.rest = b''

    @property
    def heard(self):
        return self.speech_ms >= 200

    @property
    def ended(self):
        return self.heard and self.quiet_ms >= HANDS_FREE_END_MS

    def feed(self, data):
        """Returns the loudest frame level of `data` (dBFS) for the UI."""
        data = self.rest + data
        cut = len(data) - len(data) % self.FRAME
        self.rest = data[cut:]
        loudest = -120.0
        for i in range(0, cut, self.FRAME):
            db = PauseGate.level(data[i:i + self.FRAME])
            loudest = max(loudest, db)
            self.levels.append(db)
            if len(self.levels) > 500:
                del self.levels[0]
            floor = sorted(self.levels)[len(self.levels) // 5]
            if db > max(floor + 12, -50.0):
                self.speech_ms += 20
                self.quiet_ms = 0
            else:
                self.quiet_ms += 20
        return loudest


class VoiceAgent:
    def __init__(self, emit):
        Gst.init(None)
        self.emit_raw = emit
        self.store = Store()
        self.thread_id = None
        self.realtime = False
        self.realtime_ready = threading.Event()
        # The open conversation's Codex thread is resumed in the background (resume reads the
        # whole rollout: seconds for one full of screenshots); what needs Codex waits on this.
        self.resumed = threading.Event()
        self.resumed.set()
        self.open_generation = 0
        self.talking = False
        self.agent_busy = False
        self.muted = False
        self.turn_id = None
        self.turn_started = 0.0
        self.last_voice = 0.0     # last reply audio or progress request
        # The turn in words (task_state, docs/89) and what the voice already told of it.
        self.turn = None
        self.turn_lock = threading.Lock()
        self.task_pending = False
        self.told = {}
        self.screen_seen = 0.0       # time of the last screen caption taken in (docs/88)
        # Who looks: the app and the overlay say whether they are on screen (SetWatching, by
        # D-Bus sender); the phone's own screen must be on and showing Plasma too.
        self.watchers = {}
        self.foreground = (True, 0.0)
        self.playing_until = 0.0
        self.reply_audio_ms = 0
        self.reply_sink = None
        self.mic_chunks = 0
        self.last_activity = time.monotonic()
        self.approvals = {}       # our id -> (json-rpc id, kind)
        self.lock = threading.RLock()
        self.player = None
        self.recorder = None
        self.mic_buffer = b''
        self.gate = PauseGate()
        # A press's audio stays here until it is sent (docs/87): released to send, it goes up
        # at once; cancelled or turned into text, nothing reached the realtime session, whose
        # input buffer could not be cleared (app-server has no such call) and would have
        # joined the dropped words to the next press.
        # "朗读" (docs/87): the voice says an answer again; that speech is not a new message.
        self.aloud_pending = False   # asked; the next assistant segment is the reading
        self.aloud_items = set()     # transcript segments of readings: heard, never shown
        self.held = []               # gated chunks of this press, not yet uploaded
        self.press_audio = b''       # all of this press, for speech-to-text
        self.call = None             # the proxied call, when the assistant talks in a call (docs/63)
        self.owner_audio = None      # what the user says to the call agent while talking
        # Id of the current push-to-talk press: the UI shows all transcript pieces
        # of one press as one message, however the server split them.
        self.press = 0
        self.endpointer = Endpointer()
        self.hands_free = False      # listening until speech ends, not until release
        self.talk_started = 0.0
        # Transcript segments being spoken or transcribed: item id -> (role, press, start time).
        self.segments = {}
        # thread/realtime/start was sent and neither started nor closed has come back:
        # a press in the meantime waits for that session instead of starting another.
        self.realtime_starting = False
        # Audio must reach the server in order: one sender thread, fixed chunks.
        self.uploads = queue.Queue()
        threading.Thread(target=self.upload_loop, daemon=True).start()
        self.prefs = preferences()
        self.key_working = None      # the last test of the API key: True, False, or not tested
        self.installer = None        # a Codex installation under way
        self.server = None
        # The workspace comes up with the service, ready before the first task needs it.
        threading.Thread(target=workspace_env, kwargs={'wait': 20}, daemon=True).start()
        self.start_server()
        GLib.timeout_add_seconds(30, self.idle_check)

    def start_server(self):
        """codex app-server; without Codex (not installed yet) the service still runs, and
        what needs it says so (the setup prompt, docs/87)."""
        try:
            server = AppServer(self.on_notification, self.on_request)
            server.call('initialize', {'clientInfo': {'name': 'rungic-voice-agent', 'version': '1.0'},
                                       'capabilities': {'experimentalApi': True}})
            server.notify('initialized')
            self.server = server
        except (FileNotFoundError, TimeoutError, RuntimeError) as error:
            log('codex app-server not started:', error)
            self.server = None

    def restart_server(self):
        """A new key, sign-in or installation: Codex reads them when it starts. The open
        conversation is closed; the app reopens it (agent-restarted)."""
        with self.lock:
            open_id = self.thread_id
            self.close_conversation()
            old, self.server = self.server, None
            if old:
                try:
                    old.proc.terminate()
                except OSError:
                    pass
            self.start_server()
        self.emit_raw({'type': 'agent-restarted', 'conversation': open_id, 'time': time.time()})

    def needs_setup(self, voice):
        """What is missing before the agent can work, as a prompt in the conversation."""
        if not self.server:
            self.emit({'type': 'message', 'role': 'assistant', 'id': f'setup-{time.time_ns()}',
                       'text': '这件事需要 Codex 来操作手机，但它还没有安装。'}, keep=False)
            self.emit({'type': 'setup', 'text': '还差一步：安装 Codex', 'detail': '装好之后我就能替你做事。',
                       'page': 'codex'}, keep=False)
            return True
        if voice and not openai_key():
            self.emit({'type': 'message', 'role': 'assistant', 'id': f'setup-{time.time_ns()}',
                       'text': '语音要用 OpenAI API Key 连上 OpenAI，现在还没有配置。'}, keep=False)
            self.emit({'type': 'setup', 'text': '还差一步：配置 OpenAI API Key', 'detail': '配好之后就能直接说话；打字也可以先用。',
                       'page': 'key'}, keep=False)
            return True
        return False

    # ---- events -------------------------------------------------------------
    def emit(self, event, keep=True):
        event.setdefault('time', time.time())
        if self.thread_id:
            event.setdefault('conversation', self.thread_id)
            if keep:
                self.store.append(self.thread_id, event)
        self.emit_raw(event)

    def set_state(self):
        self.emit({'type': 'state', **self.state()}, keep=False)
        return False

    def state(self):
        if not self.thread_id:
            phase = 'closed'
        elif self.talking:
            phase = 'listening'
        elif time.monotonic() < self.playing_until:
            phase = 'speaking'
        elif self.agent_busy:
            phase = 'working'
        elif not self.realtime:
            phase = 'connecting'
        else:
            phase = 'ready'
        call_phase = self.call.phase if self.call and self.call.phase in ('agent', 'user') else None
        return {'conversation': self.thread_id, 'phase': phase, 'agentBusy': self.agent_busy,
                'handsFree': self.talking and self.hands_free, 'assistant': self.thread_id == self.assistant_id(),
                'call': call_phase == 'agent', 'callPhase': call_phase}

    # ---- conversations ----------------------------------------------------------
    def thread_settings(self):
        # update_plan is off unless configured (codex config resolve_update_plan_enabled):
        # its plan is the task card's checklist and the voice's milestones (docs/89).
        config = {'model_reasoning_effort': AGENT_EFFORT, 'tools.update_plan.enabled': True}
        # The agent works in its own workspace (docs/research/91): its commands and its desktop
        # tools see that KWin only, so whatever it opens appears there from the first frame.
        # Codex starts MCP servers with a few variables only (rungic-cua fills in the user's
        # session for the rest), so they go to the server explicitly.
        env = workspace_env()
        if env:
            config['shell_environment_policy.set'] = env
            config['mcp_servers.rungic-desktop.env'] = env
        # Full access without approval prompts (the user's choice, docs/59): the
        # sandbox could not reach the desktop and every approval interrupted work.
        return {'cwd': str(Path.home()), 'sandbox': 'danger-full-access', 'approvalPolicy': 'never',
                'model': AGENT_MODEL, 'config': config, 'developerInstructions': prompt('agent.md')}

    def open_conversation(self, thread_id, connect=True):
        """Open a conversation. What the app shows comes from our own store and returns at
        once; the Codex thread is resumed in the background (docs/59): only talking needs it,
        and resuming reads the whole rollout (2.7 s for one of 8 MB, screenshots included)."""
        with self.lock:
            if thread_id and thread_id == self.thread_id:
                # Already open (the app showing the assistant's conversation): reopening
                # would cut the realtime session in the middle of a reply.
                if connect and not self.realtime:
                    threading.Thread(target=self.start_realtime, daemon=True).start()
                return {'conversation': thread_id,
                        'title': self.store.index.get(thread_id, {}).get('title', '新对话'),
                        'history': self.store.history(thread_id)}
            self.close_conversation()
            self.open_generation += 1
            if thread_id:
                self.thread_id = thread_id
                self.resumed = threading.Event()
                threading.Thread(target=self.resume_thread, args=(thread_id, self.open_generation, self.resumed),
                                 daemon=True).start()
                self.store.touch(self.thread_id)
            else:
                # A new thread: its id comes from Codex, and starting one is quick.
                if not self.server:
                    self.needs_setup(False)
                    raise RuntimeError('Codex 还没有安装')
                result = self.server.call('thread/start', self.thread_settings())
                self.thread_id = result['thread']['id']
                self.resumed = threading.Event()
                self.resumed.set()
            self.last_activity = time.monotonic()
            log('open', self.thread_id, 'resuming' if thread_id else 'new')
            history = self.store.history(self.thread_id)
            if connect:
                threading.Thread(target=self.start_realtime, daemon=True).start()
            GLib.idle_add(self.set_state)
            return {'conversation': self.thread_id,
                    'title': self.store.index.get(self.thread_id, {}).get('title', '新对话'),
                    'history': history}

    def resume_thread(self, thread_id, generation, resumed):
        started = time.monotonic()
        if not self.server:
            return
        try:
            self.server.call('thread/resume', {'threadId': thread_id, **self.thread_settings()})
        except Exception as error:  # noqa: BLE001
            log('resume', thread_id, 'failed:', error)
            with self.lock:
                if generation != self.open_generation:
                    return
                if thread_id == self.assistant_id():
                    # Codex saves a thread once it has a turn: one never talked in is gone after a
                    # restart. Start the assistant a new one; the overlay reopens it.
                    if not self.store.history(thread_id):
                        self.store.delete(thread_id)
                    result = self.server.call('thread/start', self.thread_settings())
                    self.thread_id = result['thread']['id']
                    (DATA / 'assistant.json').write_text(json.dumps({'thread': self.thread_id}))
                    self.store.touch(self.thread_id, '语音助手')
                    resumed.set()
                    self.emit({'type': 'assistant-reset'}, keep=False)
                else:
                    self.emit({'type': 'error', 'text': f'无法恢复这个对话：{error}'})
            return
        if generation != self.open_generation:
            log('resumed', thread_id, 'after another was opened: left alone')
            return
        log('resumed', thread_id, f'in {time.monotonic() - started:.1f} s')
        resumed.set()

    def start_realtime(self):
        # The thread must be resumed in Codex first (open_conversation resumes it behind).
        thread_id, resumed = self.thread_id, self.resumed
        if not resumed.wait(60) or self.thread_id != thread_id:
            return
        with self.lock:
            if self.realtime or self.realtime_starting or not self.thread_id or not self.server:
                return
            if not openai_key():
                return
            # A second start while the first is under way replaced the session and
            # dropped the audio sent to the first (a press right after opening).
            self.realtime_starting = True
            self.realtime_ready.clear()
            try:
                self.server.call('thread/realtime/start', {
                    'threadId': self.thread_id, 'model': REALTIME_MODEL,
                    'outputModality': 'audio', 'transport': {'type': 'websocket'},
                    # Instructions of the realtime model itself (replaces Codex's default,
                    # which prompts/realtime.md includes).
                    'prompt': prompt('realtime.md')})
            except Exception as error:
                self.realtime_starting = False
                self.emit({'type': 'error', 'text': f'语音连接失败：{error}'})
                return
        if not self.realtime_ready.wait(20):
            self.realtime_starting = False   # never started: the next press tries again

    def stop_realtime(self):
        if self.realtime and self.thread_id:
            try:
                self.server.call('thread/realtime/stop', {'threadId': self.thread_id}, timeout=5)
            except Exception:
                pass
        self.realtime = False
        self.realtime_starting = False
        self.realtime_ready.clear()
        self.segments.clear()
        GLib.idle_add(self.stop_audio)

    def close_conversation(self, thread_id=None):
        """Close the open conversation (only if it is `thread_id`, when given)."""
        with self.lock:
            if thread_id and thread_id != self.thread_id:
                return
            if self.thread_id:
                self.stop_realtime()
                log('close', self.thread_id)
            self.thread_id = None
            GLib.idle_add(self.set_state)

    # ---- the assistant's conversation (Home held, docs/67) -------------------------
    def assistant_id(self):
        try:
            return json.loads((DATA / 'assistant.json').read_text()).get('thread')
        except (OSError, ValueError):
            return None

    def open_assistant(self, connect=False):
        """The one conversation the Home button talks in, open (and warm) without
        the realtime link unless `connect`. Returns what open_conversation returns."""
        with self.lock:
            wanted = self.assistant_id()
            if wanted and self.thread_id == wanted:
                if connect and not self.realtime:
                    threading.Thread(target=self.start_realtime, daemon=True).start()
                return {'conversation': wanted, 'title': self.store.index.get(wanted, {}).get('title', '语音助手'),
                        'history': self.store.history(wanted)}
            if wanted:
                opened = self.open_conversation(wanted, connect)   # resumes behind; resume_thread replaces a lost one
            else:
                opened = self.open_conversation('', connect)
                (DATA / 'assistant.json').write_text(json.dumps({'thread': opened['conversation']}))
            self.store.touch(opened['conversation'], '语音助手')
            opened['title'] = self.store.index[opened['conversation']]['title']
            return opened

    def warm(self):
        """At service start and whenever no other conversation is open: the assistant's
        conversation resumed and the microphone pipeline built, so that holding Home
        only has to open the realtime link (and audio waits for it, not the user)."""
        GLib.idle_add(self.ensure_recorder)
        try:
            if not self.thread_id:
                self.open_assistant(connect=False)
                log('warm: assistant conversation', self.thread_id)
        except Exception as error:  # noqa: BLE001
            log('warm', error)

    def delete_conversation(self, thread_id):
        if thread_id == self.thread_id:
            self.close_conversation()
        was_assistant = thread_id == self.assistant_id()
        try:
            self.server.call('thread/archive', {'threadId': thread_id}, timeout=10)
        except Exception as error:
            log('archive failed', error)
        self.store.delete(thread_id)
        if was_assistant:
            # The Home button's conversation starts over (the overlay asks for it again).
            (DATA / 'assistant.json').unlink(missing_ok=True)
            self.emit_raw({'type': 'assistant-reset'})

    def idle_check(self):
        if self.realtime and not self.talking and not self.agent_busy \
                and time.monotonic() - self.last_activity > IDLE_STOP_S:
            log('idle: stopping realtime session')
            threading.Thread(target=self.stop_realtime, daemon=True).start()
            GLib.idle_add(self.set_state)
        return True

    # ---- audio (main loop thread) ------------------------------------------------
    def ensure_player(self):
        if self.player is None:
            # Reply audio arrives in bursts, faster or slower than it plays. Stamping
            # buffers with their arrival time (do-timestamp) made pulsesink "resync":
            # it dropped up to a second of speech or inserted silence. Play the samples
            # strictly in order instead and let PulseAudio pace them (sync=false).
            self.player = Gst.parse_launch(
                'appsrc name=src format=bytes do-timestamp=false block=false '
                f'caps=audio/x-raw,format=S16LE,rate={RATE},channels=1,layout=interleaved '
                '! queue max-size-time=0 max-size-bytes=0 max-size-buffers=0 '
                '! audioconvert ! audioresample ! pulsesink name=out sync=false buffer-time=300000')
            if self.reply_sink:
                self.player.get_by_name('out').set_property('device', self.reply_sink)
            self.player_src = self.player.get_by_name('src')
            bus = self.player.get_bus()
            bus.add_signal_watch()
            bus.connect('message::error', lambda _bus, message: log('player error', message.parse_error()[0].message))
            self.player.set_state(Gst.State.PLAYING)

    def stop_audio(self):
        """Drop queued reply audio (barge-in, close)."""
        if self.player is not None:
            self.player.set_state(Gst.State.NULL)
            self.player = None
        was_speaking = time.monotonic() < self.playing_until
        self.playing_until = 0.0
        if was_speaking:
            self.set_state()
        return False

    def start_talking(self, sink=None):
        if self.call and self.call.phase == 'user':
            return False     # the user is on the phone themselves: the assistant is paused
        self.last_activity = time.monotonic()
        self.muted = False
        self.reply_sink = sink
        if not self.thread_id:
            return False
        if self.needs_setup(True):
            self.set_state()
            return False
        if not self.realtime:
            threading.Thread(target=self.start_realtime, daemon=True).start()
        self.stop_audio()           # barge in: stop speaking at once
        self.talking = True
        self.ensure_recorder()
        self.mic_buffer = b''
        self.gate = PauseGate()
        self.held = []
        self.press_audio = b''
        self.endpointer = Endpointer()
        self.hands_free = False
        self.talk_started = time.monotonic()
        # During a proxied call the user talks to the call agent: keep the audio
        # here instead of sending it to the assistant's own realtime session.
        self.owner_audio = b'' if self.call and self.call.active else None
        self.press = int(time.time() * 1000)
        self.recorder.set_state(Gst.State.PLAYING)
        self.mic_chunks = 0
        log('talk: start, reply on', self.reply_sink or 'default sink')
        # The UI puts the user's bubble in place at once (docs/87): the transcript comes after
        # the release, and the reply can begin before it, so the bubble cannot wait for it.
        if self.owner_audio is None:
            self.emit({'type': 'talk-started', 'press': self.press}, keep=False)
        self.set_state()
        return False

    def ensure_recorder(self):
        if self.recorder is None:
            self.recorder = Gst.parse_launch(
                f'pulsesrc device={MIC} ! audioconvert ! audioresample '
                f'! audio/x-raw,format=S16LE,rate={RATE},channels=1 '
                f'! appsink name=sink emit-signals=true sync=false blocksize={RATE * 2 * CHUNK_MS // 1000}')
            self.recorder.get_by_name('sink').connect('new-sample', self.on_microphone)
            self.recorder.set_state(Gst.State.READY)
        return False

    def release_talking(self):
        """The hold ended: what was said is complete, unless nothing has been said yet
        (a quick press): then listen on hands-free until speech ends (like Siri)."""
        if not self.talking:
            return False
        if self.owner_audio is None and not self.endpointer.heard:
            self.hands_free = True
            log('talk: released before speech, listening hands-free')
            self.set_state()
            return False
        return self.stop_talking()

    def start_listening(self, sink=None):
        """Hands-free from the start (a tap on the orb)."""
        self.start_talking(sink)
        if self.talking:
            self.hands_free = True
            self.set_state()
        return False

    def cancel_talking(self):
        """Hands-free heard nothing, or the overlay was dismissed while listening: close
        the microphone and send nothing more (what was sent stays below a turn: no stop)."""
        if not self.talking:
            return False
        self.talking = False
        self.hands_free = False
        if self.recorder is not None:
            self.recorder.set_state(Gst.State.READY)
        self.mic_buffer = b''
        self.held = []
        self.press_audio = b''
        log('talk: cancelled, nothing sent')
        self.emit({'type': 'listen-cancelled', 'press': self.press}, keep=False)
        self.set_state()
        return False

    def stop_talking(self):
        if not self.talking:
            return False
        if self.owner_audio is None and not self.endpointer.heard:
            return self.cancel_talking()         # nothing was said: send nothing
        self.talking = False
        self.hands_free = False
        self.last_activity = time.monotonic()
        if self.recorder is not None:
            # The microphone is open only while talking; READY keeps the pipeline built.
            self.recorder.set_state(Gst.State.READY)
        if self.owner_audio is not None:
            audio, self.owner_audio = self.owner_audio + self.mic_buffer, None
            self.mic_buffer = b''
            log(f'talk: {len(audio) // 48} ms for the call agent')
            threading.Thread(target=self.instruct_call, args=(audio,), daemon=True).start()
            self.set_state()
            return False
        log(f'talk: stop after {self.mic_chunks * CHUNK_MS} ms of audio, {self.gate.dropped_ms} ms of pauses left out')
        rest = self.gate.feed(self.mic_buffer) + self.gate.finish()
        self.mic_buffer = b''
        for chunk in self.held:
            self.uploads.put(chunk)
        self.held = []
        self.press_audio = b''
        if rest:
            self.uploads.put(rest)
        self.uploads.put(bytes(RATE * 2 * END_SILENCE_MS // 1000))
        self.emit({'type': 'talk-sent', 'press': self.press}, keep=False)
        self.set_state()
        return False

    def on_microphone(self, sink):
        sample = sink.emit('pull-sample')
        if not self.talking:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            if self.owner_audio is not None:
                self.owner_audio += bytes(info.data)
                buf.unmap(info)
                return Gst.FlowReturn.OK
            data = bytes(info.data)
            buf.unmap(info)
            self.mic_buffer += data
            self.press_audio += data
            level = self.endpointer.feed(data)
            self.emit({'type': 'level', 'db': round(level, 1)}, keep=False)
            if self.hands_free:
                elapsed = time.monotonic() - self.talk_started
                if (self.endpointer.ended and self.prefs['handsFreeAutoSend']) or elapsed > HANDS_FREE_MAX_S:
                    GLib.idle_add(self.stop_talking)
                elif not self.endpointer.heard and elapsed > HANDS_FREE_NO_SPEECH_S:
                    GLib.idle_add(self.cancel_talking)
            chunk = RATE * 2 * CHUNK_MS // 1000
            while len(self.mic_buffer) >= chunk:
                send = self.gate.feed(self.mic_buffer[:chunk])
                if send:
                    self.held.append(send)
                self.mic_buffer = self.mic_buffer[chunk:]
                self.mic_chunks += 1
        return Gst.FlowReturn.OK

    def upload_loop(self):
        while True:
            self.append_audio(self.uploads.get())

    def append_audio(self, data):
        if not self.realtime_ready.wait(15) or not self.thread_id:
            return
        try:
            self.server.call('thread/realtime/appendAudio', {'threadId': self.thread_id, 'audio': {
                'data': base64.b64encode(data).decode(), 'sampleRate': RATE, 'numChannels': 1,
                'samplesPerChannel': len(data) // 2}}, timeout=10)
        except Exception as error:
            log('appendAudio', error)

    def call_in_progress(self) -> bool:
        return bool(self.call and self.call.phase in ('agent', 'user'))

    def play(self, audio, owner=False):
        """Reply audio. During a call only what the call assistant has for the user (`owner`)
        plays: the assistant's own replies and progress spoke over the call (docs/63)."""
        if not owner and self.call_in_progress():
            return False
        if self.talking:
            log('reply audio dropped while talking')
            return False
        if self.muted or not self.prefs['speak']:
            return False
        data = base64.b64decode(audio['data'])
        rate = audio.get('sampleRate', RATE)
        self.ensure_player()
        was_speaking = time.monotonic() < self.playing_until
        self.playing_until = max(self.playing_until, time.monotonic()) + len(data) / 2 / rate
        self.player_src.emit('push-buffer', Gst.Buffer.new_wrapped(data))
        self.reply_audio_ms += len(data) * 1000 // 2 // rate
        if not was_speaking:
            self.set_state()
            GLib.timeout_add(int((self.playing_until - time.monotonic()) * 1000) + 200, self.speaking_check)
        return False

    def speaking_check(self):
        if time.monotonic() < self.playing_until:
            GLib.timeout_add(int((self.playing_until - time.monotonic()) * 1000) + 200, self.speaking_check)
        else:
            log(f'reply audio: {self.reply_audio_ms} ms played')
            self.reply_audio_ms = 0
            self.set_state()
        return False

    # ---- spoken progress (main loop thread) ----------------------------------------
    def start_progress(self):
        GLib.timeout_add_seconds(1, self.progress_tick)
        return False

    def progress_tick(self):
        if not self.agent_busy:
            return False
        # What it is doing on the assistant's screen (docs/88) joins the turn's current step.
        # A live picture with it (a Blender render's passes, docs/90) goes on the task card.
        screen = screen_activity()
        if screen.get('time', 0) > self.screen_seen:
            self.screen_seen = screen['time']
            with self.turn_lock:
                changed = self.turn is not None and (
                    (screen.get('state') == 'working' and bool(screen.get('text')) and self.turn.on_screen(screen['text']))
                    | self.turn.on_live(screen))
            if changed:
                self.task_changed()
        if not self.realtime:
            return True
        now = time.monotonic()
        if self.call_in_progress():
            self.last_voice = now          # the call is what the user hears now
            return True
        if self.talking:
            self.last_voice = now
        self.last_voice = max(self.last_voice, self.playing_until)
        if now - self.turn_started < PROGRESS_AFTER_S:
            return True
        if self.approvals:
            self.last_voice = now     # waiting for the user, who was already asked
            return True
        with self.turn_lock:
            reason = self.progress_reason(now)
            facts = self.turn.facts() if reason and self.turn else ''
        if not reason:
            return True
        elapsed = now - self.turn_started
        tone = '语气平稳、让人安心。'
        if elapsed >= APOLOGY_AFTER_S and not self.told.get('apology'):
            self.told['apology'] = True
            tone = '已经等了一阵，语气平和，简短地为久等致歉一次。'
        text = (f'进度（系统给你的进度信息，不是用户说的话；直接对用户说一句，不要回应这条信息本身）\n{facts}\n{reason}只说上面列出的事实：“已完成”才说成做完了，“进行中”“此刻正在”说成正在做，'
                f'“打算”说成打算；不要补充没列出的内容，也不要重复上一次说过的话。{tone}')
        self.last_voice = now
        threading.Thread(target=self.speak_progress, args=(text,), daemon=True).start()
        return True

    def progress_reason(self, now):
        """Why to speak now, as the instruction for the voice, or None (docs/89). Milestones
        first; the screen shows everything else, so the voice waits longer while someone looks."""
        turn, told = self.turn, self.told
        if turn is None:
            return None
        watched = self.user_watching()
        quiet = now - self.last_voice
        if quiet < (GAP_WATCHED_S if watched else GAP_AWAY_S):
            return None
        plan = turn.plan
        if len(plan) >= 2 and not told.get('plan'):
            told['plan'] = True
            told['step'] = turn.step_now()
            return '用一句话告诉用户打算分几步做（按上面的计划简短概括）。'
        step = turn.step_now()
        if plan and step and step != told.get('step'):
            told['step'] = step
            return '用一句很短的话告诉用户现在进行到哪一步了。'
        current = turn.current
        key = f"{current['id']}|{current['text']}" if current else ''
        if current:
            running = time.time() - current['since']
            again = LONG_AGAIN_WATCHED_S if watched else LONG_AGAIN_AWAY_S
            times = told.setdefault('long', {}).get(key, 0)
            if running >= LONG_STEP_S and times < 2 and (times == 0 or quiet >= again):
                told['long'][key] = times + 1
                return '这一步用时较长：用一句话告诉用户它还在进行、进行到什么程度（有百分比或数量就说）。'
        # Codex hands its own commentary to the voice already ([BACKEND] messages): no second
        # telling of intentions here.
        if not plan:
            if current and key != told.get('activity') and time.time() - current['since'] >= 4 \
                    and (not watched or quiet >= 30):
                told['activity'] = key
                return '用一句很短的话告诉用户此刻在做什么。'
        if not told.get('still') and now - self.turn_started >= STILL_AFTER_S and quiet >= STILL_AFTER_S:
            told['still'] = True
            return '用一句很短的话告诉用户还在处理。'
        return None

    def user_watching(self):
        """Someone looks at the chat (app or overlay on screen) and the phone shows Plasma."""
        if not any(self.watchers.values()):
            return False
        shown, checked = self.foreground
        if time.monotonic() - checked > WATCHERS_FRESH_S:
            shown = platform_request({'op': 'status'}).get('foreground', True)
            self.foreground = (shown, time.monotonic())
        return bool(shown)

    def set_watching(self, sender, watching):
        self.watchers[sender] = bool(watching)

    def watcher_gone(self, sender):
        self.watchers.pop(sender, None)

    # ---- the turn in words (task_state, docs/89) ----------------------------------------
    def task_changed(self):
        """The card changed: tell the app, a few times a second at most."""
        if self.task_pending:
            return
        self.task_pending = True
        GLib.timeout_add(400, self.flush_task)

    def flush_task(self):
        self.task_pending = False
        with self.turn_lock:
            snapshot = self.turn.snapshot() if self.turn else None
        if snapshot is not None and self.agent_busy:
            self.emit({'type': 'task', **snapshot}, keep=False)
        return False

    def speak_progress(self, text):
        log('progress:', ' | '.join(line for line in text.splitlines()[1:] if line)[:400])
        try:
            self.server.call('thread/realtime/appendSpeech', {'threadId': self.thread_id, 'text': text}, timeout=10)
        except Exception as error:
            log('appendSpeech', error)

    # ---- codex events (reader thread) -----------------------------------------------
    def on_notification(self, method, params):
        if params.get('threadId') not in (None, self.thread_id):
            return
        if method == 'thread/realtime/outputAudio/delta':
            GLib.idle_add(self.play, params['audio'])
        elif method == 'thread/realtime/started':
            self.realtime = True
            self.realtime_starting = False
            self.realtime_ready.set()
            GLib.idle_add(self.set_state)
        elif method == 'thread/realtime/closed':
            self.realtime = False
            self.realtime_starting = False
            self.realtime_ready.clear()
            GLib.idle_add(self.set_state)
        elif method == 'thread/realtime/error':
            self.emit({'type': 'error', 'text': params.get('message', '')})
        # Transcripts by segment (item id), not the role-only transcript/delta and
        # transcript/done: the user's transcription often finishes after the reply
        # has begun streaming, and the chat has to tell the two streams apart.
        elif method == 'thread/realtime/item/started' and (params.get('item') or {}).get('type') == 'transcriptSegment':
            item = params['item']
            role = 'user' if item.get('role') == 'user' else 'assistant'
            if role == 'assistant' and self.aloud_pending:
                self.aloud_pending = False
                self.aloud_items.add(item['id'])
            self.segments[item['id']] = (role, self.press if role == 'user' else 0, time.time())
        elif method == 'thread/realtime/item/transcript/delta':
            if params.get('itemId') in self.aloud_items:
                return
            role, press, _ = self.segments.get(params.get('itemId'), ('assistant', 0, 0))
            event = {'type': 'delta', 'role': role, 'id': params.get('itemId'), 'text': params.get('delta', '')}
            if role == 'user':
                event['press'] = press
            self.emit(event, keep=False)
        elif method == 'thread/realtime/item/completed' and (params.get('item') or {}).get('type') == 'transcriptSegment':
            item = params['item']
            role, press, started = self.segments.pop(item['id'], ('user' if item.get('role') == 'user' else 'assistant', self.press, 0))
            if role != 'user':
                self.muted = False      # the reply cut by the stop button has ended
            if item['id'] in self.aloud_items:
                self.aloud_items.discard(item['id'])
                return                  # a reading: heard, not a message
            text = (item.get('text') or '').strip()
            if text:
                # When the segment began: an acknowledgement begun before agent work
                # stays a bubble above it, also when the history is replayed.
                event = {'type': 'message', 'role': role, 'id': item['id'], 'text': text, 'started': started}
                if role == 'user':
                    self.store.touch(self.thread_id, text)
                    event['press'] = press
                self.emit(event)
        elif method == 'turn/started':
            self.turn_id = (params.get('turn') or {}).get('id')
            self.agent_busy = True
            self.turn_started = self.last_voice = time.monotonic()
            with self.turn_lock:
                self.turn = task_state.TurnState()
            self.told = {}
            self.emit({'type': 'agent-started'})
            GLib.idle_add(self.set_state)
            GLib.idle_add(self.start_progress)
        elif method == 'turn/completed':
            self.turn_id = None
            self.agent_busy = False
            # A caption left "working" (a tool call cut short) must not stay on the screen.
            if screen_activity().get('state') == 'working':
                from rungic_cua import activity
                activity.report('', state='done')
            self.last_activity = time.monotonic()
            # The card as it ended stays with the history (plan, files, steps).
            with self.turn_lock:
                final = self.turn.snapshot() if self.turn else None
                self.turn = None
            if final and (final['plan'] or final['recent'] or final['files']):
                final.pop('current', None)
                self.emit({'type': 'task', 'final': True, **final})
            self.emit({'type': 'agent-finished'})
            GLib.idle_add(self.set_state)
        elif method in ('item/started', 'item/completed'):
            self.agent_item(method.endswith('completed'), params.get('item') or {})
            with self.turn_lock:
                changed = self.turn is not None and self.turn.on_item(params.get('item') or {}, method.endswith('completed'))
            if changed:
                GLib.idle_add(self.task_changed)
        elif method == 'turn/plan/updated':
            with self.turn_lock:
                if self.turn is not None:
                    self.turn.on_plan(params.get('plan') or [], params.get('explanation'))
            GLib.idle_add(self.task_changed)
        elif method == 'item/commandExecution/outputDelta':
            with self.turn_lock:
                changed = self.turn is not None and self.turn.on_output(params.get('itemId', ''), params.get('delta', ''))
            if changed:
                GLib.idle_add(self.task_changed)
        elif method == 'item/fileChange/patchUpdated':
            with self.turn_lock:
                changed = self.turn is not None and self.turn.on_patch(params.get('itemId', ''), params.get('changes') or [])
            if changed:
                GLib.idle_add(self.task_changed)
        elif method == 'account/login/completed':
            self.emit_raw({'type': 'account', 'success': bool(params.get('success')), 'error': params.get('error') or '',
                           'time': time.time()})
            if params.get('success'):
                threading.Thread(target=self.restart_server, daemon=True).start()

    def agent_item(self, completed, item):
        kind = item.get('type')
        if kind == 'commandExecution':
            self.emit({'type': 'command', 'id': item.get('id'), 'command': item.get('command', ''),
                       'status': 'done' if completed else 'running', 'exitCode': item.get('exitCode'),
                       'output': (item.get('aggregatedOutput') or '')[-4000:]}, keep=completed)
        elif kind == 'mcpToolCall':
            # Desktop operations (rungic-desktop MCP) shown like command cards.
            arguments = item.get('arguments') or {}
            label = arguments.get('goal') or arguments.get('app') or arguments.get('window_id') or ''
            output = ''
            if item.get('error'):
                output = str(item['error'].get('message', item['error']))
            elif item.get('result'):
                output = ''.join(c.get('text', '') for c in (item['result'].get('content') or []) if isinstance(c, dict))
            failed = item.get('status') == 'failed' or bool(item.get('error'))
            self.emit({'type': 'command', 'id': item.get('id'), 'command': f"{item.get('tool')} {label}".strip(),
                       'status': 'done' if completed else 'running', 'exitCode': (1 if failed else 0) if completed else None,
                       'output': output[-4000:]}, keep=completed)
        elif kind == 'fileChange' and completed:
            paths = [c.get('path', '') for c in item.get('changes', [])]
            self.emit({'type': 'files', 'id': item.get('id'), 'paths': paths, 'status': item.get('status')})
        elif kind == 'agentMessage' and completed and item.get('text'):
            if item.get('phase') != 'final_answer':
                with self.turn_lock:
                    if self.turn is not None:
                        self.turn.on_commentary(item['text'])
            self.emit({'type': 'agent-message', 'id': item.get('id'), 'text': item['text'],
                       'final': item.get('phase') == 'final_answer'})

    def on_request(self, request_id, method, params):
        if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
            approval = f'a{request_id}'
            self.approvals[approval] = request_id
            files = method.startswith('item/fileChange')
            self.emit({'type': 'approval', 'id': approval, 'kind': 'files' if files else 'command',
                       'text': (params.get('reason') or '修改文件') if files else (params.get('command') or ''),
                       'reason': params.get('reason') or '', 'status': 'pending'})
            # The task now waits for the user, not for the agent: say so at once.
            self.last_voice = time.monotonic()
            reason = params.get('reason') or ('修改文件' if files else command_summary(params.get('command') or ''))
            threading.Thread(target=self.speak_progress, daemon=True, args=(
                f'进度（任务暂停，等待用户批准）：{reason}\n'
                '用一句很短的话请用户在屏幕上的卡片里点「允许」或「拒绝」。',)).start()
        else:
            # Other requests (MCP elicitations, permission profiles ...) are not supported yet.
            log('declined request', method)
            self.server.respond(request_id, {'decision': 'decline'})

    # ---- proxied calls (docs/63) ------------------------------------------------------
    def start_call(self, params):
        """The assistant takes part in the call that the app has placed or received."""
        import call_proxy
        if self.call and self.call.active:
            self.call.stop('replaced')
        app = params.get('app') or 'wechat'

        def emit(event, keep=True):
            kind = event.get('type')
            if kind == 'call-phase' and event.get('phase') == 'user':
                # The user talks on the phone now: pause the assistant (its realtime
                # session would otherwise keep listening and could speak into the call).
                threading.Thread(target=self.stop_realtime, daemon=True).start()
                threading.Thread(target=self.watch_user_audio, daemon=True).start()
            elif kind == 'call-ended' and self.thread_id:
                threading.Thread(target=self.start_realtime, daemon=True).start()   # resume
                threading.Thread(target=self.speak_call_result, args=(event.get('reason'), event.get('summary') or ''),
                                 daemon=True).start()
            if kind in ('call-phase', 'call-ended'):
                GLib.idle_add(self.set_state)
            self.emit(event, keep)

        def hang_up():
            # The model finds the hang-up control in the call window (computer use plan one, docs/68).
            window = (self.call.window_id if self.call else None) or call_window(app)
            result = luna_goal('End the call that is in progress: press the hang-up (end call) control of the call '
                               'window. Press nothing else. Reply DONE once the call has ended.', timeout=60,
                               window=window)
            log('call: hang up', result.get('outcome'), result.get('answer') or result.get('note') or '',
                json.dumps(result.get('steps', []), ensure_ascii=False)[:1500])

        self.call = call_proxy.CallProxy(emit, self.tell_owner, app=app, contact=params.get('contact', ''),
                                         goal=params.get('goal', ''), owner=params.get('owner') or '凯文',
                                         monitor=bool(params.get('monitor')), incoming=bool(params.get('incoming')),
                                         hang_up=hang_up)
        self.call.on_answered = lambda: call_snapshot('answered')
        call = self.call
        self.call.confirm_connected = lambda: call_screen_connected(call.window_id or call_window(app))
        self.call.start()
        GLib.idle_add(self.set_state)
        # Dial only once the call agent can listen: the other side is heard from
        # their first word instead of after the setup (10-20 s when set up later).
        ready = self.call.ready.wait(20)
        result = {'started': True, 'ready': ready, 'contact': params.get('contact', ''), 'app': app}
        if params.get('dial') and ready:
            result.update(self.dial(app, params.get('contact', ''), params['dial']))
            if not result['dialed']:
                self.call.stop('dial failed')
        return result

    def dial(self, app, contact, control):
        """Place the call: the model looks at the chat on screen (computer use plan one, docs/68),
        checks the header shows `contact` and starts a voice call; the call counts as placed only
        when the app opens its call audio (a system signal, not the click), and the model is
        stopped at that moment so it presses nothing in the call window."""
        self.emit({'type': 'call-state', 'state': 'dialing'}, keep=False)
        before = self.call.streams_seen
        hint = f' (it may be labelled "{control}")' if control and control.isascii() and len(control) < 40 else ''
        goal = (f'The active window shows a chat. First check the name in the chat header: it must be {contact}. '
                f'If it is not, press nothing and reply FAILED. If it is, start a voice call (not a video call) with '
                f'{contact} from this chat{hint}: the phone button in the chat header may open a small menu first; '
                'then choose the voice call in it. As soon as a calling or ringing screen appears, stop at once and '
                'reply DONE. Never press anything in the call window.')
        result = luna_goal(goal, timeout=120, stop_when=lambda: self.call.streams_seen > before)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and self.call.streams_seen == before and result.get('outcome') != 'failed':
            time.sleep(0.2)
        placed = self.call.streams_seen > before
        if placed:
            self.call.window_id = call_window(app)
            log('call: call window', self.call.window_id)
            threading.Thread(target=lambda: (time.sleep(2), call_snapshot('ringing')), daemon=True).start()
            threading.Thread(target=self.call.watch_ringing, daemon=True).start()
        self.emit({'type': 'call-state', 'state': 'ringing' if placed else 'dial-failed'}, keep=False)
        return {'dialed': placed, 'confirmed_by': 'call audio opened' if placed else None,
                'outcome': result.get('outcome'), 'screen': result.get('answer') or result.get('note'),
                'actions': [a for step in result.get('steps', []) for a in step.get('actions', [])]}

    def watch_user_audio(self):
        """After a take-over, every 2 s: where WeChat's streams are, their latency and the
        load, for the stutter the user heard after taking over (docs/63)."""
        app = self.call.app if self.call else 'wechat'
        while self.call and self.call.phase == 'user':
            try:
                env = {**os.environ, 'LC_ALL': 'C'}
                inputs = subprocess.run(['pactl', 'list', 'sink-inputs'], capture_output=True, text=True, env=env,
                                        timeout=5).stdout.split('Sink Input #')[1:]
                streams = []
                for block in inputs:
                    if f'application.process.binary = "{app}"' in block:
                        sink = re.search(r'Sink: (\d+)', block)
                        latency = re.search(r'Sink Latency: (\d+)', block)
                        buffer = re.search(r'Buffer Latency: (\d+)', block)
                        streams.append(f"#{block.split(chr(10), 1)[0]} sink {sink.group(1) if sink else '?'} "
                                       f"buffer {int(buffer.group(1)) // 1000 if buffer else '?'} ms "
                                       f"sink {int(latency.group(1)) // 1000 if latency else '?'} ms")
                # (Android's side, the phone track's underruns, is in `dumpsys media.audio_flinger`
                # on the host: the container cannot read it.)
                load = open('/proc/loadavg').read().split()[:3]
                log('call audio:', '; '.join(streams) or 'no streams', '| load', ' '.join(load))
            except Exception as error:  # noqa: BLE001  (diagnostics only)
                log('call audio', error)
            time.sleep(2)

    def speak_call_result(self, reason, summary):
        """The assistant was quiet during the call; now one or two sentences on how it went."""
        if not self.realtime_ready.wait(20) or not self.thread_id:
            return
        time.sleep(0.5)
        text = (f'通话结束（{reason}）。' + (f'通话助理的总结：{summary}\n' if summary else '')
                + '用一两句话告诉用户结果，不要重复细节。')
        try:
            self.server.call('thread/realtime/appendSpeech', {'threadId': self.thread_id, 'text': text}, timeout=10)
        except Exception as error:  # noqa: BLE001
            log('call result', error)

    def call_command(self, command):
        call = self.call
        if not (call and call.phase in ('agent', 'user')):
            return
        if call.phase == 'user':
            # The user is on the phone themselves: only hanging up applies.
            if command == 'hang-up':
                call.hang_up()
                GLib.idle_add(self.set_state)
            return
        if command in ('monitor-on', 'monitor-off'):
            call.set_monitor(command == 'monitor-on')
        elif command == 'take-over':
            call.take_over()
        elif command == 'hang-up':
            call.hang_up()
        GLib.idle_add(self.set_state)

    def instruct_call(self, audio):
        import call_proxy
        try:
            text = call_proxy.transcribe(audio)
        except Exception as error:  # noqa: BLE001
            self.emit({'type': 'error', 'text': f'没听清你对通话助理说的话：{error}'})
            return
        if text and self.call and self.call.active:
            self.call.instruct(call_proxy.simplified(text))

    def tell_owner(self, text):
        """Speak to the user on their side (a question from the call agent)."""
        import call_proxy
        try:
            audio = call_proxy.synthesize(text)
        except Exception as error:  # noqa: BLE001
            log('tell_owner', error)
            return
        call = self.call
        if call and call.phase == 'agent':
            call.pause_monitor(len(audio) / 2 / call_proxy.RATE + 0.5)   # not over the call
        GLib.idle_add(self.play, {'data': base64.b64encode(audio).decode(), 'sampleRate': call_proxy.RATE}, True)

    def stop_task(self):
        """Stop button: interrupt the running agent turn and the reply being spoken."""
        # The rest of a reply already being spoken keeps arriving: drop it until it ends.
        self.muted = time.monotonic() < self.playing_until + 0.5
        GLib.idle_add(self.stop_audio)
        if not (self.agent_busy and self.thread_id and self.turn_id):
            return
        log('stop task', self.turn_id)
        try:
            self.server.call('turn/interrupt', {'threadId': self.thread_id, 'turnId': self.turn_id}, timeout=10)
        except Exception as error:
            log('turn/interrupt', error)
            self.emit({'type': 'error', 'text': f'停止失败：{error}'})
            return
        self.emit({'type': 'task-stopped'})

    def approve(self, approval, decision):
        request_id = self.approvals.pop(approval, None)
        if request_id is None:
            return
        answer = {'allow': 'accept', 'allow-session': 'acceptForSession'}.get(decision, 'decline')
        self.server.respond(request_id, {'decision': answer})
        self.emit({'type': 'approval-result', 'id': approval, 'decision': answer})

    # ---- typed input, speech-to-text, reading aloud (docs/87) ---------------------------
    def send_text(self, text, attachments):
        """A typed message (with images or files): an agent turn of its own, started
        directly (turn/start); while one runs, Codex steers it with this instead."""
        text = text.strip()
        paths = [a['path'] for a in attachments if a.get('path')]
        if not text and not paths or not self.thread_id:
            return
        if self.needs_setup(False):
            return
        if not self.resumed.wait(60):
            raise RuntimeError('对话还没准备好')
        images = [p for p in paths if Path(p).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif')]
        others = [p for p in paths if p not in images]
        prompt_text = text
        if others:
            # Codex takes images as input; other files are named, and the agent reads them.
            prompt_text += '\n\n附件：\n' + '\n'.join(others)
        items = [{'type': 'text', 'text': prompt_text, 'text_elements': []}]
        items += [{'type': 'localImage', 'path': p} for p in images]
        self.store.touch(self.thread_id, text or Path(paths[0]).name)
        self.last_activity = time.monotonic()
        self.emit({'type': 'message', 'role': 'user', 'id': f'typed-{time.time_ns()}', 'text': text,
                   'typed': True, 'attachments': attachments})
        self.server.call('turn/start', {'threadId': self.thread_id, 'input': items})

    def talk_to_text(self):
        """The hold ended over "转文字": what was said comes back as text to edit; nothing
        is sent to the assistant."""
        if not self.talking:
            return ''
        audio = self.press_audio + self.mic_buffer
        self.cancel_talking()
        if len(audio) < RATE * 2 // 5:          # under 0.2 s
            return ''
        import call_proxy
        text = call_proxy.transcribe(audio)
        log(f'talk: {len(audio) // 48} ms turned into {len(text)} characters of text')
        return call_proxy.simplified(text)

    def read_aloud(self, text):
        """"朗读": the voice reads an answer out (the realtime session speaks it)."""
        if not self.thread_id or not text.strip():
            return
        if not self.realtime:
            threading.Thread(target=self.start_realtime, daemon=True).start()
        if not self.realtime_ready.wait(20):
            raise RuntimeError('语音连接还没准备好')
        self.muted = False
        self.aloud_pending = True
        self.speak_progress('把下面这段话原样读给用户听，不要增减内容，也不要评论：\n' + text.strip())

    # ---- settings (docs/87) ----------------------------------------------------------------
    def setup(self):
        from rungic_cua import keys
        path = shutil.which('codex', path=os.environ.get('PATH', '') + ':' + str(Path.home() / '.local/bin'))
        version, runs = '', None
        if path:
            try:
                out = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=20).stdout
                version = out.strip().split()[-1] if out.strip() else ''
                runs = bool(version)
            except (OSError, subprocess.SubprocessError):
                runs = False
        account = None
        if self.server:
            try:
                account = self.server.call('account/read', {'refreshToken': False}, timeout=10).get('account')
            except Exception as error:  # noqa: BLE001
                log('account/read', error)
        key = keys.read('openai-api-key')
        store = 'file'
        try:
            import tomllib
            config = tomllib.loads((Path.home() / '.codex/config.toml').read_text())
            store = config.get('cli_auth_credentials_store', 'file')
        except (OSError, ValueError):
            pass
        try:
            app_version = subprocess.run(['dpkg-query', '-W', '-f', '${Version}', 'rungic-voice-agent'],
                                         capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            app_version = ''
        return {'codex': {'installed': bool(path), 'version': version, 'path': path or '', 'runs': runs,
                          'running': self.server is not None},
                'account': account, 'credentials': 'keyring' if store in ('keyring', 'auto') else 'file',
                'key': {'set': bool(key), 'masked': (key[:3] + '…' + key[-4:]) if len(key) > 10 else ('已设置' if key else ''),
                        'store': keys.where('openai-api-key'), 'working': self.key_working},
                'preferences': self.prefs, 'version': app_version, 'home': str(Path.home())}

    @staticmethod
    def test_key(key):
        """Whether OpenAI accepts the key: (ok, error)."""
        request = urllib.request.Request('https://api.openai.com/v1/models', headers={'Authorization': 'Bearer ' + key})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status == 200, ''
        except urllib.error.HTTPError as error:
            return False, '密钥无效' if error.code in (401, 403) else f'OpenAI 返回 {error.code}'
        except (OSError, ValueError) as error:
            return False, f'连不上 OpenAI：{error}'

    def set_api_key(self, key):
        from rungic_cua import keys
        key = key.strip()
        ok, error = self.test_key(key)
        self.key_working = ok
        if not ok:
            return {'ok': False, 'error': error}
        where = keys.store('openai-api-key', key)
        log('api key stored in', where)
        # Codex signed in with an API key uses it for everything: sign in with the new one.
        try:
            account = self.server.call('account/read', {'refreshToken': False}, timeout=10).get('account') if self.server else None
            if account and account.get('type') == 'apiKey':
                self.server.call('account/login/start', {'type': 'apiKey', 'apiKey': key}, timeout=20)
        except Exception as error:  # noqa: BLE001
            log('api key sign-in', error)
        threading.Thread(target=self.restart_server, daemon=True).start()
        return {'ok': True, 'store': where}

    def test_api_key(self):
        key = openai_key()
        ok, error = self.test_key(key) if key else (False, '还没有设置密钥')
        self.key_working = ok
        return {'ok': ok, 'error': error}

    def remove_api_key(self):
        from rungic_cua import keys
        keys.clear('openai-api-key')
        self.key_working = None
        threading.Thread(target=self.restart_server, daemon=True).start()
        return {'ok': True}

    def codex_login(self, kind):
        if not self.server:
            return {'error': 'Codex 还没有安装'}
        if kind == 'apiKey':
            key = openai_key()
            if not key:
                return {'error': '先设置 API Key'}
            result = self.server.call('account/login/start', {'type': 'apiKey', 'apiKey': key}, timeout=30)
            threading.Thread(target=self.restart_server, daemon=True).start()
            return result
        return self.server.call('account/login/start', {'type': 'chatgptDeviceCode'}, timeout=30)

    def set_preferences(self, values):
        self.prefs = {k: bool(values.get(k, v)) for k, v in self.prefs.items()}
        CONFIG.mkdir(parents=True, exist_ok=True)
        (CONFIG / 'preferences.json').write_text(json.dumps(self.prefs))
        self.emit_raw({'type': 'preferences', **self.prefs, 'time': time.time()})
        return self.prefs

    def install_codex(self, method):
        """Installs Codex: the system package (polkit asks for the password) or the official
        script into ~/.local/bin; progress as `install` events."""
        if self.installer and self.installer.poll() is None:
            return {'error': '正在安装'}
        if method == 'script':
            command = ['sh', '-c', 'curl -fsSL https://chatgpt.com/codex/install.sh | sh']
        else:
            command = ['pkexec', 'env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install', '-y', 'rungic-codex']
        threading.Thread(target=self.run_installer, args=(command,), daemon=True).start()
        return {'ok': True}

    def run_installer(self, command):
        def event(**fields):
            self.emit_raw({'type': 'install', 'time': time.time(), **fields})
        event(step='download', state='running', line='$ ' + ' '.join(command))
        try:
            self.installer = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                              env={**os.environ, 'LANG': 'C.UTF-8'})
        except OSError as error:
            event(state='failed', error=str(error))
            return
        for line in self.installer.stdout:
            line = line.rstrip()
            step = 'install' if re.match(r'(Unpacking|Setting up|Installing|Extracting|正在)', line) else None
            event(line=line[:300], **({'step': step} if step else {}))
        code = self.installer.wait()
        if code in (-15, -9):
            event(state='cancelled')
            return
        if code != 0:
            event(state='failed', error=f'安装程序退出码 {code}')
            return
        event(step='check')
        self.restart_server()
        if not self.server:
            event(state='failed', error='装好了，但 Codex 运行不了')
            return
        event(step='connect')
        event(state='done')

    def cancel_install(self):
        if self.installer and self.installer.poll() is None:
            self.installer.terminate()
        return {'ok': True}


def call_window(app: str) -> str | None:
    """The app's topmost window, which is its call window during a call (KWin)."""
    try:
        out = subprocess.run(['rungic-cua', 'top-window', app], capture_output=True, text=True, timeout=20).stdout
        return (json.loads(out).get('window') or {}).get('id')
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def call_screen_connected(window_id: str | None) -> bool:
    """Whether the call window shows the call connected: a running call timer, not
    "calling" or "waiting". Only its top, where call apps show the timer; about 2 s
    (docs/63). The window itself, not the active one: the chat window was active once,
    and a call that was up went unnoticed."""
    try:
        args = ['window', window_id] if window_id else ['active-window']
        done = subprocess.run(['/usr/libexec/rungic-screenshot', *args], capture_output=True, timeout=10)
        if done.returncode != 0:
            return False
        end = done.stdout.index(b'\n')
        header = json.loads(done.stdout[:end])
        from PIL import Image
        modes = {4: 'BGRX', 5: 'BGRA', 6: 'BGRA', 16: 'RGBX', 17: 'RGBA', 18: 'RGBA'}
        image = Image.frombuffer('RGBA', (header['width'], header['height']), done.stdout[end + 1:], 'raw',
                                 modes.get(header.get('format'), 'BGRA'), header['stride'], 1).convert('RGB')
        top = image.crop((0, 0, image.width, max(60, image.height // 8)))
        buffer = io.BytesIO()
        top.save(buffer, 'JPEG', quality=85, subsampling=0)
        body = {'model': 'gpt-6-luna', 'reasoning': {'effort': 'none'}, 'max_output_tokens': 16, 'input': [
            {'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'This is the top of a call window. Is a running call-duration timer '
                                               '(like 00:05) shown? Answer only yes or no.'},
                {'type': 'input_image', 'detail': 'original',
                 'image_url': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode()}]}]}
        key = openai_key()
        request = urllib.request.Request('https://api.openai.com/v1/responses', data=json.dumps(body).encode(),
                                         headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=20) as response:
            reply = json.loads(response.read())
        text = ''.join(c.get('text', '') for o in reply.get('output', []) if o.get('type') == 'message'
                       for c in o.get('content', []))
        return text.strip().lower().startswith('yes')
    except Exception as error:  # noqa: BLE001  (not connected, as far as we know)
        log('call screen check', error)
        return False


def call_snapshot(tag: str) -> None:
    """Where the call's windows are, for diagnosis (docs/63): the window list in the log, and
    both screens as they look now in ~/.cache/rungic-voice-agent (the latest call only)."""
    try:
        info = json.loads(subprocess.run(['rungic-cua', 'windows'], capture_output=True, text=True, timeout=20).stdout)
        log(f'call: {tag}: windows', json.dumps([{k: w.get(k) for k in ('caption', 'app', 'screen', 'active', 'minimized')}
                                                 for w in info.get('windows', [])], ensure_ascii=False))
        directory = Path.home() / '.cache/rungic-voice-agent'
        directory.mkdir(parents=True, exist_ok=True)
        from PIL import Image
        for output in info.get('screens', []):
            done = subprocess.run(['/usr/libexec/rungic-screenshot', 'screen', output], capture_output=True, timeout=15)
            if done.returncode != 0:
                continue
            end = done.stdout.index(b'\n')
            header = json.loads(done.stdout[:end])
            modes = {4: 'BGRX', 5: 'BGRA', 6: 'BGRA', 16: 'RGBX', 17: 'RGBA', 18: 'RGBA'}
            image = Image.frombuffer('RGBA', (header['width'], header['height']), done.stdout[end + 1:], 'raw',
                                     modes.get(header.get('format'), 'BGRA'), header['stride'], 1).convert('RGB')
            image.thumbnail((960, 960))
            image.save(directory / f'call-{tag}-{output}.jpg', quality=80)
    except Exception as error:  # noqa: BLE001  (diagnostics only)
        log('call snapshot', tag, error)


def luna_goal(goal: str, timeout: float = 120, stop_when=None, window: str | None = None) -> dict:
    """A task for rungic-cua's computer use on the assistant's screen (docs/68), following the
    active window. `stop_when()` turning true stops the model before its next action, through
    the abort file its loop watches (the user's "stop" uses the same file)."""
    abort = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'rungic-clicker' / 'abort'
    abort.unlink(missing_ok=True)
    task = {'goal': goal, 'steps': 8, **({'window': window} if window else {})}
    process = subprocess.Popen(['rungic-cua', 'goal', json.dumps(task, ensure_ascii=False)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + timeout
    signalled = False
    while process.poll() is None and time.monotonic() < deadline:
        if stop_when and not signalled and stop_when():
            abort.parent.mkdir(parents=True, exist_ok=True)
            abort.touch()
            signalled = True
        time.sleep(0.2)
    if process.poll() is None:
        abort.parent.mkdir(parents=True, exist_ok=True)
        abort.touch()
        try:
            process.wait(15)
        except subprocess.TimeoutExpired:
            process.kill()
    out, err = process.communicate()
    abort.unlink(missing_ok=True)
    try:
        result = json.loads(out)
    except ValueError:
        result = {'outcome': 'error', 'note': (err or out)[-300:]}
    if signalled:
        result['outcome'] = 'signalled'
    return result


class Service:
    def __init__(self):
        self.connection = None
        self.watched = {}            # D-Bus sender -> name watch (SetWatching)
        self.agent = VoiceAgent(self.emit_signal)
        info = Gio.DBusNodeInfo.new_for_xml(INTERFACE)
        self.interface = info.interfaces[0]
        Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
                         self.register, None, lambda conn, name: (log('lost bus name'), os._exit(1)))
        threading.Thread(target=self.agent.warm, daemon=True).start()

    def watch_sender(self, connection, sender):
        """Forget what a client said about watching once it leaves the bus (the app quit)."""
        def watch():
            if sender not in self.watched:
                self.watched[sender] = Gio.bus_watch_name_on_connection(
                    connection, sender, Gio.BusNameWatcherFlags.NONE, None,
                    lambda conn, name: (self.agent.watcher_gone(name),
                                        Gio.bus_unwatch_name(self.watched.pop(name, 0)) if name in self.watched else None))
            return False
        GLib.idle_add(watch)

    def register(self, connection, name):
        self.connection = connection
        connection.register_object(OBJECT_PATH, self.interface, self.call, None, None)
        log('service ready')

    def emit_signal(self, event):
        text = json.dumps(event, ensure_ascii=False)

        def send():
            if self.connection:
                self.connection.emit_signal(None, OBJECT_PATH, BUS_NAME, 'Event', GLib.Variant('(s)', (text,)))
            return False
        GLib.idle_add(send)

    def call(self, connection, sender, path, interface, method, params, invocation):
        args = params.unpack()
        agent = self.agent

        def run():
            try:
                result = None
                if method == 'ListConversations':
                    result = json.dumps(agent.store.listing(agent.assistant_id()), ensure_ascii=False)
                elif method == 'OpenConversation':
                    result = json.dumps(agent.open_conversation(args[0]), ensure_ascii=False)
                elif method == 'CloseConversation':
                    # The assistant's conversation stays open (resident, docs/67): the app
                    # leaving its page must not cut the overlay's session.
                    if not args[0] or args[0] != agent.assistant_id():
                        agent.close_conversation(args[0] or None)
                        agent.warm()      # back to the assistant's conversation, warm
                elif method == 'OpenAssistant':
                    result = json.dumps(agent.open_assistant(), ensure_ascii=False)
                elif method == 'AssistantTalk':
                    agent.open_assistant()
                    GLib.idle_add(agent.start_talking, reply_sink(args[0]))
                elif method == 'ReleaseTalking':
                    GLib.idle_add(agent.release_talking)
                elif method == 'CancelTalking':
                    GLib.idle_add(agent.cancel_talking)
                elif method == 'StartListening':
                    GLib.idle_add(agent.start_listening, reply_sink(args[0]))
                elif method == 'DeleteConversation':
                    agent.delete_conversation(args[0])
                elif method == 'StartTalking':
                    GLib.idle_add(agent.start_talking, reply_sink(args[0]))
                elif method == 'StopTalking':
                    GLib.idle_add(agent.stop_talking)
                elif method == 'Interrupt':
                    GLib.idle_add(agent.stop_audio)
                elif method == 'StopTask':
                    agent.stop_task()
                elif method == 'Approve':
                    agent.approve(args[0], args[1])
                elif method == 'State':
                    result = json.dumps(agent.state())
                elif method == 'StartCall':
                    result = json.dumps(agent.start_call(json.loads(args[0])), ensure_ascii=False)
                elif method == 'CallCommand':
                    agent.call_command(args[0])
                elif method == 'SendText':
                    agent.send_text(args[0], json.loads(args[1] or '[]'))
                elif method == 'Use':
                    # The app's conversation is the one its next press or message goes to
                    # (docs/89): the overlay, a restart or the warm-up may have opened another
                    # meanwhile, and every call below acts on whichever is open. Returns once
                    # it is open, so the app's next call acts on it.
                    if args[0] and args[0] != agent.thread_id:
                        log('use', args[0], 'instead of', agent.thread_id)
                        agent.open_conversation(args[0])
                elif method == 'SetWatching':
                    self.watch_sender(connection, sender)
                    agent.set_watching(sender, args[0])
                elif method == 'TalkToText':
                    result = json.dumps({'text': agent.talk_to_text()}, ensure_ascii=False)
                elif method == 'ReadAloud':
                    agent.read_aloud(args[0])
                elif method == 'Setup':
                    result = json.dumps(agent.setup(), ensure_ascii=False)
                elif method == 'SetApiKey':
                    result = json.dumps(agent.set_api_key(args[0]), ensure_ascii=False)
                elif method == 'TestApiKey':
                    result = json.dumps(agent.test_api_key(), ensure_ascii=False)
                elif method == 'RemoveApiKey':
                    result = json.dumps(agent.remove_api_key(), ensure_ascii=False)
                elif method == 'CodexLogin':
                    result = json.dumps(agent.codex_login(args[0]), ensure_ascii=False)
                elif method == 'InstallCodex':
                    result = json.dumps(agent.install_codex(args[0]), ensure_ascii=False)
                elif method == 'CancelInstall':
                    result = json.dumps(agent.cancel_install(), ensure_ascii=False)
                elif method == 'SetPreferences':
                    result = json.dumps(agent.set_preferences(json.loads(args[0])), ensure_ascii=False)
                invocation.return_value(GLib.Variant('(s)', (result,)) if result is not None else None)
            except Exception as error:
                log('call failed', method, error)
                invocation.return_dbus_error('com.rungic.VoiceAgent.Error', str(error))
        # Codex calls block; keep the main loop (audio, D-Bus) responsive.
        threading.Thread(target=run, daemon=True).start()


def platform_request(request, timeout=1.0):
    """One request to the Android host's platform bridge (rungic-platform's socket), or {}."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as bridge:
            bridge.settimeout(timeout)
            bridge.connect('/mnt/android-wayland/platform.sock')
            bridge.sendall(json.dumps(request).encode() + b'\n')
            reply = b''
            while not reply.endswith(b'\n'):
                chunk = bridge.recv(65536)
                if not chunk:
                    break
                reply += chunk
        return json.loads(reply or b'{}')
    except (OSError, ValueError):
        return {}


def screen_activity():
    """The assistant's screen's caption (rungic_cua.activity, docs/88), or {}."""
    try:
        from rungic_cua import activity
        return activity.read()
    except ImportError:
        return {}


def command_summary(command):
    """The command itself, without the shell wrapper Codex adds."""
    match = re.fullmatch(r"/bin/(?:ba)?sh -lc '([\s\S]*)'", command.strip())
    return (match.group(1) if match else command)[:120]


def reply_sink(screen):
    """Answer where the user spoke: a press on a cast screen (KWin names those
    CAST-n) follows Android's routing, which plays on that display; a press on
    the phone plays on the phone even while casting."""
    if screen.startswith('CAST-'):
        return None
    try:
        sinks = subprocess.check_output(['pactl', 'list', 'short', 'sinks'], text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    if any(line.split('\t')[1:2] == [PHONE_SINK] for line in sinks.splitlines()):
        return PHONE_SINK
    return None


def test_turn(audio_file, seconds, screen, stop_after=None, raw=False):
    """Open a new conversation and speak a recording, printing events."""
    agent = VoiceAgent(lambda e: log(json.dumps(e, ensure_ascii=False)[:300]))
    agent.reply_sink = reply_sink(screen)
    log('reply on', agent.reply_sink or 'default sink')
    opened = agent.open_conversation('')
    agent.realtime_ready.wait(20)
    data = Path(audio_file).read_bytes()
    agent.talking = True
    agent.press = int(time.time() * 1000)
    chunk = RATE * 2 * CHUNK_MS // 1000
    gate = PauseGate()
    for offset in range(0, len(data), chunk):
        send = gate.feed(data[offset:offset + chunk]) if not raw else data[offset:offset + chunk]
        if send:
            agent.append_audio(send)
        time.sleep(CHUNK_MS / 1000)
    agent.talking = False
    log(f'test: {gate.dropped_ms} ms of pauses left out')
    agent.append_audio(gate.finish() + bytes(RATE * 2 * END_SILENCE_MS // 1000))
    loop = GLib.MainLoop()
    GLib.timeout_add(int(seconds * 1000), loop.quit)
    if stop_after:
        GLib.timeout_add(int(stop_after * 1000), lambda: (log('test: stop button'),
                                                           threading.Thread(target=agent.stop_task).start(), False)[-1])
    loop.run()
    agent.close_conversation()
    print('conversation', opened['conversation'])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--service', action='store_true', help='run the D-Bus service')
    parser.add_argument('--audio-file', help='test: speak this raw S16LE 24 kHz mono file in a new conversation')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--screen', default='', help='test: screen the turn starts from (reply routing)')
    parser.add_argument('--stop-after', type=float, help='test: press the stop button after this many seconds')
    parser.add_argument('--raw', action='store_true', help='test: send the file without shortening pauses')
    parser.add_argument('--start-call', metavar='JSON',
                        help='let the assistant take part in the call just placed or received: '
                             '{"contact": ..., "goal": ..., "app": "wechat", "incoming": false, "monitor": false, '
                             '"dial": "<control that places the call, e.g. Voice Call>"}')
    parser.add_argument('--call-command', choices=['monitor-on', 'monitor-off', 'take-over', 'hang-up'])
    args = parser.parse_args()
    if args.start_call or args.call_command:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        if args.start_call:
            json.loads(args.start_call)   # fail early on bad JSON
            reply = bus.call_sync(BUS_NAME, OBJECT_PATH, BUS_NAME, 'StartCall', GLib.Variant('(s)', (args.start_call,)),
                                  None, 0, 30000).unpack()[0]
            print(reply)
        else:
            bus.call_sync(BUS_NAME, OBJECT_PATH, BUS_NAME, 'CallCommand', GLib.Variant('(s)', (args.call_command,)),
                          None, 0, 30000)
        return
    if args.audio_file:
        test_turn(args.audio_file, args.seconds, args.screen, args.stop_after, args.raw)
    elif args.service:
        Service()
        GLib.MainLoop().run()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
