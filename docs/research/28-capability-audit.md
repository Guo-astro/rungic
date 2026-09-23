# Phosh 日常使用能力与 Android 硬件接口审计

> 历史研究记录：Phosh 专属实现已于2026-09-23移除。本篇保留共享硬件接口与研究结论；当前代码见 `shared/`、`native/plasma/`、`plasma/`，现行集成见 [40篇](../40-plasma-mobile-integration.md)。旧Phosh路径和已删除的原始日志不再作为可执行入口。

日期：2026-09-23。设备：moto g100s / ZY32MVJS25。基线为 第 27 篇（旧Phosh专属记录已删除） 的 Phosh 0.57、GNOME 51、APK 2.2、统一 Mesa/KGSL。

本轮完成设备和源码检查、软件包安装模拟及补全方案分析。没有安装浏览器或播放器，没有修改刷新率、音频、网络配置，也没有重启桌面。已安装包仍为 645 个。原始记录保存在 `.work/refs/phosh-capabilities-20260923/`。

用户随后要求每项先调查现有实现。对应 [第 29 篇复用研究](29-reuse-research.md) 已找到 Termux/Droidspaces 宿主音频与 Winland Oboe/剪贴板实现；下面的“需要桥接”描述当前功能缺口，并不表示桥接代码都需要从零编写。

## GNOME 应用是否与 Phosh 配套

当前组合是 Phosh / Phoc 0.57.0、Stevia 0.57.0、Phosh Mobile Settings 0.57.0，加上 Alpine edge 提供的标准 GNOME 应用。文件管理器为 51.0.1，设置、计算器、终端、文本编辑器、图片和时钟为 51 系列，Papers 为 50.2。

这是符合 Phosh 技术栈的组合；Phosh 官方本来就复用 GNOME 的组件。但当前是定制的 Android LXC 会话，没有完整部署手机 Linux 发行版的硬件服务。Phosh 版本与 GNOME 应用版本也不要求数字相同。[官方组件说明](https://phosh.mobi/about/)

GNOME Settings 是 `gnome-control-center`，依赖 NetworkManager、UPower、PulseAudio/PipeWire、BlueZ、hostname1/login1 等接口。Phosh Mobile Settings 管理外壳、键盘等移动设置。安装它们并不会自动把 Android 的硬件服务转成这些接口。

## 实测清单

| 能力 | 当前证据与状态 | 补全方式与判断 |
|---|---|---|
| 基础桌面、触摸、GPU、挖孔 | 已接通；应用统一使用 Mesa，Phosh 顶栏避开挖孔 | 保持第 27 篇基线；新增功能继续使用这套图形库 |
| 120Hz 与动态刷新 | Android 提供 30/60/90/120Hz；APK 渲染循环固定上限 60；GNOME 输出刷新率为 0 | 可以开发 Android 刷新率与帧调度桥接；尚未验证 120fps 性能 |
| 播放声音 | PulseAudio 17 正在运行，但只有 `auto_null / Dummy Output` | 可以接 Linux 音频到 APK AudioTrack/AAudio；属于需要开发的公共接口 |
| 麦克风 | 只有虚拟输出的 monitor，无真实输入；APK 未声明录音权限 | 另做 AudioRecord/AAudio 输入、权限与生命周期；未接通 |
| 浏览器 | 未安装；只有 WebKitGTK 库 | 可补装并测试 Wayland、代理、网页隔离、下载、中文输入和视频；浏览器及引擎版本须一起考虑 |
| 视频播放器 | Showtime、Livi、Totem、mpv 均未安装 | 可补装 Showtime 或 Livi；还缺部分 GStreamer 插件；有声音依赖音频桥 |
| 硬件视频解码 | GPU 绘制已接通；没有 Android MediaCodec 桥，容器没有 `/dev/video*` | 需要单独开发并验证 GStreamer/FFmpeg 与 MediaCodec 的连接，不能承诺补装播放器后自动获得硬解 |
| 网络访问 | 容器能看到 `wlan0`、IP；通过指定代理访问 phosh.mobi 返回 HTTP 200 | 基本联网正常 |
| Wi-Fi 信息 | Android 能读到 SSID、频段、RSSI、链路速率；容器无 NetworkManager | 可以桥接只读数据；原生 GNOME Wi-Fi 页面还需适配它依赖的接口 |
| Wi-Fi 连接、热点、VPN | Android 正在管理，容器丢弃 NET_ADMIN / NET_RAW | 控制请求应交给 Android；优先提供 Android 设置入口，再逐项接原生控制 |
| GNOME 代理设置 | 会话 HTTP/HTTPS 环境变量正确，GNOME proxy mode 却为 `none` | 补装浏览器时统一 GNOME 与浏览器代理配置；当前 curl 成功不能代表每个图形应用已遵循代理 |
| 电量、温度、电池信息 | UPower 已读到 91%、28°C、循环次数等；Android 同时报告 91%、28°C | 基本信息已可用；充电策略与状态解释仍应与 Android 对齐 |
| 亮度、自动亮度 | sysfs 可读 276/2047；Phosh `HasBrightnessControl=false`；sysfs 为只读 | 可通过 APK 控制当前窗口亮度并回传；整机自动亮度交给 Android |
| 蓝牙 | 无 BlueZ 服务，也没有 Android 蓝牙桥 | 声音桥可使用 Android 已连接的耳机；Linux 设置中枚举、连接设备是另外的接口工作 |
| 型号、设备名、系统信息 | Linux 看到 Alpine 与虚拟屏幕 WL-1；缺 hostname1 | 可补 Linux 服务与 Android 设备元数据；界面应区分宿主和容器信息 |
| 日期、时区、休眠、电源按钮 | 缺 timedate1/login1；容器无改系统时间/重启权限；Linux 锁屏、空闲休眠已禁用 | 时间显示与时区可同步；整机锁屏、休眠、关机由 Android 负责，不能简单启动另一套电源管理 |
| GNOME 设置后台服务 | `gnome-settings-daemon`、`gnome-session` 已安装，但没有对应运行进程 | 应按功能补充会话服务与启动顺序；配置写入成功不等于硬件已执行 |
| 文件、图片、PDF、共享目录 | 已装并有前轮验证，共享文件仍可见 | 基础能力已有；网络共享、可移动盘需补 GVfs/后端，属于后续专项 |
| 文件内容搜索 | LocalSearch 已运行，但提取器因 Landlock 缺失拒绝工作；内核 `CONFIG_SECURITY_LANDLOCK` 未启用 | 文件名查找和内容索引要分别验收；完善内容索引需要内核能力评估，不能靠打开设置补齐 |
| 中文输入 | Stevia 可显示；IBus 没有中文转换引擎，但已装 UIM 含拼音相关数据；`cn+altgr-pinyin` 只是键盘布局 | 先调查 Stevia/UIM 可复用链路，再比较 IBus/Rime 与 Android IME 桥；尚未完成中文连续输入验收 |
| Android ↔ Linux 剪贴板 | Linux 内部有 Wayland data-control；当前 APK 的 `onWaylandClipboardChanged` 为空 | 双向同步可以补；以前 VNC 原型的剪贴板验收不代表 APK 2.2 已有同样能力 |
| 录屏、会议共享屏幕 | Phoc 提供 screencopy/image-copy；有 portal 主服务与 GTK 后端，但没有 PipeWire 服务和 wlr portal 后端 | Linux 桌面采集具备基础，需补组件并验证；不等于能录制整个 Android 屏幕 |
| 定位、自动旋转、相机、震动 | GeoClue/feedbackd 部分已安装；APK 固定竖屏，未接 Android 传感器/相机/震动接口 | 状态、旋转、震动可逐步桥接；相机需要独立图像传输和应用接口，工作量更大 |
| 应用商店/自动更新 | 没有完成适合定制 Mesa 的图形更新流程 | 优先维护受控的 Alpine 包清单；Flatpak 及其独立图形运行时需要另做 KGSL 兼容验证 |

## 刷新率链路：屏幕能到 120Hz，当前 Linux 画面还没有

Android `dumpsys display` 的物理模式为 1080×2400，支持 120.00001、90、60.000004、30.000002Hz。采样时 `mActiveModeId=4`，物理显示处于 30Hz；这是当时的状态，不是该设备始终只能运行 30Hz。

同一次输出中的旧/覆盖 DisplayInfo 还可能写着 120Hz，因此不能任选一个 `renderFrameRate` 字段就当作实际 Linux 帧率。

当前有三处独立问题：

1. `phosh/native-apk/src/dev/moto/phosh/MainActivity.java` 调用 `NativeBridge.setRefreshRate(60)`。Rust `compositor.rs` 按该数值限制循环周期，呈现上限因而仍受 60 限制，实际帧率可能更低。
2. 原生 `android/backend/wayland/seat.rs` 创建和更新外层 Wayland 输出时也写死 `refresh: 60000`。仅修改 Java 数字并不足以完善显示信息和调度。
3. Phoc 使用 wlroots 的嵌套 Wayland 后端。其 `output.c` 明确拒绝非 0 的 custom refresh；GNOME 实际拿到的是 `WL-1 / 720x1600@0`，0 表示未知。这个虚拟输出并不是手机的物理显示控制器。

wlroots 嵌套后端的 adaptive-sync 状态也不能当作手机硬件 VRR/ARR 的证据。设备实测 `hasArrSupport=false`，不支持 Android 定义的那套 ARR HAL 能力；仍可使用已经存在的离散刷新率模式切换。[Android ARR 文档](https://developer.android.com/develop/ui/views/animations/adaptive-refresh-rate)

建议按以下顺序实现：

1. APK 获取显示支持模式与当前模式，使用 `Surface.setFrameRate` 请求交互时的高刷新率，并监听系统实际选择结果。该设备的 `high` 分类报告为 90Hz，所以不能把 “high” 简单当成 120Hz。
2. 用 Choreographer/AChoreographer 的节奏驱动呈现和 Wayland frame callback，处理 Surface 销毁、后台暂停和返回。现在 callback 还有提交时立即回复的路径，需一并整理。
3. 将真实显示状态通过现有私有接口传给 Linux。设置可以显示“手机支持上限”“当前物理刷新率”和“桌面呈现帧率”；这些数值应分别测量。需要完整 GNOME 模式选择时，再适配 Phosh DisplayConfig 与 Android 的控制请求。
4. 交互时请求高刷新，静止时释放请求或降到合适档位；视频按内容帧率处理，并加入切换滞后。Android 的省电、温控和其他窗口仍可能覆盖请求。

`setFrameRate` 是偏好请求，不保证系统一定采用；Android 官方建议通过显示变更回调确认结果。[Frame rate API](https://developer.android.com/media/optimize/performance/frame-rate)

验收必须包含滚动/动画的呈现时间、帧丢失、静止降频、后台返回和功耗。现有两侧 `glFinish` 同步也可能影响 120fps 性能，尚未进行该性能验证。

## 声音与视频

通过 libpulse 只读查询得到：

```text
pulse_context_state: 4
sink 0 auto_null Dummy Output
source 0 auto_null.monitor Monitor of Dummy Output
```

这意味着当前默认音频会被送到空输出，monitor 也不是麦克风。没有 `/dev/snd`，`/proc/asound/cards` 能看到宿主声卡名称并不意味着容器能使用它。

建议延用 Linux 应用标准 PulseAudio 接口。复用调查发现可优先验证 Termux/Droidspaces 的宿主 PulseAudio socket 路线；另一候选是接通并修正现有 Winland Oboe 桥，让混音后的 PCM 由 APK 播放。这样播放器、浏览器和提示音可以共用一个出口；Android 继续管理扬声器、有线耳机和蓝牙耳机。仍需验收音频焦点、时间戳/缓冲、音量语义、断线重连和音画同步。[AudioTrack PCM 接口](https://developer.android.com/reference/android/media/AudioTrack)

麦克风另走反向输入链路，需要 Android 录音权限和明确的开始/停止状态。不能把播放出口做通等同于通话、回声消除也已完成。

本机 Android vendor codec 配置包含 Qualcomm AVC/H.264、HEVC/H.265、VP9 decoder。这证明 Android 有对应解码组件配置；没有做 Linux 端的硬解验证。容器既没有访问 Android MediaCodec 的接口，也没有可用视频设备直通。[MediaCodec API](https://developer.android.com/reference/android/media/MediaCodec)

第一阶段可以补播放器和软件解码，并实测 720p/1080p 常见片源的流畅度、CPU 和音画同步。硬件解码需独立连接 GStreamer/FFmpeg 与 Android MediaCodec；播放器和不同浏览器的解码后端还可能各需适配。DRM 受保护流媒体也应单独验证，不纳入普通视频可播放的承诺。

## 应用与依赖可直接补什么

本机 APK 仓库索引提供：

| 应用/组件 | 可用版本 | 说明 |
|---|---|---|
| GNOME Web / Epiphany | 50.6-r0 | 上游已发布 51.0，当前仓库落后 |
| WebKitGTK 6.0 API 库 | 2.48.1-r4 | 已装，但上游稳定版为 2.54.0，不能因其他 GNOME App 是 51 就视为浏览器引擎也最新 |
| Firefox | 154.0-r0 | 可作为另一条浏览器路线；需要实际验证触摸、Wayland、隔离和代理 |
| Showtime | 50.0-r2 | GNOME 官方视频播放器，可优先用于本地视频 |
| Livi | 0.5.0-r0 | 面向移动设备的较小播放器，可作为备选 |
| mpv | 0.41.0-r5 | 可作视频后端/诊断工具，手机桌面界面需另外考虑 |
| gst-plugins-good / ugly / libav | 1.28.5 | 当前缺少，补充常见容器格式、音频输出和解码能力 |

上游来源：[GNOME Web 51](https://apps.gnome.org/Epiphany/)、[Showtime](https://apps.gnome.org/Showtime/)、[WebKitGTK 当前稳定版](https://webkitgtk.org/)。版本以本次审计为准。

模拟安装 Epiphany、Showtime、语言包、上述 GStreamer 插件及 PulseAudio 工具成功，需要增加 27 个包，APK 安装占用从约 996.5MiB 变为 1029.9MiB，增量约 33.4MiB。不含缓存、用户数据，也不包含更新 WebKit 到 2.54 的成本。此模拟没有替换定制 Mesa。

浏览器正式交付应选择持续更新的引擎：要坚持最新 GNOME Web，应一起评估 Epiphany 51 / WebKitGTK 2.54 的构建与兼容；若先用仓库 Firefox，也要先完成上述实机验证。不能只根据窗口能启动就宣布浏览器可日用。

## 网络和设置如何补全

容器共享 Android 网络 namespace。实测 `wlan0` 的 IPv4 为 `192.168.5.60/24`，Android 报告 5GHz Wi-Fi、约 -38dBm、433Mbps 协商链路速率。链路速率不是实际下载速度。详细 SSID 等信息保留在本地诊断记录。

Linux 的主路由表没有普通 Linux 常见的默认路由不代表断网；Android 使用策略路由。当前通过 `http://192.168.5.45:6152` 访问 HTTPS 成功。会话的 `http_proxy` / `https_proxy` / `ALL_PROXY` 均正确，但 GNOME 的代理设置为空，需在浏览器部署时统一。

要在 Linux 显示网络状态，可以让 APK 使用 Android 网络 API 回传连接类型、地址、DNS、SSID、RSSI 和速率。SSID 等字段受 Android 权限约束；现有 root 诊断读到数据不代表普通 APK 已拥有读取权限。

如果要求现有 GNOME Wi-Fi 页面完整工作，还须实现它所期望的 NetworkManager 对象和信号，涉及 Device、Wireless、AccessPoint、ActiveConnection、IP 配置以及设置对象，不能只放一个 JSON 文件。[NetworkManager D-Bus 接口](https://www.networkmanager.dev/docs/api/latest/spec.html)

建议先扩展 Phosh Mobile Settings 中的设备状态页和 Android 设置入口，以较小维护成本补齐可读信息；再针对需要保留的 GNOME 标准面板做适配。连接、热点、VPN 仍由 Android 执行，避免两个网络管理器同时配置同一张网卡。

设备名/系统页可补 OpenRC 的 hostname1/localed 等服务与宿主元数据；已经安装的 `openrc-settingsd` 目前没有运行。时间、电源和设备管理的写操作需要另外定义边界，不能把容器启动的服务直接当作手机管理器。

## 建议实施顺序与验收

1. **可见、可用的基础补齐**：统一桌面代理；部署并验收浏览器、播放器和解码插件；完善会话服务；将主题、壁纸、收藏等启动脚本中的强制设置改成首次初始化，避免用户设置重启后丢失。
2. **声音出口**：完成 PulseAudio → APK → Android 音频，验证本地视频、网页视频、系统提示音和耳机切换；接着补录音。
3. **显示与硬件状态**：120Hz 请求、实际帧调度和静止降频；网络状态、亮度、设备型号、充电状态桥接；设置里清楚标记可控与只读项目。
4. **输入和桌面集成**：中文输入、双向剪贴板、旋转、录屏 portal、保存凭据的 keyring；逐项验证，不以包已安装代替功能验收。
5. **较重的硬件工程**：视频硬解、相机、完整蓝牙控制和内容索引所需 Landlock 内核能力。

将 Android 能力集中到现有 APK 的一套私有接口，Linux 一侧提供应用常用的标准出口。这样以后安装普通 GNOME 应用，声音、显示和网络适配可以复用，减少逐个应用配置。该路线沿用 Android 全局 SELinux Enforcing；目前识别到的主要缺口是服务和协议尚未实现。
