# Plasma 媒体共享接口与质量验收

2026-09-23，工作记录（仍在实施和验收，不等于下列能力全部完成）。范围为独立 Ubuntu Plasma 容器；保留 Phosh。

## 原则与接口映射

用户要求不再逐个 App 重造硬件通路，优先利用 Linux/桌面标准接口和 Pipeline 扩展机制；已写入 `AGENTS.md`。安装成功不等于功能验收。

| 使用方 | 公共接口 | 本机后端及缺口 |
|---|---|---|
| Snapshot、Firefox | PipeWire Camera | 现有 moto-camera-source → Android Camera2，继续复用 |
| 原版 Plasma Camera、cam、其他 libcamera 客户端 | libcamera Pipeline Handler | 新增上游 virtual pipeline 的 PipeWire 帧输入，共用已有 Camera2 后端；候选测试已列出前后摄、cam 连续30帧、原版相机前摄预览和照片保存 |
| KRecorder、Qt 播放器 | Qt Multimedia → PulseAudio | 发现共享播放缓冲协商导致周期性插零，修复位于 Qt PulseAudio 后端，不修改录音机 |
| GNOME/GStreamer 音频程序 | PulseAudio | 同一参考音频经 paplay 输出与参考 PCM 完全一致；需继续回归实际 App |
| Plasma 录屏 | KWin ScreencastingRequest → PipeWire → GStreamer | 使用已有 motoh264enc 硬件编码器，PulseAudio monitor/mic 与 audiomixer；画质和声音选择留在录屏功能层 |
| 只认识 V4L2 的程序 | V4L2 或 libcamera 的兼容层 | 本轮不把 libcamera/PipeWire 成功宣称为所有 V4L2 应用已兼容 |

## 调研与选型

- [libcamera Pipeline Handler 指南](https://docs.libcamera.org/master/guides/pipeline-handler.html)及固定版本[0.7.0源码](https://github.com/libcamera-org/libcamera/tree/v0.7.0/src/libcamera/pipeline/virtual)：virtual pipeline 已提供设备注册、请求队列、线程、DMA-BUF 分配与配置解析，可扩展帧源。采用该框架，不把 Android camera socket 代码再写入 Plasma Camera。LGPL-2.1-or-later；新增文件沿用此许可。
- libcamera 的 Android Camera HAL 支持主要是让 libcamera 对外提供 HAL，不等同于消费手机现有 Android HAL，不能直接当成反向桥接。
- [Qt Multimedia GStreamer 文档](https://doc.qt.io/qt-6/qtmultimedia-gstreamer.html)：存在自定义 QCamera/GStreamer 入口，但 Plasma Camera2.1.1实际直接调用 libcamera，因此只改 QT_MEDIA_BACKEND 不解决设备枚举。其源码GPL许可原样保留在 `.work/refs/plasma-media-20260923/upstream/`。
- [KPipeWire6.6源码](https://github.com/KDE/kpipewire/tree/Plasma/6.6)：现有 Plasma Mobile录屏未设quality/fps、不录音频；VP8路径包含硬编码CRF45。主线已有系统音/麦克风接口，但不是本机6.6库能力，且本机音频仍由PulseAudio提供；不为此混装新版桌面库。复用[GStreamer audiomixer](https://gstreamer.freedesktop.org/documentation/audiomixer/audiomixer.html)、pulsesrc、现有硬件codec插件。
- [PipeWire1.6.2 gstpipewiresrc](https://github.com/PipeWire/pipewire/blob/1.6.2/src/gst/gstpipewiresrc.c)将SPA视频变换元数据转换为image-orientation tag。消费者应使用`videoflip video-direction=auto`，不硬编码本机上下翻转。首轮H.264样本未消费此tag而倒置，失败材料保留。
- [Termux OpenSL ES sink](https://github.com/termux/termux-packages/blob/master/packages/pulseaudio/module-sles-sink.c)默认125ms块；现场候选改为48kHz/20ms。PulseAudio17的module-tunnel-sink-new没有latency_msec参数，实验加载被拒，已恢复合法参数；不能把旧tunnel文档套给new实现。
- [Qt6.10.2 PulseAudio sink源码](https://github.com/qt/qtmultimedia/blob/v6.10.2/src/multimedia/pulseaudio/qpulseaudiosink.cpp)以1024帧设置maxlength而tlength默认。本机转发链路请求块超过该上限，导致每1024有效样本插入62个零。把1024帧作为tlength目标、让maxlength按服务协商的候选已通过参考音频相关性验证，正在构建同版本公共Qt库。对照6.11.2仍有相同buffer_attr写法；不声称上游已修。

## 当前证据

材料目录：`.work/refs/plasma-media-20260923/`。用户录音、相机帧及其解码副本只作为本地排查证据，不能放进发布归档。

- 用户录音clip_0001.ogg：48kHz单声道Vorbis，2.48s，无满幅削波。仅凭此不能证明主观音质正常。
- 已知997Hz纯音经与KRecorder相同的QMediaRecorder接口录入：完整6s，SNR约40.8dB（Vorbis有损编码）；未复现输入字节错位。
- 原Qt播放6s样本，15s仍未播完；调整宿主块长后可按时结束，但仍周期性插零。直接QAudioSink播放PCM也复现，排除了文件解码与KRecorder独有界面逻辑。
- paplay参考PCM对比相关性1.0、增益1.0；Qt缓冲参数候选相关性0.9999985、增益约0.70707（单声道转双声道）。LD_PRELOAD探针仅用于证明原因，不作为最终部署方式。
- libcamera候选已列出两个设备，cam后摄30帧，常态约30fps；后摄此时对着暗处，原始帧和相机预览一致。前摄原版Plasma Camera显示实际场景，保存image_0001.jpg。首次切换短暂绿色/启动延迟仍需核验。
- 原版Plasma Camera录像可生成H.264/MP3文件，但出现非单调PTS和负duration警告，未验收通过。不能因照片正常就宣称录像正常。
- 新录屏第二个样本：720×1600 H.264、30fps，AAC48kHz双声道，约50.6s，视频/音频时长接近；尚需在消费方向tag后重新验证图像及声音来源。多路实时source停录改为并行送EOS，避免mux等待另一条仍在产生数据的分支。

## 实现入口与待验收

`plasma/libcamera/pipewire-pipeline.patch`、`virtual.yaml`；`plasma/qt-pulse-buffer.patch`；`plasma/recording/`。

仍需完成：正式打包与重启应用后生效，原版相机录像时间戳定位/修复，Snapshot回归，KRecorder实际录音回放，录屏方向/画质/系统声音/麦克风/混音/无声及重复开始停止、长按设置入口、停止后的硬件资源释放。固定分辨率仅为现有桌面720×1600和相机720×1280，不能称为原生1080p或全像素拍照。


## 18:08 补充状态（持续验收中）

- 已安装并 hold：libcamera0.7/libcamera-dev `0.7.0-1ubuntu2+moto1`，libqt6multimedia6/qt6-multimedia-dev `6.10.2-2+moto1`，Plasma Camera `2.1.1-2build1+moto1`；APT依赖检查与dpkg audit通过。打包脚本 `plasma/package-media.py`，10个deb及SHA256保存在材料目录的packages内，不含用户数据。
- Qt公共库实际构建样本已验证参考PCM相关性0.99999953；正式包不使用LD_PRELOAD。Android专用PulseAudio的48kHz/20ms配置已写入 `plasma/android-audio.pa` 及设备配置。
- libcamera接入路径是 Android Camera2 → 既有PipeWire摄像头 → libcamera virtual Pipeline Handler → libcamera客户端。原生PipeWire客户端仍直接使用PipeWire。WirePlumber的libcamera硬件发现保持禁用，避免反向重复发现/循环。仅暴露已提供的图像尺寸和自动拍摄能力，不能把框架支持的手动曝光、对焦等宣称为桥接已实现。
- Plasma Camera原应用重复提交共享QVideoFrame并改写时间戳，是应用自身缺陷。`plasma/camera-frame-timestamps.patch`为每次提交创建独立帧元数据，并使用单调时钟；不包含任何私有硬件入口。这是有源码证据的应用补丁例外。新录像video_0002.mp4已可完整取得：10.00s视频166帧，9.456s音频；仍有Qt FFmpeg对B帧按相邻PTS估算duration造成负值的警告，完整录像仍未验收。
- KWin moto4修复GLES共享内存读回方向，已安装并于18时左右重开桌面。`screen-moto4-frame.png`证实录屏方向正常；先前“只消费orientation tag即可”的判断不完整，实际也有生产者SHM像素方向问题。`plasma/build-kwin.sh`已包含新补丁。
- 长录屏screen-recording (3)于17:58:37收到正常停止请求，但保存超时，随后桌面重启。104MB临时数据保留。untrunc恢复得到250.233s/7507帧视频；音轨恢复时长不可信，不能称为完整恢复。原文件不得删除。
- 新录屏采用fragmented MP4，使异常退出时已写出的片段仍可解析。第4个诊断录屏证实视频28.4s而音轨异常扩展到1817s，EOS卡在audio0；已抓GDB线程栈。正在验证GStreamer clocksync对混音输出按公共时钟节流的方案，不能把之前9s短样本成功外推为长录屏正常。
- 18:03起用户新增开启动画/列表滑动掉帧及Moto调度白名单问题，调查见49篇；媒体剩余验收继续保留。

- 音频独立管线进一步复现：先结束PulseAudio分支、最后结束时钟化静音分支时，所有EOS与BUS EOS在约3秒测试内正常到达。录屏代码已改用此顺序，完整视频+混音回归仍待做。clocksync单独不能修复先停静音导致的EOS问题。

## 18:50状态补充（显示设置优先，媒体回归保留）

- 用户随后要求KDE显示页、刷新率档位/自动及原生分辨率，当前优先完成50篇；媒体任务未宣称完成。
- 第3次录屏已恢复约250.233秒、校正上下方向并恢复同期音轨，写入Android `Plasma/Videos/screen-recording-3-recovered.mp4`。恢复文件完整解码无错误；未以客观事件测量音画同步，原始partial保留。第7次录屏停录仍超时，其fragmented MP4可直接重封装，得到约59秒、双轨完整解码无错误的 `screen-recording-7-recovered.mp4`，原始partial也保留。
- “先audio0、后silence/video”的顺序只通过独立音频测试，未解决静止画面下完整mux阻塞。最新候选改为并发结束video及实际音频源，等其返回后最后结束clocked silence，需完整录屏验证。不能把该候选标为已修复。
- `plasma/qt-video-duration.patch`编译了共享FFmpeg插件候选，仅在 `/opt/moto-qt-duration` 私有路径运行Plasma Camera，原系统插件未替换。video_0003约12秒实录仍有负duration警告；因此单给输入AVFrame设置duration的候选未验收，不打入Qt正式包。正式Qt仍为已通过音频PCM验证的moto1。

## 多屏同时录屏（2026-09-24）

需求：点录屏后，有外屏（Miracast电视）时手机与外屏同时录制。

- **快捷设置**（`plasma/recording/main.qml`）：为每块屏幕各建一个`TaskManager.ScreencastingRequest`，手机（快捷设置所在屏）排第一。全部拿到PipeWire节点后调用`RecordUtil.startRecordingScreens`；3秒内外屏未就绪时只录已有的。
- **录制脚本**（`moto-screen-recorder NODE OUT [NODE OUT ...]`）：
  - 所有屏幕在同一GStreamer管线、同一时钟下，每屏单独编码成一个MP4。
  - 音频只编码一次，经`tee`写入每个文件。
  - 文件名：单屏不变（`screen-recording (n).mp4`）；多屏为`screen-recording (n) - 手机.mp4`与`… - 外屏.mp4`。
  - 录制中外屏断开时，该屏分支单独收尾，手机继续录，停止后两个文件都保存。
- **硬件H.264**：
  - `motoh264enc`经宿主`CodecBridge`固定使用`c2.qti.avc.encoder`，并要求`isHardwareAccelerated()`为真、非纯软件实现，否则报错，不回退到软件编码。
  - 录制时logcat确认分配了`QC2Comp … c2.qti.avc.encoder`。
- **编码能力适配**：
  - **实测限制**：
    - 1080×2400@60单路被拒（`Frame rate unsupported`），@30单路可以。
    - 1080×2400与1080p两路同时编码，第二路即使30fps也会`CodecException`。
    - 864×1920@60与1920×1080@60两路同时编码可以。
  - **单屏60fps录屏原先就已失效**：手机改为原生1080×2400渲染后，“流畅”档的单屏录屏已在协商阶段失败（`not-negotiated`），并非本次多屏改动引入。
  - **适配规则**：多屏或60fps时，每路在拿到实际尺寸后（`videoflip`输出CAPS事件）缩到长边≤1920、短边≤1088，保持比例，由`videoconvertscale`一次完成转换与缩放。单屏30fps保持原生分辨率。
- **实测**：
  - 双屏：手机864×1920@60、电视1920×1080@60，均可完整解码，内容正确。
  - 中途断开外屏：两个文件都保存。
  - 单屏60fps：864×1920，恢复可用。
- **保存位置问题（共享层）**：
  - 今天01:12 `xdg-user-dirs-update`把`~/.config/user-dirs.dirs`中的标准目录全部改成了`$HOME`，录屏、截图、下载与电视桌面文件夹因此都落到主目录。
  - 原因是`moto-plasma-shared`的bindfs在前台运行，systemd在挂载完成前就判定服务已启动，会话抢先启动，`~/Videos`等指向`Shared/…`的链接暂时失效，于是被重置。
  - 修复：
    - 服务加`ExecStartPost`等待挂载点就绪。
    - 会话启动时若共享存储已挂载，写`user-dirs.conf` `enabled=False`，并用`xdg-user-dirs-update --set`固定各目录，失败不阻止会话启动。
  - 容器重启后验证：`xdg-user-dir VIDEOS`为`~/Videos`，录屏已保存到`~/Videos`。
- **外屏录像带光标**：plasma-workspace的`ScreencastingRequest`固定以`pointer_hidden`申请流。其底层`Screencasting`类未导出（不在已安装头文件与符号中），因此录屏插件按其实现自带`ScreenStreamRequest`（`plasma/recording/screenstream.*`，直接使用KWin的`zkde_screencast_unstable_v1`），外屏以`pointer_embedded`申请，手机仍为`pointer_hidden`。实测电视录像中逐帧检测到约21×31像素的光标，并随触控板移动。

## 录屏收尾超时的原因与修复（2026-09-27，发布`20260927.7`）

现象：停止录屏后`Timed out finalizing recording`（12秒上限），只留下`.partial.mp4`；`20260926.20`起的完整验收中多次出现，录得越久越容易失败。

排查：在容器中用同一管线、屏幕源换成`videotestsrc`（1080x2400、60fps、live）复现，并在每个元件的输出pad上加EOS与buffer计数探针。
- 收尾时间随时长增长：录6秒收尾1.1秒，60秒收尾6.3–7.5秒；去掉音频支路仍为7.4秒，积压在视频支路。
- 60秒内视频源产生3582帧，第一个泄漏队列只放出34帧；`videorate`用复制帧补足，输出3190帧，编码器输出3187帧。EOS在第一个队列后停了11秒。
- 原因：缩放转换、`videorate`与硬件编码器在同一线程。60fps档（864x1920）时编码器经宿主桥接的实际吞吐约50fps，低于设定帧率；`videorate`按时间戳补帧，输出越来越落后于实时（约每分钟7秒），上游的泄漏队列因此丢掉几乎全部真实画面，停止时又必须先编完积压。音频也受影响：旧管线60秒文件的音轨比视频短1.5秒。

修复（`plasma/recording/recorder.py`）：在`videorate`与编码器之间加一个泄漏队列（4帧），编码器独立一个线程，跟不上时丢弃编码前的帧而不积压。
- 测试源60秒：全部3578帧进入转换，编码2981帧（约50fps，可变帧率），收尾0.29秒；视频59.77秒、音频59.78秒。
- 30fps档（1080x2400，不缩放）40秒：1194帧无丢帧，收尾0.2秒。
- 实机快捷设置验收连续3次通过（此前连续5次失败）；真实屏幕30秒录制平均49.4fps，文件含H.264与AAC两轨；停止后录屏进程退出，APK端`c2.qti.avc.encoder`会话关闭（1504帧输入/输出）。

剩余：60fps档实际约50fps，受硬件编码经宿主桥接的吞吐限制；多屏（手机+电视）同时录制未在这次复测（没有接电视），两路分支结构相同。

