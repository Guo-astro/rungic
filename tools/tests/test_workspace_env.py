#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""An agent workspace's environment (docs/research/91, docs/103): set up as Plasma's desktop session
is, whoever calls. No forced QT_QPA_PLATFORMTHEME (it reached programs' temporary applications and
left their session bus deaf), in-process file dialogs, KDE_FULL_SESSION; the user's session's values
go along as RUNGIC_USER_* and come back in rungic-user. rungic-workspace-env and the voice agent's
workspace_env() (what Codex threads and their desktop tools get) set the same."""
from pathlib import Path
import ast
import os
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / 'agent/workspace/rungic-workspace-env'
USER = ROOT / 'agent/workspace/rungic-user'
AGENT = ROOT / 'agent/assistant/rungic_voice_agent.py'
# The user's session on the phone: Plasma Mobile's portal dialogs; its theme as it was before docs/103.
SESSION = {'PATH': '/usr/bin:/bin', 'WAYLAND_DISPLAY': 'wayland-0', 'QT_QPA_PLATFORMTHEME': 'KDE',
           'PLASMA_INTEGRATION_USE_PORTAL': '1', 'KDE_FULL_SESSION': 'true'}
DESKTOP = {'PLASMA_INTEGRATION_USE_PORTAL': '0', 'KDE_FULL_SESSION': 'true', 'KDE_SESSION_VERSION': '6',
           'XDG_CURRENT_DESKTOP': 'KDE', 'QT_QPA_PLATFORM': 'wayland', 'XDG_SESSION_TYPE': 'wayland'}


def parse(text):
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


class WorkspaceEnv(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.runtime = base / 'run'
        self.state = base / 'state'
        (self.state / 'rungic-workspaces/1').mkdir(parents=True)
        (self.state / 'rungic-workspaces/1/bus').write_text('unix:path=/run/user/1000/rungic-workspace-1.bus\n')
        self.runtime.mkdir()
        self.sock = socket.socket(socket.AF_UNIX)         # the workspace's Wayland socket: it is running
        self.sock.bind(str(self.runtime / 'wayland-ws-1'))
        self.addCleanup(self.sock.close)

    def run_env(self, extra=None, *command):
        env = {**SESSION, 'XDG_RUNTIME_DIR': str(self.runtime), 'XDG_STATE_HOME': str(self.state), **(extra or {})}
        result = subprocess.run(['sh', str(ENV), '1', *(command or ('env',))], env=env, capture_output=True,
                                text=True, check=True)
        return parse(result.stdout)

    # covers: agent.workspaces/E5
    def test_a_desktop_session(self):
        env = self.run_env()
        self.assertNotIn('QT_QPA_PLATFORMTHEME', env)
        for name, value in DESKTOP.items():
            self.assertEqual(env.get(name), value, name)
        self.assertEqual(env['WAYLAND_DISPLAY'], 'wayland-ws-1')
        self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'], 'unix:path=/run/user/1000/rungic-workspace-1.bus')

    # covers: agent.workspaces/E5
    def test_the_users_values_go_along(self):
        env = self.run_env()
        self.assertEqual(env['RUNGIC_USER_QT_QPA_PLATFORMTHEME'], 'KDE')
        self.assertEqual(env['RUNGIC_USER_PLASMA_INTEGRATION_USE_PORTAL'], '1')
        self.assertEqual(env['RUNGIC_USER_WAYLAND_DISPLAY'], 'wayland-0')

    # covers: agent.workspaces/E5
    def test_from_inside_a_workspace_they_stay(self):
        inside = {'RUNGIC_WORKSPACE': '1', 'QT_QPA_PLATFORMTHEME': '', 'PLASMA_INTEGRATION_USE_PORTAL': '0',
                  'RUNGIC_USER_QT_QPA_PLATFORMTHEME': 'KDE', 'RUNGIC_USER_PLASMA_INTEGRATION_USE_PORTAL': '1'}
        env = self.run_env(inside)
        self.assertEqual(env['RUNGIC_USER_QT_QPA_PLATFORMTHEME'], 'KDE')
        self.assertEqual(env['RUNGIC_USER_PLASMA_INTEGRATION_USE_PORTAL'], '1')

    # covers: agent.workspaces/E5
    def test_back_in_the_users_session(self):
        env = self.run_env(None, 'sh', str(USER), 'env')
        self.assertEqual((env.get('QT_QPA_PLATFORMTHEME'), env.get('PLASMA_INTEGRATION_USE_PORTAL')), ('KDE', '1'))
        self.assertNotIn('RUNGIC_WORKSPACE', env)
        self.assertNotIn('RUNGIC_USER_QT_QPA_PLATFORMTHEME', env)
        self.assertNotIn('RUNGIC_USER_PLASMA_INTEGRATION_USE_PORTAL', env)
        # A user's session without them gets none back.
        env = self.run_env({'QT_QPA_PLATFORMTHEME': '', 'PLASMA_INTEGRATION_USE_PORTAL': ''}, 'sh', str(USER), 'env')
        self.assertNotIn('QT_QPA_PLATFORMTHEME', env)
        self.assertNotIn('PLASMA_INTEGRATION_USE_PORTAL', env)


class AgentWorkspaceEnv(unittest.TestCase):
    """The voice agent's workspace_env(): the same desktop for Codex threads and their desktop tools
    (Codex can only set variables: QT_QPA_PLATFORMTHEME is empty, which Qt takes as unset)."""

    def workspace_env(self, temp):
        tree = ast.parse(AGENT.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'workspace_env')
        root = Path(temp)
        (root / 'mnt/android-wayland').mkdir(parents=True)
        (root / 'mnt/android-wayland/ws-1').touch()
        (root / 'state/rungic-workspaces/1').mkdir(parents=True)
        (root / 'state/rungic-workspaces/1/bus').write_text('unix:path=/run/user/1000/rungic-workspace-1.bus\n')
        (root / 'run').mkdir()
        (root / 'run/wayland-ws-1').touch()

        def rooted(path, *rest):            # /mnt/... in the temporary tree
            path = str(path)
            return Path(str(root) + path, *rest) if path.startswith('/mnt/') else Path(path, *rest)
        namespace = {'Path': rooted, 'os': os, 'time': __import__('time'), 'subprocess': subprocess,
                     'log': lambda *a: None, 'WORKSPACE': 1}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(AGENT), 'exec'), namespace)
        saved = dict(os.environ)
        os.environ.update({**SESSION, 'XDG_STATE_HOME': str(root / 'state'), 'XDG_RUNTIME_DIR': str(root / 'run'),
                           'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus'})
        try:
            return namespace['workspace_env'](1)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    # covers: agent.workspaces/E5
    def test_same_desktop_as_the_script(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self.workspace_env(temp)
        for name, value in DESKTOP.items():
            self.assertEqual(env.get(name), value, name)
        self.assertEqual(env['QT_QPA_PLATFORMTHEME'], '')
        self.assertEqual(env['RUNGIC_USER_QT_QPA_PLATFORMTHEME'], 'KDE')
        self.assertEqual(env['RUNGIC_USER_PLASMA_INTEGRATION_USE_PORTAL'], '1')


if __name__ == '__main__':
    unittest.main()
