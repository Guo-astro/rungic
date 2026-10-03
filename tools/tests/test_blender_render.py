# SPDX-License-Identifier: MIT
"""Rungic's Blender modules (system/config/usr/lib/blender/scripts, docs/90) against a stand-in of
Blender's Python API: the render defaults a startup module sets (Cycles on the CPU, half the CPU
threads, the viewport's GPU backend kept at Vulkan unless the user wrote OPENGL) and the progressive
render (batches of one sample sequence, the window left free). What the stand-in renders is a known
function of the sample numbers, so the batches' average can be compared with one render of them all.
Whether Adreno draws the viewport right with Vulkan is the phone's to show (docs/90)."""
import importlib
import json
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
BLENDER = ROOT / 'system/config/usr/lib/blender/scripts'
PHONE_CORES = 8


class Pixels:
    def __init__(self, values):
        self.values = np.asarray(values, np.float32)

    def foreach_get(self, out):
        out[:] = self.values

    def foreach_set(self, values):
        self.values = np.array(values, np.float32)


class Images:
    """bpy.data.images: what renders wrote (by path) and what _save wrote out."""

    def __init__(self, files):
        self.files = files
        self.saved = {}

    def load(self, path, check_existing=True):
        values = self.files[path]
        return SimpleNamespace(size=(2, 2), pixels=Pixels(values), name=path)

    def new(self, name, width, height, float_buffer=False):
        image = SimpleNamespace(pixels=Pixels(np.zeros(width * height * 4)))
        image.save_render = lambda path: self.saved.__setitem__(path, image.pixels.values.copy())
        return image

    def remove(self, image):
        pass

    def __contains__(self, name):
        return False


def sample(n):
    """What sample number n of the scene contributes to each of the 2x2 RGBA pixels."""
    return np.array([np.sin(n + 1.0 + i) for i in range(16)], np.float32)


def scene(engine='BLENDER_EEVEE', threads_mode='AUTO', threads=0, samples=60):
    return SimpleNamespace(
        render=SimpleNamespace(engine=engine, threads_mode=threads_mode, threads=threads, filepath='',
                               use_persistent_data=False,
                               image_settings=SimpleNamespace(file_format='PNG', color_depth='8')),
        cycles=SimpleNamespace(device='GPU', samples=samples, use_denoising=True, use_sample_subset=False,
                               sample_offset=0, sample_subset_length=0))


@pytest.fixture
def bpy(tmp_path, monkeypatch):
    """A stand-in of the parts of bpy (and gpu) the modules use, installed for the import."""
    files, renders, timers = {}, [], []
    data = SimpleNamespace(filepath='', scenes=[scene()], images=Images(files))
    preferences = SimpleNamespace(view=SimpleNamespace(show_splash=True),
                                  system=SimpleNamespace(gpu_backend='OPENGL'))

    def render(write_still=False):
        s = context.scene
        c = s.cycles
        numbers = range(c.sample_offset, c.sample_offset + c.sample_subset_length) if c.use_sample_subset \
            else range(c.samples)
        renders.append((s.render.engine, list(numbers)))
        files[s.render.filepath] = np.mean([sample(n) for n in numbers], axis=0)
        Path(s.render.filepath).write_bytes(b'exr')

    context = SimpleNamespace(scene=data.scenes[0], preferences=preferences)
    ops = SimpleNamespace(render=SimpleNamespace(render=render),
                          wm=SimpleNamespace(save_userpref=mock.Mock(), save_as_mainfile=mock.Mock()))
    handlers = types.ModuleType('bpy.app.handlers')
    handlers.persistent = lambda function: function
    handlers.load_post, handlers.load_factory_startup_post, handlers.render_init = [], [], []
    app = types.ModuleType('bpy.app')
    app.handlers = handlers
    app.background, app.factory_startup, app.binary_path = False, False, '/usr/bin/blender'
    app.timers = SimpleNamespace(register=lambda function, first_interval=0, persistent=False: timers.append(function))
    module = types.ModuleType('bpy')
    module.app, module.data, module.context, module.ops = app, data, context, ops
    module.utils = SimpleNamespace(user_resource=lambda kind: str(tmp_path / 'config'))
    gpu = types.ModuleType('gpu')
    gpu.platform = SimpleNamespace(vendor_get=lambda: 'freedreno')
    module.renders, module.timers, module.gpu = renders, timers, gpu
    monkeypatch.setitem(sys.modules, 'bpy', module)
    monkeypatch.setitem(sys.modules, 'bpy.app', app)
    monkeypatch.setitem(sys.modules, 'bpy.app.handlers', handlers)
    monkeypatch.setitem(sys.modules, 'gpu', gpu)
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path / 'run'))
    monkeypatch.syspath_prepend(str(BLENDER / 'modules'))
    monkeypatch.syspath_prepend(str(BLENDER / 'startup'))
    return module


def defaults(bpy):
    """The startup module as Blender loads it, on the phone's eight cores, its first timer run."""
    with mock.patch('os.cpu_count', return_value=PHONE_CORES):
        sys.modules.pop('rungic_render_defaults', None)
        module = importlib.import_module('rungic_render_defaults')
    module.register()
    for timer in bpy.timers:
        timer()
    return module


def start(bpy, backend):
    """A new start of Blender's window: the preference as saved, the module run again."""
    bpy.context.preferences.system.gpu_backend = backend
    bpy.timers.clear()
    bpy.ops.wm.save_userpref.reset_mock()
    return defaults(bpy)


# covers: apps.blender/E1
def test_a_new_scene_renders_with_cycles_on_half_the_cpu(bpy):
    defaults(bpy)
    s = bpy.data.scenes[0]
    assert (s.render.engine, s.cycles.device) == ('CYCLES', 'CPU')
    assert (s.render.threads_mode, s.render.threads) == ('FIXED', PHONE_CORES // 2)
    assert bpy.context.preferences.view.show_splash is False
    # A script asks for automatic threads or eight: the render starts with four.
    for mode, threads in (('AUTO', 0), ('FIXED', 8)):
        s.render.threads_mode, s.render.threads = mode, threads
        for handler in bpy.app.handlers.render_init:
            handler(s)
        assert (s.render.threads_mode, s.render.threads) == ('FIXED', 4)
    s.render.threads = 2                     # fewer is the script's choice
    for handler in bpy.app.handlers.render_init:
        handler(s)
    assert s.render.threads == 2


# covers: apps.blender/E1
def test_an_opened_file_keeps_its_engine_but_not_more_threads(bpy):
    defaults(bpy)
    bpy.data.filepath = '/home/me/scene.blend'
    bpy.data.scenes[:] = [scene(engine='BLENDER_EEVEE', threads_mode='FIXED', threads=8)]
    for handler in bpy.app.handlers.load_post:
        handler()
    s = bpy.data.scenes[0]
    assert s.render.engine == 'BLENDER_EEVEE' and s.render.threads == 4


# covers: apps.blender/E2
def test_every_window_start_keeps_the_viewport_on_vulkan(bpy, tmp_path):
    defaults(bpy)
    system = bpy.context.preferences.system
    assert system.gpu_backend == 'VULKAN' and bpy.ops.wm.save_userpref.called
    marker = tmp_path / 'config/rungic-gpu-backend'
    assert marker.read_text().startswith('VULKAN')
    # An older Blender still on OpenGL saved OpenGL back when it quit: the next start puts Vulkan back,
    # so what this session saves on quitting says Vulkan.
    start(bpy, 'OPENGL')
    assert system.gpu_backend == 'VULKAN' and bpy.ops.wm.save_userpref.called
    start(bpy, 'VULKAN')
    assert system.gpu_backend == 'VULKAN' and not bpy.ops.wm.save_userpref.called


def test_background_and_other_gpus_are_left_alone(bpy):
    bpy.app.background = True
    defaults(bpy)
    assert bpy.context.preferences.system.gpu_backend == 'OPENGL'
    bpy.app.background = False
    bpy.gpu.platform.vendor_get = lambda: 'AMD'
    start(bpy, 'OPENGL')
    assert bpy.context.preferences.system.gpu_backend == 'OPENGL'


# covers: apps.blender/E3
def test_opengl_written_by_the_user_is_kept(bpy, tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/rungic-gpu-backend').write_text('OPENGL\n')
    defaults(bpy)
    assert bpy.context.preferences.system.gpu_backend == 'OPENGL'
    assert not bpy.ops.wm.save_userpref.called
    assert (tmp_path / 'config/rungic-gpu-backend').read_text() == 'OPENGL\n'


def render_module(bpy):
    sys.modules.pop('rungic_render', None)
    module = importlib.import_module('rungic_render')
    module.reports = []     # the chat's task card (rungic_cua.activity), not written here
    module._report = lambda text, image='', progress=None, state='working': module.reports.append((image, progress, state))
    return module


# covers: apps.blender/E4
def test_batches_show_previews_and_end_as_one_render(bpy, tmp_path):
    rr = render_module(bpy)
    assert rr.schedule(60) == [(0, 4), (4, 8), (12, 16), (28, 32)]
    assert rr.schedule(64) == [(0, 4), (4, 8), (12, 16), (28, 36)]
    bpy.app.background = True
    s = bpy.data.scenes[0]
    s.render.engine = 'CYCLES'
    seen = []
    real_status = rr._status
    rr._status = lambda output, **fields: (seen.append(fields), real_status(output, **fields))
    output = str(tmp_path / 'Pictures/ball.png')
    rr.render(output)
    # Each batch a further part of the same sample sequence, as the chat's previews show it.
    assert [numbers for _, numbers in bpy.renders] == [list(range(o, o + n)) for o, n in rr.schedule(60)]
    progress = [(f['samples'], f['of']) for f in seen if f['phase'] == 'rendering']
    assert progress == [(4, 60), (12, 60), (28, 60), (60, 60)]
    status = json.loads(Path(output + '.status.json').read_text())
    assert status['phase'] == 'done' and status['samples'] == 60 and status['preview'] == output
    # The finished picture is the render of all 60 samples at once.
    one_render = np.mean([sample(n) for n in range(60)], axis=0)
    np.testing.assert_allclose(bpy.data.images.saved[output], one_render, rtol=1e-5)
    assert s.render.image_settings.file_format == 'PNG' and s.cycles.use_sample_subset is False
    assert [p for _, p, _ in rr.reports] == [4 / 60, 12 / 60, 28 / 60, 1.0, 1.0] and rr.reports[-1][2] == 'done'


# covers: apps.blender/E4
def test_in_the_window_a_background_blender_renders_and_the_call_returns(bpy, tmp_path):
    rr = render_module(bpy)
    output = str(tmp_path / 'ball.png')
    with mock.patch.object(rr.subprocess, 'Popen') as popen:
        status = rr.render(output)
    assert status == output + '.status.json' and not bpy.renders     # nothing rendered in the window
    argv = popen.call_args.args[0]
    assert argv[:2] == ['/usr/bin/blender', '-b'] and argv[3] == '--python-expr'
    assert f'_render_here({output!r}' in argv[4] and popen.call_args.kwargs['start_new_session']
    copy = bpy.ops.wm.save_as_mainfile.call_args.kwargs
    assert copy['copy'] is True and copy['filepath'] == argv[2]
    assert json.loads(Path(status).read_text())['phase'] == 'rendering'
    # The window follows the status file: a preview is shown once, and following ends when done.
    tick = bpy.timers[-1]
    shown = []
    rr._show = lambda path, state: shown.append(path)
    preview = tmp_path / 'preview.jpg'
    preview.write_bytes(b'jpg')
    rr._status(output, phase='rendering', samples=4, of=60, preview=str(preview))
    assert tick() == 0.5 and tick() == 0.5 and shown == [str(preview)]
    rr._status(output, phase='done', samples=60, of=60, preview=output)
    Path(output).write_bytes(b'png')
    assert tick() is None and shown == [str(preview), output]
