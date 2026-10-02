"""rungic-bus-forward: a service of the user's bus offered on another bus (docs/research/97 §19.2).

Two real bus daemons: a service on the "user" one, the forwarder on the "desktop" one; calls,
errors, replies and signals seen from the desktop side.
"""
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'agent/workspace/rungic-bus-forward'
NAME = 'org.example.Secret'

SERVICE = textwrap.dedent('''
    import gi
    gi.require_version('Gio', '2.0')
    from gi.repository import Gio, GLib
    XML = """<node><interface name="org.example.Secret">
      <method name="Echo"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
      <method name="Fail"/>
      <method name="Shout"><arg type="s" direction="in"/></method>
      <signal name="Said"><arg type="s"/></signal>
    </interface></node>"""
    info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def call(conn, sender, path, iface, method, params, invocation):
        if method == 'Echo':
            invocation.return_value(GLib.Variant('(s)', ('echo ' + params[0],)))
        elif method == 'Fail':
            invocation.return_dbus_error('org.example.Error.Locked', 'the wallet is locked')
        elif method == 'Shout':
            conn.emit_signal(None, path, iface, 'Said', GLib.Variant('(s)', (params[0],)))
            invocation.return_value(None)
    bus.register_object('/org/example/secret', info, call, None, None)
    Gio.bus_own_name_on_connection(bus, 'org.example.Secret', Gio.BusNameOwnerFlags.NONE, None, None)
    print('ready', flush=True)
    GLib.MainLoop().run()
''')


def bus(tmp_path, name):
    address = f'unix:path={tmp_path}/{name}'
    process = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--nopidfile', f'--address={address}'])
    for _ in range(50):
        if (tmp_path / name).exists():
            break
        time.sleep(0.05)
    return address, process


def gdbus(address, *args):
    env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address)
    return subprocess.run(['gdbus', *args], env=env, capture_output=True, text=True, timeout=20)


@pytest.mark.skipif(not shutil.which('dbus-daemon') or not shutil.which('gdbus'), reason='needs dbus-daemon and gdbus')
def test_calls_errors_and_signals_reach_the_users_service(tmp_path):
    user, user_bus = bus(tmp_path, 'user')
    desktop, desktop_bus = bus(tmp_path, 'desktop')
    processes = [user_bus, desktop_bus]
    try:
        service = subprocess.Popen([sys.executable, '-c', SERVICE], env=dict(os.environ, DBUS_SESSION_BUS_ADDRESS=user),
                                   stdout=subprocess.PIPE, text=True)
        processes.append(service)
        assert service.stdout.readline().strip() == 'ready'
        forward = subprocess.Popen([sys.executable, str(SCRIPT), NAME],
                                   env=dict(os.environ, DBUS_SESSION_BUS_ADDRESS=desktop, RUNGIC_USER_BUS=user))
        processes.append(forward)
        for _ in range(50):
            if NAME in gdbus(desktop, 'call', '--session', '--dest', 'org.freedesktop.DBus', '--object-path', '/org/freedesktop/DBus',
                             '--method', 'org.freedesktop.DBus.ListNames').stdout:
                break
            time.sleep(0.1)

        echo = gdbus(desktop, 'call', '--session', '--dest', NAME, '--object-path', '/org/example/secret',
                     '--method', 'org.example.Secret.Echo', 'hello')
        assert echo.stdout.strip() == "('echo hello',)"

        failed = gdbus(desktop, 'call', '--session', '--dest', NAME, '--object-path', '/org/example/secret',
                       '--method', 'org.example.Secret.Fail')
        assert failed.returncode != 0
        assert 'org.example.Error.Locked' in failed.stderr and 'the wallet is locked' in failed.stderr

        introspected = gdbus(desktop, 'introspect', '--session', '--dest', NAME, '--object-path', '/org/example/secret')
        assert 'Echo' in introspected.stdout and 'Said' in introspected.stdout

        monitor = subprocess.Popen(['gdbus', 'monitor', '--session', '--dest', NAME],
                                   env=dict(os.environ, DBUS_SESSION_BUS_ADDRESS=desktop), stdout=subprocess.PIPE, text=True)
        processes.append(monitor)
        time.sleep(0.5)
        gdbus(desktop, 'call', '--session', '--dest', NAME, '--object-path', '/org/example/secret',
              '--method', 'org.example.Secret.Shout', 'saved')
        deadline = time.time() + 5
        seen = ''
        while time.time() < deadline and 'Said' not in seen:
            seen += monitor.stdout.readline()
        assert "org.example.Secret.Said ('saved',)" in seen
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
