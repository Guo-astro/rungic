# Android / Linux shared bridges

These sources support the Plasma environment through standard Linux interfaces.
They were extracted from the retired Phosh directory; a Phosh installation is
not required. Android-side services are in `plasma/native-apk/`.

| Path | Interface and consumer |
|---|---|
| `media/camera-source.cpp` | Android Camera2 → PipeWire cameras → libcamera / Snapshot / Firefox |
| `media/media-bridge.py` | Demand-driven camera and microphone lifecycle; PulseAudio microphone source; `android_phone` sink that always plays on the phone (not the cast screen); virtual "Linux 扬声器"/"Linux 麦克风" devices for software taking part in calls ([docs/62](../docs/62-linux-virtual-audio.md)) |
| `media/codec-client.*`, `gst-moto-codec.c`, `ffmpeg-moto-codec.c` | Android MediaCodec IPC → GStreamer / FFmpeg / Firefox |
| `media/snapshot-moto-codec.patch` | Historical Snapshot import patch; active source is `vendor/snapshot/` |
| `platform/network-manager.py` | Android networking → NetworkManager D-Bus interface |
| `platform/clipboard.py` | Android clipboard ↔ Wayland clipboard |
| `graphics/` | EGL/GBM/AHB diagnostic helpers |
| `android/moto-cast/` | Root Wi-Fi Display control (scan/connect/disconnect/decor) through Android's WFD stack, run with `app_process` ([docs/58](../docs/58-miracast-desktop-feasibility.md)) |
| `android/moto-cast/moto-cast-watch`, `android/moto-cast-watch.sh` | Reconnects the TV when the TV side ends the session (never after a user disconnect); boot script also keeps Moto's secondary-display launcher off the TV ([docs/58](../docs/58-miracast-desktop-feasibility.md) step 5) |
| `android/wfd.sepolicy.rule`, `android/moto-wfd-sepolicy.sh` | SELinux fixes for Qualcomm Wi-Fi Display (Miracast), loaded at boot from `/data/adb/service.d` ([docs/58](../docs/58-miracast-desktop-feasibility.md)) |

Runtime service definitions and Ubuntu build scripts remain in `plasma/`.
Detailed pipeline mapping: [media](../docs/48-plasma-media-pipelines.md) and
[desktop integration](../docs/40-plasma-mobile-integration.md).
