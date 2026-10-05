"""The agent at work, whichever way it was asked (2026-10-05): a push-to-talk turn or a task given in
a call. The assistant's screen, the director and the wake lock go by it."""
import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

source = Path(__file__).resolve().parents[2] / 'agent/assistant/rungic_voice_agent.py'
node = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'VoiceAgent')
node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in ('update_at_work', 'at_work', 'phone_work', 'phone_emit')]
calls = []
namespace = {'mark_agent_busy': lambda busy: calls.append(('busy', busy)),
             'forget_screen_dismissal': lambda: calls.append(('forget',))}
exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)


class AtWorkTests(unittest.TestCase):
    def agent(self, tasks=(), busy=False, background=None):
        a = namespace['VoiceAgent']()
        a.agent_busy, a.background = busy, background or {}
        a.phone = types.SimpleNamespace(snapshot={'sessionId': '', 'tasks': list(tasks)})
        a.emit = Mock()
        calls.clear()
        return a

    # covers: agent.workspace-lifecycle/E6
    def test_a_task_given_in_a_call_is_work_after_the_call(self):
        a = self.agent([{'taskId': 't', 'status': 'running', 'readOnly': False}])
        self.assertTrue(a.at_work())
        a.phone_emit({'type': 'phone-state'})
        self.assertEqual(calls, [('busy', True)], 'the phone stays awake for it')
        a.emit.assert_called_once()

    # covers: agent.workspace-lifecycle/E6
    def test_a_read_only_task_does_not_act_on_the_desktop(self):
        self.assertFalse(self.agent([{'taskId': 't', 'status': 'running', 'readOnly': True}]).at_work())

    # covers: agent.workspace-lifecycle/E6
    def test_when_the_work_ends_closed_screens_come_back_next_time(self):
        a = self.agent([{'taskId': 't', 'status': 'running', 'readOnly': False}])
        a.update_at_work()
        a.phone.snapshot['tasks'][0]['status'] = 'completed'
        calls.clear()
        a.phone_emit({'type': 'phone-task'})
        self.assertEqual(calls, [('busy', False), ('forget',)])

    # covers: agent.workspace-lifecycle/E6
    def test_a_background_call_step_keeps_the_phone_awake_only(self):
        a = self.agent(background={'th': 1})
        self.assertFalse(a.at_work(), 'the screens go by desktop work')
        a.update_at_work()
        self.assertEqual(calls, [('busy', True)])


if __name__ == '__main__':
    unittest.main()
