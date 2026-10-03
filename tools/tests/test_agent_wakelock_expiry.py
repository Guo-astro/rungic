"""rungic-agent-wakelock ends on its own (docs/research/97 §12): the real service loop, with the kernel's
wake_lock files in a temporary directory. Every lock it takes carries the 60 s timeout and is renewed
while the agent works; when the service dies without unlocking (SIGKILL, a crash), the last lock it wrote
still expires. That the kernel honours the timeout is Android's; what the service writes is checked here."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'agent/workspace/rungic-agent-wakelock'


class Killed(BaseException):
    """The service process ends here, without its SIGTERM handler (like SIGKILL)."""


def load(runtime):
    os.environ['RUNGIC_WAKELOCK_RUNTIME'] = str(runtime)
    loader = importlib.machinery.SourceFileLoader('agent_wakelock_expiry', str(SCRIPT))
    spec = importlib.util.spec_from_loader('agent_wakelock_expiry', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# covers: agent.keep-awake/E2
def test_every_lock_expires_by_itself_within_60_seconds(tmp_path, monkeypatch):
    user = tmp_path / 'run/1000'
    user.mkdir(parents=True)
    w = load(tmp_path / 'run')
    kernel = tmp_path / 'sys'
    kernel.mkdir()
    writes = []

    def write(path, value):
        writes.append((Path(path).name, value))
        (kernel / Path(path).name).write_text(value)
        return True
    monkeypatch.setattr(w, 'LOCK', str(kernel / 'wake_lock'))
    monkeypatch.setattr(w, 'UNLOCK', str(kernel / 'wake_unlock'))
    monkeypatch.setattr(w, 'write', write)
    monkeypatch.setattr(w.signal, 'signal', lambda *a: None)
    marker = user / 'rungic-agent.busy'
    marker.write_text(json.dumps({'pid': os.getpid()}))
    ticks = []

    def sleep(seconds):
        ticks.append(seconds)
        if len(ticks) == 4:
            raise Killed                          # the service dies mid-work, nothing unlocks
    monkeypatch.setattr(w.time, 'sleep', sleep)
    with pytest.raises(Killed):
        w.main()
    assert writes == [('wake_lock', 'rungic_agent 60000000000')] * 4, 'renewed every tick, each with its timeout'
    assert all(s == w.EVERY_S for s in ticks) and w.EVERY_S < 60
    assert not (kernel / 'wake_unlock').exists()
    # What the kernel holds after the crash is a timed lock: name and nanoseconds, at most 60 s.
    name, timeout = (kernel / 'wake_lock').read_text().split()
    assert name == 'rungic_agent' and int(timeout) <= 60 * 10**9


# covers: agent.keep-awake/E2
def test_released_as_soon_as_no_agent_works(tmp_path, monkeypatch):
    user = tmp_path / 'run/1000'
    user.mkdir(parents=True)
    w = load(tmp_path / 'run')
    writes = []
    monkeypatch.setattr(w, 'write', lambda path, value: writes.append((path, value)) or True)
    monkeypatch.setattr(w.signal, 'signal', lambda *a: None)
    marker = user / 'rungic-workspace-2.busy'
    marker.write_text(json.dumps({'pid': os.getpid()}))
    ticks = []

    def sleep(seconds):
        ticks.append(seconds)
        if len(ticks) == 1:
            marker.unlink()
        if len(ticks) == 3:
            raise Killed
    monkeypatch.setattr(w.time, 'sleep', sleep)
    with pytest.raises(Killed):
        w.main()
    assert writes == [(w.LOCK, 'rungic_agent 60000000000'), (w.UNLOCK, 'rungic_agent')]
