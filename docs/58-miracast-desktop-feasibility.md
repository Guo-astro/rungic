# Miracast投屏桌面与手机触控板：可行性分析

2026-09-24（含root条件下的补充），XT2537-4 / Android16 / APK1.25 / KWin 6.6.6+moto10 / Plasma Mobile 6.6.5。本篇只做调研与方案，尚未实现；“已核实”指本机或源码中确认过的事实，其余为推断，需原型验证。

## 目标

Linux桌面通过Miracast显示到电视/显示器，外屏进入Plasma Mobile的桌面（Docked）模式；投屏期间手机屏幕作为触控板和键盘。

## 已核实的事实

| 环节 | 结果 | 依据 |
|---|---|---|
| Android Miracast源端 | 可用：`WifiDisplayAdapter featureState=3`（开启），`wifi_display_on=1`，Wi-Fi P2P可用；装有`com.qualcomm.wfd.service`与Moto WFD overlay | `dumpsys display`、`pm list packages` |
| 用户发起连接 | `android.settings.CAST_SETTINGS`解析到AOSP `WifiDisplaySettingsActivity`（系统自带无线显示设置页），普通应用可直接打开 | `cmd package resolve-activity` |
| 应用自行发起连接 | 不行：`CONFIGURE_WIFI_DISPLAY`为`signature|knownSigner`。root进程（uid 0）通过权限检查，可用`app_process`调用DisplayManager隐藏接口（scan/connect/disconnect），属待验证推断 | `dumpsys package permission` |
| Moto Ready For | 已预装（`com.motorola.mobiledesktop` 08.0.3，含`wfd.hce.SourceHceService`），是Moto自家的Android桌面模式；它接管外屏时外屏跑的是Moto桌面，不是给第三方的演示屏 | `dumpsys package` |
| Plasma Mobile外屏行为 | 6.6.5已内置：`KScreenOSDProvider`在输出数>1时自动打开`convergenceModeEnabled`，拔出后恢复；`convergentwindows`脚本在该模式下给窗口加边框、不强制最大化；快捷设置有Docked Mode开关 | `vendor/plasma-mobile` |
| KWin运行时增加输出 | Wayland嵌套后端已有`createVirtualOutput/removeVirtualOutput`（KDE虚拟显示器投屏使用），每个输出在宿主上是一个独立的xdg_toplevel | `vendor/kwin/src/backends/wayland/wayland_backend.cpp` |
| 宿主输入 | 已有Touch/Trackpad/Mouse三种模式、相对位移与点击注入、Android按键与文本提交通道 | `native/plasma/src/compositor.rs`、`input_router.rs` |

## Root条件下的目标架构（2026-09-24补充）

原则：Linux拥有桌面、设备语义和用户交互；Android只当“显示/无线/编码驱动”。外屏在Linux里应像插上一台显示器，手机应像接上一块触控板和键盘，接收端在Plasma里选择。

补充核实（root）：

| 项 | 结果 |
|---|---|
| 网络 | 容器`lxc.net.0.type = none`，与Android共用网络命名空间，能直接使用P2P组网卡上的连接 |
| Wi-Fi P2P | Android wpa_supplicant控制socket在`/data/vendor/wifi/wpa/sockets/wlan0`，`p2p0`网卡存在 |
| 触摸屏 | `chipone-tddi`（event8，TDDI液晶，触摸依赖面板供电）；`/dev/uinput`在Android侧可用 |
| 容器设备 | 容器内暂无`/dev/input`、`/dev/uinput`，未运行udevd；需在LXC配置直通并处理设备属性 |
| KWin输入 | `InputRedirection`支持同时挂多个输入后端；libinput后端目前只在DRM后端创建，只依赖Session，可在嵌套模式下额外挂载 |
| Linux Miracast发送端 | GNOME Network Displays 0.99.0（2026-01）：WFD P2P（经NetworkManager+wpa_supplicant）、MICE（Miracast over Infrastructure，无需P2P）、Chromecast；无界面守护进程与D-Bus管理接口；画面来自portal ScreenCast，GStreamer编码 |
| 发起WFD连接 | root进程通过`CONFIGURE_WIFI_DISPLAY`检查（AOSP对root/system uid直接放行），可用`app_process`调用DisplayManager隐藏接口（scrcpy同类做法），待实测 |

### 输出：外屏作为KWin的热插拔输出

- 触发：宿主检测到外屏后，经平台桥调用KWin（本地补丁，D-Bus）`createVirtualOutput`；断开时`removeVirtualOutput`。KScreen、每输出缩放（电视宜1.5–2）、Plasma Docked模式全部按标准路径生效。
- 传输引擎A（默认）：Android高通WFD栈。宿主在WFD显示上建`Presentation`，第二个toplevel经零拷贝（UBWC）子层提交；SurfaceFlinger合成进WFD编码面（一次GPU/HWC合成），硬件编码、音频、HDCP由厂商栈负责，接收端兼容性最好。
- 传输引擎B（进阶）：Linux侧自有发送端。基于GNOME Network Displays的RTSP/WFD协商与封装，P2P改由Android wpa_supplicant（root下经控制socket设置WFD IE与发现/连接，或经宿主`WifiP2pManager`）提供；另可直接走MICE（无P2P，保留现有Wi-Fi与VPN）和Chromecast。画面从KWin输出取：最短路径是让KWin直接渲染进MediaCodec输入Surface的缓冲（宿主出租这些AHB，零拷贝编码），可设低延迟编码参数（无B帧、帧内刷新、60fps）。
- 两者共用同一个Linux侧D-Bus服务（接收端列表、连接、断开、状态），Plasma快捷设置与设置模块只面向该服务；引擎A的扫描/连接由root辅助进程调用隐藏接口实现。

### 输入：手机作为真实的Linux触控板与键盘

- 极致路线：投屏期间root守护进程`EVIOCGRAB`独占触摸屏（Android不再响应），把多点触控原始事件写入一个带`INPUT_PROP_POINTER/BUTTONPAD`与物理分辨率的uinput触控板；该设备直通进容器，KWin在嵌套模式下额外挂libinput后端读取它。由此得到libinput级的加速曲线、防误触、轻点/拖拽、双指滚动与KWin三/四指手势，系统设置里的触控板模块也直接可用。需要处理：Android InputReader也会看到新uinput设备（root下经隐藏接口禁用该设备）、容器内设备节点与udev属性（`ID_INPUT_TOUCHPAD`）。
- 稳妥路线：宿主把Android MotionEvent处理成wl_pointer相对位移、带finger来源的滚动和`zwp_pointer_gestures_v1`手势发给KWin（嵌套后端已绑定宿主的手势协议）。无内核改动，但加速与轻点逻辑要自己实现或移植libinput算法。
- 键盘：APK内自带键盘视图，发送evdev键码（同样可走uinput键盘或wl_keyboard），由Linux侧Rime组字，Ctrl/Alt/Meta快捷键完整；蓝牙实体键盘照常可用。
- 手机屏幕：TDDI触摸依赖面板供电，不能关屏；投屏时用root把背光降到0并显示纯黑，省电且触摸仍有效（待实测）。

### Root带来的系统保障

- 投屏是长时间高负载场景：宿主启动后由root把其`oom_score_adj`设为-1000，避免重演57篇Elisa事故中前台宿主被lmkd杀死；另加容器GPU内存看门狗。
- P2P与STA同信道（root下设置P2P操作信道等于当前Wi-Fi信道），避免多信道切换带来的带宽与延迟损失。

### 分阶段验证（每步都是小原型）

1. root辅助进程扫描/连接接收端；宿主在外屏显示Presentation测试图；记录显示标志、分辨率、端到端延迟（需要一台Miracast接收端）。
2. KWin热插拔第二输出+宿主多窗口绑定，外屏出现Plasma并自动进入Docked模式。
3. 输入：先做宿主级触控板+手势；并行验证uinput触控板+嵌套libinput后端。
4. 声音、断开重连、宿主重启恢复、功耗温度；然后评估引擎B（MICE/Chromecast/自有编码）。

### 现有实现调研与自研边界（2026-09-24）

- KDE：本轮在invent.kde.org按“miracast”“wifi display”检索未找到Miracast发送端项目（只能记为本轮未找到）。相邻组件：KDE Connect的`virtualmonitor`（把另一台装有KDE Connect的设备当扩展屏，走RDP/VNC，不面向电视）、`mousepad`/`remotekeyboard`（手机当触控板/键盘，需切到KDE Connect应用）、krfb/KRdp（VNC/RDP服务端）。
- GNOME Network Displays：GPL-3.0，本轮查到的唯一仍在维护的Linux Miracast发送端（0.99.0，2026-09-22仍有提交）；不绑定GNOME，经portal ScreenCast取画面，可配合xdg-desktop-portal-kde。
- 更底层的库：MiracleCast（albfan维护，2026-03有提交，以接收端为主，发送端不完整）；Intel WDS（RTSP状态机库，LGPL-2.1，2022年已归档）；gst-rtsp-server（GND在其上实现WFD）。AOSP早期的libstagefright WFD发送端已移除，现由厂商（本机为高通）闭源实现。
- 协议本身：Wi-Fi Direct（带WFD信息元素）→ RTSP能力协商（M1–M7，保活M16）→ RTP承载MPEG-TS（H.264，LPCM/AAC）；HDCP 2.x与UIBC可选。自研最小发送端的工作量主要在接收端兼容性、P2P建链可靠性与音画同步，协议状态机与封装本身不大。
- 自研的合理位置是宿主原生层：编码器（MediaCodec）与Wi-Fi P2P都在Android侧，且只有宿主能让KWin直接渲染进编码器输入缓冲实现零拷贝。结论：先用高通WFD栈（引擎A）打通完整体验并量化延迟，确有必要再在宿主Rust里自研引擎B，并以引擎A为基准对比。

### 用户需求（2026-09-24确认）

- 有一台支持的电视。
- 投屏时手机继续显示Plasma移动界面（两个输出同时渲染）。
- 手机屏幕上有可拖动的悬浮控制按钮，在“手机正常触控 / 触控板（控制电视指针）/ 键盘（向电视上的窗口输入）”之间切换。按钮做在宿主Activity内（Android视图层），不依赖KWin状态、响应即时；触控板模式是覆盖在手机界面上的半透明层，键盘模式在下方显示键盘、上方保留触控板区域。

## 初版方案：Android Presentation承载外屏输出（无root假设）

```
电视 ◀─Miracast(Android WFD编码)─ Android WFD显示(Presentation类)
                                        ▲ Presentation窗口(SurfaceView，零拷贝子层)
宿主APK ── 第二个xdg_toplevel ◀── KWin输出WL-1(createVirtualOutput)
手机屏幕：宿主Activity切换为触控板+键盘界面 → Trackpad模式 → wl_pointer/wl_keyboard → KWin外屏输出
```

1. 连接：用户在Plasma里点“无线投屏”，宿主打开系统无线显示设置页选电视（无需root）；进阶可由root辅助进程在Plasma内直接列出和连接接收端。
2. 外屏出现：AOSP把WFD显示注册为演示类显示（推断：`FLAG_PRESENTATION`，需实测标志）。宿主`DisplayManager`监听到后，在该显示上创建`Presentation`，内含SurfaceView；有Presentation时外屏显示它而不是镜像手机。
3. 输出：宿主经平台桥通知容器，KWin（本地补丁，D-Bus入口）调用`createVirtualOutput`按外屏尺寸建输出WL-1；宿主把第二个toplevel绑定到Presentation的窗口，配置尺寸、独立的零拷贝图层与帧节拍。Plasma Mobile随即进入Docked模式。
4. 手机端：主Activity切换为触控板界面（单指移动、轻点点击、双指滚动、三指等手势沿用Trackpad模式），键盘用Android输入法（按键与文本提交已有通道，中文可走Android输入法提交或Linux侧Rime）。指针事件发往外屏输出的toplevel。
5. 断开：Presentation消失→`removeVirtualOutput`→退出Docked模式→手机恢复桌面。
6. 声音：Android WFD随会话传输设备音频，容器声音经现有PulseAudio→AudioTrack桥进入Android，推断会一同送到电视，需实测。

### 需要做的工作

| 部分 | 内容 | 规模 |
|---|---|---|
| 宿主Java | 显示监听、Presentation、触控板/键盘界面、打开投屏设置 | 中 |
| 宿主Rust | 多窗口：toplevel与Android窗口的绑定、每个输出独立的表面尺寸、零拷贝Presenter、GLES回退与帧节拍；输入按目标输出路由（目前全部按单一表面设计） | 大 |
| KWin补丁 | D-Bus增删宿主输出、输出名/尺寸/缩放；确认嵌套后端对两个输出的指针进出与光标 | 中 |
| 容器桥 | 平台桥事件→KWin；Plasma快捷设置“无线投屏” | 小 |
| 可选root辅助 | `app_process`调用隐藏接口扫描/连接接收端 | 小到中，待验证 |

## 备选方案：借Moto Ready For

把现有Activity直接放到Ready For接管的外屏上全屏运行，Ready For自带手机触控板与键盘，宿主只需处理显示尺寸与密度变化（与旋转同类）和鼠标事件。改动最小，但依赖Moto私有功能、外屏只有Linux一个窗口且受Ready For窗口管理约束，也无法在Linux侧选择和连接接收端。适合作快速原型，不作为通用方案。

## 风险与待验证

- WFD显示的实际标志、分辨率（通常1080p60或720p）与Presentation是否可用，需接真实Miracast接收端验证；部分电视的Miracast兼容性差。
- 端到端延迟：Miracast编码、Wi-Fi与电视解码通常在百毫秒量级（推断），光标会有可感知的滞后；电视游戏模式可改善。
- Wi-Fi P2P与现有Wi-Fi/VPN（SwiftWire）并发时可能换信道或降速。
- Ready For与系统投屏入口可能争用同一WFD会话；需确认普通“无线显示”连接不会被Ready For接管。
- 功耗与发热：KWin多渲染一个1080p输出，外加Android硬件编码。
- Plasma Mobile的Docked模式偏基础（窗口边框、非最大化），外屏上的面板/任务栏体验需实机评估，可能需要桌面化调整。
- 手机屏幕若继续显示Plasma移动界面则需要双输出同时渲染；推荐投屏时手机端只显示触控板，内置输出保持但不参与交互。

## 原型验收顺序

1. 用系统无线显示页连电视；宿主在外屏显示Presentation测试图，记录显示标志、尺寸与延迟。
2. KWin建第二输出并在外屏显示Plasma，确认Docked模式自动开启。
3. 手机触控板移动/点击/滚动与键盘（含中文）在外屏应用中可用。
4. 断开、重连、旋转手机、宿主重启后的恢复；声音路由；功耗与温度。
