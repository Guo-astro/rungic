#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""An agent workspace outlives the user's interface (docs/research/97): rungic-workspace@.service is
not part of the user's graphical session, so Plasma restarting (the Rungic app installed, a crash)
does not stop it. systemd stops a unit with another only through these dependencies; the system
test workspace_headless shows the workspace going on when the user's KWin goes away."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / 'agent/workspace/rungic-workspace@.service'
# The dependencies by which systemd stops or restarts a unit with another (systemd.unit(5)).
STOPPED_WITH = ('PartOf', 'BindsTo', 'Requires', 'Requisite', 'Upholds', 'StopPropagatedFrom', 'Conflicts')
SESSION = ('plasma', 'graphical-session', 'kwin', 'rungic-voice-agent', 'rungic-voice-overlay', 'xdg-desktop')


def unit(path):
    """{section: [(key, value)]} of a unit file (keys may repeat)."""
    sections, current = {}, None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('['):
            current = sections.setdefault(line.strip('[]'), [])
        else:
            key, _, value = line.partition('=')
            current.append((key.strip(), value.strip()))
    return sections


class WorkspaceUnitTest(unittest.TestCase):
    # covers: agent.workspaces/E7
    def test_not_stopped_with_the_users_session(self):
        sections = unit(UNIT)
        for section in sections.values():
            for key, value in section:
                if key in STOPPED_WITH:
                    self.assertFalse(any(name in value for name in SESSION),
                                     f'{key}={value}: the user interface restarting would stop the workspace')
                self.assertNotEqual(key, 'StopWhenUnneeded')
        # Not pulled in (and so not taken down) by the graphical session: started by the agent's tools.
        self.assertNotIn('Install', sections)
        self.assertEqual(dict(sections['Service']).get('Restart'), 'on-failure')

    # covers: agent.workspaces/E7
    def test_runs_without_the_android_host_by_default(self):
        """Headless by default: the workspace does not need the Android host, which goes away when the
        Rungic app is installed or frozen (KWin's virtual backend unless RUNGIC_WORKSPACE_BACKEND says)."""
        script = (ROOT / 'agent/workspace/rungic-workspace').read_text()
        self.assertIn('backend=${RUNGIC_WORKSPACE_BACKEND:-virtual}', script)
        self.assertNotIn('RUNGIC_WORKSPACE_BACKEND', dict(unit(UNIT)['Service']).get('Environment', ''))


if __name__ == '__main__':
    unittest.main()
