#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["perfetto>=0.58", "pandas>=2"]
# ///
# SPDX-License-Identifier: MIT
"""Per-stage timing of the real desktop pipeline while scrolling the app drawer.

KWin (moto6 FTrace: Paint, GpuWait, Import) -> Android host queueBuffer ->
SurfaceFlinger, plus CPU per process and KGSL GPU time per process. Each round
starts from the home screen with the drawer opened, accessibility off and
Android thermal status <= --max-thermal.

  kwin_pipeline_run.py OUT_DIR [--rounds 3] [--seconds 10] [--swipes 8] [--plasmashell-rhi vulkan]

--plasmashell-rhi runs plasmashell's Qt Quick on another RHI backend through a
runtime drop-in (/run/user/1000/systemd/user, gone after reboot), verified from
the loaded driver, and restores the normal service afterwards.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compbench_run  # noqa: E402
import moto_agent  # noqa: E402
import moto_trace  # noqa: E402
import moto_trace_report  # noqa: E402
from moto_device import PLASMA, run  # noqa: E402


DROPIN = '/run/user/1000/systemd/user/plasma-plasmashell.service.d/90-moto-rhi-audit.conf'


def plasmashell_rhi(backend):
    """Restart plasmashell with QSG_RHI_BACKEND=backend (None restores); returns the loaded GPU driver."""
    if backend:
        text = f'[Service]\nEnvironment=QSG_RHI_BACKEND={backend}\n'
        run(f"mkdir -p {Path(DROPIN).parent} && printf '%b' '{text}' > {DROPIN}", 'user')
    else:
        run(f'rm -f {DROPIN}', 'user')
    run('systemctl --user daemon-reload && systemctl --user restart plasma-plasmashell.service', 'user', timeout=120)
    time.sleep(8)
    maps = run('grep -oE "libvulkan_freedreno.so|kgsl_dri.so|freedreno_dri.so|libgallium[^ ]*" '
               '/proc/$(pgrep -xo plasmashell)/maps | sort -u', 'container', check=False).stdout.split()
    return maps


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('out', type=Path)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--swipes', type=int, default=8)
    parser.add_argument('--max-thermal', type=int, default=0)
    parser.add_argument('--plasmashell-rhi', choices=['vulkan', 'opengl'])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    moto_agent.ui_enable(False)
    rounds = []
    drivers = plasmashell_rhi(args.plasmashell_rhi) if args.plasmashell_rhi else None
    try:
        rounds = measure(args)
    finally:
        if args.plasmashell_rhi:
            plasmashell_rhi(None)
    summarise(args, rounds, drivers)


def measure(args):
    rounds = []
    for i in range(1, args.rounds + 1):
        thermal = compbench_run.wait_cool(args.max_thermal)
        run(f'{PLASMA} home', 'root', check=False)
        time.sleep(1)
        run('input swipe 540 2000 540 600 250', 'shell')  # open the app drawer
        time.sleep(2)
        trace = moto_trace.capture(args.seconds, f'kwin-pipeline-{i}', during=moto_trace.swipes(args.swipes, 500, 0.25))
        report = moto_trace_report.analyse(trace, 1.5, args.seconds)
        report['thermal_before'] = thermal
        report['thermal_after'] = compbench_run.thermal_status()
        (args.out / f'round-{i}.json').write_text(json.dumps(report, indent=1))
        rounds.append(report)
        print(f"round {i}: paint p50={report['kwin'].get('Paint', {}).get('p50')} "
              f"gpuwait p50={report['kwin'].get('GpuWait', {}).get('p50')} host/s={report['host_queue']['per_s']}",
              flush=True)
    run(f'{PLASMA} home', 'root', check=False)
    return rounds


def summarise(args, rounds, drivers):
    def med(path):
        values = []
        for r in rounds:
            v = r
            for key in path:
                v = v.get(key, {}) if isinstance(v, dict) else {}
            if isinstance(v, (int, float)):
                values.append(v)
        return round(statistics.median(values), 3) if values else None

    gpu_key = lambda r, name: next((v for k, v in r['gpu']['per_process'].items() if name in k), {})
    summary = {
        'rounds': len(rounds), 'plasmashell_rhi': args.plasmashell_rhi or 'default', 'plasmashell_drivers': drivers,
        'kwin_paint_ms_p50': med(['kwin', 'Paint', 'p50']), 'kwin_paint_ms_p95': med(['kwin', 'Paint', 'p95']),
        'kwin_gpuwait_ms_p50': med(['kwin', 'GpuWait', 'p50']), 'kwin_gpuwait_ms_p95': med(['kwin', 'GpuWait', 'p95']),
        'kwin_import_ms_p50': med(['kwin', 'Import', 'p50']),
        'kwin_paints': med(['kwin', 'Paint', 'n']),
        'host_buffers_per_s': med(['host_queue', 'per_s']),
        'host_interval_ms_p50': med(['host_queue', 'interval_ms', 'p50']),
        'host_interval_ms_p95': med(['host_queue', 'interval_ms', 'p95']),
        'host_queueBuffer_ms_p50': med(['host_queue', 'queueBuffer_ms', 'p50']),
        'sf_interval_ms_p95': med(['sf_display', 'interval_ms', 'p95']),
        'cpu_core_pct': {k: med(['cpu', k, 'core_pct']) for k in ('kwin', 'plasmashell', 'apk', 'surfaceflinger')},
        'gpu_busy_pct': med(['gpu', 'busy_pct']),
        'gpu_total_ms': {name: round(statistics.median(gpu_key(r, name).get('total_ms', 0) for r in rounds), 2)
                         for name in ('kwin_wayland', 'plasmashell', 'dev.moto.plasma')},
        'gpu_submission_ms_mean': {name: round(statistics.median(gpu_key(r, name).get('mean', 0) for r in rounds), 3)
                                   for name in ('kwin_wayland', 'plasmashell', 'dev.moto.plasma')},
    }
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
