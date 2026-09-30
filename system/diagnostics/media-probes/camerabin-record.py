#!/usr/bin/python3
"""camerabin-record.py OUT [patched]: record with camerabin as Snapshot does (pipewiresrc camera, camerabin's
default audio source, MP4 H.264/AAC), 3 s viewfinder, then 8 s of video; prints the file's tracks."""
import sys, time, subprocess, gi
gi.require_version('Gst', '1.0'); gi.require_version('GstPbutils', '1.0')
from gi.repository import Gst, GstPbutils, GLib
Gst.init(None)
out = sys.argv[1]
cb = Gst.ElementFactory.make('camerabin')
src = Gst.ElementFactory.make('pipewiresrc'); src.set_property('target-object', 'rungic.camera.0')
if 'patched' in sys.argv:
    src.set_property('provide-clock', False); src.set_property('do-timestamp', True)
wrap = Gst.ElementFactory.make('wrappercamerabinsrc'); wrap.set_property('video-source', src)
cb.set_property('camera-source', wrap)
cb.set_property('viewfinder-sink', Gst.ElementFactory.make('fakesink'))
cont = GstPbutils.EncodingContainerProfile.new('mp4', None, Gst.Caps.from_string('video/quicktime,variant=iso'), None)
cont.add_profile(GstPbutils.EncodingVideoProfile.new(Gst.Caps.from_string('video/x-h264'), None, None, 0))
cont.add_profile(GstPbutils.EncodingAudioProfile.new(Gst.Caps.from_string('audio/mpeg,mpegversion=4'), None, None, 0))
cb.set_property('video-profile', cont)
cb.set_property('mode', 2)
cb.set_property('location', out)
cb.set_state(Gst.State.PLAYING)
time.sleep(3)
print('clock before', cb.get_clock().get_name() if cb.get_clock() else None)
cb.emit('start-capture'); time.sleep(8); cb.emit('stop-capture')
print('clock during', cb.get_clock().get_name() if cb.get_clock() else None)
deadline = time.time() + 30
while time.time() < deadline and not cb.get_property('idle'):
    time.sleep(0.2)
print('idle', cb.get_property('idle'))
cb.set_state(Gst.State.NULL)
p = '/usr/lib/rungic-codec/ffmpeg/bin/ffprobe'
print(subprocess.run([p, '-v', 'error', '-count_frames', '-show_entries', 'stream=codec_type,start_time,duration,nb_read_frames', '-of', 'compact', out], capture_output=True, text=True).stdout)
