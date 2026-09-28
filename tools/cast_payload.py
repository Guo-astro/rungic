#!/usr/bin/env python3
"""One casting payload for clean-image seeds and existing-account upgrades."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    ('shared/android/rungic-cast/rungic-cast', 'rungic-cast', 0o755),
    ('shared/android/rungic-cast/rungic-cast-watch', 'rungic-cast-watch', 0o755),
    ('shared/android/rungic-cast/install.sh', 'install.sh', 0o755),
    ('profiles/cast-adapters.json', 'adapters.json', 0o644),
    ('shared/android/wfd.sepolicy.rule', 'wfd.sepolicy.rule', 0o644),
    ('shared/android/rungic-wfd-sepolicy.sh', 'service.d/rungic-wfd-sepolicy.sh', 0o755),
    ('shared/android/rungic-cast-watch.sh', 'service.d/rungic-cast-watch.sh', 0o755),
)


def manifest(directory):
    files = [dest for _, dest, _ in FILES] + ['rungic-cast.jar']
    rows = [f'{hashlib.sha256((directory / name).read_bytes()).hexdigest()}  {name}' for name in sorted(files)]
    (directory / 'SHA256SUMS').write_text('\n'.join(rows) + '\n')


def stage(directory, jar):
    directory.mkdir(parents=True, exist_ok=True)
    for source, name, mode in FILES:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / source).read_bytes())
        path.chmod(mode)
    (directory / 'rungic-cast.jar').write_bytes(jar.read_bytes())
    (directory / 'rungic-cast.jar').chmod(0o644)
    manifest(directory)
