# Miracast投屏桌面与手机触控板：可行性分析

2026-09-24（含root条件下的补充），XT2537-4 / Android16 / KWin 6.6.6 / Plasma Mobile 6.6.5。前半部分是调研与方案；第1–3步原型已实现并实机验证（见各节），“已核实”指本机或源码中确认过的事实，其余为推断。

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

### 测试与观测方法（手机与开发机K8不在同一地点）

Miracast需要Wi-Fi Direct近距离直连；手机经VPN连到K8，K8（Intel AX200，支持P2P-client/GO/device）不能当接收端。改为真实电视接收、agent在手机侧观测：

- 画面：WFD显示是Android的独立显示，root下`screencap -d <显示ID>`取编码前画面（若为安全显示被拒，用下一项）。
- 码流：高通`wfdconfig.xml`的`RTPDumpEnable`保存发出的RTP流，拉回K8解码，核对分辨率、码率、关键帧间隔与画面内容。
- 协商：logcat中的RTSP协商与会话状态，用于定位兼容性失败发生在哪一步。
- 延迟：手机侧从出帧到发包自动测；电视解码显示部分需一次人工观测（手机与电视同时显示毫秒时钟并拍照）。
- 自研发送端（引擎B）的协议调试不受距离限制：P2P只负责建链，RTSP协商与RTP传输是普通IP流量，可经VPN连K8上的软件接收端调试。

## 实测：系统投屏卡在“正在准备”（已修复）

2026-09-24，接收端TCL 85Q6H（广播R1与R2两个入口），另试“客厅电视”与DIRECT-9c4hVFLO，结果相同。

- 现象：六次尝试都能完成Wi-Fi Direct建组（手机为组主，GO intent 15，`p2p0` 192.168.49.1/24，2.4GHz 2417MHz），但高通`ExtendedRemoteDisplay`一直停在`ESTABLISHING`，约10秒后以“Why on earth is surface null??”拆除，电视停在“正在准备”。
- 排除：SwiftWire VPN只接管`10.77.0.0/24`与`198.18.0.1`（分流），其路由表没有IPv4默认路由，P2P流量不经隧道；用户关闭VPN后同样失败。`wfdservice64`按会话由`vendor.wfdservice64`属性启停，属正常。
- 定位：高通WFD进程读不到调试属性，几乎不打日志。用户授权后临时`setenforce 0`，投屏立即成功；宽容模式下记录的WFD相关拒绝为：`vendor_wifidisplayhalservice_qti`的`capability net_raw`（每次会话失败前约0.7秒出现，推断用于把socket绑定到P2P网卡）与`vendor_media_data_file`目录search、`vendor_wfdservice`查找`vendor.perfservice`、`vendor_wfdservice/vendor_wfd_app`读取`vendor_wfd_sys_debug_prop`。
- 修复：`shared/android/wfd.sepolicy.rule`只放行上述四组；`shared/android/moto-wfd-sepolicy.sh`安装为`/data/adb/service.d/moto-wfd-sepolicy.sh`，每次开机用`magiskpolicy --live --apply`加载`/data/adb/moto-wfd/wfd.sepolicy.rule`（与Docker规则同一方式）。SELinux恢复Enforcing后再次投屏成功，之后没有新的WFD拒绝；临时打开的`persist.vendor.debug.wfd*`已用`resetprop -p --delete`删除。
- 连接后的状态：WFD显示`TCL 85Q6H-9E92[R1]`，1920×1080@60，`activeDisplayState=2`；Moto启动器在该显示上启动`SecondaryDisplayLauncher`（外屏是可运行Activity的副屏，而非只能镜像），这对后续由宿主接管外屏有利。
- 未验证：`net_raw`以外的三组规则是否必要（为减少用户往返一并放行）；重启后规则自动加载需在下次重启时确认。

## 第1步原型：root投屏控制与接管电视画面（2026-09-24）

### root投屏控制：`moto-cast`

`shared/android/moto-cast/`：Java源码经javac+d8编为`moto-cast.jar`，装在`/data/adb/moto-wfd/`，由root经`app_process`运行，反射调用`DisplayManagerGlobal`隐藏接口（root通过`CONFIGURE_WIFI_DISPLAY`检查），输出JSON：`status`、`scan [秒]`、`connect <地址|名称> [秒]`、`disconnect`、`decor <显示ID> [on|off]`。实测按名称约3–6秒连上。

实现中踩到的两处框架行为：

- Android 16的`DisplayManagerGlobal.startWifiDisplayScan`不再隐式注册显示回调，调用方必须先`registerDisplayListener`，否则抛`IllegalStateException`（未捕获时app_process以SIGKILL结束，表现为“Killed”）。
- `WifiDisplayController`只连接当前发现列表中的对端，扫描开始或停止都会清空该列表，而`WifiDisplayStatus`里可能仍显示上一轮的“可用”。因此连接请求须在扫描进行中发出，并在状态仍为未连接且对端重新出现时每3秒重发。修复前的若干次“停用Ready For后连不上”实验结论因此作废并已重做。

### 接管电视画面：`CastTest`（APK1.26）

平台桥`cast-test`（`{"enabled":true|false}`或仅查询）：在Presentation类显示上放测试图案（彩条、毫秒时钟、帧计数、移动色块），手机中央叠加同源时钟用于拍照测延迟。

- WFD显示：`FLAG_PRESENTATION | FLAG_SHOULD_SHOW_SYSTEM_DECORATIONS | FLAG_TRUSTED | FLAG_OWN_DISPLAY_GROUP`，1920×1080@60，160dpi，type WIFI，无`FLAG_SECURE`；每次连接逻辑显示ID都会变。`screencap -d <SurfaceFlinger虚拟显示ID>`（`dumpsys SurfaceFlinger --display-id`）可截取合成后的电视画面。
- 遮挡：Moto Ready For在首次连接时弹出模式选择`MotoDesktopSplash`（窗口类型2938），并在该显示上放任务栏`MotoTaskBar`（`com.motorola.systemui.desk`，导航栏类窗口）与副屏启动器。Presentation位于二者之下；普通窗口无法盖过导航栏层级；`setShouldShowSystemDecors(false)`被显示自身的`FLAG_SHOULD_SHOW_SYSTEM_DECORATIONS`覆盖，无效。
- Ready For不能整体停用：`com.motorola.mobiledesktop.core`参与P2P发现，`com.motorola.mobiledesktop`参与发起连接（Moto改过的框架把连接交给它）。只停用任务栏包`com.motorola.systemui.desk`后连接正常，任务栏消失。当前设备上该包处于`disabled-user`状态，恢复命令：`pm enable --user 0 com.motorola.systemui.desk`。
- 窗口：改用`TYPE_APPLICATION_OVERLAY`（清单声明`SYSTEM_ALERT_WINDOW`，root下`appops set dev.moto.plasma SYSTEM_ALERT_WINDOW allow`），`FLAG_NOT_FOCUSABLE`使输入焦点始终留在手机；不能加`FLAG_NOT_TOUCHABLE`，否则Android 12+对不可触摸的悬浮窗限制最高0.8不透明度（画面透出底层）。结果：电视上为不透明、整屏1920×1080的测试图案。
- 焦点：向电视显示注入点击会把`mTopFocusedDisplayId`切到外屏，手机上的宿主不再是顶层resumed（平台桥随即拒绝请求）；正式方案中电视上的输入必须走宿主自己的路由，不能让Android焦点切过去。
- 帧节拍：测试图案在主线程Choreographer上重绘，跟随手机120Hz（焦点在外屏时为60Hz），而WFD显示为60Hz；正式实现须按外屏的60Hz出帧。
- 延迟：待拍照测量。

## 第2步：电视成为KWin的第二个输出（2026-09-24）

结果：手机继续显示Plasma移动界面，电视上是同一会话的第二个输出`CAST-1`（1920×1080，缩放1.5，逻辑1280×720，位于手机输出右侧）；Plasma Mobile自动进入docked（convergence）模式，窗口可移到电视上并带标题栏。断开/重连多次，KWin、plasmashell保持运行，docked模式随之开关。延迟未测（按用户要求暂缓）。

```
电视 ◀─WFD─ Android WFD显示 ◀─ 宿主悬浮窗PlasmaCastDesktop（SurfaceView，Presenter零拷贝）
                                              ▲ dmabuf/AHB
宿主Smithay：wl_output "Moto Cast" ◀─bind─ KWin(moto11)：输出CAST-1的xdg_toplevel
                                              set_fullscreen(该wl_output) → 宿主认领为投屏窗口
手机屏幕：宿主原有窗口/Presenter ◀── KWin输出WL-0（不变）
```

链路：

1. 宿主平台桥`cast-desktop`（`{"enabled":true|false}`）：`CastDesktop`在Presentation类显示上加`TYPE_APPLICATION_OVERLAY`悬浮窗（与第1步相同的不透明、不可聚焦参数），内含固定为显示模式尺寸的SurfaceView；`surfaceChanged`经JNI`bindCastSurface(surface,w,h,刷新mHz)`交给原生层，`surfaceDestroyed`调用`releaseCastSurface`。显示移除（断开投屏）时悬浮窗随之移除。
2. 原生宿主（`native/plasma/src/android/backend/wayland/cast.rs`）：绑定后新增wl_output全局（make“Moto”、model“Cast”、1000×563mm、缩放1），释放时撤回该全局。KWin对它的xdg_toplevel发出`set_fullscreen(该输出)`时，`fullscreen_request`把它认领为投屏窗口：配置为电视尺寸、映射在空间坐标(100000,0)、不参与手机的渲染列表、触摸命中和焦点选择（新窗口抢到的键盘焦点还给手机窗口）。每帧`render_all`把它的dmabuf留给`present_cast`，经独立的`Presenter`送到电视SurfaceView，完成后同样调用`finish_presentation`回帧回调；帧时钟停摆判断把未结清的投屏Presenter视为忙。
3. KWin嵌套后端（vendor/kwin，`6.6.6-0ubuntu0.1+moto11`）：`WaylandDisplay`以KWayland `Output`绑定宿主的wl_output并跟踪增删；`WaylandBackend`对make/model为Moto/Cast的宿主输出创建`CAST-n`输出（热插拔，发`outputAdded`与`outputsQueried`），其xdg_toplevel以该宿主wl_output请求全屏；制造商、型号、物理尺寸、刷新率取自宿主输出。`MOTO_KWIN_FLAT_OUTPUT`的Android主屏模式与`internal`标记只作用于手机输出，投屏输出按外接显示器处理。
4. Plasma Mobile（vendor/plasma-mobile）：`KScreenOSDProvider`在输出数>1时打开convergence模式，但上游`KScreenOSDUtil`构造时从未调用`retrieveKScreen()`，输出数恒为0，插入外屏也不会切换（上游master同样未修复）。本地在构造函数中调用它；插件在手机上编译后以dpkg-divert覆盖`/usr/lib/aarch64-linux-gnu/qt6/qml/org/kde/plasma/quicksetting/kscreenosd/libkscreenosdplugin.so`。

问题与处理：

- **断开时KWin被宿主断开**：KWin最初以`wl_output` v2绑定，KWayland `Output`销毁时发送`release`（v3起才有），宿主判定协议错误`invalid method 0 (since 2 < 3), object wl_output#44`并断开KWin，会话里的plasmashell、portal等随之以255退出重启。改为绑定v3（KWayland不处理v4的name/description事件）后断开/重连正常。
- **docked模式持久值**：`KScreenOSDProvider`把“插入前的模式”记在持久设置本身，会话在docked状态下重启会把`true`当成初始值，之后拔出外屏也不再退出docked。上面的崩溃期间出现过一次，已手动写回`false`（`kwriteconfig6 --file plasmamobilerc --group General --key convergenceModeEnabled --notify false`）。只要会话不在投屏中重启就不会触发；未改上游逻辑。
- **缩放**：KWin的`chooseScale`对高度>500mm的外接屏按电视目标30.5dpi计算，1000×563mm下给1.35；首次出现时曾以其他模式记下缩放1。现已用`kscreen-doctor output.CAST-1.scale.1.5`设为1.5，写入`kwinoutputconfig.json`并按输出UUID保留；用户可在显示设置中改。
- **Android焦点不能切到电视**：用`input -d <电视显示> tap`调试会把Android顶层焦点移到外屏，之后`am start`会把宿主Activity以自由窗口启动到电视上。宿主`MainActivity`在非默认显示上创建时改为在显示0上重新启动自身并结束（APK1.27）。电视上的指针输入由第3步经宿主路由，不依赖Android的外屏触摸。
- **帧节拍**：投屏窗口目前跟随手机输出的帧时钟出帧，未按电视60Hz单独节拍；Presenter统计计数由两个Presenter共用。

验收方法：`moto-cast connect <电视>`连上后调用`cast-desktop`；`kscreen-doctor -o`应列出WL-0与CAST-1；`screencap -d <电视的SurfaceFlinger虚拟显示ID>`截取电视画面；用KWin脚本（`workspace.sendClientToScreen`）把窗口移到CAST-1确认应用显示在电视上；关闭再打开`cast-desktop`，确认`pgrep kwin_wayland/plasmashell`不变、输出与`convergenceModeEnabled`随之变化。

## 第3步：手机作为电视的触控板与键盘（2026-09-24）

结果：投屏时手机右侧出现可上下拖动的悬浮控制条。手机模式下只有一个“投屏控制”按钮，点它进入触控板；展开后有“手机 / 触控板 / 键盘”三段。

- **手机**：手机照常操作Plasma移动界面。
- **触控板**：手机屏幕盖一层半透明触控面板（Plasma界面仍隐约可见），在电视上移动KWin光标、单击、拖动、滚动。
- **键盘**：触控板加上Android输入法；按键和文字送到电视上获得焦点的Linux窗口。输入法被返回键收起后自动回到触控板。

实机验证：

- 触控板把电视上的Kalk按出7、8。
- 键盘模式下，按键输入的“abc1+2”和经输入法提交路径的“你好，世界”“中文输入”都正确进入电视上的KRunner，电视上不再弹出Plasma屏幕键盘。
- 多次切换模式、重启会话，KWin与plasmashell不崩溃。

```
手机：CastControls（控制条 + TouchpadView，Java手势）
   │ NativeBridge.castPointer(op,x,y)：0开关 1相对移动 2按键 3滚动 4滚动结束
   ▼
宿主 cast.rs：cast_pointer → wl_pointer 进入投屏窗口（KWin输出CAST-n的宿主窗口），位置限制在电视像素内
   ▼
KWin(moto12) 嵌套后端：Pointer::motion → 输出CAST-n上的绝对位置；投屏输出没有光标层，光标由KWin画进电视画面
键盘：Android输入法 → DisplayView InputConnection → 已有按键/文字通道 → 宿主wl_keyboard / text-input-v3 → KWin → 焦点窗口
```

实现要点：

- **触控板手势在Java侧识别**（`CastControls.TouchpadView`）：
  - 单指移动为相对位移，增益约1.3到4倍，随速度增大。
  - 轻点在抬起时按下左键，180ms后松开；这期间再次按下即为拖动（与libinput的tap-and-drag一致），不移动再轻点一次即为双击。
  - 双指移动为自然方向滚动，结束时发送axis stop。
  - 双指轻点为右键，三指轻点为中键。
- **宿主**：投屏指针与手机原有的Touch/Trackpad/Mouse模式分开。`cast_pointer`开启时，座位额外提供`wl_pointer`；手机侧仍是`wl_touch`，控制条之外的触摸被触控面板截获，不会进入手机界面。指针事件只发给投屏窗口，焦点原点取该窗口在空间中的位置。
- **enter时序**：Smithay只在焦点变化时发送`wl_pointer.enter`/`zwp_text_input_v3.enter`，而KWin看到新能力或创建对象后才绑定。因此：
  - 开启触控板时不立即移动指针，由第一次手指移动进入投屏窗口。
  - KWin创建text-input后先主动enable一次。
- **KWin光标**：
  - 嵌套后端原本把光标交给宿主的`wl_pointer.set_cursor`。宿主只把光标画在手机画面上，电视路径是单缓冲零拷贝。
  - 现在投屏输出不创建CursorOnly层，KWin的`assignOverlays`找不到光标层，就把光标画进主层。
  - 手机输出保持原有的光标层。
- **键盘**：沿用`DisplayView`的InputConnection。Latin字符和按键按键码注入。中文、表情等无法用键码表示的文字经text-input-v3提交，见下文。
- **平台桥**：
  - `cast-controls`：查询或设置`{"mode":"phone|touchpad|keyboard"}`。
  - `text-commit`：`{"text":…}`，与输入法`commitText`走同一调用，用于测试和工具。

排查中修复的共享层问题：

1. **KWayland `Output`导致KWin崩溃**：
   - 上游`Output::Private::addMode`（KWayland master仍如此）先把新模式插到QList末尾并记下`currentIt`，然后遍历时`erase`重复模式。`erase`移动元素后`currentIt`失效，循环越过末尾，导致SIGSEGV。
   - 宿主每次改变刷新率（DisplayPacer在60/120Hz间切换）都会重发wl_output mode。KWin从第2步开始绑定宿主wl_output，因此在切换触控板/键盘时崩溃。核心转储显示崩在KWayland监听回调内。
   - KWin改用自有的`HostOutput`直接监听原始wl_output事件，只保留制造商、型号、物理尺寸和当前模式；`set_fullscreen`直接调用`xdg_toplevel_set_fullscreen`。
   - KWin退出时先释放HostOutput再断开连接，否则`wl_output.release`会发到已关闭的连接上，退出时崩溃并打乱会话重启。
2. **Android键码表错位**：
   - `keymap.rs`中所有标点都错了一行，例如逗号被映射为句点、等号被映射为`[`。Home、End、Insert、SysRq以及小键盘除号、乘号、小数点、回车也不对。
   - 已按`linux/input-event-codes.h`改正，并补上Caps Lock、`+`（小键盘加号）、`*`。
   - 影响所有经Android按键事件进入的输入，包括蓝牙键盘和输入法`sendKeyEvent`。
3. **电视每次重连缩放回到1倍**：KWin按输出名保存缩放等设置（这些输出没有EDID）。投屏输出原先每次连接都递增为CAST-2、CAST-3……，于是每次都成了新输出。现在取最小可用编号，电视始终是CAST-1，沿用已保存的1.5倍。
4. **电视上弹出Plasma屏幕键盘**：
   - `KWIN_IM_SHOW_ALWAYS=1`是为手机触屏准备的，现在只对内部输出生效。判断依据是正在输入的窗口所在输出，取不到时用活动输出。
   - 外接输出按KWin原规则处理：最后输入来自触摸或数位板时才弹出。
   - 输入面板的“允许显示”（`InputPanelV1Window::allow`）一经授予就不再收回，因此文本框的自动显示请求（text-input v1/v2/v3）改走`showForTextInput`：不满足上述条件时收起面板。用户经D-Bus手动调出不受影响。
5. **中文经Android输入法提交**：
   - 宿主原有的text-input-v3提交路径（`arabic_input.rs`）从未生效。Smithay在没有input-method客户端时丢弃全部text-input请求，而且KWin本身也不绑定宿主的text-input。
   - 现在Smithay（`native/plasma/lib/smithay`本地修改）在没有input-method时也跟踪启用状态。text-input对象销毁时清除激活记录，焦点离开时总是发送leave。原先KWin重启后，旧连接留下的失效激活记录会让新KWin的enable一直被当成“已有激活实例”而丢弃。KWin嵌套后端绑定宿主的`zwp_text_input_manager_v3`并保持启用，收到的`commit_string`交给KWin输入法的`commitHostText` → `commitString`：焦点客户端有text-input时直接提交，没有时用临时键位注入。
   - 手机模式下的“Android 键盘”菜单也经过这条路径。

仍待处理：

- 延迟未测。
- 手势的增益与轻点阈值只在实机上初调过。
- 手机的Android焦点在键盘模式时仍在宿主Activity，需确认各类输入法的行为（本机为搜狗）。
- KWin在已有投屏触控板时崩溃重启，手机左上角会短暂出现KWin画的光标（已知的启动时光标问题）。

验收方法：

1. `cast-desktop`连接后调用`cast-controls {"mode":"touchpad"}`。
2. 用`input swipe/tap`在手机上操作；`native-stats`的`dispatch=cast_motion x=… y=…`给出电视像素位置，KWin脚本`workspace.cursorPos`应与之一致（逻辑坐标×1.5）。
3. 截取电视画面，确认光标位置与点击效果。
4. 键盘模式下用`input text`和`text-commit`分别验证按键与中文提交。
5. 每一步后`pgrep kwin_wayland`，确认进程ID不变。

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
