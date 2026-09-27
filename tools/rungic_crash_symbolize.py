#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Symbolize the phone's crash reports off the phone (docs/61).

  rungic_crash_symbolize.py REPORT...     report ids under /var/lib/rungic-cores (YYYYmmdd-HHMMSS-comm-pid)
  rungic_crash_symbolize.py --recent N    the N newest reports that still have core.zst

Loading a desktop process's debug information takes gigabytes; in the phone's container (no memory
limit) that starved Android until its low-memory killer took the VPN and the Plasma APK
(2026-09-27). So the phone only answers what is cheap: the report, which package owns each module
mapped in the core, and a tar of those exact files with core.zst. The analysis runs in the build
host's container (build_on_device.py --host macmini): the files form a sysroot, the owning
packages' -dbgsym at exactly the phone's versions are unpacked into it (this project's from the
release repository, Ubuntu's from ddebs.ubuntu.com), and gdb runs the phone's own collector
(plasma/diagnostics/rungic-coredump-collect) against that sysroot. The phone's report gets the new
backtrace.txt and info.json (signature recomputed, the unsymbolized one kept), as
rungic-crash-symbols did there.
"""
import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import build_on_device
import rungic_device
import rungic_release
from rungic_device import WORKSPACE

STORE = '/var/lib/rungic-cores'
WORK = '/root/rungic-build/crash'
REPORT = re.compile(r'\d{8}-\d{6}-[^/\s]+-\d+')

MANIFEST = r'''
import json, os, subprocess, sys
report = sys.argv[1]
info = json.load(open(f'/var/lib/rungic-cores/{report}/info.json'))
files = {m['file'] for m in info.get('modules', []) if (m.get('file') or '').startswith('/')}
if info.get('exe'):
    files.add(info['exe'])
files = sorted(f for f in files if os.path.exists(f))
# Debug symbols only for what the crashing thread runs through (its libraries in the collector's
# backtrace, and the executable): a desktop process maps some 250 libraries, gigabytes of symbols.
crashing = set(info.get('exe') and [info['exe']] or [])
try:
    text = open(f'/var/lib/rungic-cores/{report}/backtrace.txt').read()
    first = []
    for line in text.splitlines():
        if line.startswith('#0 ') and first and any(l.startswith('#1') for l in first):
            break
        if line.startswith('#'):
            first.append(line)
    import re
    for line in first:
        m = re.search(r' (?:from|at) (/[^ :]+\.so[^ :]*)', line)
        if m:
            crashing.add(os.path.realpath(m[1]))
except OSError:
    crashing = set(files)
owners = {}
for path in [f for f in files if os.path.realpath(f) in crashing or f in crashing]:
    for candidate in (path, path.replace('/usr/lib/', '/lib/', 1), path.replace('/lib/', '/usr/lib/', 1)):
        text = subprocess.run(['dpkg-query', '-S', candidate], capture_output=True, text=True).stdout
        line = next((l for l in text.splitlines() if not l.startswith('diversion')), None)
        if line:
            name = line.split(': ', 1)[0].split(', ')[0]
            fields = subprocess.run(['dpkg-query', '-W', '-f', '${Package} ${Version} ${Architecture}', name],
                                    capture_output=True, text=True).stdout.split()
            if len(fields) == 3:
                owners[fields[0]] = {'version': fields[1], 'arch': fields[2]}
            break
print(json.dumps({'info': info, 'files': files, 'owners': owners}))
'''

# Runs in the build host's container: the phone's collector against the sysroot.
ANALYSE = r'''
import compression.zstd as zstd, importlib.machinery, importlib.util, json, shutil, sys
from pathlib import Path
work, report = Path(sys.argv[1]), sys.argv[2]
root = work / 'sysroot'
loader = importlib.machinery.SourceFileLoader('collect', str(work.parent / 'rungic-coredump-collect'))
collect = importlib.util.module_from_spec(importlib.util.spec_from_loader('collect', loader))
loader.exec_module(collect)
gdb = collect.gdb
collect.gdb = lambda *a, **k: gdb('-iex', f'set sysroot {root}', '-iex', f'set debug-file-directory {root}/usr/lib/debug',
                                  *a, **k)
info = json.loads((root / f'var/lib/rungic-cores/{report}/info.json').read_text())
core = work / 'core'
with zstd.open(root / f'var/lib/rungic-cores/{report}/core.zst', 'rb') as source, open(core, 'wb') as target:
    shutil.copyfileobj(source, target, 1 << 20)
exe = str(root) + info['exe'] if info.get('exe') else ''
header = collect.gdb('-c', str(core), timeout=120)
trace, crashing = collect.backtrace(core, exe)
mods = collect.modules(core, exe)
core.unlink()
for m in mods:                      # module paths as the phone has them, not the sysroot's
    if m['file'] and m['file'].startswith(str(root)):
        m['file'] = m['file'][len(str(root)):]
text = '\n'.join(l for l in (header + '\n' + trace).splitlines() if not l.startswith('[New LWP'))
text = text.replace(str(root), '')
sig, frames = collect.signature(info['comm'], collect.parse_frames(crashing), mods)
have = lambda b: bool(b) and (root / f'usr/lib/debug/.build-id/{b[:2]}/{b[2:]}.debug').exists()
if info.get('signature') and info['signature'] != sig and not info.get('signature_unsymbolized'):
    info['signature_unsymbolized'] = info['signature']
info.update(signature=sig, signature_frames=frames, symbolized=True, symbolized_on='build host',
            modules=[{'file': m['file'] or m['name'], 'build_id': m['build_id']} for m in mods])
info['top_frames'] = [l for l in crashing.splitlines() if l.startswith('#')][:4]
info['missing_symbols'] = sorted({m['file'] for m in mods if m['file'] and m['build_id'] and not have(m['build_id'])})
(work / 'backtrace.txt').write_text(text + '\n')
(work / 'info.json').write_text(json.dumps(info, indent=1))
print(json.dumps({'report': report, 'signature': sig, 'frames': frames, 'missing_symbols': len(info['missing_symbols'])}))
'''


def retrying(action, *args, attempts=4, **kwargs):
    """The phone over a Wi-Fi VPN: adb drops for seconds now and then; retry those, not real errors."""
    for attempt in range(attempts):
        try:
            return action(*args, **kwargs)
        except rungic_device.DeviceError as error:
            transient = any(t in str(error) for t in ('offline', 'not among adb devices', 'Timed out', 'no devices'))
            if not transient or attempt == attempts - 1:
                raise
            time.sleep(15)
            subprocess.run([rungic_device.adb_path(), 'reconnect', 'offline'], capture_output=True, timeout=30)
            rungic_device.transport.cache_clear()


def phone(script, timeout=300):
    return retrying(rungic_device.run, script, 'container', timeout).stdout


def recent(count):
    text = phone(f'ls -1d {STORE}/*/core.zst 2>/dev/null | sort -r | head -n {int(count)}')
    return [Path(line).parent.name for line in text.split()]


def symbolize(host, report):
    manifest = json.loads(phone(f'python3 - {shlex.quote(report)} <<\'RUNGIC_EOF\'\n{MANIFEST}\nRUNGIC_EOF'))
    work = f'{WORK}/{report}'
    # The exact files of the crash, dereferenced, with the report: straight from the phone to the build
    # host over the LAN (tools/pq/rungic-transfer), not through this computer and the VPN.
    host.run(f'rm -rf {work} && mkdir -p {work}/sysroot {work}/debs')
    listing = ' '.join(shlex.quote(f.lstrip('/')) for f in manifest['files'])
    phone(f'tar -chf - -C / {listing} {STORE.lstrip("/")}/{report}/core.zst {STORE.lstrip("/")}/{report}/info.json | '
          f'{build_on_device.MacMini.PHONE_SSH} put crash/{report}/sysroot', timeout=1800)
    # Debug symbols at the phone's exact versions.
    pool = rungic_release.POOL
    ubuntu = []
    for name, owner in manifest['owners'].items():
        upstream_version = owner['version'].split(':', 1)[-1]
        deb = pool / f'{name}-dbgsym_{upstream_version}_{owner["arch"]}.deb'
        if deb.exists():
            host.put(deb, f'{work}/debs/{deb.name}', '644')
        else:
            ubuntu.append(f'{name}-dbgsym={owner["version"]}')
    ddebs = ('-o DPkg::Lock::Timeout=1200 -o Dir::Etc::SourceList=/etc/apt/rungic-ddebs.sources -o Dir::Etc::SourceParts=- '
             '-o Dir::State::Lists=/var/lib/rungic-ddebs/lists')
    # Ubuntu's symbols are kept in the build host's volume ({WORK}/ddebs): ddebs.ubuntu.com has no
    # mirror and a desktop process needs hundreds of MB of them.
    wanted = ' '.join(shlex.quote(spec) for spec in ubuntu)
    host.run(f'''set -e
mkdir -p /var/lib/rungic-ddebs/lists/partial {WORK}/ddebs
stamp=/var/lib/rungic-ddebs/lists/.updated
if [ -z "$(find $stamp -mmin -1440 2>/dev/null)" ]; then apt-get -q {ddebs} update >/dev/null && touch $stamp; fi
cd {WORK}/ddebs
for spec in {wanted}; do
  name=${{spec%%=*}}; version=$(printf %s "${{spec#*=}}" | sed 's/:/%3a/')
  ls "${{name}}_${{version}}_"*.ddeb >/dev/null 2>&1 || apt-get -q {ddebs} download "$spec" >/dev/null 2>&1 || echo "unavailable: $spec"
  for deb in "${{name}}_${{version}}_"*.ddeb; do [ -e "$deb" ] && dpkg-deb -x "$deb" {work}/sysroot; done
done
cd {work}/debs
for deb in *.deb; do [ -e "$deb" ] && dpkg-deb -x "$deb" {work}/sysroot; done; true''', timeout=3 * 3600)
    host.put(WORKSPACE / 'plasma/diagnostics/rungic-coredump-collect', f'{WORK}/rungic-coredump-collect', '644')
    script = WORKSPACE / f'.work/crash/analyse.py'
    script.write_text(ANALYSE)
    host.put(script, f'{WORK}/analyse.py', '644')
    result = json.loads(host.out(f'python3 {WORK}/analyse.py {work} {shlex.quote(report)}', timeout=1800).splitlines()[-1])
    for name in ('backtrace.txt', 'info.json'):
        phone(f'{build_on_device.MacMini.PHONE_SSH} get crash/{report}/{name} > {STORE}/{report}/{name}.new && '
              f'mv {STORE}/{report}/{name}.new {STORE}/{report}/{name}')
    host.run(f'rm -rf {work}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('reports', nargs='*')
    parser.add_argument('--recent', type=int)
    parser.add_argument('--host', choices=[h for h in build_on_device.HOSTS if h != 'phone'], default='macmini')
    args = parser.parse_args()
    reports = [r for r in args.reports if REPORT.fullmatch(r)]
    if len(reports) != len(args.reports):
        parser.error('report ids look like YYYYmmdd-HHMMSS-comm-pid')
    if args.recent:
        reports += recent(args.recent)
    if not reports:
        parser.error('name reports or pass --recent N')
    host = build_on_device.use(args.host)
    print(json.dumps([symbolize(host, r) for r in dict.fromkeys(reports)], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
