"""rungic_cua.switch (docs/research/91): which session an app runs in, closing and giving back.

Processes are a tiny sleeping program with a workspace's or the user's display in their environment; nothing
graphical starts."""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'agent/computer-use'))


def load(runtime):
    os.environ['XDG_RUNTIME_DIR'] = runtime
    from rungic_cua import switch
    return importlib.reload(switch)


# A program under a name nothing else runs under (sleep may be a multi-call coreutils binary,
# which does not run under another name).
SLEEPER = Path(tempfile.mkdtemp()) / 'rungic-test-sleeper'
if shutil.which('cc'):
    source = SLEEPER.with_suffix('.c')
    source.write_text('#include <unistd.h>\nint main(void) { sleep(60); return 0; }\n')
    subprocess.run(['cc', '-o', str(SLEEPER), str(source)], check=True)
# Like Firefox: the executable ends in "-bin", and it has a helper process of the same program.
BROWSER = SLEEPER.parent / 'rungic-test-browser-bin'
if shutil.which('cc'):
    source = BROWSER.with_suffix('.c')
    source.write_text('#include <unistd.h>\nint main(void) { fork(); sleep(60); return 0; }\n')
    subprocess.run(['cc', '-o', str(BROWSER), str(source)], check=True)
pytestmark = pytest.mark.skipif(not SLEEPER.exists(), reason='no C compiler for the test program')


def sleeper(display):
    env = {**os.environ, 'WAYLAND_DISPLAY': display}
    process = subprocess.Popen([str(SLEEPER), '60'], env=env)
    time.sleep(0.1)
    return process


def test_single_instance_by_program():
    with tempfile.TemporaryDirectory() as runtime:
        switch = load(runtime)
        assert switch.single_instance({'id': 'wechat', 'exec': '/usr/bin/wechat %U'})
        assert switch.single_instance({'id': 'firefox', 'exec': 'firefox --new-window %u'})
        assert not switch.single_instance({'id': 'org.kde.kalk', 'exec': 'kalk'})
        assert not switch.single_instance({'id': 'blender', 'exec': 'blender %f'})


def test_processes_by_session():
    with tempfile.TemporaryDirectory() as runtime:
        switch = load(runtime)
        theirs, ours = sleeper('wayland-0'), sleeper('wayland-ws-7')
        try:
            assert theirs.pid in switch.processes({'rungic-test-sleeper'}, None)
            assert ours.pid not in switch.processes({'rungic-test-sleeper'}, None)
            assert switch.processes({'rungic-test-sleeper'}, 7) == [ours.pid]
            assert switch.processes({'rungic-test-sleeper'}, 6) == []
        finally:
            theirs.kill(); ours.kill(); theirs.wait(); ours.wait()


def test_a_browser_is_found_by_its_name_and_only_its_main_process():
    with tempfile.TemporaryDirectory() as runtime:
        switch = load(runtime)
        env = {**os.environ, 'WAYLAND_DISPLAY': 'wayland-0'}
        process = subprocess.Popen([str(BROWSER)], env=env)
        time.sleep(0.2)
        try:
            assert switch.processes({'rungic-test-browser'}, None) == [process.pid]
        finally:
            subprocess.run(['pkill', '-f', str(BROWSER)])
            process.wait()


def test_close_records_and_restore_gives_back():
    with tempfile.TemporaryDirectory() as runtime:
        switch = load(runtime)
        entry = {'id': 'test.sleeper', 'name': '测试', 'exec': f'{SLEEPER} 60'}
        theirs = sleeper('wayland-0')
        left = switch.close_in_user_session(entry, [theirs.pid])
        theirs.wait(5)
        assert left == []
        assert json.loads(Path(runtime, 'rungic-workspace-switched.json').read_text())['test.sleeper']['name'] == '测试'
        ours = sleeper('wayland-ws-7')      # the app, reopened in the workspace
        with mock.patch.object(switch, 'in_call', return_value=False), \
                mock.patch.object(switch.subprocess, 'Popen') as popen:
            assert switch.restore(7) == ['测试']
        ours.wait(5)
        command = popen.call_args.args[0]
        assert command == ['kstart', '--application', 'test.sleeper']
        assert popen.call_args.kwargs['env'].get('RUNGIC_WORKSPACE') is None
        assert not popen.call_args.kwargs['env'].get('WAYLAND_DISPLAY', '').startswith('wayland-ws-')
        assert switch.switched() == {}


def test_restore_from_inside_a_workspace_opens_on_the_phone():
    """Called with only the workspace's environment (no RUNGIC_USER_*): still the user's session."""
    with tempfile.TemporaryDirectory() as runtime:
        switch = load(runtime)
        Path(runtime, 'rungic-workspace-switched.json').write_text(
            json.dumps({'test.sleeper': {'name': '测试', 'programs': ['rungic-test-sleeper']}}))
        workspace = {'WAYLAND_DISPLAY': 'wayland-ws-1', 'RUNGIC_WORKSPACE': '1', 'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/tmp/x'}
        with mock.patch.dict(os.environ, workspace), mock.patch.object(switch, 'in_call', return_value=False), \
                mock.patch.object(switch.subprocess, 'Popen') as popen:
            os.environ.pop('RUNGIC_USER_WAYLAND_DISPLAY', None)
            switch.restore(1)
        env = popen.call_args.kwargs['env']
        assert env['WAYLAND_DISPLAY'] == 'wayland-0'
        assert env['DBUS_SESSION_BUS_ADDRESS'] == f'unix:path={runtime}/bus'
        assert 'RUNGIC_WORKSPACE' not in env


def test_restore_waits_for_a_call():
    with tempfile.TemporaryDirectory() as runtime:
        switch = load(runtime)
        Path(runtime, 'rungic-workspace-switched.json').write_text(
            json.dumps({'wechat': {'name': '微信', 'programs': ['wechat']}}))
        with mock.patch.object(switch, 'in_call', return_value=True), \
                mock.patch.object(switch.subprocess, 'Popen') as popen:
            assert switch.restore(1) == []
        popen.assert_not_called()
        assert 'wechat' in switch.switched()
