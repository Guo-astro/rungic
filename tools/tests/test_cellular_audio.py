#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Socket-pair tests; never touch a modem or a real phone number."""
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'plasma/voice-agent'))
from cellular_audio import PCMPlayer, exchange, FRAME_BYTES


class CellularPCMTest(unittest.TestCase):
    def test_handshake_preserves_first_pcm_bytes(self):
        client, server = socket.socketpair()
        with client, server:
            server.sendall(b'{"ok":true}\n\x00\xff\x10\x00')
            self.assertEqual(exchange(client, {'op': 'audio'}), {'ok': True})
            self.assertEqual(client.recv(4), b'\x00\xff\x10\x00')

    def test_error_never_becomes_audio(self):
        client, server = socket.socketpair()
        with client, server:
            server.sendall(b'{"error":"failed","reason":"stale-call"}\n')
            with self.assertRaisesRegex(RuntimeError, 'stale-call'):
                exchange(client, {'op': 'audio'})

    def test_clocked_silence_audio_and_disconnect(self):
        client, server = socket.socketpair()
        client.settimeout(1)
        server.settimeout(1)
        player = PCMPlayer()
        received = bytearray()
        failed = threading.Event()
        server.sendall(b'{"ok":true,"rate":24000,"channels":1,"format":"s16le"}\n')
        with patch('cellular_audio.connect', return_value=client):
            player.open('call-a', received.extend, failed.set)
        request_bytes = bytearray()
        while not request_bytes.endswith(b'\n'):
            request_bytes.extend(server.recv(1))
        self.assertEqual(json.loads(request_bytes)['id'], 'call-a')
        silence = bytearray()
        while len(silence) < FRAME_BYTES:
            silence.extend(server.recv(FRAME_BYTES-len(silence)))
        self.assertEqual(bytes(silence), bytes(FRAME_BYTES))
        player.push(b'\x23\x01' * 480)
        data = bytearray()
        while b'\x23\x01' not in data:
            data.extend(server.recv(FRAME_BYTES))
        self.assertIn(b'\x23\x01', data)
        server.sendall(b'\x01'); time.sleep(.01); server.sendall(b'\x02\x03\x04')
        deadline = time.monotonic()+1
        while len(received) < 4 and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertEqual(received, b'\x01\x02\x03\x04')
        server.close()
        self.assertTrue(failed.wait(1))
        self.assertTrue(player.closed)
        self.assertFalse(player.close())

    def test_cancel_during_audio_handshake(self):
        client, server = socket.socketpair()
        with server:
            player = PCMPlayer()
            player.close()
            server.sendall(b'{"rate":24000,"channels":1,"format":"s16le"}\n')
            with patch('cellular_audio.connect', return_value=client):
                with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                    player.open('call-a', lambda _: None, lambda: None)
            self.assertEqual(client.fileno(), -1)

    def test_flush_discards_unspoken_held_audio(self):
        player = PCMPlayer()
        player.hold(); player.push(b'\x23\x01'*480)
        player.flush(); player.release()
        self.assertEqual(player.pending, b'')
        self.assertFalse(player.busy())
        player.close(); player.push(b'\xff\x7f')
        self.assertEqual(player.pending, b'')


if __name__ == '__main__':
    unittest.main()
