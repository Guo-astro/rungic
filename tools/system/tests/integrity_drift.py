# SPDX-License-Identifier: MIT
# system-test: as root
"""rungic-integrity on a real Ubuntu rootfs and its dpkg database (docs/61): the throwaway test
container is the system. It starts clean (the programs this harness built into /usr are declared
local, as the phone's machine-local files are); then package files are changed and removed, files no
package owns appear, a local credential gets the wrong mode, and each is reported by name with the
state drift. Files the image never installed (dpkg path-exclude) are not reported. A development
overlay (tools/rungic_dev.py) is the state development, its apt files not unowned. Credentials are
declared by path, owner and mode only: their contents never appear in the report."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import harness

TOOL = '/src/system/diagnostics/rungic-integrity'
MANIFEST = Path('/tmp/local-config.json')
SECRET = 'http_proxy=http://agent:S3CRET-TOKEN@proxy:6152'
LOG = []
CHANGED = REMOVED = None


def integrity(declared):
    MANIFEST.write_text(json.dumps({'files': declared}))
    done = subprocess.run(['python3', TOOL, '--json', '--manifest', str(MANIFEST)], capture_output=True, text=True)
    if not done.stdout.startswith('{'):
        raise harness.Failed(f'rungic-integrity exit {done.returncode}: {done.stderr[-3000:]}')
    report = json.loads(done.stdout)
    shown = {k: v for k, v in report.items() if k not in ('local', 'rebuilt')}
    shown['summary'] = {k: v for k, v in report['summary'].items() if v}
    LOG.append(json.dumps(shown)[-6000:] + done.stderr[-1000:])
    return done.returncode, done.stdout, report


def package_files(package):
    listed = subprocess.run(['dpkg', '-L', package], capture_output=True, text=True, check=True).stdout.split()
    return [p for p in listed if os.path.isfile(p) and not os.path.islink(p) and p.startswith('/usr/bin/')]


def deb(name, version, depends, files, links=None):
    """A real package, built and installed with dpkg (a release metapackage, as rungic_release.py makes)."""
    root = Path(f'/tmp/deb-{name}')
    shutil.rmtree(root, ignore_errors=True)
    (root / 'DEBIAN').mkdir(parents=True)
    (root / 'DEBIAN/control').write_text(f'Package: {name}\nVersion: {version}\nArchitecture: all\n'
                                         f'Maintainer: test <test@invalid>\nDepends: {depends}\nDescription: test\n')
    for path, text in files.items():
        (root / path.lstrip('/')).parent.mkdir(parents=True, exist_ok=True)
        (root / path.lstrip('/')).write_text(text)
    for path, target in (links or {}).items():
        (root / path.lstrip('/')).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, root / path.lstrip('/'))
    subprocess.run(['dpkg-deb', '--root-owner-group', '-b', str(root), f'/tmp/{name}.deb'], check=True, capture_output=True)
    subprocess.run(['dpkg', '-i', f'/tmp/{name}.deb'], check=True, capture_output=True)


# covers[system]: delivery.integrity/E1, delivery.integrity/E2, delivery.integrity/E3, delivery.integrity/E4
def test():
    steps = []

    def check(condition, what):
        steps.append(what)
        if not condition:
            raise harness.Failed(what + ': not so\n' + (LOG[-1] if LOG else ''))

    # The container as built differs from the phone's rootfs in three ways, and they are found: the
    # Docker build removed apt's lists (a package's directory is missing), the image diverts initctl
    # locally (a development state), and systemd-coredump's core_pattern sysctl is not masked (on the
    # phone rungic-plasma-config ships the mask).
    code, _, first = integrity([])
    s = first['summary']
    check(code == 1 and s['state'] == 'drift', 'the container as built: drift')
    check([p['path'] for p in first['packages']['missing']] == ['/var/lib/apt/lists/partial'], "a missing package directory (apt's)")
    check([d['path'] for d in first['diversions']['project']] == ['/sbin/initctl'] and s['development'],
          'a local dpkg diversion: development')
    check(first['crash'] == ["/etc/sysctl.d/50-coredump.conf is not masked: systemd-sysctl could redirect Android's core_pattern"],
          "the crash chain's precondition")
    os.makedirs('/var/lib/apt/lists/partial', mode=0o700, exist_ok=True)
    subprocess.run(['dpkg-divert', '--local', '--rename', '--remove', '/sbin/initctl'], check=True, capture_output=True)
    deb('rungic-test-config', '1', 'systemd-coredump', {}, links={'/etc/sysctl.d/50-coredump.conf': '/dev/null'})
    # What no package owns now (this harness's cmake installs) is declared local, as the phone's
    # machine-local files are.
    _, _, first = integrity([])
    built = first['unowned']['usr'] + first['unowned']['etc']
    declared = [{'path': p} for p in built]
    code, _, report = integrity(declared)
    s = report['summary']
    check(code == 0 and s['state'] == 'clean', 'the fresh system is clean')
    verify = subprocess.run(['dpkg', '--verify'], capture_output=True, text=True).stdout
    excluded = [l.split()[-1] for l in verify.splitlines() if l.startswith('missing') and '/usr/share/' in l]
    check(s['missing_files'] == 0,
          f'files the image never installed (dpkg path-exclude; dpkg --verify: {len(excluded)} missing) are not reported')

    # Drift of every kind, each named.
    global CHANGED, REMOVED
    changed, removed = CHANGED, REMOVED = package_files('openssh-client')[:2]
    shutil.copy2(changed, '/tmp/changed-file')
    with open(changed, 'ab') as f:
        f.write(b'\0drift')
    os.rename(removed, '/tmp/removed-file')
    Path('/etc/rungic-unowned.conf').write_text('x=1\n')
    Path('/usr/local/bin').mkdir(parents=True, exist_ok=True)
    shutil.copy('/usr/bin/true', '/usr/local/bin/ssh')                 # shadows the packaged command
    Path('/usr/share/rungic-user-file').write_text('')
    os.chown('/usr/share/rungic-user-file', 1000, 1000)
    Path('/etc/profile.d').mkdir(exist_ok=True)
    Path('/etc/profile.d/proxy.sh').write_text(SECRET + '\n')
    os.chmod('/etc/profile.d/proxy.sh', 0o666)
    local = [{'path': '/etc/profile.d/proxy.sh', 'owner': 'root', 'mode': '0644', 'required': True},
             {'path': '/var/lib/rungic-host/audio-cookie', 'owner': '1000', 'mode': '0600', 'required': True}]
    code, text, report = integrity(declared + local)
    s = report['summary']
    owner = lambda path: next(p['package'] for p in report['packages']['changed'] + report['packages']['missing']
                              if p['path'] == path)
    check(code == 1 and s['state'] == 'drift', 'any drift is the state drift (exit 1)')
    check([p['path'] for p in report['packages']['changed']] == [changed] and owner(changed) == 'openssh-client',
          f'a changed package file is named with its package ({changed})')
    check([p['path'] for p in report['packages']['missing']] == [removed] and owner(removed) == 'openssh-client',
          f'a missing package file is named with its package ({removed})')
    check(report['unowned']['etc'] == ['/etc/rungic-unowned.conf'], 'a file in /etc that no package owns')
    check(report['unowned']['usr_local_shadowing'] == ['/usr/local/bin/ssh'], 'a /usr/local file shadowing a packaged command')
    check(report['ownership']['non_root_files'] == ['/usr/share/rungic-user-file'], 'a file in /usr owned by a user')
    proxy, cookie = report['local'][-2:]
    check(proxy['present'] and proxy['problems'] == ['mode 0o666, want 0644'], 'a credential with the wrong mode')
    check(not cookie['present'] and s['local_missing_required'] == 1, 'a required local file that is absent')
    check('S3CRET' not in text and 'http_proxy' not in text and 'S3CRET' not in MANIFEST.read_text(),
          'credentials are checked by path, owner and mode; their contents appear nowhere')

    # A rule that the file is not installed (path-exclude) takes it out of the report.
    Path('/etc/dpkg/dpkg.cfg.d/zz-system-test').write_text(f'path-exclude={removed}\n')
    _, _, report = integrity(declared + local + [{'path': '/etc/dpkg/dpkg.cfg.d/zz-system-test'}])
    check(report['packages']['missing'] == [], 'a path-exclude rule silences its missing file')

    # Put back: clean again.
    shutil.copy2('/tmp/removed-file', removed)
    shutil.copy2('/tmp/changed-file', changed)
    for path in ('/etc/rungic-unowned.conf', '/usr/local/bin/ssh', '/usr/share/rungic-user-file',
                 '/etc/dpkg/dpkg.cfg.d/zz-system-test'):
        os.unlink(path)
    os.chmod('/etc/profile.d/proxy.sh', 0o644)
    Path('/var/lib/rungic-host').mkdir(parents=True, exist_ok=True)
    Path('/var/lib/rungic-host/audio-cookie').write_text('cookie')
    os.chown('/var/lib/rungic-host/audio-cookie', 1000, 1000)
    os.chmod('/var/lib/rungic-host/audio-cookie', 0o600)
    code, _, report = integrity(declared + local)
    check(code == 0 and report['summary']['state'] == 'clean', 'with everything put back, clean again')

    # A development overlay on a release: the metapackage's release.json names the base release and
    # the overrides (rungic_dev.py), its apt source and pins are not unowned files.
    version = subprocess.run(['dpkg-query', '-W', '-f', '${Version}', 'openssh-client'], capture_output=True,
                             text=True).stdout
    release = {'version': '20261003.1', 'commit': 'abc1234',
               'dev': {'base': '20261003.1', 'overrides': {'rungic-plasma-session': {
                   'version': '0.300+dev20261003T120000.abc1234', 'commit': 'abc1234', 'dirty': False}}}}
    deb('rungic-release', '20261003.1+dev1', f'openssh-client (= {version})',
        {'/usr/share/rungic/release.json': json.dumps(release)})
    Path('/etc/apt/preferences.d').mkdir(parents=True, exist_ok=True)
    Path('/etc/apt/preferences.d/rungic-dev').write_text('Package: rungic-plasma-session\nPin: version 0.300+dev*\n'
                                                       'Pin-Priority: 1001\n')
    Path('/etc/apt/sources.list.d/rungic-dev.sources').write_text('Types: deb\nURIs: file:/var/lib/rungic-apt/dev\n'
                                                                 'Suites: ./\nTrusted: yes\n')
    code, _, report = integrity(declared + local)
    s = report['summary']
    check(code == 2 and s['state'] == 'development' and s['development'], 'a development overlay is the state development (exit 2)')
    check(report['release']['dev'] == {'base': '20261003.1',
                                       'overrides': {'rungic-plasma-session': '0.300+dev20261003T120000.abc1234'}}
          and s['dev_overrides'] == 1, 'release.dev lists the base release and the overrides')
    check(report['release']['installed'] and report['release']['mismatch'] == [], "the release's exact dependencies are met")
    check(report['unowned']['etc'] == [] and report['unowned']['usr'] == [],
          "the overlay's own apt files are not unowned")
    return steps


def tidy():
    """Leave the container to the tests after this one as it was (they share it)."""
    subprocess.run(['dpkg', '--purge', 'rungic-release', 'rungic-test-config'], capture_output=True)
    for path in ('/etc/apt/preferences.d/rungic-dev', '/etc/apt/sources.list.d/rungic-dev.sources',
                 '/etc/profile.d/proxy.sh', '/var/lib/rungic-host/audio-cookie', '/etc/rungic-unowned.conf',
                 '/usr/local/bin/ssh', '/usr/share/rungic-user-file', '/etc/dpkg/dpkg.cfg.d/zz-system-test'):
        Path(path).unlink(missing_ok=True)
    for saved, path in (('/tmp/changed-file', CHANGED), ('/tmp/removed-file', REMOVED)):
        if path and os.path.exists(saved):
            shutil.copy2(saved, path)


def checked():
    try:
        return test()
    finally:
        tidy()


if __name__ == '__main__':
    harness.run('integrity_drift', checked)
