#!/usr/bin/env python3
"""plasma/rebrand-user.py (docs/70) in a temporary home: up renames, down gives it back."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent.parent / 'plasma/rebrand-user.py'


def load(home):
    with patch.dict(os.environ, {'HOME': str(home)}, clear=False):
        os.environ.pop('XDG_CONFIG_HOME', None)
        spec = importlib.util.spec_from_file_location('rebrand_user', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        with patch('pathlib.Path.home', return_value=home):
            spec.loader.exec_module(module)
    return module


KWINRC = '[Wayland]\nInputMethod=/usr/share/applications/moto-plasma-rime.desktop\n'
PLACES = '<bookmark href="file:///home/linux/Shared/Pictures"/>\n'
MOBILERC = '[QuickSettings]\nenabledQuickSettings=org.kde.plasma.quicksetting.bluetooth,dev.moto.quicksetting.cast,' \
           'dev.moto.quicksetting.agentscreen\n'
CODEX = '[mcp_servers.moto-desktop]\ncommand = "/usr/bin/moto-cua"\nargs = ["mcp"]\n'
UPDATERC = '[moto.upd]\nctime=1\ndone=moto-native-display-v1,moto-quicksettings-v1\n\n' \
           '[moto-voice-agent.upd]\ndone=moto-codex-v1\n'


class RebrandUser(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        c = self.home / '.config'
        (c / 'moto-voice-agent').mkdir(parents=True)
        (c / 'moto-voice-agent/openai-api-key').write_text('sk-test')
        (c / 'kwinrc').write_text(KWINRC)
        (c / 'plasmamobilerc').write_text(MOBILERC)
        (c / 'kconf_updaterc').write_text(UPDATERC)
        (self.home / '.local/share').mkdir(parents=True)
        (self.home / '.local/share/user-places.xbel').write_text(PLACES)
        (self.home / '.codex/skills').mkdir(parents=True)
        (self.home / '.codex/config.toml').write_text(CODEX)
        (self.home / '.codex/skills/moto-phone-desktop').symlink_to(
            '/usr/share/moto-voice-agent/skills/moto-phone-desktop')
        self.m = load(self.home)

    def test_up_renames_and_runs_once(self):
        report = self.m.up()
        c = self.home / '.config'
        self.assertIn('rungic-plasma-rime.desktop', (c / 'kwinrc').read_text())
        self.assertIn('file:///home/rungic/Shared/Pictures',
                      (self.home / '.local/share/user-places.xbel').read_text())
        self.assertIn('com.rungic.quicksetting.cast,com.rungic.quicksetting.agentscreen',
                      (c / 'plasmamobilerc').read_text())
        self.assertEqual((c / 'rungic-voice-agent/openai-api-key').read_text(), 'sk-test')
        self.assertTrue((c / 'moto-voice-agent').exists())          # kept for a rollback
        codex = (self.home / '.codex/config.toml').read_text()
        self.assertIn('[mcp_servers.rungic-desktop]', codex)
        self.assertIn('/usr/bin/rungic-cua', codex)
        skills = self.home / '.codex/skills'
        self.assertEqual(os.readlink(skills / 'rungic-phone-desktop'),
                         '/usr/share/rungic-voice-agent/skills/rungic-phone-desktop')
        self.assertFalse((skills / 'moto-phone-desktop').is_symlink())
        updaterc = (c / 'kconf_updaterc').read_text()
        self.assertIn('[rungic.upd]\ndone=rungic-native-display-v1,rungic-quicksettings-v1', updaterc)
        self.assertIn('[rungic-voice-agent.upd]\ndone=rungic-codex-v1', updaterc)
        self.assertEqual(sorted(report['records']), ['rungic-voice-agent.upd', 'rungic.upd'])
        self.assertEqual(self.m.up(), {'done': 'already'})

    def test_down_gives_back_what_up_took(self):
        self.m.up()
        c = self.home / '.config'
        (c / 'rungic-voice-agent/openai-api-key').write_text('sk-changed-after-up')
        self.m.down()
        self.assertEqual((c / 'kwinrc').read_text(), KWINRC)
        self.assertEqual((c / 'plasmamobilerc').read_text(), MOBILERC)
        self.assertEqual((self.home / '.local/share/user-places.xbel').read_text(), PLACES)
        self.assertEqual((self.home / '.codex/config.toml').read_text(), CODEX)
        self.assertEqual((c / 'moto-voice-agent/openai-api-key').read_text(), 'sk-changed-after-up')
        self.assertFalse((c / 'rungic-voice-agent').exists())
        skills = self.home / '.codex/skills'
        self.assertEqual(os.readlink(skills / 'moto-phone-desktop'),
                         '/usr/share/moto-voice-agent/skills/moto-phone-desktop')
        self.assertFalse((skills / 'rungic-phone-desktop').is_symlink())
        self.assertFalse(self.m.MARKER.exists())
        # up again after a rollback: the records are there already, the rest renames again
        self.m.up()
        self.assertEqual((c / 'rungic-voice-agent/openai-api-key').read_text(), 'sk-changed-after-up')
        self.assertEqual((c / 'kconf_updaterc').read_text().count('[rungic.upd]'), 1)


if __name__ == '__main__':
    unittest.main()
