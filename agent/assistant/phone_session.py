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

import task_state


class PhoneSession:
    def __init__(self, server, settings, emit, foreground, prompt, language, executable='rungic-agent-session', history=lambda conversation: []):
        self.server, self.settings, self.emit = server, settings, emit
        self.foreground, self.prompt, self.language = foreground, prompt, language
        self.history = history
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.pending = {}
        self.threads = {}
        # What each phone task is doing, kept as for a push-to-talk turn (task_state, docs/89): the
        # same plan, current activity and files, shown on the same task card.
        self.cards = {}
        self.card_timers = {}
        self.serial = 0
        self.snapshot = {'sessionId': '', 'phase': 'closed', 'tasks': [], 'conversation': ''}
        self.process = subprocess.Popen(['sh', '-c', '[ ! -r /etc/profile.d/proxy.sh ] || . /etc/profile.d/proxy.sh; exec "$@"', 'rungic-phone-session', executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=None, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

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
        self._track(method, params)
        self._write({'type': 'notification', 'method': method, 'params': params})
        return True

    def _track(self, method, params):
        """Codex's notifications of a phone task into its TurnState, as the push-to-talk turn does."""
        thread = params.get('threadId')
        with self.lock:
            info = self.threads.get(thread)
            if not info:
                return
            if method == 'turn/started' or thread not in self.cards:
                self.cards[thread] = task_state.TurnState()
            state = self.cards[thread]
            changed = False
            if method == 'turn/plan/updated':
                state.on_plan(params.get('plan') or [], params.get('explanation'))
                changed = True
            elif method in ('item/started', 'item/completed'):
                item = params.get('item') or {}
                completed = method.endswith('completed')
                changed = state.on_item(item, completed)
                if completed and item.get('type') == 'agentMessage' and item.get('phase') != 'final_answer' and item.get('text'):
                    state.on_commentary(item['text'])
                    changed = True
            elif method == 'item/commandExecution/outputDelta':
                changed = state.on_output(params.get('itemId', ''), params.get('delta', ''))
            elif method == 'item/fileChange/patchUpdated':
                changed = state.on_patch(params.get('itemId', ''), params.get('changes') or [])
            elif method == 'turn/completed':
                # The card as it ended stays with the task (plan, files, steps), as for a turn.
                final = state.snapshot()
                final.pop('current', None)
                timer = self.card_timers.pop(thread, None)
                if timer:
                    timer.cancel()
        if method == 'turn/completed':
            self.emit({'type': 'task', 'taskId': info.get('taskId', ''), 'conversation': info.get('conversation', ''), 'final': True, **final})
            return
        if changed:
            self._card_changed(thread)

    def _card_changed(self, thread):
        """Tell the app, a few times a second at most (as VoiceAgent.task_changed)."""
        with self.lock:
            if thread in self.card_timers:
                return
            timer = threading.Timer(0.4, self._flush_card, (thread,))
            timer.daemon = True
            self.card_timers[thread] = timer
        timer.start()

    def _flush_card(self, thread):
        with self.lock:
            self.card_timers.pop(thread, None)
            info, state = self.threads.get(thread), self.cards.get(thread)
            snapshot = state.snapshot() if state else None
            facts = state.facts() if state else ''
        if info and snapshot is not None:
            self.emit({'type': 'task', 'taskId': info.get('taskId', ''), 'conversation': info.get('conversation', ''), **snapshot}, False)
            # What the voice may say of it, as push-to-talk's voice is told (TurnState.facts).
            if info.get('taskId'):
                self.post('TaskFacts', {'taskId': info['taskId'], 'facts': facts})

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
                self._mark_call(bool(self.snapshot.get('sessionId')))
            self.emit(event, message.get('keep', True))

    def _mark_call(self, active):
        """While a call is open the phone stays awake (rungic-agent-wakelock): the call goes on with
        the screen locked, as a phone call does (2026-10-05). Plasma hidden no longer ends it; it
        ends when the user hangs up. The marker names the session's process, so a crashed session
        holds nothing."""
        path = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}') / 'rungic-call.busy'
        try:
            if active:
                if not path.exists():
                    path.write_text(json.dumps({'pid': getattr(self.process, 'pid', 0)}))
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass
