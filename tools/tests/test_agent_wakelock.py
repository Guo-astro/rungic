"""rungic-agent-wakelock: awake while an agent works (docs/research/97 §12)."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'agent/workspace/rungic-agent-wakelock'


def load(runtime):
    os.environ['RUNGIC_WAKELOCK_RUNTIME'] = str(runtime)
    loader = importlib.machinery.SourceFileLoader('agent_wakelock', str(SCRIPT))
    spec = importlib.util.spec_from_loader('agent_wakelock', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# covers: agent.keep-awake/E1
def test_only_live_holders_keep_it_awake(tmp_path):
    user = tmp_path / '1000'
    user.mkdir()
    w = load(tmp_path)
    assert w.busy() == []
    (user / 'rungic-workspace-2.busy').write_text(json.dumps({'pid': os.getpid(), 'thread': 't'}))
    (user / 'rungic-workspace-3.busy').write_text(json.dumps({'pid': 2**22 + 12345}))   # gone
    (user / 'rungic-agent.busy').write_text('not json')
    assert w.busy() == ['rungic-workspace-2.busy']
    (user / 'rungic-agent.busy').write_text(json.dumps({'pid': os.getpid()}))
    assert sorted(w.busy()) == ['rungic-agent.busy', 'rungic-workspace-2.busy']
