"""Check approved-plan handoff and stopping only the matching task, without model/network access."""
import ast
import json
from pathlib import Path
import re
import threading
import time
import types
import unittest
from unittest.mock import Mock

source = Path(__file__).resolve().parents[2] / 'plasma/voice-agent/rungic_voice_agent.py'
node = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'VoiceAgent')
node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in
             {'investigate_suggestion', 'suggestion_task', 'stop_suggestion', 'emit'}]
connection = Mock()
namespace = {'json': json, 're': re, 'time': time,
             'Gio': types.SimpleNamespace(bus_get_sync=lambda *a: connection, BusType=types.SimpleNamespace(SESSION=0), DBusCallFlags=types.SimpleNamespace(NONE=0)),
             'GLib': types.SimpleNamespace(Variant=lambda *a: a, VariantType=types.SimpleNamespace(new=lambda v: v))}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)

class SuggestionTaskTests(unittest.TestCase):
    def setUp(self):
        self.a = namespace['VoiceAgent']()
        self.a.lock = threading.Lock(); self.a.agent_busy = False; self.a.talking = False
        self.a.thread_id = 'conversation'; self.a.turn_id = 'turn'
        self.a.call_in_progress = Mock(return_value=False); self.a.needs_setup = Mock(return_value=False)
        self.a.store = types.SimpleNamespace(index={'conversation': {}}, touch=Mock())
        self.a.open_conversation = Mock(return_value={'conversation': 'conversation'})
        self.a.emit = Mock(); self.a.send_text = Mock(); self.a.server = Mock()
        self.id = 'a' * 24
        self.item = {'id': self.id, 'title': 'test', 'plan': 'UNAPPROVED LATER PLAN',
                     'task': {'id': 'task', 'state': 'running', 'mode': 'apply',
                              'approvedPlan': {'planRevision': 'r1', 'plan': 'APPROVED SNAPSHOT', 'verification': 'check', 'rollback': 'undo'}}}
        connection.call_sync.return_value.unpack.side_effect = lambda: (json.dumps(self.item),)

    def test_apply_uses_frozen_snapshot(self):
        self.a.investigate_suggestion(self.id, 'task', apply=True)
        text = self.a.send_text.call_args.args[0]
        self.assertIn('APPROVED SNAPSHOT', text)
        self.assertNotIn('UNAPPROVED LATER PLAN', text)
        self.assertEqual(self.a.store.index['conversation']['suggestionTask'], 'task')

    def test_wrong_task_and_wrong_mode_cannot_execute(self):
        with self.assertRaises(RuntimeError): self.a.investigate_suggestion(self.id, 'old-task', apply=True)
        with self.assertRaises(RuntimeError): self.a.investigate_suggestion(self.id, 'task', apply=False)
        self.a.send_text.assert_not_called()

    def test_auth_setup_failure_is_not_a_started_task(self):
        self.a.needs_setup.return_value = True
        with self.assertRaises(RuntimeError): self.a.investigate_suggestion(self.id, 'task', apply=True)
        self.a.open_conversation.assert_not_called()

    def test_stopping_old_task_does_not_interrupt_other_conversation(self):
        self.a.agent_busy = True
        self.a.store.index['conversation'] = {'suggestion': 'different', 'suggestionTask': 'new-task'}
        self.a.stop_suggestion(self.id, 'task')
        self.a.server.call.assert_not_called()
        self.assertEqual(self.a.emit.call_args.args[0]['suggestionTask'], 'task')

    def test_failed_interrupt_keeps_task_running(self):
        self.a.agent_busy = True
        self.a.store.index['conversation'] = {'suggestion': self.id, 'suggestionTask': 'task'}
        self.a.server.call.side_effect = RuntimeError('transport unavailable')
        with self.assertRaises(RuntimeError): self.a.stop_suggestion(self.id, 'task')
        self.a.emit.assert_not_called()
        self.assertEqual(self.a.suggestion_task(self.id, 'task')['state'], 'running')

    def test_finished_result_can_be_recovered_after_switching_conversations(self):
        self.a.store.index['original'] = {'suggestion': self.id, 'suggestionTask': 'task',
                                         'suggestionTaskState': 'finished', 'suggestionResult': 'saved result'}
        status = self.a.suggestion_task(self.id, 'task')
        self.assertEqual(status['state'], 'finished')
        self.assertEqual(status['result'], 'saved result')

    def test_terminal_result_is_persisted_before_event_delivery(self):
        self.a.store.index['conversation'] = {'suggestion': self.id, 'suggestionTask': 'task', 'suggestionTaskState': 'running'}
        self.a.store.save_index = Mock(); self.a.store.append = Mock(); self.a.emit_raw = Mock()
        emit = namespace['VoiceAgent'].emit
        emit(self.a, {'type': 'agent-message', 'final': True, 'text': 'actual result'})
        emit(self.a, {'type': 'agent-finished'})
        self.assertEqual(self.a.store.index['conversation']['suggestionTaskState'], 'finished')
        self.assertEqual(self.a.store.index['conversation']['suggestionResult'], 'actual result')
        self.assertEqual(self.a.store.save_index.call_count, 2)
        self.assertEqual(self.a.emit_raw.call_args.args[0]['suggestionTask'], 'task')
