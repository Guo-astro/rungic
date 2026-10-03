# SPDX-License-Identifier: MIT
"""The communication audio contract from both ends (quality/contracts/communication-audio.json), built
and run in the system test container (no PulseAudio, no Android, no KWin needed):

- consumer: the phone mode session's client (agent/assistant/session/audio.cpp, driven muted by
  tools/system/communication_client.cpp) against a stand-in of the service on
  $XDG_RUNTIME_DIR/rungic-communication.sock: it opens muted, follows the positions of its epoch only,
  learns the new epoch from a flush, and reports the service's error.
- provider: the real service (shared/media/communication-audio.cpp) with a fake pactl (its PulseAudio
  pipe devices are FIFOs, as module-pipe-sink/-source make them) and a stand-in of Android's capture
  socket at /mnt/android-wayland/capture.sock (the audio contract's communication ops): a client opens
  a session, gets ready and positions, its PCM reaches Android framed with the epoch, a flush moves the
  epoch, mute and close are answered, a second client is refused, and the devices are unloaded."""
import json
import os
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

import contracts
import harness

SRC = Path('/src')
BUILD = Path('/tmp/communication')
CONTRACT = contracts.load('communication-audio')
REQUESTS, REPLIES = CONTRACT['messages']['requests'], CONTRACT['messages']['replies']
CAPTURE = Path('/mnt/android-wayland/capture.sock')   # the provider's fixed path (the app's socket)
PACTL = '''import os, sys
args = sys.argv[1:]
with open(os.environ['FAKE_PACTL_LOG'], 'a') as log:
    log.write(' '.join(args) + '\\n')
if args[:1] == ['load-module']:
    path = next(a[5:] for a in args if a.startswith('file='))
    if not os.path.exists(path):
        os.mkfifo(path, 0o600)
    print(30 if args[1] == 'module-pipe-source' else 31)
elif args[:1] == ['get-sink-volume']:
    print('Volume: front-left: 26214 /  40% / -23.88 dB,   front-right: 26214 /  40% / -23.88 dB')
'''


def compile_(output, *sources, include=None):
    flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'Qt6Core', 'Qt6Network', 'gstreamer-1.0',
                            'gstreamer-app-1.0'], capture_output=True, text=True, check=True).stdout.split()
    done = subprocess.run(['g++', '-std=gnu++20', '-O1', '-o', str(output), *([f'-I{include}'] if include else []),
                           *map(str, sources), *flags], capture_output=True, text=True)
    if done.returncode:
        raise harness.Failed(f'building {output.name}: {done.stderr[-600:]}')
    return output


def build():
    BUILD.mkdir(exist_ok=True)
    (BUILD / 'bin').mkdir(exist_ok=True)
    (BUILD / 'bin/pactl').write_text(f'#!/usr/bin/python3\n{PACTL}')
    (BUILD / 'bin/pactl').chmod(0o755)
    service = compile_(BUILD / 'rungic-communication-audio', SRC / 'shared/media/communication-audio.cpp')
    client = compile_(BUILD / 'communication_client', SRC / 'tools/system/communication_client.cpp',
                      SRC / 'agent/assistant/session/audio.cpp', include=SRC / 'agent/assistant/session')
    return service, client


def runtime(name):
    path = Path(f'/tmp/rt-{name}')
    path.mkdir(mode=0o700, exist_ok=True)
    return path


class Lines:
    """JSON lines from a socket, with a timeout."""

    def __init__(self, sock):
        self.sock, self.buffer = sock, b''

    def send(self, message):
        self.sock.sendall((json.dumps(message) + '\n').encode())

    def next(self, want=lambda m: True, timeout=5):
        deadline = time.monotonic() + timeout
        while True:
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                message = json.loads(line)
                if want(message):
                    return message
            left = deadline - time.monotonic()
            if left <= 0:
                raise harness.Failed('no answer from the communication audio socket')
            self.sock.settimeout(left)
            part = self.sock.recv(65536)
            if not part:
                return None
            self.buffer += part


def keeps(name, message, steps, what):
    problems = contracts.validate(REPLIES[name], message or {})
    if problems:
        raise harness.Failed(f'{what}: {message} breaks the contract: {problems}')
    steps.append(what)


# ---- consumer ------------------------------------------------------------------------------------

class Service:
    """The service as the contract describes it, for the session's client: ready on open, positions of
    the current epoch every 50 ms, a flush answered with the next epoch (and one stale position of the
    old one right after it), mute answered and then the session failed."""

    def __init__(self, path):
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(1)
        self.requests, self.problems = [], []
        self.epoch, self.played, self.lock = 1, 0, threading.Lock()
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        conn, _ = self.server.accept()
        lines = Lines(conn)
        opened = threading.Event()

        def positions():
            while opened.is_set():
                with self.lock:
                    self.played += 240
                    lines.send({**REPLIES['position'], 'epoch': self.epoch, 'playedFrames': self.played,
                                'writtenFrames': self.played + 4800})
                time.sleep(0.05)
        try:
            while True:
                request = lines.next(timeout=30)
                if request is None:
                    return
                self.requests.append(request)
                example = REQUESTS.get(request.get('op'))
                found = contracts.validate(example, request, 'request') if example else ['unknown op']
                self.problems += [f'{request.get("op")}: {p}' for p in found]
                if request['op'] == 'open':
                    lines.send({**REPLIES['ready'], 'sessionId': request['sessionId'], 'microphone': not request['muted']})
                    opened.set()
                    threading.Thread(target=positions, daemon=True).start()
                elif request['op'] == 'flush':
                    with self.lock:
                        lines.send({**REPLIES['flushed'], 'id': request['id'], 'epoch': self.epoch, 'playedFrames': self.played,
                                    'writtenFrames': self.played + 4800, 'newEpoch': self.epoch + 1})
                        lines.send({**REPLIES['position'], 'epoch': self.epoch, 'playedFrames': 999999, 'writtenFrames': 999999})
                        self.epoch, self.played = self.epoch + 1, 0
                elif request['op'] == 'mute':
                    lines.send({**REPLIES['muted'], 'id': request['id'], 'muted': request['muted']})
                    opened.clear()
                    lines.send(REPLIES['error'])
        except (OSError, harness.Failed):
            return


# covers[consumer]: iface:communication-audio
def consumer(client, steps):
    run = runtime('consumer')
    service = Service(run / 'rungic-communication.sock')
    done = subprocess.run([str(client), 'consumer-test'], capture_output=True, text=True, timeout=30,
                          env={**os.environ, 'XDG_RUNTIME_DIR': str(run)})
    events = {}
    for event in map(json.loads, done.stdout.splitlines()):
        events.setdefault(event['event'], event)   # the first of each (closing the client reports a disconnect)
    if 'timeout' in events or 'failed' not in events:
        raise harness.Failed(f'the client did not finish: {done.stdout[-500:]} {done.stderr[-300:]}')
    if service.problems:
        raise harness.Failed(f'the client broke the contract: {service.problems}')
    ops = [r['op'] for r in service.requests]
    if ops != ['open', 'flush', 'mute'] or service.requests[0]['muted'] is not True:
        raise harness.Failed(f'requests {service.requests}')
    steps.append('the session opens muted with its id, then flushes and mutes, as the contract asks')
    if not events['ready']['opened']:
        raise harness.Failed('ready did not open the client')
    playing = events['playing']
    if not (playing['epoch'] == 1 and playing['played'] > 0 and playing['written'] == playing['played'] + 4800):
        raise harness.Failed(f'positions not followed: {playing}')
    steps.append("the client follows the service's positions")
    if events['flushed']['epoch'] != 2 or events['after-flush']['epoch'] != 2:
        raise harness.Failed(f'flush: {events["flushed"]} {events["after-flush"]}')
    if not 0 < events['after-flush']['played'] < 999999:
        raise harness.Failed(f'a position of the old epoch was taken: {events["after-flush"]}')
    steps.append('a flush moves the client to the new epoch; positions of the old one are ignored')
    if events['failed']['error'] != REPLIES['error']['error']:
        raise harness.Failed(f'error: {events["failed"]}')
    steps.append("the service's error reaches the session")


# ---- provider ------------------------------------------------------------------------------------

class Android:
    """Android's capture socket as the audio contract gives its communication ops."""

    def __init__(self):
        self.epoch, self.packets, self.lock = 1, [], threading.Lock()

    def output(self, conn, stream, request):
        while True:
            head = stream.read(12)
            if len(head) < 12:
                return
            epoch, count = struct.unpack('>QI', head)
            pcm = stream.read(count)
            with self.lock:
                self.packets.append((epoch, pcm))

    def control(self, conn, stream, request):
        for line in stream:
            ask = json.loads(line)
            with self.lock:
                written = sum(len(p) for e, p in self.packets if e == self.epoch) // 2
                reply = {'ok': True, 'epoch': self.epoch, 'playedFrames': written // 2, 'writtenFrames': written, 'rate': 48000}
                if ask['op'] == 'flush':
                    if ask['epoch'] <= self.epoch:
                        reply = {'error': 'Stale playback generation'}
                    else:
                        reply['newEpoch'], self.epoch = ask['epoch'], ask['epoch']
            conn.sendall((json.dumps({**reply, 'id': ask.get('id', 0)}) + '\n').encode())

    def pcm(self, epoch):
        with self.lock:
            return b''.join(p for e, p in self.packets if e == epoch)


def wait_for(condition, what, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise harness.Failed(f'timed out waiting for {what}')
        time.sleep(0.02)


# covers[provider]: iface:communication-audio
def provider(service, steps):
    run = runtime('provider')
    log = run / 'pactl.log'
    android = Android()
    with contracts.StandIn('audio', socket_name='capture', streams={
            'communication-output': android.output, 'communication-control': android.control}) as capture:
        CAPTURE.unlink(missing_ok=True)
        CAPTURE.symlink_to(capture.path)
        process = subprocess.Popen([str(service)], stderr=open(run / 'service.err', 'w'), env={
            **os.environ, 'XDG_RUNTIME_DIR': str(run), 'PATH': f'{BUILD / "bin"}:{os.environ["PATH"]}',
            'FAKE_PACTL_LOG': str(log)})
        try:
            path = run / 'rungic-communication.sock'
            wait_for(path.exists, 'the service socket')
            owner = Lines(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
            owner.sock.connect(str(path))
            owner.send({**REQUESTS['open'], 'sessionId': 'provider-test', 'muted': True, 'id': 1})
            ready = owner.next(lambda m: m.get('type') != 'position')
            keeps('ready', ready, steps, 'open: ready, muted (no microphone), with the PulseAudio devices')
            if ready['microphone'] is not False or ready['sessionId'] != 'provider-test':
                raise harness.Failed(f'ready: {ready}')
            asked = [r['op'] for r in capture.requests]
            if asked != ['communication-output', 'communication-control'] or capture.problems:
                raise harness.Failed(f'Android was asked {capture.requests} {capture.problems}')
            steps.append("Android's communication output and control are opened for the session, not the microphone")
            keeps('position', owner.next(lambda m: m.get('type') == 'position'), steps, 'positions every 100 ms')
            fifo = os.open(run / 'rungic-communication-output.pcm', os.O_WRONLY | os.O_NONBLOCK)
            first = bytes(range(256)) * 15                 # what PulseAudio's android_communication sink writes
            os.write(fifo, first)
            wait_for(lambda: android.pcm(1) == first, 'the PCM at Android, epoch 1')
            steps.append("the call's PCM reaches Android in packets of the session's epoch")
            owner.send({**REQUESTS['flush'], 'sessionId': 'provider-test', 'id': 2})
            flushed = owner.next(lambda m: m.get('id') == 2 and m.get('type') != 'position')
            keeps('flushed', flushed, steps, 'flush: answered with the next epoch')
            if flushed['newEpoch'] != 2 or android.epoch != 2:
                raise harness.Failed(f'flush: {flushed}, Android at {android.epoch}')
            second = bytes(reversed(first))
            os.write(fifo, second)
            wait_for(lambda: android.pcm(2) == second, 'the PCM at Android, epoch 2')
            steps.append('after a flush the PCM carries the new epoch')
            owner.send({**REQUESTS['mute'], 'sessionId': 'provider-test', 'id': 3})
            keeps('muted', owner.next(lambda m: m.get('id') == 3 and m.get('type') != 'position'), steps, 'mute answered')
            intruder = Lines(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
            intruder.sock.connect(str(path))
            intruder.send({**REQUESTS['open'], 'sessionId': 'intruder'})
            if intruder.next().get('error') != 'Communication audio is in use':
                raise harness.Failed('a second client was not refused')
            steps.append('a second client is refused while the session is open')
            owner.send({**REQUESTS['close'], 'sessionId': 'provider-test', 'id': 4})
            keeps('closed', owner.next(lambda m: m.get('id') == 4 and m.get('type') != 'position'), steps, 'close answered')
            os.close(fifo)
            wait_for(lambda: log.read_text().count('unload-module') == 2, 'the PulseAudio devices unloaded')
            calls = log.read_text().splitlines()
            if not (any(c.startswith('load-module module-pipe-sink sink_name=android_communication ') for c in calls)
                    and any(c.startswith('load-module module-pipe-source source_name=android_communication_microphone ') for c in calls)
                    and 'set-sink-volume android_communication 40%' in calls):
                raise harness.Failed(f'pactl: {calls}')
            steps.append("the devices follow the phone output's volume and are unloaded on close")
        finally:
            process.terminate()
            process.wait(5)
            CAPTURE.unlink(missing_ok=True)


def test():
    steps = []
    service, client = build()
    consumer(client, steps)
    provider(service, steps)
    return steps


if __name__ == '__main__':
    harness.run('communication_audio', test)
