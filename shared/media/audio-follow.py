#!/usr/bin/python3
"""While casting, each sound plays where its picture is (docs/58, "声音跟着画面").

Android sends every ordinary media sound to the TV while a Wi-Fi display is connected, so the
container's default output `android` (Termux PulseAudio, following Android's routing) plays on the
TV, also for an app the user looks at on the phone. `android_phone` always plays on the phone
itself (media-bridge, docs/59), alongside the TV. This service moves each playback stream of the
user's session between the two while a TV is connected:

  an app whose window is on the phone's own screen         -> android_phone
  an app whose window is on the TV (computer mode, CAST-n) -> android
  a workspace's sound (rungic-workspace-sound's loopback):
      shown on the TV (the director)                       -> android
      shown on the phone (its window, fullscreen)          -> android_phone
  the independent desktop's (workspace 0, docs/research/97 §19.6):
      the TV in computer mode                              -> android
      else                                                 -> android_phone
  a sound without a window (a command, a notification)     -> where the user's desktop is: the TV
                                                              in computer mode, else the phone

Streams an app put elsewhere itself (the voice assistant's android_phone, a call's Linux speaker,
a workspace's own sink) are left alone. With no TV every moved stream goes back to `android`.

Window places come from a KWin script loaded once, which reports {pid: [outputs]} at start and at
every window added, removed or moved to another output; the TV's state from the platform bridge's
"screens" events (rungic_host_watch); new streams from `pactl subscribe`. Nothing is polled.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from gi.repository import Gio, GLib

sys.path.insert(0, '/usr/lib/python3/dist-packages')
import rungic_host_watch  # noqa: E402

TV, PHONE = 'android', 'android_phone'
ENV = {**os.environ, 'LC_ALL': 'C'}
SERVICE_PATH = '/com/rungic/AudioFollow'
INTERFACE = '''
<node><interface name="com.rungic.AudioFollow"><method name="Windows"><arg type="s" direction="in"/></method></interface></node>
'''
# Every window's process and output, reported again whenever one comes, goes or changes output.
SCRIPT = '''
function report() {
  const out = {};
  const wins = workspace.windowList();
  for (let i = 0; i < wins.length; i++) {
    const w = wins[i];
    if (!w.pid || !w.output) continue;
    (out[w.pid] = out[w.pid] || []).push(String(w.output.name));
  }
  callDBus("SERVICE", "/com/rungic/AudioFollow", "com.rungic.AudioFollow", "Windows", JSON.stringify(out));
}
function watch(w) { w.outputChanged.connect(report); }
const all = workspace.windowList();
for (let i = 0; i < all.length; i++) watch(all[i]);
workspace.windowAdded.connect(function (w) { watch(w); report(); });
workspace.windowRemoved.connect(report);
report();
'''


def log(*args):
    print(time.strftime('%H:%M:%S'), *args, flush=True)


def pactl(*args):
    return subprocess.run(['pactl', *args], capture_output=True, text=True, env=ENV, timeout=5)


def bridge(request):
    try:
        return rungic_host_watch._request(request, 3)
    except (OSError, ValueError):
        return {}


def parents(pid, depth=6):
    """`pid` and its ancestors (a browser's sound comes from a child of its window's process)."""
    chain = []
    while pid and pid > 1 and depth > 0:
        chain.append(pid)
        try:
            status = Path(f'/proc/{pid}/status').read_text()
            pid = int(re.search(r'^PPid:\s+(\d+)', status, re.M).group(1))
        except (OSError, AttributeError, ValueError):
            break
        depth -= 1
    return chain


def streams():
    """Playback streams: [{index, sink (name), pid, module}]."""
    sinks = {}
    for line in pactl('list', 'short', 'sinks').stdout.splitlines():
        parts = line.split('\t')
        if len(parts) > 1:
            sinks[parts[0]] = parts[1]
    out, current = [], None
    for line in pactl('list', 'sink-inputs').stdout.splitlines() + ['Sink Input #end']:
        if line.startswith('Sink Input #'):
            if current:
                out.append(current)
            current = {'index': line.split('#', 1)[1], 'sink': '', 'pid': 0, 'module': ''}
        elif current is not None:
            text = line.strip()
            if text.startswith('Sink:'):
                current['sink'] = sinks.get(text.split(':', 1)[1].strip(), '')
            elif text.startswith('Owner Module:'):
                current['module'] = text.split(':', 1)[1].strip()
            elif text.startswith('application.process.id = '):
                try:
                    current['pid'] = int(text.split('=', 1)[1].strip().strip('"'))
                except ValueError:
                    pass
    return [s for s in out if s['index'] != 'end']


def loopback_workspaces():
    """Owner module index -> workspace N, of the workspaces' loopbacks (rungic-workspace-sound)."""
    out = {}
    for line in pactl('list', 'short', 'modules').stdout.splitlines():
        parts = line.split('\t')
        if len(parts) > 2 and parts[1] == 'module-loopback':
            found = re.search(r'source=rungic_ws(\d+)\.monitor', parts[2])
            if found:
                out[parts[0]] = int(found.group(1))
    return out


class Follow:
    def __init__(self):
        self.windows = {}          # pid -> [output names]
        self.tv = {}               # the platform bridge's "tv" state
        self.moved = set()         # streams this moved to the phone
        self.lock = threading.Lock()
        self.pending = False

    # ---- where each sound goes -----------------------------------------------------------------
    def target(self, stream, loopbacks):
        """The sink `stream` belongs on now, or None to leave it."""
        casting = bool(self.tv.get('connected'))
        if stream['module'] in loopbacks:
            slot = loopbacks[stream['module']]
            if not casting:
                return TV
            if slot == 0:   # desktop mode: on the TV in computer mode
                return TV if self.tv.get('content') == 'desktop' else PHONE
            return TV if slot in (self.tv.get('shown') or []) else PHONE
        # An app's own choice, other than the two this moves between: leave it.
        if stream['sink'] not in (TV, PHONE) or (stream['sink'] == PHONE and stream['index'] not in self.moved):
            return None
        if not casting:
            return TV
        outputs = []
        for pid in parents(stream['pid']):
            outputs = self.windows.get(str(pid)) or self.windows.get(pid) or []
            if outputs:
                break
        if any(o.startswith('CAST') for o in outputs):
            return TV
        if outputs:
            return PHONE
        return TV if self.tv.get('content') == 'desktop' else PHONE

    def sweep(self):
        with self.lock:
            self.pending = False
            loopbacks = loopback_workspaces()
            live = set()
            for stream in streams():
                live.add(stream['index'])
                sink = self.target(stream, loopbacks)
                if not sink or sink == stream['sink']:
                    continue
                if pactl('move-sink-input', stream['index'], sink).returncode == 0:
                    (self.moved.add if sink == PHONE else self.moved.discard)(stream['index'])
                    log('moved', stream['index'], f"(pid {stream['pid']})", stream['sink'], '->', sink)
            self.moved &= live

    def soon(self):
        """A sweep shortly (a burst of events makes one)."""
        if not self.pending:
            self.pending = True
            GLib.timeout_add(150, lambda: (self.sweep(), False)[1])

    # ---- what changed --------------------------------------------------------------------------
    def on_windows(self, report):
        try:
            self.windows = json.loads(report)
        except ValueError:
            return
        self.soon()

    def on_screens(self):
        state = bridge({'op': 'tv'})
        tv = state.get('tv') or {}
        if tv != self.tv:
            log('tv', json.dumps(tv))
        self.tv = tv
        GLib.idle_add(lambda: (self.soon(), False)[1])

    def watch_pulse(self):
        process = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, env=ENV)
        for line in process.stdout:
            if "on sink-input" in line and ("'new'" in line or "'change'" in line):
                GLib.idle_add(lambda: (self.soon(), False)[1])
        log('pactl subscribe ended')
        os._exit(1)   # systemd starts it again


def load_script(bus, name):
    path = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'rungic-audio-follow.js'
    path.write_text(SCRIPT.replace('SERVICE', bus.get_unique_name()))
    call = lambda method, obj, iface, args: bus.call_sync('org.kde.KWin', obj, iface, method, args, None, 0, 5000).unpack()
    try:
        call('unloadScript', '/Scripting', 'org.kde.kwin.Scripting', GLib.Variant('(s)', (name,)))
    except GLib.Error:
        pass
    number = call('loadScript', '/Scripting', 'org.kde.kwin.Scripting', GLib.Variant('(ss)', (str(path), name)))[0]
    call('run', f'/Scripting/Script{number}', 'org.kde.kwin.Script', None)


def main():
    follow = Follow()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    node = Gio.DBusNodeInfo.new_for_xml(INTERFACE)

    def on_call(connection, sender, path, interface, method, args, invocation):
        follow.on_windows(args.unpack()[0])
        invocation.return_value(None)

    bus.register_object(SERVICE_PATH, node.interfaces[0], on_call, None, None)
    load_script(bus, 'rungic-audio-follow')
    rungic_host_watch.watch(['screens'], follow.on_screens, fallback=30, legacy=5, name='audio-follow-screens')
    threading.Thread(target=follow.watch_pulse, daemon=True, name='pactl-subscribe').start()
    log('following: windows from KWin, the TV from the platform bridge, streams from PulseAudio')
    GLib.MainLoop().run()


if __name__ == '__main__':
    main()
