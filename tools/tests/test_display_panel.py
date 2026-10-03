# SPDX-License-Identifier: MIT
"""The status bar around Android's camera hole (desktop/display.py, installed as rungic-plasma-display,
docs/43): from the cutout the Rungic app reports in android-display.ini, the panel settings that put
the bar's centre line on the hole's centre, side padding from Android's safe area only while the hole
is in the bar's row, and all of it for the phone's own screen only, never a TV listed first.

The program runs as it does in the session, on a private session bus, with stand-ins on PATH for what
it asks: rungic-plasma-screen-metrics (Qt's screens), kscreen-doctor -j (KScreen's outputs) and
kwriteconfig6 (which records what it is told to write)."""
import configparser
import importlib.machinery
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DISPLAY = ROOT / 'desktop/display.py'


def module():
    loader = importlib.machinery.SourceFileLoader('rungic_plasma_display', str(DISPLAY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def ini(**values):
    """android-display.ini as MainActivity writes it (pixels of the app's buffer)."""
    fields = {'version': 1, 'width': 1080, 'height': 2400, 'safe-top': 0, 'safe-left': 0, 'safe-right': 0,
              'cutout-left': 0, 'cutout-right': 0, 'cutout-top': 0, 'cutout-bottom': 0, 'corner-radius': 0}
    fields.update({k.replace('_', '-'): v for k, v in values.items()})
    return '[display]\n' + ''.join(f'{k}={v}\n' for k, v in fields.items())


def section(text):
    config = configparser.ConfigParser()
    config.read_string(text)
    return config['display']


HOLE = dict(cutout_left=500, cutout_right=580, cutout_top=30, cutout_bottom=84)   # a 54 px hole, centre y=57


# covers: desktop.panels/E1
@pytest.mark.parametrize('kscreen_scale', [1, 3, 2.5])
def test_the_bar_is_centred_on_the_hole(kscreen_scale):
    values = module().panel_values(section(ini(**HOLE)), {'width': 360}, {'scale': kscreen_scale})
    # Plasma divides the configured values by KScreen's scale; Qt's screen is 360 logical px for 1080.
    height = values['statusBarHeight'] / kscreen_scale
    assert height / 2 == pytest.approx((30 + 84) / 2 * 360 / 1080), 'the bar centre line is the hole centre line'
    assert values['statusBarCenterSpacing'] / kscreen_scale == pytest.approx((80 + 16) * 360 / 1080), \
        'the centre gap spans the hole and a margin'
    assert round(height) == 38, 'the G100 S hole gives the 38 px bar the panel reserves (docs/43)'


# covers: desktop.panels/E1
def test_without_a_hole_the_bar_keeps_its_own_height():
    values = module().panel_values(section(ini()), {'width': 360}, {'scale': 1})
    assert values['statusBarHeight'] == -1 and values['statusBarCenterSpacing'] == 0


# covers: desktop.panels/E4
def test_side_padding_follows_the_safe_area_only_with_the_hole_in_the_bar():
    mod = module()
    upright = mod.panel_values(section(ini(safe_left=120, safe_right=60, **HOLE)), {'width': 360}, {'scale': 1})
    assert upright['statusBarLeftPadding'] == pytest.approx(120 / 3)
    assert upright['statusBarRightPadding'] == pytest.approx(60 / 3)
    # Turned, Android reports its safe area at the side and no hole in the top row (MainActivity keeps
    # only cutouts above the top safe inset): the usual padding, the desktop goes on under the hole.
    turned = mod.panel_values(section(ini(width=2400, height=1080, safe_left=120)), {'width': 800}, {'scale': 1})
    assert turned['statusBarLeftPadding'] == pytest.approx(24 / 3)
    assert turned['statusBarRightPadding'] == pytest.approx(24 / 3)
    # A hole outside the bar's row (lower than 256 px) is not one either.
    low = mod.panel_values(section(ini(safe_left=120, cutout_left=500, cutout_right=580, cutout_top=300,
                                       cutout_bottom=360)), {'width': 360}, {'scale': 1})
    assert low['statusBarHeight'] == -1 and low['statusBarLeftPadding'] == pytest.approx(24 / 3)


def bin_dir(tmp_path, screens, outputs):
    bin = tmp_path / 'bin'
    bin.mkdir()
    for name, data in (('rungic-plasma-screen-metrics', screens), ('kscreen-doctor', {'outputs': outputs})):
        path = bin / name
        path.write_text(f'#!/bin/sh\ncat <<"EOF"\n{json.dumps(data)}\nEOF\n')
        path.chmod(0o755)
    writes = tmp_path / 'writes'
    path = bin / 'kwriteconfig6'
    path.write_text(f'#!/bin/sh\necho "$@" >>{writes}\n')
    path.chmod(0o755)
    return bin, writes


def run_display(tmp_path, screens, outputs, wait=lambda writes: len(writes) >= 4, timeout=15):
    """The program in its loop until `wait` holds for the writes so far (or the time is up)."""
    bin, writes = bin_dir(tmp_path, screens, outputs)
    (tmp_path / 'home').mkdir()
    (tmp_path / 'android-display.ini').write_text(ini(safe_left=120, safe_right=60, **HOLE))
    env = {**os.environ, 'PATH': f'{bin}:{os.environ["PATH"]}', 'HOME': str(tmp_path / 'home'),
           'RUNGIC_ANDROID_DISPLAY': str(tmp_path / 'android-display.ini')}
    proc = subprocess.Popen(['dbus-run-session', '--', sys.executable, str(DISPLAY)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        deadline = time.monotonic() + timeout
        lines = []
        while time.monotonic() < deadline:
            lines = writes.read_text().splitlines() if writes.exists() else []
            if wait(lines):
                break
            time.sleep(0.2)
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        output = proc.communicate(timeout=10)[0]
    return {line.split(' --key ')[1].split(' -- ')[0]: float(line.split(' -- ')[1]) for line in lines}, lines, output


needs_bus = pytest.mark.skipif(not shutil.which('dbus-run-session'), reason='needs dbus-run-session')
TV = {'name': 'CAST-1', 'manufacturer': 'Rungic', 'model': 'Cast', 'width': 1280, 'height': 720, 'scale': 1.5}
PHONE = {'name': 'WL-0', 'manufacturer': 'Rungic', 'model': 'Handset', 'width': 360, 'height': 800, 'scale': 3}


# covers: desktop.panels/E1 desktop.panels/E4
@needs_bus
def test_the_phone_screen_gets_the_values_even_with_a_tv_listed_first(tmp_path):
    values, lines, output = run_display(tmp_path, [TV, PHONE], [{'name': 'CAST-1', 'scale': 1.5}, {'name': 'WL-0', 'scale': 3}])
    assert set(values) == {'statusBarHeight', 'statusBarCenterSpacing', 'statusBarLeftPadding', 'statusBarRightPadding'}, output
    assert all('--file plasmamobilerc --group Panels --group WhenOnTop' in line for line in lines)
    # The phone's metrics (360 logical px, KScreen scale 3), not the TV's.
    assert values['statusBarHeight'] / 3 == pytest.approx(38)
    assert values['statusBarLeftPadding'] == pytest.approx(120 / 3 * 3), 'safe-left 120 px is 40 logical px'
    assert 'Android centerline-aligned panel' in output


# covers: desktop.panels/E4
@needs_bus
def test_without_the_phone_screen_nothing_is_written(tmp_path):
    values, lines, output = run_display(tmp_path, [TV], [{'name': 'CAST-1', 'scale': 1.5}],
                                        wait=lambda writes: False, timeout=3)
    assert lines == [], 'the cutout of the phone is never applied to another screen'
    assert 'Display metadata unavailable' in output
