#!/usr/bin/env python3
"""Record SurfaceFlinger presentation timestamps while repeating a fixed swipe.

Run with the Plasma app drawer already visible. This measures the Android
surface, not individual Linux application repaint completion.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import statistics
import subprocess
import threading
import time

import rungic_device

ADB = rungic_device.adb('shell')

def shell(*args):
    return subprocess.check_output(ADB + [shlex.join(args)], text=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--scenario', choices=['scroll', 'launch'], default='scroll')
    args = parser.parse_args()
    layers = shell('dumpsys', 'SurfaceFlinger', '--list')
    matches = [l for l in layers.splitlines() if re.search(r'SurfaceView\[(com\.rungic|dev\.moto)\.plasma/', l) and '(BLAST)' in l]
    if len(matches) != 1:
        raise SystemExit('Expected one Plasma BLAST surface: ' + repr(matches))
    layer = re.search(r'\{(.*?) parentId=', matches[0])[1] if 'RequestedLayerState{' in matches[0] else matches[0]
    shell('dumpsys', 'SurfaceFlinger', '--latency-clear')
    raw = []
    actions = []
    def gestures():
        if args.scenario == 'launch':
            for _ in range(4):
                actions.append({'start_monotonic': time.monotonic(), 'action': 'launch-calculator'})
                shell('input', 'tap', '180', '465')
                time.sleep(2)
                actions[-1]['end_monotonic'] = time.monotonic()
                # Plasma's close-current-app button, above Android's edge bar.
                shell('input', 'tap', '810', '2340')
                time.sleep(4)
            return
        for i in range(8):
            start, end = (1800, 700) if i % 2 == 0 else (700, 1800)
            actions.append({'start_monotonic': time.monotonic(), 'from_y': start, 'to_y': end})
            shell('input', 'swipe', '500', str(start), '500', str(end), '900')
            actions[-1]['end_monotonic'] = time.monotonic()
            time.sleep(0.15)
    worker = threading.Thread(target=gestures)
    worker.start()
    while worker.is_alive():
        text = shell('dumpsys', 'SurfaceFlinger', '--latency', layer)
        raw.append({'monotonic': time.monotonic(), 'text': text})
        time.sleep(0.2)
    worker.join()
    pts = set()
    for entry in raw:
        for line in entry['text'].splitlines()[1:]:
            values = line.split()
            if len(values) == 3 and all(v.isdigit() for v in values):
                actual = int(values[1])
                if 0 < actual < 9223372036854775807:
                    pts.add(actual)
    pts = sorted(pts)
    intervals = [(b-a)/1e6 for a,b in zip(pts, pts[1:])]
    # The short pauses are intentional. Report them rather than silently
    # dropping slow frames; compare identical scenarios only.
    ordered = sorted(intervals)
    summary = {'frames': len(pts), 'median_ms': statistics.median(intervals) if intervals else None,
               'p95_ms': ordered[int((len(ordered)-1)*.95)] if ordered else None,
               'over_16_9_ms': sum(t > 16.9 for t in intervals),
               'over_33_7_ms': sum(t > 33.7 for t in intervals)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'layer': layer, 'actions': actions, 'samples': raw,
                                       'present_ns': pts, 'summary': summary}, indent=2) + '\n')
    print(json.dumps(summary))

if __name__ == '__main__':
    main()
