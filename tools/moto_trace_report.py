#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["perfetto>=0.58", "pandas>=2"]
# ///
# SPDX-License-Identifier: MIT
"""Summarise a tools/moto_trace.py capture: presentation, KWin phases, CPU and GPU per process.

Inputs: <name>.pftrace (Android perfetto) and <name>.pftrace.kgsl.txt (tracefs
instance with KGSL events, same boot clock). Durations are milliseconds.

- host_queue: the desktop APK's outer queueBuffer calls (one per buffer it hands
  to SurfaceFlinger), their spacing and duration.
- sf_display: SurfaceFlinger display frames (all layers), present spacing and jank types.
- kwin: begin/end pairs of KWin FTrace markers (Paint, GpuWait, Import); KWin
  6.6.6+moto6 writes them unbuffered, older builds batch them (invalid times).
- cpu: scheduled time per process, as % of one core over the window.
- gpu: KGSL retire-start on the GPU's 19.2 MHz always-on counter per
  submitting process, and the union of all submissions as GPU busy %.
"""
import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

from perfetto.trace_processor import TraceProcessor, TraceProcessorConfig

GPU_TICK_HZ = 19.2e6
PROCESSES = {'kwin': '%kwin_wayland', 'plasmashell': '%plasmashell', 'apk': 'dev.moto.plasma',
             'surfaceflinger': '%surfaceflinger'}
MARKER = re.compile(r'^(?P<name>.+?) begin_ctx=(?P<ctx>\d+)$|^(?P<ename>.+?) end_ctx=(?P<ectx>\d+)$')
KGSL = re.compile(r'^\s*(?P<task>.+)-(?P<tid>\d+)\s+\(\s*(?P<tgid>\d+)\)\s+\[\d+\]\s+\S+\s+'
                  r'(?P<ts>\d+\.\d+): (?P<event>\w+): (?P<args>.*)$')


def stats(values):
    if not values:
        return {'n': 0}
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]
    return {'n': len(values), 'mean': round(statistics.fmean(values), 3), 'p50': round(pick(.5), 3),
            'p95': round(pick(.95), 3), 'p99': round(pick(.99), 3), 'max': round(ordered[-1], 3)}


def rows(tp, sql):
    return list(tp.query(sql))


def analyse(trace, start_s=None, end_s=None):
    tp = TraceProcessor(trace=str(trace), config=TraceProcessorConfig(ingest_ftrace_in_raw=True, load_timeout=180))
    bounds = rows(tp, 'select start_ts, end_ts from trace_bounds')[0]
    t0 = bounds.start_ts + int((start_s or 0) * 1e9)
    t1 = bounds.start_ts + int(end_s * 1e9) if end_s else bounds.end_ts
    window = (t1 - t0) / 1e9
    pids = {key: [r.pid for r in rows(tp, f"select pid from process where name like '{pattern}'")]
            for key, pattern in PROCESSES.items()}
    result = {'trace': str(trace), 'window_s': round(window, 3), 'pids': pids}

    # The desktop APK's native EGL SurfaceView has no per-layer frame timeline on
    # this build, so use its queueBuffer slices (atrace gfx) as host submissions
    # and SurfaceFlinger's display frames (all layers) as the present timeline.
    # Surface::queueBuffer and BufferQueueProducer::queueBuffer are both traced as
    # "queueBuffer" and nest; count only the outer one (one per presented buffer).
    queue = rows(tp, f"""select s.ts, s.dur from slice s join thread_track tt on s.track_id = tt.id
        join thread t using(utid) join process p using(upid) left join slice parent on s.parent_id = parent.id
        where s.name = 'queueBuffer' and p.name = 'dev.moto.plasma' and s.ts >= {t0} and s.ts < {t1}
          and (parent.name is null or parent.name != 'queueBuffer') order by s.ts""")
    result['host_queue'] = {'buffers': len(queue), 'per_s': round(len(queue) / window, 2) if window else None,
                            'interval_ms': stats([(b.ts - a.ts) / 1e6 for a, b in zip(queue, queue[1:])]),
                            'queueBuffer_ms': stats([q.dur / 1e6 for q in queue if q.dur and q.dur > 0])}
    frames = rows(tp, f"""select f.ts, f.dur, f.jank_type from actual_frame_timeline_slice f
        join process p using(upid) where p.name like '%surfaceflinger' and f.ts >= {t0} and f.ts < {t1}
        order by f.ts""")
    presents = sorted(f.ts + f.dur for f in frames if f.dur and f.dur > 0)
    jank = defaultdict(int)
    for f in frames:
        jank[f.jank_type or 'None'] += 1
    result['sf_display'] = {'frames': len(frames), 'per_s': round(len(presents) / window, 2) if window else None,
                            'interval_ms': stats([(b - a) / 1e6 for a, b in zip(presents, presents[1:])]),
                            'jank_types': dict(jank)}

    # KWin FTrace markers.
    if pids['kwin']:
        marks = rows(tp, f"""select e.ts, a.display_value buf from ftrace_event e
            join thread t using(utid) join process p using(upid)
            join args a on a.arg_set_id = e.arg_set_id and a.key = 'buf'
            where e.name = 'print' and p.pid in ({','.join(map(str, pids['kwin']))})
              and e.ts >= {t0} and e.ts < {t1} order by e.ts""")
        open_, phases, batched = {}, defaultdict(list), 0
        for m in marks:
            lines = [l for l in (m.buf or '').splitlines() if l]
            batched += len(lines) > 1
            for line in lines:
                x = MARKER.match(line)
                if not x:
                    continue
                if x['ctx']:
                    open_[(x['name'], x['ctx'])] = m.ts
                elif (x['ename'], x['ectx']) in open_:
                    begin = open_.pop((x['ename'], x['ectx']))
                    phases[x['ename'].split(' (')[0]].append((m.ts - begin) / 1e6)
        result['kwin'] = {name: stats(v) for name, v in phases.items()}
        result['kwin']['batched_print_events'] = batched

    # CPU time per process.
    cpu = {}
    for key, plist in pids.items():
        if plist:
            total = rows(tp, f"""select coalesce(sum(min(s.ts + s.dur, {t1}) - max(s.ts, {t0})), 0) ns from sched s
                join thread t using(utid) join process p using(upid)
                where p.pid in ({','.join(map(str, plist))}) and s.ts < {t1} and s.ts + s.dur > {t0}""")[0].ns
            cpu[key] = {'ms': round(total / 1e6, 1), 'core_pct': round(100 * total / 1e9 / window, 1)}
    result['cpu'] = cpu

    freq = rows(tp, f"""select c.ts, c.value from counter c join gpu_counter_track t on c.track_id = t.id
        where t.name = 'gpufreq' order by c.ts""")
    if freq:
        weighted, previous = defaultdict(float), None
        for sample in freq + [type('end', (), {'ts': t1, 'value': None})()]:
            if previous is not None:
                span = min(sample.ts, t1) - max(previous.ts, t0)
                if span > 0:
                    weighted[int(previous.value / 1e3)] += span / 1e9  # counter is in kHz
            previous = sample
        result['gpu_freq_mhz_seconds'] = {k: round(v, 3) for k, v in sorted(weighted.items())}
    names = {r.pid: r.name for r in rows(tp, 'select pid, name from process where pid is not null')}
    tp.close()

    kgsl = Path(str(trace) + '.kgsl.txt')
    if kgsl.exists():
        result['gpu'] = analyse_kgsl(kgsl, t0 / 1e9, t1 / 1e9, window, names)
    return result


def analyse_kgsl(path, t0, t1, window, names):
    owner, spans = {}, []
    for line in path.read_text(errors='replace').splitlines():
        m = KGSL.match(line)
        if not m:
            continue
        args = dict(kv.split('=', 1) for kv in re.findall(r'[\w/]+=[^ ,]+', m['args']))
        if m['event'] == 'adreno_cmdbatch_queued':
            owner.setdefault(args['ctx'], int(m['tgid']))
        elif m['event'] == 'adreno_cmdbatch_retired' and t0 <= float(m['ts']) < t1:
            start, retire = int(args['start']), int(args['retire'])
            if retire > start:
                spans.append((args['ctx'], start, retire))
    per_process, busy = defaultdict(list), 0
    for ctx, start, retire in spans:
        per_process[owner.get(ctx, -1)].append((retire - start) / GPU_TICK_HZ * 1e3)
    last = None
    for _, start, retire in sorted(spans, key=lambda s: s[1]):
        if last is None or start > last:
            busy += retire - start
            last = retire
        elif retire > last:
            busy += retire - last
            last = retire
    return {'busy_pct': round(100 * busy / GPU_TICK_HZ / window, 2) if window else None,
            'per_process': {f"{names.get(pid, '?')}[{pid}]": {**stats(d), 'total_ms': round(sum(d), 2)}
                            for pid, d in sorted(per_process.items(), key=lambda kv: -sum(kv[1]))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--start', type=float, help='seconds from trace start')
    parser.add_argument('--end', type=float, help='seconds from trace start')
    args = parser.parse_args()
    print(json.dumps(analyse(args.trace, args.start, args.end), indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
