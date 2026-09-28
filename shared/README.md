# Android / Linux shared bridges

These sources support the Plasma environment through standard Linux interfaces.
They were extracted from the retired Phosh directory; a Phosh installation is
not required. Android-side services are in `plasma/native-apk/`.

| Path | Interface and consumer |
|---|---|
| `media/camera-source.cpp` | Android Camera2 → PipeWire cameras → libcamera / Snapshot / Firefox |
| `media/media-bridge.py` | Demand-driven camera and microphone lifecycle; PulseAudio microphone source; `android_phone` sink that always plays on the phone (not the cast screen); virtual "Linux 扬声器"/"Linux 麦克风" devices for software taking part in calls ([docs/62](../docs/62-linux-virtual-audio.md)) |
| `media/codec-client.*`, `gst-rungic-codec.c`, `ffmpeg-rungic-codec.c` | Android MediaCodec IPC → GStreamer / FFmpeg / Firefox |
| `media/snapshot-moto-codec.patch` | Historical Snapshot import patch; active source is `packages/snapshot/` (patch queue) |
| `platform/network-manager.py` | Android networking → NetworkManager D-Bus interface |
| `platform/clipboard.py` | Android clipboard ↔ Wayland clipboard |
| `graphics/` | EGL/GBM/AHB diagnostic helpers |
| `android/rungic-cast/` | Root Wi-Fi Display control (scan/connect/disconnect/decor) through Android's WFD stack, run with `app_process`; `wfd-config` limits the vendor `wfdconfig.xml` video offer to the phone's hardware encoder ([docs/58](../docs/58-miracast-desktop-feasibility.md)) |
| `android/rungic-cast/rungic-cast-watch`, `android/rungic-cast-watch.sh` | Reconnects the TV when the TV side ends the session (never after a user disconnect); boot script also binds the generated `wfdconfig.xml` over the vendor one and keeps Moto's secondary-display launcher off the TV ([docs/58](../docs/58-miracast-desktop-feasibility.md) step 5) |
| `android/miracast-probe/` | Parked, unfinished experiment: a self-written Wi-Fi Display source (P2P via WifiP2pManager, RTSP M1–M16, MPEG-TS/RTP ported from AOSP 8.1 wifi-display, Apache-2.0) run as root with `app_process`; negotiates with the TCL TV but no picture yet. Not built into the APK ([docs/84](../docs/84-miracast-source.md)) |
| `android/wfd.sepolicy.rule`, `android/rungic-wfd-sepolicy.sh` | SELinux fixes for Qualcomm Wi-Fi Display (Miracast), loaded at boot from `/data/adb/service.d` ([docs/58](../docs/58-miracast-desktop-feasibility.md)) |

Runtime service definitions and Ubuntu build scripts remain in `plasma/`.
Detailed pipeline mapping: [media](../docs/48-plasma-media-pipelines.md) and
[desktop integration](../docs/40-plasma-mobile-integration.md).
