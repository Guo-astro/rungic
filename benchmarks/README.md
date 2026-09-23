# Reviewed benchmark evidence

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
