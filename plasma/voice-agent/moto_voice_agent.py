#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Voice agent prototype (docs/59): phone microphone -> GPT Realtime through
`codex app-server` -> phone speaker. The realtime model hands requests to the
Codex agent with its `background_agent` tool; Codex runs them and the model
speaks the result. This program only moves audio and shows what happens.

  moto-voice-agent                 talk through the phone microphone
  moto-voice-agent --text "..."    add a typed message (does not ask for a reply)
  moto-voice-agent --audio-file F  speak F (raw S16LE 24 kHz mono) as the microphone (testing)

Transport is WebSocket so all traffic, audio included, goes through the proxy
that the `codex` wrapper sets (WebRTC media would bypass an HTTP proxy).
"""
import argparse
import base64
import itertools
import json
import os
import subprocess
import sys
import threading
import time

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

RATE = 24000          # PCM format of the Realtime API
CHUNK_MS = 100
MIC = 'android_microphone'
# Echo guard: the phone plays the reply through its speaker, which the server's
# voice detection would hear as the user interrupting. Pause the microphone
# while playing and a little after.
ECHO_TAIL_S = 0.6
# The user speaks Mandarin; without this, transcripts and answers drift to
# Traditional Chinese.
LANGUAGE = ('The user speaks Mandarin Chinese on a phone running this Linux desktop. '
            'Always write and speak Simplified Chinese (简体中文) unless asked otherwise.')


def log(kind, text):
    print(f'{time.strftime("%H:%M:%S")} {kind:10} {text}', flush=True)


class AppServer:
    """JSON-RPC 2.0 over stdio with `codex app-server`."""

    def __init__(self, on_notification, on_request):
        env = dict(os.environ)
        # The agent uses the ChatGPT sign-in; Codex 0.156 takes realtime (WebSocket)
        # credentials only from an API key, read from OPENAI_API_KEY. Only this
        # process gets it.
        key_file = os.path.expanduser('~/.config/moto-voice-agent/openai-api-key')
        if os.path.exists(key_file):
            with open(key_file) as f:
                env['OPENAI_API_KEY'] = f.read().strip()
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
            raise TimeoutError(method)
        reply = self.pending.pop(request_id)[1]
        if 'error' in reply:
            raise RuntimeError(f'{method}: {reply["error"]}')
        return reply.get('result')

    def notify(self, method, params=None):
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            message['params'] = params
        self.send(message)

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
                result = self.on_request(message['method'], message.get('params') or {})
                self.send({'jsonrpc': '2.0', 'id': message['id'], 'result': result})
            else:
                self.on_notification(message['method'], message.get('params') or {})
        log('closed', 'codex app-server exited')
        os._exit(1)


class VoiceAgent:
    def __init__(self, use_microphone):
        Gst.init(None)
        self.thread_id = None
        self.started = threading.Event()
        self.playing_until = 0.0
        self.player = Gst.parse_launch(
            f'appsrc name=src is-live=true format=time do-timestamp=true '
            f'caps=audio/x-raw,format=S16LE,rate={RATE},channels=1,layout=interleaved '
            '! queue ! audioconvert ! audioresample ! pulsesink')
        self.player_src = self.player.get_by_name('src')
        self.player.set_state(Gst.State.PLAYING)
        self.recorder = None
        if use_microphone:
            self.recorder = Gst.parse_launch(
                f'pulsesrc device={MIC} ! audioconvert ! audioresample '
                f'! audio/x-raw,format=S16LE,rate={RATE},channels=1 '
                f'! appsink name=sink emit-signals=true sync=false '
                f'blocksize={RATE * 2 * CHUNK_MS // 1000}')
            self.recorder.get_by_name('sink').connect('new-sample', self.on_microphone)
        self.server = AppServer(self.on_notification, self.on_request)

    def start(self):
        self.server.call('initialize', {'clientInfo': {'name': 'moto-voice-agent', 'version': '0.1'},
                                        'capabilities': {'experimentalApi': True}})
        self.server.notify('initialized')
        thread = self.server.call('thread/start', {'cwd': os.path.expanduser('~'), 'sandbox': 'read-only',
                                                   'approvalPolicy': 'on-request',
                                                   'developerInstructions': LANGUAGE})
        self.thread_id = thread['thread']['id']
        log('thread', f'{self.thread_id} model={thread.get("model")} sandbox={thread.get("sandbox")}')
        self.server.call('thread/realtime/start', {'threadId': self.thread_id, 'outputModality': 'audio',
                                                   'transport': {'type': 'websocket'},
                                                   'realtimeStartInstructions': LANGUAGE})
        if self.recorder:
            self.recorder.set_state(Gst.State.PLAYING)
            log('listening', f'microphone {MIC}')

    def send_audio_file(self, path):
        """Feed a recording in real time as if spoken, then silence for the server VAD."""
        with open(path, 'rb') as f:
            data = f.read()
        chunk = RATE * 2 * CHUNK_MS // 1000
        data += bytes(RATE * 2)  # one second of silence ends the utterance
        log('you', f'(audio {len(data) / 2 / RATE:.1f}s from {path})')
        for offset in range(0, len(data), chunk):
            self.append_audio(data[offset:offset + chunk])
            time.sleep(CHUNK_MS / 1000)

    def send_text(self, text):
        log('you', text)
        self.server.call('thread/realtime/appendText', {'threadId': self.thread_id, 'text': text, 'role': 'user'})

    def on_microphone(self, sink):
        sample = sink.emit('pull-sample')
        if not self.started.is_set() or time.monotonic() < self.playing_until:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if ok:
            data = bytes(info.data)
            buf.unmap(info)
            threading.Thread(target=self.append_audio, args=(data,), daemon=True).start()
        return Gst.FlowReturn.OK

    def append_audio(self, data):
        try:
            self.server.call('thread/realtime/appendAudio', {'threadId': self.thread_id, 'audio': {
                'data': base64.b64encode(data).decode(), 'sampleRate': RATE, 'numChannels': 1,
                'samplesPerChannel': len(data) // 2}}, timeout=10)
        except Exception as error:
            log('error', f'appendAudio: {error}')

    def on_notification(self, method, params):
        if method == 'thread/realtime/outputAudio/delta':
            audio = params['audio']
            data = base64.b64decode(audio['data'])
            seconds = len(data) / 2 / audio.get('sampleRate', RATE) / audio.get('numChannels', 1)
            self.playing_until = max(self.playing_until, time.monotonic()) + seconds + ECHO_TAIL_S
            self.player_src.emit('push-buffer', Gst.Buffer.new_wrapped(data))
        elif method == 'thread/realtime/transcript/done':
            log(params.get('role', '?'), params.get('text', ''))
        elif method in ('thread/realtime/started', 'thread/realtime/closed', 'thread/realtime/error'):
            if method == 'thread/realtime/started':
                self.started.set()
            log(method.rsplit('/', 1)[1], json.dumps(params, ensure_ascii=False)[:300])
        elif method == 'item/started':
            item = params.get('item', {})
            if item.get('type') == 'commandExecution':
                log('agent', f'run {item.get("command")}')
        elif method == 'item/completed':
            item = params.get('item', {})
            if item.get('type') == 'agentMessage':
                log('agent', item.get('text', ''))
            elif item.get('type') == 'commandExecution':
                log('agent', f'exit {item.get("exitCode")}: {str(item.get("aggregatedOutput", ""))[:200]}')
        elif method == 'turn/started':
            log('agent', 'task started')
        elif method == 'turn/completed':
            log('agent', 'task finished')

    def on_request(self, method, params):
        # Prototype: no approval UI yet; anything beyond the read-only sandbox is declined.
        log('approval', f'{method} declined: {json.dumps(params, ensure_ascii=False)[:200]}')
        return {'decision': 'decline'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--text', help='send this request as text instead of listening')
    parser.add_argument('--audio-file', help='speak this raw S16LE 24 kHz mono file instead of listening')
    parser.add_argument('--seconds', type=float, default=90, help='stop after this long (0 = run until killed)')
    args = parser.parse_args()
    agent = VoiceAgent(use_microphone=args.text is None and args.audio_file is None)
    agent.start()
    agent.started.wait(20)
    if args.text:
        agent.send_text(args.text)
    if args.audio_file:
        threading.Thread(target=agent.send_audio_file, args=(args.audio_file,), daemon=True).start()
    loop = GLib.MainLoop()
    if args.seconds:
        GLib.timeout_add(int(args.seconds * 1000), loop.quit)
    try:
        loop.run()
    finally:
        try:
            agent.server.call('thread/realtime/stop', {'threadId': agent.thread_id}, timeout=5)
        except Exception:
            pass


if __name__ == '__main__':
    main()
