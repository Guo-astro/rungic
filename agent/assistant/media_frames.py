# SPDX-License-Identifier: GPL-2.0-or-later
"""Moving pictures and videos the user attaches, as frames the agent can see (docs/88).

Codex takes still images only: of a GIF it decodes the first frame, an animated WebP it passes on
as it is, and a video it cannot take at all (codex-rs/utils/image, 0.159.2). So a few frames
spread over the clip are taken out here and sent as images, with a line that says what they are:
videos with ffprobe/ffmpeg, animations (GIF, WebP, APNG) with Pillow, which reads all of them.
Frames are kept in ~/.cache/rungic-voice-agent/frames, one folder per file and version, and are
named after the file and their time, which is how the agent sees them labelled.
"""
import hashlib
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

VIDEO = {'.mp4', '.m4v', '.mov', '.mkv', '.webm', '.avi', '.3gp', '.ogv', '.mpg', '.mpeg', '.ts', '.wmv', '.flv'}
ANIMATION = {'.gif', '.webp', '.png', '.apng'}
MAX_FRAMES = 8
SECONDS_PER_FRAME = 2.0
LONG_SIDE = 1024
KEEP_S = 7 * 86400


def cache_root():
    return Path.home() / '.cache/rungic-voice-agent/frames'


def may_move(path):
    suffix = Path(path).suffix.lower()
    return suffix in VIDEO or suffix in ANIMATION


def frame_count(duration, available=None):
    """How many frames to show of a clip this long: one every couple of seconds, at least two,
    at most MAX_FRAMES, and never more than it has."""
    count = min(MAX_FRAMES, max(2, math.ceil(duration / SECONDS_PER_FRAME)))
    return min(count, available) if available else count


def prepare(path, log=print):
    """The frames of a video or moving picture: {kind, path, duration, width, height, audio,
    frames: [{time, path}]}, or None for a still picture, a file that can't be read, or no tools."""
    source = Path(path)
    try:
        stat = source.stat()
    except OSError:
        return None
    key = hashlib.sha1(f'{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()[:16]
    folder = cache_root() / key
    manifest = folder / 'frames.json'
    try:
        info = json.loads(manifest.read_text())
        if all(Path(f['path']).exists() for f in info['frames']):
            folder.touch()      # sent again: kept another week
            return info
    except (OSError, ValueError, KeyError, TypeError):
        pass
    forget_old(log)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        info = (video_frames if source.suffix.lower() in VIDEO else animation_frames)(source, folder, log)
    except Exception as error:  # noqa: BLE001  (an unreadable file is sent by its path only)
        log('frames:', source, error)
        info = None
    if not info or not info['frames']:
        shutil.rmtree(folder, ignore_errors=True)
        return None
    manifest.write_text(json.dumps(info, ensure_ascii=False))
    return info


def frame_name(folder, source, seconds):
    return folder / f'{source.stem}@{seconds:06.2f}s.jpg'


def animation_frames(source, folder, log):
    from PIL import Image
    with Image.open(source) as image:
        total = getattr(image, 'n_frames', 1)
        if total < 2:
            return None
        starts, at = [], 0.0
        for index in range(total):
            image.seek(index)
            starts.append(at)
            at += (image.info.get('duration') or 100) / 1000
        duration = at
        count = frame_count(duration, total)
        indices = sorted({min(total - 1, int((i + 0.5) * total / count)) for i in range(count)})
        frames = []
        for index in indices:
            image.seek(index)
            frame = image.convert('RGB')
            frame.thumbnail((LONG_SIDE, LONG_SIDE))
            target = frame_name(folder, source, starts[index])
            frame.save(target, 'JPEG', quality=85)
            frames.append({'time': round(starts[index], 2), 'path': str(target)})
        return {'kind': 'animation', 'path': str(source), 'duration': round(duration, 2),
                'width': image.width, 'height': image.height, 'audio': False, 'frames': frames}


def video_frames(source, folder, log):
    if not shutil.which('ffprobe') or not shutil.which('ffmpeg'):
        log('frames: no ffmpeg/ffprobe for', source)
        return None
    probe = json.loads(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,width,height,duration'
         ':stream_side_data=rotation', '-of', 'json', str(source)],
        capture_output=True, text=True, timeout=20, check=True).stdout)
    streams = probe.get('streams', [])
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    if not video:
        return None
    duration = float(probe.get('format', {}).get('duration') or video.get('duration') or 0)
    width, height = video.get('width', 0), video.get('height', 0)
    rotation = next((d.get('rotation') for d in video.get('side_data_list', []) if 'rotation' in d), 0)
    if abs(int(rotation or 0)) % 180 == 90:
        width, height = height, width
    count = frame_count(duration) if duration > 0 else 1
    frames = []
    for i in range(count):
        seconds = (i + 0.5) * duration / count if duration > 0 else 0.0
        target = frame_name(folder, source, seconds)
        # -ss before -i: a fast seek to the nearest key frame, then decoding up to the time.
        done = subprocess.run(
            ['ffmpeg', '-v', 'error', '-nostdin', '-ss', f'{seconds:.3f}', '-i', str(source), '-frames:v', '1',
             # Within LONG_SIDE, never larger than the video (the box is the smaller of the two).
             '-vf', f"scale='min({LONG_SIDE},iw)':'min({LONG_SIDE},ih)':force_original_aspect_ratio=decrease"
                    ':force_divisible_by=2',
             '-q:v', '3', '-y', str(target)],
            capture_output=True, text=True, timeout=30)
        if done.returncode == 0 and target.exists():
            frames.append({'time': round(seconds, 2), 'path': str(target)})
        else:
            log('frames: ffmpeg', source, seconds, done.stderr.strip()[-300:])
    return {'kind': 'video', 'path': str(source), 'duration': round(duration, 2), 'width': width, 'height': height,
            'audio': any(s.get('codec_type') == 'audio' for s in streams), 'frames': frames}


def describe(info):
    """The line the agent reads about a clip, before its frames."""
    times = ', '.join(f'{f["time"]:g} s' for f in info['frames'])
    what = 'video' if info['kind'] == 'video' else 'animated image'
    sound = ', with sound' if info.get('audio') else ''
    return (f'{info["path"]} ({what}, {info["duration"]:g} s, {info["width"]}x{info["height"]}{sound}): '
            f'{len(info["frames"])} frames from it are attached as images, at {times}')


def forget_old(log=print):
    """Frames of files last sent more than a week ago."""
    root = cache_root()
    if not root.is_dir():
        return
    now = time.time()
    for folder in root.iterdir():
        try:
            if now - folder.stat().st_mtime > KEEP_S:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError as error:
            log('frames: forget', folder, error)
