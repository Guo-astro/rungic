"""Where the agent works (docs/research/91): the user's desktop or its own workspace.

The screens beside the phone's own are two: desktop mode (the user's desktop gets a second output,
shown in a floating window or on the TV: casting is desktop mode on the TV) and the assistant's
screen (the agent's own workspace, a KWin of its own). The agent works:

- on the user's desktop while desktop mode is on or a TV shows the desktop: the user is at that
  screen and wants the work there;
- else in its own workspace;
- or where the user says (`desktop_where`), for the rest of the conversation.

The voice agent starts this MCP server in the workspace's environment, with the user's session
as RUNGIC_USER_*. It serves the tools itself but acts through two children, `rungic-cua mcp` in
each session, started when first needed: each keeps all the logic of its session (windows,
input, screenshots, switching apps over), and nothing here touches a desktop.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
from itertools import count

logger = logging.getLogger('rungic-cua.router')

PLATFORM = '/mnt/android-wayland/platform.sock'
WHERE_TOOL = {
    'name': 'desktop_where',
    'description': ("Where your desktop tools work. 'desktop': the user's desktop screen (desktop mode's floating "
                    "window or the TV; the user watches and may use it too). 'workspace': your own workspace (the "
                    "assistant's screen), which the user's phone never shows by itself. 'auto' (the default): the "
                    "user's desktop while desktop mode is on or the TV shows the desktop, else your workspace. Set it "
                    "when the user says where to work (\"在我的桌面上\", \"在助理屏上\"); it holds for this "
                    "conversation. Without `target` it only says where you work now and why."),
    'inputSchema': {'type': 'object', 'properties': {
        'target': {'type': 'string', 'enum': ['auto', 'desktop', 'workspace']}}},
    'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False},
}
SESSION_NAMES = {'desktop': "the user's desktop", 'workspace': 'your workspace (the assistant\'s screen)'}


def bridge(request: dict, timeout: float = 3.0) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(PLATFORM)
        conn.sendall(json.dumps(request).encode() + b'\n')
        reply = b''
        while not reply.endswith(b'\n'):
            chunk = conn.recv(65536)
            if not chunk:
                break
            reply += chunk
    return json.loads(reply)


def desktop_in_use() -> tuple[bool, str]:
    """Whether the user has their desktop screen out: desktop mode on, or a TV showing it."""
    try:
        state = bridge({'op': 'desktop-mode'})
    except (OSError, ValueError) as error:
        return False, f'desktop mode unknown ({error})'
    if 'error' in state:
        return False, f"desktop mode unknown ({state['error']})"
    if state.get('tv'):
        return True, 'the TV shows the desktop'
    if state.get('enabled'):
        return True, 'desktop mode is on'
    return False, 'desktop mode is off and no TV shows the desktop'


def user_session_env(env: dict) -> dict:
    """The user's session, from the workspace's environment (RUNGIC_USER_*, else its usual one)."""
    env = dict(env)
    runtime = env.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
    env['WAYLAND_DISPLAY'] = env.get('RUNGIC_USER_WAYLAND_DISPLAY') or 'wayland-0'
    env['DBUS_SESSION_BUS_ADDRESS'] = env.get('RUNGIC_USER_DBUS_SESSION_BUS_ADDRESS') or f'unix:path={runtime}/bus'
    for name in ('RUNGIC_WORKSPACE', 'DISPLAY', 'XAUTHORITY'):
        env.pop(name, None)
    return env


class Child:
    """`rungic-cua mcp` in one session, spoken to over its stdio."""

    def __init__(self, env: dict) -> None:
        self.process = subprocess.Popen(['rungic-cua', 'mcp'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        env={**env, 'RUNGIC_CUA_CHILD': '1'}, text=True, bufsize=1)
        self.ids = count(1)
        self.lock = threading.Lock()
        self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                    'clientInfo': {'name': 'rungic-cua-router', 'version': '0.1.0'}})
        self._send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def alive(self) -> bool:
        return self.process.poll() is None

    def _send(self, message: dict) -> None:
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def request(self, method: str, params: dict) -> dict:
        with self.lock:
            rid = next(self.ids)
            self._send({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params})
            while True:
                line = self.process.stdout.readline()
                if not line:
                    raise RuntimeError('the desktop tools of that session stopped')
                message = json.loads(line)
                if message.get('id') == rid:
                    break
        if 'error' in message:
            raise RuntimeError(message['error'].get('message', 'error'))
        return message.get('result') or {}

    def close(self) -> None:
        try:
            self.process.stdin.close()
            self.process.wait(3)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()


class Router:
    def __init__(self, env: dict | None = None) -> None:
        self.env = dict(env or os.environ)
        self.override = 'auto'
        self.children: dict[str, Child] = {}
        self.last: str | None = None

    def where(self) -> tuple[str, str]:
        """(target, why)."""
        if self.override != 'auto':
            return self.override, 'the user said so'
        in_use, why = desktop_in_use()
        return ('desktop' if in_use else 'workspace'), why

    def child(self, target: str) -> Child:
        child = self.children.get(target)
        if child is None or not child.alive():
            env = self.env if target == 'workspace' else user_session_env(self.env)
            child = self.children[target] = Child(env)
        return child

    def call(self, name: str, arguments: dict) -> dict:
        """A tools/call result: from the child of the session the agent works in now."""
        if name == WHERE_TOOL['name']:
            if arguments.get('target'):
                self.override = str(arguments['target'])
            target, why = self.where()
            self.last = target
            data = {'where': target, 'screen': SESSION_NAMES[target], 'why': why, 'setting': self.override}
            return {'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}]}
        target, why = self.where()
        result = self.child(target).request('tools/call', {'name': name, 'arguments': arguments})
        if target != self.last:
            # The agent learns where it works whenever that changes.
            note = {'where': target, 'screen': SESSION_NAMES[target], 'why': why}
            result = {**result, 'content': [*result.get('content', []),
                                            {'type': 'text', 'text': json.dumps(note, ensure_ascii=False)}]}
            self.last = target
        return result

    def close(self) -> None:
        for child in self.children.values():
            child.close()
