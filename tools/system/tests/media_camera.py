# SPDX-License-Identifier: MIT
"""The phone's cameras as PipeWire cameras, without the phone (docs/48, docs/research/33): PipeWire
and WirePlumber run in the session, the media bridge (rungic-media-bridge) starts one
rungic-camera-source per camera that the platform bridge's stand-in lists (capture-info), and the
app's capture socket is a stand-in (tools/system/android_media.py) sending pictures with a marker in
the sensor's top-left corner and a moving bar. A GStreamer pipewiresrc is the application. Checked:
the two nodes and what they offer, Android's camera opened only while an application uses a node and
released after, the nodes gone while the Linux desktop is not in front and back after, and pictures
turned upright by the camera's rotation."""
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst  # noqa: E402

import android_media  # noqa: E402
import contracts  # noqa: E402
import harness  # noqa: E402

WORK = Path('/tmp/camera-test')
STEPS = []
WIDTH, HEIGHT = 720, 1280           # the sensor's 1280x720 turned upright


def check(condition, what, detail=''):
    STEPS.append(what)
    if not condition:
        raise harness.Failed(f'{what}: not so {detail}'.rstrip() + logs())


def logs():
    out = ''
    for name in ('bridge.log', 'pipewire.log', 'wireplumber.log'):
        path = WORK / name
        if path.exists():
            out += f'\n--- {name} ---\n' + path.read_text(errors='replace')[-1500:]
    return out


def wait(condition, what, timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value:
            STEPS.append(what)
            return value
        if time.monotonic() > deadline:
            raise harness.Failed(f'timed out waiting for {what}' + logs())
        time.sleep(0.2)


def nodes():
    """node.name -> the node of PipeWire's graph (pw-dump)."""
    out = subprocess.run(['pw-dump'], capture_output=True, text=True, timeout=10).stdout
    found = {}
    for obj in json.loads(out or '[]'):
        if obj.get('type') == 'PipeWire:Interface:Node':
            props = obj.get('info', {}).get('props', {})
            found[props.get('node.name')] = obj
    return {k: v for k, v in found.items() if k and k.startswith('rungic.camera.')}


class Consumer:
    """An application using a camera node: pipewiresrc into an appsink."""

    def __init__(self, node):
        self.pipeline = Gst.parse_launch(f'pipewiresrc target-object={node} ! video/x-raw,format=BGRA ! '
                                         'appsink name=sink sync=false max-buffers=8 drop=true')
        self.sink = self.pipeline.get_by_name('sink')
        self.pipeline.set_state(Gst.State.PLAYING)

    def frames(self, seconds):
        """(pts, caps size, digest, pixel at points) of the pictures that come in `seconds`."""
        out, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            sample = self.sink.emit('try-pull-sample', Gst.SECOND // 4)
            if not sample:
                continue
            structure = sample.get_caps().get_structure(0)
            size = (structure.get_value('width'), structure.get_value('height'))
            buffer = sample.get_buffer()
            ok, info = buffer.map(Gst.MapFlags.READ)
            data = bytes(info.data)
            buffer.unmap(info)
            out.append((buffer.pts, size, hashlib.sha1(data).hexdigest(), data))
        return out

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)


def white(data, x, y):
    b, g, r, _ = data[(y * WIDTH + x) * 4:(y * WIDTH + x) * 4 + 4]
    return min(b, g, r) > 235


# covers[system]: apps.camera/E1 apps.camera/E2 apps.camera/E3 apps.camera/E4
# covers[consumer]: iface:camera iface:platform-bridge
def test():
    WORK.mkdir(exist_ok=True)
    runtime = Path(f'/tmp/rt-{os.getuid()}')
    runtime.mkdir(mode=0o700, exist_ok=True)
    os.environ.update(XDG_RUNTIME_DIR=str(runtime), LANG='C.UTF-8')
    Gst.init(None)
    info = contracts.query(contracts.load('platform-bridge'), {'op': 'capture-info'})['reply']
    info = {**info, 'cameras': [dict(c) for c in info['cameras']]}
    children = []
    try:
        children.append(subprocess.Popen(['pipewire'], stdout=open(WORK / 'pipewire.log', 'w'), stderr=subprocess.STDOUT))
        wait(lambda: (runtime / 'pipewire-0').exists(), 'PipeWire runs')
        children.append(subprocess.Popen(['wireplumber'], stdout=open(WORK / 'wireplumber.log', 'w'), stderr=subprocess.STDOUT))
        with contracts.StandIn('platform-bridge', {'capture-info': info}) as bridge, \
                android_media.Capture(info['cameras']) as capture:
            os.environ.update(RUNGIC_PLATFORM_SOCKET=bridge.path, RUNGIC_CAPTURE_SOCKET=capture.path)
            children.append(subprocess.Popen(['python3', '/usr/bin/rungic-media-bridge'], stdout=open(WORK / 'bridge.log', 'w'),
                                             stderr=subprocess.STDOUT))
            found = wait(lambda: len(nodes()) == 2 and nodes(), 'a camera node for each camera Android lists', 20)
            props = {name: node['info']['props'] for name, node in found.items()}
            check(all(p.get('media.class') == 'Video/Source' and p.get('media.role') == 'Camera' for p in props.values()),
                  'they are PipeWire cameras (Video/Source, role Camera)')
            check(props['rungic.camera.0'].get('node.description') == 'Android Rear Camera'
                  and props['rungic.camera.1'].get('node.description') == 'Android Front Camera', 'named by the side they face')
            formats = found['rungic.camera.0']['info'].get('params', {}).get('EnumFormat', [])
            check(len(formats) == 1 and formats[0].get('format') == 'BGRA'
                  and formats[0].get('size') == {'width': WIDTH, 'height': HEIGHT}
                  and formats[0].get('framerate') == {'num': 30, 'denom': 1},
                  'each offers only what it does: BGRA, upright 720x1280, 30 frames a second', json.dumps(formats))
            time.sleep(2)
            check(capture.ops().count('camera') == 0, 'Android\'s camera stays closed while no application uses one')

            # An application uses the rear camera: Android's camera opens; the pictures move, in order, upright.
            app = Consumer('rungic.camera.0')
            wait(lambda: capture.count('camera 0') == 1, 'an application starting opens Android\'s rear camera')
            frames = app.frames(3)
            check(len(frames) >= 20, 'pictures come', f'({len(frames)} in 3 s)')
            check({size for _, size, _, _ in frames} == {(WIDTH, HEIGHT)}, 'each 720x1280')
            stamps = [pts for pts, _, _, _ in frames]
            check(all(b > a for a, b in zip(stamps, stamps[1:])), 'with rising timestamps')
            check(len({digest for _, _, digest, _ in frames}) > len(frames) // 2, 'and a changing picture')
            last = frames[-1][3]
            # Rotation 90: the sensor's top-left is the upright picture's top-right.
            check(white(last, WIDTH - 20, 40) and not white(last, 20, 40) and not white(last, 20, HEIGHT - 40),
                  'the rear picture is turned upright by its rotation (90)')
            app.stop()
            wait(lambda: capture.count('camera 0') == 0, 'the application stopping releases Android\'s camera', 8)
            wait(lambda: nodes().get('rungic.camera.0', {}).get('info', {}).get('state') in ('idle', 'suspended'),
                 'and the node goes back to idle')
            app = Consumer('rungic.camera.1')
            wait(lambda: capture.count('camera 1') == 1, 'the front camera opens for its application')
            frames = app.frames(1.5)
            check(frames, 'front pictures come')
            last = frames[-1][3]
            check(white(last, 20, HEIGHT - 40) and not white(last, WIDTH - 20, 40),
                  'the front picture is turned upright by its rotation (270)')
            app.stop()
            wait(lambda: capture.count('camera 1') == 0, 'and is released after')

            # The Linux desktop leaves the front (the app in the background): no cameras, Android's released.
            app = Consumer('rungic.camera.0')
            wait(lambda: capture.count('camera 0') == 1, 'a camera in use')
            info['visible'], capture.visible = False, False
            wait(lambda: not nodes(), 'out of the front the camera nodes go away', 10)
            wait(lambda: capture.count('camera 0') == 0 and capture.count('camera 1') == 0,
                 'and Android has no camera open')
            app.stop()
            info['visible'], capture.visible = True, True
            wait(lambda: len(nodes()) == 2, 'back in front the nodes are there again', 15)
    finally:
        for child in reversed(children):
            child.terminate()
            try:
                child.wait(5)
            except subprocess.TimeoutExpired:
                child.kill()
    return STEPS


if __name__ == '__main__':
    harness.run('media_camera', test)
