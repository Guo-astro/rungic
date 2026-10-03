# SPDX-License-Identifier: MIT
# system-test: as root
"""The container's init (system/init, docs/45) prepares what Flatpak's sandboxes need: a writable
/proc/sys/user and a fully visible proc in /run/rungic-proc. When the kernel or LXC refuses those
mounts, it says so in its log and the container starts all the same (it goes on to /sbin/init).
Run as root in the throwaway test container: mount, umount and mknod are stand-ins that record their
calls and refuse the mounts a test names; /sbin/init is a stand-in that records being reached."""
import os
import subprocess
from pathlib import Path

import harness

SRC = Path('/src')
WORK = Path('/tmp/flatpak-init')
LOG = Path('/var/log/plasma/init.log')
STEPS = []


def check(condition, what, detail=''):
    STEPS.append(what)
    if not condition:
        raise harness.Failed(f'{what}: not so {detail}'.rstrip())


def boot(refused):
    """system/init with the mounts whose target is in `refused` failing; its log and calls."""
    stubs = WORK / 'bin'
    stubs.mkdir(parents=True, exist_ok=True)
    calls = WORK / 'calls'
    calls.write_text('')
    refuse = ' '.join(refused)
    (stubs / 'mount').write_text(f'''#!/bin/sh
echo "mount $*" >> {calls}
for target in {refuse or '/nothing-refused'}; do
    case " $* " in *" $target "*) echo "mount: $target: permission denied" >&2; exit 32;; esac
done
exit 0
''')
    for name in ('umount', 'mknod', 'chmod'):
        (stubs / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {calls}\n')
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    init = WORK / 'sbin-init'
    init.write_text(f'#!/bin/sh\necho "init reached container=$container" >> {calls}\n')
    init.chmod(0o755)
    script = (SRC / 'system/init').read_text()
    assert script.count('exec /sbin/init') == 1
    copy = WORK / 'init'
    copy.write_text(script.replace('exec /sbin/init', f'exec {init}'))
    Path('/var/lib/rungic-host').mkdir(parents=True, exist_ok=True)
    Path('/var/lib/rungic-host/android-shm-context').write_text('u:object_r:rungic_shm:s0')
    LOG.unlink(missing_ok=True)
    result = subprocess.run(['sh', str(copy)], env={'PATH': f'{stubs}:/usr/sbin:/usr/bin:/sbin:/bin'},
                            capture_output=True, text=True, timeout=60)
    return result, LOG.read_text() if LOG.exists() else '', calls.read_text().splitlines()


# covers[system]: apps.flatpak/E3
def test():
    result, log, calls = boot([])
    check(result.returncode == 0 and 'init reached container=lxc' in calls, 'with the mounts allowed, init goes on',
          f'{result.stderr} {log}')
    check('mount --bind /proc/sys/user /proc/sys/user' in calls and 'mount -o remount,bind,rw /proc/sys/user' in calls
          and any(c.startswith('mount -t proc') and c.endswith('/run/rungic-proc') for c in calls),
          'it makes /proc/sys/user writable and mounts a visible proc for the sandboxes', str(calls))
    check('Flatpak sandboxes will fail' not in log, 'and says nothing about Flatpak', log)
    check(oct(os.stat('/run/rungic-proc').st_mode & 0o777) == '0o700', 'the visible proc is only root\'s')

    result, log, calls = boot(['/proc/sys/user', '/run/rungic-proc'])
    check(result.returncode == 0 and 'init reached container=lxc' in calls,
          'with both refused, the container starts all the same', f'{result.stderr} {log}')
    check('/proc/sys/user stays read-only; Flatpak sandboxes will fail' in log
          and 'no visible proc; Flatpak sandboxes will fail' in log, 'and the log says why Flatpak will fail', log)
    check(any(c.startswith('mknod /dev/fuse') or c.startswith('chmod 0666 /dev/fuse') for c in calls),
          'the steps after them still run', str(calls))
    return STEPS


if __name__ == '__main__':
    harness.run('flatpak_init', test)
