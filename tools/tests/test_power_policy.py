# SPDX-License-Identifier: MIT
"""Brightness and power on the Linux side (desktop/brightness.py, which loads desktop/power-policy.py
as installed: rungic-plasma-session). The service runs on a private session bus against a stand-in of
the platform bridge (tools/contracts.py; brightness-get from its contract, the writing ops answered as
PlatformBridge.java does); KConfig's kreadconfig6/kwriteconfig6 are small stand-ins on PATH. Clients
are ordinary D-Bus clients, as Plasma's applets, players and kcm_mobile_power are."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import dbus
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import contracts  # noqa: E402

BRIGHTNESS = ROOT / 'desktop/brightness.py'
POLICY = ROOT / 'desktop/power-policy.py'
SS = 'org.freedesktop.ScreenSaver'
AGENT = 'org.kde.Solid.PowerManagement.PolicyAgent'
BC = 'org.kde.Solid.PowerManagement.Actions.BrightnessControl'

# The installed layout: brightness.py loads the policy from /usr/libexec; here from the tree.
BOOT = textwrap.dedent('''
    import importlib.util, runpy, sys
    spec = importlib.util.spec_from_file_location
    policy = sys.argv[2]
    def located(name, path, *a, **k):
        if path == '/usr/libexec/rungic-power-policy.py':
            path = policy
        return spec(name, path, *a, **k)
    importlib.util.spec_from_file_location = located
    script = sys.argv[1]
    sys.argv = [script]
    runpy.run_path(script, run_name='__main__')
''')

# kreadconfig6 / kwriteconfig6 --file F --group G... --key K [--default D] [VALUE]
KCONFIG = textwrap.dedent('''
    import json, os, sys
    args = sys.argv[1:]
    groups, key, default, value, file = [], None, '', None, None
    i = 0
    while i < len(args):
        if args[i] == '--file': file = args[i + 1]; i += 2
        elif args[i] == '--group': groups.append(args[i + 1]); i += 2
        elif args[i] == '--key': key = args[i + 1]; i += 2
        elif args[i] == '--default': default = args[i + 1]; i += 2
        else: value = args[i]; i += 1
    path = os.path.join(os.environ['XDG_CONFIG_HOME'], file + '.json')
    store = json.load(open(path)) if os.path.exists(path) else {}
    name = '/'.join(groups) + ':' + key
    if os.path.basename(sys.argv[0]) == 'kreadconfig6':
        print(store.get(name, default))
    else:
        store[name] = value
        json.dump(store, open(path, 'w'))
''')


class Platform(contracts.StandIn):
    """The platform bridge: the contract's queries, and the ops these services write with."""

    def __init__(self, timeout_ms=60000):
        super().__init__('platform-bridge', {'brightness-get': {'level': 50, 'followAndroid': True}})
        self.foreground, self.locked, self.timeout_ms = True, False, timeout_ms

    def answer(self, request):
        op = request.get('op')
        if op == 'brightness':
            value = request['value']
            if not (value == -1 or 0.02 <= value <= 1):
                return {'error': 'brightness'}
            self.replies['brightness-get'] = {'level': round(value * 100), 'followAndroid': False}
            return {'ok': True}
        if op == 'keep-awake':
            return {'ok': True, 'foreground': self.foreground, 'locked': self.locked}
        if op == 'screen-timeout':
            if 'ms' in request:
                self.timeout_ms = request['ms']
            return {'ms': self.timeout_ms}
        if op == 'lock':
            return {'ok': True}
        return super().answer(request)

    def ops(self, op):
        return [r for r in self.requests if r.get('op') == op]


def wait_for(condition, what, timeout=8):
    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f'timed out waiting for {what}')
        time.sleep(0.05)


class Service:
    def __init__(self, tmp_path, platform):
        # A bus of its own (never the user's session bus), on a short path (sun_path is 108 bytes).
        self.bus_dir = tempfile.TemporaryDirectory(prefix='rungic-bus-')
        self.bus_daemon = subprocess.Popen(
            ['dbus-daemon', '--session', '--nofork', '--print-address=1', f'--address=unix:path={self.bus_dir.name}/bus'],
            stdout=subprocess.PIPE, text=True)
        self.address = self.bus_daemon.stdout.readline().strip()
        assert self.address.startswith(f'unix:path={self.bus_dir.name}/bus'), self.address
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir()
        for name in ('kreadconfig6', 'kwriteconfig6'):
            (bin_dir / name).write_text(f'#!{sys.executable}\n{KCONFIG}')
            (bin_dir / name).chmod(0o755)
        self.config = tmp_path / 'config'
        self.config.mkdir()
        env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=self.address, RUNGIC_PLATFORM_SOCKET=platform.path,
                   PATH=f'{bin_dir}:{os.environ["PATH"]}', XDG_CONFIG_HOME=str(self.config), LANG='C.UTF-8')
        self.process = subprocess.Popen([sys.executable, '-c', BOOT, str(BRIGHTNESS), str(POLICY)], env=env,
                                        stderr=open(tmp_path / "service.err", "w"))
        self.bus = self.client()
        wait_for(lambda: self.bus.name_has_owner(SS) and self.bus.name_has_owner(BC), 'the service on the bus')

    def client(self):
        return dbus.bus.BusConnection(self.address)

    def powerdevilrc(self):
        path = self.config / 'powerdevilrc.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def kwrite(self, name, value):
        store = self.powerdevilrc()
        store[name] = value
        (self.config / 'powerdevilrc.json').write_text(json.dumps(store))

    def stop(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.bus.close()
        self.bus_daemon.terminate()
        self.bus_daemon.wait(5)
        self.bus_dir.cleanup()


@pytest.fixture
def setup(tmp_path):
    started = []

    def start(**kwargs):
        platform = Platform(**kwargs).__enter__()
        service = Service(tmp_path, platform)
        started.append((platform, service))
        return platform, service
    yield start
    for platform, service in started:
        service.stop()
        platform.__exit__(None, None, None)


def screensaver(bus):
    return dbus.Interface(bus.get_object('org.freedesktop.ScreenSaver', '/org/freedesktop/ScreenSaver'), SS)


def agent(bus):
    return dbus.Interface(bus.get_object('org.kde.Solid.PowerManagement', '/org/kde/Solid/PowerManagement/PolicyAgent'), AGENT)


def last_awake(platform):
    awake = platform.ops('keep-awake')
    return awake[-1]['enabled'] if awake else None


# covers: desktop.power/E1
def test_a_player_keeps_the_screen_on_only_while_it_asks(setup):
    platform, service = setup()
    wait_for(lambda: last_awake(platform) is False, 'the first keep-awake sync, off')
    player = service.client()
    cookie = screensaver(player).Inhibit('org.kde.haruna', 'Playing a video')
    wait_for(lambda: last_awake(platform) is True, 'Android asked to keep the screen on')
    assert agent(service.bus).HasInhibition(dbus.UInt32(4))
    requested = agent(service.bus).Get(AGENT, 'RequestedInhibitions', dbus_interface='org.freedesktop.DBus.Properties')
    assert [(str(r[0]), str(r[1]), str(r[2])) for r in requested] == [('idle', 'org.kde.haruna', 'Playing a video')]
    # Another client cannot release the player's lease.
    other = service.client()
    with pytest.raises(dbus.DBusException) as denied:
        screensaver(other).UnInhibit(cookie)
    assert denied.value.get_dbus_name() == 'org.freedesktop.DBus.Error.AccessDenied'
    time.sleep(2.5)
    assert last_awake(platform) is True
    # Paused: the lease is released.
    screensaver(player).UnInhibit(cookie)
    wait_for(lambda: last_awake(platform) is False, 'the lease released')
    assert not agent(service.bus).HasInhibition(dbus.UInt32(4))
    # A client that goes away (quits, crashes) takes its lease with it: PowerDevil's interface too.
    leaving = service.client()
    dbus.Interface(leaving.get_object('org.kde.Solid.PowerManagement', '/org/kde/Solid/PowerManagement/PolicyAgent'),
                   AGENT).AddInhibition(dbus.UInt32(4), 'presenter', 'Presenting')
    legacy = service.client()
    dbus.Interface(legacy.get_object('org.freedesktop.PowerManagement.Inhibit', '/org/freedesktop/PowerManagement/Inhibit'),
                   'org.freedesktop.PowerManagement.Inhibit').Inhibit('downloader', 'Downloading')
    wait_for(lambda: last_awake(platform) is True, 'kept on again')
    leaving.close()
    legacy.close()
    wait_for(lambda: not agent(service.bus).Get(AGENT, 'RequestedInhibitions',
                                                dbus_interface='org.freedesktop.DBus.Properties'), 'leases reclaimed')
    wait_for(lambda: last_awake(platform) is False, 'the screen no longer kept on')
    # Only leases that keep the screen from going off: no others are taken.
    with pytest.raises(dbus.DBusException) as unsupported:
        agent(service.bus).AddInhibition(dbus.UInt32(2), 'x', 'shutdown')
    assert unsupported.value.get_dbus_name() == 'org.freedesktop.DBus.Error.NotSupported'


# covers: desktop.power/E4
def test_in_the_background_a_lease_is_not_active_and_it_is_renewed_while_the_bridge_lives(setup):
    platform, service = setup()
    platform.foreground = False                         # Rungic is not in front
    player = service.client()
    screensaver(player).Inhibit('player', 'Playing')
    wait_for(lambda: last_awake(platform) is True, 'the lease sent')
    wait_for(lambda: not agent(service.bus).HasInhibition(dbus.UInt32(4)), 'not active in the background', 5)
    active = agent(service.bus).Get(AGENT, 'ActiveInhibitions', dbus_interface='org.freedesktop.DBus.Properties')
    assert list(active) == []
    # Android lets the lease lapse after 12 s unless it is renewed: the bridge renews it every 2 s.
    before = len(platform.ops('keep-awake'))
    wait_for(lambda: len(platform.ops('keep-awake')) - before >= 2, 'two renewals', 8)
    assert all(r['enabled'] for r in platform.ops('keep-awake')[before:])
    platform.foreground = True
    wait_for(lambda: agent(service.bus).HasInhibition(dbus.UInt32(4)), 'active again in front', 5)
    # The bridge dies unexpectedly: nothing renews the lease any more.
    service.process.kill()
    service.process.wait(5)
    count = len(platform.ops('keep-awake'))
    time.sleep(2.5)
    assert len(platform.ops('keep-awake')) == count


# covers: desktop.power/E3
def test_the_screen_off_time_follows_android_both_ways(setup):
    platform, service = setup(timeout_ms=115000)        # Android: 1 min 55 s, nearest choice 2 min
    for profile in ('AC', 'Battery', 'LowBattery'):
        wait_for(lambda: service.powerdevilrc().get(f'{profile}/Display:TurnOffDisplayIdleTimeoutSec') == '120',
                 f'{profile} from Android')
        assert service.powerdevilrc()[f'{profile}/Display:TurnOffDisplayWhenIdle'] == 'true'
    pm = dbus.Interface(service.bus.get_object('org.kde.Solid.PowerManagement', '/org/kde/Solid/PowerManagement'),
                        'org.kde.Solid.PowerManagement')
    # The settings page writes powerdevilrc and asks for a refresh: Android gets the new time.
    service.kwrite('AC/Display:TurnOffDisplayIdleTimeoutSec', '300')
    pm.refreshStatus()
    wait_for(lambda: platform.timeout_ms == 300000, 'Android set to 5 min')
    service.kwrite('AC/Display:TurnOffDisplayWhenIdle', 'false')
    pm.reparseConfiguration()
    wait_for(lambda: platform.timeout_ms == 0, 'Android set to never')


def test_never_on_android_shows_as_never(setup):
    platform, service = setup(timeout_ms=0)
    wait_for(lambda: service.powerdevilrc().get('AC/Display:TurnOffDisplayWhenIdle') == 'false', 'never from Android')


# covers: desktop.power/E5
def test_lock_asks_android_and_android_locked_is_the_screensaver_active(setup):
    platform, service = setup()
    saver = screensaver(service.client())
    assert not saver.GetActive()
    saver.Lock()
    assert platform.ops('lock') == [{'op': 'lock'}]
    platform.locked = True                              # Android's keyguard reports locked
    wait_for(lambda: saver.GetActive(), 'the screensaver active while Android is locked', 5)
    platform.locked = False
    wait_for(lambda: not saver.GetActive(), 'inactive after unlocking', 5)


# covers: desktop.power/E6
def test_upower_never_shuts_down_or_hibernates_the_container():
    import configparser
    conf = configparser.ConfigParser()
    conf.optionxform = str
    conf.read(ROOT / 'system/config/etc/UPower/UPower.conf.d/60-rungic-android.conf')
    # UPower honours Ignore only with AllowRiskyCriticalPowerAction (up-daemon.c, 1.90+).
    assert conf['UPower']['CriticalPowerAction'] == 'Ignore'
    assert conf['UPower']['AllowRiskyCriticalPowerAction'] == 'true'


# covers: desktop.brightness/E1
# covers[consumer]: iface:platform-bridge
def test_plasma_brightness_is_the_window_brightness_and_follows_android_again(setup):
    platform, service = setup()
    control = dbus.Interface(service.bus.get_object('org.kde.Solid.PowerManagement',
                                                    '/org/kde/Solid/PowerManagement/Actions/BrightnessControl'), BC)
    wait_for(lambda: control.brightness() == 50, 'Android brightness read')
    assert control.brightnessMax() == 100
    control.setBrightness(45)
    assert platform.ops('brightness')[-1] == {'op': 'brightness', 'value': 0.45}
    assert control.brightness() == 45
    time.sleep(2.5)                                     # the next reads keep it
    assert control.brightness() == 45
    # Following Android again (the device page's switch): Plasma shows Android's setting.
    platform.replies['brightness-get'] = {'level': 72, 'followAndroid': True}
    wait_for(lambda: control.brightness() == 72, "Android's setting shown", 5)
    # Out of range from Plasma: clamped to what Android takes.
    control.setBrightness(0)
    assert platform.ops('brightness')[-1]['value'] == 0.02


# covers: desktop.brightness/E2
def test_brightness_only_touches_the_window_never_system_settings(setup):
    platform, service = setup()
    control = dbus.Interface(service.bus.get_object('org.kde.Solid.PowerManagement',
                                                    '/org/kde/Solid/PowerManagement/Actions/BrightnessControl'), BC)
    for level in (10, 45, 100):
        control.setBrightness(level)
    time.sleep(2.5)
    # The Linux side asks only for the window's brightness and reads; nothing else.
    assert {r['op'] for r in platform.requests} <= {'brightness', 'brightness-get', 'keep-awake', 'screen-timeout'}
    assert all(r == {'op': 'brightness', 'value': r['value']} for r in platform.ops('brightness'))
    # The app does not hold the permission to change system settings (brightness, its automatic
    # mode), and its brightness op sets the window's attribute only.
    manifest = (ROOT / 'android/app/AndroidManifest.xml').read_text()
    assert 'WRITE_SETTINGS' not in manifest
    bridge = (ROOT / 'android/app/src/com/rungic/plasma/PlatformBridge.java').read_text()
    op = bridge[bridge.index('if(op.equals("brightness"))'):]
    op = op[:op.index('\n        }\n')]
    assert 'screenBrightness' in op and 'Settings.' not in op and '/sys/' not in op
