#!/usr/bin/env python3
"""The service and its codex app-server (docs/101): an app-server the service replaces on purpose
(restart_server: a new key, sign-in or Codex) ends quietly; one that dies on its own takes the
service down, so systemd starts it again. A switch of the sign-in once restarted the whole service."""
import ast
import unittest
from pathlib import Path
from unittest.mock import Mock

root = Path(__file__).resolve().parents[2]
source = root / 'agent/assistant/rungic_voice_agent.py'
tree = ast.parse(source.read_text())
server_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AppServer')
server_class.body = [n for n in server_class.body if isinstance(n, ast.FunctionDef) and n.name == 'read']
exits = []
namespace = {'json': __import__('json'), 'log': lambda *a: None,
             'os': type('os', (), {'_exit': staticmethod(lambda code: exits.append(code))})}
exec(compile(ast.Module(body=[server_class], type_ignores=[]), str(source), 'exec'), namespace)
AppServer = namespace['AppServer']


def server(retired):
    s = AppServer()
    s.proc = Mock(stdout=iter(['{"jsonrpc": "2.0", "method": "turn/started", "params": {}}\n']))
    s.pending = {}
    s.on_notification = Mock()
    s.on_request = Mock()
    s.retired = retired
    return s


class AppServerExitTests(unittest.TestCase):
    def setUp(self):
        exits.clear()

    # covers: agent.sign-in/E4
    def test_replaced_on_purpose_keeps_the_service(self):
        s = server(retired=True)
        s.read()
        s.on_notification.assert_called_once()
        self.assertEqual(exits, [])

    # covers: agent.sign-in/E4
    def test_died_on_its_own_takes_the_service_down(self):
        server(retired=False).read()
        self.assertEqual(exits, [1])

    # covers: agent.sign-in/E4
    def test_restart_server_retires_the_old_one_first(self):
        text = source.read_text()
        body = text[text.index('    def restart_server(self):'):text.index('    def needs_setup(self')]
        self.assertLess(body.index('old.retired = True'), body.index('old.proc.terminate()'))


if __name__ == '__main__':
    unittest.main()
