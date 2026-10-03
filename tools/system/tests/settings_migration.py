# SPDX-License-Identifier: MIT
"""The project's one-time user migrations (rungic.upd, docs/61) run by KDE's own kconf_update, as
desktop/session runs it before KWin: on a user who arranged their quick settings and still has the
old /usr/local input method, and on a new user with Plasma Mobile's default list. The migrations
change what they must, leave the user's own choices, and are recorded so that they run only once:
a later change by the user survives the next session start."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import harness

UPDATE = Path('/src/system/config/usr/share/kconf_update')
KCONF_UPDATE = '/usr/lib/aarch64-linux-gnu/libexec/kf6/kconf_update'
IDS = ['rungic-quicksettings-v1', 'rungic-firefox-launcher-v1', 'rungic-usr-paths-v1', 'rungic-recording-quicksetting-v1']
CAST, SCREEN = 'com.rungic.quicksetting.cast', 'com.rungic.quicksetting.agentscreen'
WIFI, BLUETOOTH = 'org.kde.plasma.quicksetting.wifi', 'org.kde.plasma.quicksetting.bluetooth'
OLD_RECORD, NEW_RECORD = 'org.kde.plasma.quicksetting.record', 'com.rungic.quicksetting.record'
OLD_IM = '/usr/local/share/applications/moto-plasma-rime.desktop'
NEW_IM = '/usr/share/applications/rungic-plasma-rime.desktop'


def env(home):
    return {**os.environ, 'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
            'XDG_DATA_HOME': str(home / '.local/share'), 'QT_QPA_PLATFORM': 'offscreen'}


def new_home():
    """A user whose data directory holds rungic.upd and its scripts, as /usr/share does on the phone."""
    home = Path(tempfile.mkdtemp(prefix='home-', dir='/tmp'))
    (home / '.config').mkdir()
    shutil.copytree(UPDATE, home / '.local/share/kconf_update')
    return home


def kconf_update(home):
    # As desktop/session runs it: offscreen, before any compositor.
    subprocess.run([KCONF_UPDATE], env=env(home), capture_output=True, timeout=120)


def read(home, file, group, key):
    return subprocess.run(['kreadconfig6', '--file', file, '--group', group, '--key', key], env=env(home),
                          capture_output=True, text=True, check=True).stdout.strip()


def write(home, file, group, key, value):
    subprocess.run(['kwriteconfig6', '--file', file, '--group', group, '--key', key, value], env=env(home), check=True)


# covers[system]: desktop.settings-migration/E1 desktop.settings-migration/E2 desktop.settings-migration/E3
# covers[system]: desktop.settings-migration/E4
def test():
    steps = []

    def check(condition, what):
        steps.append(what)
        if not condition:
            raise harness.Failed(f'{what}: not so')

    def tiles(home, key='enabledQuickSettings'):
        value = read(home, 'plasmamobilerc', 'QuickSettings', key)
        return value.split(',') if value else []

    # A user who arranged the quick settings and set the input method before the move to /usr.
    user = new_home()
    write(user, 'plasmamobilerc', 'QuickSettings', 'enabledQuickSettings', ','.join([WIFI, BLUETOOTH, OLD_RECORD]))
    write(user, 'kwinrc', 'Wayland', 'InputMethod', OLD_IM)
    write(user, 'kwinrc', 'Wayland', 'VirtualKeyboardEnabled', 'true')
    kconf_update(user)
    check(tiles(user) == [WIFI, BLUETOOTH, CAST, SCREEN, NEW_RECORD],
          'cast after Bluetooth, the assistant screen after cast, the recording tile in the old one\'s place')
    check(tiles(user, 'disabledQuickSettings') == [OLD_RECORD], "Plasma Mobile's recording tile goes to the disabled list")
    check(read(user, 'kwinrc', 'Wayland', 'InputMethod') == NEW_IM, 'the input method names the packaged Rime keyboard')
    check(read(user, 'kwinrc', 'Wayland', 'VirtualKeyboardEnabled') == 'true', 'the other settings stay')
    done = read(user, 'kconf_updaterc', 'rungic.upd', 'done').split(',')
    check(sorted(done) == sorted(IDS), 'kconf_update recorded every migration as done')

    # The user rearranges the tiles and picks the old keyboard path again: the next session start
    # runs kconf_update again, and the migrations, done once, do not run again.
    write(user, 'plasmamobilerc', 'QuickSettings', 'enabledQuickSettings', ','.join([CAST, WIFI]))
    write(user, 'plasmamobilerc', 'QuickSettings', 'disabledQuickSettings', '')
    write(user, 'kwinrc', 'Wayland', 'InputMethod', OLD_IM)
    kconf_update(user)
    check(tiles(user) == [CAST, WIFI] and tiles(user, 'disabledQuickSettings') == [],
          "a later arrangement is the user's: no migration runs twice")
    check(read(user, 'kwinrc', 'Wayland', 'InputMethod') == OLD_IM, 'nor does the path migration')

    # A user who disabled recording, with a list of their own, and one whose input method is another.
    other = new_home()
    write(other, 'plasmamobilerc', 'QuickSettings', 'enabledQuickSettings', ','.join([WIFI, BLUETOOTH]))
    write(other, 'plasmamobilerc', 'QuickSettings', 'disabledQuickSettings', OLD_RECORD)
    mine = '/usr/share/applications/org.kde.plasma.keyboard.desktop'
    write(other, 'kwinrc', 'Wayland', 'InputMethod', mine)
    kconf_update(other)
    check(tiles(other) == [WIFI, BLUETOOTH, CAST, SCREEN], 'the new recording tile is not enabled for one who disabled recording')
    check(tiles(other, 'disabledQuickSettings') == [OLD_RECORD, NEW_RECORD], 'it is disabled, as the old one was')
    check(read(other, 'kwinrc', 'Wayland', 'InputMethod') == mine, "an input method the user chose is not changed")

    # A new user: Plasma Mobile's default list, which places new tiles by itself.
    fresh = new_home()
    kconf_update(fresh)
    script = (UPDATE / 'rungic-recording-quicksetting.sh').read_text()
    default = next(l for l in script.splitlines() if l.startswith('DEFAULT=')).split('=', 1)[1].split(',')
    check(tiles(fresh) == [NEW_RECORD if t == OLD_RECORD else t for t in default],
          'with the default list cast and the assistant screen are not placed; only the recording tile is swapped')
    check(read(fresh, 'kwinrc', 'Wayland', 'InputMethod') == '', 'no input method is invented')
    return steps


if __name__ == '__main__':
    harness.run('settings_migration', test)
