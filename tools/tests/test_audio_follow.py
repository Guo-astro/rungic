#!/usr/bin/env python3
"""rungic-audio-follow (shared/media/audio-follow.py, docs/58): while casting, each sound plays where
its picture is; without a TV everything goes back to the default output."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

root = Path(__file__).resolve().parents[2]
sys.modules.setdefault('gi', types.ModuleType('gi'))
repository = types.ModuleType('gi.repository')
repository.Gio = repository.GLib = mock.MagicMock()
sys.modules['gi.repository'] = repository
sys.modules['rungic_host_watch'] = types.ModuleType('rungic_host_watch')
spec = importlib.util.spec_from_file_location('audio_follow', root / 'shared/media/audio-follow.py')
follow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(follow)


def stream(index, sink='android', pid=0, module=''):
    return {'index': str(index), 'sink': sink, 'pid': pid, 'module': module}


class TargetTest(unittest.TestCase):
    def setUp(self):
        self.f = follow.Follow()
        self.f.windows = {'100': ['WL-0'], '200': ['CAST-1']}
        self.f.tv = {'connected': True, 'content': 'director', 'shown': [2]}
        patcher = mock.patch.object(follow, 'parents', side_effect=lambda pid: [pid, 1])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_app_on_the_phone_plays_on_the_phone(self):
        self.assertEqual(self.f.target(stream(1, pid=100), {}), 'android_phone')

    def test_an_app_on_the_tv_stays_on_the_tv(self):
        self.assertEqual(self.f.target(stream(1, pid=200), {}), 'android')

    def test_a_workspace_on_the_tv_or_the_phone(self):
        loops = {'40': 2, '41': 3}
        self.assertEqual(self.f.target(stream(1, module='40'), loops), 'android')
        self.assertEqual(self.f.target(stream(2, module='41'), loops), 'android_phone')

    def test_no_window_follows_the_users_desktop(self):
        self.assertEqual(self.f.target(stream(1, pid=999), {}), 'android_phone')
        self.f.tv['content'] = 'desktop'
        self.assertEqual(self.f.target(stream(1, pid=999), {}), 'android')

    def test_an_apps_own_choice_is_left(self):
        self.assertIsNone(self.f.target(stream(1, sink='linux_speaker', pid=100), {}))
        self.assertIsNone(self.f.target(stream(2, sink='android_phone', pid=200), {}))   # the voice assistant's

    def test_without_a_tv_the_moved_go_back(self):
        self.f.moved = {'1'}
        self.f.tv = {'connected': False}
        self.assertEqual(self.f.target(stream(1, sink='android_phone', pid=100), {}), 'android')
        self.assertEqual(self.f.target(stream(2, module='40'), {'40': 2}), 'android')


if __name__ == '__main__':
    unittest.main()
