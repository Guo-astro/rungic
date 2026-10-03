# SPDX-License-Identifier: MIT
"""The Rime keyboard's own checks (docs/41) where their dependencies are: desktop/rime/tests/run.sh
builds the plugin and rungic-rime-check from the working tree, runs the engine and session-lifecycle
check, then the session test inside Qt Virtual Keyboard (offscreen; no KWin, no Android). The
experiences are tagged where they are checked: check.cpp, tests/tst_session.qml and run.sh."""
import subprocess
import tempfile

import harness


def test():
    with tempfile.TemporaryDirectory(prefix='rime-') as work:
        result = subprocess.run(['sh', '/src/desktop/rime/tests/run.sh', work], capture_output=True, text=True,
                                timeout=900, check=False)
    lines = (result.stdout + result.stderr).splitlines()
    steps = [line[5:] for line in lines if line.startswith('ok   ')]
    steps += [line for line in lines if line.startswith(('PASS', 'Totals'))]
    if result.returncode or not any(line.startswith('PASS: Rime engine and session lifecycle') for line in lines):
        raise harness.Failed('\n'.join(lines[-40:]))
    return steps


if __name__ == '__main__':
    harness.run('rime_keyboard', test)
