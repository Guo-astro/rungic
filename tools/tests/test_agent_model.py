#!/usr/bin/env python3
"""The agent's model reaches the thread (docs/98): a resume of a thread Codex still has loaded keeps
its old model (measured with Codex 0.156.1), so the service unloads it (thread/unsubscribe) and
resumes again; the open conversation takes a new choice when it is idle, else after its turn."""
import ast
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

root = Path(__file__).resolve().parents[2]
source = root / 'agent/assistant/rungic_voice_agent.py'
tree = ast.parse(source.read_text())
agent_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VoiceAgent')
agent_class.body = [n for n in agent_class.body if isinstance(n, ast.FunctionDef)
                    and n.name in {'resume_with_settings', 'apply_agent_model'}]
namespace = {'threading': threading, 'log': lambda *a: None}
exec(compile(ast.Module(body=[agent_class], type_ignores=[]), str(source), 'exec'), namespace)
VoiceAgent = namespace['VoiceAgent']


class FakeCodex:
    """A loaded thread keeps its model on resume; an unloaded one takes the settings."""

    def __init__(self, loaded_model=('gpt-6-luna', 'low')):
        self.loaded = {'t1': loaded_model}
        self.calls = []

    def call(self, method, params, timeout=60):
        self.calls.append(method)
        tid = params['threadId']
        if method == 'thread/unsubscribe':
            self.loaded.pop(tid, None)
            return {'status': 'unsubscribed'}
        if method == 'thread/resume':
            if tid not in self.loaded:
                self.loaded[tid] = (params.get('model'), params['config'].get('model_reasoning_effort'))
            model, effort = self.loaded[tid]
            return {'model': model, 'reasoningEffort': effort}
        return {}


def agent(codex, model='gpt-6-astra', effort='medium', history=True):
    a = VoiceAgent()
    a.server = codex
    a.lock = threading.RLock()
    a.thread_id = 't1'
    a.agent_busy = a.talking = False
    a.realtime = a.realtime_starting = False
    a.model_pending = False
    a.stop_realtime = Mock()
    a.start_realtime = Mock()
    a.store = Mock()
    a.store.history.return_value = ['a turn'] if history else []
    a.agent_model = Mock(return_value={'model': model, 'effort': effort})
    a.thread_settings = Mock(return_value={'model': model, 'config': {'model_reasoning_effort': effort}})
    return a


class ResumeTests(unittest.TestCase):
    def test_loaded_on_another_model_is_reloaded(self):
        codex = FakeCodex()
        reply = agent(codex).resume_with_settings('t1')
        self.assertEqual((reply['model'], reply['reasoningEffort']), ('gpt-6-astra', 'medium'))
        self.assertEqual(codex.calls, ['thread/resume', 'thread/unsubscribe', 'thread/resume'])

    def test_already_on_the_model_is_left_alone(self):
        codex = FakeCodex(('gpt-6-astra', 'medium'))
        agent(codex).resume_with_settings('t1')
        self.assertEqual(codex.calls, ['thread/resume'])

    def test_unknown_catalog_never_reloads(self):
        codex = FakeCodex()
        agent(codex, model=None, effort=None).resume_with_settings('t1')
        self.assertEqual(codex.calls, ['thread/resume'])


class ApplyTests(unittest.TestCase):
    def test_idle_conversation_takes_it_now_and_the_voice_comes_back(self):
        codex = FakeCodex()
        a = agent(codex)
        a.realtime = True
        a.apply_agent_model()
        a.stop_realtime.assert_called_once()
        self.assertEqual(codex.loaded['t1'], ('gpt-6-astra', 'medium'))
        self.assertFalse(a.model_pending)

    def test_busy_or_empty_conversation_waits(self):
        for kwargs, setup in (({}, {'agent_busy': True}), ({}, {'talking': True}), ({'history': False}, {})):
            codex = FakeCodex()
            a = agent(codex, **kwargs)
            for k, v in setup.items():
                setattr(a, k, v)
            a.apply_agent_model()
            self.assertTrue(a.model_pending)
            self.assertEqual(codex.calls, [])
            a.stop_realtime.assert_not_called()


if __name__ == '__main__':
    unittest.main()
