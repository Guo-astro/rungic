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


# covers: agent.phone-mode/E2
def test_read_tasks_disable_all_configured_mcp(tmp_path, monkeypatch):
    (tmp_path / '.codex').mkdir()
    (tmp_path / '.codex/config.toml').write_text('[mcp_servers.writes]\ncommand="unsafe"\n')
    monkeypatch.setattr(module.Path, 'home', lambda: tmp_path)
    settings = bridge()._task_settings('task1', True)
    assert settings['sandbox'] == 'read-only'
    assert settings['config']['mcp_servers.writes.enabled'] is False
    assert settings['config']['mcp_servers.rungic-desktop.enabled'] is False


# covers: agent.phone-mode/E2
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


# covers: agent.phone-mode/E7
def test_notifications_stay_scoped():
    obj = bridge()
    obj.threads['native-thread'] = {'conversation': 'origin'}
    messages = []
    obj._write = messages.append
    assert not obj.notification('turn/completed', {'threadId': 'selected-chat'})
    assert obj.notification('turn/completed', {'threadId': 'native-thread'})
    assert len(messages) == 1


# covers: agent.phone-mode/E11
def test_desktop_language_does_not_force_spoken_language():
    obj = bridge()
    obj.foreground = lambda: True
    obj.prompt = lambda: 'Speak the user\'s language'
    obj.language = lambda: 'en'
    obj.command = lambda method, args: args
    assert obj.start('origin')['language'] == ''


class Process:
    """The coordinator's side of the pipe: the lines it printed, then gone."""
    def __init__(self, lines):
        self.stdout = iter(lines)
        self.terminated = False
    def poll(self):
        return 0 if self.terminated else None
    def terminate(self):
        self.terminated = True
    def wait(self, timeout=None):
        return 0


def reader(lines):
    obj = bridge()
    obj.process = Process(lines)
    obj.pending = {}
    obj.snapshot = {'sessionId': 's', 'phase': 'live', 'conversation': 'c'}
    obj.events = []
    obj.emit = lambda event, keep=True: obj.events.append(event)
    return obj


# covers: agent.phone-mode/E1
def test_a_reply_without_an_id_is_dropped_not_the_end():
    # ExternalBusy was written without an id; its reply had none and the reader's KeyError took
    # the coordinator down with it (2026-10-03).
    import json
    event, result = threading.Event(), {}
    obj = reader([json.dumps({'type': 'reply', 'result': {'ok': True}}) + '\n',
                  'not json\n',
                  json.dumps({'type': 'reply', 'id': 7, 'result': {'sessionId': 'x'}}) + '\n',
                  json.dumps({'type': 'event', 'event': {'type': 'phone-notice', 'text': 'still here'}}) + '\n'])
    obj.pending[7] = event, result
    obj._read()
    # Answered by the reply after the bad lines (the coordinator stopping at the end marks what is
    # left pending, which command() would have taken already).
    assert event.is_set() and result['sessionId'] == 'x'
    assert {'type': 'phone-notice', 'text': 'still here'} in obj.events


# covers: agent.phone-mode/E1
def test_post_gives_every_command_an_id():
    obj = bridge()
    obj.serial = 0
    written = []
    obj._write = written.append
    obj.post('ExternalBusy', {'busy': True})
    obj.post('ExternalBusy', {'busy': False})
    assert [m['id'] for m in written] == [1, 2]
    assert all(m['type'] == 'command' and m['method'] == 'ExternalBusy' for m in written)


# covers: agent.phone-mode/E1
def test_post_to_a_stopped_coordinator_is_dropped():
    obj = bridge()
    obj.serial = 0
    def stopped(message):
        raise RuntimeError('Phone session service stopped; try again')
    obj._write = stopped
    obj.post('ExternalBusy', {'busy': True})   # a hint: no exception into the agent's turn handling


# covers: agent.phone-mode/E1
def test_the_agent_writes_no_command_without_an_id():
    # Every command to the coordinator goes through command() or post(), which number it.
    source = (MODULE.parent / 'rungic_voice_agent.py').read_text()
    assert 'phone._write(' not in source
