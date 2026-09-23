#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""KWin PipeWire node -> Android H.264 + PulseAudio -> MP4. No portal bypass:
only plasmashell creates the restricted KWin screen stream and passes its node.
"""
import configparser
import os
from pathlib import Path
import signal
import threading
import sys
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

CONFIG = Path.home() / '.config/moto-screen-recording.ini'
PROFILES = {'standard': (4000, 30), 'high': (8000, 30), 'smooth': (12000, 60)}
SOURCES = {'none': [], 'system': ['android.monitor'], 'microphone': ['android_microphone'],
           'both': ['android.monitor', 'android_microphone']}

def settings():
    c = configparser.ConfigParser()
    c.read(CONFIG)
    p = c['Recording'] if c.has_section('Recording') else {}
    return p.get('quality', 'high'), p.get('audio', 'system')

class Recorder:
    def __init__(self, node, output):
        Gst.init(None)
        quality, audio = settings()
        bitrate, fps = PROFILES.get(quality, PROFILES['high'])
        sources = SOURCES.get(audio, SOURCES['system'])
        self.output = Path(output)
        self.partial = self.output.with_suffix('.partial.mp4')
        video = (f'pipewiresrc name=video path={node} do-timestamp=true provide-clock=false keepalive-time={1000//fps} '
                 '! video/x-raw ! videoflip video-direction=auto ! queue max-size-buffers=4 leaky=downstream ! videoconvert '
                 f'! videorate ! video/x-raw,format=I420,framerate={fps}/1 '
                 f'! motoh264enc bitrate={bitrate} ! h264parse ! queue ! mux.video_0 ')
        audio_pipe = ''
        if sources:
            # Both sources use the pipeline clock; silence source keeps idle intervals timed.
            audio_pipe = ('audiomixer name=mix ignore-inactive-pads=true '
                          '! clocksync ! audioconvert ! audio/x-raw,format=F32LE,rate=48000,channels=2 '
                          '! avenc_aac bitrate=192000 ! aacparse ! queue ! mux.audio_0 '
                          'audiotestsrc name=silence is-live=true wave=silence ! audio/x-raw,rate=48000,channels=2 ! mix. ')
            for index, source in enumerate(sources):
                gain = 0.5 if len(sources) == 2 else 1.0
                audio_pipe += (f'pulsesrc name=audio{index} device={source} provide-clock=false buffer-time=200000 '
                               '! audio/x-raw,rate=48000 ! queue ! audioconvert ! audioresample '
                               f'! audio/x-raw,rate=48000,channels=2 ! volume volume={gain} ! mix. ')
        self.pipeline = Gst.parse_launch(video + audio_pipe + 'mp4mux name=mux fragment-duration=1000 ! filesink name=file')
        self.pipeline.get_by_name('file').set_property('location', str(self.partial))
        self.pipeline.use_clock(Gst.SystemClock.obtain())
        self.loop = GLib.MainLoop()
        self.ok = False
        self.stopping = False
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message', self.message)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.stop)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.stop)
        GLib.timeout_add_seconds(15, self.start_timeout)
        self.started = False
        # Reserve names only after constructing the pipeline successfully.
        # A pre-existing partial file must also leave no empty final file behind.
        self.final_fd = os.open(self.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.close(os.open(self.partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except Exception:
            os.close(self.final_fd)
            self.output.unlink()
            raise
        print(f'CONFIG quality={quality} bitrate={bitrate} fps={fps} audio={audio}', flush=True)

    def start_timeout(self):
        if not self.started:
            print('ERROR Screen capture did not start', flush=True)
            self.loop.quit()
        return False

    def message(self, bus, message):
        if message.type == Gst.MessageType.ERROR:
            error, detail = message.parse_error()
            print(f'ERROR {error.message} ({detail})', flush=True)
            self.loop.quit()
        elif message.type == Gst.MessageType.EOS:
            self.ok = True
            self.loop.quit()
        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self.pipeline:
            if message.parse_state_changed()[1] == Gst.State.PLAYING:
                self.started = True
                print('READY', flush=True)

    def stop(self):
        if not self.stopping:
            self.stopping = True
            print('STOPPING', flush=True)
            # Keep the clocked silence/video branches alive while PulseAudio
            # drains. Ending silence first lets the mixer race through padding
            # and can leave another source blocked behind a full queue.
            threading.Thread(target=self.end_sources, daemon=True).start()
            GLib.timeout_add_seconds(12, self.stop_timeout)
        return False

    def end_sources(self):
        def end(name):
            source = self.pipeline.get_by_name(name)
            if source:
                result = source.send_event(Gst.Event.new_eos())
                print(f'EOS {name} accepted={result}', flush=True)
        # A static screen may have no pending video buffer. End video and real
        # audio concurrently so the muxer can drain either queue. Keep clocked
        # silence until these sources have accepted EOS: ending it first lets
        # audiomixer pad indefinitely after a suspended PulseAudio monitor.
        threads = [threading.Thread(target=end, args=(name,), daemon=True)
                   for name in ['video', 'audio0', 'audio1']
                   if self.pipeline.get_by_name(name)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        end('silence')

    def stop_timeout(self):
        print('ERROR Timed out finalizing recording', flush=True)
        self.loop.quit()
        return False

    def run(self):
        try:
            self.pipeline.set_state(Gst.State.PLAYING)
            self.loop.run()
        finally:
            self.pipeline.set_state(Gst.State.NULL)
            os.close(self.final_fd)
        if self.ok and self.partial.stat().st_size > 0:
            os.replace(self.partial, self.output)
            print('SAVED', flush=True)
            return 0
        # Keep nonempty partial files for recovery; never claim an incomplete file is saved.
        self.output.unlink(missing_ok=True)
        if self.partial.exists() and not self.partial.stat().st_size:
            self.partial.unlink()
        return 1

if __name__ == '__main__':
    if len(sys.argv) != 3 or not sys.argv[1].isdigit():
        raise SystemExit('usage: moto-screen-recorder NODE OUTPUT.mp4')
    try:
        raise SystemExit(Recorder(int(sys.argv[1]), sys.argv[2]).run())
    except Exception as e:
        print(f'ERROR {e}', flush=True)
        raise SystemExit(1)
