# Android / Linux shared bridges

These sources support the Plasma environment through standard Linux interfaces.
They were extracted from the retired Phosh directory; a Phosh installation is
not required. Android-side services are in `plasma/native-apk/`.

| Path | Interface and consumer |
|---|---|
| `media/camera-source.cpp` | Android Camera2 → PipeWire cameras → libcamera / Snapshot / Firefox |
| `media/media-bridge.py` | Demand-driven camera and microphone lifecycle; PulseAudio microphone source |
| `media/codec-client.*`, `gst-moto-codec.c`, `ffmpeg-moto-codec.c` | Android MediaCodec IPC → GStreamer / FFmpeg / Firefox |
| `media/snapshot-moto-codec.patch` | Historical Snapshot import patch; active source is `vendor/snapshot/` |
| `platform/network-manager.py` | Android networking → NetworkManager D-Bus interface |
| `platform/clipboard.py` | Android clipboard ↔ Wayland clipboard |
| `graphics/` | EGL/GBM/AHB diagnostic helpers |

Runtime service definitions and Ubuntu build scripts remain in `plasma/`.
Detailed pipeline mapping: [media](../docs/48-plasma-media-pipelines.md) and
[desktop integration](../docs/40-plasma-mobile-integration.md).
