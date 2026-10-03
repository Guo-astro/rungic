# SPDX-License-Identifier: MIT
"""Voice messages spoken by the assistant (rungic_cua.server, docs/62): the speech plays into the
Linux microphone only once rungic-audio-route reports the app's recording stream moved there; when
it does not come within the wait, nothing is spoken and the recording that was started is cancelled,
so what the real microphone recorded is never sent. Both plans: atspi (named controls) and luna (the
model presses the controls). rungic-audio-route and pacat are stand-ins on PATH; the app is a stand-in
backend that records the controls pressed."""
import os
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'agent/computer-use'))
# Libraries of the computer-use stack that this does not reach (the JEV executor, pinyin names), as
# stand-ins only while the server loads. The rungic_cua modules it loads stay: other tests use them.
STUBS = {name: mock.MagicMock() for name in ('arc_cua', 'arc_cua.policies', 'arc_cua.errors', 'arc_cua.keyboard',
                                             'arc_cua.models', 'pypinyin') if name not in sys.modules}
sys.modules.update(STUBS)
try:
    from rungic_cua import server
finally:
    for name in STUBS:
        sys.modules.pop(name, None)


ROUTER = '''#!{python}
import os, sys, time
print('ready', flush=True)
if os.environ.get('FAKE_ROUTED'):
    time.sleep(0.3)
    print('routed source-output 7 android_microphone -> linux_microphone', flush=True)
sys.stdin.read()          # until the caller closes the pipe: the routing ends
'''
PACAT = '''#!{python}
import os, sys
open(os.environ['FAKE_SPOKEN'], 'ab').write(sys.stdin.buffer.read())
'''


@pytest.fixture
def tools(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name, text in (('rungic-audio-route', ROUTER), ('pacat', PACAT)):
        (bin_dir / name).write_text(textwrap.dedent(text).format(python=sys.executable))
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv('PATH', f'{bin_dir}:{os.environ["PATH"]}')
    monkeypatch.setenv('FAKE_SPOKEN', str(tmp_path / 'spoken.pcm'))
    monkeypatch.setattr(server.speech, 'synthesize', lambda text, voice=None: b'\x01\x00' * 2400)
    monkeypatch.setattr(server.time, 'sleep', lambda seconds: None)
    return tmp_path


class App:
    """The chat app's window as the atspi backend sees it: its controls and the presses on them."""

    def __init__(self):
        self.pressed = []
        names = ('Send Voice', 'Send voice message', 'Cancel')
        self._nodes = {i: name for i, name in enumerate(names)}
        self._window = {'pid': os.getpid()}
        self._root = None
        self.input = SimpleNamespace(click=lambda x, y: self.pressed.append(('click', self._nodes[x])),
                                     press=lambda x, y: self.pressed.append(('press', self._nodes[x])),
                                     release=lambda: self.pressed.append(('release',)))

    def observe(self):
        return SimpleNamespace(window='Chat', elements=[SimpleNamespace(id=i, name=n) for i, n in self._nodes.items()])

    def _global_center(self, name):
        return next(i for i, n in self._nodes.items() if n == name), 0


def cua_with(app):
    cua = server.Cua()
    cua._backend = app
    return cua


# covers: apps.virtual-audio/E5
def test_not_routed_in_time_nothing_is_spoken_and_the_recording_is_cancelled(tools):
    app = App()
    with pytest.raises(RuntimeError, match='did not start recording through the Linux microphone'):
        cua_with(app).voice_message({'text': 'hello', 'start': 'Send Voice', 'finish': 'Send voice message'})
    assert app.pressed == [('click', 'Send Voice'), ('click', 'Cancel')]
    assert not (tools / 'spoken.pcm').exists()


# covers: apps.virtual-audio/E5
def test_routed_the_speech_goes_into_the_linux_microphone_and_is_sent(tools, monkeypatch):
    monkeypatch.setenv('FAKE_ROUTED', '1')
    app = App()
    result = cua_with(app).voice_message({'text': 'hello', 'start': 'Send Voice', 'finish': 'Send voice message'})
    assert result['sent'] and app.pressed == [('click', 'Send Voice'), ('click', 'Send voice message')]
    assert (tools / 'spoken.pcm').read_bytes() == b'\x01\x00' * 2400


class Model:
    """luna's ComputerUse: the model presses whatever the instruction says; here it only records them."""
    runs = []

    def __init__(self, backend, output, window):
        pass

    def run(self, instruction, **kwargs):
        Model.runs.append(instruction)
        return {'outcome': 'done', 'steps': []}


# covers: apps.virtual-audio/E5
def test_luna_not_routed_in_time_nothing_is_spoken_and_the_recording_is_cancelled(tools, monkeypatch):
    Model.runs = []
    monkeypatch.setattr(server, 'ComputerUse', Model)
    cua = server.Cua()
    cua._backend = SimpleNamespace(kwin=SimpleNamespace(
        windows=lambda: {'active': {'pid': os.getpid(), 'output': 'CAST-1', 'id': 'w1'}}))
    monkeypatch.setattr(cua, 'agent_output', lambda: 'CAST-1')
    result = cua.voice_message_luna({'text': 'hello'})
    assert result['sent'] is False and 'nothing was spoken' in result['note']
    assert len(Model.runs) == 2 and 'start recording' in Model.runs[0]
    assert 'Cancel it without sending' in Model.runs[1]
    assert not (tools / 'spoken.pcm').exists()
