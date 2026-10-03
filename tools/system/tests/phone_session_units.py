# SPDX-License-Identifier: MIT
"""The phone mode's coordinator (agent/assistant/session, docs/101) built from the working tree and its
unit tests run off the phone: session-core-test and session-state-test, whose cases say what they cover
(the mute and hang-up case runs against a stand-in of the Android communication audio socket). The
package build runs the same tests (packaging/rungic-voice-agent/build.sh); this runs them on every
change without building a package."""
import os
import subprocess

import harness

BUILD = '/tmp/build-session'


def test():
    steps = []
    log = open('/tmp/session-build.log', 'w')
    for argv in (['cmake', '-S', '/src/agent/assistant/session', '-B', BUILD, '-DBUILD_TESTING=ON',
                  '-DCMAKE_BUILD_TYPE=RelWithDebInfo'],
                 ['cmake', '--build', BUILD, '-j', str(os.cpu_count() or 4),
                  '--target', 'session-core-test', 'session-state-test']):
        if subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT).returncode:
            raise harness.Failed('build failed: ' + open('/tmp/session-build.log').read()[-1500:])
    steps.append('built session-core-test and session-state-test')
    for name in ('session-core-test', 'session-state-test'):
        done = subprocess.run([f'{BUILD}/{name}'], capture_output=True, text=True, timeout=120,
                              env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})
        if done.returncode:
            raise harness.Failed(f'{name}: {(done.stderr or done.stdout)[-1500:]}')
        steps.append(f'{name}: {done.stdout.strip()[-200:]}')
    return steps


if __name__ == '__main__':
    harness.run('phone_session_units', test)
