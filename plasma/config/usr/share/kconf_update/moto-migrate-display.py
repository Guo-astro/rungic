#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""kconf_update script (moto.upd, Id=moto-native-display-v1): one-time migration of the
legacy nested output's inconsistent scale in ~/.config/kwinoutputconfig.json.

The phone's output is WL-0. Its mode becomes the Android display size and its scale 3.0,
the values this migration applied before it ran as a kconf_update script. The marker
~/.local/state/moto-native-display-v1 of that earlier tool is honoured, and written here.
kconf_update records the Id as done even if this fails, so failures leave things untouched.
"""
import configparser
import json
import shutil
import sys
from pathlib import Path

SCALE = 3.0
config = Path.home() / '.config/kwinoutputconfig.json'
marker = Path.home() / '.local/state/moto-native-display-v1'
if marker.exists():
    sys.exit(0)
try:
    display = configparser.ConfigParser()
    display.read('/mnt/android-wayland/android-display.ini')
    width, height = display.getint('display', 'width'), display.getint('display', 'height')
except (configparser.Error, ValueError, OSError):
    sys.exit(0)   # no Android display information: nothing reliable to migrate to
if min(width, height) < 320:
    sys.exit(0)
if config.exists():
    data = json.loads(config.read_text())
    backup = config.with_suffix('.before-native-display.json')
    if not backup.exists():
        shutil.copy2(config, backup)
    for section in data:
        if section.get('name') != 'outputs':
            continue
        for output in section.get('data', []):
            if output.get('connectorName') == 'WL-0':
                output['scale'] = SCALE
                output.setdefault('mode', {}).update(width=width, height=height)
    temporary = config.with_suffix('.native-display.tmp')
    temporary.write_text(json.dumps(data, indent=4) + '\n')
    temporary.replace(config)
marker.parent.mkdir(parents=True, exist_ok=True)
marker.write_text(f'{width}x{height} scale={SCALE}\n')
