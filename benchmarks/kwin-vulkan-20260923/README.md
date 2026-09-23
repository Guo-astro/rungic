# KWin + native Vulkan quantification (2026-09-24)

Report: [docs/56-kwin-vulkan-quantification.md](../../docs/56-kwin-vulkan-quantification.md).

| Directory | Content |
|---|---|
| `pipeline/` | Real desktop, KWin moto7 GLES, drawer scrolling, 3 rounds (`tools/kwin_pipeline_run.py`) |
| `pipeline-plasmashell-vulkan/`, `pipeline-default-2/` | Experiment C: plasmashell Qt Quick on Vulkan, then the default GL control |
| `compbench-l3/` | Prototype, 3 layers, host-paced, GLES/Vulkan x finish/fence (`tools/compbench_run.py`) |
| `compbench-l3-unthrottled/` | Prototype, 3 layers, unthrottled, fence |
| `compbench-l1/` | Prototype, 1 layer, host-paced, fence |

Each run JSON names its perfetto trace; traces and KGSL text stay in `.work/`
(too large for Git) and are identified by `TRACES-SHA256SUMS`. `meta.json`
records device status before and after each prototype matrix. Re-analyse a
trace with `uv run --script tools/moto_trace_report.py TRACE`.
