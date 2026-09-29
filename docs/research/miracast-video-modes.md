# Miracast 视频模式：真实能力、精确选择与验收

2026-09-29，执行端现场核验为 mibook / x86_64，默认路由 192.168.5.1，系统代理 none。实机为 ADB 5038 的 USB G100 `ZY32M9MRVP`，Android 16 / `W1VT36H.1-51-8`，SELinux Enforcing；接收端为 UGREEN。没有操作同时在线的 G100 S。本轮针对运行中的系统升级，不是整包清数据验收。

## 设计边界

用户要求分辨率和帧率可切换，且不能按当前手机或接收端写死。公共层负责模式标识 `WIDTHxHEIGHT@FPS`、能力交集、等待/取消、按接收端保存用户选择、读回验证与失败恢复。协议位表描述标准，不是某个设备的能力名单。

现有实现保留 Android WFD / Wi-Fi P2P / 厂商编码链路。Qualcomm 会话控制及 XML 配置放在独立后端类，运行时检查安装的接口、枚举、模式校验函数、厂商配置和 MediaCodec；没有加入机型、SoC、固件号、UGREEN 名称或地址分支。其他实现没有相应接口时明确报告不可调整；可选配置适配失败不阻断原生自动投屏，精确模式仍必须经读回核验，不能声称所有手机已支持。新增后端应实现同样的模式/实际状态契约，而不是复制一份前端或强制替换所有厂商引擎。

模式候选先取以下交集：接收端本次 RTSP 回复的 codec/profile/level/位图 → 手机原厂编码上限与硬件 MediaCodec → 已安装会话接口可表达的模式。这个候选集合不能直接显示为可用列表：接口接受参数并不证明投屏后端能实际输出该模式。最终胶囊列表只保留其中当前正在协商使用、或在当前后端/接收端能力下完成切换并核对成功的模式；没有未验证/试用入口。Android Display/KScreen 的 60Hz 不能证明编码视频为 60fps。

## 上游、协议与实际接口核验

- 协议依据 Wi-Fi Alliance **Wi-Fi Display Technical Specification v2.1 (2017)**，表 71–73：[规范副本](https://tools.barco.com/kb-downloads/4814/Wi-Fi_Display_Technical_Specification_v2.pdf)。R2 VESA 位 30/31 是 2560×1440p30/p60，32/33 是 2560×1600p30/p60；不能把只列到位 28 的 R1 表或 Microsoft 扩展表混用。规范有版权，项目只实现字段解析和数值映射，没有复制规范正文。
- 对照 [AOSP WifiDisplayController](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/services/core/java/com/android/server/display/WifiDisplayController.java) 的发现、P2P、RTSP 超时和原生重试。保留 Android 控制器拥有其正在进行的连接，外层仅在状态回到 disconnected 时重新请求；不用 certification mode 延长普通用户超时。AOSP 为 Apache-2.0，项目未复制其实现。
- 核对手机安装的 WfdService APK DEX、framework display DEX 和 native 导出接口。`DisplayInfo.supportedReadyForModes` 是 Moto 合成的列表，不是从接收端读取；`setUserPreferredDisplayMode` 在当前 WifiDisplayDevice 没有实现，不能承担 WFD 协商。
- `ISessionManagerService.getCommonResolution()` 在当前 R2 会话返回空列表，不能把它解释为接收端不支持任何模式。旧 `setResolution` 返回 0 但没有改变实际协商，不能把返回码作为成功证据。
- 可用接口为已有 `getManagedSession()` 的 `IWfdSession.setCodecResolution(codec, profile, level, family, bitmap)`。通过 `peekService` 取得已绑定的服务，使用安装 APK 自带的 AIDL 类和具名枚举；不猜 Binder transaction 编号、不复制厂商类，不调用会创建/替换会话的 `getWiFiDisplaySession()`。
- 当前 native AIDL 存在 64 位模式参数，但 Java wrapper 的 VESA 校验表不接受 R2 的位 30–32；native 会话 handle 没有已核实的读取入口。本轮不猜 handle、不另建会话、不修改闭源库或 SoC 判断来强行开放高分辨率。
- 原厂 XML 的 `AVFormatChange.Valid=0` 不代表所有手动切换接口失效。实际在线切换及 RTSP SET_PARAMETER / 接收端 200 OK 已纠正早期“只能重连”的判断。XML/property 控制的是 offer 上限/启用位，不能当作精确模式选择。

项目新 Java 为 MIT、Plasma QML 沿用 GPL-2.0-or-later；没有将厂商 APK、库或反编译源码纳入仓库。原始源码核验、符号和实机日志放在 `.work/experiments/g100-ugreen-negotiation-20260929/`。

## 接收端真实回复

`handshake.pcap` 的 M3 回复来自接收端，原始参数：

```
wfd2_video_formats: 40 01 10 0040 00000001ffff 0001ffffffff 000000000fff 10 0000 001f 11, 01 20 0040 00000001ffff 0001ffffffff 000000000fff 10 0000 001f 11, 01 02 0040 00000001ffff 0001ffffffff 000000000fff 10 0000 001f 11 00
```

这是接收端报告的 H.264 能力：CEA 包含 1080p60、没有 4K 位；VESA 包含 1440p30/60，最高尺寸为 2560×1600p30，不含 1600p60。三份 profile 不能解读成三种最高分辨率。以上是声明能力，不是解码器已逐项验收。

默认 M4 选择 CEA `80`，即 **1080p30**，虽然 Android/KScreen 显示刷新率为 60Hz。此前 UGREEN 记录中的“720/1080@60”来自显示框架，应只作为显示刷新率证据，不能追认为视频 60fps。

自动能力读取目前使用系统已有 tcpdump，在连接期间仅观察 RTSP TCP 7236，不采集 RTP 音视频。解析器限 1 MiB，处理 TCP 分段、重传、重叠、乱序和 RTSP Content-Length；缺段、多会话歧义、不支持的链路/IP格式均不推测能力。捕获限 150 秒，正常结束删除原始 PCAP；能力缓存绑定接收端、本次 display、boot ID 和时间。缺 tcpdump、捕获失败或从 Android 设置直接建立而没有握手记录时，能力为 unknown，提示重新连接，不从内置文件冒充接收端声明。目前仅实现 IPv4/标准 RTSP 端口；其他传输需扩展观察适配器。

## 共享控制流程

- **唯一交互入口是投屏胶囊展开面板的“分辨率与帧率…”**，使用 `rungic-cast modes`、`resolution ADDRESS/MODE`。Plasma “投屏”设备面板负责选择、连接和断开，不重复放置模式选择。Linux 命令保留统一控制接口，经平台桥调用 root 工具；前端不自行计算能力或写入厂商参数。
- 普通连接默认预算 120 秒；桥为 180 秒，模式切换含回退预算 330 秒，Linux socket 为 350 秒。状态报告实际等待阶段、经过时间和尝试次数，取消/新请求会终止旧请求。原生仍在 connecting 时不每五秒打断它。
- 同尺寸帧率优先在线改；当前会话 ABI 改变编码尺寸时不会同步改变 Android display，因此尺寸变化通过断开/重新协商建立正确大小的外屏。不是只修改 KScreen 分辨率或缩放。
- XML 从解除本组件 bind 后读取的原厂文件重新生成，不用上次 720p 的 override 再计算 1080p；挂载所有权核验、锁和失败恢复沿用共享配置机制。离线恢复默认 offer，用户的接收端偏好单独保留。
- 只有 native 协商读回匹配、Android display 尺寸一致、连接保持稳定才报告 `mode_applied`。失败恢复原偏好和可用模式，返回 `mode-not-applied`/`restored`；不把“请求已发出”冒充“已生效”。
- `resolution.actual` / `video_width` / `video_height` / `video_fps` 是视频读回；`display_refresh_rate` 单列。KScreen 仍可显示 60Hz，与 30fps 视频并不矛盾。该读回证明协商目标，不代表动态画面的实际吞吐一直达到目标 fps。

## 实机结果

最初按 XML/属性尝试的七组结果（`matrix/`）：720p30/60、1080p30能选中；请求 1080p60、1440p30/60、1600p30 均实际落在1080p30。因此该控制路径不能作为精确模式功能，实验属性全部恢复原值。

随后用会话接口并接入尺寸核验（`online-matrix/`）：

| 请求 | 实际视频模式 | Android / KWin 尺寸 | 完成时间 |
|---|---|---|---|
| 1280×720p30 | 1280×720p30 | 1280×720 | 43.22 秒，包含首候选在线尝试后重连 |
| 1280×720p60 | 1280×720p60 | 1280×720 | 3.63 秒，在线 |
| 1920×1080p30 | 1920×1080p30 | 1920×1080 | 33.72 秒，包含首候选在线尝试后重连 |
| 1920×1080p60 | 1920×1080p60 | 1920×1080 | 3.69 秒，在线 |

最终代码跳过不能同步改变外屏尺寸的在线尝试，直接重连。上述每项保存 root 状态、Android display/window dump 和 KScreen JSON；外屏始终位于手机逻辑右边界 (360,0)，保持手机 scale=3、外屏 scale=1，没有再产生布局空隙。`online-switch.txt` 另有 1080p30→60 的真实 SET_PARAMETER 和接收端 200 OK。

一次从断开到连接花费 **72.57 秒**，120 秒预算成功等到接收端重新出现；31 秒时仍为 waiting-receiver / attempt=0。不能把接收端尚未被发现归因为用户没有进入等待页面，也不能据此宣称所有慢连接根因已解决。

部署为 APK **2.21/69**（JNI 与升级前完全一致）、root payload、Linux测试包 `rungic-cast 0.374+cast2`。包版本明确是本次未提交源码的本地测试产物，没有发布到发行仓库。备份在实验目录 `final-deploy/backup`、`previous.apk`、`ui-before.tar.gz`，另保留最初 `online-deploy/backup` 的原始载荷。回退应先断开并恢复租约，再通过共享安装器装回载荷与旧 APK/UI；不要删除尚未释放的 UI 租约。

离线协议测试覆盖 R1/R2 位表、64 位高位、隔行区分、截断、TCP 分段/乱序/重传/重叠、缺段不拼接、缺协商不推测，并用真实 PCAP复核。APK/root 编译通过、既有5项首启安装回归通过。QML lint只有原有 Qt.application.screens 类型信息警告，无新增语法错误。未验收内容包括逐个 VESA/HH 低分辨率、其他手机/接收端、长时吞吐、音频与锁屏；不能把本轮四个常用模式推广为全能力表通过。

### 部署后补验

- 控制端对1440p30/60、1600p30在执行前拒绝，维持当前会话。选项内1920×1200p30实测未被采用，29.31秒后返回 `mode-not-applied` / `restored=true`，恢复原偏好与1080p60；没有静默把1080p当作1200p。
- 取消正在连接的请求0.63秒返回 disconnected，旧命令退出143；随后30.49秒重连，自动恢复保存的1080p60。
- 通过Android实际弹窗选择1080p25成功；Linux命令经已部署APK平台桥切换1080p50、24、60，分别3.49/3.49/3.67秒完成并读回一致。均为协商/状态验收，不代表电视物理面板或视频吞吐测量。
- Android胶囊真实界面已打开并截图，显示“分辨率与帧率”与实际视频fps。早期候选还在Plasma设备面板提供入口，用户明确要求只在胶囊调整，最终测试包cast2已移除Plasma重复入口。Plasma重新加载后没有新增投屏QML运行错误。SSH socket仍为enabled/active。
- 证据：`final-test/`、`final-test.log`、`android-dialog.xml`、`android-selected-25.json`、`bridge-test.log`、`plasma-picker-ready.png`，均在前述实验目录。

### 最终载荷与资源释放

早期候选的Plasma下拉框实际点选1080p30后（此重复入口已按用户要求移除），`plasma-selected.json`读回1080p30；测试结束恢复1080p60。新取消测试在捕获已经启动后取消，3秒内确认临时PCAP与对应tcpdump子进程均已回收，再次重连和保存模式应用成功（`cleanup-test.log`）。resident observer只回收确认owner进程已退出的捕获，150秒外部超时仍是兜底。

最终root jar SHA-256：`243f65e05c032a5cbbc17b16bc5c1bd87382a496e4ea3b90500cbea1106ffdf2`，部署记录 `release-deploy/`；APK SHA-256：`d185b1ae66288ad97ac0120347199e22e63dfcf192bcb9e8af780b90e80723ec`。实验用四个WFD位图/自动模式属性已恢复原空值，生产实现不依赖这些实验属性。最终状态单独存为 `final-status.json`。

## 2026-09-29：修正“候选模式被当作可用模式”的列表问题

用户实测发现多项不能用，并明确要求列表只显示发送端与接收端真正支持的交集。初版虽然做了receiver位图、MediaCodec和会话参数检查，却直接展示了全部候选。特别是改变尺寸走XML重新协商时，XML只提供上限，不能保证精确选中VESA/HH模式；例如1920×1200p30实际回落到1080p。已测失败的模式还继续列出，是初版缺陷，不能解释为用户选错。

最终采用更严格的发送端输出证据门槛：仍先核验接收端实时声明、编码器和安装接口，然后只展示当前一致的协商模式及曾完成准确切换的模式；显式切换后连续5秒检查真实视频模式、连接和Android外屏大小，任一样不匹配均不加入列表。失败结果覆盖旧成功结果并从菜单移除。不新增“未验证模式”或“试用”菜单，也不把本次G100/UGREEN的分辨率写进生产白名单。

`ModeHistory`的结果键包括接收端地址、真实RTSP能力、手机firmware fingerprint、安装的WFD服务APK、本组件jar和原厂XML的内容摘要。任何一项变化都不沿用旧结果，每个模式的结果独立7天过期；损坏/错误identity的记录按未知处理。没有可靠发送端枚举或有效检查记录的新组合，只显示自动与当前可核对的模式，不能凭猜测补全所有模式。显式root/CLI指令仍可用于研发逐模式验证，未通过的候选不会被放进产品列表。

本轮只更新root组件，APK胶囊自动读取过滤后的`options`，保留2.21，Plasma设备面板仍无分辨率入口。载荷SHA-256 `2f5098e1565161f886a87c28aef0396a5c50322dc9712ab4cff34abb2db71062`，备份及证据 `.work/experiments/g100-cast-mode-validation-20260929/`。部署初始列表只有自动和当前1080p60，随后通过真实切换逐项生成结果，没有导入手写白名单或伪造旧测试记录。

`tools/tests/ModeHistoryDeviceTest.java`在独立测试结果文件中验证成功持久化、失败覆盖成功、逐项过期、损坏/错误identity不信任、不同接收端和能力变化隔离；不修改投屏状态。测试通过。完整输出、每次列表和请求结果保存在`verify.log`与同目录JSON，连接预算及回退机制保持。

最终实机复核：720p30/60与1080p24/25/30/50/60逐项准确协商并保持尺寸一致，菜单逐项加入成功结果；1920×1200p30再次回落，返回失败、恢复1080p60且不进入菜单。Android胶囊实际弹窗的UI树确认仅8项（自动＋上述7项），没有未验证/试用入口；`final-menu.xml/png`保存最终界面。检查记录只证明协商模式和输出尺寸，不把它夸大成长期流畅度、解码画质或物理屏幕刷新测量。
