# SPDX-License-Identifier: GPL-3.0-or-later
"""PowerDevil inhibition subset for an Android foreground desktop window.

Android owns suspend and physical locking. These leases prevent foreground
screen timeout only; they never create a background CPU wake lock.
"""
import concurrent.futures
import dbus
import dbus.service
from gi.repository import GLib

POLICY = 'org.kde.Solid.PowerManagement.PolicyAgent'
PROPS = 'org.freedesktop.DBus.Properties'
LEGACY = 'org.freedesktop.PowerManagement.Inhibit'


class Policy(dbus.service.Object):
    def __init__(self, bus, host):
        super().__init__(bus, '/org/kde/Solid/PowerManagement/PolicyAgent')
        self.host = host
        self.records = {}
        self.counter = 0
        self.foreground = False
        self.ready = False
        self.locked = False
        self.pending = False
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.legacy = Legacy(bus, self)
        self.screensavers = [ScreenSaver(bus, self, path) for path in
                            ('/ScreenSaver', '/org/freedesktop/ScreenSaver')]
        bus.add_signal_receiver(self.owner_changed, signal_name='NameOwnerChanged',
                                dbus_interface='org.freedesktop.DBus')
        GLib.timeout_add_seconds(2, self.sync)
        self.sync()

    @dbus.service.method('dev.moto.Android.Power', in_signature='b', sender_keyword='sender')
    def SetWaylandInhibition(self, enabled, sender=None):
        key = ('wayland', sender)
        if enabled and key not in self.records:
            self.records[key] = (sender, 4, 'org.kde.KWin', 'Wayland 应用正在阻止屏幕休眠', True)
            self.changed()
        elif not enabled and self.records.pop(key, None):
            self.changed()

    def rows(self, active_only=False):
        rows = []
        for owner, types, who, why, allowed in self.records.values():
            active = allowed and self.ready and self.foreground
            if active_only and not active:
                continue
            what = ':'.join(name for bit, name in ((1, 'sleep'), (4, 'idle')) if types & bit)
            rows.append(dbus.Struct((what, who, why, 'block', dbus.UInt32((1 if active else 0) | (2 if allowed else 0))), signature='ssssu'))
        return dbus.Array(rows, signature='(ssssu)')

    def changed(self):
        self.PropertiesChanged(POLICY, {'RequestedInhibitions': self.rows(),
                                      'ActiveInhibitions': self.rows(True)}, [])
        self.legacy.HasInhibitChanged(bool(self.records))
        self.sync()

    @dbus.service.signal(PROPS, signature='sa{sv}as')
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    @dbus.service.method(PROPS, in_signature='ss', out_signature='v')
    def Get(self, interface, name):
        if interface != POLICY or name not in ('RequestedInhibitions', 'ActiveInhibitions'):
            raise dbus.DBusException('Unknown property', name=PROPS+'.UnknownProperty')
        return self.rows(name == 'ActiveInhibitions')

    @dbus.service.method(PROPS, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return {k: self.Get(interface, k) for k in ('RequestedInhibitions', 'ActiveInhibitions')} if interface == POLICY else {}

    @dbus.service.method(POLICY, in_signature='uss', out_signature='u', sender_keyword='sender')
    def AddInhibition(self, types, who, why, sender=None):
        if int(types) & ~5 or not int(types):
            raise dbus.DBusException('Only foreground idle/sleep leases are supported', name='org.freedesktop.DBus.Error.NotSupported')
        if len(self.records) >= 512:
            raise dbus.DBusException('Too many leases', name='org.freedesktop.DBus.Error.LimitsExceeded')
        self.counter += 1
        self.records[self.counter] = (sender, int(types), str(who)[:256], str(why)[:1024], True)
        self.changed()
        return self.counter

    @dbus.service.method(POLICY, in_signature='u', sender_keyword='sender')
    def ReleaseInhibition(self, cookie, sender=None):
        row = self.records.get(int(cookie))
        if row and row[0] != sender:
            raise dbus.DBusException('Lease belongs to another client', name='org.freedesktop.DBus.Error.AccessDenied')
        if self.records.pop(int(cookie), None):
            self.changed()

    @dbus.service.method(POLICY, in_signature='u', out_signature='b')
    def HasInhibition(self, types):
        return self.ready and self.foreground and any(r[1] & int(types) and r[4] for r in self.records.values())

    @dbus.service.method(POLICY, in_signature='ssb')
    def SetInhibitionAllowed(self, who, why, allowed):
        for key, row in list(self.records.items()):
            if row[2:4] == (who, why):
                self.records[key] = (*row[:4], bool(allowed))
        self.changed()

    @dbus.service.method(POLICY, out_signature='aas')
    def ListInhibitions(self):
        return dbus.Array([dbus.Array([r[2],r[3]],signature='s') for r in self.records.values() if r[4]], signature='as')

    def owner_changed(self, name, old, new):
        if new:
            return
        gone = [key for key, row in self.records.items() if row[0] == name]
        for key in gone:
            del self.records[key]
        if gone:
            self.changed()

    def sync(self):
        if self.pending:
            return True
        self.pending = True
        enabled = any(r[4] for r in self.records.values())
        def send():
            try:
                result = self.host(op='keep-awake', enabled=enabled)
                ready, foreground, locked = True, bool(result.get('foreground')), bool(result.get('locked'))
            except (OSError, ValueError):
                ready, foreground, locked = False, False, self.locked
            GLib.idle_add(self.synced, ready, foreground, locked)
        self.pool.submit(send)
        return True

    def synced(self, ready, foreground, locked):
        if self.locked != locked:
            self.locked = locked
            for saver in self.screensavers:
                saver.ActiveChanged(locked)
        self.pending = False
        changed = (self.ready, self.foreground) != (ready, foreground)
        self.ready, self.foreground = ready, foreground
        if changed:
            self.PropertiesChanged(POLICY, {'RequestedInhibitions': self.rows(),
                                          'ActiveInhibitions': self.rows(True)}, [])
        return False


class Legacy(dbus.service.Object):
    def __init__(self, bus, policy):
        super().__init__(bus, '/org/freedesktop/PowerManagement/Inhibit')
        self.policy = policy

    @dbus.service.method(LEGACY, in_signature='ss', out_signature='u', sender_keyword='sender')
    def Inhibit(self, who, why, sender=None):
        return self.policy.AddInhibition(1, who, why, sender)

    @dbus.service.method(LEGACY, in_signature='u', sender_keyword='sender')
    def UnInhibit(self, cookie, sender=None):
        self.policy.ReleaseInhibition(cookie, sender)

    @dbus.service.method(LEGACY, out_signature='b')
    def HasInhibit(self):
        return self.policy.HasInhibition(1)

    @dbus.service.signal(LEGACY, signature='b')
    def HasInhibitChanged(self, inhibited):
        pass


class ScreenSaver(dbus.service.Object):
    IFACE = 'org.freedesktop.ScreenSaver'

    def __init__(self, bus, policy, path):
        super().__init__(bus, path)
        self.policy = policy

    @dbus.service.method(IFACE, in_signature='ss', out_signature='u', sender_keyword='sender')
    def Inhibit(self, who, why, sender=None):
        return self.policy.AddInhibition(4, who, why, sender)

    @dbus.service.method(IFACE, in_signature='u', sender_keyword='sender')
    def UnInhibit(self, cookie, sender=None):
        self.policy.ReleaseInhibition(cookie, sender)

    @dbus.service.method(IFACE, out_signature='b')
    def GetActive(self):
        return self.policy.locked

    @dbus.service.method(IFACE)
    def Lock(self):
        self.policy.host(op='lock')

    @dbus.service.signal(IFACE, signature='b')
    def ActiveChanged(self, active):
        pass
