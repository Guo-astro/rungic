#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Multi-touch on the phone's own touchscreen, for gestures adb input cannot make (docs/65).

Frames of input_event structs (aarch64: 24 bytes: time, type, code, value) in multi-touch
protocol B are written to the panel's evdev node as root, one frame per write, from a single
shell: builtin print writes a frame, builtin read -t on an empty FIFO waits between frames, so no
process starts per frame and the timing stays near real fingers (~12 ms frames). Android then sees
them as the panel's own touches, and so does everything behind it (the Plasma session, Qt).

Coordinates are screen pixels (wm size); the panel's range is found with getevent. Before
playing it checks that no real finger is down (a touch mixed in made swipes multi-finger once).

  rungic_touch.py tap X Y
  rungic_touch.py drag X Y DX DY [--steps N]
  rungic_touch.py pinch X Y GAP [--out | --in] [--steps N]
  rungic_touch.py spread-lift-one X Y           the pinch whose second finger lifts first while the
                                                first keeps moving (it tucked the assistant screen's
                                                window, docs/65)

Every gesture runs at 12 ms a frame unless --pause S says otherwise.
"""
import argparse
import re
import struct
import sys

import rungic_device

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, BTN_TOUCH = 0, 0x14a
ABS_MT_SLOT, ABS_MT_TOUCH_MAJOR, ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 0x2f, 0x30, 0x35, 0x36
ABS_MT_TRACKING_ID, ABS_MT_PRESSURE = 0x39, 0x3a
FIFO = '/data/local/tmp/rungic-touch.fifo'


def event(kind, code, value):
    return struct.pack('<qqHHi', 0, 0, kind, code, value)


class Panel:
    """The touchscreen: its evdev node and how its coordinates relate to the screen's pixels."""

    def __init__(self, device, width, height, scale_x, scale_y):
        self.device, self.width, self.height = device, width, height
        self.scale_x, self.scale_y = scale_x, scale_y

    @classmethod
    def find(cls, run=rungic_device.out):
        listing = run('getevent -lp 2>/dev/null', 'root')
        size = re.search(r'(\d+)x(\d+)', run('wm size', 'shell').split(':')[-1])
        width, height = int(size[1]), int(size[2])
        for block in listing.split('add device')[1:]:
            x = re.search(r'ABS_MT_POSITION_X\s*:.*?max (\d+)', block)
            y = re.search(r'ABS_MT_POSITION_Y\s*:.*?max (\d+)', block)
            if x and y and 'INPUT_PROP_DIRECT' in block:
                device = re.search(r'(/dev/input/event\d+)', block)[1]
                return cls(device, width, height, (int(x[1]) + 1) / width, (int(y[1]) + 1) / height)
        raise SystemExit('no direct multi-touch panel in getevent -lp')


class Gesture:
    """Frames of fingers: frame(s0=(x, y), s1=None) puts finger 0 down or moves it, lifts finger 1."""

    def __init__(self, panel):
        self.panel, self.frames, self.down, self.next_id = panel, [], set(), 100

    def frame(self, **fingers):
        data = b''
        for name, position in fingers.items():
            slot = int(name[1:])
            data += event(EV_ABS, ABS_MT_SLOT, slot)
            if position is None:
                data += event(EV_ABS, ABS_MT_TRACKING_ID, -1)
                self.down.discard(slot)
                continue
            if slot not in self.down:
                data += event(EV_ABS, ABS_MT_TRACKING_ID, self.next_id)
                data += event(EV_ABS, ABS_MT_TOUCH_MAJOR, 8) + event(EV_ABS, ABS_MT_PRESSURE, 60)
                self.next_id += 1
                self.down.add(slot)
            data += event(EV_ABS, ABS_MT_POSITION_X, round(position[0] * self.panel.scale_x))
            data += event(EV_ABS, ABS_MT_POSITION_Y, round(position[1] * self.panel.scale_y))
        data += event(EV_KEY, BTN_TOUCH, 1 if self.down else 0) + event(EV_SYN, SYN_REPORT, 0)
        self.frames.append(data)
        return self

    def script(self, pause):
        lines = [f'rm -f {FIFO}; mkfifo {FIFO}; exec 3<>{FIFO}', f'exec 4>{self.panel.device}']
        for frame in self.frames:
            lines.append('print -n "' + ''.join(f'\\x{b:02x}' for b in frame) + '" >&4')
            lines.append(f'read -t {pause} -u3 _ || true')
        lines.append(f'exec 4>&- 3<&-; rm -f {FIFO}')
        return '\n'.join(lines)

    def play(self, pause=0.012, run=rungic_device.run):
        if self.down:
            raise ValueError('a finger is still down at the end of the gesture')
        return run(self.script(pause), 'root', timeout=120)


def fingers_down(run=rungic_device.out):
    """Real fingers on the screen now (dumpsys input), so that a test does not mix with them."""
    text = run('dumpsys input', 'root', timeout=60)
    counts = [int(n) for n in re.findall(r'Last Cooked Touch: pointerCount=(\d+)', text)]
    return max(counts, default=0)


def tap(panel, x, y):
    return Gesture(panel).frame(s0=(x, y)).frame(s0=(x, y)).frame(s0=None)


def drag(panel, x, y, dx, dy, steps=20):
    g = Gesture(panel).frame(s0=(x, y))
    for k in range(1, steps + 1):
        g.frame(s0=(x + dx * k / steps, y + dy * k / steps))
    for _ in range(4):                       # still before the let-go: no flick
        g.frame(s0=(x + dx, y + dy))
    return g.frame(s0=None)


def pinch(panel, x, y, gap, out=True, steps=14):
    """Two fingers on a horizontal line through (x, y), `gap` apart at the start (out) or the end (in)."""
    near, far = gap / 2, gap / 2 + 15 * steps
    start, end = (near, far) if out else (far, near)
    g = Gesture(panel)
    for k in range(steps + 1):
        half = start + (end - start) * k / steps
        g.frame(s0=(x + half, y), s1=(x - half, y))
    return g.frame(s0=None, s1=None)


def spread_lift_one(panel, x, y, width):
    """Spread towards the right edge, the left finger lifts, the right one moves on a little and lifts."""
    a, b = x + 50, x - 50
    g = Gesture(panel).frame(s0=(a, y), s1=(b, y))
    for _ in range(10):
        a, b = min(width - 5, a + 12), b - 25
        g.frame(s0=(a, y), s1=(b, y))
    g.frame(s1=None, s0=(a, y))
    for _ in range(6):
        a = min(width - 2, a + 1)
        g.frame(s0=(a, y))
    return g.frame(s0=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('gesture', choices=['tap', 'drag', 'pinch', 'spread-lift-one'])
    parser.add_argument('numbers', nargs='+', type=float)
    parser.add_argument('--steps', type=int)
    parser.add_argument('--in', dest='inward', action='store_true', help='pinch: fingers come together')
    parser.add_argument('--out', action='store_true', help='pinch: fingers spread (default)')
    parser.add_argument('--pause', type=float, default=0.012, help='seconds between frames')
    args = parser.parse_args()
    down = fingers_down()
    if down:
        sys.exit(f'{down} finger(s) on the screen now: try again when nobody touches it')
    panel = Panel.find()
    n = args.numbers
    if args.gesture == 'tap':
        g = tap(panel, n[0], n[1])
    elif args.gesture == 'drag':
        g = drag(panel, n[0], n[1], n[2], n[3], args.steps or 20)
    elif args.gesture == 'pinch':
        g = pinch(panel, n[0], n[1], n[2], not args.inward, args.steps or 14)
    else:
        g = spread_lift_one(panel, n[0], n[1], panel.width)
    g.play(args.pause)
    print(f'{args.gesture}: {len(g.frames)} frames on {panel.device}')


if __name__ == '__main__':
    main()
