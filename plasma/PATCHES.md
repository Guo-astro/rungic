# 补丁与正式源码的关系

2026-09-23开始，修改后的正式源码已直接vendor进`vendor/`。KWin、KScreen、Plasma Mobile、Settings、Keyboard、Portal、libcamera、Qt Multimedia、Plasma Camera、FFmpeg和Snapshot的构建以vendor源码为准。

这里的已应用补丁和`shared/media/snapshot-moto-codec.patch`保留为首次适配的历史证据；版本及顺序见`vendor/manifest.json`。不要修改源码后再手工维护一份同内容补丁，也不要对vendor重放它们。后续变化直接提交Git，按基线提交导出diff即可。

例外：`qt-video-duration.patch`仍为独立的未验收实验，没有包含进vendor/Qt正式代码。如需继续研究，应在开发分支或独立构建副本应用，验收后再合入正式源码。

`androidgraphicsbuffer.h`和`libcamera/pipewire_frame_generator.*`是指向正式vendor文件的兼容链接；显示协议头及FFmpeg桥仍由`plasma/android-display-client.h`与`shared/media/`统一提供。
