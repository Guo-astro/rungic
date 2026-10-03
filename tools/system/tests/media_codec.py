# SPDX-License-Identifier: MIT
"""The GStreamer elements of the Android hardware codecs (shared/media/gst-rungic-codec.c, docs/48,
docs/research/35), without the phone: the app's codec broker is a stand-in
(tools/system/android_media.py, CodecBridge.java's protocol) whose decoder returns grey pictures in
presentation order. Files made with the software encoders are played with playbin3, as players do.
Checked: playbin3 picks the hardware decoders by their rank; the pictures keep their own times through
B-frames; pause, resume, seek (FLUSH) and EOS work, every record of the protocol acknowledged in turn;
an encoder that needs the hardware fails without it, also when encodebin picked it, rather than
switching to a software encoder."""
import os
import subprocess
import time
from pathlib import Path

import gi

gi.require_version('Gst', '1.0')
gi.require_version('GstPbutils', '1.0')
from gi.repository import Gst, GstPbutils  # noqa: E402

import android_media  # noqa: E402
import harness  # noqa: E402

WORK = Path('/tmp/codec-test')
STEPS = []
FRAME = Gst.SECOND // 30


def check(condition, what, detail=''):
    STEPS.append(what)
    if not condition:
        raise harness.Failed(f'{what}: not so {detail}'.rstrip())


def make(name, encode):
    path = WORK / name
    pipeline = (f'videotestsrc num-buffers=90 pattern=ball ! video/x-raw,format=I420,width=320,height=240,framerate=30/1 ! '
                f'{encode} ! filesink location={path}')
    result = subprocess.run(['gst-launch-1.0', '-q', *pipeline.split()], capture_output=True, text=True, timeout=120)
    check(result.returncode == 0 and path.stat().st_size > 0, f'a test file {name} made with the software encoder',
          result.stderr[-500:])
    return path


def elements(bin_):
    found = []
    iterator = bin_.iterate_recurse()
    while True:
        result, element = iterator.next()
        if result != Gst.IteratorResult.OK:
            return found
        factory = element.get_factory()
        found.append(factory.get_name() if factory else '')


class Player:
    """playbin3 into an appsink that takes one picture at a time (the test sets the pace)."""

    def __init__(self, path):
        self.playbin = Gst.ElementFactory.make('playbin3')
        self.sink = Gst.ElementFactory.make('appsink')
        self.sink.set_property('sync', False)
        self.sink.set_property('max-buffers', 1)
        self.playbin.set_property('video-sink', self.sink)
        self.playbin.set_property('audio-sink', Gst.ElementFactory.make('fakesink'))
        self.playbin.set_property('uri', path.as_uri())
        self.bus = self.playbin.get_bus()
        self.playbin.set_state(Gst.State.PLAYING)
        self.settle()

    def settle(self):
        """Until a state change is done: before that the appsink answers nothing (it is not playing)."""
        return self.playbin.get_state(10 * Gst.SECOND)[0]

    def errors(self):
        out = []
        while True:
            message = self.bus.pop_filtered(Gst.MessageType.ERROR)
            if not message:
                return out
            error, debug = message.parse_error()
            out.append(f'{message.src.get_name()}: {error.message} {debug or ""}')

    def pictures(self, count=None):
        """Times of the next pictures (all up to EOS when count is None)."""
        out = []
        while count is None or len(out) < count:
            sample = self.sink.emit('try-pull-sample', 5 * Gst.SECOND)
            if sample is None:
                break
            out.append(sample.get_buffer().pts)
        return out

    def eos(self):
        return self.sink.get_property('eos')

    def stop(self):
        self.playbin.set_state(Gst.State.NULL)


def failing_encoder(env_socket, **env):
    """rungich264enc asked for by name, and encodebin's choice for H.264: does anything come out?"""
    os.environ['RUNGIC_CODEC_SOCKET'] = env_socket
    os.environ.pop('RUNGIC_CODEC_DISABLE', None)
    os.environ.update(env)
    out = {}
    for how in ('named', 'encodebin'):
        pipeline = Gst.Pipeline()
        source = Gst.ElementFactory.make('videotestsrc')
        source.set_property('num-buffers', 10)
        caps = Gst.ElementFactory.make('capsfilter')
        caps.set_property('caps', Gst.Caps.from_string('video/x-raw,format=I420,width=320,height=240,framerate=30/1'))
        if how == 'named':
            encoder = Gst.ElementFactory.make('rungich264enc')
        else:
            encoder = Gst.ElementFactory.make('encodebin')
            encoder.set_property('profile', GstPbutils.EncodingVideoProfile.new(
                Gst.Caps.from_string('video/x-h264'), None, None, 0))
        sink = Gst.ElementFactory.make('appsink')
        sink.set_property('sync', False)
        for element in (source, caps, encoder, sink):
            pipeline.add(element)
        source.link(caps)
        caps.link(encoder)
        encoder.link(sink)
        pipeline.set_state(Gst.State.PLAYING)
        message = pipeline.get_bus().timed_pop_filtered(15 * Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
        made = 0
        while sink.emit('try-pull-sample', 0):
            made += 1
        chosen = [e for e in elements(pipeline) if e.endswith('enc') and e != 'encodebin']
        out[how] = (message.type if message else None, made, chosen)
        pipeline.set_state(Gst.State.NULL)
    return out


# covers[system]: apps.hw-codec/E1 apps.hw-codec/E3 apps.hw-codec/E4
# covers[consumer]: iface:codec
def test():
    WORK.mkdir(exist_ok=True)
    Gst.init(None)
    files = {
        ('h264', 0): make('h264.mp4', 'x264enc bframes=2 b-adapt=false key-int-max=30 ! h264parse ! mp4mux'),
        ('h265', 1): make('h265.mp4', 'x265enc key-int-max=30 ! h265parse ! mp4mux'),
        ('vp9', 2): make('vp9.webm', 'vp9enc keyframe-max-dist=30 deadline=1 ! webmmux'),
    }
    # As deep as x265's B-pyramid reorders (a real decoder holds as many pictures as the stream needs).
    with android_media.Codec(depth=6, burst=3) as broker:
        os.environ['RUNGIC_CODEC_SOCKET'] = broker.path
        for (codec, kind), path in files.items():
            player = Player(path)
            times = player.pictures(30)
            used = elements(player.playbin)
            times += player.pictures()
            errors = player.errors()
            player.stop()
            inspect = subprocess.run(['gst-inspect-1.0', f'rungic{codec}dec'], capture_output=True, text=True).stdout[-400:]
            check(f'rungic{codec}dec' in used, f'playbin3 picks rungic{codec}dec for {codec}',
                  f'{used} {errors} {len(times)} {inspect}')
            check(len(times) == 90 and times == sorted(set(times)), f'{codec}: all 90 pictures, in order', f'({len(times)}) {[t // 1000000 for t in times]}')
            check(all(abs(b - a - FRAME) < Gst.MSECOND for a, b in zip(times, times[1:])),
                  f'{codec}: each at its own time, a frame apart', str(times[:6]))
            check((False, kind, 320, 240) in broker.opened, f'{codec}: the app\'s {codec} decoder was asked for 320x240')

        # Pause, resume and seek in the file with B-frames; then to the end.
        player = Player(files[('h264', 0)])
        first = player.pictures(10)
        player.playbin.set_state(Gst.State.PAUSED)
        check(player.settle() == Gst.StateChangeReturn.SUCCESS, 'pause')
        time.sleep(0.5)
        player.playbin.set_state(Gst.State.PLAYING)
        player.settle()
        more = player.pictures(5)
        check(more and abs(more[0] - first[-1] - FRAME) < Gst.MSECOND, 'resume carries on from the next picture',
              f'{first[-1]} {more[:1]}')
        flushes = broker.commands.count(('FLUSH',))
        check(player.playbin.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 2 * Gst.SECOND),
              'seek to 2 s')
        player.settle()
        rest = player.pictures()
        errors = player.errors()
        eos = player.eos()
        player.stop()
        check(broker.commands.count(('FLUSH',)) > flushes, 'the seek flushes the hardware decoder')
        start = first[0]                   # the file's first picture (B-frames: not at 0)
        check(rest and abs(rest[0] - start - 2 * Gst.SECOND) < Gst.MSECOND and rest == sorted(set(rest)),
              'after the seek the pictures go on from 2 s, in order', f'{start} {rest[:3]}')
        check(len(rest) == 30 and eos and not errors, 'to the end of the file (EOS), without errors', str(errors))
        check(broker.problems == [], 'every record of the protocol was acknowledged in turn', str(broker.problems))

    # Encoders that need the hardware: without it they fail, they do not switch to software.
    with android_media.Codec(refuse=True) as broker:
        cases = {'no app': failing_encoder('/nonexistent/codec.sock'),
                 'no hardware component': failing_encoder(broker.path),
                 'RUNGIC_CODEC_DISABLE=1': failing_encoder(broker.path, RUNGIC_CODEC_DISABLE='1')}
    for case, result in cases.items():
        for how, (message, made, chosen) in result.items():
            check(message == Gst.MessageType.ERROR and made == 0, f'{case}: rungich264enc ({how}) fails, nothing encoded',
                  str(result))
            check(chosen == ['rungich264enc'], f'{case}: and no software encoder took over ({how})', str(chosen))
    return STEPS


if __name__ == '__main__':
    harness.run('media_codec', test)
