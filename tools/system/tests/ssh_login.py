# SPDX-License-Identifier: MIT
# system-test: as root
"""SSH into the container as the installed system has it (docs/83, AGENTS.md 2026-09-29), on a fresh
Ubuntu with openssh-server, run as root in the throwaway test container:

- host keys: the image comes without them; the installer's own step (the ssh-keygen line of
  tools/ci/rungic-firstboot.sh) makes all three for this phone, a second install makes other ones;
  later, the sshd-keygen.service our drop-in changes (sshd-keygen.service.d/rungic.conf) runs
  whenever one is missing, not only on the first boot. Its conditions are merged as systemd does
  and evaluated by systemd-analyze; its ExecStart then runs.
- login: sshd with our sshd_config.d/10-rungic.conf, next to the Ubuntu cloud image's
  60-cloudimg-settings.conf (PasswordAuthentication no). The account's password and a key in
  ~/.ssh/authorized_keys both log in; root logs in with a key only.
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import harness

SRC = Path('/src')
SSH = Path('/etc/ssh')
KEY_TYPES = ('rsa', 'ecdsa', 'ed25519')
PORT = 2222
LOG = []


def sh(argv, check=True, **kwargs):
    result = subprocess.run(argv, capture_output=True, text=True, **kwargs)
    LOG.append(f'$ {" ".join(map(str, argv))} -> {result.returncode}\n{result.stdout[-600:]}{result.stderr[-600:]}')
    if check and result.returncode:
        raise harness.Failed(f'{argv} failed: {result.stdout[-800:]}{result.stderr[-800:]}')
    return result


def host_keys():
    return sorted(p.name for p in SSH.glob('ssh_host_*_key*'))


def fingerprints():
    return {t: sh(['ssh-keygen', '-lf', str(SSH / f'ssh_host_{t}_key.pub')]).stdout.split()[1] for t in KEY_TYPES}


def strip_keys():
    """As the image builders do (build_rootfs_image.py, build_fingerprinted_rootfs.py)."""
    for path in SSH.glob('ssh_host_*_key*'):
        path.unlink()


def installer_keygen():
    """The installer's host key step, as rungic-firstboot.sh runs it in the rootfs it provisions."""
    lines = [l for l in (SRC / 'tools/ci/rungic-firstboot.sh').read_text().splitlines() if 'ssh-keygen' in l]
    if len(lines) != 1:
        raise harness.Failed(f'rungic-firstboot.sh: expected one ssh-keygen step, found {lines}')
    sh(['sh', '-c', f'set -eu\nprovision=/\ndie() {{ echo "$*" >&2; exit 1; }}\n{lines[0]}'])


def keygen_unit():
    """sshd-keygen.service's [Unit] conditions with our drop-in applied, and its ExecStart."""
    unit = Path('/usr/lib/systemd/system/sshd-keygen.service')
    dropin = SRC / 'system/config/usr/lib/systemd/system/sshd-keygen.service.d/rungic.conf'
    if not unit.exists():
        raise harness.Failed('Ubuntu has no sshd-keygen.service: the drop-in changes nothing')
    conditions, start = [], []
    for text in (unit.read_text(), dropin.read_text()):
        for line in text.splitlines():
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if key.startswith('Condition'):
                if value:
                    conditions.append(f'{key}={value}')
                else:
                    conditions = []        # an empty assignment resets every condition (systemd.unit(5))
            elif key == 'ExecStart' and value:
                start.append(value.lstrip('-@:+!'))
    return conditions, start, unit.read_text()


def conditions_hold(conditions):
    if not conditions:
        return True
    return sh(['systemd-analyze', 'condition', *conditions], check=False).returncode == 0


def login(user, password=None, key=None):
    """True when `user` logs in over SSH and runs id -un; with a password only, or a key only."""
    options = ['-p', str(PORT), '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
               '-o', 'ConnectTimeout=10', '-o', 'NumberOfPasswordPrompts=1']
    env = dict(os.environ)
    if password is not None:
        askpass = Path('/tmp/askpass')
        askpass.write_text(f'#!/bin/sh\necho {password}\n')
        askpass.chmod(0o755)
        options += ['-o', 'PreferredAuthentications=password,keyboard-interactive', '-o', 'PubkeyAuthentication=no']
        env.update(SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE='force', DISPLAY=':0')
    else:
        options += ['-i', str(key), '-o', 'IdentitiesOnly=yes', '-o', 'PreferredAuthentications=publickey',
                    '-o', 'BatchMode=yes']
    result = sh(['ssh', *options, f'{user}@127.0.0.1', 'id -un'], check=False, env=env,
                stdin=subprocess.DEVNULL, timeout=30)
    return result.returncode == 0 and result.stdout.strip() == user


# covers[system]: install.ssh-access/E2 install.ssh-access/E3
def test():
    steps = []
    sshd = None

    def check(condition, what):
        steps.append(what)
        if not condition:
            log = Path('/tmp/sshd.log').read_text()[-1500:] if Path('/tmp/sshd.log').exists() else ''
            raise harness.Failed(what + ': not so\n' + '\n'.join(LOG[-6:]) + '\n--- sshd ---\n' + log)

    try:
        # ---- host keys -------------------------------------------------------------------------
        strip_keys()
        check(host_keys() == [], 'no host keys, as the image is built (tools/system/tests/rootfs_image.py)')
        installer_keygen()
        check(all((SSH / f'ssh_host_{t}_key').exists() and (SSH / f'ssh_host_{t}_key.pub').exists() for t in KEY_TYPES),
              'installation makes the three host keys (RSA, ECDSA, Ed25519)')
        first = fingerprints()
        strip_keys()
        installer_keygen()
        check(all(fingerprints()[t] != first[t] for t in KEY_TYPES), 'another installation has its own host keys')

        conditions, start, unit = keygen_unit()
        LOG.append(unit)
        check(start, 'sshd-keygen.service has an ExecStart')
        check('ConditionFirstBoot=yes' not in conditions, 'not limited to the first boot')
        check(not conditions_hold(conditions), 'all keys there: sshd-keygen does not run')
        kept = fingerprints()
        for missing in KEY_TYPES:
            for suffix in ('', '.pub'):
                (SSH / f'ssh_host_{missing}_key{suffix}').unlink()
            check(conditions_hold(conditions), f'the {missing} key missing: sshd-keygen runs')
            for command in start:
                sh(['sh', '-c', command])
            now = fingerprints()
            check((SSH / f'ssh_host_{missing}_key').exists() and now[missing] != kept[missing],
                  f'the missing {missing} key is made again')
            check(all(now[t] == kept[t] for t in KEY_TYPES if t != missing), 'the keys that were there are kept')
            kept = now

        # ---- login -----------------------------------------------------------------------------
        conf = SSH / 'sshd_config.d'
        conf.mkdir(exist_ok=True)
        shutil.copy(SRC / 'system/config/etc/ssh/sshd_config.d/10-rungic.conf', conf / '10-rungic.conf')
        (conf / '60-cloudimg-settings.conf').write_text('PasswordAuthentication no\n')
        effective = sh(['sshd', '-T']).stdout
        check(re.search(r'^passwordauthentication yes$', effective, re.M), 'sshd reads our setting before the cloud image\'s')
        sh(['chpasswd'], input='tester:Tester-pass-1\nroot:Root-pass-1\n')
        sh(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', '/tmp/client'])
        public = Path('/tmp/client.pub').read_text()
        for home, owner in ((Path('/home/tester'), 'tester'), (Path('/root'), 'root')):
            (home / '.ssh').mkdir(mode=0o700, exist_ok=True)
            (home / '.ssh/authorized_keys').write_text(public)
            (home / '.ssh/authorized_keys').chmod(0o600)
            shutil.chown(home / '.ssh', owner, owner)
            shutil.chown(home / '.ssh/authorized_keys', owner, owner)
        Path('/run/sshd').mkdir(mode=0o755, exist_ok=True)
        sshd = subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-p', str(PORT), '-o', 'ListenAddress=127.0.0.1'],
                                stdout=subprocess.DEVNULL, stderr=open('/tmp/sshd.log', 'w'))
        deadline = time.monotonic() + 15
        while sh(['bash', '-c', f'exec 3<>/dev/tcp/127.0.0.1/{PORT}'], check=False).returncode:
            if time.monotonic() > deadline or sshd.poll() is not None:
                check(False, 'sshd listening')
            time.sleep(0.2)

        check(login('tester', password='Tester-pass-1'), 'the account logs in with its password')
        check(login('tester', key='/tmp/client'), 'the account logs in with a key in ~/.ssh/authorized_keys')
        check(not login('tester', password='wrong'), 'a wrong password does not log in')
        check(login('root', key='/tmp/client'), 'root logs in with a key')
        check(not login('root', password='Root-pass-1'), "root's password does not log in")
    finally:
        if sshd:
            sshd.kill()
    return steps


if __name__ == '__main__':
    harness.run('ssh_login', test)
