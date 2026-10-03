# SPDX-License-Identifier: MIT
"""The session's GPU environment (desktop/gpu-env, /etc/plasma/gpu-env), sourced by the session, KWin
and the workspaces: hardware Mesa on KGSL, Qt Quick and GTK on GL (not Vulkan: whole grey frames,
docs/56), and nothing left over that forces software rendering. What the GPU then draws, and whether
a frame flashes grey, is the phone's to show (docs/51, docs/56)."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GPU_ENV = ROOT / 'desktop/gpu-env'


def session(env):
    """The environment after the file is sourced, as desktop/session does."""
    out = subprocess.run(['sh', '-c', f'. "{GPU_ENV}" && env -0'], env=env, capture_output=True, check=True).stdout
    return dict(line.split('=', 1) for line in out.decode().split('\0') if '=' in line)


# covers: apps.gpu/E2
def test_qt_quick_and_gtk_draw_with_gl_on_kgsl():
    env = session({'PATH': '/usr/bin:/bin', 'LIBGL_ALWAYS_SOFTWARE': '1', 'QT_QUICK_BACKEND': 'software',
                   'LD_LIBRARY_PATH': '/opt/old-mesa/lib'})
    assert env['QSG_RHI_BACKEND'] == 'opengl' and env['GSK_RENDERER'] == 'gl'
    assert env['MESA_LOADER_DRIVER_OVERRIDE'] == 'kgsl' and env['FD_KGSL_ENABLE_DMABUF'] == '1'
    assert env['KWIN_COMPOSE'] == 'O2ES'
    # Left over from a software-rendering session: gone, or Qt Quick and Mesa would render on the CPU.
    assert 'LIBGL_ALWAYS_SOFTWARE' not in env and 'LD_LIBRARY_PATH' not in env and env['QT_QUICK_BACKEND'] == ''
