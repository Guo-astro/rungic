# Rungic GLES / Vulkan diagnostics

These are diagnostic workloads, not a native KWin Vulkan backend. Results and
measurement limits are documented in ../../docs/51-plasma-vulkan-benchmark.md.

The target is the existing Ubuntu ARM64 container with Qt 6.10, its coherent
Mesa build, and Vulkan enabled for the ordinary desktop user. Build inside that
container after placing this directory at /opt/rungic-gpu-bench:

```sh
cd /opt/rungic-gpu-bench
c++ -O2 -std=c++17 -fPIC quick-render.cpp -o quick-render $(pkg-config --cflags --libs Qt6Quick Qt6Gui Qt6Core)
```

The Qt program reads its scene and writes measurement JSON using two positional
arguments. Only that process needs QSG_RHI_BACKEND=opengl or vulkan. It forces an
OpenGL ES 3.2 surface for the GL test. The revised program warms for four seconds,
then measures for twelve seconds with precise timers and reads physical refresh
metadata every 500 ms. See quick-render-v1.cpp in the evidence directory for the
earlier coarse-timer run.

From the workspace root, with the phone unused, awake and set to native
1080x2400, scale 3 and fixed 120 Hz:

```sh
python3 tools/compare_plasma_gpu.py .work/refs/new-gpu-run/compositor --phase compositor
python3 tools/compare_plasma_gpu.py .work/refs/new-gpu-run/quick --phase quick
```

The compositor test restarts the desktop repeatedly and operates the app drawer
and calculator. It restores GLES in its cleanup path. Do not run during normal
phone use or recording. Layout-dependent taps and process checks must still be
reviewed if the drawer changes. A failed process/layout check invalidates a run.

Offline analysis of the archived run:

```sh
python3 tools/analyze_plasma_gpu.py benchmarks/plasma-vulkan-20260923
```

The archived clock-calibration.json belongs to that host/device clock session;
do not copy its offset into another session. Without a fresh calibration the
analysis reports whole-macro timing only, which includes scripted pauses.
CPU time, client frame submission, and Android Surface presentation are distinct
measurements. None is a measurement of energy or GPU execution time.
