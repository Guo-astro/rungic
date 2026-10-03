#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The voice service's half of what the Agent app shows (agent/assistant/rungic_voice_agent.py, the
methods themselves taken out of VoiceAgent): opening a conversation answers from the service's own
store without waiting for Codex, deleting one archives its Codex thread, and a message's pictures
go to the agent as pictures and its other files by path. Codex is a recording stand-in."""
import ast
import json
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'agent/assistant/rungic_voice_agent.py'
tree = ast.parse(SOURCE.read_text())
agent_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VoiceAgent')
agent_class.body = [n for n in agent_class.body if isinstance(n, ast.FunctionDef)
                    and n.name in {'open_conversation', 'delete_conversation', 'send_text'}]
media_frames = types.SimpleNamespace(may_move=lambda p: Path(p).suffix.lower() in ('.gif', '.mp4'),
                                     prepare=lambda p, log: None, describe=lambda c: '')
namespace = {'threading': threading, 'time': time, 'Path': Path, 'log': lambda *a: None, '_': lambda s: s,
             'media_frames': media_frames, 'json': json,
             'GLib': types.SimpleNamespace(idle_add=lambda *a: None)}
exec(compile(ast.Module(body=[agent_class], type_ignores=[]), str(SOURCE), 'exec'), namespace)
VoiceAgent = namespace['VoiceAgent']


class Store:
    def __init__(self):
        self.index = {'c1': {'title': '天气'}, 'c2': {'title': '旧的'}}
        self.events = {'c1': [{'type': 'message', 'role': 'user', 'text': '明天会下雨吗'}]}
        self.deleted = []

    def history(self, cid):
        return list(self.events.get(cid, []))

    def touch(self, cid, title=None, main=False):
        self.index.setdefault(cid, {})

    def opened(self, cid, history, main=False):
        return {'conversation': cid, 'history': history}

    def delete(self, cid):
        self.deleted.append(cid)
        self.index.pop(cid, None)


def agent():
    a = VoiceAgent()
    a.lock = threading.RLock()
    a.phone = None
    a.call = None
    a.thread_id = None
    a.realtime = False
    a.open_generation = 0
    a.store = Store()
    a.server = Mock()
    a.close_conversation = Mock()
    a.start_realtime = Mock()
    a.note_instructions = Mock()
    a.assistant_id = Mock(return_value='main')
    a.emit = Mock()
    a.emit_raw = Mock()
    a.set_state = Mock()
    a.needs_setup = Mock(return_value=False)
    a.agent_model = Mock(return_value={'model': '', 'effort': ''})
    a.resumed = threading.Event()
    a.resumed.set()
    return a


class ServiceSideTest(unittest.TestCase):
    # covers: agent.chat-app/E1
    def test_opening_answers_from_the_store_while_codex_resumes_behind(self):
        a = agent()
        resuming = threading.Event()
        release = threading.Event()

        def resume_thread(cid, generation, resumed):     # Codex reading a large rollout
            resuming.set()
            release.wait(10)
            resumed.set()
        a.resume_thread = resume_thread
        started = time.monotonic()
        opened = a.open_conversation('c1', connect=False)
        self.assertLess(time.monotonic() - started, 0.5, 'not waiting for the resume')
        self.assertTrue(resuming.wait(2), 'the resume runs behind')
        self.assertFalse(a.resumed.is_set(), 'still resuming when the app already has the conversation')
        self.assertEqual(opened['history'], [{'type': 'message', 'role': 'user', 'text': '明天会下雨吗'}])
        release.set()

    # covers: agent.chat-app/E9
    def test_deleting_a_conversation_archives_its_codex_thread(self):
        a = agent()
        a.thread_id = 'c2'
        a.delete_conversation('c2')
        a.close_conversation.assert_called_once()
        a.server.call.assert_called_once_with('thread/archive', {'threadId': 'c2'}, timeout=10)
        self.assertEqual(a.store.deleted, ['c2'])
        # Codex failing to archive does not keep the conversation in the list.
        a = agent()
        a.server.call.side_effect = RuntimeError('no such thread')
        a.delete_conversation('c1')
        self.assertEqual(a.store.deleted, ['c1'])

    # covers: agent.attachments/E3
    def test_pictures_go_as_pictures_and_other_files_by_path(self):
        a = agent()
        a.thread_id = 'c1'
        a.send_text('这张图里是什么', [{'path': '/home/u/Pictures/cat.jpg', 'name': 'cat.jpg', 'kind': 'image'},
                                     {'path': '/home/u/Documents/report.pdf', 'name': 'report.pdf', 'kind': 'file'}])
        method, turn = a.server.call.call_args.args
        self.assertEqual(method, 'turn/start')
        items = turn['input']
        self.assertIn({'type': 'localImage', 'path': '/home/u/Pictures/cat.jpg'}, items)
        self.assertNotIn({'type': 'localImage', 'path': '/home/u/Documents/report.pdf'}, items)
        text = items[0]['text']
        self.assertTrue(text.startswith('这张图里是什么'))
        self.assertIn('Attachments:\n/home/u/Documents/report.pdf', text, 'the agent reads the file itself')
        self.assertNotIn('cat.jpg', text)
        shown = a.emit.call_args.args[0]
        self.assertEqual((shown['type'], shown['role'], len(shown['attachments'])), ('message', 'user', 2),
                         'the message, with what it carries, for the chat')


if __name__ == '__main__':
    unittest.main()
