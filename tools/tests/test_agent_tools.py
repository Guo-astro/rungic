"""The agent's diagnostic tools without the phone (docs/55): which MCP tools say they are read-only,
and how ui_tap turns an AT-SPI element without actions into an Android tap."""
import ast
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rungic_agent  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
# Tools that change something: operate controls, switch accessibility, record a trace (it toggles
# KWin's markers and tracefs), install symbols, write an evidence bundle.
CHANGING = {'ui_press', 'ui_tap', 'ui_set_text', 'ui_accessibility', 'trace', 'crash_symbolize', 'snapshot'}


def mcp_tools(monkeypatch):
    """Import the real rungic_agent_mcp with stand-ins for the MCP SDK (and perfetto, used by the
    trace report), recording each tool's annotations as the server would publish them."""
    tools = {}

    class Server:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self, annotations):
            def register(fn):
                tools[fn.__name__] = annotations
                return fn
            return register

    annotations = lambda **hints: types.SimpleNamespace(**hints)
    stand_ins = {'mcp': types.ModuleType('mcp'), 'mcp.server': types.ModuleType('mcp.server'),
                 'mcp.server.mcpserver': types.SimpleNamespace(Image=object, MCPServer=Server),
                 'mcp.types': types.SimpleNamespace(ToolAnnotations=annotations)}
    try:
        import perfetto.trace_processor  # noqa: F401
    except ImportError:
        stand_ins['perfetto'] = types.ModuleType('perfetto')
        stand_ins['perfetto.trace_processor'] = types.SimpleNamespace(TraceProcessor=object, TraceProcessorConfig=object)
    for name, module in stand_ins.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, 'rungic_agent_mcp', raising=False)
    monkeypatch.setattr(sys, 'pycache_prefix', sys.pycache_prefix)     # the server sets its own on import
    import rungic_agent_mcp  # noqa: F401
    return tools


# covers: delivery.agent-diagnostics/E5
def test_read_only_tools_are_marked_and_changes_are_apart(monkeypatch):
    tools = mcp_tools(monkeypatch)
    declared = {node.name for node in ast.parse((ROOT / 'tools/rungic_agent_mcp.py').read_text()).body
                if isinstance(node, ast.FunctionDef) and node.decorator_list}
    assert set(tools) == declared and CHANGING <= declared
    for name, hints in tools.items():
        assert hints.read_only_hint is (name not in CHANGING), name
        assert hints.destructive_hint is False and hints.open_world_hint is False
        assert hints.idempotent_hint is (name not in CHANGING), name
    # The read-only host request refuses the bridge's setters before reaching the phone.
    for op in ('display-set', 'brightness-set', 'network-set'):
        with pytest.raises(ValueError):
            rungic_agent.host_request(op)


# covers: delivery.ui-automation/E3
def test_ui_tap_maps_the_element_centre_to_physical_pixels(monkeypatch):
    """Kalk's keypad draws its own keys (no AT-SPI action): the tap goes to the window origin from KWin
    plus the element's centre in window coordinates, times physical / logical width."""
    answers = {
        ('apps',): [{'name': 'kalk', 'pid': 4242, 'windows': 1}, {'name': 'plasmashell', 'pid': 99, 'windows': 3}],
        ('tree', 'kalk', '--all'): [
            {'path': '0', 'role': 'frame', 'name': 'Kalk', 'extents': [0, 0, 360, 700]},
            {'path': '0/3/7', 'role': 'label', 'name': '7', 'extents': [10, 400, 80, 60]}],
        ('windows',): [
            {'pid': 99, 'x': 0, 'y': 0, 'w': 360, 'h': 40},                 # the panel
            {'pid': 4242, 'x': 0, 'y': 0, 'w': 200, 'h': 100},              # another window of kalk, other size
            {'pid': 4242, 'x': 0, 'y': 40, 'w': 360, 'h': 700}],
    }
    taps = []
    monkeypatch.setattr(rungic_agent, 'a11y', lambda *args, **kw: answers[args])
    monkeypatch.setattr(rungic_agent, 'host_request', lambda op: {'physicalWidth': 1080} if op == 'display-get' else None)
    monkeypatch.setattr(rungic_agent, 'run', lambda script, level='root', **kw: taps.append((script, level)))
    result = rungic_agent.ui_tap('kalk', '0/3/7')
    # centre (50, 430) in the window, window at (0, 40), scale 1080 / 360 = 3
    assert taps == [('input tap 150 1410', 'shell')]
    assert result['tap'] == [150, 1410] and result['scale'] == 3.0

    # An element outside its window is not tapped somewhere else.
    answers[('tree', 'kalk', '--all')][1]['extents'] = [10, 800, 80, 60]
    with pytest.raises(ValueError, match='not on screen'):
        rungic_agent.ui_tap('kalk', '0/3/7')
    assert len(taps) == 1
