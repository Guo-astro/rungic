# SPDX-License-Identifier: MIT
"""The assistant's screens on the phone (rungic-agent-screen, docs/58, docs/research/91): one floating
window for one workspace, one director window as soon as a second workspace (or a team's board
beside one) is to be shown. The real script, against a stand-in of the platform bridge
(tools/contracts.py) and stand-ins of what it starts and looks for (systemd-run, pgrep, pkill,
systemctl, kstart): its windows "run" while a line of the fake process table says so. How the
director window lays out its members is Main.qml's (tools/tests/test_agent_screen_window.py)."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import contracts  # noqa: E402

SCRIPT = ROOT / 'agent/screen/rungic-agent-screen'
WINDOW = '/usr/libexec/rungic-agent-screen-window'

# The fake process table: one "pid command line" a line, in $FAKE_PROCS; each fake logs its argv.
FAKES = {
    'pgrep': '''
show = any(a.startswith('-') and 'a' in a for a in args[:-1])
found = [l for l in procs() if re.search(args[-1], l.split(' ', 1)[1])]
for line in found:
    print(line if show else line.split(' ', 1)[0])
sys.exit(0 if found else 1)
''',
    'pkill': '''
keep = [l for l in procs() if not re.search(args[-1], l.split(' ', 1)[1])]
Path(os.environ['FAKE_PROCS']).write_text(''.join(l + '\\n' for l in keep))
''',
    'systemd-run': '''
if WINDOW in args:
    with open(os.environ['FAKE_PROCS'], 'a') as f:
        f.write(f'{1000 + len(procs())} ' + ' '.join(args[args.index(WINDOW):]) + '\\n')
''',
    'systemctl': '',
    'kstart': '',
}
PRELUDE = f'''#!{sys.executable}
import json, os, re, sys
from pathlib import Path
WINDOW = {WINDOW!r}
args = sys.argv[1:]
def procs():
    p = Path(os.environ['FAKE_PROCS'])
    return [l for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps([os.path.basename(sys.argv[0]), args]) + '\\n')
'''


def director_state(members):
    reply = json.loads(json.dumps(contracts.query(contracts.load('platform-bridge'), {'op': 'director'})['reply']))
    reply['members'] = members
    return reply


@pytest.fixture
def phone(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name, body in FAKES.items():
        (bin_dir / name).write_text(PRELUDE + body)
        (bin_dir / name).chmod(0o755)
    (tmp_path / 'run').mkdir()
    env = {'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'XDG_RUNTIME_DIR': str(tmp_path / 'run'),
           'HOME': str(tmp_path / 'home'), 'FAKE_PROCS': str(tmp_path / 'procs'), 'FAKE_LOG': str(tmp_path / 'log')}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv('RUNGIC_WORKSPACE', raising=False)

    class Phone:
        def windows(self, *lines):
            (tmp_path / 'procs').write_text(''.join(f'{100 + i} {WINDOW} {l}\n' for i, l in enumerate(lines)))

        def shown(self):
            text = (tmp_path / 'procs').read_text() if (tmp_path / 'procs').exists() else ''
            return sorted(l.split(' ', 1)[1].removeprefix(WINDOW + ' ') for l in text.splitlines() if l.strip())

        def log(self, name):
            text = (tmp_path / 'log').read_text() if (tmp_path / 'log').exists() else ''
            return [args for n, args in map(json.loads, text.splitlines()) if n == name]

        def script(self, bridge):
            """The script as a module (not desktop mode: argv[0] is not rungic-desktop-mode)."""
            monkeypatch.setenv('RUNGIC_PLATFORM_SOCKET', bridge.path)
            loader = importlib.machinery.SourceFileLoader('rungic_agent_screen', str(SCRIPT))
            module = importlib.util.module_from_spec(importlib.util.spec_from_loader('rungic_agent_screen', loader))
            loader.exec_module(module)
            assert not module.DESKTOP
            return module

        def run(self, bridge, *args):
            done = subprocess.run([str(SCRIPT), *args], capture_output=True, text=True, timeout=30,
                                  env={**os.environ, 'RUNGIC_PLATFORM_SOCKET': bridge.path})
            assert done.returncode == 0, done.stderr
            return json.loads(done.stdout)
    return Phone()


# covers: desktop-mode.director/E1
def test_one_workspace_has_a_floating_window_of_its_own(phone):
    with contracts.StandIn('platform-bridge') as bridge:
        phone.script(bridge).start_window(2)
    assert phone.shown() == ['--workspace 2']
    run = phone.log('systemd-run')[-1]
    assert 'BindsTo=rungic-workspace@2.service' in run, 'closed with its workspace'


# covers: desktop-mode.director/E1
def test_a_second_workspace_turns_the_windows_into_one_director(phone):
    phone.windows('--workspace 2')
    with contracts.StandIn('platform-bridge') as bridge:
        phone.script(bridge).start_window(3)
    assert phone.shown() == ['--director'], 'one director window instead of a window each'
    assert {tuple(a) for a in phone.log('pkill')} >= {('-f', f'^{WINDOW} --workspace 2$'), ('-f', f'^{WINDOW} --workspace 3$')}


# covers: desktop-mode.director/E1
def test_the_director_shows_every_workspace_so_a_third_opens_no_other_window(phone):
    phone.windows('--director')
    with contracts.StandIn('platform-bridge', {'director': director_state([2, 3])}) as bridge:
        phone.script(bridge).start_window(4)
    assert phone.shown() == ['--director']
    assert not phone.log('systemd-run') and not phone.log('pkill')


# covers: desktop-mode.director/E1
def test_a_team_s_board_beside_one_workspace_makes_the_director(phone):
    phone.windows('--workspace 2')
    state = director_state([2, 100])                      # a team's board (Director.BOARD) and workspace 2
    screen = json.loads(json.dumps(contracts.query(contracts.load('platform-bridge'), {'op': 'agent-screen'})['reply']))
    screen.update(enabled=True, workspace=2)
    with contracts.StandIn('platform-bridge', {'director': state, 'agent-screen': screen}) as bridge:
        result = phone.run(bridge, 'team')
    assert result == {'director': True}
    assert phone.shown() == ['--director'], 'the board and one screen are two tiles: the director'
