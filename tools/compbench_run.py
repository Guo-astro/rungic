#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["perfetto>=0.58", "pandas>=2"]
# ///
# SPDX-License-Identifier: MIT
"""Run plasma/bench/compbench as an interleaved GLES/Vulkan matrix on the phone.

The Plasma session is stopped so the Android host serves only compbench, then
restored (also on failure). Each run is traced (perfetto + KGSL instance) so
GPU execution time per frame comes from the kernel, not from the benchmark.
Accessibility is switched off first; the phone must be awake with the desktop
APK in the foreground.

  compbench_run.py OUT_DIR [--rounds 3] [--variant api:sync ...] [--layers 3] [--taps 1]
"""
import argparse
import json
import shlex
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rungic_agent  # noqa: E402
import rungic_device  # noqa: E402
import rungic_trace  # noqa: E402
import rungic_trace_report  # noqa: E402
from rungic_device import PLASMA, run  # noqa: E402

BINARY = '/usr/bin/rungic-compbench'


def bench(variant, args, seconds, warmup, box):
    api, sync = variant.split(':')
    extra = ' --unthrottled' if args.unthrottled else ''
    # With the Plasma session stopped the user session environment is gone; compbench
    # only needs the desktop UID, the GPU environment and the host socket path.
    command = (f'. /etc/plasma/gpu-env; unset WAYLAND_DISPLAY; exec {BINARY} --api {api} --sync {sync} '
               f'--layers {args.layers} --taps {args.taps} --seconds {seconds} --warmup {warmup}{extra}')
    box['result'] = run(f'exec runuser -u "$(getent passwd 1000 | cut -d: -f1)" -- sh -c {shlex.quote(command)}',
                        'container', timeout=seconds + warmup + 60, check=False)


def thermal_status():
    text = rungic_device.out("dumpsys thermalservice | grep -m1 'Thermal Status'", 'shell')
    return int(text.split(':')[1])


def wait_cool(limit=0, timeout=1800):
    """Throttling distorts CPU/GPU numbers; wait until Android reports thermal status <= limit."""
    deadline = time.monotonic() + timeout
    while (status := thermal_status()) > limit:
        if time.monotonic() > deadline:
            raise RuntimeError(f'phone still at thermal status {status}')
        print(f'thermal status {status}; waiting', flush=True)
        time.sleep(30)
    return status


def one_run(variant, args, out, index):
    box = {'thermal_before': wait_cool(args.max_thermal)}
    worker = threading.Thread(target=bench, args=(variant, args, args.seconds, args.warmup, box))

    def during():
        worker.start()
        worker.join()

    trace = rungic_trace.capture(args.seconds + args.warmup + 2, f'compbench-{index}-{variant.replace(":", "-")}',
                               'light', during=during)
    result = box['result']
    if result.returncode:
        raise RuntimeError(f'{variant}: {result.stderr[-800:] or result.stdout[-800:]}')
    summary = json.loads(result.stdout[result.stdout.index('{'):])
    # Only the measured window: the benchmark starts ~1.5 s into the trace, plus warm-up.
    report = rungic_trace_report.analyse(trace, 1.5 + args.warmup + 0.5, 1.5 + args.warmup + args.seconds)
    gpu = {k: v for k, v in report.get('gpu', {}).get('per_process', {}).items() if 'compbench' in k}
    summary['kgsl'] = next(iter(gpu.values()), None)
    summary['gpu_busy_pct'] = report.get('gpu', {}).get('busy_pct')
    summary['host_queue'] = report.get('host_queue')
    summary['sf_display'] = report.get('sf_display')
    summary['cpu'] = report.get('cpu')
    summary['gpu_freq_mhz_seconds'] = report.get('gpu_freq_mhz_seconds')
    summary['trace'] = str(trace)
    summary['thermal_before'] = box['thermal_before']
    summary['thermal_after'] = thermal_status()
    (out / f'{index:02d}-{variant.replace(":", "-")}.json').write_text(json.dumps(summary, indent=1))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('out', type=Path)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--variant', action='append', help='api:sync, e.g. gles:finish vulkan:fence')
    parser.add_argument('--layers', type=int, default=3)
    parser.add_argument('--taps', type=int, default=1)
    parser.add_argument('--seconds', type=float, default=12)
    parser.add_argument('--warmup', type=float, default=3)
    parser.add_argument('--unthrottled', action='store_true')
    parser.add_argument('--keep-session', action='store_true', help='do not stop Plasma (compbench overlays it)')
    parser.add_argument('--max-thermal', type=int, default=0, help='start a run only at or below this thermal status')
    args = parser.parse_args()
    variants = args.variant or ['gles:finish', 'vulkan:finish']
    args.out.mkdir(parents=True, exist_ok=True)
    order = []
    for r in range(args.rounds):  # ABBA-style alternation against drift and warm-up effects
        order += variants if r % 2 == 0 else list(reversed(variants))
    rungic_agent.ui_enable(False)
    meta = {'order': order, 'args': vars(args) | {'out': str(args.out)}, 'status_before': rungic_agent.status()}
    results = []
    try:
        if not args.keep_session:
            run('systemctl stop rungic-plasma-session.service', 'container', timeout=60)
            time.sleep(3)
        for index, variant in enumerate(order, 1):
            summary = one_run(variant, args, args.out, index)
            results.append((variant, summary))
            print(f"{index:2d} {variant:15s} fps={summary['fps']:.1f} cpu%={summary['process_cpu_core_pct']:.1f} "
                  f"wait_p50={summary['wait_ms']['p50']:.2f} gpu_mean={(summary['kgsl'] or {}).get('mean')}", flush=True)
            time.sleep(2)
    finally:
        if not args.keep_session:
            run(f'{PLASMA} restart-session', 'root', timeout=240, check=False)
        meta['status_after'] = rungic_agent.status()
        (args.out / 'meta.json').write_text(json.dumps(meta, indent=1, ensure_ascii=False))

    table = {}
    for variant in variants:
        runs = [s for v, s in results if v == variant]
        med = lambda f: round(statistics.median(f(s) for s in runs), 3)
        table[variant] = {
            'runs': len(runs),
            'fps': med(lambda s: s['fps']),
            'process_cpu_core_pct': med(lambda s: s['process_cpu_core_pct']),
            'render_cpu_ms_p50': med(lambda s: s['render_cpu_ms']['p50']),
            'wait_ms_p50': med(lambda s: s['wait_ms']['p50']),
            'wait_ms_p95': med(lambda s: s['wait_ms']['p95']),
            'present_interval_ms_p95': med(lambda s: s['present_interval_ms'].get('p95', 0)),
            'gpu_ms_per_submission_mean': med(lambda s: (s['kgsl'] or {}).get('mean', 0)),
            'gpu_busy_pct': med(lambda s: s['gpu_busy_pct'] or 0),
        }
    (args.out / 'summary.json').write_text(json.dumps(table, indent=1))
    print(json.dumps(table, indent=1))


if __name__ == '__main__':
    main()
