#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise service methods with external adapters replaced, without starting D-Bus."""
import ast
import json
from pathlib import Path
import sys
import time
import types
import unittest
import uuid
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'plasma/voice-agent'))
source = ROOT / 'plasma/voice-agent/rungic_voice_agent.py'
tree = ast.parse(source.read_text())
agent_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VoiceAgent')
methods = {'emit', '_start_call', 'call_command'}
agent_class.body = [n for n in agent_class.body if isinstance(n, ast.FunctionDef) and n.name in methods]
namespace = dict(json=json, time=time, uuid=uuid,
                 GLib=types.SimpleNamespace(idle_add=lambda fn: fn()), threading=Mock())
exec(compile(ast.Module(body=[agent_class], type_ignores=[]), str(source), 'exec'), namespace)
VoiceAgent = namespace['VoiceAgent']


class FakeCall:
    def __init__(self, emit, tell_owner, **kwargs):
        self.emit = emit
        self.app = kwargs['app']
        self.phase = 'agent'
        self.active = True
        self.ready = Mock(wait=Mock(return_value=True))
        self.hang_up = Mock()
        self.instruct = Mock()
        self.take_over = Mock()

    def start(self):
        self.emit({'type':'call-started','backend':self.app})


class CallConversationTest(unittest.TestCase):
    def setUp(self):
        self.agent = VoiceAgent()
        self.agent.thread_id = 'origin'
        self.agent.call = None
        for name in ('store','emit_raw','tell_owner','set_state','start_realtime','stop_realtime',
                     'watch_user_audio','speak_call_result'):
            setattr(self.agent, name, Mock())
        namespace['threading'].reset_mock()

    def start(self):
        with patch.dict(sys.modules, {'call_proxy':types.SimpleNamespace(CallProxy=FakeCall)}):
            return self.agent._start_call({'backend':'app','app':'wechat','contact':'Test'})

    def test_events_and_persistence_follow_origin_after_switch(self):
        result = self.start()
        self.agent.thread_id = 'other'
        self.agent.call.emit({'type':'call-state','state':'connected'}, keep=False)
        conversation, event = self.agent.store.append.call_args.args
        self.assertEqual(conversation, 'origin')
        self.assertEqual(event['conversation'], 'origin')
        self.assertEqual(event['callId'], result['callId'])
        self.assertGreater(event['connectedAt'], 0)
        self.agent.call.emit({'type':'call-ended','summary':'Done'})
        self.assertEqual(self.agent.store.append.call_args.args[0], 'origin')
        namespace['threading'].Thread.assert_not_called()  # no speech in the unrelated conversation

    def test_no_implicit_default_call(self):
        with patch.dict(sys.modules, {'call_proxy':types.SimpleNamespace(CallProxy=Mock())}) as modules:
            with self.assertRaises(ValueError):
                self.agent._start_call({'contact':'Test'})
            modules['call_proxy'].CallProxy.assert_not_called()

    def test_old_card_cannot_hang_up_or_instruct_another_call(self):
        self.start()
        for op in ('hang-up','take-over','instruct','dtmf'):
            with self.subTest(op=op), self.assertRaises(ValueError):
                self.agent.call_command(json.dumps({'callId':'previous','op':op,'text':'hello','digit':'1'}))
        self.agent.call.hang_up.assert_not_called()
        self.agent.call.instruct.assert_not_called()
        self.agent.call.take_over.assert_not_called()

    def test_current_card_and_existing_cli_controls(self):
        result = self.start()
        self.agent.call_command(json.dumps({'callId':result['callId'],'op':'instruct','text':' 请询问进度 '}))
        self.agent.call.instruct.assert_called_once_with('请询问进度')
        self.agent.call_command('take-over')
        self.agent.call.take_over.assert_called_once()
        self.agent.call_command(json.dumps({'callId':result['callId'],'op':'hang-up'}))
        self.agent.call.hang_up.assert_called_once()

    def test_delayed_old_events_do_not_pause_new_call(self):
        self.start()
        previous = self.agent.call
        previous.phase = 'ended'
        self.start()
        previous.emit({'type':'call-phase','phase':'user'})
        previous.emit({'type':'call-ended'})
        namespace['threading'].Thread.assert_not_called()


if __name__ == '__main__':
    unittest.main()
