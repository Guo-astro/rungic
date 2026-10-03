# SPDX-License-Identifier: MIT
"""The Bluetooth contract from the Linux side: the real BlueZ service shared/platform/bluez.py against
tools/contracts.py's stand-in of the platform bridge (quality/contracts/bluetooth.json), on a D-Bus
connection that records what it would publish. The provider's side is the acceptance scenario
contract.bluetooth on the phone."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools/tests'))
import contracts  # noqa: E402
from test_contract_network import Bus, Invocation, service  # noqa: E402

GLib = pytest.importorskip('gi.repository.GLib')
ADAPTER = '/org/bluez/hci0'
STATE = next(q for q in contracts.load('bluetooth')['queries'] if q['name'] == 'state')['reply']
BUDS, SPEAKER = '11:22:33:44:55:66', '77:88:99:AA:BB:CC'


def started(monkeypatch, android):
    module = service(monkeypatch, android.path, 'shared/platform/bluez.py', 'android_bluetooth')
    bridge = module.Bridge(Bus())
    bridge.poll()
    assert module.GLib.settle(lambda: not bridge.polling and ADAPTER in bridge.graph and len(bridge.graph) > 2)
    return module, bridge


def prop(bridge, path, interface, name):
    return bridge.graph[path][interface][name].unpack()


# covers[consumer]: iface:bluetooth
def test_android_adapter_and_devices_become_bluez_objects(monkeypatch):
    with contracts.StandIn('bluetooth') as android:
        module, bridge = started(monkeypatch, android)
    assert prop(bridge, ADAPTER, 'org.bluez.Adapter1', 'Powered') is True
    assert prop(bridge, ADAPTER, 'org.bluez.Adapter1', 'Alias') == 'moto g100'
    assert prop(bridge, ADAPTER, 'org.bluez.Adapter1', 'Address') == 'AA:BB:CC:00:11:22'
    buds = module.device_path(BUDS)
    assert prop(bridge, buds, 'org.bluez.Device1', 'Paired') is True
    assert prop(bridge, buds, 'org.bluez.Device1', 'Connected') is True
    assert prop(bridge, buds, 'org.bluez.Device1', 'Icon') == 'audio-headphones'
    assert prop(bridge, buds, 'org.bluez.Device1', 'UUIDs') == ['0000110b-0000-1000-8000-00805f9b34fb']
    # A device found while discovering, not bonded: shown by its address, not paired.
    speaker = module.device_path(SPEAKER)
    assert prop(bridge, speaker, 'org.bluez.Device1', 'Paired') is False
    assert prop(bridge, speaker, 'org.bluez.Device1', 'Alias') == SPEAKER.replace(':', '-')
    assert android.requests == [{'op': 'bluetooth', 'action': 'state'}]
    assert android.problems == []


# covers[consumer]: iface:bluetooth
def test_no_android_bluetooth_is_an_adapter_switched_off(monkeypatch):
    with contracts.StandIn('bluetooth', handler=lambda name, request: {'error': 'No Bluetooth adapter'}) as android:
        module = service(monkeypatch, android.path, 'shared/platform/bluez.py', 'android_bluetooth')
        bridge = module.Bridge(Bus())
        bridge.poll()
        assert module.GLib.settle(lambda: not bridge.polling)
    assert prop(bridge, ADAPTER, 'org.bluez.Adapter1', 'Powered') is False
    assert [p for p in bridge.graph if p.startswith(ADAPTER + '/dev_')] == []


# covers[consumer]: iface:bluetooth
def test_changes_from_the_desktop_are_android_requests(monkeypatch):
    with contracts.StandIn('bluetooth') as android:
        module, bridge = started(monkeypatch, android)
        # Discovery follows its client's bus name, which a recording connection has none of.
        monkeypatch.setattr(module.Gio, 'bus_watch_name_on_connection', lambda *args: 1)
        monkeypatch.setattr(module.Gio, 'bus_unwatch_name', lambda watch: None)
        V = GLib.Variant
        before = len(android.requests)
        assert bridge.set(None, None, ADAPTER, 'org.bluez.Adapter1', 'Powered', V('b', False)) is True
        assert bridge.set(None, None, ADAPTER, 'org.bluez.Adapter1', 'Alias', V('s', 'My phone')) is True
        calls = {}
        for path, interface, method, args in (
                (ADAPTER, 'org.bluez.Adapter1', 'StartDiscovery', None),
                (module.device_path(BUDS), 'org.bluez.Device1', 'Disconnect', None),
                (module.device_path(BUDS), 'org.bluez.Device1', 'Connect', None),
                (ADAPTER, 'org.bluez.Adapter1', 'RemoveDevice', V('(o)', (module.device_path(BUDS),)))):
            calls[method] = Invocation()
            bridge.call(None, ':1.7', path, interface, method, args, calls[method])
        assert module.GLib.settle(lambda: all(i.value is not None or i.error for i in calls.values()))
        assert all(i.error is None for i in calls.values()), {m: i.error for m, i in calls.items()}
        asked = android.requests[before:]
    changes = [r for r in asked if r.get('action') != 'state']
    assert {'op': 'bluetooth', 'action': 'power', 'on': False} in changes
    assert {'op': 'bluetooth', 'action': 'name', 'name': 'My phone'} in changes
    assert {'op': 'bluetooth', 'action': 'discover', 'on': True} in changes
    assert {'op': 'bluetooth', 'action': 'disconnect', 'address': BUDS} in changes
    assert {'op': 'bluetooth', 'action': 'connect', 'address': BUDS} in changes
    assert {'op': 'bluetooth', 'action': 'unpair', 'address': BUDS} in changes
    assert android.problems == []
