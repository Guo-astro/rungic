# SPDX-License-Identifier: MIT
# system-test: as root
"""SSH is on by itself on a newly installed system (AGENTS.md, 2026-09-29): on a fresh Ubuntu rootfs
with openssh-server, rungic-plasma-config's postinst applies the service policy for the first time
(desktop/services/policy.json) and leaves ssh.socket enabled, not masked; a group kept off is masked.
A device that recorded SSH before keeps what it has: the user's choice in Settings -> Services
survives upgrades. Runs as root in the throwaway test container, which is the fresh system."""
import json
import shutil
import subprocess
from pathlib import Path

import harness

SRC = Path('/src')
STATE = Path('/var/lib/rungic/service-defaults')
WANTS = Path('/etc/systemd/system/sockets.target.wants/ssh.socket')


LOG = []


def postinst():
    # As dpkg runs it: deb-systemd-helper does nothing unless called from a maintainer script.
    env = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'DPKG_MAINTSCRIPT_PACKAGE': 'rungic-plasma-config',
           'DPKG_MAINTSCRIPT_NAME': 'postinst', 'DPKG_MAINTSCRIPT_ARCH': 'all'}
    run = subprocess.run(['sh', '-x', str(SRC / 'packaging/rungic-plasma-config/postinst'), 'configure'],
                         capture_output=True, text=True, env=env)
    LOG.append(run.stdout[-1500:] + run.stderr[-3000:])
    run.check_returncode()


def where():
    """What the failure message shows: the postinst's trace, the state and the ssh units' links."""
    links = subprocess.run('ls -l /etc/systemd/system/*.wants/ssh* /etc/systemd/system/ssh* 2>&1; '
                           'cat /var/lib/rungic/service-defaults 2>&1 | grep -i ssh', shell=True,
                           capture_output=True, text=True).stdout
    return f'\n{links}\n--- postinst ---\n{LOG[-1] if LOG else ""}'


def enabled(unit):
    """systemctl reads the unit files offline (no systemd runs here); deb-systemd-helper's is-enabled
    reads only its own records."""
    state = subprocess.run(['systemctl', 'is-enabled', unit], capture_output=True, text=True).stdout.strip()
    return state == 'enabled'


def masked(unit):
    path = Path('/etc/systemd/system') / unit
    return path.is_symlink() and str(path.readlink()) == '/dev/null'


# covers[system]: install.ssh-access/E1 desktop.services-ssh/E4
def test():
    steps = []

    def check(condition, what):
        steps.append(what)
        if not condition:
            raise harness.Failed(what + ': not so' + where())

    policy = json.loads((SRC / 'desktop/services/policy.json').read_text())
    ssh = next(g for g in policy['groups'] if 'ssh.socket' in g.get('system', []))

    def install(default):
        """A fresh system (no policy applied yet) and the package's postinst, SSH's default `default`."""
        STATE.unlink(missing_ok=True)
        Path('/usr/share/rungic').mkdir(parents=True, exist_ok=True)
        Path('/usr/share/rungic/service-policy.json').write_text(json.dumps(
            {**policy, 'groups': [{**g, 'default': default} if g is ssh else g for g in policy['groups']]}))
        postinst()

    check(enabled('ssh.socket'), "the image as built: openssh-server's own install enabled ssh.socket")
    install(ssh['default'])
    check(ssh['default'] == 'enabled', 'policy.json: SSH is on by default')
    check(enabled('ssh.socket') and WANTS.is_symlink(), 'the first install leaves ssh.socket enabled (sockets.target wants it)')
    check(not masked('ssh.socket') and not masked('ssh.service'), 'ssh.socket and ssh.service are not masked')
    check('system ssh.socket' in STATE.read_text().splitlines(), 'the default is recorded, so it is applied once')
    kept_off = next(u for g in policy['groups'] if g['default'] == 'masked' for u in g.get('system', []))
    check(masked(kept_off), f'a group kept off is masked ({kept_off})')

    # The user turns SSH off in Settings -> Services (its helper: systemctl disable); an upgrade runs
    # postinst again.
    subprocess.run(['systemctl', 'disable', 'ssh.socket', 'ssh.service'], check=True, capture_output=True)
    postinst()
    check(not enabled('ssh.socket') and not WANTS.exists(), "an upgrade keeps the user's choice: recorded units are left as they are")

    # The defect this guards against (found 2026-10-03): with the old default, a first install turned
    # SSH off. (deb-systemd-helper's enable does not undo its own earlier disable, so this goes last.)
    subprocess.run(['systemctl', 'enable', 'ssh.socket'], check=True, capture_output=True)
    install('disabled')
    check(not enabled('ssh.socket') and not WANTS.exists(), 'the old default "disabled" would turn SSH off on a first install')
    return steps


if __name__ == '__main__':
    harness.run('ssh_on_first_install', test)
