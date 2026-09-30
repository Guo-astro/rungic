#!/usr/bin/env python3
"""The ChatGPT device-code sign-in (docs/101). Codex replaces a sign-in under way with every new one
and ends the old as "Login was not completed" (codex-rs app-server account_processor.rs): a second
tap then showed the new code for a moment and the old one's end covered it. The service hands back
the code under way while it is valid, drops the ends of replaced sign-ins, and cancels for real."""
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
                    and n.name in {'codex_login', 'cancel_codex_login', 'login_completed'}]
clock = [1000.0]
namespace = {'threading': threading, 'log': lambda *a: None, '_': lambda text: text, 'openai_key': lambda: 'sk-test',
             'DEVICE_CODE_S': 15 * 60, 'time': type('time', (), {'time': staticmethod(lambda: clock[0])})}
exec(compile(ast.Module(body=[agent_class], type_ignores=[]), str(source), 'exec'), namespace)
VoiceAgent = namespace['VoiceAgent']


class FakeCodex:
    def __init__(self):
        self.calls, self.started = [], 0

    def call(self, method, params, timeout=60):
        self.calls.append((method, params))
        if method == 'account/login/start' and params['type'] == 'chatgptDeviceCode':
            self.started += 1
            return {'type': 'chatgptDeviceCode', 'loginId': f'login-{self.started}', 'userCode': f'CODE-{self.started}',
                    'verificationUrl': 'https://auth.openai.com/codex/device'}
        return {}


class CodexLoginTests(unittest.TestCase):
    def setUp(self):
        clock[0] = 1000.0
        self.codex = FakeCodex()
        self.agent = VoiceAgent()
        self.agent.server = self.codex
        self.agent.login = None
        self.agent.login_lock = threading.Lock()
        self.agent.logins_cancelled = set()
        self.agent.emit_raw = Mock()
        self.agent.restart_server = Mock()

    def events(self):
        return [c.args[0] for c in self.agent.emit_raw.call_args_list if c.args[0]['type'] == 'account']

    def test_second_tap_shows_the_same_code(self):
        first = self.agent.codex_login('chatgpt')
        clock[0] += 60
        second = self.agent.codex_login('chatgpt')
        self.assertEqual((first['userCode'], second['userCode']), ('CODE-1', 'CODE-1'))
        self.assertEqual(self.codex.started, 1)          # Codex never replaced the first sign-in

    def test_an_expired_code_is_asked_again(self):
        self.agent.codex_login('chatgpt')
        clock[0] += 15 * 60
        self.assertEqual(self.agent.codex_login('chatgpt')['userCode'], 'CODE-2')

    def test_a_replaced_sign_in_ending_is_not_shown(self):
        self.agent.login = {'loginId': 'login-2', 'userCode': 'CODE-2', 'verificationUrl': '', 'started': clock[0]}
        self.agent.login_completed({'loginId': 'login-1', 'success': False, 'error': 'Login was not completed'})
        self.assertEqual(self.events(), [])
        self.assertEqual(self.agent.login['loginId'], 'login-2')

    def test_the_current_sign_in_ending_is_shown(self):
        self.agent.codex_login('chatgpt')
        self.agent.login_completed({'loginId': 'login-1', 'success': True})
        self.assertEqual(self.events()[0]['success'], True)
        self.assertIsNone(self.agent.login)
        for t in threading.enumerate():                     # the restart runs in a thread
            if t is not threading.current_thread() and t.daemon:
                t.join(1)
        self.agent.restart_server.assert_called_once()     # Codex reads the new sign-in when it starts
        self.agent.codex_login('chatgpt')
        self.agent.login_completed({'loginId': 'login-2', 'success': False, 'error': 'expired'})
        self.assertEqual(self.events()[-1]['error'], 'expired')

    def test_cancel_reaches_codex(self):
        self.agent.codex_login('chatgpt')
        self.agent.cancel_codex_login()
        self.assertIn(('account/login/cancel', {'loginId': 'login-1'}), self.codex.calls)
        self.assertIsNone(self.agent.login)

    def test_a_cancelled_sign_in_ending_is_not_a_failure_on_the_page(self):
        self.agent.codex_login('chatgpt')
        self.agent.cancel_codex_login()
        self.agent.login_completed({'loginId': 'login-1', 'success': False, 'error': 'Login was not completed'})
        self.assertEqual(self.events(), [])

    def test_api_key_forgets_the_device_code(self):
        self.agent.codex_login('chatgpt')
        self.agent.codex_login('apiKey')
        self.assertIsNone(self.agent.login)


if __name__ == '__main__':
    unittest.main()
