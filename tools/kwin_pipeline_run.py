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
                      [--zerocopy on,off] [--kwin-env KEY=VALUE ...]

--zerocopy alternates the host's debug.moto.zerocopy property per round (ABBA)
and summarises each setting separately; the property is left on afterwards.
--kwin-env sets environment variables for kwin_wayland through a runtime drop-in
and restarts the session; the drop-in is removed and the session restarted after.

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
import rungic_agent  # noqa: E402
import rungic_trace  # noqa: E402
import rungic_trace_report  # noqa: E402
from rungic_device import PLASMA, run  # noqa: E402


DROPIN = '/run/user/1000/systemd/user/plasma-plasmashell.service.d/90-moto-rhi-audit.conf'
KWIN_DROPIN = '/run/user/1000/systemd/user/plasma-kwin_wayland.service.d/90-moto-env-audit.conf'


def kwin_env(pairs):
    """Restart the desktop with extra kwin_wayland environment (empty list restores)."""
    if pairs:
        text = '[Service]\\n' + ''.join(f'Environment={p}\\n' for p in pairs)
        run(f"mkdir -p {Path(KWIN_DROPIN).parent} && printf '%b' '{text}' > {KWIN_DROPIN}", 'user')
    else:
        run(f'rm -f {KWIN_DROPIN}', 'user', check=False)
    run('systemctl --user daemon-reload', 'user')
    run(f'{PLASMA} restart-session', 'root', timeout=240)
    time.sleep(12)


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
    parser.add_argument('--zerocopy', help='comma-separated settings to alternate, e.g. on,off')
    parser.add_argument('--kwin-env', action='append', default=[], help='KEY=VALUE for kwin_wayland')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rungic_agent.ui_enable(False)
    rounds = []
    if args.kwin_env:
        kwin_env(args.kwin_env)
    drivers = plasmashell_rhi(args.plasmashell_rhi) if args.plasmashell_rhi else None
    try:
        rounds = measure(args)
    finally:
        if args.plasmashell_rhi:
            plasmashell_rhi(None)
        if args.kwin_env:
            kwin_env([])
        if args.zerocopy:
            run('setprop debug.moto.zerocopy 1', 'root')
    if args.zerocopy:
        for setting in args.zerocopy.split(','):
            summarise(args, [r for r in rounds if r.get('zerocopy') == setting], drivers, f'-zerocopy-{setting}')
    else:
        summarise(args, rounds, drivers)


def measure(args):
    rounds = []
    settings = args.zerocopy.split(',') if args.zerocopy else [None]
    order = [settings[(i // len(settings)) % 2 and -1 - i % len(settings) or i % len(settings)]
             for i in range(args.rounds * len(settings))]  # ABBA
    for i, setting in enumerate(order, 1):
        if setting:
            run(f"setprop debug.moto.zerocopy {'0' if setting == 'off' else '1'}", 'root')
            time.sleep(1)  # the host re-reads the property every 500 ms
        thermal = compbench_run.wait_cool(args.max_thermal)
        run(f'{PLASMA} home', 'root', check=False)
        time.sleep(1)
        run('input swipe 540 2000 540 600 250', 'shell')  # open the app drawer
        time.sleep(2)
        trace = rungic_trace.capture(args.seconds, f'kwin-pipeline-{i}', during=rungic_trace.swipes(args.swipes, 500, 0.25))
        report = rungic_trace_report.analyse(trace, 1.5, args.seconds)
        report['thermal_before'] = thermal
        report['zerocopy'] = setting
        report['host_native_stats'] = rungic_agent.host_request('native-stats')['stats'].split('zero_copy', 1)[-1]
        report['thermal_after'] = compbench_run.thermal_status()
        (args.out / f'round-{i}{"-zerocopy-" + setting if setting else ""}.json').write_text(json.dumps(report, indent=1))
        rounds.append(report)
        print(f"round {i} {setting or ''}: paint p50={report['kwin'].get('Paint', {}).get('p50')} "
              f"gpuwait p50={report['kwin'].get('GpuWait', {}).get('p50')} host/s={report['host_queue']['per_s']}",
              flush=True)
    run(f'{PLASMA} home', 'root', check=False)
    return rounds


def summarise(args, rounds, drivers, suffix=''):
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
        'kwin_env': args.kwin_env,
        'host_native_stats_last': rounds[-1].get('host_native_stats') if rounds else None,
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
        'bw_mbps': {dev: round(statistics.median(r.get('gpu', {}).get('bw_mbps', {}).get(dev, 0) for r in rounds), 1)
                    for dev in sorted({d for r in rounds for d in r.get('gpu', {}).get('bw_mbps', {})})},
        'gpu_total_ms': {name: round(statistics.median(gpu_key(r, name).get('total_ms', 0) for r in rounds), 2)
                         for name in ('kwin_wayland', 'plasmashell', 'dev.moto.plasma')},
        'gpu_submission_ms_mean': {name: round(statistics.median(gpu_key(r, name).get('mean', 0) for r in rounds), 3)
                                   for name in ('kwin_wayland', 'plasmashell', 'dev.moto.plasma')},
    }
    (args.out / f'summary{suffix}.json').write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
