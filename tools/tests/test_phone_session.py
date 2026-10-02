# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline: inspect native transport settings without a phone, key or server."""
import importlib.util
from pathlib import Path
import threading

MODULE = Path(__file__).resolve().parents[2] / 'agent/assistant/phone_session.py'
spec = importlib.util.spec_from_file_location('phone_session', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def bridge(settings=None):
    obj = module.PhoneSession.__new__(module.PhoneSession)
    obj.settings = lambda: settings or {'sandbox': 'danger-full-access', 'config': {
        'mcp_servers.rungic-desktop.env': {'WAYLAND_DISPLAY': 'agent-0'}}}
    obj.lock = threading.RLock()
    obj.threads = {}
    obj.history = lambda conversation: []
    return obj


def test_read_tasks_disable_all_configured_mcp(tmp_path, monkeypatch):
    (tmp_path / '.codex').mkdir()
    (tmp_path / '.codex/config.toml').write_text('[mcp_servers.writes]\ncommand="unsafe"\n')
    monkeypatch.setattr(module.Path, 'home', lambda: tmp_path)
    settings = bridge()._task_settings('task1', True)
    assert settings['sandbox'] == 'read-only'
    assert settings['config']['mcp_servers.writes.enabled'] is False
    assert settings['config']['mcp_servers.rungic-desktop.enabled'] is False


def test_exclusive_tools_are_task_owned(tmp_path, monkeypatch):
    monkeypatch.setattr(module.Path, 'home', lambda: tmp_path)
    obj = bridge()
    config = obj._task_settings('task1', False)['config']
    assert config['mcp_servers.rungic-desktop.command'] == 'rungic-task-tools'
    assert config['mcp_servers.rungic-desktop.args'] == ['--task', 'task1', '--', 'rungic-cua', 'mcp']
    assert config['mcp_servers.rungic-desktop.env']['RUNGIC_TASK_ID'] == 'task1'
    assert config['mcp_servers.rungic-desktop.env']['WAYLAND_DISPLAY'] == 'agent-0'
    assert 'RUNGIC_TASK_ID' not in obj.settings()['config']['mcp_servers.rungic-desktop.env']


def test_rpc_strips_private_fields_and_registers_thread_before_reply(tmp_path, monkeypatch):
    monkeypatch.setattr(module.Path, 'home', lambda: tmp_path)
    calls, replies = [], []
    class Server:
        def call(self, method, params):
            calls.append((method, params))
            return {'thread': {'id': 'codex-thread'}}
    obj = bridge()
    obj.server = lambda: Server()
    def reply(message):
        assert obj.owns('codex-thread')
        replies.append(message)
    obj._write = reply
    obj._rpc({'id': 1, 'method': 'thread/start', 'params': {'taskId': 'task1', 'readOnly': True, 'conversation': 'origin'}})
    assert not {'taskId', 'readOnly', 'conversation'} & calls[0][1].keys()
    assert obj.threads['codex-thread']['conversation'] == 'origin'
    assert replies[0]['result']['thread']['id'] == 'codex-thread'


def test_notifications_stay_scoped():
    obj = bridge()
    obj.threads['native-thread'] = {'conversation': 'origin'}
    messages = []
    obj._write = messages.append
    assert not obj.notification('turn/completed', {'threadId': 'selected-chat'})
    assert obj.notification('turn/completed', {'threadId': 'native-thread'})
    assert len(messages) == 1


def test_desktop_language_does_not_force_spoken_language():
    obj = bridge()
    obj.foreground = lambda: True
    obj.prompt = lambda: 'Speak the user\'s language'
    obj.language = lambda: 'en'
    obj.command = lambda method, args: args
    assert obj.start('origin')['language'] == ''
