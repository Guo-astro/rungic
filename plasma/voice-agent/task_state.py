# SPDX-License-Identifier: MIT
"""What an agent turn is doing, in words people read (docs/89).

One TurnState per Codex turn, fed from the app-server's notifications:

  turn/plan/updated                    the plan Codex keeps (update_plan): steps and their status
  item/started, item/completed         commands (with Codex's own parse, commandActions), file
                                       changes, tool calls, web searches (reasoning is not a step)
  item/commandExecution/outputDelta    a running command's output: its last line and progress
  item/fileChange/patchUpdated         files being written, with lines added and removed
  the assistant's screen's caption     rungic_cua.activity (docs/88), for desktop work; with a live
                                       picture (a Blender render's latest pass, docs/90) the card
                                       shows it and refreshes it as passes come
  agentMessage (commentary)            Codex's own words about what it is about to do

snapshot() is what the chat shows (the task card); facts() is what the voice may say, in tenses
it cannot confuse: done, now, next. Nothing here talks to anyone; the voice agent decides when.
"""
from __future__ import annotations

import os
import re
import shlex
import time

ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07')
PERCENT = re.compile(r'(?<![\d.])(\d{1,3}(?:\.\d+)?)\s?%')
COUNTED = re.compile(r'(?i)\b(sample|tile|frame|step|chunk|file|item|part|epoch|batch)s?\b\D{0,4}(\d+)\s*/\s*(\d+)')
SHELL = re.compile(r"^/bin/(?:ba)?sh -lc (['\"])([\s\S]*)\1$")

# Programs by what they do for the user. The first match of the command's program wins.
PROGRAMS = [
    ({'blender'}, '运行 Blender'),
    ({'pkcon', 'apt', 'apt-get', 'dpkg', 'aptitude'}, '安装或查询软件包'),
    ({'flatpak'}, '安装或管理 Flatpak 应用'),
    ({'pip', 'pip3', 'uv', 'pipx'}, '安装 Python 包'),
    ({'npm', 'pnpm', 'yarn', 'npx', 'node'}, '运行 Node.js'),
    ({'make', 'cmake', 'ninja', 'cargo', 'gcc', 'g++', 'clang', 'meson', 'go'}, '编译'),
    ({'git'}, 'Git'),
    ({'curl', 'wget', 'aria2c'}, '访问网络'),
    ({'ffmpeg', 'ffprobe'}, '处理音视频'),
    ({'convert', 'magick', 'identify'}, '处理图片'),
    ({'spectacle', 'rungic-screenshot'}, '截图'),
    ({'rungic-cast'}, '投屏'),
    ({'rungic-platform'}, '调用手机功能'),
    ({'rungic-agent-screen'}, '开关助理屏'),
    ({'rungic-cua'}, '操作桌面'),
    ({'journalctl', 'dmesg', 'coredumpctl'}, '查看日志'),
    ({'systemctl'}, '查看或管理系统服务'),
    ({'df', 'du', 'free', 'upower', 'lscpu', 'uptime'}, '查看设备状态'),
    ({'ls', 'find', 'fd', 'tree'}, '查找文件'),
    ({'cat', 'head', 'tail', 'less', 'bat', 'nl', 'wc'}, '查看文件'),
    ({'grep', 'rg', 'ag'}, '搜索文本'),
    ({'file', 'stat', 'sha256sum', 'md5sum'}, '检查文件'),
    ({'rm', 'rmdir', 'trash', 'gio'}, '删除或整理文件'),
    ({'cp', 'mv', 'mkdir', 'ln', 'touch', 'tar', 'unzip', 'zip'}, '整理文件'),
    ({'sleep'}, '等待'),
    ({'kill', 'pkill', 'killall'}, '结束进程'),
]
PYTHON = {'python', 'python3'}
SHELL_WORDS = {'cd', 'export', 'set', 'source', '.', 'env', 'sudo', 'nice', 'timeout', 'time', 'nohup', 'exec'}


def unwrap(command: str) -> str:
    """The command without the shell wrapper Codex adds."""
    match = SHELL.match(command.strip())
    return match.group(2) if match else command.strip()


def first_program(command: str) -> tuple[str, list[str]]:
    """The first real program of a command line and its arguments (after cd, env, &&, pipes)."""
    for part in re.split(r'&&|\|\||;|\|', command):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        while words and (words[0] in SHELL_WORDS or '=' in words[0] or words[0].startswith('-')
                         or re.fullmatch(r'\d+[smh]?', words[0])):
            if words[0] == 'cd':
                words = []
                break
            words = words[1:]
        if words:
            return os.path.basename(words[0]), words[1:]
    return '', []


def describe_command(command: str, actions: list | None = None) -> str:
    """What a command does, in a few words of Simplified Chinese."""
    for action in actions or []:
        kind = action.get('type')
        if kind == 'read':
            return f"读取 {action.get('name') or os.path.basename(str(action.get('path') or ''))}"
        if kind == 'listFiles':
            path = action.get('path')
            return f'查看 {os.path.basename(str(path).rstrip("/")) or path} 里的文件' if path else '查看文件列表'
        if kind == 'search':
            query = action.get('query')
            return f'搜索“{query}”' if query else '搜索文件'
    program, args = first_program(unwrap(command))
    if program in PYTHON:
        script = next((a for a in args if a.endswith('.py')), '')
        if '-m' in args and args.index('-m') + 1 < len(args):
            return f"运行 Python 模块 {args[args.index('-m') + 1]}"
        return f'运行 Python 脚本 {os.path.basename(script)}' if script else '运行 Python'
    if program == 'blender':
        script = next((a for a in args if a.endswith('.py')), '')
        background = '-b' in args or '--background' in args
        what = '在后台运行 Blender' if background else '运行 Blender'
        return f'{what}（{os.path.basename(script)}）' if script else what
    if program == 'git' and args:
        return f'Git {args[0]}'
    for names, text in PROGRAMS:
        if program in names:
            return text
    return f'运行 {program}' if program else '运行命令'


def last_line(text: str) -> str:
    """The last non-empty line of terminal output (carriage returns redraw a line)."""
    text = ANSI.sub('', text)
    for line in reversed(re.split(r'[\r\n]+', text)):
        line = ' '.join(line.split())
        if line:
            return line[:160]
    return ''


def progress_of(line: str) -> float | None:
    """A fraction done, when the line says so plainly (a percentage, or "Sample 12/64")."""
    counted = COUNTED.search(line)
    if counted and int(counted.group(3)) > 0:
        return min(1.0, int(counted.group(2)) / int(counted.group(3)))
    percent = PERCENT.search(line)
    if percent and float(percent.group(1)) <= 100:
        return float(percent.group(1)) / 100
    return None


def count_lines(diff: str) -> tuple[int, int]:
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith('+') and not line.startswith('+++'):
            added += 1
        elif line.startswith('-') and not line.startswith('---'):
            removed += 1
    return added, removed


def describe_files(changes: list) -> tuple[str, list[dict]]:
    files = []
    for change in changes or []:
        kind = (change.get('kind') or {}).get('type', 'update')
        added, removed = count_lines(change.get('diff') or '')
        files.append({'path': change.get('path', ''), 'kind': kind, 'added': added, 'removed': removed})
    if not files:
        return '修改文件', files
    verb = {'add': '新建', 'delete': '删除'}.get(files[0]['kind'], '修改')
    name = os.path.basename(files[0]['path'])
    return (f'{verb} {name}' if len(files) == 1 else f'{verb} {name} 等 {len(files)} 个文件'), files


class TurnState:
    """One agent turn, as the task card and the voice see it."""

    RECENT = 12      # finished activities kept for the card

    def __init__(self, now: float | None = None) -> None:
        self.started = now if now is not None else time.time()
        self.plan: list[dict] = []           # [{'step', 'status': pending|inProgress|completed}]
        self.explanation = ''
        self.current: dict | None = None     # {'id', 'kind', 'text', 'detail', 'progress', 'since'}
        self.recent: list[dict] = []         # finished activities, newest last: {'kind', 'text', 'ok', 'seconds'}
        self.files: dict[str, dict] = {}     # path -> {'kind', 'added', 'removed'} over the turn
        self.intent = ''                     # Codex's latest commentary: an intention, not a result
        self.intent_at = 0.0
        self.output: dict[str, str] = {}     # item id -> recent output text (tail)
        self.preview: dict | None = None     # {'image', 'text', 'progress', 'done'}: a live picture

    # ---- inputs --------------------------------------------------------------------------
    def on_plan(self, plan: list, explanation: str | None = None) -> bool:
        """Codex's plan changed. True when the step in progress is a different one."""
        before = self.step_now()
        self.plan = [{'step': str(p.get('step', '')), 'status': str(p.get('status', 'pending'))} for p in plan or []]
        if explanation:
            self.explanation = explanation
        return self.step_now() != before

    def on_item(self, item: dict, completed: bool, now: float | None = None) -> bool:
        """An item started or finished. True when the card should change."""
        now = now if now is not None else time.time()
        kind = item.get('type')
        item_id = item.get('id', '')
        if kind == 'commandExecution':
            text, activity = describe_command(item.get('command', ''), item.get('commandActions')), 'command'
        elif kind == 'fileChange':
            text, files = describe_files(item.get('changes'))
            activity = 'files'
            if completed:
                for f in files:
                    total = self.files.setdefault(f['path'], {'kind': f['kind'], 'added': 0, 'removed': 0})
                    total['added'] += f['added']
                    total['removed'] += f['removed']
        elif kind == 'mcpToolCall':
            tool = item.get('tool', '')
            text = '在助理屏上操作' if tool.startswith('desktop_') else f'使用工具 {tool}'
            activity = 'screen' if tool.startswith('desktop_') else 'tool'
        elif kind == 'webSearch':
            query = item.get('query') or ''
            text, activity = (f'上网搜索“{query}”' if query else '上网搜索'), 'search'
        elif kind == 'imageView':
            text, activity = f"查看图片 {os.path.basename(item.get('path') or '')}".strip(), 'look'
        elif kind == 'imageGeneration':
            text, activity = '生成图片', 'image'
        elif kind == 'sleep':
            text, activity = '等待', 'wait'
        else:
            return False
        # Reasoning is not a step: between steps the card says it is thinking by itself.
        if not completed:
            self.current = {'id': item_id, 'kind': activity, 'text': text, 'detail': '', 'progress': None, 'since': now}
            return True
        seconds = round(now - self.current['since']) if self.current and self.current.get('id') == item_id else 0
        ok = not (kind == 'commandExecution' and item.get('exitCode') not in (None, 0))
        self.recent.append({'kind': activity, 'text': text, 'ok': ok, 'seconds': seconds})
        self.recent = self.recent[-self.RECENT:]
        if self.current and self.current.get('id') == item_id:
            self.current = None
        self.output.pop(item_id, None)
        return True

    def on_output(self, item_id: str, delta: str) -> bool:
        """Output of the running command. True when what the card shows changed."""
        tail = (self.output.get(item_id, '') + delta)[-4000:]
        self.output[item_id] = tail
        if not self.current or self.current.get('id') != item_id:
            return False
        line = last_line(tail)
        progress = progress_of(line)
        if progress is None and self.current.get('progress') is not None:
            progress = self.current['progress']       # keep the last known fraction
        changed = line != self.current.get('detail') or progress != self.current.get('progress')
        self.current['detail'] = line
        self.current['progress'] = progress
        return changed

    def on_patch(self, item_id: str, changes: list) -> bool:
        text, files = describe_files(changes)
        if self.current and self.current.get('id') == item_id:
            added = sum(f['added'] for f in files)
            removed = sum(f['removed'] for f in files)
            self.current['text'] = text
            self.current['detail'] = f'+{added} −{removed} 行' if added or removed else ''
            return True
        return False

    def on_screen(self, caption: str) -> bool:
        """The assistant's screen's caption (rungic_cua.activity) while a desktop tool runs."""
        if not self.current or self.current.get('kind') != 'screen' or not caption:
            return False
        if self.current.get('detail') == caption:
            return False
        self.current['detail'] = caption
        return True

    def on_live(self, report: dict) -> bool:
        """A report with a picture on the activity channel (rungic_cua.activity), written during
        this turn: the card shows the latest one."""
        if not report.get('image') or float(report.get('time') or 0) < self.started:
            return False
        preview = {'image': report['image'], 'text': report.get('text', ''), 'progress': report.get('progress'),
                   'done': report.get('state') == 'done'}
        if preview == self.preview:
            return False
        self.preview = preview
        return True

    def on_commentary(self, text: str, now: float | None = None) -> None:
        self.intent = ' '.join(text.split())[:200]
        self.intent_at = now if now is not None else time.time()

    # ---- outputs -------------------------------------------------------------------------
    def step_now(self) -> str:
        return next((p['step'] for p in self.plan if p['status'] == 'inProgress'), '')

    def snapshot(self, now: float | None = None) -> dict:
        """The task card: plan, what is happening now, what was done, files touched."""
        now = now if now is not None else time.time()
        current = dict(self.current) if self.current else None
        if current:
            current['seconds'] = round(now - current.pop('since'))
            current.pop('id', None)
        return {'plan': self.plan, 'explanation': self.explanation, 'current': current,
                'recent': self.recent[-6:], 'intent': self.intent, 'preview': self.preview,
                'files': [{'path': p, **f} for p, f in self.files.items()]}

    def facts(self, now: float | None = None) -> str:
        """What the voice may say, by tense: done, now, next. Only facts; an intention says so."""
        now = now if now is not None else time.time()
        lines = [f'已用时 {round(now - self.started)} 秒，任务仍在进行。']
        if self.plan:
            done = [p['step'] for p in self.plan if p['status'] == 'completed']
            doing = [p['step'] for p in self.plan if p['status'] == 'inProgress']
            todo = [p['step'] for p in self.plan if p['status'] == 'pending']
            lines.append(f'计划共 {len(self.plan)} 步。')
            if done:
                lines.append('已完成：' + '；'.join(done))
            if doing:
                lines.append('进行中：' + '；'.join(doing))
            if todo:
                lines.append('还没开始：' + '；'.join(todo[:3]))
        if self.current:
            detail = self.current.get('detail') or ''
            progress = self.current.get('progress')
            extra = [f"{round(now - self.current['since'])} 秒"]
            if progress is not None:
                extra.append(f'约 {round(progress * 100)}%')
            if detail and self.current.get('kind') == 'screen':
                extra.append(detail)
            lines.append(f"此刻正在：{self.current['text']}（{'，'.join(extra)}）")
        elif self.recent:
            lines.append(f"刚做完：{self.recent[-1]['text']}")
        if self.preview and not self.preview['done'] and self.preview.get('progress') is not None:
            lines.append(f"渲染进度：{self.preview['text']}（约 {round(self.preview['progress'] * 100)}%，画面正在逐步变清晰）")
        if self.intent and now - self.intent_at < 60:
            lines.append(f'接下来打算：{self.intent}（这是打算，还没做完）')
        return '\n'.join(lines)
