# Reviewed benchmark evidence

`kwin-vulkan-20260923/` holds the KWin + native Vulkan quantification (doc 56):
real-desktop stage timing and the GLES/Vulkan compositor prototype.

`zero-copy-20260924/` and `ondemand-vsync-20260924/` hold the zero-copy,
explicit-sync and on-demand vsync runs (doc 57); trace files stay in `.work/diag`
and are identified by TRACES-SHA256SUMS.

`plasma-vulkan-20260923/` contains the accepted GLES/Zink and native Qt Vulkan
runs, clock calibration, renderer information and analysis. Raw data has not
been rewritten to conceal its original collection paths or conditions.

From the workspace root:

```sh
python3 tools/analyze_plasma_gpu.py benchmarks/plasma-vulkan-20260923
```

Methods and limits: [report](../docs/51-plasma-vulkan-benchmark.md).
New exploratory runs, screenshots and recordings belong in `.work/` first.
The original REPRO-SHA256SUMS describes the pre-migration layout; it is historical
provenance. Use SHA256SUMS for the migrated evidence files.
