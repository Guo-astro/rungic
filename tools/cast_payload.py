#!/usr/bin/env python3
"""One casting payload for clean-image seeds and existing-account upgrades."""
import hashlib
import argparse
import json
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


def build_inputs():
    paths = [ROOT / 'shared/android/rungic-cast/build.sh', ROOT / 'tools/cast_payload.py',
             *sorted((ROOT / 'shared/android/rungic-cast/src').rglob('*.java'))]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def attest_build(jar, snapshot):
    inputs = json.loads(snapshot.read_text())
    if inputs != build_inputs():
        raise ValueError('casting sources changed during compilation; rebuild')
    report = {'schema': 1, 'inputs': inputs,
              'jar_sha256': hashlib.sha256(jar.read_bytes()).hexdigest()}
    jar.with_suffix('.build.json').write_text(json.dumps(report, indent=2) + '\n')


def validate_build(jar):
    report_path = jar.with_suffix('.build.json')
    if not report_path.is_file():
        raise ValueError('casting jar has no build provenance; rebuild with shared/android/rungic-cast/build.sh')
    report = json.loads(report_path.read_text())
    if report.get('schema') != 1 or report.get('inputs') != build_inputs():
        raise ValueError('casting jar does not match current sources; rebuild')
    if report.get('jar_sha256') != hashlib.sha256(jar.read_bytes()).hexdigest():
        raise ValueError('casting jar digest differs from its build report')
    return report


def manifest(directory):
    files = [dest for _, dest, _ in FILES] + ['rungic-cast.jar']
    rows = [f'{hashlib.sha256((directory / name).read_bytes()).hexdigest()}  {name}' for name in sorted(files)]
    (directory / 'SHA256SUMS').write_text('\n'.join(rows) + '\n')


def stage(directory, jar):
    validate_build(jar)
    directory.mkdir(parents=True, exist_ok=True)
    for source, name, mode in FILES:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / source).read_bytes())
        path.chmod(mode)
    (directory / 'rungic-cast.jar').write_bytes(jar.read_bytes())
    (directory / 'rungic-cast.jar').chmod(0o644)
    manifest(directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    snapshot = sub.add_parser('snapshot')
    snapshot.add_argument('output', type=Path)
    attest = sub.add_parser('attest')
    attest.add_argument('jar', type=Path)
    attest.add_argument('snapshot', type=Path)
    args = parser.parse_args()
    if args.command == 'snapshot':
        args.output.write_text(json.dumps(build_inputs(), indent=2) + '\n')
    else:
        attest_build(args.jar, args.snapshot)
