#!/usr/bin/python3
"""Route one application's audio through the Linux microphone / speaker (docs/62).

  moto-audio-route --binary wechat --microphone [--speaker]

While this runs, the application's capture streams are moved to
linux_microphone and (with --speaker) its playback streams to linux_speaker,
including streams it opens later (e.g. when a recording or a call starts).
On exit (SIGTERM, SIGINT or stdin closed) every moved stream goes back to the
device it came from. Prints "ready" once watching and one line per move.

Matching is by application.process.binary: calls in WeChat come from its
WebRTC module and are named "Chromium", a name other applications share.
PulseAudio's stream-restore remembers each move by application name; moving
back at the end leaves the application on the device it used before.
"""
import argparse
import os
import select
import signal
import stat
import subprocess
import sys
import threading

MIC, SPEAKER = 'linux_microphone', 'linux_speaker'
ENV = {**os.environ, 'LC_ALL': 'C'}


def pactl(*args):
    return subprocess.run(['pactl', *args], capture_output=True, text=True, env=ENV, timeout=5)


def names(kind):
    """index -> name of sinks or sources."""
    out = {}
    for line in pactl('list', 'short', kind).stdout.splitlines():
        fields = line.split('\t')
        if len(fields) >= 2:
            out[fields[0]] = fields[1]
    return out


def streams(kind, binary):
    """{index: device index} of the binary's sink-inputs or source-outputs."""
    header = 'Sink Input #' if kind == 'sink-inputs' else 'Source Output #'
    device_key = 'Sink:' if kind == 'sink-inputs' else 'Source:'
    found, index, device, match = {}, None, None, False
    for line in pactl('list', kind).stdout.splitlines() + [header + 'end']:
        if line.startswith(header):
            if index is not None and match:
                found[index] = device
            index, device, match = line[len(header):].strip(), None, False
        elif line.strip().startswith(device_key):
            device = line.split(':', 1)[1].strip()
        elif line.strip() == f'application.process.binary = "{binary}"':
            match = True
    return found


class Router:
    def __init__(self, binary, microphone, speaker):
        self.binary = binary
        self.targets = {}
        if microphone:
            self.targets['source-outputs'] = ('move-source-output', 'sources', MIC)
        if speaker:
            self.targets['sink-inputs'] = ('move-sink-input', 'sinks', SPEAKER)
        self.moved = {}     # (kind, index) -> original device name
        self.lock = threading.Lock()

    def sweep(self):
        with self.lock:
            for kind, (command, devices, target) in self.targets.items():
                by_index = names(devices)
                for index, device in streams(kind, self.binary).items():
                    if (kind, index) in self.moved or by_index.get(device) == target:
                        continue
                    if pactl(command, index, target).returncode == 0:
                        self.moved[(kind, index)] = by_index.get(device, device)
                        print(f'routed {kind[:-1]} {index} {self.moved[(kind, index)]} -> {target}', flush=True)

    def restore(self):
        with self.lock:
            commands = {kind: command for kind, (command, _, _) in self.targets.items()}
            for (kind, index), original in self.moved.items():
                if pactl(commands[kind], index, original).returncode == 0:
                    print(f'restored {kind[:-1]} {index} -> {original}', flush=True)
            self.moved.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--binary', required=True, help='application.process.binary, e.g. wechat')
    parser.add_argument('--microphone', action='store_true', help='capture streams -> Linux 麦克风')
    parser.add_argument('--speaker', action='store_true', help='playback streams -> Linux 扬声器')
    args = parser.parse_args()
    if not (args.microphone or args.speaker):
        parser.error('choose --microphone and/or --speaker')
    router = Router(args.binary, args.microphone, args.speaker)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    watch = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, env=ENV)
    # A caller holding a pipe to stdin ends the routing by closing it (or dying).
    inputs = [watch.stdout] + ([sys.stdin] if stat.S_ISFIFO(os.fstat(0).st_mode) else [])
    try:
        router.sweep()
        print('ready', flush=True)
        while not stop.is_set():
            ready = select.select(inputs, [], [], 0.5)[0]
            if sys.stdin in ready and not sys.stdin.readline():
                break
            if watch.stdout in ready:
                line = watch.stdout.readline()
                if not line:
                    break
                if "'new' on source-output" in line or "'new' on sink-input" in line:
                    router.sweep()
    finally:
        router.restore()
        watch.terminate()
    return 0


if __name__ == '__main__':
    sys.exit(main())
