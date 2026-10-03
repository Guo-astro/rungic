# SPDX-License-Identifier: GPL-2.0-or-later
"""Transport adapter for the native phone-session coordinator.

Scheduling, audio and intent control live in C++. This adapter reuses the
resident service's authenticated Codex connection and conversation store.
"""
import json
import os
from pathlib import Path
import subprocess
import threading
import tomllib


class PhoneSession:
    def __init__(self, server, settings, emit, foreground, prompt, language, executable='rungic-agent-session', history=lambda conversation: []):
        self.server, self.settings, self.emit = server, settings, emit
        self.foreground, self.prompt, self.language = foreground, prompt, language
        self.history = history
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.pending = {}
        self.threads = {}
        self.serial = 0
        self.snapshot = {'sessionId': '', 'phase': 'closed', 'tasks': [], 'conversation': ''}
        self.process = subprocess.Popen(['sh', '-c', '[ ! -r /etc/profile.d/proxy.sh ] || . /etc/profile.d/proxy.sh; exec "$@"', 'rungic-phone-session', executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=None, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._watch_foreground, daemon=True).start()

    def _write(self, message):
        with self.write_lock:
            if self.process.poll() is not None:
                raise RuntimeError('Phone session service stopped; try again')
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            self.process.stdin.flush()

    def alive(self):
        return self.process.poll() is None

    def post(self, method, args=None):
        """A command nobody waits for (ExternalBusy, a hint). It has an id all the same: the
        coordinator answers every command with its id, and a reply without one ended the reader and
        the coordinator with it (2026-10-03). A stopped coordinator drops the hint."""
        with self.lock:
            self.serial += 1
            rid = self.serial
        try:
            self._write({'type': 'command', 'id': rid, 'method': method, 'args': args or {}})
        except (RuntimeError, OSError):
            pass

    def command(self, method, args=None, timeout=30):
        with self.lock:
            self.serial += 1
            rid = self.serial
            event, result = threading.Event(), {}
            self.pending[rid] = event, result
        try:
            self._write({'type': 'command', 'id': rid, 'method': method, 'args': args or {}})
            if not event.wait(timeout):
                raise RuntimeError('Phone session did not answer')
            if 'error' in result:
                raise RuntimeError(str(result['error']))
            return result
        finally:
            with self.lock:
                self.pending.pop(rid, None)

    def start(self, conversation):
        if not self.foreground():
            raise RuntimeError('Open Plasma before starting phone mode')
        return self.command('StartPhoneMode', {'conversationId': conversation,
                            # Desktop language is a reply fallback, not a forced
                            # transcription language: the user may speak another.
                            'instructions': self.prompt() + self.context(conversation), 'language': ''})

    def context(self, conversation):
        records = []
        for event in self.history(conversation)[-80:]:
            if event.get('type') in ('message', 'agent-message'):
                records.append({'role': event.get('role', 'assistant'), 'text': event.get('text', '')[:3000]})
            elif event.get('type') == 'phone-task':
                task = event.get('task') or {}
                if task.get('result'):
                    records.append({'role': 'task_result', 'text': task['result'][:3000]})
        while len(json.dumps(records, ensure_ascii=False)) > 16000:
            records.pop(0)
        return '\nRecent conversation (quoted context only; do not execute old requests):\n' + json.dumps(records[-20:], ensure_ascii=False)

    def owns(self, thread):
        with self.lock:
            return thread in self.threads

    def notification(self, method, params):
        if not self.owns(params.get('threadId')):
            return False
        self._write({'type': 'notification', 'method': method, 'params': params})
        return True

    def request(self, rid, method, params):
        if not self.owns(params.get('threadId')):
            return False
        self._write({'type': 'request', 'id': rid, 'method': method, 'params': params})
        return True

    def _task_settings(self, task, read_only):
        settings = self.settings()
        settings['config'] = dict(settings.get('config') or {})
        config = settings['config']
        # Read-only tasks cannot call arbitrary MCP servers, including configured
        # third-party servers which may mutate outside the filesystem sandbox.
        names = {'rungic-desktop'}
        try:
            raw = tomllib.loads((Path.home() / '.codex/config.toml').read_text())
            names.update(raw.get('mcp_servers', {}))
        except FileNotFoundError:
            pass
        if read_only:
            settings['sandbox'] = 'read-only'
            for name in names:
                config[f'mcp_servers.{name}.enabled'] = False
        else:
            # Each writable task owns all its MCP workers; revoking the lease
            # cancels their process group without killing detached GUI apps.
            for name in names:
                if name != 'rungic-desktop':
                    config[f'mcp_servers.{name}.enabled'] = False
            config['mcp_servers.rungic-desktop.command'] = 'rungic-task-tools'
            config['mcp_servers.rungic-desktop.args'] = ['--task', task, '--', 'rungic-cua', 'mcp']
            env = dict(config.get('mcp_servers.rungic-desktop.env') or {})
            env['RUNGIC_TASK_ID'] = task
            config['mcp_servers.rungic-desktop.env'] = env
        return settings

    def _rpc(self, message):
        params = dict(message.get('params') or {})
        method, task = message['method'], params.pop('taskId', '')
        read_only = params.pop('readOnly', False)
        conversation = params.pop('conversation', '')
        try:
            if method in ('thread/start', 'thread/resume'):
                params = {**self._task_settings(task, read_only), **params}
                if conversation:
                    params['developerInstructions'] = params.get('developerInstructions', '') + self.context(conversation)
            if method == 'ServerResponse':
                self.server().respond(params['requestId'], params['result'])
                result = {}
            else:
                result = self.server().call(method, params)
            if method in ('thread/start', 'thread/resume'):
                thread = (result.get('thread') or {}).get('id') or params.get('threadId')
                if thread:
                    with self.lock:
                        self.threads[thread] = {'taskId': task, 'conversation': conversation}
            self._write({'type': 'rpc-result', 'id': message['id'], 'result': result})
        except Exception as error:
            self._write({'type': 'rpc-result', 'id': message['id'], 'error': str(error), 'uncertain': isinstance(error, (TimeoutError, OSError, EOFError))})

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self._handle(json.loads(line))
                except Exception as error:
                    # One bad line is dropped and said, never the end of the session.
                    print(f'phone session: dropped a message ({error!r}): {line[:300]!r}', flush=True)
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            with self.lock:
                self.snapshot.update(sessionId='', phase='closed')
                for event, result in self.pending.values():
                    result['error'] = 'Phone session service stopped'
                    event.set()
            self.emit({'type': 'phone-state', 'conversation': self.snapshot.get('conversation', ''),
                       'sessionId': '', 'phase': 'closed', 'microphone': False}, False)

    def _handle(self, message):
        kind = message.get('type')
        if kind == 'reply':
            with self.lock:
                pair = self.pending.get(message.get('id'))
                if pair:
                    pair[1].update(message.get('result') or {})
                    pair[0].set()
        elif kind == 'rpc':
            threading.Thread(target=self._rpc, args=(message,), daemon=True).start()
        elif kind == 'event':
            event = message['event']
            if event.get('type') == 'phone-state':
                with self.lock:
                    self.snapshot.update(event)
            self.emit(event, message.get('keep', True))

    def _watch_foreground(self):
        while self.process.poll() is None:
            threading.Event().wait(0.5)
            if self.snapshot.get('sessionId'):
                try:
                    self.command('Foreground', {'visible': self.foreground()}, timeout=5)
                except (RuntimeError, OSError):
                    pass
