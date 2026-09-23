#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Launch and close an app through the Plasma Mobile UI by accessible names only.

Replaces the fixed-coordinate taps of the doc 51 launch scenario. Each step is
checked against the process table and AT-SPI registration, so a missed tap
fails the run instead of silently measuring the wrong thing. `--search` types
the name into the drawer search first, which moves the icon: the same code
must still find it.

  ui_launch_check.py [--app Calculator] [--process kalk] [--rounds 2] [--search]
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import moto_agent  # noqa: E402
from moto_device import run  # noqa: E402


def running(process):
    return run(f'pgrep -x {process}', 'container', check=False).returncode == 0


def wait_for(condition, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.3)
    return False


def press(name):
    buttons = [b for b in moto_agent.ui_find('plasmashell', role='button', name=f'^{name}$')]
    if not buttons:
        raise RuntimeError(f'no plasmashell button named {name!r}')
    return moto_agent.ui_press('plasmashell', buttons[0]['path'])


def open_drawer(timeout=6):
    """Swipe the drawer open and wait until its search field sits still on screen."""
    run('input swipe 540 2000 540 600 250', 'shell')
    previous, deadline = None, time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.3)
        fields = moto_agent.ui_find('plasmashell', role='text', name='Search')
        current = tuple(fields[0]['extents']) if fields else None
        if current and current == previous and current[1] >= 0:
            return
        previous = current
    raise RuntimeError('app drawer did not open')


def icon_for(app, timeout=5):
    """The launcher delegate of `app`, once its position stops changing (drawer animations)."""
    previous, deadline = None, time.monotonic() + timeout
    while time.monotonic() < deadline:
        labels = [n for n in moto_agent.ui_find('plasmashell', role='label', name=f'^{app}$')
                  if n.get('extents', [0, 0, 0, 0])[2] > 0]
        current = (labels[0]['path'], tuple(labels[0]['extents'])) if labels else None
        if current and current == previous:
            return current[0].rsplit('/', 1)[0]  # the icon delegate that owns the label
        previous = current
        time.sleep(0.3)
    raise RuntimeError(f'launcher entry {app!r} not visible or not settling')


def launch(app, process, search):
    press('Home')
    time.sleep(0.8)
    open_drawer()
    if search:
        # Kirigami's search field exposes no EditableText interface: focus it, type through Android input.
        field = [f for f in moto_agent.ui_find('plasmashell', role='text', name='Search')]
        if not field:
            raise RuntimeError('drawer search field not showing')
        moto_agent.ui_press('plasmashell', field[0]['path'], 'SetFocus')
        run(f'input text {app[:4]}', 'shell')
        time.sleep(1.0)
    tap = moto_agent.ui_tap('plasmashell', icon_for(app))
    started = wait_for(lambda: running(process), 10)
    registered = wait_for(lambda: any(a['name'] == process for a in moto_agent.a11y('apps')), 10)
    step = {'tap': tap['tap'], 'started': started, 'registered': registered}
    if not started:
        step['screenshot'] = moto_agent.screenshot()  # evidence of what the tap hit
    return step


def close(process):
    press('Close app')
    return {'exited': wait_for(lambda: not running(process), 10)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--app', default='Calculator')
    parser.add_argument('--process', default='kalk')
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--search', action='store_true')
    args = parser.parse_args()
    moto_agent.ui_enable(True)
    time.sleep(2)
    if running(args.process):
        close(args.process)
    results = []
    for i in range(args.rounds):
        step = launch(args.app, args.process, args.search) | close(args.process)
        results.append(step)
        print(json.dumps(step), flush=True)
    ok = all(r['started'] and r['registered'] and r['exited'] for r in results)
    print(json.dumps({'ok': ok, 'rounds': len(results)}))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
