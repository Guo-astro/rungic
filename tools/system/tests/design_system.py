# SPDX-License-Identifier: MIT
"""The design system's C++ halves (desktop/design: PageSwipe, SystemTheme) as an app has them: the
com.rungic.design module built from the working tree, and desktop/design/tests/tst_design.qml run
by qmltestrunner offscreen against it. Meanwhile this test turns the system's colours dark and light
the way System Settings does (kdeglobals [Colors:Window] BackgroundNormal, written with KConfig's
change notice on the session bus), so the running SystemTheme has something to follow. The
experiences are tagged in tst_design.qml."""
import os
import subprocess
import tempfile
import time
from pathlib import Path

import harness

DARK, LIGHT = '35,38,41', '239,240,241'      # Breeze Dark's and Breeze Light's window background


def test():
    with tempfile.TemporaryDirectory(prefix='design-') as work:
        work = Path(work)
        for step in (['cmake', '-S', '/src/desktop/design', '-B', work / 'build', '-DCMAKE_BUILD_TYPE=RelWithDebInfo'],
                     ['cmake', '--build', work / 'build', f'-j{os.cpu_count()}']):
            built = subprocess.run(step, capture_output=True, text=True, check=False)
            if built.returncode:
                raise harness.Failed(f'{step[:2]}: {(built.stdout + built.stderr)[-3000:]}')
        config = work / 'config'
        config.mkdir()
        env = {**os.environ, 'XDG_CONFIG_HOME': str(config), 'QT_QPA_PLATFORM': 'offscreen',
               'QT_QUICK_CONTROLS_STYLE': 'Basic', 'QML_IMPORT_PATH': str(work / 'build/qml')}

        def colours(rgb):
            subprocess.run(['kwriteconfig6', '--notify', '--file', 'kdeglobals', '--group', 'Colors:Window',
                            '--key', 'BackgroundNormal', rgb], env=env, check=True)
        colours(DARK)
        runner = subprocess.Popen(['/usr/lib/qt6/bin/qmltestrunner', '-input', '/src/desktop/design/tests/tst_design.qml'],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.monotonic() + 120
        turn = 0
        while runner.poll() is None and time.monotonic() < deadline:
            time.sleep(1)
            turn += 1
            colours(LIGHT if turn % 2 else DARK)
        if runner.poll() is None:
            runner.kill()
        output = runner.communicate()[0]
    lines = output.splitlines()
    if runner.returncode or not any(line.startswith('Totals:') and ' 0 failed' in line for line in lines):
        raise harness.Failed('\n'.join(lines[-40:]))
    return [line for line in lines if line.startswith(('PASS', 'Totals'))]


if __name__ == '__main__':
    harness.run('design_system', test)
