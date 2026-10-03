# SPDX-License-Identifier: MIT
# system-test: as root
"""Rootless Docker's system side on a fresh Ubuntu rootfs (docs/85), as root in the throwaway test
container: system/docker/prepare (run at boot by rungic-docker-prepare.service) gives every login
account a subordinate ID range and a data directory named by its UID, and the TUN device; an
account renamed the way the account setup renames it (usermod --login, then system/account's
rename_subordinate) keeps its data and its range. And rungic-plasma-config's service policy masks the
rootful docker and containerd units, which cannot run in the phone's container."""
import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

import harness

SRC = Path('/src')
DATA = Path('/var/lib/rungic-docker')
STEPS = []


def check(condition, what, detail=''):
    STEPS.append(what)
    if not condition:
        raise harness.Failed(f'{what}: not so {detail}'.rstrip())


def run(*argv, **kwargs):
    return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def ranges(path):
    """login -> (start, count) in /etc/subuid or /etc/subgid."""
    out = {}
    for line in Path(path).read_text().splitlines():
        name, start, count = line.split(':')
        out[name] = (int(start), int(count))
    return out


def prepare():
    result = run('sh', str(SRC / 'system/docker/prepare'))
    check(result.returncode == 0, 'prepare finishes', result.stderr)
    return result


def account_setup():
    spec = importlib.util.spec_from_file_location('account_setup', SRC / 'system/account/setup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# covers[system]: apps.docker/E5 apps.docker/E6
def test():
    for name, uid, shell in (('alice', 1101, '/bin/bash'), ('bob', 1102, '/bin/bash'), ('daemonish', 1103, '/usr/sbin/nologin')):
        run('userdel', '-r', name)
        run('useradd', '-m', '-u', str(uid), '-s', shell, name, check=True)
    # Accounts from before useradd gave subordinate ranges: none for alice (nor for daemonish).
    for path in ('/etc/subuid', '/etc/subgid'):
        lines = [line for line in Path(path).read_text().splitlines(keepends=True)
                 if not line.startswith(('alice:', 'daemonish:'))]
        Path(path).write_text(''.join(lines))
    result = prepare()

    tun = Path('/dev/net/tun')
    if tun.exists():
        st = os.stat(tun)
        check(stat.S_ISCHR(st.st_mode) and os.major(st.st_rdev) == 10 and os.minor(st.st_rdev) == 200
              and st.st_mode & 0o777 == 0o666, 'the TUN device is there for everyone (c 10:200, 0666)')
    else:
        check('no /dev/net/tun' in result.stderr, 'without TUN allowed, prepare says so and goes on', result.stderr)
    for path in ('/etc/subuid', '/etc/subgid'):
        found = ranges(path)
        check('alice' in found and found['alice'][1] == 65536, f'{path}: the account without a range gets 65536 IDs')
        spans = sorted((start, start + count) for start, count in found.values())
        check(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), f'{path}: no range overlaps another', str(spans))
        check('daemonish' not in found, f'{path}: an account that cannot log in gets none')
    tester = int(run('id', '-u', 'tester').stdout)
    for name, uid in (('alice', 1101), ('bob', 1102), ('tester', tester)):
        st = os.stat(DATA / str(uid))
        check(st.st_uid == uid and st.st_mode & 0o777 == 0o700, f'{name}: a data directory of its own, by UID, 0700')
    check(not (DATA / '1103').exists(), 'none for an account that cannot log in')

    # The account setup renames alice; the next boot's prepare.
    (DATA / '1101/image.db').write_text('layers')
    directories = sorted(p.name for p in DATA.iterdir())
    before = {path: ranges(path)['alice'] for path in ('/etc/subuid', '/etc/subgid')}
    run('usermod', '--login', 'alicia', 'alice', check=True)
    account_setup().rename_subordinate('alice', 'alicia')
    prepare()
    check((DATA / '1101/image.db').read_text() == 'layers', 'renamed, the account keeps its Docker data')
    for path, span in before.items():
        found = ranges(path)
        check(found.get('alicia') == span and 'alice' not in found, f'{path}: and its range, under the new name')
    check(sorted(p.name for p in DATA.iterdir()) == directories, 'and no second data directory',
          str(sorted(p.name for p in DATA.iterdir())))

    # The service policy, applied by rungic-plasma-config on a first install, masks rootful Docker.
    policy = json.loads((SRC / 'desktop/services/policy.json').read_text())
    Path('/usr/share/rungic').mkdir(parents=True, exist_ok=True)
    Path('/usr/share/rungic/service-policy.json').write_text(json.dumps(policy))
    Path('/var/lib/rungic/service-defaults').unlink(missing_ok=True)
    env = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'DPKG_MAINTSCRIPT_PACKAGE': 'rungic-plasma-config',
           'DPKG_MAINTSCRIPT_NAME': 'postinst', 'DPKG_MAINTSCRIPT_ARCH': 'all'}
    result = run('sh', str(SRC / 'packaging/rungic-plasma-config/postinst'), 'configure', env=env)
    check(result.returncode == 0, 'rungic-plasma-config configures', result.stderr[-800:])
    for unit in ('docker.service', 'docker.socket', 'containerd.service'):
        path = Path('/etc/systemd/system') / unit
        check(path.is_symlink() and str(path.readlink()) == '/dev/null', f'rootful {unit} is masked')
    user = Path('/etc/systemd/user/docker.service')
    check(not (user.is_symlink() and str(user.readlink()) == '/dev/null'), 'the rootless user docker.service is not masked')
    return STEPS


if __name__ == '__main__':
    harness.run('docker_prepare', test)
