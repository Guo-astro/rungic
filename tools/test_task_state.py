"""The task state of an agent turn (plasma/voice-agent/task_state.py, docs/89)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'plasma/voice-agent'))
import task_state as ts  # noqa: E402


def test_commands_read_as_what_they_do():
    assert ts.describe_command("/bin/bash -lc 'blender -b -t 6 --python /home/u/make_donut.py'") == '在后台运行 Blender（make_donut.py）'
    assert ts.describe_command("/bin/bash -lc 'cd /tmp && python3 render.py --fast'") == '运行 Python 脚本 render.py'
    assert ts.describe_command("/bin/bash -lc 'timeout 60 pkcon install-local -y a.deb'") == '安装或查询软件包'
    assert ts.describe_command('/bin/bash -lc "git status --short"') == 'Git status'
    assert ts.describe_command('/bin/bash -lc "sed -n 1,80p x.py"',
                               [{'type': 'read', 'name': 'x.py', 'path': '/h/x.py', 'command': 'sed'}]) == '读取 x.py'
    assert ts.describe_command('whatever-tool --x') == '运行 whatever-tool'


def test_output_gives_the_last_line_and_progress():
    assert ts.last_line('a\nFra:1 Mem:12M | Sample 12/64\r\x1b[2K') == 'Fra:1 Mem:12M | Sample 12/64'
    assert ts.progress_of('Fra:1 Mem:12M | Sample 16/64') == 0.25
    assert ts.progress_of('Downloading  45%|####') == 0.45
    assert ts.progress_of('2026-09-29 12/10 notes') is None


def test_a_turn_with_a_plan():
    state = ts.TurnState(now=100)
    assert state.on_plan([{'step': '写建模脚本', 'status': 'inProgress'}, {'step': '渲染', 'status': 'pending'}])
    assert not state.on_plan([{'step': '写建模脚本', 'status': 'inProgress'}, {'step': '渲染', 'status': 'pending'}])
    state.on_item({'type': 'fileChange', 'id': 'f1', 'changes': [
        {'path': '/h/make.py', 'kind': {'type': 'add'}, 'diff': '+a\n+b\n'}]}, False, now=101)
    assert state.snapshot(now=102)['current']['text'] == '新建 make.py'
    state.on_item({'type': 'fileChange', 'id': 'f1', 'status': 'completed', 'changes': [
        {'path': '/h/make.py', 'kind': {'type': 'add'}, 'diff': '+a\n+b\n'}]}, True, now=103)
    assert state.on_plan([{'step': '写建模脚本', 'status': 'completed'}, {'step': '渲染', 'status': 'inProgress'}])
    state.on_item({'type': 'commandExecution', 'id': 'c1', 'command': "/bin/bash -lc 'blender -b --python /h/make.py'"},
                  False, now=104)
    assert state.on_output('c1', 'Saved\nFra:1 | Sample 32/64\n')
    snap = state.snapshot(now=130)
    assert snap['current'] == {'kind': 'command', 'text': '在后台运行 Blender（make.py）', 'detail': 'Fra:1 | Sample 32/64',
                               'progress': 0.5, 'seconds': 26}
    assert snap['files'] == [{'path': '/h/make.py', 'kind': 'add', 'added': 2, 'removed': 0}]
    facts = state.facts(now=130)
    assert '已完成：写建模脚本' in facts and '进行中：渲染' in facts and '约 50%' in facts
    state.on_item({'type': 'commandExecution', 'id': 'c1', 'exitCode': 1, 'command': 'blender'}, True, now=140)
    assert state.snapshot(now=141)['recent'][-1] == {'kind': 'command', 'text': '运行 Blender', 'ok': False, 'seconds': 36}


def test_commentary_is_an_intention():
    state = ts.TurnState(now=0)
    state.on_commentary('我会做一个甜甜圈，完成后附在回复里。', now=5)
    assert '这是打算，还没做完' in state.facts(now=10)
    assert '打算' not in state.facts(now=100)


def test_screen_captions_follow_the_desktop_tool():
    state = ts.TurnState(now=0)
    assert not state.on_screen('打开“渲染”菜单')          # no desktop tool running
    state.on_item({'type': 'mcpToolCall', 'id': 'm1', 'tool': 'desktop_goal'}, False, now=1)
    assert state.on_screen('打开“渲染”菜单')
    assert '打开“渲染”菜单' in state.facts(now=3)
