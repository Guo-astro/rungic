# SPDX-License-Identifier: MIT
"""Desktop mode's fullscreen is an ordinary fullscreen window (docs/research/97 §21): on a portrait
phone-sized headless KWin, the floating window opens fullscreen from its toolbar; the fullscreen
window is KWin's active fullscreen (Active layer), steps down for a dialog that activates (as the
polkit prompt does) and comes back on top after it; Esc leaves it. The platform bridge is a stand-in
of its contract, so the window's queries are those the Rungic app answers on the phone."""
import os
import subprocess
from pathlib import Path

import contracts
import harness

ACTIVE, NORMAL, ABOVE = 5, 2, 3
DIALOG = '''
import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk
d = Gtk.MessageDialog(text="system test dialog"); d.set_title("system test dialog"); d.run()
'''


# covers[system]: desktop-mode.fullscreen/E2 desktop-mode.fullscreen/E5
# covers[consumer]: iface:platform-bridge
def test():
    with contracts.StandIn('platform-bridge') as bridge, harness.Session(1080, 2400) as s:
        os.environ['RUNGIC_PLATFORM_SOCKET'] = bridge.path
        (s.runtime / 'wayland-ws-0').touch()     # the independent desktop runs: desktop mode is on
        s.start(['/usr/libexec/rungic-agent-screen-window', '--desktop'])
        floater = s.wait_for(lambda: s.find(cls='rungic-agent-screen-window'), 20, 'the floating window')
        s.check(floater['layer'] == ABOVE, 'the floating window is a layer surface in the top layer')
        # Its picture at the default place: 72% of the width at (12, 110), 16:9; the toolbar under it,
        # the fullscreen button first (Main.qml).
        width = round(1080 * 0.72)
        height = round(width * 9 / 16)
        s.tap(12 + width / 2, 110 + height / 2)
        bar_x = 12 + (width - 188) / 2
        s.tap(bar_x + 8 + 20, 110 + height + 10 + 20)
        full = s.wait_for(lambda: s.find(cls='com.rungic.DesktopMode', full=True), 10, 'the fullscreen window')
        s.check(full['layer'] == ACTIVE and full['active'], 'fullscreen is the active fullscreen window, in the Active layer')
        s.check(full['frame'] == [0, 0, 1080, 2400], 'fullscreen covers the whole output')
        dialog = s.start(['python3', '-c', DIALOG])
        s.wait_for(lambda: s.find(caption='system test dialog', active=True), 10, 'the dialog, active')
        order = [w['caption'] for w in s.stack()]
        full = s.find(cls='com.rungic.DesktopMode')
        s.check(full['layer'] == NORMAL and order.index('system test dialog') > order.index(full['caption']),
                'an activated dialog is above fullscreen, which steps down to the Normal layer')
        dialog.kill()
        s.wait_for(lambda: s.find(cls='com.rungic.DesktopMode', active=True, layer=ACTIVE), 10, 'fullscreen back on top')
        s.check(True, 'fullscreen is back in the Active layer once the dialog is gone')
        s.key('ESCAPE')
        s.wait_for(lambda: not s.find(cls='com.rungic.DesktopMode'), 10, 'fullscreen left')
        s.check(s.find(cls='rungic-agent-screen-window') is not None, 'Esc leaves fullscreen; the floating window stays')
        s.check({'op': 'desktop-mode'} in bridge.requests, 'the window asked the platform bridge for desktop mode')
        return s.steps


if __name__ == '__main__':
    harness.run('desktop_mode_fullscreen', test)
