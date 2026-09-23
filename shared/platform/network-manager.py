#!/usr/bin/python3
"""NetworkManager D-Bus subset backed by Android, not a network daemon.

Android alone owns the interfaces, routes, resolver and credentials. All data is
live and volatile. Unsupported mutations fail explicitly. Requires PyGObject.
"""
import concurrent.futures
import hashlib
import ipaddress
import json
import logging
import os
import signal
import socket
import struct
import threading
import time
import uuid
from xml.sax.saxutils import escape

from gi.repository import Gio, GLib

NM = 'org.freedesktop.NetworkManager'
BASE = '/org/freedesktop/NetworkManager'
PROPS = 'org.freedesktop.DBus.Properties'
OM = 'org.freedesktop.DBus.ObjectManager'
OM_PATH = '/org/freedesktop'
HOST = 'dev.moto.Android.Network'
SOCKET = '/mnt/android-wayland/platform.sock'
LOG = logging.getLogger('android-network')
V = GLib.Variant


def host_request(**request):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3.5)
        client.connect(SOCKET)
        client.sendall(json.dumps(request).encode() + b'\n')
        data = bytearray()
        while b'\n' not in data:
            part = client.recv(8192)
            if not part or len(data) + len(part) > 524288:
                raise OSError('Invalid Android response')
            data.extend(part)
        result = json.loads(data.split(b'\n', 1)[0])
        if 'error' in result:
            raise OSError(result['error'])
        return result


def props(**kwargs):
    return {key: V(sig, value) for key, (sig, value) in kwargs.items()}


def ident(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def profile(row, wifi):
    name = row.get('ssid') or 'Android ' + row['kind']
    kind = '802-11-wireless' if wifi else '802-3-ethernet' if row['kind'] == 'ethernet' else 'generic'
    uid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'android-network:' + row['kind'] + ':' + name + ':' + row['interface']))
    settings = {'connection': props(id=('s', name), uuid=('s', uid), type=('s', kind),
                                   **{'interface-name': ('s', row['interface']), 'read-only': ('b', True), 'autoconnect': ('b', False)}),
                'ipv4': props(method=('s', 'auto')), 'ipv6': props(method=('s', 'auto'))}
    if wifi:
        settings[kind] = props(ssid=('ay', list(row.get('ssid', '').encode())), mode=('s', 'infrastructure'))
    elif kind == '802-3-ethernet':
        settings[kind] = {}
    else:
        settings['generic'] = {}
    return name, uid, kind, settings


def ip_config(row, version):
    address_data, route_data, dns = [], [], []
    gateway = ''
    for value in row.get('addresses', []):
        try:
            a = ipaddress.ip_interface(value)
            if a.version == version:
                address_data.append(props(address=('s', str(a.ip)), prefix=('u', a.network.prefixlen)))
        except ValueError:
            continue
    for value in row.get('dns', []):
        try:
            if ipaddress.ip_address(value).version == version:
                dns.append(value.split('%')[0])
        except ValueError:
            continue
    for value in row.get('routes', []):
        try:
            r = ipaddress.ip_network(value['destination'], strict=False)
            if r.version != version:
                continue
            entry = props(dest=('s', str(r.network_address)), prefix=('u', r.prefixlen))
            if value.get('gateway'):
                hop = str(ipaddress.ip_address(value['gateway'])).split('%')[0]
                entry['next-hop'] = V('s', hop)
                if value.get('default'):
                    gateway = hop
            route_data.append(entry)
        except (ValueError, KeyError):
            continue
    result = props(AddressData=('aa{sv}', address_data), Gateway=('s', gateway), RouteData=('aa{sv}', route_data),
                   Domains=('as', []), Searches=('as', []), DnsOptions=('as', []), DnsPriority=('i', 0))
    if version == 4:
        result.update(props(NameserverData=('aa{sv}', [props(address=('s', a)) for a in dns]),
                            Nameservers=('au', [struct.unpack('=I', socket.inet_aton(a))[0] for a in dns]),
                            WinsServers=('au', []), WinsServerData=('as', [])))
    else:
        result['Nameservers'] = V('aay', [list(ipaddress.ip_address(a).packed) for a in dns])
    return result


def security_flags(security):
    # Android WifiInfo SECURITY_TYPE_* -> NM AP security flags. Unknown is
    # deliberately not labelled open: no AP is published without known security.
    return {0: (0, 0), 1: (1, 0), 2: (1, 0x100 | 0x88), 3: (1, 0x200 | 0x88),
            4: (1, 0x400 | 0x88), 5: (1, 0x2000 | 0x88), 6: (1, 0x800 | 0x88),
            9: (1, 0x200 | 0x88)}.get(security)


def make_graph(snapshot):
    """Build a complete snapshot before publishing any changes on the bus."""
    available = snapshot is not None
    snapshot = snapshot or {}
    rows = snapshot.get('networks', [])
    wifi = next((r for r in rows if r['kind'] == 'wifi'), None)
    default = next((r for r in rows if r.get('default')), None)
    enabled = bool(snapshot.get('wifiEnabled', False))
    connectivity = (4 if default.get('validated') else 2 if default.get('captive') else 3) if default else (1 if available else 0)
    state = (70 if default.get('validated') else 50) if default else (20 if available else 0)
    graph, settings = {}, {}
    devices, connections, active = [], [], []
    primary = '/'
    primary_type = ''
    # Always retain the real Wi-Fi device when disabled; other objects exist
    # only while Android reports those actual networks. No synthetic Ethernet.
    inputs = [('wifi', wifi)]
    inputs += [(ident(r['interface']), r) for r in rows if r['kind'] != 'wifi']
    for token, row in inputs:
        is_wifi = token == 'wifi'
        device = BASE + '/Devices/' + token
        devices.append(device)
        iface = row['interface'] if row else 'wlan0'
        dev_state = 100 if row else (30 if enabled and available else 20)
        device_type = 2 if is_wifi else 1 if row['kind'] == 'ethernet' else 14
        ac = BASE + '/ActiveConnection/' + token if row else '/'
        conn = BASE + '/Settings/' + token if row else '/'
        ip4, ip6, ap = '/', '/', '/'
        hw = row.get('mac', '') if row else ''
        dev_connectivity = (4 if row.get('validated') else 2 if row.get('captive') else 3) if row else 1
        if row:
            name, uid, kind, profile_data = profile(row, is_wifi)
            settings[conn] = profile_data
            connections.append(conn)
            active.append(ac)
            for version in (4, 6):
                config = ip_config(row, version)
                if config['AddressData'].n_children():
                    path = BASE + '/IP%dConfig/' % version + token
                    graph[path] = {NM + '.IP%dConfig' % version: config}
                    if version == 4:
                        ip4 = path
                    else:
                        ip6 = path
            sec = security_flags(row.get('security', -1))
            if is_wifi and row.get('ssid') and sec is not None:
                ap = BASE + '/AccessPoint/' + ident(row.get('bssid') or row['ssid'])
                rssi = row.get('rssi', -100)
                strength = max(0, min(100, round((rssi + 100) * 100 / 45)))
                graph[ap] = {NM + '.AccessPoint': props(Flags=('u', sec[0]), WpaFlags=('u', 0), RsnFlags=('u', sec[1]),
                    Ssid=('ay', list(row['ssid'].encode())), Frequency=('u', max(0, row.get('frequency', 0))),
                    HwAddress=('s', row.get('bssid', '')), Mode=('u', 2), MaxBitrate=('u', max(0, row.get('linkMbps', 0)) * 1000),
                    Strength=('y', strength), LastSeen=('i', int(time.monotonic())))}
            graph[conn] = {NM + '.Settings.Connection': props(Unsaved=('b', True), Flags=('u', 3), Filename=('s', ''))}
            graph[ac] = {NM + '.Connection.Active': props(Connection=('o', conn), SpecificObject=('o', ap), Id=('s', name),
                Uuid=('s', uid), Type=('s', kind), Devices=('ao', [device]), State=('u', 2),
                StateFlags=('u', 128 | 4 | (8 if ip4 != '/' else 0) | (16 if ip6 != '/' else 0)),
                Default=('b', bool(row.get('default') and ip4 != '/' and graph[ip4][NM + '.IP4Config']['Gateway'].unpack())),
                Default6=('b', bool(row.get('default') and ip6 != '/' and graph[ip6][NM + '.IP6Config']['Gateway'].unpack())),
                Ip4Config=('o', ip4), Ip6Config=('o', ip6), Dhcp4Config=('o', '/'), Dhcp6Config=('o', '/'),
                Vpn=('b', False), Controller=('o', '/'), Master=('o', '/'))}
            if row.get('default'):
                primary, primary_type = ac, kind
        graph[device] = {NM + '.Device': props(Udi=('s', 'android:' + iface), Interface=('s', iface), IpInterface=('s', iface if row else ''),
            Driver=('s', 'android'), DriverVersion=('s', ''), FirmwareVersion=('s', ''), Capabilities=('u', 1),
            State=('u', dev_state), StateReason=('(uu)', (dev_state, 0)), DeviceType=('u', device_type),
            Managed=('b', available), Autoconnect=('b', False), Real=('b', True), HwAddress=('s', hw),
            Ip4Config=('o', ip4), Ip6Config=('o', ip6), Dhcp4Config=('o', '/'), Dhcp6Config=('o', '/'),
            ActiveConnection=('o', ac), AvailableConnections=('ao', [conn] if row else []),
            FirmwareMissing=('b', False), NmPluginMissing=('b', False), Mtu=('u', max(0, row.get('mtu', 0)) if row else 0),
            Metered=('u', (1 if row.get('metered') else 2) if row else 0),
            Ip4Connectivity=('u', dev_connectivity if ip4 != '/' else 1), Ip6Connectivity=('u', dev_connectivity if ip6 != '/' else 1))}
        if is_wifi:
            # Encryption and known frequency bands; deliberately no AP/hotspot capability.
            caps = 0x28 | 0x100 | 0x200
            if snapshot.get('wifi5GHz'):
                caps |= 0x400
            if snapshot.get('wifi6GHz'):
                caps |= 0x800
            graph[device][NM + '.Device.Wireless'] = props(HwAddress=('s', hw), PermHwAddress=('s', ''), Mode=('u', 2 if row else 0),
                Bitrate=('u', max(0, row.get('linkMbps', 0)) * 1000 if row else 0), WirelessCapabilities=('u', caps),
                AccessPoints=('ao', [ap] if ap != '/' else []), ActiveAccessPoint=('o', ap), LastScan=('x', -1))
        elif device_type == 1:
            graph[device][NM + '.Device.Wired'] = props(HwAddress=('s', hw), PermHwAddress=('s', ''), Speed=('u', 0),
                S390Subchannels=('as', []), Carrier=('b', True))
        else:
            graph[device][NM + '.Device.Generic'] = props(TypeDescription=('s', 'Android ' + row['kind']))
    graph[BASE] = {NM: props(Devices=('ao', devices), AllDevices=('ao', devices), ActiveConnections=('ao', active),
        PrimaryConnection=('o', primary), PrimaryConnectionType=('s', primary_type), ActivatingConnection=('o', '/'),
        State=('u', state), Startup=('b', False), Version=('s', '1.54.0-android-bridge.1'), Capabilities=('au', []),
        NetworkingEnabled=('b', available), WirelessEnabled=('b', enabled), WirelessHardwareEnabled=('b', available),
        WwanEnabled=('b', False), WwanHardwareEnabled=('b', False), Connectivity=('u', connectivity),
        ConnectivityCheckAvailable=('b', False), ConnectivityCheckEnabled=('b', False), ConnectivityCheckUri=('s', ''),
        Metered=('u', (1 if default.get('metered') else 2) if default else 0)),
        HOST: props(BackendAvailable=('b', available), Manager=('s', 'Android'), Version=('s', '1'),
                    DefaultTransport=('s', default['kind'] if default else ''), ConfigurationReadOnly=('b', True))}
    graph[BASE + '/Settings'] = {NM + '.Settings': props(Connections=('ao', connections), Hostname=('s', 'android'), CanModify=('b', False))}
    graph[BASE + '/AgentManager'] = {NM + '.AgentManager': {}}
    return graph, settings


# Signatures are a deliberately bounded part of the public NM protocol.
METHODS = {
    NM: {'GetDevices': ('', 'ao'), 'GetAllDevices': ('', 'ao'), 'GetDeviceByIpIface': ('s', 'o'),
         'GetPermissions': ('', 'a{ss}'), 'CheckConnectivity': ('', 'u'), 'state': ('', 'u'),
         'ActivateConnection': ('ooo', 'o'), 'AddAndActivateConnection': ('a{sa{sv}}oo', 'oo'),
         'AddAndActivateConnection2': ('a{sa{sv}}ooa{sv}', 'ooa{sv}'), 'DeactivateConnection': ('o', ''),
         'Enable': ('b', ''), 'Sleep': ('b', ''), 'Reload': ('u', '')},
    NM + '.Device': {'Disconnect': ('', ''), 'Delete': ('', '')},
    NM + '.Device.Wireless': {'GetAccessPoints': ('', 'ao'), 'GetAllAccessPoints': ('', 'ao'), 'RequestScan': ('a{sv}', '')},
    NM + '.Settings': {'ListConnections': ('', 'ao'), 'GetConnectionByUuid': ('s', 'o'),
                      'AddConnection': ('a{sa{sv}}', 'o'), 'AddConnectionUnsaved': ('a{sa{sv}}', 'o'),
                      'SaveHostname': ('s', ''), 'ReloadConnections': ('', 'b')},
    NM + '.Settings.Connection': {'GetSettings': ('', 'a{sa{sv}}'), 'GetSecrets': ('s', 'a{sa{sv}}'),
                                  'Update': ('a{sa{sv}}', ''), 'UpdateUnsaved': ('a{sa{sv}}', ''),
                                  'Update2': ('a{sa{sv}}ua{sv}', 'a{sv}'), 'Delete': ('', ''), 'Save': ('', '')},
    NM + '.AgentManager': {'Register': ('s', ''), 'RegisterWithCapabilities': ('su', ''), 'Unregister': ('', '')},
    HOST: {'OpenSettings': ('', '')},
    OM: {'GetManagedObjects': ('', 'a{oa{sa{sv}}}')},
}
SIGNALS = {NM: {'StateChanged': 'u', 'DeviceAdded': 'o', 'DeviceRemoved': 'o', 'CheckPermissions': ''},
    NM + '.Device': {'StateChanged': 'uuu'}, NM + '.Device.Wireless': {'AccessPointAdded': 'o', 'AccessPointRemoved': 'o'},
    NM + '.Settings': {'NewConnection': 'o', 'ConnectionRemoved': 'o'}, NM + '.Settings.Connection': {'Updated': '', 'Removed': ''},
    OM: {'InterfacesAdded': 'oa{sa{sv}}', 'InterfacesRemoved': 'oas'}}


def signature_parts(signature):
    def end(pos):
        if signature[pos] == 'a':
            return end(pos + 1)
        if signature[pos] in '({':
            closing = ')' if signature[pos] == '(' else '}'
            pos += 1
            while signature[pos] != closing:
                pos = end(pos)
            return pos + 1
        return pos + 1
    pos = 0
    while pos < len(signature):
        next_pos = end(pos)
        yield signature[pos:next_pos]
        pos = next_pos


def introspection(interface, properties):
    xml = '<node><interface name="' + interface + '">'
    for key, value in properties.items():
        access = 'readwrite' if interface == NM and key == 'WirelessEnabled' else 'read'
        xml += '<property name="%s" type="%s" access="%s"/>' % (key, escape(value.get_type_string()), access)
    for method, (ins, outs) in METHODS.get(interface, {}).items():
        xml += '<method name="' + method + '">'
        for direction, sig in [('in', ins), ('out', outs)]:
            for t in signature_parts(sig):
                xml += '<arg type="%s" direction="%s"/>' % (escape(t), direction)
        xml += '</method>'
    for name, sig in SIGNALS.get(interface, {}).items():
        xml += '<signal name="' + name + '">'
        for t in signature_parts(sig):
            xml += '<arg type="%s"/>' % escape(t)
        xml += '</signal>'
    return Gio.DBusNodeInfo.new_for_xml(xml + '</interface></node>').interfaces[0]


class Bridge:
    def __init__(self, bus):
        self.bus = bus
        self.graph, self.settings = {}, {}
        self.registrations = {}
        self.pool = concurrent.futures.ThreadPoolExecutor(2, thread_name_prefix='android-network')
        self.polling = False
        self.alive = True
        self.online = None
        self.agents = set()
        bus.register_object(OM_PATH, introspection(OM, {}), self.call, None, None)
        self.publish(None)

    def emit(self, path, interface, signal_name, sig, values):
        self.bus.emit_signal(None, path, interface, signal_name, V('(' + sig + ')', values))

    def publish(self, snapshot):
        try:
            graph, settings = make_graph(snapshot)
        except (KeyError, TypeError, ValueError):
            LOG.warning('Invalid Android network snapshot')
            graph, settings = make_graph(None)
            snapshot = None
        old, old_settings = self.graph, self.settings
        self.graph, self.settings = graph, settings
        online = snapshot is not None
        if online != self.online:
            LOG.info('Android backend %s', 'available' if online else 'unavailable')
            self.online = online
        for path, interfaces in graph.items():
            added = {}
            for iface, values in interfaces.items():
                if (path, iface) not in self.registrations:
                    self.registrations[path, iface] = self.bus.register_object(path, introspection(iface, values), self.call, self.get, self.set)
                    added[iface] = values
                elif values != old.get(path, {}).get(iface, {}):
                    delta = {key: val for key, val in values.items() if val != old[path][iface].get(key)}
                    self.emit(path, PROPS, 'PropertiesChanged', 'sa{sv}as', (iface, delta, []))
            if added:
                self.emit(OM_PATH, OM, 'InterfacesAdded', 'oa{sa{sv}}', (path, added))
        for path, interfaces in old.items():
            removed = [iface for iface in interfaces if iface not in graph.get(path, {})]
            if removed:
                self.emit(OM_PATH, OM, 'InterfacesRemoved', 'oas', (path, removed))
                for iface in removed:
                    self.bus.unregister_object(self.registrations.pop((path, iface)))
        if old:
            before, after = old[BASE][NM]['State'].unpack(), graph[BASE][NM]['State'].unpack()
            if before != after:
                self.emit(BASE, NM, 'StateChanged', 'u', (after,))
            for prop, iface, added, removed in [('Devices', NM, 'DeviceAdded', 'DeviceRemoved')]:
                a, b = set(old[BASE][NM][prop].unpack()), set(graph[BASE][NM][prop].unpack())
                for path in b - a:
                    self.emit(BASE, iface, added, 'o', (path,))
                for path in a - b:
                    self.emit(BASE, iface, removed, 'o', (path,))
            for path, interfaces in graph.items():
                if NM + '.Device' in interfaces and path in old:
                    before = old[path][NM + '.Device']['State'].unpack()
                    after = interfaces[NM + '.Device']['State'].unpack()
                    if before != after:
                        self.emit(path, NM + '.Device', 'StateChanged', 'uuu', (after, before, 0))
                wifi = NM + '.Device.Wireless'
                if wifi in interfaces and wifi in old.get(path, {}):
                    a, b = set(old[path][wifi]['AccessPoints'].unpack()), set(interfaces[wifi]['AccessPoints'].unpack())
                    for ap in b - a:
                        self.emit(path, wifi, 'AccessPointAdded', 'o', (ap,))
                    for ap in a - b:
                        self.emit(path, wifi, 'AccessPointRemoved', 'o', (ap,))
            for path in settings.keys() - old_settings.keys():
                self.emit(BASE + '/Settings', NM + '.Settings', 'NewConnection', 'o', (path,))
            for path in old_settings.keys() - settings.keys():
                self.emit(path, NM + '.Settings.Connection', 'Removed', '', ())
                self.emit(BASE + '/Settings', NM + '.Settings', 'ConnectionRemoved', 'o', (path,))
            for path in settings.keys() & old_settings.keys():
                if settings[path] != old_settings[path]:
                    self.emit(path, NM + '.Settings.Connection', 'Updated', '', ())
        return False

    def poll(self):
        if not self.polling:
            self.polling = True
            def work():
                try:
                    data = host_request(op='network-get')
                    if data.get('version') != 1:
                        raise ValueError('Unsupported host protocol')
                except (OSError, ValueError):
                    data = None
                def done():
                    self.polling = False
                    if self.alive:
                        self.publish(data)
                    return False
                GLib.idle_add(done)
            self.pool.submit(work)
        return GLib.SOURCE_CONTINUE

    def get(self, bus, sender, path, interface, name):
        return self.graph.get(path, {}).get(interface, {}).get(name)

    def set(self, bus, sender, path, interface, name, value):
        if path != BASE or interface != NM or name != 'WirelessEnabled':
            return False
        try:
            result = host_request(op='network-wifi', enabled=value.unpack())
            if not result.get('accepted'):
                return False
            self.poll()
            return True  # accepted only; published state always comes from Android
        except (OSError, ValueError):
            return False

    def call(self, bus, sender, path, interface, method, args, invocation):
        def reply(sig='', *values):
            invocation.return_value(V('(' + sig + ')', values))
        def unsupported():
            invocation.return_dbus_error(NM + '.NotSupported', 'This connection is managed by Android. Use Android network settings; Linux profiles are read-only.')
        try:
            if interface == OM and method == 'GetManagedObjects':
                return reply('a{oa{sa{sv}}}', self.graph)
            if interface == HOST and method == 'OpenSettings':
                def work():
                    try:
                        host_request(op='settings', target='network')
                        GLib.idle_add(lambda: (reply(), False)[1])
                    except (OSError, ValueError):
                        GLib.idle_add(lambda: (invocation.return_dbus_error(HOST + '.Unavailable', 'Return to the Linux desktop and try again.'), False)[1])
                self.pool.submit(work)
                return
            if interface == NM:
                if method in ('GetDevices', 'GetAllDevices'):
                    return reply('ao', self.graph[BASE][NM]['Devices'].unpack())
                if method == 'GetDeviceByIpIface':
                    for p, interfaces in self.graph.items():
                        if NM + '.Device' in interfaces and interfaces[NM + '.Device']['Interface'].unpack() == args.unpack()[0]:
                            return reply('o', p)
                    invocation.return_dbus_error(NM + '.UnknownDevice', 'No such Android interface')
                    return
                if method == 'GetPermissions':
                    permissions = {NM + '.' + s: 'no' for s in ('enable-disable-network', 'enable-disable-wifi', 'enable-disable-wwan',
                        'sleep-wake', 'network-control', 'wifi.share.protected', 'wifi.share.open', 'settings.modify.system',
                        'settings.modify.own', 'settings.modify.hostname', 'settings.modify.global-dns', 'reload', 'checkpoint-rollback',
                        'enable-disable-statistics', 'enable-disable-connectivity-check', 'wifi.scan')}
                    permissions[NM + '.enable-disable-wifi'] = 'yes'
                    return reply('a{ss}', permissions)
                if method in ('state', 'CheckConnectivity'):
                    return reply('u', self.graph[BASE][NM]['State' if method == 'state' else 'Connectivity'].unpack())
                if method == 'ActivateConnection' and args.unpack()[0] in self.settings:
                    # Returning an already active connection performs no mutation.
                    for p, ifaces in self.graph.items():
                        ac = ifaces.get(NM + '.Connection.Active', {})
                        if ac.get('Connection') == V('o', args.unpack()[0]):
                            return reply('o', p)
            if interface == NM + '.Device.Wireless':
                if method in ('GetAccessPoints', 'GetAllAccessPoints'):
                    return reply('ao', self.graph[path][interface]['AccessPoints'].unpack())
            if interface == NM + '.Settings':
                if method == 'ListConnections':
                    return reply('ao', list(self.settings))
                if method == 'GetConnectionByUuid':
                    for p, s in self.settings.items():
                        if s['connection']['uuid'].unpack() == args.unpack()[0]:
                            return reply('o', p)
                    invocation.return_dbus_error(NM + '.Settings.InvalidConnection', 'No such active Android connection')
                    return
            if interface == NM + '.Settings.Connection':
                if method == 'GetSettings':
                    return reply('a{sa{sv}}', self.settings[path])
                if method == 'GetSecrets':
                    return reply('a{sa{sv}}', {})  # credentials are never read or cached
            if interface == NM + '.AgentManager':
                if method in ('Register', 'RegisterWithCapabilities'):
                    self.agents.add(sender)
                    return reply()
                if method == 'Unregister':
                    self.agents.discard(sender)
                    return reply()
            unsupported()
        except Exception:
            LOG.exception('D-Bus method failed: %s', method)
            invocation.return_dbus_error(HOST + '.Failed', 'Android network bridge request failed')


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    # Never replace a real NetworkManager or another bridge instance.
    result = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'RequestName',
                          V('(su)', (NM, 4)), V('(u)', (0,)).get_type(), Gio.DBusCallFlags.NONE, 3000, None)
    if result.unpack()[0] != 1:
        raise SystemExit('NetworkManager bus name is already owned')
    bridge = Bridge(bus)
    loop = GLib.MainLoop()
    def stop():
        bridge.alive = False
        loop.quit()
        return False
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, stop)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, stop)
    bridge.poll()
    GLib.timeout_add_seconds(2, bridge.poll)
    try:
        loop.run()
    finally:
        bridge.alive = False
        bridge.pool.shutdown(wait=True, cancel_futures=True)


if __name__ == '__main__':
    main()
