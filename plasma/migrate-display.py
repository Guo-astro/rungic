#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""One-time migration of the legacy nested output's inconsistent scale.
Run as the desktop user while its graphical session is stopped.
"""
import argparse
import json
from pathlib import Path
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--width', type=int, required=True)
parser.add_argument('--height', type=int, required=True)
parser.add_argument('--scale', type=float, required=True)
args = parser.parse_args()
if min(args.width, args.height) < 320 or not 0.5 <= args.scale <= 3:
    parser.error('Invalid display dimensions or scale')
path = Path.home() / '.config/kwinoutputconfig.json'
marker = Path.home() / '.local/state/moto-native-display-v1'
if marker.exists():
    raise SystemExit('Native display migration already applied')
if path.exists():
    data = json.loads(path.read_text())
    backup = path.with_suffix('.before-native-display.json')
    if not backup.exists():
        shutil.copy2(path, backup)
    for section in data:
        if section.get('name') != 'outputs':
            continue
        for output in section.get('data', []):
            if output.get('connectorName') == 'WL-0':
                output['scale'] = args.scale
                output.setdefault('mode', {}).update(width=args.width, height=args.height)
    temporary = path.with_suffix('.native-display.tmp')
    temporary.write_text(json.dumps(data, indent=4) + '\n')
    temporary.replace(path)
marker.parent.mkdir(parents=True, exist_ok=True)
marker.write_text(f'{args.width}x{args.height} scale={args.scale}\n')
