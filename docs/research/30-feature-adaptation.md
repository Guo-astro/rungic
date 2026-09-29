# Phosh 功能逐项适配记录

2026-09-29 MacBook无外部网络直连桌面评估：G100只读查询确认支持monitor声明，但在用无线模块的monitor发送回调为空，原版filin不能直接通过内置网卡实现AWDL双向直连。本地专用热点可作为无互联网基线，尚未做Mac互通验收。来源、精确固件与二进制证据见[直连研究](mac-offline-desktop-link.md)。

> 历史研究记录：Phosh 专属实现已于2026-09-23移除。本篇保留共享硬件接口与研究结论；当前代码见 `shared/`、`native/plasma/`、`plasma/`，现行集成见 [40篇](../40-plasma-mobile-integration.md)。旧Phosh路径和已删除的原始日志不再作为可执行入口。

更新：2026-09-23。设备 `ZY32MVJS25` / moto g100s，Android 16。本文记录**已部署的第一批功能和实际验收边界**。第 [28 篇](28-capability-audit.md) 是实施前审计，第 [29 篇](29-reuse-research.md) 是首轮选型；它们的旧状态不代表当前状态。

桌面和后端怎样连接、研究中如何定位问题与选择方案、以后如何继续开发，见 [31：架构与连接方法](31-backend-integration.md)。本文侧重功能状态与验收，31篇侧重接口和维护。

当前：Phosh/Phoc/Stevia **0.57.0**，GNOME 应用主要 **51**，Linux 桌面 APK **2.6 / versionCode 9**，Alpine edge，统一 Mesa **26.3.0_git20260824-r100**。本轮新增服务仍保留 Android 全局 **SELinux Enforcing**；LXC/Magisk 与 Docker 原有独立域策略未扩展。

## 手机上的使用入口

- 打开 **Linux 桌面**，应用列表中已有 Firefox、视频播放器、Android 设备、密码和密钥。
- **Firefox** 已有中文界面与手机布局，遵循系统代理 `http://192.168.5.45:6152`。
- **视频播放器（Showtime）** 是默认 MP4 应用；Light Video/Livi 为另一播放器。
- **相机**支持前后摄、拍照和有声录像，**录音机**可录制麦克风；Firefox网站可正常申请摄像头/麦克风。照片和视频保存在安卓 `Linux/Pictures/Camera`、`Linux/Videos/Camera`。录像先停止保存再切回安卓，详见[33篇](33-capture-integration.md)。
- **Android 设备** 显示联网、IP/DNS、Wi-Fi 链路、电池和刷新率；提供网络、蓝牙、声音、日期、定位系统入口，设置横屏/竖屏/跟随 Android，以及恢复亮度跟随 Android。
- **Phosh 下拉面板的亮度滑条**控制当前桌面窗口。恢复自动跟随在 Android 设备页操作，不会改整机自动亮度开关。
- 屏幕键盘右上角 **中/英** 切换 UIM 拼音模式；输入拼音后点击候选上屏。Android 返回键先收起键盘；没有键盘时才显示桌面 APK 菜单。
- 普通纯文本通过独立宿主后端自动同步 Android 与 Linux 剪贴板（G100 已验前台/后台）；已标记的敏感内容不自动跨系统同步。图片/文件剪贴板不在此范围。
- 浏览器请求共享屏幕时，先经过浏览器确认，再由 Linux 的确认框选择“共享屏幕”。共享范围是 Linux 桌面。
- **密码和密钥**使用 GNOME Keyring。持久钥匙串的密码由用户首次创建时在手机上设置；没有预置固定密码，也没有自动解锁 Android 锁屏的逻辑。
- **设置 → 系统管理 → 系统服务**（2026-09-28）列出容器默认屏蔽的服务及其原因和风险，并可以重新允许；**SSH 远程登录**默认关闭，开启后用账户密码或公钥登录手机的 IP（端口 22，容器与 Android 共用网络，没有独立 IP）。详见 [83 篇](../83-service-policy.md)。

## 完成情况与验收

2026-09-28 G100 CI 新镜像的首次账户路径：已修复容器入口依赖的宿主音频目录未创建问题。用户提交后实测账户 configured=true，桌面和应用抽屉实际显示、注入滑动有效，LXC/systemd 正常运行，系统级与用户级服务无失败。当前为手工修订后安装的基础验收，硬件回归和完整清数据首启仍待完成，不能沿用本篇 G100S 历史结果；本轮记录见 [79 篇](../79-g100-ci-execution.md)。

| 项目 | 已实现和已验证 | 边界 |
|---|---|---|
| 声音输出 | 容器 PulseAudio tunnel → 私有 Unix socket → Termux PulseAudio/AAudio；真实输出、重启/重连；2.5增加专用服务失去响应后的自动恢复 | 电话焦点、耳机切换、长时间音画同步未完成；恢复期间声音会中断 |
| 麦克风 | APK AudioRecord → 标准PulseAudio source，默认AndroidMicrophone；录音机和视频音轨有真实非零样本 | 48kHz单声道，桌面可见且存在消费者才采集；蓝牙/电话焦点未验 |
| 拍照/录像 | Camera2 → libyuv → PipeWire → GNOME Camera51；前后摄、JPEG、有声H.264/AAC及Firefox VP8/Opus实测 | 720p/目标30fps；H.264已接硬编，音频软件编码；切回安卓立即断开采集，中断MP4可能无效 |
| 浏览器 | Firefox 154.0-r0，移动布局，官方中文语言包，HTTPS、下载、WebGL2、网页视频、Linux 屏幕共享 | 不是所有网站/DRM 视频兼容承诺 |
| 视频 | Showtime 50.0-r2、Livi 0.5.0-r0、GStreamer 1.28.5 插件；本地720p与浏览器1080p测试 | H.264/HEVC/VP9已接高通硬解，见35篇；其他格式可走软件，GPU绘制与硬解分别验收 |
| 动态显示 | Android Choreographer 驱动，触摸请求120Hz，持续画面请求至少60Hz，静止释放 | 实测交互约89帧/秒；系统90Hz渲染/温控限制仍生效，未证明持续120fps |
| 旋转/挖孔 | 横竖屏与触摸坐标同步、横屏侧边挖孔留空、竖屏顶栏恢复 | 已连续两轮切换；不是完整 iio-sensor-proxy 传感器服务 |
| 亮度 | Phosh 自带滑条接 Android 窗口，拖动实测到53%，恢复跟随成功 | 跟随时显示Android用户设定，不是实时自动亮度/nits；整机由Android管理 |
| 网络/硬件信息 | Android设备页；原生GNOME网络/Wi-Fi、Phosh图标与开关已接Android真实状态，SSID/IP/DNS/网关/链路详情与断线重连通过 | Linux只列当前Wi-Fi；新连接/密码/热点/VPN由Android管理，见[32篇](32-network-integration.md) |
| 中文输入 | Stevia UIM 中文、候选与连续“你好你好”输入；完整重启后再次“你好”通过 | 尚未覆盖所有应用和输入法操作；UIM空格是候选切换，点击候选提交 |
| 双向剪贴板 | 中文、emoji、换行、清空、重启恢复；敏感标记跳过实测 | 纯文本、有大小限制；G100 后台已验，无法识别未标记的密码 |
| 屏幕共享 | PipeWire + portal-wlr，公开ScreenCast接口和Firefox getDisplayMedia实测 | SHM采集、最高30fps；未验证长会议负载和远程会议服务 |
| 文件/文档 | 容器私有FUSE、文档portal、共享目录；GVfs WebDAV中文读写通过 | SMB/NFS后端已装，未连接用户真实网络盘；不接管Android可移动设备 |
| 凭据 | Seahorse、Secret Service临时条目存取删除通过 | 持久钥匙串需用户自行设置/解锁；尚未测试长期真实凭据 |
| 设置保留 | 完整容器停止/启动后主题、壁纸、输入源保持 | 旧锁屏/空闲容器策略仍由启动脚本设置 |

## 选型、修复和实现细节

### 1. 声音

优先复用已研究的 Termux/Droidspaces 路线。Termux PulseAudio **17.0-4** 在 Termux UID 下运行独立实例，容器默认 sink 为 `android`。宿主 runtime/state 私有；256字节独立cookie，Linux cookie为1000:1000/0600。socket目录只读挂入LXC，没有TCP音频服务。48kHz双声道，空闲3秒释放AAudio，tunnel每2秒重连。

`phosh/android-audio`、`android-audio.pa`、`android-tunnel.pa`，以及 manager/enter/LXC config 已部署。APK执行root控制器使用Magisk `--mount-master`，解决应用数据隔离namespace看不到Termux目录的问题。不会停止用户其他PulseAudio实例。

AudioFlinger记录证明有实际Android输出轨道，采样时无underrun；它不能证明人的听感、耳机路由或A/V同步。Termux APK缺少RECORD_AUDIO声明，不能把其录音模块直接加载后称麦克风已接通。

来源：[Termux PulseAudio](https://github.com/termux/termux-packages/tree/master/packages/pulseaudio)、[Droidspaces音频文档](https://github.com/ravindu644/Droidspaces-OSS/blob/main/Documentation/Graphics-and-Audio.md)、[PulseAudio模块](https://wiki.freedesktop.org/www/Software/PulseAudio/Documentation/User/Modules/)。源码与版本见29篇及refs。

### 2. 浏览器和视频

使用 postmarketOS **mobile-config-firefox 5.4.1-r0** 的移动CSS/autoconfig，保留其隐私默认设置，移除额外搜索重写和扩展自动安装。包内 `general.config.sandbox_enabled=false` 属于特权autoconfig加载机制，不是网页进程沙箱开关。

Alpine `firefox-intl` 当前为空包。下载Mozilla官方154.0中文XPI，核验版本范围与签名文件，通过标准 `Extensions.Install` policy加载；UI及诊断均显示zh-CN。

Firefox因KGSL没有DRM render节点误判软件显卡，初始为WebRender(Software)。`firefox-policies.json` 将 `gfx.webrender.all` 设为可由用户更改的默认true，实测切换到WebRender，诊断识别FD710，WebGL1/2可用。没有禁用content/RDD sandbox：内容沙箱级别6，进程 `NoNewPrivs=1 / Seccomp=2 / Seccomp_filters=2`。

独立测试profile的结果：

- WebGL2绘制并读取像素 `[26,204,77,255]`，GL错误0。
- 本地1080p30 H.264网页视频8秒，242帧中4帧丢弃；为短测试，不推广为长期性能结论。较早冷启动测试丢帧更多，不能把改善全部归因于单一修改。
- 浏览器下载自有中文文本文件，大小/内容正确；HTTPS Phosh官网已打开。
- 720p/1080p各360帧的纯软件解码基准：0.609秒/1.047秒。分别591.2/343.9帧每秒是**无显示吞吐**，不是手机播放帧率。

测试profile与用户profile隔离，Marionette和ADB调试转发已关闭。普通用户运行，不把root浏览器作为兼容方案。

来源：[Mozilla policies](https://firefox-admin-docs.mozilla.org/reference/policies/)、[mobile-config-firefox](https://docs.postmarketos.org/mobile-config-firefox/main/index.html)、[Mozilla中文语言包](https://archive.mozilla.org/pub/firefox/releases/154.0/linux-aarch64/xpi/zh-CN.xpi)、[Showtime](https://apps.gnome.org/Showtime/)。

### 3. 显示、旋转与亮度

Java `DisplayPacer` 的Choreographer回调驱动Rust frame clock，替换固定60Hz sleep。APK1.22起静止桌面不再每个vsync唤醒：原生层空闲400ms后停止请求Choreographer回调，有Wayland请求、Android输入或SurfaceFlinger回调时立即恢复（见57篇）。Wayland frame callback使用单调vsync时间，移除commit立即返回零时间戳的路径；成功EGL提交单独计数。

触摸请求最高120Hz并保持2秒；持续提交≥8fps时请求至少60Hz，2.5秒迟滞后释放。静止实测物理30Hz、桌面约2fps空闲提交。`android-refresh.ini`分别记录系统报告Hz、支持范围、请求值与实际提交fps。Android省电和温控仍有最终决定权。

横屏短边保持720，根据可用区域调整长边与触摸坐标。修复Phosh safe-area计算使用“曾出现的最大mode宽度”的错误，改用当前mode；实测横屏顶栏32逻辑像素，回竖屏恢复43，连续两轮通过。

0.57的亮度使用 `PhoshBacklight`，旧GSD Power.Screen桥不适用。新增小型 `backlight-android.c` 后端复用上游滑条/异步合并逻辑，socket I/O在GTask线程内，2秒超时、4KB响应上限；只有宿主socket存在才选用。拖动实测Android `windowBrightness=0.53`，恢复-1后Phosh同步更新。APK不申请整机WRITE_SETTINGS，不写宿主sysfs。

来源：[Android帧率API](https://developer.android.com/media/optimize/performance/frame-rate)、[Choreographer](https://developer.android.com/reference/android/view/Choreographer)、[窗口亮度](https://developer.android.com/reference/android/view/WindowManager.LayoutParams#screenBrightness)、Phosh0.57官方 `backlight*.c / brightness-manager.c / monitor.c`。补充比较与许可证见 `.work/refs/phosh-features-20260923/brightness-keyring-research.md`。

### 4. Android设备页和输入

`PlatformBridge.java`是APK私有filesystem Unix socket；验证peer UID 0/1000，固定操作白名单，限制消息大小与超时。Android设备页使用GTK4/libadwaita。网络只读取实际API值，不创建假NetworkManager设备。蓝牙/声音/日期/定位入口已实现；网络入口和返回已实机操作，其余不能当作硬件控制已逐项验收。

`openrc-settingsd --read-only`提供容器hostname1/timedate1，时区Asia/Shanghai。原生login1、完整GNOME SessionManager及polkit登录会话仍缺失，日志中相关warning保留在待办范围。

Stevia复用已安装UIM，输入源为 `[('ibus','uim:cn'),('xkb','us')]`，此处不是另起IBus服务。GTK4在preedit布局变化时重复发送CHANGE_CAUSE_OTHER，但周围文本未变；旧Stevia每次重置completer导致拼音被取消。补丁仅在周围文字/选区实际变化时响应该重置，保留激活重置语义。自编Stevia保留上游hunspell/presage/UIM能力，prefix=/usr，避免词典路径错用/usr/local。

双向剪贴板复用wl-clipboard与ClipboardManager，前台才读写，最多65536字符/262144 UTF-8字节，不存历史、不记录正文。Android `EXTRA_IS_SENSITIVE` 与Wayland `CLIPBOARD_STATE=sensitive`均不自动同步；Linux敏感内容保持本地的实测通过。

来源：[Stevia](https://gitlab.gnome.org/World/Phosh/stevia)、GTK4 `gtkimcontextwayland.c`（本地保存）、[wl-clipboard](https://github.com/bugaevc/wl-clipboard)、[Android剪贴板](https://developer.android.com/develop/ui/views/touch-and-input/copy-paste)。Stevia补丁遵循GPL-3.0-or-later。

### 5. Portal、文件与凭据

PipeWire **1.6.8-r5**、WirePlumber **0.5.17**、portal-wlr **0.8.4**；Alpine的pulseaudio-wireplumber配置关闭竞争的音频/蓝牙硬件监控。PipeWire用于图像流，本地应用音频继续PulseAudio。session-apps补齐D-Bus激活环境，避免portal选错桌面后端。

portal-wlr在无DRM/GBM的KGSL嵌套输出中向NULL gbm调用格式查询而崩溃，GDB回溯已确认。`portal-wlr-no-gbm.patch`在无gbm时跳过DMABUF协商，使用其已有SHM路径。桌面本身继续GPU渲染。共享确认框使用gtk4-layer-shell覆盖层，解决被Firefox遮挡的问题，仍需明确点击同意。

公开ScreenCast Create/Select/Start/OpenPipeWireRemote→GStreamer图像采集通过；Firefox getDisplayMedia得到live 720×1600/30fps流，并能绘制到canvas读取像素。完整容器重启后的采集再验通过，测试结束关闭session与全部tracks。

文档portal原来访问root-only宿主/dev/fuse失败；改为容器私有10:229节点0666，宿主/dev/fuse保持0600。完整重启后GetMountPoint返回 `/run/user/1000/doc`。GVfs WebDAV独立回环测试的中文文件名、读写和删除通过；测试服务、反向转发和挂载已清理。

Seahorse **47.0.1-r2**为Alpine当前包，手机窄屏UI可打开；GNOME Secret Service临时session条目存取、删除通过。没有为了“自动登录”创建空密码持久钥匙串。

来源：[portal-wlr](https://github.com/emersion/xdg-desktop-portal-wlr)、[ScreenCast协议](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html)、[gtk4-layer-shell Python示例](https://github.com/wmww/gtk4-layer-shell/blob/main/examples/simple-example.py)、[GNOME钥匙串创建](https://help.gnome.org/seahorse/keyring-create.html)。portal-wlr补丁遵循MIT；各复用库/应用保留上游许可证。

## 回归和当前未完成项

完整Phosh容器停止/启动已验证：默认Android声音出口、PipeWire/WirePlumber单实例、Stevia中文输入、剪贴板、文档portal、共享屏幕自动恢复；主题prefer-dark与用户壁纸不被重置。此次不是整机冷启动/断网首启验收。

Docker的 `moto-nginx` 仍healthy，原Alpine LXC仍RUNNING；不停止这两个服务。六个定制Mesa包保持内容哈希锁定。编译依赖已清理，当前 **701包 / APK报告1300.9MiB**；这不是总文件系统占用或RAM占用。

后续仍需单独实施和验收：

1. 麦克风授权/指示/输入流已在第33篇部署；音频焦点、耳机和蓝牙路由、长期A/V同步仍未完成。
2. 原生网络已在第32篇接入并实测；2026-09-27起Wi‑Fi操作、蜂窝（ModemManager）、蓝牙（BlueZ）与息屏时间也接入标准服务（docs/73第四阶段）；完整会话/polkit、SIM PIN/APN与VPN协议管理仍未完成。
3. MediaCodec已接入（35篇）；通话实时性能、长时间与后台摄像头录制、GeoClue定位/传感器服务、feedbackd震动后端。
4. Landlock内核能力与LocalSearch内容索引；不会通过关闭提取器隔离掩盖缺失。
5. 固定Mesa前提下的图形安装/更新；完整SMB/NFS、用户持久凭据及长会议负载。
6. 真实持续120fps和功耗测量；不能把120Hz请求等同120fps。

2026-09-23修复前复查：GNOME“设置→网络”明确显示 `NetworkManager not running`；system D-Bus无对应服务。同时Android Wi-Fi已连接且验证联网，容器经指定代理访问HTTPS返回200。该错误来自原生网络接口尚未适配，独立“Android设备”页可用不能算这一项已完成。见 复查证据（历史材料已移除）。

## 本地材料与复现

- 源码/配置：`phosh/`，JNI入口源在 `native/phosh/src/`；Rust本轮差异已保存 `phosh/native-vsync.patch`。
- 原生APK：`.work/refs/phosh-wayland-native-20260922/Linux-Desktop-2.3.apk`。`phosh/build-native-core.sh` 与 `phosh/build-native-apk.sh`可在现有构建环境重建；前者沿用已锁定的Winland/Smithay基线，不能仅应用vsync补丁替代历史GPU补丁。
- Linux差异：`stevia-compose.patch`、`portal-wlr-no-gbm.patch`、`phosh-rotation-safe-area.patch`、`phosh-android-brightness.patch`；后两项叠加在27篇Phosh0.57定制基线上。
- `.work/refs/phosh-features-20260923/`保存源归档、编译参数、测试脚本、实测JSON/截图、部署文件归档和SHA256。具体索引见同目录 `README.md`。
- `feature-binaries.tar.gz`是定制Linux文件与配置快照，不是完整rootfs，也不是适用于任意手机的独立安装包；不要直接覆盖未知版本环境。
- 旧manager/session/enter/world/config与旧Phosh二进制保留；升级前完整rootfs仍在runtime `/var/lib/lxc/phosh/rootfs-pre-0.57`。
- **本轮没有更新Fastboot ROM或原有一键完整重装包。**

2026-09-23后续实施：已完成原生NetworkManager子集桥接与GNOME51界面适配、真实Wi-Fi开关/重连/失联恢复验证，当前状态见[32：网络接入](32-network-integration.md)。APK2.4保留2.3的其他功能。

2026-09-23采集实施：APK2.5与Linux标准麦克风、前后摄像头、相机/录音机/网页采集已部署；修复共享目录bindfs与当前FUSE ABI不匹配，完整容器重启再验通过。采集原理、普通权限、输出watchdog、实测文件与未完成边界见[33：采集接入](33-capture-integration.md)。清理临时构建依赖后为712包/1344.9MiB；上面的701包是第一批适配结束时的历史数值。

2026-09-23硬件编解码核验：Android端强制高通AVC/HEVC组件，各完成1080p90帧硬编→硬解及像素抽样校验，保持Enforcing；另找到可枚举NV12的原厂V4L2节点。**当时Linux播放器、相机和Firefox尚未接入；现已由35篇部署更新**，具体证据、Sailfish近期Android16支持及后续候选见[34篇](34-hardware-codec-audit.md)。

2026-09-23软件接入：APK2.6增加私有MediaCodec桥，GStreamer、Snapshot51、Firefox154接高通H.264/HEVC/VP9能力；WebCodecs H.264 60帧编码/解码和WebRTC回环已验，通话短测仍有丢帧，MediaRecorder WebM保持软件编码。软件回退、沙箱、源码与边界见[35篇](35-hardware-codec-integration.md)。同轮恢复底部15逻辑像素原生高度、移除早期手势留白和白底；保留Android全屏与顶部挖孔。禁用无密码的Phosh独立锁屏，整机仍由Android锁屏；Firefox默认使用移动UA。

2026-09-23桌面启动补修：发现Firefox发行版desktop三个Exec直接调用原程序，绕过编解码包装入口；之前只测命令行漏检了此路径。新增`phosh/install-firefox-launcher.py`生成同ID用户desktop覆盖，普通启动/新窗口/隐私窗口均走包装脚本。恢复步骤、原始问题证据与桌面启动复测见修复记录（历史材料已移除）。

2026-09-23输入补修：35篇自动化测试留下日常profile测试焦点设置，触发Firefox154已知IME空指针。清理后真实屏幕键盘英文、中文候选、退出后重开输入网址均通过；当前codec测试脚本增加独立profile前置检查。根因、上游补丁状态与证据见[36篇](../36-firefox-input-fix.md)。这次没有改变发行版；后续Debian/Ubuntu评估见[37篇](../37-linux-distribution-evaluation.md)。

2026-09-28 首启 UX 第一批：安装阶段与异常恢复页、账户事务状态和显示确认门槛已实现，来源、契约和测试见 [82 篇](../82-first-run-ux-refactor.md)。G100 候选 APK 保留账户启动进入 Plasma 欢迎页，测试后恢复息屏；新账户组件仅完成离线测试，完整清数据首启尚未验证，不扩大此前 `.5` 镜像的验收范围。

2026-09-28 X70 首次账户补充：已修复共享挂载正常但 Pictures 等 XDG 目录未初始化的问题，采用公共会话准备入口；XDG、Qt 与 GLib 路径核验通过。此项仅证明新账户标准目录可访问，不扩展为相机或媒体采集验收。详见 69、83 篇。


2026-09-28 X70 Air Pro 显示大小：实现共享物理密度策略，原生推荐 350%，渲染短边 720 自动对应约 199.17%，保留已有用户选择。KScreen GUI 应用/倒计时恢复、无显示配置默认值、会话重启与倍率往返已在当前账户测试；完整新镜像清数据安装另验。版本、证据和限制见 [85 篇](../85-phone-display-size-policy.md)。


2026-09-28 显示策略第二轮：X70 的首次显示默认值现优先参考 Android density，360 逻辑像素保护默认布局；480→320 密度实测证明已有选择保留、新配置分别生成 350%/250%，720 渲染同步补偿。 具体接口、回退、测试及边界见 [85 篇](../85-phone-display-size-policy.md)。

2026-09-28 X70 Miracast 只读评估：原厂 WFD/P2P 服务存在，但当前手机缺 root 投屏组件、overlay 未授权且无线显示关闭。远端投屏首装/权限修复已合并，源码 APK 为 2.11/59，尚未部署；X70 真实电视投屏未验收。后续使用公共能力探测/连接状态与设备适配器，保留已有 Android/高通链路；差异、上游核验及验收见 [86 篇](../86-x70-miracast-assessment.md)。

2026-09-28 X70 Miracast 部署：APK 2.12＋root 组件已安装；原厂高通 WFD 1080p60，动态配置 unchanged、无新 SELinux 规则。会话级固件适配器暂时停用并恢复两个 Moto UI 包，解决其覆盖 Linux。用户确认电视正常，三轮重连通过；后台更新通过，Dozing 时电视显示 Android 锁屏。声音/输入和整包验收边界见 [86 篇](../86-x70-miracast-assessment.md)。

2026-09-28 收尾补测：容器快捷开关已更新至 rungic-cast 0.331。直接关闭系统 WFD 后 watcher 恢复 UI 包/释放租约通过，但随后的两次重连超时，目标接收端最终报告 unavailable；此异常恢复边界尚未解决，详见 86 篇，不能将前三轮正常重连推广到此场景。锁屏测试由用户手动解锁，自动恢复未验收。

2026-09-29 G100 剪贴板历史：原先只有文本桥运行，Klipper 未启动。plasma-mobile rungic6 已使手机会话常驻同一个 Klipper，并在外屏桌面右下角显示原生剪贴板托盘。前台双向文本、历史选择后 GTK 实际粘贴、关闭窗口继续记录和桌面重启保留已验；托盘用虚拟外屏点击验证，非物理电视。手机通用弹窗越界、助理屏全屏时 Android 焦点限制仍未修复，Android 输入法旧历史未导入。证据与增量部署范围见 [剪贴板历史记录](clipboard-history.md)。

2026-09-29 后续修复：APK 2.14 将剪贴板访问移到容器生命周期内的独立 Shell 身份进程；Linux 直连、APK 仅兼容转发，取消 Activity 焦点条件。G100 上独立 Android 应用前台复制 → Wayland/Klipper、Linux 选择 → Android 实际粘贴，以及助理屏全屏主窗口失焦都已通过。敏感/非文本不跨系统；Klipper 默认阻止清空会恢复上条记录，暂时关闭该选项后双向清空通过，再恢复用户配置。部署与剩余边界见 [后台剪贴板](clipboard-background.md)。

## 2026-09-29：SIM 电话 Agent 候选（双向验收未完成）

见[研究、部署和 10000 实验](cellular-call-agent.md)。G100 已安装 APK 2.18 / Agent 0.365 候选：共享 Realtime 对话 → `cellular_call` / `cellular_audio` → root CallDaemon / non-UI InCallService → Android Telecom 与系统通话 PCM → SIM。已验证真实拨号/接通/挂断、客服下行转写、Linux 微缩通话条和文字指示。客服仍表示未听清，远端上行、物理麦克风隔离、接管与故障恢复未通过完整验收，不能作为跨机型可用能力。私下语音指令和独立旁听开关未开放。

后续执行环境限制 ADB 和远程构建，新状态修正、音频诊断与计时排版仅在工作树中，尚未部署。最新实机证据与各阶段边界以链接记录为准；底座仍为 20260929.2。

2026-09-29 后续本地源码：手机卡/微信通话按用户指定的通道进入同一套助理卡片；能力查询不自动改选。卡片按通话与原对话 ID 恢复，旧卡片控制受校验。25 项离线回归和技能校验通过，尚未部署；不增加上行或跨机型验收结论。详见上述研究文档的“按用户意图选通道与共享卡片”。


2026-09-29 最新增量部署：G100 / W1VT36H.1-51-8 已安装 **APK 2.20 / Agent 0.367**（底座仍为 20260929.2）。通用通道选择、原对话卡片、转写和技能已实机部署；通过共享 CallDaemon 的 VOICE_COMMUNICATION + 运行时显式 TELEPHONY 输出，让 Android AudioPolicy 选择通话上行。10000 第四次 Realtime 实验已获得远端识别“湖南电信”并进入业务菜单的证据；接管释放 Agent 音频、恢复静音且保留原电话，随后挂断回到空闲。前述 2.18 / 0.365 与“未部署”是历史阶段；最新路由研究、版本哈希、日志、回退和边界见[通话实验记录](cellular-call-agent.md)。不写死设备端口、不修改 HAL/SELinux。物理麦克风隔离专项、故障恢复、真人/其他设备和完整自主决策仍未验收；私下语音及独立旁听保持关闭，SSH 自动开启保持不变。


2026-09-29 G100 / UGREEN 投屏：已将厂商 UI 冲突从机型/固件名单重构为运行时窗口规则。确认同一 WFD 外屏中 Linux 窗口上方的已知 UI、核验所属包/UID/类型后才申请恢复租约；状态独立报告 ui_policy。修正工厂预装包未带 SYSTEM 标志的漏判后，android-native 默认路径下自动识别两类 Moto 窗口、断开恢复和重新连接已实测；初始可能短暂露出 Moto。当前外屏布局空隙也通过标准 KScreen 接口修正并在重连后保留；GUI 缩放操作、声音/输入/其他机型验收另做。证据、首个候选失败、最终 jar 和剩余边界见 [G100 UGREEN 记录](g100-ugreen-miracast.md)。

2026-09-29 Miracast 视频模式：分辨率/帧率选择只放在 APK 投屏胶囊的展开面板，底层共用 root 模式控制；选项来自真实 RTSP 接收端回复、硬件编码与已安装接口的交集，视频帧率不再拿 Android 显示刷新率代替。连接预算 120 秒，支持取消；同尺寸帧率在线切换、尺寸变化重新协商并核对外屏大小。G100/UGREEN 的720p30/60和1080p30/60均通过模式读回与KScreen尺寸核验；1440/1600p声明存在但当前后端未能应用，不作为可用模式宣传。实际协议、适配边界、版本、验证与恢复见 [视频模式记录](miracast-video-modes.md)。

2026-09-29 模式列表修正：声明兼容的候选不再直接作为可用选项。胶囊只显示当前一致的模式和在相同发送端/接收端能力下完成准确切换检查的模式；失败项排除、软件或能力变化使旧记录失效，无未验证/试用入口。此前将编码器/API参数支持等同投屏实际输出，导致1920×1200等无效项仍可选，已修正。见 [视频模式记录](miracast-video-modes.md)。

2026-09-29 胶囊交互统一：APK 2.22/70 用胶囊内的共享 BottomSheet 替换模式选择的 Android AlertDialog，设备选择复用同一容器。选中后点击应用才切换，取消/返回/遮罩/下拉回到胶囊；返回优先关闭浮层。G100/UGREEN 实测交互及1080p30→60应用通过，模式过滤与 root 后端保持不变。证据、实现边界与回退 APK 见 [视频模式记录](miracast-video-modes.md)。
