"""rungic_touch without a device (docs/65): the panel found from getevent's listing, frames in
multi-touch protocol B as 24-byte input_events, one shell script that writes them, and no play
while a real finger is down."""
import struct

import pytest

import rungic_touch

GETEVENT = '''add device 1: /dev/input/event3
  name:     "gpio-keys"
  events:
    KEY (0001): KEY_VOLUMEDOWN
add device 2: /dev/input/event8
  name:     "chipone-tddi"
  events:
    ABS (0003): ABS_MT_SLOT           : value 0, min 0, max 9, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_X     : value 0, min 0, max 4319, fuzz 0, flat 0, resolution 0
                ABS_MT_POSITION_Y     : value 0, min 0, max 9599, fuzz 0, flat 0, resolution 0
  input props:
    INPUT_PROP_DIRECT
'''


def fake(script, level='root', timeout=60):
    return GETEVENT if script.startswith('getevent') else 'Physical size: 1080x2400\n'


def events(frame):
    return [struct.unpack('<qqHHi', frame[i:i + 24])[2:] for i in range(0, len(frame), 24)]


def test_the_panel_and_its_scale():
    panel = rungic_touch.Panel.find(run=fake)
    assert (panel.device, panel.width, panel.height) == ('/dev/input/event8', 1080, 2400)
    assert (panel.scale_x, panel.scale_y) == (4.0, 4.0)


def test_a_tap_is_down_then_up():
    panel = rungic_touch.Panel('/dev/input/event8', 1080, 2400, 4.0, 4.0)
    g = rungic_touch.tap(panel, 100, 200)
    first, last = events(g.frames[0]), events(g.frames[-1])
    assert (3, rungic_touch.ABS_MT_TRACKING_ID, 100) in first
    assert (3, rungic_touch.ABS_MT_POSITION_X, 400) in first and (3, rungic_touch.ABS_MT_POSITION_Y, 800) in first
    assert first[-2:] == [(1, rungic_touch.BTN_TOUCH, 1), (0, 0, 0)]
    assert (3, rungic_touch.ABS_MT_TRACKING_ID, -1) in last and (1, rungic_touch.BTN_TOUCH, 0) in last


def test_the_second_finger_lifts_first():
    panel = rungic_touch.Panel('/dev/input/event8', 1080, 2400, 4.0, 4.0)
    g = rungic_touch.spread_lift_one(panel, 800, 1200, panel.width)
    lifted = [i for i, f in enumerate(g.frames) if (3, rungic_touch.ABS_MT_TRACKING_ID, -1) in events(f)]
    assert len(lifted) == 2 and lifted[1] == len(g.frames) - 1          # one, later the other
    xs = [v for k, c, v in events(g.frames[-2]) if c == rungic_touch.ABS_MT_POSITION_X]
    assert xs and xs[0] <= 1080 * 4                                      # never past the panel


def test_one_script_no_process_per_frame():
    panel = rungic_touch.Panel('/dev/input/event8', 1080, 2400, 4.0, 4.0)
    script = rungic_touch.drag(panel, 500, 1000, 100, 0).script(0.012)
    assert script.count('print -n') == 26          # down, 20 moves, 4 still, up and 'base64' not in script and 'usleep' not in script
    assert 'exec 4>/dev/input/event8' in script and 'read -t 0.012 -u3' in script


def test_not_while_a_finger_is_down():
    assert rungic_touch.fingers_down(run=lambda *a, **k: 'Last Cooked Touch: pointerCount=1\n') == 1
    assert rungic_touch.fingers_down(run=lambda *a, **k: 'Last Cooked Touch: pointerCount=0\n') == 0
    panel = rungic_touch.Panel('/dev/input/event8', 1080, 2400, 4.0, 4.0)
    with pytest.raises(ValueError):
        rungic_touch.Gesture(panel).frame(s0=(1, 1)).play(run=lambda *a, **k: None)
