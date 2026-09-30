#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""System-wide perfetto traces covering Android, the Plasma container and the Adreno GPU.

The container shares Android's kernel, so one Android perfetto session sees
KWin/plasmashell threads, SurfaceFlinger, the desktop APK and KGSL command
batches together. KWin's own FTrace markers ("Paint (<output>) begin_ctx=N")
reach the same buffer once tracefs is mounted in the container
(system/diagnostics) and /FTrace is enabled; capture() enables it only for
the capture and restores the previous state.

Analysis uses Perfetto's trace_processor (Python package `perfetto`), see
tools/rungic_trace_report.py.
"""
import argparse
import subprocess
import threading
import time
from pathlib import Path

import rungic_device
from rungic_device import run

DIAG_DIR = rungic_device.WORKSPACE / '.work/diag'
REMOTE_DIR = '/data/misc/perfetto-traces'

FTRACE_EVENTS = {
    'frame': [
        'sched/sched_switch', 'sched/sched_waking', 'sched/sched_process_exit', 'task/task_newtask',
        'task/task_rename', 'power/cpu_frequency', 'power/cpu_idle', 'power/gpu_frequency',
        'dma_fence/dma_fence_signaled', 'ftrace/print',
    ],
    # Smaller traces for repeated benchmark runs over a slow adb link.
    'light': ['sched/sched_switch', 'power/gpu_frequency', 'ftrace/print'],
}
ATRACE = {'frame': ['gfx', 'view', 'input', 'sched', 'freq'], 'light': ['gfx']}
# Perfetto on this user build only accepts its allowlisted ftrace events, so the
# KGSL events go to a separate tracefs instance on the same boot clock.
GPU_INSTANCE = '/sys/kernel/tracing/instances/rungic_gpu'
GPU_EVENTS = ['adreno_cmdbatch_queued', 'adreno_cmdbatch_submitted', 'adreno_cmdbatch_retired',
              'adreno_drawctxt_switch', 'kgsl_context_create', 'kgsl_pwrlevel']


# Qualcomm bus DCVS: bwmon's measured DDR/LLCC bandwidth per sampling window.
BW_EVENTS = ['dcvs/bw_hwmon_meas']


def gpu_instance_start():
    enable = '\n'.join(f'echo 1 > $I/events/kgsl/{e}/enable' for e in GPU_EVENTS)
    enable += ''.join(f'\n[ ! -e $I/events/{e}/enable ] || echo 1 > $I/events/{e}/enable' for e in BW_EVENTS)
    run(f'''set -e
I={GPU_INSTANCE}
[ ! -d $I ] || rmdir $I
mkdir $I
echo boot > $I/trace_clock
echo 16384 > $I/buffer_size_kb
echo 1 > $I/options/record-tgid
{enable}
echo 1 > $I/tracing_on
''', 'root')


def gpu_instance_stop(remote):
    run(f'''I={GPU_INSTANCE}
echo 0 > $I/tracing_on
cat $I/trace > {remote}; chmod 644 {remote}
rmdir $I
''', 'root', check=False)


def config(duration_s, preset='frame', buffer_mb=96):
    events = '\n'.join(f'      ftrace_events: "{e}"' for e in FTRACE_EVENTS[preset])
    categories = '\n'.join(f'      atrace_categories: "{c}"' for c in ATRACE[preset])
    return f'''
buffers {{ size_kb: {buffer_mb * 1024} fill_policy: RING_BUFFER }}
buffers {{ size_kb: 4096 fill_policy: RING_BUFFER }}
data_sources {{ config {{ name: "linux.ftrace" target_buffer: 0 ftrace_config {{
{events}
{categories}
      atrace_apps: "{rungic_device.apk()}"
      buffer_size_kb: 16384
      drain_period_ms: 250
      symbolize_ksyms: false
}} }} }}
data_sources {{ config {{ name: "linux.process_stats" target_buffer: 1
    process_stats_config {{ scan_all_processes_on_start: true proc_stats_poll_ms: 1000 }} }} }}
data_sources {{ config {{ name: "android.surfaceflinger.frametimeline" target_buffer: 0 }} }}
data_sources {{ config {{ name: "linux.sys_stats" target_buffer: 1
    sys_stats_config {{ stat_period_ms: 250 stat_counters: STAT_CPU_TIMES }} }} }}
duration_ms: {int(duration_s * 1000)}
'''


def kwin_ftrace(enable):
    """Toggle KWin's FTrace markers over D-Bus; returns the previous state (None if unavailable)."""
    result = run(f'''
test -e /sys/kernel/tracing/trace_marker || exit 3
qdbus6 org.kde.KWin /FTrace org.freedesktop.DBus.Properties.Get org.kde.kwin.FTrace isEnabled
qdbus6 org.kde.KWin /FTrace org.kde.kwin.FTrace.setEnabled {'true' if enable else 'false'}
''', 'user', check=False)
    lines = result.stdout.split()
    return (lines[0] == 'true') if result.returncode == 0 and lines else None


def capture(duration_s=10, label='trace', preset='frame', during=None):
    """Record a trace; `during` (callable) runs on the host while recording. Returns the local path."""
    stamp = time.strftime('%Y%m%d-%H%M%S')
    name = f'rungic-{stamp}-{label}.pftrace'
    local = DIAG_DIR / name
    local.parent.mkdir(parents=True, exist_ok=True)
    # Enable KWin's markers only once perfetto is recording: with tracing off the
    # kernel rejects trace_marker writes (EBADF) and KWin's QFile then stops
    # writing until it is reopened. Disable/enable reopens it.
    kwin_ftrace(False)
    previous = None
    gpu_instance_start()
    box = {}

    def record():
        box['result'] = run(f"cat <<'EOF' | perfetto --txt -c - -o {REMOTE_DIR}/{name}\n{config(duration_s, preset)}\nEOF\n",
                            'root', timeout=duration_s + 90, check=False)

    thread = threading.Thread(target=record)
    thread.start()
    try:
        time.sleep(1.5)            # perfetto startup; ftrace begins shortly after launch
        previous = kwin_ftrace(True)
        if during:
            during()
        thread.join()
    finally:
        gpu_remote = f'/data/local/tmp/{name}.kgsl.txt'
        gpu_instance_stop(gpu_remote)
        if previous is not None:
            kwin_ftrace(False)
    result = box.get('result')
    if result is None or result.returncode:
        raise rungic_device.DeviceError(f'perfetto failed: {result.stderr if result else "no result"}')
    # The trace directory is not readable by adb's shell user.
    staged = f'/data/local/tmp/{name}'
    run(f'mv {REMOTE_DIR}/{name} {staged} && chmod 644 {staged}', 'root')
    try:
        for remote, target in ((staged, local), (gpu_remote, local.with_name(local.name + '.kgsl.txt'))):
            subprocess.run(rungic_device.adb('pull', remote, str(target)), check=True,
                           capture_output=True, timeout=600, stdin=subprocess.DEVNULL)
    finally:
        run(f'rm -f {staged} {gpu_remote}', 'root', check=False)
    return local


def swipes(count=6, duration_ms=500, pause=0.3):
    """Vertical swipes through Android input (layout-independent, unlike taps)."""
    def act():
        for i in range(count):
            start, end = (1800, 700) if i % 2 == 0 else (700, 1800)
            run(f'input swipe 540 {start} 540 {end} {duration_ms}', 'shell')
            time.sleep(pause)
    return act


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--duration', type=float, default=10)
    parser.add_argument('--label', default='trace')
    parser.add_argument('--swipes', type=int, default=0, help='vertical swipes during the capture')
    parser.add_argument('--preset', choices=sorted(FTRACE_EVENTS), default='frame')
    args = parser.parse_args()
    path = capture(args.duration, args.label, args.preset, during=swipes(args.swipes) if args.swipes else None)
    print(path)


if __name__ == '__main__':
    main()
