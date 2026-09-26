#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Post-release acceptance on the phone (docs/61): scenarios from plasma/release/acceptance.json.

  rungic_acceptance.py smoke [--release V]     every deploy; about two minutes
  rungic_acceptance.py full [--release V]      release candidates: smoke plus the full scenarios
  rungic_acceptance.py run ID... [--release V] selected scenarios
  rungic_acceptance.py compare A B             metrics of two reports (paths)

A check returns passed/metrics/details; metrics are compared with the newest report of an
earlier release. Results: .work/acceptance/<release>/<time>/report.json. Every scenario
restores what it changes (accessibility, display scale, recordings it made). Items that
automatic checks do not replace are listed as manual in each report.
"""
import argparse
import datetime
import json
import re
import shlex
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rungic_agent  # noqa: E402
import rungic_device  # noqa: E402
from rungic_device import out, run  # noqa: E402

SCENARIOS = rungic_device.WORKSPACE / 'plasma/release/acceptance.json'
RESULTS = rungic_device.WORKSPACE / '.work/acceptance'
CHECKS = {}


def check(fn):
    CHECKS[fn.__name__] = fn
    return fn


def result(passed, metrics=None, **details):
    return {'passed': bool(passed), 'metrics': metrics or {}, 'details': details}


def user(script, timeout=120):
    return run(script, 'user', timeout, check=False)


def wait_for(condition, timeout=10, interval=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(interval)
    return condition()


# ---------------------------------------------------------------- session

@check
def session_ready(ctx, settle_s=15, timeout=90):
    """KWin and plasmashell up with stable PIDs, and plasmashell running long enough to have
    loaded its launcher model: later checks must not race a session that is still starting."""
    probe = ('test -f /run/user/1000/moto-session.env && echo env; k=$(pidof kwin_wayland) && echo kwin $k; '
             'p=$(pidof -s plasmashell) && echo shell $p $(ps -o etimes= -p $p)')
    samples, deadline = [], time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = run(probe, 'container', check=False).stdout
        state = {line.split()[0]: line.split()[1:] for line in text.splitlines() if line.strip()}
        key = (tuple(state.get('kwin', [])), (state.get('shell') or [None])[0])
        age = int(state['shell'][1]) if len(state.get('shell', [])) > 1 else 0
        samples = (samples + [key])[-3:]
        if {'env', 'kwin', 'shell'} <= set(state) and len(samples) == 3 and len(set(samples)) == 1 \
                and age >= settle_s:
            return result(True, {'shell_age_s': age}, kwin=list(key[0]), plasmashell=key[1])
        time.sleep(2)
    return result(False, present=sorted(state), samples=[list(map(str, s)) for s in samples])


@check
def user_units(ctx, critical=()):
    failed = user('systemctl --user --failed --no-legend --plain | cut -d" " -f1').stdout.split()
    bad = [u for u in failed if any(re.fullmatch(p.replace('*', '.*'), u) for p in critical)]
    return result(not bad, {'failed_units': len(failed)}, failed=failed, critical_failed=bad)


@check
def new_crashes(ctx):
    since = max(1.0, time.time() - ctx['since'] + 2)   # relative, so host and phone clocks need not agree
    groups = rungic_agent.crash_groups(since)['groups']
    known = ctx['spec'].get('known_crash_signatures', {})
    new = [g for g in groups if g['signature'] not in known]
    return result(not new, {'crash_groups': len(groups), 'unknown': len(new)},
                  unknown=[{k: g[k] for k in ('signature', 'comm', 'signal', 'count', 'frames', 'latest_report')}
                           for g in new],
                  known=[{'signature': g['signature'], 'count': g['count'], 'why': known[g['signature']]}
                         for g in groups if g['signature'] in known])


# ---------------------------------------------------------------- display and input

@check
def display_geometry(ctx):
    android = re.search(r'(\d+)x(\d+)', out('wm size | tail -1', 'shell'))
    android = (int(android[1]), int(android[2])) if android else None
    doctor = json.loads(user('kscreen-doctor -j 2>/dev/null').stdout or '{}')
    outputs = []
    for o in doctor.get('outputs', []):
        if not o.get('enabled'):
            continue
        mode = next((m for m in o.get('modes', []) if m['id'] == o.get('currentModeId')), None)
        if mode:
            outputs.append({'name': o['name'], 'size': [mode['size']['width'], mode['size']['height']],
                            'scale': o.get('scale'), 'rotation': o.get('rotation'), 'refresh': mode.get('refreshRate')})
    phone = [o for o in outputs if sorted(o['size']) == sorted(android or ())]
    return result(bool(phone), {'refresh_hz': phone[0]['refresh'] if phone else None},
                  android=android, outputs=outputs)


def _home():
    """A known starting point: keyboard hidden, drawer closed, home screen."""
    import ui_launch_check as ui
    run(f'{rungic_device.PLASMA} hide-keyboard', 'root', check=False)
    for _ in range(2):
        ui.press('Home')
        time.sleep(0.8)


def _drawer_search():
    import ui_launch_check as ui
    _home()
    try:
        ui.open_drawer()
    except RuntimeError:
        _home()
        ui.open_drawer()
    fields = rungic_agent.ui_find('plasmashell', role='text', name='Search')
    if not fields:
        raise RuntimeError('drawer search field not showing')
    return fields[0]


OCR = """
import json, sys
from rapidocr import RapidOCR
out = RapidOCR()(sys.argv[1])
print(json.dumps([[t, float(sc), [int(v) for v in b[0]]] for t, sc, b in zip(out.txts, out.scores, out.boxes)],
                 ensure_ascii=False))
"""


def ocr_screen():
    """Text on the phone's screen: [text, score, [x, y]] from RapidOCR in moto-clicker's venv."""
    shot = rungic_agent.screenshot()
    rungic_device.to_container(shot, '/var/tmp/moto-acceptance-ocr.png', '644')
    text = user('py=/usr/lib/moto-clicker/venv/bin/python; [ -x $py ] || py=/usr/local/lib/moto-clicker/venv/bin/python; '
                f"$py -c {shlex.quote(OCR)} "
                '/var/tmp/moto-acceptance-ocr.png 2>/dev/null; rm -f /var/tmp/moto-acceptance-ocr.png', timeout=120)
    return json.loads(text.stdout.strip().splitlines()[-1]), shot


@check
def input_text(ctx, text='Calcul', expect='Calculator', absent='Clock'):
    """Android text input into the drawer search, read back from the screen by OCR: right after a
    session restart the results never reach the AT-SPI tree, and the search field exposes no text."""
    enabled = rungic_agent.a11y('state')['enabled']
    if not enabled:
        rungic_agent.ui_enable(True)
        time.sleep(2)
    try:
        field = _drawer_search()
        taps = 0
        for taps in range(1, 4):
            rungic_agent.ui_tap('plasmashell', field['path'])
            focused = wait_for(lambda: any('focused' in f.get('states', []) for f in
                                           rungic_agent.ui_find('plasmashell', role='text', name='Search')),
                               timeout=3, interval=0.3)
            if focused:
                break
        if not focused:
            return result(False, {'taps': taps}, error='the drawer search field never took focus')
        run(f'input text {shlex.quote(text)}', 'shell')
        time.sleep(1.5)
        words, _ = ocr_screen()
        top = field['extents'][1] * 3 + 400          # logical → pixels, generous: field and results
        seen = [w for w, score, (x, y) in words if y < top + 600]
        # Case-insensitive: right after a container start the first Android key input sometimes
        # arrives with the wrong case ("CaICUL"); that is recorded, text delivery is what is checked.
        typed = [w for w in seen if w.lower().startswith(text.lower()) and not w.lower().startswith(expect.lower())]
        return result(bool(typed) and expect in seen and absent not in seen, {'taps': taps}, sent=text,
                      case_exact=any(w.startswith(text) for w in typed), seen=seen[:20])
    finally:
        try:
            _home()
        except Exception:
            pass
        if not enabled:
            rungic_agent.ui_enable(False)


# ---------------------------------------------------------------- media

CAMERA_PROBE = r'''
import gi, json, sys, time
gi.require_version('Gst', '1.0')
from gi.repository import Gst
Gst.init(None)
node, count = sys.argv[1], int(sys.argv[2])
pipe = Gst.parse_launch(f'pipewiresrc target-object={node} num-buffers={count + 5} ! videoconvert ! '
                        'video/x-raw,format=GRAY8 ! appsink name=sink sync=false max-buffers=4 drop=false')
sink = pipe.get_by_name('sink')
pipe.set_state(Gst.State.PLAYING)
frames, start, caps = [], time.monotonic(), None
while len(frames) < count and time.monotonic() - start < 40:
    sample = sink.emit('try-pull-sample', 10 * Gst.SECOND)
    if sample is None:
        break
    caps = caps or sample.get_caps().to_string()
    buf = sample.get_buffer()
    ok, info = buf.map(Gst.MapFlags.READ)
    data = info.data[::211]
    mean = sum(data) / len(data)
    std = (sum((x - mean) ** 2 for x in data) / len(data)) ** 0.5
    frames.append({'t': round(time.monotonic() - start, 3), 'pts': buf.pts, 'mean': round(mean, 1),
                   'std': round(std, 1)})
    buf.unmap(info)
first = time.monotonic() - start
pipe.set_state(Gst.State.NULL)
print(json.dumps({'frames': frames, 'caps': caps, 'seconds': round(first, 2)}))
'''


def _node_state(name):
    dump = json.loads(user('pw-dump 2>/dev/null').stdout or '[]')
    for obj in dump:
        info = obj.get('info') or {}
        if obj.get('type', '').endswith(':Node') and (info.get('props') or {}).get('node.name') == name:
            return info.get('state')
    return None


@check
def camera_frames(ctx, node='moto.camera.0', frames=20):
    probe = user(f"python3 -c {shlex.quote(CAMERA_PROBE)} {shlex.quote(node)} {int(frames)}", timeout=90)
    try:
        data = json.loads(probe.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return result(False, error=(probe.stderr or probe.stdout)[-1500:])
    got = data['frames']
    pts = [f['pts'] for f in got]
    monotonic = all(b > a for a, b in zip(pts, pts[1:]))
    # Not a constant fill: sensor noise or scene changes. A dark scene (phone face down) still
    # has noise; a pipeline that delivers zeroed or stale buffers has none.
    varied = sum(1 for f in got if f['std'] > 0) + len({f['mean'] for f in got}) - 1
    fps = (len(pts) - 1) / ((pts[-1] - pts[0]) / 1e9) if len(pts) > 1 and pts[-1] > pts[0] else None
    idle = wait_for(lambda: _node_state(node) in ('suspended', 'idle'), timeout=10)
    luma = round(sum(f['mean'] for f in got) / len(got), 1) if got else None
    arrival = [f['t'] for f in got]
    max_gap = round(max((b - a for a, b in zip(arrival, arrival[1:])), default=0), 3)
    return result(len(got) == frames and monotonic and varied >= frames // 2 and idle,
                  {'fps': round(fps, 1) if fps else None, 'first_frame_s': arrival[0] if arrival else None,
                   'max_gap_s': max_gap, 'mean_luma': luma},
                  frames=len(got), monotonic=monotonic, varied=varied, caps=data['caps'],
                  state_after=_node_state(node))


def _pactl_short(kind):
    rows = []
    for line in user(f'pactl list short {kind}').stdout.splitlines():
        parts = line.split('\t')
        if len(parts) >= 2:
            rows.append(parts)
    return rows


@check
def audio_playback(ctx):
    default = user('pactl get-default-sink').stdout.strip()
    sinks = {row[1]: row for row in _pactl_short('sinks')}
    # 1 s of a quiet 440 Hz tone at 5 % stream volume: enough to route, barely audible.
    user('''python3 - <<'PY'
import math, struct, wave
with wave.open('/tmp/moto-acceptance-tone.wav', 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
    w.writeframes(b''.join(struct.pack('<hh', v, v) for v in
                  (int(800 * math.sin(2 * math.pi * 440 * i / 48000)) for i in range(48000 * 2))))
PY''')
    import threading
    player = threading.Thread(target=user, args=('paplay --volume=3277 --client-name=moto-acceptance '
                                                 '/tmp/moto-acceptance-tone.wav',), daemon=True)
    player.start()
    stream = wait_for(lambda: [r for r in _pactl_short('sink-inputs')], timeout=4, interval=0.2)
    sink_index = stream[0][1] if stream else None
    sink_name = next((name for name, row in sinks.items() if row[0] == sink_index), None)
    player.join(15)
    user('rm -f /tmp/moto-acceptance-tone.wav')
    suspended = wait_for(lambda: dict((r[1], r[-1]) for r in _pactl_short('sinks')).get(default) in
                         ('SUSPENDED', 'IDLE'), timeout=12)
    return result(bool(stream) and sink_name == default and suspended, default_sink=default,
                  stream_sink=sink_name, state_after=dict((r[1], r[-1]) for r in _pactl_short('sinks')).get(default))


@check
def audio_record(ctx):
    default = user('pactl get-default-source').stdout.strip()
    rec = user('timeout 2.5 parecord --raw --format=s16le --channels=1 --rate=48000 --client-name=moto-acceptance '
               '/tmp/moto-acceptance.raw; python3 -c "import struct,sys; d=open(\'/tmp/moto-acceptance.raw\','
               '\'rb\').read(); n=len(d)//2; s=struct.unpack(\'<%dh\'%n, d[:n*2]); '
               'print(n, max(map(abs, s)) if s else 0, (sum(x*x for x in s)/max(n,1))**0.5)"; '
               'rm -f /tmp/moto-acceptance.raw', timeout=30).stdout.split()
    samples, peak, rms = (int(rec[0]), int(rec[1]), float(rec[2])) if len(rec) == 3 else (0, 0, 0.0)
    suspended = wait_for(lambda: dict((r[1], r[-1]) for r in _pactl_short('sources')).get(default) in
                         ('SUSPENDED', 'IDLE'), timeout=12)
    return result(samples > 48000 and peak > 0 and suspended, {'rms': round(rms, 1), 'peak': peak},
                  default_source=default, samples=samples)


# ---------------------------------------------------------------- full level

@check
def app_launch(ctx, app='Calculator', process='kalk', rounds=2):
    """Launch and close through the launcher by accessible names (tools/ui_launch_check.py)."""
    import ui_launch_check as ui
    enabled = rungic_agent.a11y('state')['enabled']
    if not enabled:
        rungic_agent.ui_enable(True)
        time.sleep(2)
    try:
        if ui.running(process):
            ui.close(process)
        steps = []
        for _ in range(rounds):
            began = time.monotonic()
            step = ui.launch(app, process, False)
            step['launch_s'] = round(time.monotonic() - began, 1)
            step |= ui.close(process)
            steps.append(step)
        ok = all(s['started'] and s['registered'] and s['exited'] for s in steps)
        return result(ok, {'launch_s': max(s['launch_s'] for s in steps)}, rounds=steps)
    finally:
        try:
            _home()
        except Exception:
            pass
        if not enabled:
            rungic_agent.ui_enable(False)


def _phone_output():
    doctor = json.loads(user('kscreen-doctor -j 2>/dev/null').stdout or '{}')
    android = re.search(r'(\d+)x(\d+)', out('wm size | tail -1', 'shell'))
    size = sorted((int(android[1]), int(android[2]))) if android else None
    for o in doctor.get('outputs', []):
        mode = next((m for m in o.get('modes', []) if m['id'] == o.get('currentModeId')), None)
        if o.get('enabled') and mode and sorted((mode['size']['width'], mode['size']['height'])) == size:
            return o
    return None


@check
def display_scale_roundtrip(ctx, other=2.75):
    """KScreen applies a scale to the phone output and reverts it: the display settings path
    (KScreen -> KWin output management -> the Android host) works both ways."""
    output = _phone_output()
    if not output:
        return result(False, error='phone output not found in kscreen-doctor')
    name, original = output['name'], output['scale']
    target = other if abs(original - other) > 0.01 else original - 0.25
    user(f'kscreen-doctor output.{name}.scale.{target}')
    applied = wait_for(lambda: (lambda o: o and abs(o['scale'] - target) < 0.01)(_phone_output()), timeout=8)
    user(f'kscreen-doctor output.{name}.scale.{original}')
    restored = wait_for(lambda: (lambda o: o and abs(o['scale'] - original) < 0.01)(_phone_output()), timeout=8)
    return result(bool(applied) and bool(restored), output=name, original=original, tried=target,
                  applied=bool(applied), restored=bool(restored))


CODEC = r"""
set -e
d=$(mktemp -d /var/tmp/moto-codec.XXXXXX); trap 'rm -rf "$d"' EXIT
bin=/usr/lib/moto-codec/ffmpeg/bin; [ -x $bin/ffprobe ] || bin=/usr/local/lib/moto-codec/ffmpeg/bin
# The /usr/local build's rpath lacked ffmpeg/lib, so its tools picked up the system libav* (fixed in moto-codec).
export LD_LIBRARY_PATH=$bin/../lib:$bin/../..
now() { python3 -c 'import time; print(time.monotonic())'; }
t0=$(now)
gst-launch-1.0 -q videotestsrc num-buffers=FRAMES pattern=ball ! video/x-raw,width=1280,height=720,framerate=30/1 \
  ! motoh264enc ! h264parse ! mp4mux ! filesink location=$d/t.mp4
t1=$(now)
$bin/ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=codec_name,nb_read_frames,width,height \
  -show_entries format=duration -of json $d/t.mp4
t2=$(now)
decoded=$($bin/ffmpeg -v error -c:v h264_moto -i $d/t.mp4 -f framemd5 - 2>/dev/null | grep -vc '^#')
t3=$(now)
echo "@@ encode_s=$(python3 -c "print(round($t1 - $t0, 2))") decode_s=$(python3 -c "print(round($t3 - $t2, 2))") decoded=$decoded"
"""


@check
def codec_roundtrip(ctx, frames=90):
    """Android hardware H.264 encode through the GStreamer element (motoh264enc), then decode through the
    private FFmpeg's h264_moto: frame counts, duration and resolution checked."""
    text = user(CODEC.replace('FRAMES', str(int(frames))), timeout=180)
    body, _, tail = text.stdout.partition('@@ ')
    try:
        probe = json.loads(body)
    except ValueError:
        return result(False, error=(text.stderr or text.stdout)[-1500:])
    stream = (probe.get('streams') or [{}])[0]
    values = dict(kv.split('=', 1) for kv in tail.split())
    encoded = int(stream.get('nb_read_frames') or 0)
    decoded = int(values.get('decoded') or 0)
    duration = float(probe.get('format', {}).get('duration') or 0)
    ok = (encoded == frames and decoded == frames and stream.get('codec_name') == 'h264'
          and (stream.get('width'), stream.get('height')) == (1280, 720) and abs(duration - frames / 30) < 0.2)
    return result(ok, {'encode_s': float(values.get('encode_s') or 0), 'decode_s': float(values.get('decode_s') or 0)},
                  encoded_frames=encoded, decoded_frames=decoded, duration=duration, stream=stream)


@check
def rime_input(ctx):
    """Chinese input, in two automatic parts: the Rime engine and data commit Chinese first candidates
    (moto-rime-check: nihao, zhongguo, ceshi, 300 compositions), and focusing a Qt text field
    (moto-input-probe) brings up the keyboard (its keys appear on AT-SPI). Android key events reach the
    client directly, not through Rime, so typing on the virtual keyboard itself stays a manual item."""
    check = run('for p in /usr/libexec/moto-rime-check /usr/local/libexec/moto-rime-check; do [ -x $p ] && '
                'exec $p; done; exit 9', 'user', timeout=120, check=False)
    engine = check.returncode == 0
    enabled = rungic_agent.a11y('state')['enabled']
    if not enabled:
        rungic_agent.ui_enable(True)
        time.sleep(2)
    probe = next((p for p in ('/usr/bin/moto-input-probe', '/usr/local/bin/moto-input-probe')
                  if run(f'test -x {p}', 'container', check=False).returncode == 0), None)
    keyboard = False
    try:
        if probe:
            user(f'(setsid {probe} >/dev/null 2>&1 &) ; true')
            field = wait_for(lambda: next((f for f in rungic_agent.ui_find('moto-input-probe', role='text')), None)
                             if any(a['name'] == 'moto-input-probe' for a in rungic_agent.a11y('apps')) else None,
                             timeout=20)
            if field:
                rungic_agent.ui_tap('moto-input-probe', field['path'])
                keyboard = bool(wait_for(lambda: [n for n in rungic_agent.ui_find('plasma-keyboard', role='label')
                                                  if n['name'] in ('q', 'a', 'z')], timeout=8))
        return result(engine and keyboard, engine=check.stdout.strip() or f'exit {check.returncode}',
                      keyboard_shown=keyboard, probe=probe)
    finally:
        run('pkill -x moto-input-probe', 'container', check=False)
        try:
            _home()
        except Exception:
            pass
        if not enabled:
            rungic_agent.ui_enable(False)


def _quick_settings():
    """The quick settings fully expanded: the first pull shows one row only, and AT-SPI reports the
    tiles of the collapsed part as showing although they are off screen."""
    run('input swipe 300 2 300 1200 400', 'shell')
    time.sleep(1.2)
    run('input swipe 540 500 540 1800 400', 'shell')
    time.sleep(1.5)


def _tap_label(pattern):
    labels = [n for n in rungic_agent.ui_find('plasmashell', role='label', name=pattern)
              if n.get('extents', [0, 0, 0, 0])[2] > 0]
    if not labels:
        raise RuntimeError(f'no visible label {pattern!r}')
    return rungic_agent.ui_tap('plasmashell', labels[0]['path'])


PROBE_RECORDING = r"""
f=$(ls -t "$HOME"/Videos/screen-recording*.mp4 2>/dev/null | grep -v '\.partial\.mp4$' | head -1)
[ -n "$f" ] && [ -s "$f" ] || exit 3
bin=/usr/lib/moto-codec/ffmpeg/bin; [ -x $bin/ffprobe ] || bin=/usr/local/lib/moto-codec/ffmpeg/bin
export LD_LIBRARY_PATH=$bin/../lib:$bin/../..
echo "$f"; stat -c %Y "$f"
$bin/ffprobe -v error -show_entries stream=codec_type,codec_name,avg_frame_rate -show_entries format=duration -of json "$f"
"""


@check
def screen_recording(ctx, seconds=4):
    """The recording quick setting, pressed as a user would (AT-SPI finds it, a touch toggles it): a playable
    MP4 with a video and an audio track and about the recorded duration. The file is deleted afterwards."""
    enabled = rungic_agent.a11y('state')['enabled']
    if not enabled:
        rungic_agent.ui_enable(True)
        time.sleep(2)
    started = time.time()
    path = None
    try:
        _home()
        _quick_settings()
        _tap_label('^录屏$')
        began = time.monotonic()
        time.sleep(seconds + 1)
        _quick_settings()
        _tap_label('^正在录屏')           # the tile while recording: "正在录屏… / 点击结束录屏"
        elapsed = time.monotonic() - began   # opening the quick settings takes a while over AT-SPI
        text = wait_for(lambda: (lambda r: r if r.returncode == 0 and float(r.stdout.split('\n')[1]) >= started - 2
                                 else None)(user(PROBE_RECORDING)), timeout=30, interval=2)
        if not text:
            journal = run('journalctl --since=-3min -o cat | grep "^Screen recording:" | tail -8', 'container',
                          check=False).stdout
            partial = user('f=$(ls -t "$HOME"/Videos/screen-recording*.partial.mp4 2>/dev/null | head -1); '
                           '[ -n "$f" ] && echo "$(stat -c %Y "$f") $f"').stdout.strip()
            if partial and float(partial.split(' ', 1)[0]) >= started - 2:
                path = partial.split(' ', 1)[1]   # this run's unfinished file only; older ones may be recoverable
            return result(False, error='no finished screen recording in ~/Videos', recorder_log=journal[-1200:])
        lines = text.stdout.split('\n', 2)
        path = lines[0]
        probe = json.loads(lines[2])
        kinds = {st['codec_type']: st for st in probe.get('streams', [])}
        duration = float(probe.get('format', {}).get('duration') or 0)
        ok = 'video' in kinds and 'audio' in kinds and abs(duration - elapsed) <= 3
        return result(ok, {'duration_s': round(duration, 2)}, between_taps_s=round(elapsed, 1),
                      streams=probe.get('streams'), file=path)
    finally:
        if path:
            user(f'rm -f {shlex.quote(path)}')
        try:
            _home()
        except Exception:
            pass
        if not enabled:
            rungic_agent.ui_enable(False)


@check
def compositor_perf(ctx, max_regression=0.15, rounds=2):
    """tools/kwin_pipeline_run.py while scrolling the drawer: KWin paint and SurfaceFlinger present intervals,
    CPU and GPU. Fails when paint p95 or the present interval p95 is worse than the previous release's by
    more than max_regression."""
    import subprocess
    out_dir = ctx['out_dir'] / 'compositor'
    run_ = subprocess.run(['uv', 'run', '--script', str(rungic_device.WORKSPACE / 'tools/kwin_pipeline_run.py'),
                           str(out_dir), '--rounds', str(rounds), '--seconds', '8', '--swipes', '6',
                           '--max-thermal', '2'], capture_output=True, text=True, timeout=1800)
    summary_path = out_dir / 'summary.json'
    if not summary_path.exists():
        return result(False, error=(run_.stderr or run_.stdout)[-1500:])
    summary = json.loads(summary_path.read_text())
    metrics = {'kwin_paint_ms_p95': summary.get('kwin_paint_ms_p95'), 'sf_interval_ms_p95': summary.get('sf_interval_ms_p95'),
               'kwin_cpu_pct': (summary.get('cpu_core_pct') or {}).get('kwin'),
               'plasmashell_cpu_pct': (summary.get('cpu_core_pct') or {}).get('plasmashell'),
               'gpu_busy_pct': summary.get('gpu_busy_pct')}
    regressions = []
    base = ctx.get('previous_metrics', {}).get('perf.compositor', {})
    for key in ('kwin_paint_ms_p95', 'sf_interval_ms_p95'):
        if isinstance(base.get(key), (int, float)) and isinstance(metrics[key], (int, float)) and base[key] > 0:
            if metrics[key] > base[key] * (1 + max_regression):
                regressions.append(f'{key} {base[key]} -> {metrics[key]}')
    return result(not regressions and metrics['kwin_paint_ms_p95'] is not None, metrics,
                  regressions=regressions, compared_with=base or None, summary=str(summary_path))


# ---------------------------------------------------------------- runner

def load():
    return json.loads(SCENARIOS.read_text())


def previous_report(release, scenario_ids):
    """Newest report of another release, for metric comparison."""
    candidates = []
    for report in RESULTS.glob('*/*/report.json'):
        if report.parent.parent.name != (release or 'unreleased'):
            candidates.append(report)
    for report in sorted(candidates, key=lambda p: p.parent.name, reverse=True):
        data = json.loads(report.read_text())
        if any(s['id'] in scenario_ids for s in data['scenarios']):
            return report, data
    return None, None


def compare(current, previous):
    rows = []
    old = {s['id']: s for s in previous['scenarios']}
    for scenario in current['scenarios']:
        before = old.get(scenario['id'])
        if not before:
            continue
        for key, value in scenario.get('metrics', {}).items():
            base = before.get('metrics', {}).get(key)
            if isinstance(value, (int, float)) and isinstance(base, (int, float)) and base:
                rows.append({'scenario': scenario['id'], 'metric': key, 'previous': base, 'current': value,
                             'change': round((value - base) / abs(base), 3)})
    return rows


def run_scenarios(selected, release=None, out_dir=None, since=None):
    spec = load()
    started = time.time()
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir = Path(out_dir) if out_dir else RESULTS / (release or 'unreleased') / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    _, base = previous_report(release, {s['id'] for s in selected})
    ctx = {'spec': spec, 'since': since or started, 'release': release, 'out_dir': out_dir,
           'previous_metrics': {s['id']: s.get('metrics', {}) for s in (base or {}).get('scenarios', [])}}
    rows = []
    for scenario in selected:
        fn = CHECKS.get(scenario['check'])
        began = time.monotonic()
        if fn is None:
            row = {'passed': None, 'metrics': {}, 'details': {'skipped': 'check not implemented'}}
        else:
            try:
                row = fn(ctx, **scenario.get('params', {}))
            except Exception as error:
                row = result(False, error=f'{type(error).__name__}: {error}',
                             trace=traceback.format_exc()[-1500:])
        if row['passed'] is False and scenario.get('screenshot_on_failure', True):
            try:
                shot = Path(rungic_agent.screenshot())
                target = out_dir / f"{scenario['id']}.png"
                shot.replace(target)
                row['details']['screenshot'] = str(target)
            except Exception:
                pass
        row = {'id': scenario['id'], 'title': scenario['title'], 'level': scenario['level'], **row,
               'seconds': round(time.monotonic() - began, 1)}
        rows.append(row)
        mark = {True: 'PASS', False: 'FAIL', None: 'SKIP'}[row['passed']]
        print(f"{mark} {scenario['id']} ({row['seconds']} s)", flush=True)
    report = {'release': release, 'time': stamp, 'scenarios': rows, 'manual': spec.get('manual', []),
              'passed': all(r['passed'] is not False for r in rows),
              'failed_ids': [r['id'] for r in rows if r['passed'] is False]}
    base_path, base = previous_report(release, {r['id'] for r in rows})
    if base:
        report['compared_with'] = str(base_path.relative_to(rungic_device.WORKSPACE))
        report['metric_changes'] = compare(report, base)
    (out_dir / 'report.json').write_text(json.dumps(report, indent=1, ensure_ascii=False) + '\n')
    report['path'] = str(out_dir / 'report.json')
    return report


def run_level(level, release=None, out_dir=None, since=None):
    levels = {'smoke': {'smoke'}, 'full': {'smoke', 'full'}}[level]
    return run_scenarios([s for s in load()['scenarios'] if s['level'] in levels], release, out_dir, since)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    for name in ('smoke', 'full'):
        p = sub.add_parser(name); p.add_argument('--release')
    p = sub.add_parser('run'); p.add_argument('ids', nargs='+'); p.add_argument('--release')
    p = sub.add_parser('compare'); p.add_argument('a'); p.add_argument('b')
    a = parser.parse_args()
    if a.cmd == 'compare':
        print(json.dumps(compare(json.loads(Path(a.b).read_text()), json.loads(Path(a.a).read_text())), indent=1))
        return 0
    if a.cmd == 'run':
        chosen = [s for s in load()['scenarios'] if s['id'] in a.ids]
        report = run_scenarios(chosen, a.release)
    else:
        report = run_level(a.cmd, a.release)
    print(json.dumps({k: report[k] for k in ('passed', 'failed_ids', 'path')}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
