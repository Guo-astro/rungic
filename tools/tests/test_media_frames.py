#!/usr/bin/env python3
"""Frames of attached videos and moving pictures for the agent (agent/assistant/media_frames.py,
docs/88): which files get frames, how many and when, their size, the line the agent reads, the
cache, and a missing ffmpeg. Needs Pillow; the video cases need ffmpeg on this machine."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'agent/assistant'))
import media_frames  # noqa: E402


def animation(path, size, count, duration=100):
    frames = [Image.new('RGB', size, (i * 40 % 256, 90, 160)) for i in range(count)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=duration, loop=0)


def quiet(*args):
    pass


class FramesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        home = patch.dict(os.environ, {'HOME': str(self.dir / 'home')})
        home.start()
        self.addCleanup(home.stop)
        self.addCleanup(self.temp.cleanup)

    def test_count(self):
        self.assertEqual(media_frames.frame_count(0.5), 2)
        self.assertEqual(media_frames.frame_count(7), 4)
        self.assertEqual(media_frames.frame_count(600), media_frames.MAX_FRAMES)
        self.assertEqual(media_frames.frame_count(10, available=3), 3)

    def test_gif_frames(self):
        path = self.dir / 'wave.gif'
        animation(path, (1600, 900), 30, duration=100)       # 3 s
        info = media_frames.prepare(path, quiet)
        self.assertEqual((info['kind'], info['duration'], info['width'], info['height']), ('animation', 3.0, 1600, 900))
        self.assertEqual([f['time'] for f in info['frames']], [0.7, 2.2])   # one every 2 s, mid-span
        with Image.open(info['frames'][0]['path']) as frame:
            self.assertEqual(frame.size, (1024, 576))       # long side 1024, proportions kept
        self.assertTrue(info['frames'][0]['path'].endswith('wave@000.70s.jpg'))
        self.assertEqual(media_frames.describe(info),
                         f'{path} (animated image, 3 s, 1600x900): 2 frames from it are attached as images, '
                         'at 0.7 s, 2.2 s')

    def test_animated_webp_and_apng(self):
        for name in ('wave.webp', 'wave.png'):
            with self.subTest(name=name):
                path = self.dir / name
                animation(path, (64, 48), 6)
                info = media_frames.prepare(path, quiet)
                self.assertEqual(info['kind'], 'animation')
                self.assertEqual(len(info['frames']), 2)

    def test_still_pictures_have_no_frames(self):
        for name in ('still.gif', 'still.webp', 'still.png'):
            with self.subTest(name=name):
                path = self.dir / name
                Image.new('RGB', (64, 48), (1, 2, 3)).save(path)
                self.assertIsNone(media_frames.prepare(path, quiet))
        self.assertEqual(list(media_frames.cache_root().iterdir()), [])
        self.assertFalse(media_frames.may_move(self.dir / 'photo.jpg'))
        self.assertIsNone(media_frames.prepare(self.dir / 'missing.gif', quiet))

    def test_cache_reused_and_renewed(self):
        path = self.dir / 'wave.gif'
        animation(path, (64, 48), 10)
        first = media_frames.prepare(path, quiet)
        with patch.object(media_frames, 'animation_frames', side_effect=AssertionError('read again')):
            self.assertEqual(media_frames.prepare(path, quiet), first)
        animation(path, (64, 48), 20)                            # a new version of the file
        os.utime(path, ns=(1, 1))
        self.assertNotEqual(media_frames.prepare(path, quiet)['duration'], first['duration'])

    def test_old_frames_forgotten(self):
        old = media_frames.cache_root() / 'old'
        old.mkdir(parents=True)
        os.utime(old, (1, 1))
        path = self.dir / 'wave.gif'
        animation(path, (64, 48), 10)
        media_frames.prepare(path, quiet)
        self.assertFalse(old.exists())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'needs ffmpeg')
    def test_video_frames(self):
        path = self.dir / 'clip.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=1280x720:rate=10:duration=5',
                        '-f', 'lavfi', '-i', 'sine=duration=5', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-y', str(path)], check=True)
        info = media_frames.prepare(path, quiet)
        self.assertEqual((info['kind'], info['width'], info['height'], info['audio']), ('video', 1280, 720, True))
        self.assertAlmostEqual(info['duration'], 5, delta=0.1)
        self.assertEqual(len(info['frames']), 3)
        self.assertEqual([round(f['time']) for f in info['frames']], [1, 2, 4])
        with Image.open(info['frames'][1]['path']) as frame:
            self.assertEqual(frame.size, (1024, 576))
        self.assertIn('(video, 5', media_frames.describe(info))
        self.assertIn('with sound', media_frames.describe(info))
        manifest = json.loads((Path(info['frames'][0]['path']).parent / 'frames.json').read_text())
        self.assertEqual(manifest, info)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'needs ffmpeg')
    def test_rotated_video_reports_upright_size(self):
        # A phone video held upright: 640x360 pixels stored, shown turned a quarter.
        flat, path = self.dir / 'flat.mp4', self.dir / 'portrait.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=10:duration=2',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', str(flat)], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-display_rotation', '90', '-i', str(flat), '-c', 'copy', '-y', str(path)],
                       check=False)
        if not path.exists():
            self.skipTest('this ffmpeg cannot write a rotation')
        info = media_frames.prepare(path, quiet)
        self.assertEqual((info['width'], info['height']), (360, 640))
        with Image.open(info['frames'][0]['path']) as frame:
            self.assertEqual(frame.size, (360, 640))

    def test_video_without_ffmpeg_is_sent_by_path(self):
        path = self.dir / 'clip.mp4'
        path.write_bytes(b'not really')
        with patch.object(media_frames.shutil, 'which', return_value=None):
            self.assertIsNone(media_frames.prepare(path, quiet))

    def test_unreadable_video(self):
        path = self.dir / 'broken.mp4'
        path.write_bytes(b'not a video')
        if not shutil.which('ffprobe'):
            self.skipTest('needs ffprobe')
        self.assertIsNone(media_frames.prepare(path, quiet))


if __name__ == '__main__':
    unittest.main()
