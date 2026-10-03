#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Voice messages (docs/62, docs/68): rungic-cua's desktop_voice_message as it runs, with stand-ins for
what is not Linux logic: the audio router (rungic-audio-route's "routed source-output" line, the
system's sign that the app records from the Linux microphone), the model that presses controls
(luna's ComputerUse), pacat and OpenAI's text-to-speech. Nothing is recorded, played or sent."""
import ast
import io
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'agent/computer-use'))
from rungic_cua import speech  # noqa: E402

source = ROOT / 'agent/computer-use/rungic_cua/server.py'
tree = ast.parse(source.read_text())
cua = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Cua')
cua.body = [n for n in cua.body if isinstance(n, ast.FunctionDef) and n.name == 'voice_message_luna']


class Router:
    """rungic-audio-route --microphone: 'ready', then a line when the app's recording stream is routed."""

    def __init__(self, log):
        self.lines = queue.Queue()
        self.log = log
        self.stdin = Mock()
        self.stdout = self

    def readline(self):
        return 'ready\n'

    def __iter__(self):
        while True:
            line = self.lines.get()
            if line is None:
                return
            yield line

    def records(self):
        self.log.append('app records from the Linux microphone')
        self.lines.put('routed source-output 41 (wechat)\n')

    def wait(self, timeout=None):
        self.lines.put(None)
        self.log.append('router closed')


class Computer:
    """The model on screen: presses record (the app may or may not start recording), then send."""

    def __init__(self, test, backend, output, window):
        self.test = test

    def run(self, task, *, max_steps=40, timeout_s=280, stop=None, gate=None):
        log = self.test.log
        if task.startswith('In the chat that is open, start recording'):
            self.test.start_goal = task
            if self.test.app_records:
                self.test.router.records()
                deadline = time.monotonic() + 5
                while not stop() and time.monotonic() < deadline:   # stopped as soon as recording started
                    time.sleep(0.01)
                log.append('record pressed; model stopped' if stop() else 'record pressed; never stopped')
            return {'outcome': 'done', 'steps': [{'actions': ['click record']}]}
        if task.startswith('A voice message is being recorded'):
            log.append('send control found while speaking')
            gate.wait(10)                                  # luna acts only once the gate opens
            log.append('send pressed')
            return {'outcome': self.test.send_outcome, 'answer': 'the voice message is in the chat', 'steps': []}
        log.append('cancel pressed')
        return {'outcome': 'done', 'steps': []}


class VoiceMessageTest(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.app_records = True
        self.send_outcome = 'done'
        self.router = Router(self.log)
        self.played = []

        def run(argv, **kwargs):
            self.assertEqual(argv[0], 'pacat')
            self.assertIn('--device=linux_microphone_input', argv)
            self.log.append('speech plays')
            self.played.append(kwargs['input'])
            time.sleep(0.05)
            self.log.append('speech ended')
        namespace = {'speech': types.SimpleNamespace(synthesize=lambda text, voice='marin': b'\x01\x00' * 24000,
                                                     RATE=speech.RATE),
                     'os': types.SimpleNamespace(path=os.path, readlink=lambda path: '/opt/wechat/wechat'),
                     'subprocess': types.SimpleNamespace(Popen=lambda *a, **k: self.router, run=run,
                                                         PIPE=-1, TimeoutExpired=TimeoutError),
                     'threading': threading, 'time': time,
                     'ComputerUse': lambda backend, output, window: Computer(self, backend, output, window)}
        exec(compile(ast.Module(body=[cua], type_ignores=[]), str(source), 'exec'), namespace)
        self.cua = namespace['Cua']()
        self.cua.agent_output = lambda: 'WL-1'
        self.cua.backend = types.SimpleNamespace(kwin=types.SimpleNamespace(
            windows=lambda: {'active': {'pid': 4242, 'output': 'WL-1', 'id': 'chat-window'}}))

    # covers: agent.voice-message/E1
    def test_speech_waits_for_the_recording_and_send_waits_for_the_speech(self):
        result = self.cua.voice_message_luna({'text': '晚上七点见'})
        self.assertTrue(result['sent'])
        self.assertEqual(result['app'], 'wechat')
        order = [entry for entry in self.log if entry != 'send control found while speaking']
        self.assertEqual(order, ['app records from the Linux microphone', 'record pressed; model stopped',
                                 'speech plays', 'speech ended', 'send pressed', 'router closed'])
        # The send control is looked for while the speech plays (no long silence at the end).
        self.assertLess(self.log.index('send control found while speaking'), self.log.index('speech ended'))
        self.assertEqual(result['seconds'], 1.0)

    # covers: agent.voice-message/E1
    def test_no_recording_through_the_linux_microphone_means_nothing_spoken(self):
        self.app_records = False
        result = self.cua.voice_message_luna({'text': '晚上七点见'})
        self.assertFalse(result['sent'])
        self.assertIn('did not start recording through the Linux microphone; nothing was spoken', result['note'])
        self.assertEqual(self.played, [])
        self.assertEqual(self.log[-1], 'router closed')

    # covers: agent.voice-message/E1
    def test_a_send_that_failed_is_cancelled_not_left_to_be_sent(self):
        self.send_outcome = 'failed'
        result = self.cua.voice_message_luna({'text': '晚上七点见'})
        self.assertFalse(result['sent'])
        self.assertIn('cancel pressed', self.log)
        self.assertLess(self.log.index('cancel pressed'), self.log.index('router closed'))

    # covers: agent.voice-message/E1
    def test_the_speech_has_its_lead_in_and_tail(self):
        pcm = b'\x10\x00' * 4800
        response = io.BytesIO(pcm)
        response.__enter__ = lambda *a: response
        response.__exit__ = lambda *a: None
        with patch.object(speech.urllib.request, 'urlopen', return_value=response) as urlopen, \
                patch.object(speech.keys, 'read', return_value='sk-test'):
            audio = speech.synthesize('晚上七点见')
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(body['response_format'], 'pcm')
        silence = bytes(int(speech.RATE * 0.3) * 2)
        self.assertEqual(audio, silence + pcm + silence)


if __name__ == '__main__':
    unittest.main()
