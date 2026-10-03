# SPDX-License-Identifier: MIT
"""The Wi-Fi Display contract from the Linux side (quality/contracts/wifi-display.json): the real
desktop/cast/rungic-cast against tools/contracts.py's stand-in of the platform bridge (its status op,
from platform-bridge.json, and op cast). The provider's side is the acceptance scenario
contract.wifi-display on the phone."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import contracts  # noqa: E402

CAST = ROOT / 'desktop/cast/rungic-cast'
STATUS = next(q for q in contracts.load('wifi-display')['queries'] if q['name'] == 'status')['reply']


def cast(bridge, *args):
    done = subprocess.run([sys.executable, str(CAST), *args], capture_output=True, text=True, timeout=30,
                          env=dict(os.environ, RUNGIC_PLATFORM_SOCKET=bridge.path))
    return done.returncode, json.loads(done.stdout)


# covers[consumer]: iface:wifi-display
def test_status_and_connect_go_through_the_app(monkeypatch):
    connected = {**STATUS, 'active_state': 2, 'active': {'name': 'Living Room TV [AA]', 'address': 'aa:bb:cc:dd:ee:ff'}}
    with contracts.StandIn(['wifi-display', 'platform-bridge'], {'connect': connected}) as bridge:
        code, status = cast(bridge, 'status')
        assert code == 0 and status == STATUS
        code, result = cast(bridge, 'connect', 'Living Room TV')
        assert code == 0 and result['active_state'] == 2
        code, _ = cast(bridge, 'scan', '5')
        assert code == 0
        code, _ = cast(bridge, 'disconnect')
        assert code == 0
    casts = [r['args'] for r in bridge.requests if r['op'] == 'cast']
    assert casts == [['status'], ['connect', 'Living Room TV'], ['scan', '5'], ['disconnect']]
    # Each cast command first asks whether the app answers at all (asleep, it would never reply).
    assert [r['op'] for r in bridge.requests] == ['status', 'cast'] * 4
    assert bridge.problems == []


# covers[consumer]: iface:wifi-display
def test_a_host_of_another_protocol_is_not_an_empty_scan(monkeypatch):
    older = {k: v for k, v in STATUS.items() if k != 'protocol_version'}
    with contracts.StandIn(['wifi-display', 'platform-bridge'], {'scan': {**older, 'receivers': []}},
                           keep_contract=False) as bridge:
        code, result = cast(bridge, 'scan')
    assert code == 1 and result['code'] == 'backend-incompatible'


# covers[consumer]: iface:wifi-display
def test_a_missing_casting_component_is_reported_as_such():
    missing = {'error': 'Casting component is not installed', 'code': 'component-missing'}
    with contracts.StandIn(['wifi-display', 'platform-bridge'],
                           handler=lambda name, request: missing if request['op'] == 'cast' else None) as bridge:
        code, result = cast(bridge, 'status')
    assert code == 1 and result == missing


# covers[consumer]: iface:wifi-display
def test_an_app_that_does_not_answer_is_not_waited_for():
    """A frozen app takes connections and never replies (here: answers its status with nothing):
    rungic-cast gives up after its status probe instead of waiting minutes for a cast command."""
    with contracts.StandIn(['wifi-display', 'platform-bridge'],
                           handler=lambda name, request: {} if request['op'] == 'status' else None,
                           keep_contract=False) as bridge:
        code, result = cast(bridge, 'connect')
    assert code == 1 and result['code'] == 'host-unreachable'
    assert [r['op'] for r in bridge.requests] == ['status']
