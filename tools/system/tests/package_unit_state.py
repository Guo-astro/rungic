# SPDX-License-Identifier: MIT
# system-test: as root
"""Our packages keep the administrator's choice of their units (docs/70): the maintainer scripts
tools/rungic_package.py generates are installed with the real dpkg, apt and deb-systemd-helper of
a fresh Ubuntu system. A first installation enables a unit; an upgrade, and a removal followed by a
reinstallation, keep a disable; 'obsolete' links of old manual installs go only when dangling. A
renamed package (formerly) conflicts with and replaces its old name, so apt removes the old package
when the new one is installed, and the new unit takes the old unit's enable state. Runs as root in
the throwaway test container, which is the fresh system."""
import subprocess
from pathlib import Path

import harness
import rungic_package

WORK = Path('/tmp/package-unit-state')
SYSTEM = Path('/etc/systemd/system')
WANTS = SYSTEM / 'multi-user.target.wants'
MIRROR = Path('/var/lib/systemd/deb-systemd-helper-enabled')
LOG = []


def sh(*argv, check=True):
    result = subprocess.run(argv, capture_output=True, text=True,
                            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'DEBIAN_FRONTEND': 'noninteractive'})
    LOG.append(f'$ {" ".join(argv)}\n{result.stdout[-800:]}{result.stderr[-800:]}')
    if check and result.returncode:
        raise harness.Failed(f'{" ".join(argv)} failed: {result.stdout[-800:]}{result.stderr[-800:]}')
    return result


def deb(name, version, unit, formerly=None, obsolete=()):
    """A package as rungic_package builds it: its unit, the generated maintainer scripts and control."""
    target = WORK / f'{name}_{version}_all.deb'
    if target.exists():
        return target
    folder = WORK / f'{name}-{version}'
    root = folder / 'root'
    (root / 'DEBIAN').mkdir(parents=True)
    unit_file = root / 'usr/lib/systemd/system' / unit
    unit_file.parent.mkdir(parents=True)
    unit_file.write_text('[Unit]\nDescription=test unit\n[Service]\nExecStart=/bin/true\n'
                         '[Install]\nWantedBy=multi-user.target\n')
    pkg = {'name': name, 'architecture': 'all', 'description': f'{name} (system test)', 'dir': folder,
           'units': {'system': [unit]}}
    if formerly:
        pkg['formerly'] = formerly
    if obsolete:
        pkg['obsolete'] = list(obsolete)
    rungic_package.maintainer_scripts(pkg, root)
    rungic_package.control(pkg, version, root)
    sh('dpkg-deb', '--root-owner-group', '--build', str(root), str(target))
    return target


def enabled(unit):
    return sh('systemctl', 'is-enabled', unit, check=False).stdout.strip() == 'enabled'


def installed(name):
    return sh('dpkg-query', '-W', '-f', '${db:Status-Abbrev}', name, check=False).stdout.startswith('ii')


# covers[system]: delivery.packaging/E3 delivery.packaging/E4
def test():
    steps = []

    def check(condition, what):
        steps.append(what)
        if not condition:
            raise harness.Failed(what + ': not so\n' + '\n'.join(LOG[-6:]))

    WORK.mkdir(parents=True, exist_ok=True)

    # E3: the enable state of a unit through upgrades and reinstallation.
    unit = 'rungic-plain.service'
    sh('dpkg', '-i', str(deb('rungic-plain', '1', unit)))
    check(enabled(unit), 'a first installation enables the unit')
    sh('systemctl', 'disable', unit)
    sh('dpkg', '-i', str(deb('rungic-plain', '2', unit)))
    check(not enabled(unit), "an upgrade keeps the administrator's disable")
    sh('dpkg', '-r', 'rungic-plain')
    sh('dpkg', '-i', str(deb('rungic-plain', '2', unit)))
    check(not enabled(unit), "removal and reinstallation keep the administrator's disable")
    sh('systemctl', 'enable', unit)
    sh('dpkg', '-i', str(deb('rungic-plain', '3', unit)))
    check(enabled(unit), 'an upgrade keeps an enabled unit enabled')

    # E3: obsolete files of old manual installs; links go only when dangling.
    WANTS.mkdir(parents=True, exist_ok=True)
    dangling, live = WANTS / 'old-gone.service', WANTS / 'rungic-obs.service'
    dangling.symlink_to('/etc/systemd/system/old-gone.service')
    live.symlink_to('/usr/lib/systemd/system/rungic-obs.service')
    tool = Path('/usr/local/lib/old-tool')
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text('old\n')
    sh('dpkg', '-i', str(deb('rungic-obs', '1', 'rungic-obs.service', obsolete=[str(dangling), str(live), str(tool)])))
    check(not dangling.is_symlink(), 'an obsolete dangling link is removed')
    check(live.is_symlink() and live.exists(), 'an obsolete link that resolves (the enable link of now) is kept')
    check(not tool.exists(), 'an obsolete file is removed')

    # E4: the rename. apt removes the old package; the new unit is as enabled as the old one was.
    for state in ('enabled', 'disabled'):
        old, new = f'moto-ren{state}', f'rungic-ren{state}'
        sh('dpkg', '-i', str(deb(old, '1', f'{old}.service')))
        check(enabled(f'{old}.service'), f'{old}: enabled by its first installation')
        if state == 'disabled':
            sh('systemctl', 'disable', f'{old}.service')
        renamed = deb(new, '1', f'{new}.service', formerly=old,
                      obsolete=[f'/etc/systemd/system/multi-user.target.wants/{old}.service'])
        sh('apt-get', 'install', '-y', '-q', '--no-install-recommends', str(renamed))
        check(installed(new) and not installed(old), f'apt installed {new} and removed {old} (Conflicts, Replaces)')
        check(enabled(f'{new}.service') == (state == 'enabled'), f'{new}.service is {state}, as {old}.service was')
        check(not (MIRROR / f'{old}.service.dsh-also').exists(), f"{old}'s enable record is purged")
        check(not (WANTS / f'{old}.service').is_symlink(), f"{old}'s enable link is gone")
    return steps


if __name__ == '__main__':
    harness.run('package_unit_state', test)
