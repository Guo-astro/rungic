#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Versioned releases of the Plasma container: local APT repository, release metapackage,
deploy, rollback and status (docs/61).

A release is moto-plasma-release=<version>: a metapackage with an exact dependency on every
package in plasma/release/packages.json (rebuilt Ubuntu packages, this project's moto-*
packages, and the Ubuntu packages coupled to them), plus /usr/share/moto/release.json with the
git commit. The repository is .work/apt/repo on this computer (the pool of .debs is build
output); deploy mirrors it to /var/lib/moto-apt in the container, where it is a trusted file:
source pinned at 1001, so its versions win over the archive and older releases can be
reinstalled. The Android-side files listed under "android" are part of a release too.

  moto_release.py import-installed    pull the .debs of the installed +moto versions from the
                                      phone's build directories into the pool
  moto_release.py import DEB...       add .debs to the pool
  moto_release.py build [--version V] metapackage for the current packages.json and git commit,
                                      regenerate the repository index
  moto_release.py list                releases in the repository
  moto_release.py deploy [V]          preflight, record, sync, install, restart, verify (latest by default)
  moto_release.py rollback            deploy the release that was installed before the current one
  moto_release.py status              installed release, its commit, repository and integrity state

Every deploy leaves a record under .work/deploy/<time>-<version>/.
"""
import argparse
import datetime
import fnmatch
import gzip
import hashlib
import io
import json
import lzma
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import moto_device
from moto_device import DeviceError, WORKSPACE, out, push, run

SPEC = WORKSPACE / 'plasma/release/packages.json'
APT = WORKSPACE / '.work/apt'
POOL = APT / 'repo'                  # flat repository: .debs, Packages, Release
RELEASES = APT / 'releases'          # <version>.json: what each metapackage pins
DEPLOY = WORKSPACE / '.work/deploy'
HISTORY = DEPLOY / 'history.json'
DEVICE_REPO = '/var/lib/moto-apt'
META = 'moto-plasma-release'
# The build directories on the phone that hold .debs of installed versions (import-installed).
DEVICE_DEB_DIRS = ['/root/moto-build/*', '/root/moto-mesa-debs', '/root/moto-display-packages',
                   '/root/moto-media-packages', '/root/moto-packages/*', '/root']
# The source and pin that moto-plasma-config ships; deploy installs the same bytes before the
# package exists, so dpkg later takes them over as unchanged conffiles.
SOURCES = (WORKSPACE / 'plasma/config/etc/apt/sources.list.d/moto.sources').read_text()
PREFERENCES = (WORKSPACE / 'plasma/config/etc/apt/preferences.d/moto').read_text()
APT_OURS = ('-o Dir::Etc::SourceList=/etc/apt/sources.list.d/moto.sources -o Dir::Etc::SourceParts=- '
            '-o APT::Get::List-Cleanup=0')


def spec():
    return json.loads(SPEC.read_text())


def deb_field(path, field):
    return subprocess.run(['dpkg-deb', '-f', str(path), field], capture_output=True, text=True,
                          check=True).stdout.strip()


def upstream_name(name, version):
    """File name version: without the epoch."""
    return f"{name}_{version.split(':', 1)[-1]}"


def pool_debs():
    result = {}
    for deb in POOL.glob('*.deb'):
        m = re.match(r'([^_]+)_([^_]+)_([^_.]+)\.deb$', deb.name)
        if m:
            result.setdefault(m[1], {})[m[2]] = deb
    return result


def pull(path, target, timeout=1800):
    """adb pull of a root-only file: staged through /data/local/tmp."""
    stage = f'/data/local/tmp/moto-pull-{int(time.time() * 1000)}'
    run(f'cp {shlex.quote(path)} {stage} && chmod 644 {stage}', 'root', timeout=timeout)
    try:
        subprocess.run(moto_device.adb('pull', stage, str(target)), check=True, capture_output=True,
                       timeout=timeout)
    finally:
        run(f'rm -f {stage}', 'root', check=False)


def git_state():
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=WORKSPACE, capture_output=True, text=True,
                            check=True).stdout.strip()
    dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=WORKSPACE,
                                capture_output=True, text=True).stdout.strip())
    return commit, dirty


# ---------------------------------------------------------------- pool

def import_debs(paths):
    POOL.mkdir(parents=True, exist_ok=True)
    added = []
    for path in map(Path, paths):
        name, version, arch = (deb_field(path, f) for f in ('Package', 'Version', 'Architecture'))
        target = POOL / f'{upstream_name(name, version)}_{arch}.deb'
        if target.exists() and target.read_bytes() != path.read_bytes():
            raise SystemExit(f'{target.name} is already in the pool with different contents; '
                             'bump the version instead of replacing a published package')
        if not target.exists():
            shutil.copy2(path, target)
            added.append(target.name)
    return added


def import_installed():
    """Pull .debs of the installed +moto versions listed in packages.json, checked against dpkg's md5sums."""
    wanted = []
    for component in spec()['rebuilt'].values():
        for name in component['packages']:
            wanted.append((name, component['version']))
    installed = dict(line.split('\t') for line in out(
        "dpkg-query -W -f '${Package}\\t${Version}\\n'", 'container').splitlines() if '\t' in line)
    have = pool_debs()
    missing = [(n, v) for n, v in wanted if upstream_name(n, v).split('_', 1)[1] not in have.get(n, {})]
    if not missing:
        return {'imported': [], 'already': len(wanted)}
    for name, version in missing:
        if installed.get(name) != version:
            raise SystemExit(f'{name}: packages.json says {version}, the phone has {installed.get(name)}')
    patterns = ' '.join(f"{d}/{upstream_name(n, v)}_*.deb" for n, v in missing for d in DEVICE_DEB_DIRS)
    script = f'''set -e
tmp=$(mktemp -d /var/tmp/moto-import.XXXXXX)
for f in {patterns}; do
  [ -f "$f" ] || continue
  b=$(basename "$f"); [ -e "$tmp/$b" ] && continue
  n=$(dpkg-deb -f "$f" Package)
  # The .deb must be the one dpkg installed: same md5sums as /var/lib/dpkg/info.
  info=/var/lib/dpkg/info/$n.md5sums; [ -f "$info" ] || info=$(ls /var/lib/dpkg/info/$n:*.md5sums 2>/dev/null | head -1)
  # Hand-assembled .debs (package-mesa.py) carry no md5sums; dpkg computed them at install.
  if ! dpkg-deb --ctrl-tarfile "$f" | tar -xO ./md5sums > "$tmp/.sums" 2>/dev/null; then
    dpkg-deb --fsys-tarfile "$f" | python3 -c '
import hashlib, sys, tarfile
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as t:
    for m in t:
        if m.isfile():
            print(hashlib.md5(t.extractfile(m).read()).hexdigest() + "  " + m.name.removeprefix("./"))' > "$tmp/.sums"
  fi
  # Every installed file matches; extra files may only be ones dpkg's path-exclude dropped.
  if [ -z "$(comm -13 <(sort "$tmp/.sums") <(sort "$info"))" ] && \
     ! comm -23 <(sort "$tmp/.sums") <(sort "$info") | grep -v -E '  usr/share/(doc|man|locale)/' | grep -q .; then
    cp "$f" "$tmp/"
  fi
  rm -f "$tmp/.sums"
done
tar -C "$tmp" -cf /var/tmp/moto-import.tar .
rm -rf "$tmp"
'''
    run(f"bash -c {shlex.quote(script)}", 'container', timeout=600)
    local = APT / 'incoming'
    shutil.rmtree(local, ignore_errors=True)
    local.mkdir(parents=True)
    moto_device.from_container('/var/tmp/moto-import.tar', local / 'x.tar')
    run('rm -f /var/tmp/moto-import.tar', 'container')
    with tarfile.open(local / 'x.tar') as tar:
        tar.extractall(local, filter='data')
    (local / 'x.tar').unlink()
    added = import_debs(sorted(local.glob('*.deb')))
    shutil.rmtree(local)
    have = pool_debs()
    still = [f'{n}={v}' for n, v in missing if upstream_name(n, v).split('_', 1)[1] not in have.get(n, {})]
    if still:
        raise SystemExit(f'not found on the phone (or not identical to what is installed): {still}')
    return {'imported': added}


# ---------------------------------------------------------------- build

def next_version():
    today = datetime.date.today().strftime('%Y%m%d')
    taken = [int(p.stem.split('.')[1]) for p in RELEASES.glob(f'{today}.*.json')] if RELEASES.exists() else []
    return f'{today}.{max(taken, default=0) + 1}'


def build_meta(version, deps, info):
    root = Path(tempfile.mkdtemp(dir=WORKSPACE / '.work/cache'))
    root.chmod(0o755)   # dpkg-deb refuses mkdtemp's 0700
    try:
        (root / 'DEBIAN').mkdir(mode=0o755)
        doc = root / 'usr/share/moto'
        doc.mkdir(parents=True)
        (doc / 'release.json').write_text(json.dumps(info, indent=1, ensure_ascii=False) + '\n')
        depends = ', '.join(f'{n} (= {v})' for n, v in sorted(deps.items()))
        (root / 'DEBIAN/control').write_text(f'''Package: {META}
Version: {version}
Architecture: all
Maintainer: range-dev <noreply@localhost>
Priority: optional
Section: metapackages
Depends: {depends}
Description: Plasma Mobile on Android: release {version}
 Pins every package of this project's release {version} (git {info["commit"][:12]}).
 See docs/61-delivery-diagnostics-plan.md.
''')
        target = POOL / f'{META}_{version}_all.deb'
        built = subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(root), str(target)],
                               capture_output=True, text=True)
        if built.returncode:
            raise SystemExit(f'dpkg-deb: {built.stderr.strip()}')
        return target
    finally:
        shutil.rmtree(root)


def index():
    """Flat repository index: Packages(.gz,.xz) and Release with origin moto / label moto-plasma."""
    packages = subprocess.run(['apt-ftparchive', 'packages', '.'], cwd=POOL, capture_output=True,
                              check=True).stdout
    (POOL / 'Packages').write_bytes(packages)
    (POOL / 'Packages.gz').write_bytes(gzip.compress(packages, mtime=0))
    (POOL / 'Packages.xz').write_bytes(lzma.compress(packages))
    release = subprocess.run(['apt-ftparchive', '-o', 'APT::FTPArchive::Release::Origin=moto',
                              '-o', 'APT::FTPArchive::Release::Label=moto-plasma',
                              '-o', 'APT::FTPArchive::Release::Suite=moto',
                              '-o', 'APT::FTPArchive::Release::Codename=moto', 'release', '.'],
                             cwd=POOL, capture_output=True, check=True).stdout
    (POOL / 'Release').write_bytes(release)


def build(version=None, allow_dirty=False, note=''):
    commit, dirty = git_state()
    if dirty and not allow_dirty:
        raise SystemExit('tracked files have uncommitted changes; commit first (a release records its commit)')
    s = spec()
    deps = {}
    have = pool_debs()
    missing = []
    for component in s['rebuilt'].values():
        for name in component['packages']:
            if upstream_name(name, component['version']).split('_', 1)[1] not in have.get(name, {}):
                missing.append(f"{name}={component['version']}")
            deps[name] = component['version']
    # The project's own packages: the version built from the current commit (tools/moto_package.py).
    if s.get('project'):
        import moto_package
        definitions = moto_package.definitions()
        built = moto_package.builds()
        for name in s['project']:
            pkg = definitions.get(name)
            if pkg is None:
                raise SystemExit(f'{name} has no plasma/packaging definition')
            if not moto_package.current(pkg):
                missing.append(f'{name} (not built for the current sources: moto_package.py build {name})')
                continue
            deps[name] = built[name]['version']
    if missing:
        raise SystemExit(f'not in the pool: {missing} (build them, or import-installed)')
    coupled = {}
    if s.get('coupled'):
        text = out('dpkg-query -W -f \'${Package}\\t${Version}\\n\' ' + ' '.join(map(shlex.quote, s['coupled'])),
                   'container')
        coupled = {n: v for n, v in (line.split('\t') for line in text.splitlines() if '\t' in line) if v}
        if set(s['coupled']) - set(coupled):
            raise SystemExit(f"coupled packages not installed: {sorted(set(s['coupled']) - set(coupled))}")
        deps.update(coupled)
    version = version or next_version()
    if (POOL / f'{META}_{version}_all.deb').exists():
        raise SystemExit(f'release {version} exists already')
    info = {'version': version, 'commit': commit, 'dirty': dirty, 'built': datetime.datetime.now().isoformat(
        timespec='seconds'), 'note': note, 'packages': deps, 'coupled': sorted(coupled),
        'android': android_manifest(s), 'session_restart': s.get('session_restart', [])}
    meta = build_meta(version, deps, info)
    index()
    RELEASES.mkdir(parents=True, exist_ok=True)
    (RELEASES / f'{version}.json').write_text(json.dumps(info, indent=1, ensure_ascii=False) + '\n')
    return {'version': version, 'metapackage': meta.name, 'packages': len(deps), 'commit': commit[:12]}


def android_manifest(s):
    result = {}
    for item in s.get('android', []):
        data = (WORKSPACE / item['source']).read_bytes()
        result[item['path']] = {'source': item['source'], 'mode': item.get('mode', '644'),
                                'sha256': hashlib.sha256(data).hexdigest()}
    return result


def releases():
    if not RELEASES.exists():
        return []
    return sorted((json.loads(p.read_text()) for p in RELEASES.glob('*.json')),
                  key=lambda r: [int(x) for x in r['version'].split('.')])


# ---------------------------------------------------------------- device

def device_release():
    text = run(f"cat /usr/share/moto/release.json 2>/dev/null; dpkg-query -W -f '\\n@@${{Version}}' {META} "
               '2>/dev/null', 'container', check=False).stdout
    body, _, version = text.partition('\n@@')
    try:
        info = json.loads(body) if body.strip() else None
    except ValueError:
        info = None
    return (version.strip() or None), info


def preflight():
    problems = []
    state = run(f'''
[ -e /var/lib/dpkg/lock-frontend ] && fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 && echo "dpkg is locked by another process"
a=$(dpkg --audit 2>&1); [ -n "$a" ] && echo "dpkg --audit: $(echo "$a" | head -3)"
free=$(df -Pk / | awk 'NR==2 {{print $4}}'); [ "$free" -lt 2097152 ] && echo "less than 2 GiB free on /"
systemctl is-system-running >/dev/null 2>&1 || echo "systemd: $(systemctl is-system-running 2>&1)"
true''', 'container', check=False)
    if state.returncode:
        problems.append(f'container not reachable: {state.stderr.strip()}')
    problems += [l for l in state.stdout.splitlines() if l.strip()]
    # systemd "degraded" is common (failed units); record it but do not stop on it.
    fatal = [p for p in problems if not p.startswith('systemd:')]
    return problems, fatal


def installed_versions():
    text = out("dpkg-query -W -f '${db:Status-Abbrev}\\t${Package}\\t${Version}\\n'", 'container', timeout=120)
    return {name: version for status, name, version in
            (line.split('\t') for line in text.splitlines() if line.count('\t') == 2)
            if status.startswith(('ii', 'hi'))}


def integrity_summary():
    text = run('for p in /usr/bin/moto-integrity /usr/local/bin/moto-integrity; do [ -x $p ] && exec $p --json; '
               'done; echo null', 'container', timeout=300, check=False).stdout
    try:
        report = json.loads(text)
    except ValueError:
        return None
    return report


def sync_repo():
    """Mirror .work/apt/repo to /var/lib/moto-apt: push missing .debs, replace the index."""
    listing = run(f'mkdir -p {DEVICE_REPO} && cd {DEVICE_REPO} && ls -1', 'container').stdout.split()
    local = {p.name for p in POOL.iterdir() if p.is_file()}
    send = sorted((local - set(listing)) | {'Packages', 'Packages.gz', 'Packages.xz', 'Release'})
    remove = sorted(set(listing) - local)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as tar:
        for name in send:
            tar.add(POOL / name, arcname=name)
    archive = DEPLOY / 'repo-sync.tar'
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(buffer.getvalue())
    moto_device.extract_in_container(archive, DEVICE_REPO)
    archive.unlink()
    run(f'''set -e
chown -R root:root {DEVICE_REPO}; chmod 755 {DEVICE_REPO}
cd {DEVICE_REPO} && rm -f {' '.join(map(shlex.quote, remove)) or '/dev/null/none 2>/dev/null || true'}''',
        'container', check=False)
    return {'sent': len(send), 'removed': len(remove)}


def ensure_apt_source():
    """The source and pin (moto-plasma-config ships the same files once installed)."""
    run(f'''set -e
cat > /etc/apt/sources.list.d/moto.sources.new <<'EOF'
{SOURCES}EOF
cmp -s /etc/apt/sources.list.d/moto.sources.new /etc/apt/sources.list.d/moto.sources 2>/dev/null \
  && rm /etc/apt/sources.list.d/moto.sources.new || mv /etc/apt/sources.list.d/moto.sources.new /etc/apt/sources.list.d/moto.sources
cat > /etc/apt/preferences.d/moto.new <<'EOF'
{PREFERENCES}EOF
cmp -s /etc/apt/preferences.d/moto.new /etc/apt/preferences.d/moto 2>/dev/null \
  && rm /etc/apt/preferences.d/moto.new || mv /etc/apt/preferences.d/moto.new /etc/apt/preferences.d/moto
''', 'container')


def apt_install(info, record):
    """apt-get install in a transient unit, so an adb disconnect does not interrupt dpkg.

    Every package of the release is named with its exact version: apt does not downgrade
    dependencies on its own, which a rollback needs."""
    version = info['version']
    pins = ' '.join(shlex.quote(f'{n}={v}') for n, v in sorted(info['packages'].items()))
    unit = f'moto-deploy-{int(time.time())}'
    result = run(f'''set -e
apt-get -q update {APT_OURS} >/dev/null
systemd-run --unit={unit} --wait --pipe --collect --quiet -p TimeoutStartSec=3600 \\
  --setenv=DEBIAN_FRONTEND=noninteractive \\
  apt-get -q -y --allow-downgrades --allow-change-held-packages --no-install-recommends \\
  -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install {META}={version} {pins} 2>&1
''', 'container', timeout=3900, check=False)
    (record / 'apt.log').write_text(result.stdout + result.stderr)
    return result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]


def sync_android(info, record):
    """Android-side files of the release: back up what is there, install what the release names."""
    files = info.get('android') or {}
    if not files:
        return []
    changed = []
    backup = record / 'android-before'
    for path, item in files.items():
        current = run(f'sha256sum {shlex.quote(path)} 2>/dev/null | cut -d" " -f1', 'root', check=False).stdout.strip()
        if current == item['sha256']:
            continue
        source = WORKSPACE / item['source']
        if hashlib.sha256(source.read_bytes()).hexdigest() != item['sha256']:
            raise SystemExit(f"{item['source']} changed since release {info['version']} was built; "
                             'check out its commit to deploy it')
        if current:
            backup.mkdir(parents=True, exist_ok=True)
            pull(path, backup / path.strip('/').replace('/', '__'))
        remote = push(source, 'moto-android-file')
        run(f'install -m{item["mode"]} {remote} {shlex.quote(path)}.new && mv {shlex.quote(path)}.new '
            f'{shlex.quote(path)} && rm -f {remote}', 'root')
        changed.append(path)
    return changed


def needs_restart(before, after, patterns):
    changed = [n for n in set(before) | set(after) if before.get(n) != after.get(n)]
    hit = sorted(n for n in changed if any(fnmatch.fnmatch(n, p) for p in patterns))
    return hit, sorted(changed)


def restart_session():
    result = subprocess.run([sys.executable, str(WORKSPACE / 'tools/moto_plasma.py'), 'restart-session'],
                            capture_output=True, text=True, timeout=300)
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def restart_container():
    outputs = []
    for action in ('stop', 'start'):
        result = subprocess.run([sys.executable, str(WORKSPACE / 'tools/moto_plasma.py'), action],
                                capture_output=True, text=True, timeout=300)
        outputs.append((result.stdout + result.stderr).strip())
        if result.returncode:
            return False, '\n'.join(outputs)
    return True, '\n'.join(outputs)


def history():
    return json.loads(HISTORY.read_text()) if HISTORY.exists() else []


def deploy(version=None, restart='auto', acceptance='smoke', record_label=None):
    all_releases = releases()
    if not all_releases:
        raise SystemExit('no release built yet: moto_release.py build')
    info = next((r for r in all_releases if r['version'] == version), None) if version else all_releases[-1]
    if not info:
        raise SystemExit(f'release {version} is not in {RELEASES}')
    version = info['version']
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    record = DEPLOY / f'{stamp}-{record_label or version}'
    record.mkdir(parents=True)
    log = {'version': version, 'started': stamp, 'steps': []}
    started_at = time.time()

    def step(name, **data):
        log['steps'].append({'step': name, 'time': datetime.datetime.now().isoformat(timespec='seconds'), **data})
        (record / 'deploy.json').write_text(json.dumps(log, indent=1, ensure_ascii=False) + '\n')
        print(f'[{name}] ' + ', '.join(f'{k}={v}' for k, v in data.items() if not isinstance(v, (dict, list))),
              flush=True)

    # 1 preflight
    problems, fatal = preflight()
    step('preflight', problems=problems)
    if fatal:
        log['result'] = 'aborted'
        step('abort', reason='; '.join(fatal))
        return log
    # 2 record
    previous, _ = device_release()
    before = installed_versions()
    integrity_before = integrity_summary()
    (record / 'before.json').write_text(json.dumps({'release': previous, 'packages': before}, indent=1) + '\n')
    (record / 'integrity-before.json').write_text(json.dumps(integrity_before, indent=1, ensure_ascii=False) + '\n')
    step('record', previous=previous, integrity=(integrity_before or {}).get('summary', {}).get('state'))
    # 3 sync and install
    ensure_apt_source()
    step('sync', **sync_repo())
    ok, tail = apt_install(info, record)
    step('install', ok=ok)
    if not ok:
        log['result'] = 'install-failed'
        step('abort', reason=tail[-1500:])
        return log
    # The Android side names paths inside the container: it follows a successful install,
    # so a failed one leaves both sides at the previous release.
    android = sync_android(info, record)
    step('android', changed=android)
    after = installed_versions()
    (record / 'after.json').write_text(json.dumps({'release': version, 'packages': after}, indent=1) + '\n')
    # Protection is the release's pin and exact dependencies now; drop the holds they replace.
    held = run('apt-mark showhold', 'container').stdout.split()
    released = [n for n in held if n in info['packages']]
    if released:
        run('apt-mark unhold ' + ' '.join(released), 'container')
    step('holds', released=released)
    # 4 migrations run in maintainer scripts (system) and kded's kconf_update (user, next session).
    # 5 restart
    hit, changed = needs_restart(before, after, info.get('session_restart', []))
    step('changes', changed=changed, restart_for=hit)
    whole = any(path.endswith('/lxc/plasma/config') for path in android)
    if restart == 'always' or (restart == 'auto' and (hit or android)):
        # The LXC configuration (mounts, init) applies only when the container starts.
        ok, text = restart_container() if whole else restart_session()
        step('restart', ok=ok, container=whole, output=text[-500:])
    # 6 verify
    integrity_after = integrity_summary()
    (record / 'integrity-after.json').write_text(json.dumps(integrity_after, indent=1, ensure_ascii=False) + '\n')
    summary = (integrity_after or {}).get('summary', {})
    mismatch = (integrity_after or {}).get('release', {}).get('mismatch', [])
    step('integrity', state=summary.get('state'), release_mismatch=mismatch)
    passed = not mismatch
    if acceptance != 'none':
        import moto_acceptance
        report = moto_acceptance.run_level(acceptance, release=version, out_dir=record / 'acceptance',
                                           since=started_at)
        step('acceptance', level=acceptance, passed=report['passed'], failed=report['failed_ids'])
        passed = passed and report['passed']
    # 7 save
    log['result'] = 'ok' if passed else 'verify-failed'
    step('done', result=log['result'])
    entries = history()
    entries.append({'time': stamp, 'version': version, 'previous': previous, 'result': log['result'],
                    'record': str(record.relative_to(WORKSPACE))})
    HISTORY.write_text(json.dumps(entries, indent=1) + '\n')
    return log


def rollback(restart='auto', acceptance='smoke'):
    current, _ = device_release()
    entries = [e for e in history() if e['result'] in ('ok', 'verify-failed')]
    target = None
    for entry in reversed(entries):
        if entry['version'] == current and entry.get('previous') and entry['previous'] != current:
            target = entry['previous']
            break
    if not target:
        raise SystemExit(f'no earlier release recorded before {current}')
    return deploy(target, restart, acceptance, record_label=f'rollback-to-{target}')


def status():
    version, info = device_release()
    report = integrity_summary()
    built = releases()
    return {
        'installed_release': version,
        'commit': (info or {}).get('commit'),
        'built': (info or {}).get('built'),
        'latest_in_repository': built[-1]['version'] if built else None,
        'releases_in_repository': [r['version'] for r in built][-8:],
        'integrity': (report or {}).get('summary'),
        'release_mismatch': (report or {}).get('release', {}).get('mismatch'),
        'last_deploys': history()[-5:],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('import-installed')
    p = sub.add_parser('import'); p.add_argument('debs', nargs='+')
    p = sub.add_parser('build'); p.add_argument('--version'); p.add_argument('--allow-dirty', action='store_true')
    p.add_argument('--note', default='')
    sub.add_parser('list')
    for name in ('deploy', 'rollback'):
        p = sub.add_parser(name)
        if name == 'deploy':
            p.add_argument('version', nargs='?')
        p.add_argument('--restart', choices=['auto', 'always', 'never'], default='auto')
        p.add_argument('--acceptance', choices=['smoke', 'full', 'none'], default='smoke')
    sub.add_parser('status')
    a = parser.parse_args()
    if a.cmd == 'import-installed':
        result = import_installed()
    elif a.cmd == 'import':
        result = import_debs(a.debs)
        index()
    elif a.cmd == 'build':
        result = build(a.version, a.allow_dirty, a.note)
    elif a.cmd == 'list':
        result = [{k: r[k] for k in ('version', 'commit', 'built', 'note')} for r in releases()]
    elif a.cmd == 'deploy':
        result = deploy(a.version, a.restart, a.acceptance)
    elif a.cmd == 'rollback':
        result = rollback(a.restart, a.acceptance)
    else:
        result = status()
    print(json.dumps(result, indent=1, ensure_ascii=False))
    if isinstance(result, dict) and result.get('result') not in (None, 'ok'):
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except DeviceError as error:
        sys.exit(f'moto_release: {error}')
