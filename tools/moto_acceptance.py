#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Post-release acceptance on the phone (docs/61): scenarios from plasma/release/acceptance.json.

  moto_acceptance.py smoke [--release V]     every deploy; about two minutes
  moto_acceptance.py full [--release V]      release candidates: smoke plus the full scenarios
  moto_acceptance.py run ID... [--release V] selected scenarios
  moto_acceptance.py compare A B             metrics of two reports (paths)

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
import moto_agent  # noqa: E402
import moto_device  # noqa: E402
from moto_device import out, run  # noqa: E402

SCENARIOS = moto_device.WORKSPACE / 'plasma/release/acceptance.json'
RESULTS = moto_device.WORKSPACE / '.work/acceptance'
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
def session_ready(ctx):
    text = run('test -f /run/user/1000/moto-session.env && echo env; pidof kwin_wayland >/dev/null && echo kwin; '
               'pidof plasmashell >/dev/null && echo shell', 'container', check=False).stdout.split()
    return result({'env', 'kwin', 'shell'} <= set(text), present=text)


@check
def user_units(ctx, critical=()):
    failed = user('systemctl --user --failed --no-legend --plain | cut -d" " -f1').stdout.split()
    bad = [u for u in failed if any(re.fullmatch(p.replace('*', '.*'), u) for p in critical)]
    return result(not bad, {'failed_units': len(failed)}, failed=failed, critical_failed=bad)


@check
def new_crashes(ctx):
    since = max(1.0, time.time() - ctx['since'] + 30)
    groups = moto_agent.crash_groups(since)['groups']
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
    run(f'{moto_device.PLASMA} hide-keyboard', 'root', check=False)
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
    fields = moto_agent.ui_find('plasmashell', role='text', name='Search')
    if not fields:
        raise RuntimeError('drawer search field not showing')
    return fields[0]


@check
def input_text(ctx, text='Calcul', expect='Calculator', absent='Clock'):
    """Android text input into the drawer search. Kirigami's search field exposes no AT-SPI text,
    so the effect is read instead: the drawer filters to the matching launcher entry."""
    enabled = moto_agent.a11y('state')['enabled']
    if not enabled:
        moto_agent.ui_enable(True)
        time.sleep(2)
    import ui_launch_check as ui
    try:
        field = _drawer_search()

        def labels():
            return {(n['path'], n['name']) for n in moto_agent.ui_find('plasmashell', role='label')}
        # The full grid stays "showing" under the results over AT-SPI, so look at what appears.
        before = labels()
        moto_agent.ui_press('plasmashell', field['path'], 'SetFocus')
        time.sleep(0.4)
        run(f'input text {shlex.quote(text)}', 'shell')
        new = wait_for(lambda: (lambda n: n if expect in n else None)({name for _, name in labels() - before}),
                       timeout=6) or {name for _, name in labels() - before}
        return result(expect in new and absent not in new, sent=text, results=sorted(new)[:12])
    finally:
        try:
            _home()
        except Exception:
            pass
        if not enabled:
            moto_agent.ui_enable(False)


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
while len(frames) < count and time.monotonic() - start < 25:
    sample = sink.emit('try-pull-sample', 3 * Gst.SECOND)
    if sample is None:
        break
    caps = caps or sample.get_caps().to_string()
    buf = sample.get_buffer()
    ok, info = buf.map(Gst.MapFlags.READ)
    data = info.data[::211]
    mean = sum(data) / len(data)
    std = (sum((x - mean) ** 2 for x in data) / len(data)) ** 0.5
    frames.append({'pts': buf.pts, 'mean': round(mean, 1), 'std': round(std, 1)})
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
    return result(len(got) == frames and monotonic and varied >= frames // 2 and idle,
                  {'fps': round(fps, 1) if fps else None, 'first_frames_s': data['seconds'], 'mean_luma': luma},
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
    ctx = {'spec': spec, 'since': since or started, 'release': release}
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir = Path(out_dir) if out_dir else RESULTS / (release or 'unreleased') / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
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
        report['compared_with'] = str(base_path.relative_to(moto_device.WORKSPACE))
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
