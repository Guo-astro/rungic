#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The development agents' diagnostics (tools/rungic_agent_mcp.py, docs/55) without a phone: the MCP
server's tools as declared, the choice of phone among several adb servers and devices (a stand-in adb
on PATH, never the real one), and the merged log timeline from canned Android, container and kernel
output. tools/conftest.py fails a test that reaches the device layer."""
import json
import os
from pathlib import Path
import stat
import sys
import types
from unittest.mock import patch

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import rungic_agent  # noqa: E402
import rungic_device  # noqa: E402


# ---- the MCP server's tools ------------------------------------------------------------------
class FakeServer:
    """mcp.server.mcpserver.MCPServer as far as the module uses it: tools and their annotations."""

    def __init__(self, name, instructions=''):
        self.tools = {}

    def tool(self, annotations):
        def register(function):
            self.tools[function.__name__] = (function, annotations)
            return function
        return register

    def run(self, transport):
        pass


def load_server():
    mcp = types.ModuleType('mcp')
    server = types.ModuleType('mcp.server')
    mcpserver = types.ModuleType('mcp.server.mcpserver')
    mcpserver.MCPServer = FakeServer
    mcpserver.Image = lambda data, format: ('image', format)
    mcp_types = types.ModuleType('mcp.types')
    mcp_types.ToolAnnotations = lambda **hints: types.SimpleNamespace(**hints)
    perfetto = types.ModuleType('perfetto')
    processor = types.ModuleType('perfetto.trace_processor')
    processor.TraceProcessor = processor.TraceProcessorConfig = object
    modules = {'mcp': mcp, 'mcp.server': server, 'mcp.server.mcpserver': mcpserver, 'mcp.types': mcp_types,
               'perfetto': perfetto, 'perfetto.trace_processor': processor}
    with patch.dict(sys.modules, modules):
        sys.modules.pop('rungic_agent_mcp', None)
        import rungic_agent_mcp
        sys.modules.pop('rungic_agent_mcp', None)
    return rungic_agent_mcp


# Library calls that change the phone or the container.
CHANGES = {'ui_enable', 'ui_press', 'ui_tap', 'crash_symbolize', 'capture', 'swipes'}
A11Y_CHANGES = {'enable', 'disable', 'act', 'text'}


class Recorder:
    """A library module whose functions record their calls and answer as the real ones would."""

    def __init__(self, calls, answers):
        self.calls, self.answers = calls, answers

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args))
            answer = self.answers.get(name, {})
            return answer(*args) if callable(answer) else answer
        return call


# covers: agent.dev-diagnostics/E1
def test_the_tools_say_which_change_the_device_and_the_read_only_ones_change_nothing(tmp_path):
    module = load_server()
    tools = module.server.tools
    assert len(tools) == 21
    acting = {name for name, (_, hints) in tools.items() if not hints.read_only_hint}
    # Symbolizing installs packages, the UI tools press, type and switch accessibility, a trace captures
    # (and swipes); the evidence bundle writes on this computer only.
    assert {'crash_symbolize', 'ui_press', 'ui_tap', 'ui_set_text', 'ui_accessibility', 'trace'} <= acting
    for name in ('crash_symbolize', 'trace', 'ui_accessibility'):
        assert tools[name][0].__doc__.strip(), name
    assert 'Installs packages in the container' in ' '.join(tools['crash_symbolize'][0].__doc__.split())
    calls = []
    picture = tmp_path / 'screen.png'
    from PIL import Image
    Image.new('RGB', (10, 20)).save(picture)

    def a11y(*args, timeout=120):
        calls.append(('a11y', args))
        return {'state': {'enabled': False}, 'apps': [], 'windows': [], 'find': []}.get(args[0], {})
    library = Recorder(calls, {'logs': {'entries': [], 'total': 0, 'truncated': 0, 'suppressed_noise': {}},
                               'format_entries': '', 'integrity': {'summary': {}}, 'screenshot': str(picture),
                               'session_log': '', 'crash_get': '', 'kwin_info': '',
                               'a11y': lambda *args: a11y(*args), 'ui_windows': lambda: a11y('windows'),
                               'ui_enable': lambda enabled=True: a11y('enable' if enabled else 'disable'),
                               'ui_find': lambda *args: rungic_agent.ui_find(*args)})
    arguments = {'crash_detail': ('tombstone_1',), 'host_request': ('status',), 'ui_find': ('kalk',),
                 'build_status': ('kwin',), 'trace_report': (str(tmp_path / 'x.pftrace'),)}
    with patch.object(module, 'rungic_agent', library), patch.object(rungic_agent, 'a11y', a11y), \
            patch.object(rungic_agent.time, 'sleep', lambda s: None), \
            patch.object(module, 'build_on_device', Recorder(calls, {'status': ''})), \
            patch.object(module, 'rungic_trace', Recorder(calls, {})), \
            patch.object(module, 'rungic_trace_report', Recorder(calls, {})):
        for name, (function, hints) in tools.items():
            if not hints.read_only_hint:
                continue
            calls.clear()
            function(*arguments.get(name, ()))
            changed = [c for c in calls if c[0] in CHANGES or (c[0] == 'a11y' and c[1][0] in A11Y_CHANGES)]
            assert changed == [], f'{name} is marked read-only but {changed}'


# ---- one phone among several adb servers and devices --------------------------------------------
@pytest.fixture
def adb(tmp_path, monkeypatch):
    """A stand-in adb: three devices on this server (the tools' old default serial among them); each
    call is logged with the adb server port it was given."""
    log = tmp_path / 'adb.log'
    fake = tmp_path / 'adb'
    fake.write_text(f'''#!/bin/sh
echo "port=${{ANDROID_ADB_SERVER_PORT:-5037}} $*" >> {log}
case "$*" in
  devices) printf 'List of devices attached\\nZY32MVJS25\\tdevice\\n192.168.5.20:41234\\tdevice\\nemulator-5554\\toffline\\n' ;;
  "-s 192.168.5.20:41234 shell getprop ro.serialno") echo ZY32WANTED ;;
  *getprop*) echo OTHER ;;
esac
''')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    for name in ('RUNGIC_ADB', 'RUNGIC_SERIAL', 'RUNGIC_TRANSPORT', 'MOTO_ADB', 'MOTO_SERIAL', 'MOTO_TRANSPORT'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(rungic_device, 'WORKSPACE', tmp_path)       # no .work/device.env of this computer
    monkeypatch.setenv('RUNGIC_ADB', str(fake))
    # The guard (tools/conftest.py) refuses adb_path; here adb is the fake above, in RUNGIC_ADB.
    monkeypatch.setattr(rungic_device, 'adb_path', rungic_device._unguarded_adb_path)
    monkeypatch.setenv('ANDROID_ADB_SERVER_PORT', '5038')

    def fresh():
        for cached in (rungic_device.config, rungic_device.adb_path, rungic_device.transport):
            cached.cache_clear()
    fresh()
    yield types.SimpleNamespace(path=str(fake), log=log, fresh=fresh)
    fresh()


# covers: agent.dev-diagnostics/E2
def test_the_configured_phone_not_the_old_default(adb, monkeypatch):
    monkeypatch.setenv('RUNGIC_SERIAL', 'ZY32WANTED')
    adb.fresh()
    assert rungic_device.transport() == '192.168.5.20:41234'
    assert rungic_device.adb('shell', 'id') == [adb.path, '-s', '192.168.5.20:41234', 'shell', 'id']
    calls = adb.log.read_text().splitlines()
    assert calls and all(line.startswith('port=5038 ') for line in calls), calls    # the configured adb server only
    # The old default phone is only asked for its serial, never used.
    assert not any('-s ZY32MVJS25' in line and 'getprop ro.serialno' not in line for line in calls)


# covers: agent.dev-diagnostics/E2
def test_a_configured_phone_that_is_not_there_is_an_error_not_another_phone(adb, monkeypatch):
    monkeypatch.setenv('RUNGIC_SERIAL', 'ZY32ABSENT')
    adb.fresh()
    with pytest.raises(rungic_device.DeviceError, match='ZY32ABSENT not among adb devices'):
        rungic_device.transport()


# covers: agent.dev-diagnostics/E2
def test_a_configured_transport_is_used_as_is(adb, monkeypatch, tmp_path):
    (tmp_path / '.work').mkdir()
    (tmp_path / '.work/device.env').write_text('RUNGIC_TRANSPORT=10.77.0.16:44995\nRUNGIC_SERIAL=ZY32WANTED\n')
    adb.fresh()
    assert rungic_device.adb('shell') == [adb.path, '-s', '10.77.0.16:44995', 'shell']
    assert not adb.log.exists(), 'no device listing, no other phone asked'
    monkeypatch.setenv('RUNGIC_TRANSPORT', '10.77.0.17:5555')     # the environment wins over the file
    adb.fresh()
    assert rungic_device.transport() == '10.77.0.17:5555'


# ---- one timeline ------------------------------------------------------------------------------
# covers: agent.dev-diagnostics/E4
def test_android_container_and_kernel_logs_on_one_clock(monkeypatch):
    now = 1_000_000.0

    def out(script, level='root', timeout=60):
        if script == 'date +%s.%N':
            return f'{now}\n'
        if script.lstrip().startswith('logcat'):
            return ('  999950.100  10234  4001  4010 E RungicWayland: buffer import failed\n'
                    '  999970.000  10234  4001  4010 I RungicPlasma: frame presented\n')
        if 'dmesg' in script:
            # The kernel's clock is monotonic: sampled with the wall clock in the same script.
            return f'real={now}\nnow at 500000000000 nsecs\n<3>[460.050000] kgsl: page fault\n<6>[465.000000] wlan: scan\n'
        raise AssertionError(script)

    class Journal:
        stdout = '\n'.join(json.dumps(e) for e in (
            {'__REALTIME_TIMESTAMP': str(int(999955.5e6)), 'PRIORITY': '3', 'SYSLOG_IDENTIFIER': 'kwin_wayland',
             '_PID': '812', 'MESSAGE': 'GPU reset'},
            {'__REALTIME_TIMESTAMP': str(int(999965.25e6)), 'PRIORITY': '6', 'SYSLOG_IDENTIFIER': 'plasmashell',
             '_PID': '901', 'MESSAGE': 'ready'}))
    monkeypatch.setattr(rungic_agent, 'out', out)
    monkeypatch.setattr(rungic_agent, 'run', lambda script, level='root', timeout=60, check=True: Journal)
    monkeypatch.setattr(rungic_agent, 'package_uid', lambda: 10234)
    result = rungic_agent.logs(since_seconds=120)
    timeline = [(e['src'], e['t'], e['msg']) for e in result['entries']]
    assert timeline == [
        ('logcat', 999950.1, 'buffer import failed'),
        ('journal', 999955.5, 'GPU reset'),
        ('kernel', pytest.approx(999960.05), 'kgsl: page fault'),       # 500 s of uptime before `now`
        ('journal', 999965.25, 'ready'),
        ('logcat', 999970.0, 'frame presented'),
    ]
    # Wall-clock order across the three sources; scope 'plasma' keeps the GPU's kernel lines only.
    assert [t for _, t, _ in timeline] == sorted(t for _, t, _ in timeline)
