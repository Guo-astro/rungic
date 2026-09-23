#!/usr/bin/python3
"""Use the desktop's public D-Bus API for Android navigation actions."""
import sys
import dbus

bus = dbus.SessionBus()
action = sys.argv[1]
if action == 'hide-keyboard':
    obj = bus.get_object('org.kde.KWin', '/VirtualKeyboard')
    props = dbus.Interface(obj, 'org.freedesktop.DBus.Properties')
    if props.Get('org.kde.kwin.VirtualKeyboard', 'visible'):
        props.Set('org.kde.kwin.VirtualKeyboard', 'active', dbus.Boolean(False))
        print('hidden')
elif action == 'home':
    obj = bus.get_object('org.kde.plasmashell', '/Mobile')
    dbus.Interface(obj, 'org.kde.plasmashell').openHomeScreen()
else:
    raise SystemExit('Unknown desktop action')
