# SPDX-License-Identifier: MIT
"""Framed control and clocked PCM for Android's shared cellular-call backend.

No PulseAudio routing or vendor mixer configuration lives here. The negotiated
24 kHz mono stream carries only the remote party and the agent, never a room mic.
"""
from __future__ import annotations

import json
import socket
import struct
import threading
import time

ADDRESS = '\0com.rungic.calls.v1'
FRAME_BYTES = 960                         # 20 ms, 24 kHz, mono PCM16


def connect():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(4)
        sock.connect(ADDRESS)
        _, uid, _ = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != 0:
            raise PermissionError('untrusted cellular backend')
        return sock
    except BaseException:
        sock.close()
        raise


def exchange(sock, request):
    sock.sendall(json.dumps(request).encode() + b'\n')
    data = bytearray()
    while len(data) <= 16384:
        part = sock.recv(1)                 # do not consume the PCM after the JSON
        if not part:
            raise ConnectionError('cellular backend disconnected')
        if part == b'\n':
            response = json.loads(data)
            if response.get('error'):
                raise RuntimeError('cellular: ' + response.get('reason', response['error']))
            return response
        data.extend(part)
    raise ValueError('oversized cellular response')


def request(op, **fields):
    with connect() as sock:
        return exchange(sock, {'op': op, **fields})


class PCMPlayer:
    """CallProxy's player interface plus duplex transport. Writes paced in real time,
    with silence between turns; bounded buffering and EOF trigger safe handover.
    close() may be called from either worker and never joins its own thread.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = bytearray()
        self.held = None
        self.sock = None
        self.closed = False
        self.last_audio = 0.0
        self.error = None

    def open(self, call_id, on_audio, on_error):
        sock = connect()
        try:
            result = exchange(sock, {'op': 'audio', 'id': call_id})
            if (result.get('rate'), result.get('channels'), result.get('format')) != (24000, 1, 's16le'):
                raise ValueError('unsupported cellular audio format')
            with self.lock:
                if self.closed:
                    raise RuntimeError('call cancelled before audio opened')
                self.sock, self.error = sock, on_error
        except BaseException:
            sock.close()
            raise
        threading.Thread(target=self._receive, args=(sock, on_audio), daemon=True).start()
        threading.Thread(target=self._transmit, args=(sock,), daemon=True).start()

    def push(self, data):
        with self.lock:
            if self.closed:
                return False
            target = self.pending if self.held is None else self.held
            if len(target) + len(data) > 24000 * 2 * 60:
                # Never let a stalled consumer accumulate unbounded speech.
                threading.Thread(target=self._failed, daemon=True).start()
                return False
            target.extend(data)
        return False

    def hold(self):
        with self.lock:
            self.held = bytearray()
        return False

    def release(self):
        with self.lock:
            self.pending.extend(self.held or b'')
            self.held = None
        return False

    def drop(self):
        with self.lock:
            self.held = None
        return False

    def flush(self):
        with self.lock:
            self.pending.clear()
            self.held = None
            self.last_audio = 0
        return False

    def busy(self):
        with self.lock:
            return bool(self.pending) or time.monotonic() < self.last_audio + .08

    def _receive(self, sock, on_audio):
        tail = b''
        try:
            while not self.closed:
                data = sock.recv(4800)
                if not data:
                    raise EOFError()
                data = tail + data
                size = len(data) & ~1
                if size:
                    on_audio(data[:size])
                tail = data[size:]
        except (OSError, EOFError):
            self._failed()

    def _transmit(self, sock):
        deadline = time.monotonic()
        try:
            while not self.closed:
                with self.lock:
                    data = bytes(self.pending[:FRAME_BYTES])
                    del self.pending[:FRAME_BYTES]
                    if data:
                        self.last_audio = time.monotonic()
                sock.sendall(data.ljust(FRAME_BYTES, b'\0'))
                deadline = max(deadline + .02, time.monotonic())
                time.sleep(max(0, deadline - time.monotonic()))
        except OSError:
            self._failed()

    def _failed(self):
        callback = self.error
        if self.close() and callback:
            callback()

    def close(self):
        with self.lock:
            if self.closed:
                return False
            self.closed = True
            self.pending.clear()
            self.held = None
            sock, self.sock = self.sock, None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        return True
