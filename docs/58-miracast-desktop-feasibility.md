# Miracast投屏桌面与手机触控板：可行性分析

2026-09-24，XT2537-4 / Android16 / APK1.25 / KWin 6.6.6+moto10 / Plasma Mobile 6.6.5。本篇只做调研与方案，尚未实现；“已核实”指本机或源码中确认过的事实，其余为推断，需原型验证。

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

## 推荐方案：Android Presentation承载外屏输出

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
