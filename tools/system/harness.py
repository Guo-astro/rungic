# SPDX-License-Identifier: MIT
"""System tests without Android (quality/README.md 分层; run by tools/system_test.py in its container).

Session starts a headless KWin (--virtual: no GPU, no display, no Android) of the given size, as the
phone's or a PC's, and gives a test what it needs to drive and observe the Linux system: programs
started in it, KWin's stacking (layer, fullscreen, active), pointer and keys through the fake-input
helper rungic-workspace-input. What Android would provide comes from stand-ins of the interfaces'
contracts (tools/contracts.py).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

STACK_JS = '''
const out = [];
const wins = workspace.stackingOrder;
for (let i = 0; i < wins.length; i++) {
  const w = wins[i], f = w.frameGeometry;
  out.push({caption: w.caption, cls: String(w.resourceClass), layer: w.layer, full: w.fullScreen,
            active: w.active, frame: [f.x, f.y, f.width, f.height]});
}
callDBus("SERVICE", "/com/rungic/Cua", "com.rungic.Cua", "Report", JSON.stringify(out));
'''


class Failed(AssertionError):
    pass


class Session:
    def __init__(self, width, height, name='system', outputs=1):
        self.runtime = Path(f'/tmp/rt-{os.getuid()}')
        self.runtime.mkdir(mode=0o700, exist_ok=True)
        os.environ.update(XDG_RUNTIME_DIR=str(self.runtime), WAYLAND_DISPLAY=f'wayland-{name}', QT_QPA_PLATFORM='wayland',
                          GDK_BACKEND='wayland', LANG='C.UTF-8', LIBGL_ALWAYS_SOFTWARE='1')
        self.log = open(f'/tmp/kwin-{name}.log', 'w')
        # The test's own KWin, not a user's: restricted protocols (fake input, screencast) without the
        # desktop-file grants (KWin's switch for test setups); the grants are the phone's to check.
        kwin_env = {**os.environ, 'KWIN_WAYLAND_NO_PERMISSION_CHECKS': '1'}
        self.kwin = subprocess.Popen(['kwin_wayland', '--virtual', '--width', str(width), '--height', str(height),
                                      '--socket', f'wayland-{name}', '--no-lockscreen', '--no-global-shortcuts',
                                      '--no-kactivities', *(['--output-count', str(outputs)] if outputs > 1 else [])],
                                     stdout=self.log, stderr=subprocess.STDOUT, env=kwin_env)
        self.children = []
        self.steps = []
        self.wait_for(lambda: (self.runtime / f'wayland-{name}').exists(), 20, 'KWin listening')
        from rungic_cua.kwin import KWin
        self.kwin_api = KWin()
        self.wait_for(self.try_stack, 20, 'KWin scripting')
        self.input = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.input:
            self.input.close()
        for child in self.children:
            child.kill()
        self.kwin.kill()

    # ---- driving -------------------------------------------------------------------------------
    def start(self, argv, **kwargs):
        child = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=open(f'/tmp/{Path(argv[-1]).name}.err', 'a'), **kwargs)
        self.children.append(child)
        return child

    def pointer(self):
        if not self.input:
            from rungic_cua.fakeinput import WorkspaceInput
            self.input = WorkspaceInput(self.kwin_api.cursor)
            self.input.start()
        return self.input

    def tap(self, x, y):
        """A click as a finger's tap: there first, then pressed and let go."""
        inp = self.pointer()
        inp.glide(x + 7, y + 5)
        time.sleep(0.1)
        inp.glide(x, y)
        time.sleep(0.2)
        inp.click(x, y)
        time.sleep(0.5)

    def key(self, name):
        self.pointer().chord([name])
        time.sleep(0.5)

    # ---- observing -----------------------------------------------------------------------------
    def try_stack(self):
        try:
            return self.kwin_api._script(STACK_JS) is not None
        except Exception:
            return False

    def stack(self):
        return self.kwin_api._script(STACK_JS)

    def find(self, **want):
        for window in self.stack():
            if all(window.get(k) == v for k, v in want.items()):
                return window
        return None

    def wait_for(self, condition, timeout=10, what='condition'):
        deadline = time.monotonic() + timeout
        while True:
            value = condition()
            if value:
                return value
            if time.monotonic() > deadline:
                raise Failed(f'timed out waiting for {what}')
            time.sleep(0.2)

    def check(self, condition, what):
        self.steps.append(what)
        if not condition:
            raise Failed(f'{what}: not so; stacking {json.dumps(self.stack(), ensure_ascii=False)}')


def run(name, test):
    """Runs test() and prints its result as the one JSON line tools/system_test.py reads."""
    started = time.monotonic()
    try:
        steps = test()
        print(json.dumps({'test': name, 'passed': True, 'seconds': round(time.monotonic() - started, 1), 'steps': steps},
                         ensure_ascii=False), flush=True)
    except Exception as error:
        print(json.dumps({'test': name, 'passed': False, 'seconds': round(time.monotonic() - started, 1),
                          'error': f'{type(error).__name__}: {error}'}, ensure_ascii=False), flush=True)
        sys.exit(1)
