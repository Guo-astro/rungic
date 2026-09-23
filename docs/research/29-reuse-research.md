# Phosh 适配前的现有方案调研与复用判断

> 历史研究记录：Phosh 专属实现已于2026-09-23移除。本篇保留共享硬件接口与研究结论；当前代码见 `shared/`、`native/plasma/`、`plasma/`，现行集成见 [40篇](../40-plasma-mobile-integration.md)。旧Phosh路径和已删除的原始日志不再作为可执行入口。

日期：2026-09-23。对应 [当前能力审计](28-capability-audit.md)。本轮是方案调查与源码审阅，没有安装或启用新的设备接口。以下“优先”指优先验证候选，不代表已在本机验收。

后续实施结果见 [30篇](30-feature-adaptation.md)；实际架构、选型如何随证据修正、桌面到后端的连接方式见 [31篇](31-backend-integration.md)。本文保留为实施前研究快照。

用户明确要求每项先广泛调研，再选最合适的复用方案；实现质量不好时允许重写。已记录到项目 `AGENTS.md`，后续适配持续遵循。

## 本轮取得的材料

已检查 Winland、Termux:API、Termux PulseAudio/FFmpeg、Termux:X11、Droidspaces、Winlator、libhybris、Waydroid、gst-droid/droidmedia、bluebinder、xdg-desktop-portal-wlr、IBus/Rime，以及 Phosh 和 Android 官方接口资料。

可成功取得的源文件与仓库树存于 `.work/refs/phosh-reuse-research-20260923/`，`fetches.json` 保存获取地址和结果。没有执行下载的安装脚本。部分 GitLab raw 页面不可访问，后续对应项目必须继续通过官方发布归档核验，不能将页面获取失败视为项目没有实现。

已记录仓库树版本：

- Winland：`4269ec048e83133102d00464fd4c23af44d84707`；GitHub 元数据报告最后推送 2026-09-07，未归档。
- Termux:API：`fc26ce17e3badf85d4df191af364fcf7798047f1`。
- Termux:X11：`bd1cfadd74f98b548662a48b6e1d564aa434c86e`。
- Winlator：`bae41e0c7f5f48df9dadb64b14355440126e7229`。本轮仓库树主要提供辅助模块和补丁，不能把发布 APK 的功能当作对应服务端实现已可复用。

这些值用于定位本轮材料，不表示它们都是发布版。部分 raw 文件来自当时的 main/master，保留本地内容哈希；正式采用时还需固定源码提交与构建依赖。

## 音频：已有两条很接近我们需求的实现

### 候选 A：Termux PulseAudio + Android AAudio，采用 Droidspaces 的容器连接方式

[Termux PulseAudio 包](https://github.com/termux/termux-packages/tree/master/packages/pulseaudio) 已提供 `module-aaudio-sink.c`、OpenSL ES 输出/输入后端。AAudio 模块有回调、错误处理和流重建路径，属于已经存在的音频服务端实现。

[Droidspaces 的正式文档](https://github.com/ravindu644/Droidspaces-OSS/blob/main/Documentation/Graphics-and-Audio.md) 描述了在宿主以 Termux 用户运行 PulseAudio，将 Unix socket 挂入 Linux 容器并注入 `PULSE_SERVER` 的路线。这与我们的 LXC 位于 Android 内的方向一致。其 `setup-termux.sh` 也明确选择 AAudio。

优点是 Linux 应用使用完整 PulseAudio 协议，能够复用已有混音、流音量和客户端兼容；音频本身不要求 X11。Droidspaces 的整套图形安装脚本同时安装 Termux:X11/VirGL，我们只应研究和选取音频部分，不能整段运行到当前环境。

本机已有 Termux，因此这是优先做最小验证的候选。仍需检查 Termux APK/包版本、宿主进程 UID、Android 16 音频访问、socket 权限、cookie、后台生命周期及与容器当前 PulseAudio 的关系。只有实测后才能选择“客户端直连宿主”还是“容器内服务通过 tunnel 连接宿主”。

曾有 [Android 16 音频失败 issue #27978](https://github.com/termux/termux-packages/issues/27978)。它关联的 [修复 PR #30702](https://github.com/termux/termux-packages/pull/30702) 已于 2026-07-24 合并，变更涉及显式链接 OpenSLES。不能据旧 issue 认定当前 Termux 不支持 Android 16；也不能将该修复视为所有设备、所有包版本均已验证。

### 候选 B：接通现有 Winland Oboe 音频桥

[Winland 上游](https://github.com/eirkkk/winland-Android) 已包含 `native/src/audio_oboe.rs` 和 `initAudioBridge`、录音、关闭的 JNI 接口。我们本地原生库源码也已有这一模块与 Oboe 依赖，当前定制 Java `NativeBridge` 没有声明/调用这些音频入口。

这会更贴合单一“Linux 桌面”APK 的交付体验。但源码核验发现：

- FIFO 路径硬编码为 `com.winland.server`，与我们的 `dev.moto.phosh` 不同。
- 固定 44.1kHz；需评估与设备原生采样率的匹配及延迟。
- FIFO 的阻塞打开/读取可能阻止停止标志及时生效。
- 播放按一次读取的 `n / 4` 计算帧数，没有保存不足一帧的剩余字节；还需处理音频写入返回的实际帧数。
- 当前线程和流恢复结构需进一步测试路由切换、断流、后台和重新进入。

因此可以保留 Oboe 和 PulseAudio 标准 pipe 模块，修改有问题的桥接部分；不应直接将现有代码接上就宣布稳定。README 的“zero-copy”等表述不能替代实测，代码确实存在 FIFO 到用户缓冲的读取。[Google Oboe](https://github.com/google/oboe) 是可独立复用的 Android 音频库。

**暂定顺序：先验证候选 A 的完整现成协议链路，再以单 APK 体验、延迟、后台稳定性和维护量决定是否改用 B。** 不预先决定一定自行设计 PCM 协议。

Winland GitHub 元数据的 license 字段为空，本轮根目录树也未见明确的项目级 LICENSE；依赖各有许可证。新增复制/分发范围需查明各文件授权，不能仅由“公开仓库”推断许可证。Termux:API 明确 GPLv3，Oboe 明确 Apache 2.0，xdg-desktop-portal-wlr 明确 MIT；真正纳入工程时记录对应许可与来源。

## 逐项候选与当前判断

| 项目 | 已有工作/候选 | 当前复用判断与实现前剩余研究 |
|---|---|---|
| 120Hz、动态刷新 | Winland DisplayActivity 读取 Android 当前 mode refresh；Termux:X11 LorieView 将实际刷新率传入本地显示；Android `setFrameRate` / Choreographer | 复用 Android 标准机制和已有生命周期处理。两份 UI 源码不能证明已经完成我们需要的动态 Wayland 呈现；还需逐层核对 frame callback、presentation 和嵌套 wlroots 行为 |
| 声音、音量 | Termux PulseAudio AAudio、Droidspaces 宿主 socket；Winland Oboe；Winlator ALSA 客户端模块 | 优先验证前两条，见上文。没有证据需要新写 PulseAudio 协议或整个音频栈 |
| 麦克风 | Winland Oboe 输入；Termux OpenSL ES source；Android AudioRecord | 保留输入设备与 PulseAudio 标准接口；需比较权限、音频路由、采样率、启动/停止和回声消除，不把播放成功算作录音成功 |
| 浏览器 | GNOME Web/Epiphany、Firefox，Alpine 现有包；GNOME Web 上游与 WebKitGTK 新版 | 直接使用现有浏览器；重点研究引擎版本、musl 包、Wayland GPU、网页隔离和代理。避免为新浏览器再混入另一套宿主 Mesa |
| 本地视频 | Showtime、Livi、GStreamer good/ugly/libav；mpv 作为诊断/备选 | 直接用现成播放器和插件。先核验移动布局、字幕、旋转和音画同步，再定默认应用 |
| 视频硬解 | FFmpeg 自带 MediaCodec wrapper；Termux FFmpeg 启用 JNI/MediaCodec；gst-droid + droidmedia | Android 侧解码不用从零写。现有源码依赖 Android NDK/JNI 或 Android 系统构建，不能直接把它当 Alpine 的现成插件；还需核验跨进程帧传输与 GStreamer 接口 |
| Wi-Fi 状态 | Termux:API WifiAPI 已输出 SSID、RSSI、频率、链路速率和 IP；Android ConnectivityManager/WifiInfo | 状态采集可复用或参考；Termux:API 有同签名和调用者限制，不能假设我们的 APK 可直接调用。前台/权限/Android 16 API 行为需要实测 |
| GNOME 网络页面 | Phosh 与 GNOME 的 NetworkManager 客户端；Phosh 上游有 python-dbusmock 网络测试 | 测试模板可帮助核对接口；不能把 mock 的假数据作为成品。首轮未找到针对我们这套“完整 Android 宿主 + Alpine LXC”的成熟 NetworkManager 适配器 |
| Wi-Fi 连接、热点、VPN | Android Settings/设置面板、Wi-Fi 网络请求接口；Termux:API WifiAPI | 先比较现成系统入口与直接控制 API 的覆盖范围。不能让传统 Linux NetworkManager 接管 Android 正在使用的网卡 |
| 电池、温度 | 当前 UPower 已可读；Termux:API BatteryStatus；Android 电池广播 | 优先保留现有 UPower，只补它解释不完整的 Android 充电策略，不重写已工作的电量读取 |
| 亮度 | Termux:API BrightnessAPI、Android 窗口 brightness/系统设置 | 代码已有；先选“仅桌面窗口”还是“整机”语义，再接入 Phosh 的亮度接口和自动亮度状态 |
| 设备型号、系统、时区 | openrc-settingsd、accountsservice、Android Build/设备 API | 优先配置现有 Linux 服务；宿主信息只补映射。还需逐项核对能安全执行的写操作 |
| GNOME 会话与设置生效 | 官方 Phosh 会话使用 gnome-session、gnome-settings-daemon；Alpine 相应包已装 | 优先采用上游启动及会话组件，核对 OpenRC 支持与 Android 电源边界，不随意另写所有后台服务 |
| 蓝牙 | Android Bluetooth API；libgbinder/bluebinder 经虚拟 HCI 接 BlueZ | bluebinder 是底层控制器适配，不能因为有项目就与宿主 Android 蓝牙栈并行启用。我们优先研究 Android 已有设备/路由信息与设置入口 |
| 自动旋转、位置、震动 | Termux:API Sensor/Location/Vibrate；Phosh 已有 iio-sensor-proxy、GeoClue、feedbackd 接口 | Android 数据采集有现成代码，Linux 适配遵循现有接口；竖横屏尺寸、safe area 和触摸坐标必须一起验收 |
| 中文输入 | Stevia/UIM、IBus/Rime、Winland Android IME 通道、Termux:X11 InputConnection 实践 | 暂不定案。设备其实已有 UIM 的拼音相关数据，不能只因 IBus 没中文引擎就推断所有引擎缺失；需核对 Stevia 0.57 的实际 completer 和候选框接入 |
| 双向剪贴板 | Winland DisplayActivity 的 listener、generation polling 和防回环；原生 bridge_clipboard 已存在 | 优先接回已有代码。需解决 Phoc 内层与 APK 外层两套 Wayland selection、前台权限和大文本；不新造剪贴板协议 |
| 录屏/共享桌面 | PipeWire + xdg-desktop-portal-wlr + Phoc screencopy/image-copy | 优先使用这套现成组件，已有协议基础；先验证缓冲格式和 portal 会话，避免自写录屏服务 |
| 保存凭据 | gnome-keyring、Secret Service/portal，当前已有包 | 补会话初始化与解锁流程；不另造密码存储 |
| 文件与共享目录 | Nautilus、GVfs、已有 bindfs 共享；Android 文档接口 | 继续使用当前文件与共享机制；网络盘和可移动盘按后端补，新增挂载前研究具体所有权/文件语义 |
| 内容索引 | GNOME LocalSearch；Linux Landlock | 缺少的是内核已有的 Landlock 功能，不应先关闭提取器隔离。核对本机 6.6 内核可用 ABI、GNOME 需要的 ABI 和原厂模块兼容后再决定 |
| 相机 | Android Camera2；Termux:API 拍照；gst-droid/droidmedia 相机源 | 拍照命令不是 GNOME/WebRTC 的持续摄像头。需要比较 PipeWire 相机源、GStreamer 插件和 Android 帧传输，尚未选型 |
| 图形安装/更新 | Alpine 包管理与本地 Mesa 仓库；GNOME Software/Flatpak | 先研究现有后端与自定义 Mesa 的一致性，再补图形入口；不能直接引入一个带其他 Mesa 的运行时并称兼容 |

## 看起来相近、但不能直接整体搬入的系统

[libhybris](https://github.com/libhybris/libhybris) 允许常规 Linux 程序使用 Android 驱动，README 也明确讨论 glibc/musl。它常与经过修改、裁剪的 Android HAL 环境一起使用；音频等还需要各自适配层。

[Droidian](https://docs.droidian.org/faq/) 使用 libhybris 和 Halium，[gst-droid](https://github.com/sailfishos/gst-droid) 依赖 [droidmedia](https://github.com/sailfishos/droidmedia) 将 Android 相机、解码器接入 GStreamer。这些是有价值的源码与接口参考，但当前没有证据证明可以作为插件直接装进我们保留完整 Android 16 的 LXC。正式考虑时需核对 Android 服务版本、Binder 接口、构建方式和硬件资源所有权。

[Waydroid](https://github.com/waydroid/waydroid) 的方向是 Linux 宿主运行 Android 容器，与我们相反。它的 IPC/集成思路可以借鉴，整体部署不能直接解决现有桌面的硬件接口。

[bluebinder](https://github.com/mer-hybris/bluebinder) 的目标是将 Android Binder 蓝牙转成虚拟 HCI；这与“读取 Android 已连接耳机并让 Android 继续管理”也是不同层次。

## 开始具体适配前的完成条件

每项实现前给出：候选、已有能力、当前问题、与本机的差异、准备复用的部分、必须新增/重写的部分，以及最小验证步骤。资料充分且在现有授权范围内即可继续，不增加逐项确认。

“成熟项目”不等于“本机已支持”；反过来，少量硬编码或缺失生命周期处理也不意味着必须扔掉整个项目。优先修正必要部分，把可维护性、日常使用体验和实测结果作为选择依据。

本轮形成优先候选；音频、刷新率、网络页面、中文输入、硬解等仍须在各自实施前完成对应验证。当前没有宣称任何新硬件接口已经可用。
