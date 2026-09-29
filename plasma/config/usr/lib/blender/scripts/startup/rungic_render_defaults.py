# SPDX-License-Identifier: MIT
"""Rungic's render defaults for Blender (docs/90), a system startup module
(/usr/lib/blender/scripts/startup): Blender imports it and calls register() at every start,
with the GUI or in the background (-b), and with --factory-startup too.

The user's choice (2026-09-29): Blender renders on the CPU by default, with half the cores, so
the phone keeps capacity for everything else. On this phone the GPU shares the 7.3 GB of memory:
EEVEE took about 0.9 GB more for a small scene, Cycles on the CPU about 0.2 GB (docs/90).

- A new scene (the startup file, File > New) renders with Cycles on the CPU. A file that is
  opened, or a script that sets another engine, keeps its engine: this is a default.
- Every render, and every scene of a file that is loaded, uses at most half the CPU threads.
- No splash screen (it covered the assistant's work on its screen).
"""
import os

import bpy
from bpy.app.handlers import persistent

HALF = max(1, (os.cpu_count() or 2) // 2)


def cap_threads(scene):
    render = scene.render
    if render.threads_mode == 'AUTO' or render.threads > HALF:
        render.threads_mode = 'FIXED'
        render.threads = HALF


def cpu_by_default(scene):
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'


@persistent
def loaded(*_):
    new = not bpy.data.filepath
    for scene in bpy.data.scenes:
        if new:
            cpu_by_default(scene)
        cap_threads(scene)


@persistent
def rendering(scene, *_):
    cap_threads(scene)


def startup():
    # The startup file was read before this module registered: set its scenes once now.
    loaded()
    return None


def register():
    # Blender opened by the assistant (docs/90) goes straight to work: no splash over the window.
    bpy.context.preferences.view.show_splash = False
    for handlers, function in ((bpy.app.handlers.load_post, loaded), (bpy.app.handlers.load_factory_startup_post, loaded),
                               (bpy.app.handlers.render_init, rendering)):
        if function not in handlers:
            handlers.append(function)
    bpy.app.timers.register(startup, first_interval=0)


def unregister():
    for handlers, function in ((bpy.app.handlers.load_post, loaded), (bpy.app.handlers.load_factory_startup_post, loaded),
                               (bpy.app.handlers.render_init, rendering)):
        if function in handlers:
            handlers.remove(function)
