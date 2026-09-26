#!/usr/bin/python3
"""Align Plasma's status icons with Android's cutout, in logical coordinates."""
import configparser
import dbus
import json
import logging
from pathlib import Path
import subprocess
import time

source = Path('/mnt/android-wayland/android-display.ini')
previous = None

def notify_panel_config(keys):
    # KConfigWatcher protocol (KF6 6.24). Publish one notification after all
    # fields are on disk, and flush it before marking this metadata applied.
    # Separate short-lived kwriteconfig processes can exit with a notification
    # still queued; that left the running panel on an older height in testing.
    bus = dbus.SessionBus()
    message = dbus.lowlevel.SignalMessage(
        '/plasmamobilerc', 'org.kde.kconfig.notify', 'ConfigChanged')
    message.append({'Panels\x1dWhenOnTop': [dbus.ByteArray(k.encode()) for k in keys]},
                   signature='a{saay}')
    bus.send_message(message)
    bus.flush()

def panel_values(info, qt_screen, kscreen_output):
    width = info.getint('width')
    if width <= 0:
        raise ValueError('Invalid display width')
    # KWin's nested output has two coordinate systems. Qt reports the logical
    # screen (360px at 2x), KScreen reports its backend (720px at 1x). Upstream
    # PanelSettings divides config values by KScreen.scale, so compensate here.
    factor = qt_screen['width'] / width * kscreen_output['scale']
    left, right = info.getint('cutout-left'), info.getint('cutout-right')
    top = info.getint('cutout-top', fallback=0)
    bottom = info.getint('cutout-bottom')
    has_hole = 0 <= left < right <= width and 0 <= top < bottom <= 256
    # The native StatusBar centers its single row vertically. A panel height
    # twice the cutout center makes text/icons share that centerline; it does
    # not move all of them below the hole or add another safe-area band.
    return {
        'statusBarHeight': (top + bottom) * factor if has_hole else -1,
        'statusBarCenterSpacing': (right - left + 16) * factor if has_hole else 0,
        'statusBarLeftPadding': max(24, min(info.getint('safe-left'), 256)) * factor,
        'statusBarRightPadding': max(24, min(info.getint('safe-right'), 256)) * factor,
    }

while True:
    try:
        data = source.read_text()
        settings = Path.home() / '.config/kwinoutputconfig.json'
        signature = (data, settings.stat().st_mtime_ns if settings.exists() else 0)
        if signature != previous:
            config = configparser.ConfigParser()
            config.read_string(data)
            info = config['display']
            if info.getint('version') != 1:
                raise ValueError('Unsupported display protocol')
            screens = json.loads(subprocess.check_output(['rungic-plasma-screen-metrics'], timeout=10))
            outputs = json.loads(subprocess.check_output(['kscreen-doctor', '-j'], timeout=10))['outputs']
            screen = screens[0]
            output = next(o for o in outputs if o['name'] == screen['name'])
            values = panel_values(info, screen, output)
            for key, value in values.items():
                subprocess.run(['kwriteconfig6', '--file', 'plasmamobilerc',
                                '--group', 'Panels', '--group', 'WhenOnTop',
                                '--key', key, '--', str(value)], check=True)
            notify_panel_config(values)
            previous = signature
            logging.warning('Android centerline-aligned panel: %s; Qt=%s; KScreen scale=%s',
                            values, screen, output['scale'])
    except (OSError, ValueError, KeyError, IndexError, StopIteration, configparser.Error,
            subprocess.SubprocessError, dbus.DBusException) as error:
        logging.warning('Display metadata unavailable: %s', error)
    time.sleep(1)
