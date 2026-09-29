"""A failed model turn must remain visible as a failure, including missing authentication."""
import ast
from pathlib import Path
import threading
import time
import types
import unittest
from unittest.mock import Mock

source = Path(__file__).resolve().parents[2] / 'plasma/voice-agent/rungic_voice_agent.py'
node = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'VoiceAgent')
node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == 'on_notification']
namespace = {'time': time, 'screen_activity': lambda: {}, 'GLib': types.SimpleNamespace(idle_add=Mock())}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)

class SuggestionErrorTests(unittest.TestCase):
    def agent(self):
        a = namespace['VoiceAgent']()
        a.thread_id = 'thread'; a.emit = Mock(); a.set_state = Mock()
        a.turn = None; a.turn_lock = threading.Lock()
        return a

    def test_failed_completion_reports_reason(self):
        a = self.agent()
        a.on_notification('turn/completed', {'threadId': 'thread', 'turn': {'status': 'failed', 'error': {'message': '401 authentication missing'}}})
        self.assertEqual(a.emit.call_args_list[0].args[0], {'type': 'error', 'text': '401 authentication missing'})
        self.assertFalse(a.agent_busy)

    def test_retry_does_not_prematurely_fail_task(self):
        a = self.agent()
        a.on_notification('error', {'threadId': 'thread', 'willRetry': True, 'error': {'message': 'temporary'}})
        a.emit.assert_not_called()
        a.on_notification('error', {'threadId': 'thread', 'willRetry': False, 'error': {'message': 'unavailable'}})
        self.assertEqual(a.emit.call_args.args[0]['text'], 'unavailable')
