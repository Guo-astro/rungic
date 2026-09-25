#!/usr/bin/python3
"""Plasma Mobile's brightness D-Bus API backed by Android window brightness.

This implements BrightnessControl and loads the foreground inhibition subset.
Android retains automatic panel brightness, system suspend and physical locking.
"""
import concurrent.futures
import json
import logging
import signal
import socket

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

INTERFACE = 'org.kde.Solid.PowerManagement.Actions.BrightnessControl'
PATH = '/org/kde/Solid/PowerManagement/Actions/BrightnessControl'


def host(**value):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect('/mnt/android-wayland/platform.sock')
        connection.sendall(json.dumps(value).encode() + b'\n')
        with connection.makefile('rb') as stream:
            response = stream.readline(65537)
        if len(response) > 65536:
            raise OSError('Invalid host response')
        result = json.loads(response)
        if 'error' in result:
            raise OSError(result['error'])
        return result


class Brightness(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, PATH)
        self.level = 50
        self.pending = False
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.poll()
        GLib.timeout_add_seconds(2, self.poll)

    @dbus.service.method(INTERFACE, out_signature='i')
    def brightness(self):
        return self.level

    @dbus.service.method(INTERFACE, out_signature='i')
    def brightnessMax(self):
        return 100

    @dbus.service.method(INTERFACE, out_signature='i')
    def brightnessSteps(self):
        return 20

    @dbus.service.signal(INTERFACE, signature='i')
    def brightnessChanged(self, level):
        pass

    @dbus.service.signal(INTERFACE, signature='i')
    def brightnessMaxChanged(self, level):
        pass

    def update(self, value):
        value = max(2, min(100, int(value)))
        if value != self.level:
            self.level = value
            self.brightnessChanged(value)
        return False

    def poll(self):
        if not self.pending:
            self.pending = True
            def read():
                try:
                    result = host(op='brightness-get')
                    GLib.idle_add(self.update, result['level'])
                except (OSError, ValueError, KeyError):
                    pass
                GLib.idle_add(self.finished)
            self.pool.submit(read)
        return True

    def finished(self):
        self.pending = False
        return False

    @dbus.service.method(INTERFACE, in_signature='i', async_callbacks=('reply', 'error'))
    def setBrightness(self, level, reply, error):
        level = max(2, min(100, int(level)))
        def write():
            try:
                host(op='brightness', value=level / 100)
                GLib.idle_add(self.update, level)
                GLib.idle_add(lambda: (reply(), False)[1])
            except (OSError, ValueError) as exception:
                failure = dbus.DBusException(str(exception), name='dev.moto.Android.Unavailable')
                GLib.idle_add(lambda: (error(failure), False)[1])
        self.pool.submit(write)

    @dbus.service.method(INTERFACE, in_signature='i', async_callbacks=('reply', 'error'))
    def setBrightnessSilent(self, level, reply, error):
        self.setBrightness(level, reply, error)


DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
names = [dbus.service.BusName(name, bus, do_not_queue=True) for name in
         ('org.kde.Solid.PowerManagement', INTERFACE, 'org.freedesktop.PowerManagement.Inhibit', 'org.freedesktop.ScreenSaver')]
service = Brightness(bus)
import importlib.util
spec = importlib.util.spec_from_file_location('moto_power_policy', '/usr/libexec/moto-power-policy.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
policy = module.Policy(bus, host)
loop = GLib.MainLoop()
signal.signal(signal.SIGTERM, lambda *_: loop.quit())
loop.run()
