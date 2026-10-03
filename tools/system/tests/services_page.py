# SPDX-License-Identifier: MIT
# system-test: as root
"""Settings -> Services (desktop/services, docs/83) as the user sees it: the KCM plugin built from the
working tree, loaded as System Settings loads it (desktop/services/tests/show_page.cpp) and shown
offscreen as the ordinary user, on a system with real masks: one of the policy's groups masked
whole, one in part, a mask in /etc that is not on Rungic's list (system and user) and one of
Ubuntu's in /usr/lib. systemd does not run in the container, so `systemctl show` answers from a
stand-in on the page's PATH, with the states each run sets. SSH's host key is the container's own,
compared with what ssh-keyscan reads from a running sshd. Root sets the system up and puts back
what it changed."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import harness

SRC = Path('/src')
POLICY = Path('/usr/share/rungic/service-policy.json')
RISK = {'remote': 'Reachable from the network', 'android': 'May affect Android',
        'unknown': 'Unknown impact', 'none': 'No use on this device'}
EVIDENCE = {'recorded': '', 'inferred': ' (inferred, not tested)', 'unknown': ' (reason not recorded)'}
SYSTEMCTL = r'''#!/usr/bin/python3
# systemctl show, as systemd answers it, from the states in $RUNGIC_TEST_UNITS.
import json, os, sys
args = sys.argv[1:]
states = json.load(open(os.environ['RUNGIC_TEST_UNITS']))
scope = 'user' if '--user' in args else 'system'
if 'show' not in args:
    sys.exit(0)
units = args[args.index('--') + 1:]
blocks = []
for unit in units:
    s = states.get(scope, {}).get(unit)
    if s is None:
        s = {'LoadState': 'not-found', 'ActiveState': 'inactive', 'UnitFileState': ''}
    blocks.append('Id=%s\nLoadState=%s\nActiveState=%s\nUnitFileState=%s' % (unit, s['LoadState'], s['ActiveState'], s['UnitFileState']))
print('\n\n'.join(blocks))
'''


def sh(*args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, check=True, **kwargs).stdout


def test():
    steps = []

    def check(condition, what, detail=''):
        steps.append(what)
        if not condition:
            raise harness.Failed(f'{what}: not so {detail}')

    work = Path(tempfile.mkdtemp(prefix='services-'))
    work.chmod(0o755)
    made = []                         # links this test made, removed at the end
    saved_policy = POLICY.read_bytes() if POLICY.exists() else None
    sshd = None
    try:
        # The plugin and the driver, built from the tree.
        for source, build in ((SRC / 'desktop/services', work / 'kcm'), (SRC / 'desktop/services/tests', work / 'driver')):
            for step in (['cmake', '-S', str(source), '-B', str(build), '-DCMAKE_BUILD_TYPE=RelWithDebInfo'],
                         ['cmake', '--build', str(build), f'-j{os.cpu_count()}']):
                built = subprocess.run(step, capture_output=True, text=True)
                if built.returncode:
                    raise harness.Failed(f'{" ".join(step[:3])}: {(built.stdout + built.stderr)[-3000:]}')
        plugin = next((work / 'kcm').rglob('kcm_rungic_services.so'))
        driver = work / 'driver/show-page'

        # The installed policy, and masks on the system.
        policy = json.loads((SRC / 'desktop/services/policy.json').read_text())
        POLICY.parent.mkdir(parents=True, exist_ok=True)
        POLICY.write_text(json.dumps(policy))
        groups = {g['id']: g for g in policy['groups']}
        for path in ('/etc/systemd/system/systemd-resolved.service',            # group resolved: all of it
                     '/etc/systemd/system/NetworkManager.service',              # group networkmanager: one of two
                     '/etc/systemd/system/rungic-test-other.service',           # not on Rungic's list
                     '/etc/systemd/user/rungic-test-user.service',
                     '/usr/lib/systemd/system/rungic-test-dist.service'):       # Ubuntu's kind
            link = Path(path)
            if not link.is_symlink():
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to('/dev/null')
                made.append(link)
        distribution = sorted(p.name for p in Path('/usr/lib/systemd/system').iterdir()
                              if p.is_symlink() and os.readlink(p) == '/dev/null')
        user_dir = Path('/usr/lib/systemd/user')
        distribution += sorted(f'{p.name} (user)' for p in (user_dir.iterdir() if user_dir.is_dir() else [])
                               if p.is_symlink() and os.readlink(p) == '/dev/null')

        bin_dir = work / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'systemctl').write_text(SYSTEMCTL)
        (bin_dir / 'systemctl').chmod(0o755)
        units = work / 'units.json'

        def page(states, *extra):
            units.write_text(json.dumps(states))
            units.chmod(0o644)
            env = {'PATH': f'{bin_dir}:/usr/local/bin:/usr/bin:/bin', 'HOME': '/home/tester', 'LANG': 'C.UTF-8',
                   'QT_QPA_PLATFORM': 'offscreen', 'QT_QUICK_BACKEND': 'software', 'RUNGIC_TEST_UNITS': str(units),
                   'XDG_RUNTIME_DIR': str(work / 'runtime')}
            (work / 'runtime').mkdir(mode=0o700, exist_ok=True)
            os.chown(work / 'runtime', *[int(x) for x in sh('id', '-u', 'tester').split() + sh('id', '-g', 'tester').split()])
            shown = subprocess.run(['runuser', '-u', 'tester', '--', 'env', '-i', *[f'{k}={v}' for k, v in env.items()],
                                    str(driver), str(plugin), *extra], capture_output=True, text=True, timeout=120)
            lines = [l for l in shown.stdout.splitlines() if l.startswith('{')]
            if shown.returncode or not lines:
                raise harness.Failed(f'the page did not load: {shown.stdout[-1500:]} {shown.stderr[-3000:]}')
            return json.loads(lines[-1])

        def control(result, text, kind=None):
            return next((c for c in result['controls'] if c['text'] == text and (kind is None or c['class'].startswith(kind))), None)

        # SSH on and running (as after a first install), docker off.
        running = {'system': {'ssh.socket': {'LoadState': 'loaded', 'ActiveState': 'active', 'UnitFileState': 'enabled'},
                              'ssh.service': {'LoadState': 'loaded', 'ActiveState': 'inactive', 'UnitFileState': 'disabled'},
                              'NetworkManager-wait-online.service': {'LoadState': 'loaded', 'ActiveState': 'inactive', 'UnitFileState': 'disabled'}},
                   'user': {'docker.service': {'LoadState': 'loaded', 'ActiveState': 'inactive', 'UnitFileState': 'disabled'}}}
        shown = page(running)
        check(shown['error'] == '', 'the page loads the installed policy', shown['error'])

        # covers[system]: desktop.services-ssh/E1
        # The groups, in the policy's order, each with its reason, its basis and its risk.
        check([g['id'] for g in shown['groups']] == list(groups), 'every group of the policy is listed, in order')
        for g in shown['groups']:
            p = groups[g['id']]
            check(g['name'] == p['name'] and g['summary'] == p['summary'] and g['risk'] == p['risk']
                  and g['evidence'] == p['evidence'], f'{g["id"]}: its name, reason, basis and risk from the policy', g)
            check(g['kind'] == ('optional' if p['default'] in ('enabled', 'disabled') else 'masked'), f'{g["id"]}: its kind')
            row = control(shown, p['name'], 'FormSwitchDelegate')
            check(row is not None and row['visible'], f'{g["id"]}: a switch on the page', shown['controls'])
            if g['kind'] == 'masked':
                described = row['description']
                check(RISK[p['risk']] in described and p['summary'] + EVIDENCE[p['evidence']] in described
                      and all(u in described for u in p.get('system', [])), f'{g["id"]}: the page says why, how sure and the risk',
                      described)
        status = {g['id']: (g['status'], g['on']) for g in shown['groups']}
        def mask(unit):
            link = Path('/etc/systemd/system') / unit
            return link.is_symlink() and os.readlink(link) == '/dev/null'
        check(status['resolved'] == ('Masked', False), 'a group masked in /etc shows masked, switched off', status['resolved'])
        partly = 'Masked' if all(mask(u) for u in groups['networkmanager']['system']) else 'Partly masked'
        check(status['networkmanager'] == (partly, False), 'a group masked in part shows so', status['networkmanager'])
        if not any(mask(u) for u in groups['chrony']['system']):     # (another test's postinst may have masked it)
            check(status['chrony'] == ('Allowed (not installed)', True), 'an unmasked group not installed shows so, on',
                  status['chrony'])
        check(status['docker'] == ('Off', False), 'an optional group not enabled is off', status['docker'])
        # Ubuntu's masks: listed, as words only.
        check(sorted(shown['distributionMasks']) == sorted(distribution) and 'rungic-test-dist.service' in shown['distributionMasks'],
              "Ubuntu's masks in /usr/lib are listed", shown['distributionMasks'])
        holders = [c for c in shown['controls'] if 'rungic-test-dist.service' in c['text'] + c['description']]
        check(any(c['class'].startswith('FormTextDelegate') for c in holders)
              and not any(c['class'].startswith(('FormSwitchDelegate', 'FormButtonDelegate', 'QQuickSwitch', 'QQuickButton'))
                          for c in holders), "they are shown as text, with nothing to change them", holders)
        # Other masks in /etc: listed, each a button that unmasks it; the policy's own are not repeated.
        check(sorted((m['scope'], m['unit']) for m in shown['otherMasks']) ==
              [('system', 'rungic-test-other.service'), ('user', 'rungic-test-user.service')],
              "masks in /etc that are not on Rungic's list are listed apart", shown['otherMasks'])
        check(control(shown, 'rungic-test-other.service', 'FormButtonDelegate') is not None
              and control(shown, 'rungic-test-user.service (user)', 'FormButtonDelegate') is not None,
              'each with a button to unmask it')

        # covers[system]: desktop.services-ssh/E3
        # SSH: its state, a command for each of the phone's addresses, and the host key an SSH client sees.
        ssh = groups['ssh']
        check(status['ssh'] == ('Running', True), 'SSH on and running: the switch is on, "Running"', status['ssh'])
        addresses = sorted(f'{line.split()[3].split("/")[0]}  {line.split()[1]}'
                           for line in sh('ip', '-4', '-o', 'addr', 'show', 'up').splitlines() if line.split()[1] != 'lo')
        check(addresses and sorted(shown['addresses']) == addresses, "the addresses are the system's own", (shown['addresses'], addresses))
        connect = control(shown, 'Command to connect')
        commands = [f'ssh tester@{a.split()[0]}   ({a.split()[1]})' for a in addresses]
        check(connect and connect['visible'] and all(c in connect['description'] for c in commands),
              'the page gives the command for each address, with the account', connect)
        os.makedirs('/run/sshd', exist_ok=True)
        sshd = subprocess.Popen(['/usr/sbin/sshd', '-D', '-p', '2222', '-o', 'ListenAddress=127.0.0.1'])
        scanned = ''
        for _ in range(50):
            scanned = subprocess.run(['ssh-keyscan', '-p', '2222', '-t', 'ed25519', '127.0.0.1'], capture_output=True,
                                     text=True).stdout
            if scanned.strip():
                break
            subprocess.run(['sleep', '0.2'])
        seen = subprocess.run(['ssh-keygen', '-l', '-f', '-'], input=scanned, capture_output=True, text=True).stdout.split()
        key = control(shown, 'Host key fingerprint (ED25519)')
        check(len(seen) > 1 and seen[1].startswith('SHA256:') and shown['hostKey'] == seen[1]
              and key and key['visible'] and key['description'] == seen[1],
              'the host key fingerprint shown is what ssh-keyscan reads from the running sshd', (shown['hostKey'], seen))
        # SSH turned off: the switch and the words follow, and the connection details go.
        off = {**running, 'system': {**running['system'],
                                     'ssh.socket': {'LoadState': 'loaded', 'ActiveState': 'inactive', 'UnitFileState': 'disabled'}}}
        shown = page(off)
        state = next((g['status'], g['on']) for g in shown['groups'] if g['id'] == 'ssh')
        check(state == ('Off', False), 'SSH turned off: the switch is off, "Off"', state)
        check(not control(shown, 'Command to connect')['visible'] and not control(shown, 'Host key fingerprint (ED25519)')['visible'],
              'and the page no longer offers a command or a key')
        row = control(shown, ssh['name'], 'FormSwitchDelegate')
        check(row and row['checked'] is False, "the SSH switch shows it", row)

        # Turning on a group with a risk asks first; cancelling leaves the switch and the system as
        # they were (the confirmation's half of E2; the polkit prompt needs a system bus and polkit).
        shown = page(running, 'cancel', 'resolved')
        check(shown['confirmOpened'] and shown['confirmText'] == groups['resolved']['warning'],
              'turning on a risky group asks first, with its warning', shown)
        check(shown['switchChecked'] is False and not shown['busy'], 'cancelled: the switch is back off, nothing runs', shown)
        check(Path('/etc/systemd/system/systemd-resolved.service').is_symlink(), 'and the mask is still there')
        return steps
    finally:
        if sshd:
            sshd.kill()
        for link in made:
            link.unlink(missing_ok=True)
        if saved_policy is None:
            POLICY.unlink(missing_ok=True)
        else:
            POLICY.write_bytes(saved_policy)
        subprocess.run(['rm', '-rf', str(work)])


if __name__ == '__main__':
    harness.run('services_page', test)
