#!/usr/bin/python3
"""Demand-driven Android mic / camera integration. Run as the desktop user.

PulseAudio remains the audio server; PipeWire exports Camera Video/Source nodes.
Capture sockets are private to the Android app and never listen on TCP.
"""
import fcntl
import json
import logging
import os
import select
import signal
import socket
import stat
import subprocess
import threading
import time
from pathlib import Path

RUNTIME = Path(os.environ['XDG_RUNTIME_DIR'])
FIFO = RUNTIME / 'moto-microphone.pcm'
SOURCE = 'android_microphone'
LOG = logging.getLogger('android-media')
STOP = threading.Event()
CHANGED = threading.Event()


def pactl(*args):
    return subprocess.check_output(['pactl', *args], text=True, timeout=3,
                                   env={**os.environ, 'LC_ALL': 'C'}).strip()


def read_header(client):
    data = bytearray()
    while len(data) < 65536:
        c = client.recv(1)
        if not c:
            raise OSError('Android capture connection closed')
        if c == b'\n':
            result = json.loads(data)
            if 'error' in result:
                raise OSError(result['error'])
            return result
        data.extend(c)
    raise OSError('Android response too large')


def host_info():
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(2)
        client.connect('/mnt/android-wayland/platform.sock')
        client.sendall(b'{"op":"capture-info"}\n')
        return read_header(client)


class Microphone:
    def __init__(self):
        self.thread = None
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.socket = None
        self.retry_at = 0

    def stop(self):
        self.cancel.set()
        with self.lock:
            if self.socket:
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.thread:
            self.thread.join(3)
            if not self.thread.is_alive():
                self.thread = None

    def set_wanted(self, wanted):
        if not wanted:
            self.stop()
        elif (not self.thread or not self.thread.is_alive()) and time.monotonic() >= self.retry_at:
            self.cancel.clear()
            self.thread = threading.Thread(target=self.capture, daemon=True)
            self.thread.start()

    def capture(self):
        fd = None
        try:
            with socket.socket(socket.AF_UNIX) as client:
                with self.lock:
                    self.socket = client
                if self.cancel.is_set():
                    return
                client.settimeout(50)  # Android's interactive runtime permission dialog.
                client.connect('/mnt/android-wayland/capture.sock')
                client.sendall(b'{"op":"microphone"}\n')
                header = read_header(client)
                if header != {'ok': True, 'rate': 48000, 'channels': 1, 'format': 's16le'}:
                    raise OSError('Unsupported Android microphone format')
                client.settimeout(3)
                fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
                LOG.info('microphone consumer started')
                while not self.cancel.is_set() and not STOP.is_set():
                    block = memoryview(client.recv(9600))
                    if not block:
                        raise OSError('Android microphone stream closed')
                    while block and not self.cancel.is_set():
                        if select.select([], [fd], [], 0.2)[1]:
                            try:
                                count = os.write(fd, block)
                                block = block[count:]
                            except BlockingIOError:
                                pass
        except (OSError, ValueError) as error:
            if not self.cancel.is_set():
                LOG.warning('microphone: %s', error)
                self.retry_at = time.monotonic() + 5
        finally:
            with self.lock:
                self.socket = None
            if fd is not None:
                os.close(fd)
            # Discard at most one FIFO of pending audio between consumers.
            try:
                drain = os.open(FIFO, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
                try:
                    while os.read(drain, 65536):
                        pass
                except BlockingIOError:
                    pass
                os.close(drain)
            except OSError:
                pass
            LOG.info('microphone consumer stopped')


class Cameras:
    def __init__(self):
        self.children = {}
        self.retry_at = {}

    def update(self, info):
        available = info.get('visible') and not (info.get('cameraDenied') and not info.get('cameraPermission'))
        desired = {str(c['id']): c for c in info.get('cameras', [])} if available else {}
        for key, process in list(self.children.items()):
            if key not in desired or process.poll() is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                del self.children[key]
                self.retry_at[key] = time.monotonic() + 2
        for key, metadata in desired.items():
            if key not in self.children and time.monotonic() >= self.retry_at.get(key, 0):
                args = ['/usr/local/bin/moto-camera-source', key]
                args.extend(str(metadata[k]) for k in ('width', 'height', 'rotation', 'facing'))
                self.children[key] = subprocess.Popen(args)
                LOG.info('camera %s available (%s)', key, metadata['facing'])


def ensure_source():
    sources = json.loads(pactl('-f', 'json', 'list', 'sources'))
    source = next((s for s in sources if s['name'] == SOURCE), None)
    if source is None:
        if FIFO.exists() and not stat.S_ISFIFO(FIFO.stat().st_mode):
            raise OSError('Microphone path is not a FIFO')
        module = pactl('load-module', 'module-pipe-source', 'source_name=' + SOURCE,
                      'file=' + str(FIFO), 'format=s16le', 'rate=48000', 'channels=1',
                      'channel_map=mono', 'source_properties=device.description=AndroidMicrophone')
        os.chmod(FIFO, 0o600)
        pactl('set-default-source', SOURCE)
        LOG.info('microphone source ready (module %s)', module)
        sources = json.loads(pactl('-f', 'json', 'list', 'sources'))
        source = next(s for s in sources if s['name'] == SOURCE)
    return source


def watch_pulse():
    while not STOP.is_set():
        try:
            process = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE, text=True)
            while not STOP.is_set() and process.poll() is None:
                if select.select([process.stdout], [], [], 1)[0]:
                    line = process.stdout.readline()
                    if not line:
                        break
                    if ' on source' in line or ' on server ' in line:
                        CHANGED.set()
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass
        STOP.wait(2)


def stop(*_):
    STOP.set()
    CHANGED.set()


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    lock = open(RUNTIME / 'moto-media.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    microphone, cameras = Microphone(), Cameras()
    threading.Thread(target=watch_pulse, daemon=True).start()
    last_info = 0
    info = {}
    try:
        while not STOP.is_set():
            now = time.monotonic()
            if now - last_info >= 1:
                try:
                    info = host_info()
                except (OSError, ValueError):
                    info = {}
                last_info = now
                cameras.update(info)
            try:
                source = ensure_source()
                # PA 17's JSON exporter rejects UTF-8 application names. Only
                # numeric Source and yes/no Corked fields are needed here.
                outputs = pactl('list', 'source-outputs').split('Source Output #')[1:]
                wanted = False
                for block in outputs:
                    fields = dict(line.strip().split(': ', 1) for line in block.splitlines() if ': ' in line)
                    if fields.get('Source') == str(source['index']) and fields.get('Corked') == 'no':
                        wanted = True
                permission = not (info.get('microphoneDenied') and not info.get('microphonePermission'))
                microphone.set_wanted(bool(wanted and info.get('visible') and permission))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                microphone.set_wanted(False)
                LOG.warning('audio server unavailable: %s', error)
                STOP.wait(3)
            CHANGED.wait(0.5)
            CHANGED.clear()
            STOP.wait(0.1)
    finally:
        microphone.stop()
        cameras.update({})


if __name__ == '__main__':
    main()
