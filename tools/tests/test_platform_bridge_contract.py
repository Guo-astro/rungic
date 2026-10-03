# SPDX-License-Identifier: MIT
"""The platform bridge's contract from the Linux side (quality/contracts/platform-bridge.json):
consumers run against tools/contracts.py's stand-in, no Android needed. The provider's side is the
acceptance scenario contract.platform-bridge on the phone."""
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import contracts  # noqa: E402

AGENT_SCREEN = ROOT / 'agent/screen/rungic-agent-screen'


def agent_screen(socket_path, monkeypatch, tmp_path, name='rungic-agent-screen'):
    """The rungic-agent-screen script as a module, as `name` (rungic-desktop-mode is a link to it)."""
    monkeypatch.setenv('RUNGIC_PLATFORM_SOCKET', socket_path)
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setattr(sys, 'argv', [f'/usr/bin/{name}'])
    loader = importlib.machinery.SourceFileLoader(f'agent_screen_{name.replace("-", "_")}', str(AGENT_SCREEN))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, 'window_running', lambda slot=None: False)
    monkeypatch.setattr(module, 'windows_shown', lambda: [])
    return module


# covers: delivery.system-tests/E2
def test_the_contract_is_its_own_example():
    contract = contracts.load('platform-bridge')
    names = [q['name'] for q in contract['queries']]
    assert len(names) == len(set(names))
    for q in contract['queries']:
        assert contracts.validate(q['reply'], q['reply']) == []
        assert q['request'] == {'op': q['name']}, 'read-only queries carry no other fields'


# covers: delivery.system-tests/E2
def test_a_stand_in_reply_must_keep_the_contract():
    with pytest.raises(ValueError):
        contracts.StandIn('platform-bridge', {'desktop-mode': {'enabled': 'yes'}})
    assert contracts.validate({'tv': {'shown': []}}, {'tv': {'shown': 3}}) == ['reply.tv.shown: number, not array']


# covers[consumer]: iface:platform-bridge
# covers: delivery.system-tests/E3
def test_the_assistant_screen_status_reads_where_it_is_shown(monkeypatch, tmp_path):
    reply = {**contracts.query(contracts.load('platform-bridge'), {'op': 'agent-screen'})['reply'],
             'enabled': True, 'workspace': 2, 'fullscreen': True}
    with contracts.StandIn('platform-bridge', {'agent-screen': reply}) as bridge:
        module = agent_screen(bridge.path, monkeypatch, tmp_path)
        (tmp_path / 'wayland-ws-2').touch()
        state = module.status()
    assert state['enabled'] and state['shown_on'] == 'phone fullscreen'
    assert state['size'] == '1920x1080' and state['workspace'] == 2 and state['output'] == 'workspace 2'
    assert bridge.requests == [{'op': 'agent-screen'}]


# covers[consumer]: iface:platform-bridge
def test_desktop_mode_asks_the_app_whether_a_tv_shows_it(monkeypatch, tmp_path):
    reply = {**contracts.query(contracts.load('platform-bridge'), {'op': 'desktop-mode'})['reply'], 'tv': True}
    with contracts.StandIn('platform-bridge', {'desktop-mode': reply}) as bridge:
        module = agent_screen(bridge.path, monkeypatch, tmp_path, 'rungic-desktop-mode')
        (tmp_path / 'wayland-ws-0').touch()
        state = module.status()
    assert state['enabled'] and state['shown_on'] == 'tv'
    assert bridge.requests == [{'op': 'desktop-mode'}]


# covers[consumer]: iface:platform-bridge
def test_an_error_reply_is_an_error_not_a_state(monkeypatch, tmp_path):
    with contracts.StandIn('platform-bridge') as bridge:
        module = agent_screen(bridge.path, monkeypatch, tmp_path)
        with pytest.raises(SystemExit) as stopped:
            module.bridge({'op': 'no-such-op'})
    assert 'error' in str(stopped.value)


def test_no_bridge_is_no_tv(monkeypatch, tmp_path):
    module = agent_screen(str(tmp_path / 'absent.sock'), monkeypatch, tmp_path, 'rungic-desktop-mode')
    assert module.desktop_tv() is False
