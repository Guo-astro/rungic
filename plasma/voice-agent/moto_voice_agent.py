#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Voice assistant service (docs/59).

A session D-Bus service (dev.moto.VoiceAgent) that owns `codex app-server`.
Each conversation is a Codex thread. While a conversation is open, a GPT
Realtime session runs on it: push-to-talk audio from the phone microphone goes
in, the spoken reply comes out of the speaker, and the realtime model hands
work to the Codex agent with its `background_agent` tool. Everything that
happens (speech, agent progress, commands, approvals) is sent to the UI as
JSON events and kept per conversation for the chat history.

  moto-voice-agent --service            D-Bus service (systemd user unit)
  moto-voice-agent --audio-file F.pcm   one test turn: F (S16LE 24 kHz mono) as speech

Realtime runs over WebSocket so all traffic goes through the proxy that the
`codex` wrapper sets; Codex needs an API key for that (OPENAI_API_KEY from
~/.config/moto-voice-agent/openai-api-key), while the agent itself uses the
ChatGPT sign-in.
"""
import argparse
import base64
import itertools
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gio, GLib, Gst

RATE = 24000                 # PCM format of the Realtime API
CHUNK_MS = 100
MIC = 'android_microphone'
PHONE_SINK = 'android_phone'     # always the phone itself (shared/media/media-bridge.py)
END_SILENCE_MS = 900         # after release, so the server VAD sees the end of speech
IDLE_STOP_S = 600            # stop an unused realtime session (cost)
# Spoken progress while the agent works: Codex hands agent updates to the voice
# model as context only (no response), so it would stay silent until the end.
PROGRESS_AFTER_S = 8         # quick tasks get no progress update
PROGRESS_GAP_S = 6           # silence before relaying a new step
QUIET_UPDATE_S = 20          # nothing new: say it is still working (then 30 s, 45 s, 60 s)
PROGRESS_STALE_S = 8         # an agent note older than this describes a finished step
DATA = Path.home() / '.local/share/moto-voice-agent'
CONFIG = Path.home() / '.config/moto-voice-agent'
PROMPTS = Path('/usr/local/share/moto-voice-agent/prompts')
BUS_NAME = 'dev.moto.VoiceAgent'
OBJECT_PATH = '/dev/moto/VoiceAgent'
INTERFACE = '''
<node>
  <interface name="dev.moto.VoiceAgent">
    <method name="ListConversations"><arg type="s" direction="out"/></method>
    <method name="OpenConversation"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
    <method name="CloseConversation"/>
    <method name="DeleteConversation"><arg type="s" direction="in"/></method>
    <method name="StartTalking"><arg type="s" direction="in"/></method>
    <method name="StopTalking"/>
    <method name="Interrupt"/>
    <method name="Approve"><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
    <method name="State"><arg type="s" direction="out"/></method>
    <signal name="Event"><arg type="s"/></signal>
  </interface>
</node>
'''


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
        key_file = CONFIG / 'openai-api-key'
        if key_file.exists():
            env['OPENAI_API_KEY'] = key_file.read_text().strip()
        self.proc = subprocess.Popen(['codex', 'app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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

    def listing(self):
        items = [dict(id=k, **v) for k, v in self.index.items()]
        return sorted(items, key=lambda e: e.get('updated', 0), reverse=True)


class VoiceAgent:
    def __init__(self, emit):
        Gst.init(None)
        self.emit_raw = emit
        self.store = Store()
        self.thread_id = None
        self.realtime = False
        self.realtime_ready = threading.Event()
        self.talking = False
        self.agent_busy = False
        self.turn_started = 0.0
        self.last_voice = 0.0     # last reply audio or progress request
        self.progress_text = None
        self.progress_at = 0.0
        self.quiet_updates = 0
        self.current_step = None
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
        # Audio must reach the server in order: one sender thread, fixed chunks.
        self.uploads = queue.Queue()
        threading.Thread(target=self.upload_loop, daemon=True).start()
        self.server = AppServer(self.on_notification, self.on_request)
        self.server.call('initialize', {'clientInfo': {'name': 'moto-voice-agent', 'version': '1.0'},
                                        'capabilities': {'experimentalApi': True}})
        self.server.notify('initialized')
        GLib.timeout_add_seconds(30, self.idle_check)

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
        return {'conversation': self.thread_id, 'phase': phase, 'agentBusy': self.agent_busy}

    # ---- conversations ----------------------------------------------------------
    def thread_settings(self):
        return {'cwd': str(Path.home()), 'sandbox': 'workspace-write', 'approvalPolicy': 'on-request',
                'developerInstructions': prompt('agent.md')}

    def open_conversation(self, thread_id):
        with self.lock:
            self.close_conversation()
            if thread_id:
                result = self.server.call('thread/resume', {'threadId': thread_id, **self.thread_settings()})
            else:
                result = self.server.call('thread/start', self.thread_settings())
            self.thread_id = result['thread']['id']
            if thread_id:
                self.store.touch(self.thread_id)   # a new one is listed once the user speaks
            self.last_activity = time.monotonic()
            log('open', self.thread_id, 'resumed' if thread_id else 'new')
            history = self.store.history(self.thread_id)
            threading.Thread(target=self.start_realtime, daemon=True).start()
            GLib.idle_add(self.set_state)
            return {'conversation': self.thread_id,
                    'title': self.store.index.get(self.thread_id, {}).get('title', '新对话'),
                    'history': history}

    def start_realtime(self):
        with self.lock:
            if self.realtime or not self.thread_id:
                return
            self.realtime_ready.clear()
            try:
                self.server.call('thread/realtime/start', {
                    'threadId': self.thread_id, 'outputModality': 'audio', 'transport': {'type': 'websocket'},
                    # Instructions of the realtime model itself (replaces Codex's default,
                    # which prompts/realtime.md includes).
                    'prompt': prompt('realtime.md')})
            except Exception as error:
                self.emit({'type': 'error', 'text': f'语音连接失败：{error}'})
                return
        self.realtime_ready.wait(20)

    def stop_realtime(self):
        if self.realtime and self.thread_id:
            try:
                self.server.call('thread/realtime/stop', {'threadId': self.thread_id}, timeout=5)
            except Exception:
                pass
        self.realtime = False
        self.realtime_ready.clear()
        GLib.idle_add(self.stop_audio)

    def close_conversation(self):
        with self.lock:
            if self.thread_id:
                self.stop_realtime()
                log('close', self.thread_id)
            self.thread_id = None
            GLib.idle_add(self.set_state)

    def delete_conversation(self, thread_id):
        if thread_id == self.thread_id:
            self.close_conversation()
        try:
            self.server.call('thread/archive', {'threadId': thread_id}, timeout=10)
        except Exception as error:
            log('archive failed', error)
        self.store.delete(thread_id)

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
            self.player = Gst.parse_launch(
                'appsrc name=src is-live=true format=time do-timestamp=true '
                f'caps=audio/x-raw,format=S16LE,rate={RATE},channels=1,layout=interleaved '
                '! queue ! audioconvert ! audioresample ! pulsesink name=out')
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
        self.last_activity = time.monotonic()
        self.reply_sink = sink
        if not self.thread_id:
            return False
        if not self.realtime:
            threading.Thread(target=self.start_realtime, daemon=True).start()
        self.stop_audio()           # barge in: stop speaking at once
        self.talking = True
        if self.recorder is None:
            self.recorder = Gst.parse_launch(
                f'pulsesrc device={MIC} ! audioconvert ! audioresample '
                f'! audio/x-raw,format=S16LE,rate={RATE},channels=1 '
                f'! appsink name=sink emit-signals=true sync=false blocksize={RATE * 2 * CHUNK_MS // 1000}')
            self.recorder.get_by_name('sink').connect('new-sample', self.on_microphone)
        self.mic_buffer = b''
        self.recorder.set_state(Gst.State.PLAYING)
        self.mic_chunks = 0
        log('talk: start, reply on', self.reply_sink or 'default sink')
        self.set_state()
        return False

    def stop_talking(self):
        if not self.talking:
            return False
        self.talking = False
        self.last_activity = time.monotonic()
        if self.recorder is not None:
            self.recorder.set_state(Gst.State.NULL)   # the microphone is open only while pressed
        log(f'talk: stop after {self.mic_chunks * CHUNK_MS} ms of audio')
        if self.mic_buffer:
            self.uploads.put(self.mic_buffer)
            self.mic_buffer = b''
        self.uploads.put(bytes(RATE * 2 * END_SILENCE_MS // 1000))
        self.set_state()
        return False

    def on_microphone(self, sink):
        sample = sink.emit('pull-sample')
        if not self.talking:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            self.mic_buffer += bytes(info.data)
            buf.unmap(info)
            chunk = RATE * 2 * CHUNK_MS // 1000
            while len(self.mic_buffer) >= chunk:
                self.uploads.put(self.mic_buffer[:chunk])
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

    def play(self, audio):
        if self.talking:
            log('reply audio dropped while talking')
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
        if not self.agent_busy or not self.realtime:
            return False
        now = time.monotonic()
        if self.talking:
            self.last_voice = now
        self.last_voice = max(self.last_voice, self.playing_until)
        if now - self.turn_started < PROGRESS_AFTER_S:
            return True
        if self.approvals:
            self.last_voice = now     # waiting for the user, who was already asked
            return True
        elapsed = int(now - self.turn_started)
        if self.progress_text and now - self.progress_at > PROGRESS_STALE_S:
            self.progress_text = None
        if self.progress_text and now - self.last_voice >= PROGRESS_GAP_S:
            text = (f'进度（已用时{elapsed}秒，任务仍在进行）：{self.progress_text}\n'
                    '用一句很短的话告诉用户现在在做什么，不要说成结果。')
        elif now - self.last_voice >= min(60, QUIET_UPDATE_S * 1.5 ** self.quiet_updates):
            self.quiet_updates += 1
            step = command_summary(self.current_step) if self.current_step else '分析中'
            text = (f'进度（已用时{elapsed}秒，任务仍在进行，当前步骤：{step}）\n'
                    '用一句很短的话告诉用户还在处理，不要说成结果。')
        else:
            return True
        self.progress_text = None
        self.last_voice = now
        threading.Thread(target=self.speak_progress, args=(text,), daemon=True).start()
        return True

    def speak_progress(self, text):
        log('progress:', text.splitlines()[0][:100])
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
            self.realtime_ready.set()
            GLib.idle_add(self.set_state)
        elif method == 'thread/realtime/closed':
            self.realtime = False
            self.realtime_ready.clear()
            GLib.idle_add(self.set_state)
        elif method == 'thread/realtime/error':
            self.emit({'type': 'error', 'text': params.get('message', '')})
        elif method == 'thread/realtime/transcript/delta':
            self.emit({'type': 'delta', 'role': params.get('role'), 'text': params.get('delta', '')}, keep=False)
        elif method == 'thread/realtime/transcript/done':
            text = params.get('text', '').strip()
            if text:
                role = 'user' if params.get('role') == 'user' else 'assistant'
                if role == 'user':
                    self.store.touch(self.thread_id, text)
                self.emit({'type': 'message', 'role': role, 'text': text})
        elif method == 'turn/started':
            self.agent_busy = True
            self.turn_started = self.last_voice = time.monotonic()
            self.progress_text = self.current_step = None
            self.quiet_updates = 0
            self.emit({'type': 'agent-started'})
            GLib.idle_add(self.set_state)
            GLib.idle_add(self.start_progress)
        elif method == 'turn/completed':
            self.agent_busy = False
            self.last_activity = time.monotonic()
            self.emit({'type': 'agent-finished'})
            GLib.idle_add(self.set_state)
        elif method in ('item/started', 'item/completed'):
            self.agent_item(method.endswith('completed'), params.get('item') or {})

    def agent_item(self, completed, item):
        kind = item.get('type')
        if kind == 'commandExecution':
            if not completed:
                self.current_step = item.get('command', '')
            self.emit({'type': 'command', 'id': item.get('id'), 'command': item.get('command', ''),
                       'status': 'done' if completed else 'running', 'exitCode': item.get('exitCode'),
                       'output': (item.get('aggregatedOutput') or '')[-4000:]}, keep=completed)
        elif kind == 'fileChange' and completed:
            paths = [c.get('path', '') for c in item.get('changes', [])]
            self.emit({'type': 'files', 'id': item.get('id'), 'paths': paths, 'status': item.get('status')})
        elif kind == 'agentMessage' and completed and item.get('text'):
            if item.get('phase') != 'final_answer':
                self.progress_text = item['text']
                self.progress_at = time.monotonic()
            self.emit({'type': 'agent-message', 'id': item.get('id'), 'text': item['text']})

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

    def approve(self, approval, decision):
        request_id = self.approvals.pop(approval, None)
        if request_id is None:
            return
        answer = {'allow': 'accept', 'allow-session': 'acceptForSession'}.get(decision, 'decline')
        self.server.respond(request_id, {'decision': answer})
        self.emit({'type': 'approval-result', 'id': approval, 'decision': answer})


class Service:
    def __init__(self):
        self.connection = None
        self.agent = VoiceAgent(self.emit_signal)
        info = Gio.DBusNodeInfo.new_for_xml(INTERFACE)
        self.interface = info.interfaces[0]
        Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
                         self.register, None, lambda conn, name: (log('lost bus name'), os._exit(1)))

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
                    result = json.dumps(agent.store.listing(), ensure_ascii=False)
                elif method == 'OpenConversation':
                    result = json.dumps(agent.open_conversation(args[0]), ensure_ascii=False)
                elif method == 'CloseConversation':
                    agent.close_conversation()
                elif method == 'DeleteConversation':
                    agent.delete_conversation(args[0])
                elif method == 'StartTalking':
                    GLib.idle_add(agent.start_talking, reply_sink(args[0]))
                elif method == 'StopTalking':
                    GLib.idle_add(agent.stop_talking)
                elif method == 'Interrupt':
                    GLib.idle_add(agent.stop_audio)
                elif method == 'Approve':
                    agent.approve(args[0], args[1])
                elif method == 'State':
                    result = json.dumps(agent.state())
                invocation.return_value(GLib.Variant('(s)', (result,)) if result is not None else None)
            except Exception as error:
                log('call failed', method, error)
                invocation.return_dbus_error('dev.moto.VoiceAgent.Error', str(error))
        # Codex calls block; keep the main loop (audio, D-Bus) responsive.
        threading.Thread(target=run, daemon=True).start()


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


def test_turn(audio_file, seconds, screen):
    """Open a new conversation and speak a recording, printing events."""
    agent = VoiceAgent(lambda e: log(json.dumps(e, ensure_ascii=False)[:300]))
    agent.reply_sink = reply_sink(screen)
    log('reply on', agent.reply_sink or 'default sink')
    opened = agent.open_conversation('')
    agent.realtime_ready.wait(20)
    data = Path(audio_file).read_bytes()
    agent.talking = True
    chunk = RATE * 2 * CHUNK_MS // 1000
    for offset in range(0, len(data), chunk):
        agent.append_audio(data[offset:offset + chunk])
        time.sleep(CHUNK_MS / 1000)
    agent.talking = False
    agent.append_audio(bytes(RATE * 2 * END_SILENCE_MS // 1000))
    loop = GLib.MainLoop()
    GLib.timeout_add(int(seconds * 1000), loop.quit)
    loop.run()
    agent.close_conversation()
    print('conversation', opened['conversation'])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--service', action='store_true', help='run the D-Bus service')
    parser.add_argument('--audio-file', help='test: speak this raw S16LE 24 kHz mono file in a new conversation')
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--screen', default='', help='test: screen the turn starts from (reply routing)')
    args = parser.parse_args()
    if args.audio_file:
        test_turn(args.audio_file, args.seconds, args.screen)
    elif args.service:
        Service()
        GLib.MainLoop().run()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
