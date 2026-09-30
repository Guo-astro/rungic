# SPDX-License-Identifier: MIT
"""Progressive renders the chat can watch (docs/90). In a Blender script:

    import rungic_render
    rungic_render.render('/home/me/Pictures/球.png')

Blender does not let anyone read a render while it runs (a Render Result cannot be saved or read
mid-render, docs/90), so the samples are split into batches instead: 4, 8, 16, ... up to the
scene's Cycles samples, each batch a subset of the same sample sequence (use_sample_subset). The
average of the batches so far *is* the render with that many samples, so after each batch it is
written as a preview; the last one is the finished render (measured: 6 % slower than one render).

- In the Blender window, render() saves a copy of the scene and renders it in a background
  Blender (blender -b), so the window stays responsive; it returns at once. Blender's own render
  window opens and shows each pass as it comes: on the assistant's screen, so in its floating
  window on the phone and on the TV when one is connected (docs/65), while the chat's task card
  shows the same pictures (docs/89).
- In the background (blender -b), render() runs the batches itself and returns when done.
- Every preview goes to the assistant's activity channel (rungic_cua.activity: text, image,
  progress), which the chat's task card shows as it comes (docs/89), and to
  `<output>.status.json`: {"phase": "rendering"|"done"|"error", "samples", "of", "preview", "error"}.
- Denoising: not yet. The compositor did not run on an image in the background (Blender 5.0,
  docs/90); at 64 samples the difference is small.
- Other engines (EEVEE, Workbench) render once, as before; only the status is written.
"""
import gettext
import json
import os
import subprocess
import sys
import tempfile
import time

import bpy

RUNTIME = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}', 'rungic-agent-screen')
FIRST_BATCH = 4
# The chat's task card shows these in the desktop language. The catalog ships with
# rungic-plasma-bridges (this module's package, rungic-plasma-config, is built without gettext).
_ = gettext.translation('rungic-render', localedir='/usr/share/locale', fallback=True).gettext


def schedule(total):
    """(offset, length) of each batch: 4, 8, 16, ... doubling, and the rest as the last one, which
    is never smaller than the batch before it (64 samples: 4, 8, 16, 36)."""
    batches, done, size = [], 0, FIRST_BATCH
    while done + size + size * 2 <= total:
        batches.append((done, size))
        done += size
        size *= 2
    batches.append((done, total - done))
    return batches


def _status(output, **fields):
    try:
        with open(output + '.status.json.tmp', 'w') as file:
            json.dump({'output': output, 'time': time.time(), **fields}, file, ensure_ascii=False)
        os.replace(output + '.status.json.tmp', output + '.status.json')
    except OSError:
        pass


def _report(text, image='', progress=None, state='working'):
    try:
        if '/usr/lib/rungic-cua' not in sys.path:
            sys.path.insert(0, '/usr/lib/rungic-cua')
        from rungic_cua import activity
        activity.report(text, state=state, image=image, progress=progress)
    except Exception:  # noqa: BLE001 (the preview is a courtesy; the render goes on)
        pass


def render(output, samples=None):
    """Render the current scene to `output` (PNG unless the scene says otherwise), showing its
    passes as they come. Returns the status file's path."""
    output = os.path.abspath(os.path.expanduser(output))
    os.makedirs(os.path.dirname(output), exist_ok=True)
    if bpy.app.background:
        _render_here(output, samples)
        return output + '.status.json'
    # The window stays responsive: a background Blender renders a copy of the scene.
    os.makedirs(RUNTIME, exist_ok=True)
    copy = tempfile.mktemp(prefix='render-', suffix='.blend', dir=RUNTIME)
    bpy.ops.wm.save_as_mainfile(filepath=copy, copy=True, check_existing=False)
    _status(output, phase='rendering', samples=0, of=samples or 0)
    _report(_('Blender is starting the render'), progress=0.0)
    expr = f'import rungic_render; rungic_render._render_here({output!r}, {samples!r}, cleanup={copy!r})'
    subprocess.Popen([bpy.app.binary_path, '-b', copy, '--python-expr', expr],
                     stdout=subprocess.DEVNULL, stderr=open(output + '.render.log', 'w'), start_new_session=True)
    _follow(output)
    return output + '.status.json'


def _follow(output):
    """Show the passes in Blender's render window as the background render writes them."""
    state = {'shown': None, 'image': None}

    def tick():
        try:
            with open(output + '.status.json') as file:
                status = json.load(file)
        except (OSError, ValueError):
            return 0.5
        preview = status.get('preview')
        if preview and preview != state['shown'] and os.path.exists(preview):
            try:
                _show(preview, state)
                state['shown'] = preview
            except Exception as error:  # noqa: BLE001 (the window is a courtesy)
                print('rungic_render: cannot show', preview, error, file=sys.stderr)
        return None if status.get('phase') in ('done', 'error') else 0.5

    bpy.app.timers.register(tick, first_interval=0.5, persistent=True)


def _render_window():
    """Blender's render window (one Image Editor), opened the way a render opens it."""
    manager = bpy.context.window_manager
    for window in manager.windows:
        areas = window.screen.areas
        if len(areas) == 1 and areas[0].type == 'IMAGE_EDITOR':
            return window, areas[0]
    main = manager.windows[0]
    with bpy.context.temp_override(window=main, area=main.screen.areas[0]):
        bpy.ops.render.view_show('INVOKE_DEFAULT')
    for window in manager.windows:
        areas = window.screen.areas
        if len(areas) == 1 and areas[0].type == 'IMAGE_EDITOR':
            return window, areas[0]
    return None, None


def _show(path, state):
    image = bpy.data.images.load(path, check_existing=False)
    image.name = _('Render preview')
    window, area = _render_window()
    if area is None:
        bpy.data.images.remove(image)
        return
    area.spaces.active.image = image
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.image.view_all(fit_view=True)
    old, state['image'] = state['image'], image
    if old is not None and old.name in bpy.data.images:
        bpy.data.images.remove(old)


def _render_here(output, samples=None, cleanup=None):
    scene = bpy.context.scene
    try:
        if scene.render.engine != 'CYCLES':
            _status(output, phase='rendering', samples=0, of=0)
            _report(_('Blender is rendering'))
            scene.render.filepath = output
            bpy.ops.render.render(write_still=True)
            _status(output, phase='done', samples=0, of=0, preview=output)
            _report(_('Blender render finished'), image=output, progress=1.0, state='done')
            return
        _progressive(scene, output, samples)
    except Exception as error:  # noqa: BLE001 (said in the status, then raised)
        _status(output, phase='error', error=f'{type(error).__name__}: {error}')
        _report(_('Blender render failed'), state='failed')
        raise
    finally:
        if cleanup:
            for path in (cleanup, cleanup + '1'):
                try:
                    os.remove(path)
                except OSError:
                    pass


def _progressive(scene, output, samples):
    import numpy as np
    cycles, settings = scene.cycles, scene.render.image_settings
    total = int(samples or cycles.samples)
    final_format, final_depth = settings.file_format, settings.color_depth
    cycles.samples = total
    cycles.use_denoising = False
    scene.render.use_persistent_data = True       # the scene is built once for all batches
    os.makedirs(RUNTIME, exist_ok=True)
    work = tempfile.mkdtemp(prefix='render-', dir=RUNTIME)
    stamp = f'{os.getpid()}-{int(time.time())}'
    previews, accumulated, done = [], None, 0
    for index, (offset, length) in enumerate(schedule(total)):
        cycles.use_sample_subset = True
        cycles.sample_offset = offset
        cycles.sample_subset_length = length
        settings.file_format, settings.color_depth = 'OPEN_EXR', '32'
        scene.render.filepath = os.path.join(work, f'batch{index}.exr')
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(scene.render.filepath)
        width, height = image.size
        pixels = np.empty(width * height * 4, np.float32)
        image.pixels.foreach_get(pixels)
        bpy.data.images.remove(image)
        os.remove(scene.render.filepath)
        accumulated = pixels * length if accumulated is None else accumulated + pixels * length
        done += length
        # The average so far, through the scene's view transform, as the picture it will be.
        preview = os.path.join(RUNTIME, f'render-{stamp}-{index}.jpg')
        settings.file_format = 'JPEG'
        _save(accumulated / done, width, height, preview)
        previews.append(preview)
        for old in previews[:-2]:                  # the chat may still be loading the one before
            try:
                os.remove(old)
            except OSError:
                pass
        _status(output, phase='rendering', samples=done, of=total, preview=preview)
        _report(_('Blender render · {done}/{total} samples').format(done=done, total=total), image=preview,
                progress=done / total)
    cycles.use_sample_subset = False
    settings.file_format, settings.color_depth = final_format, final_depth
    _save(accumulated / done, width, height, output)
    try:
        os.rmdir(work)
    except OSError:
        pass
    _status(output, phase='done', samples=done, of=total, preview=output)
    _report(_('Blender render finished'), image=output, progress=1.0, state='done')


def _save(pixels, width, height, path):
    image = bpy.data.images.new('rungic-render', width, height, float_buffer=True)
    image.pixels.foreach_set(pixels)
    image.save_render(path)
    bpy.data.images.remove(image)

