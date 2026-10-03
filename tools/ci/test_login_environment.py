#!/usr/bin/env python3
"""The desktop's login environment (desktop/login-environment.py, docs/100): the session gets the
PATH a display manager's login shell would give it, with ~/.local/bin on it before an installer
creates it, and the user's own ~/.profile exports, but never the session's own variables; a
broken or hanging profile leaves the session as it was."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'desktop/login-environment.py'
spec = importlib.util.spec_from_file_location('login_environment', SCRIPT)
login_environment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(login_environment)


class LoginEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin', 'QT_QPA_PLATFORM': 'wayland', 'LANG': 'C.UTF-8'}

    def profile(self, text):
        (self.home / '.profile').write_text(text)

    def run_it(self, shell='/bin/sh'):
        return login_environment.login_environment(self.env, shell)

    # covers: install.login-environment/E1
    def test_user_bins_before_they_exist(self):
        path = self.run_it()['PATH'].split(':')
        self.assertFalse((self.home / '.local/bin').exists())
        self.assertEqual(path[0], str(self.home / '.local/bin'))
        self.assertEqual(path[1], str(self.home / 'bin'))
        self.assertIn('/usr/bin', path)

    # covers: install.login-environment/E2
    def test_profile_path_and_exports(self):
        self.profile('export PATH="$HOME/tools:$PATH"\nexport EDITOR=vim\nexport QT_QPA_PLATFORM=xcb\n')
        values = self.run_it()
        self.assertIn(str(self.home / 'tools'), values['PATH'].split(':'))
        self.assertEqual(values['EDITOR'], 'vim')
        self.assertNotIn('QT_QPA_PLATFORM', values)          # the session's own
        self.assertEqual(values['PATH'].split(':').count(str(self.home / '.local/bin')), 1)

    # covers: install.login-environment/E1
    def test_bash_login_shell_reads_profile(self):
        if not os.access('/bin/bash', os.X_OK):
            self.skipTest('no bash')
        self.profile('export FROM_PROFILE=1\n')
        self.assertEqual(self.run_it('/bin/bash').get('FROM_PROFILE'), '1')

    # covers: install.login-environment/E3
    def test_broken_profile_keeps_the_session(self):
        self.profile('exit 3\n')
        values = self.run_it()
        self.assertTrue(values['PATH'].startswith(str(self.home / '.local/bin')))
        self.assertEqual(set(values), {'PATH'})

    # covers: install.login-environment/E3
    def test_hanging_profile_is_cut_short(self):
        self.profile('sleep 30\n')
        with patch.object(login_environment, 'TIMEOUT_S', 1):
            values = self.run_it()
        self.assertIn('/usr/bin', values['PATH'].split(':'))
        self.assertEqual(set(values), {'PATH'})

    # covers: install.login-environment/E1 install.login-environment/E2
    def test_output_evaluates_in_the_session_shell(self):
        self.profile("export GREETING='hello world'\n")
        env = {**self.env, 'SHELL': '/bin/sh'}
        out = subprocess.run(['sh', '-c', f'eval "$(python3 {SCRIPT})"; printf "%s|%s|%s" "$PATH" "$GREETING" "$RUNGIC_LOGIN_VARS"'],
                             env=env, capture_output=True, text=True, check=True).stdout
        path, greeting, names = out.split('|')
        self.assertTrue(path.startswith(str(self.home / '.local/bin')))
        self.assertEqual(greeting, 'hello world')
        self.assertIn('PATH', names.split())

    # covers: install.login-environment/E1
    def test_session_uses_it(self):
        session = (ROOT / 'desktop/session').read_text()
        self.assertIn('/usr/libexec/rungic-login-environment', session)
        self.assertIn('"HOME","PATH"', session)             # into rungic-session.env
        self.assertIn('PATH $RUNGIC_LOGIN_VARS', session)     # into the user manager
        build = (ROOT / 'packaging/rungic-plasma-session/build.sh').read_text()
        self.assertIn('desktop/login-environment.py" "$DESTDIR/usr/libexec/rungic-login-environment"', build)


if __name__ == '__main__':
    unittest.main()
