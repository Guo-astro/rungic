# 减少对上游源码的修改（总方案，2026-09-27）

用户于2026-09-27确定：所有上游组件统一为“固定上游＋补丁队列”（[71篇](71-upstream-patch-queue.md)），删除`vendor/`；能在我们自己的组件、扩展点或共享系统服务中解决的，不再修改上游源码。**不以提交上游作为手段**（评审周期过长）：必须保留的修改作为补丁长期维护，升级上游时清理新版本已包含的补丁。用户要求全部做完。

## 现状（2026-09-27）

16个组件带修改：补丁队列7个（KWin、kscreen、plasma-mobile、plasma-settings、FFmpeg、Snapshot、typesafe-computer-use），`vendor/`中9个。`vendor/`里wl-clipboard、arc-cua、LiteRT只有打包或原样导入，没有源码修改。

| 组件 | 修改 | 性质 |
|---|---|---|
| KWin | Android后端与挂钩约1270行；通用修复11条 | 后端无插件接口，保留 |
| kscreen | Android显示设置131行 | 第三阶段并入KWin后端 |
| plasma-mobile | 13条，其中录屏快捷设置1条、回移2条 | 录屏改插件（第一阶段），回移随升级删除 |
| plasma-settings | 模块列表修复1条；Android硬件设置跳转1条 | 后者由第四阶段替代 |
| FFmpeg | 编解码器注册2条 | 视第五阶段 |
| Snapshot | 编码器识别1条；相机时钟1条 | 相机时钟第一阶段，编码器视第五阶段 |
| typesafe-computer-use | 适配开关7行 | 保留 |
| plasma-keyboard | 2处 | 保留 |
| xdg-desktop-portal-kde | 1处 | 保留 |
| plasma-camera | 录像时间戳1处 | 保留 |
| libcamera | virtual管线的PipeWire画面源112行 | 管线只能编进库，保留 |
| qtmultimedia | PulseAudio缓冲参数5行 | 第一阶段尝试服务器端规避 |
| Mesa | UBWC导入开关19行（其余为所用Android分支的固定提交） | 保留 |
| wl-clipboard、arc-cua、LiteRT | 无源码修改 | 直接迁移 |

## 第一阶段：马上可做的小改动

| 项 | 做法 | 能删掉的 |
|---|---|---|
| 1.1 录屏快捷设置插件化 | 我们的录屏做成独立快捷设置插件包，配置中隐藏上游的录屏磁贴 | plasma-mobile `recording-quicksetting`与overlay |
| 1.2 音频块大小 | 在`pulse.pa`中调整Android输出，使块不超过1024帧，从服务器端规避Qt把`maxlength`当硬上限的问题 | qtmultimedia的修改；可行则不再自编qtmultimedia |
| 1.3 相机时钟 | `rungic-camera-source`的PipeWire时间戳与时钟做对 | Snapshot `android-camera-clock` |

验收：录屏快捷设置；浏览器、音乐播放器、通话代理等多个应用播放不断续；Snapshot、plasma-camera、浏览器分别用相机录像，音画同步。

## 第二阶段：剩余组件迁为补丁队列，删除`vendor/`

顺序：plasma-keyboard、xdg-desktop-portal-kde、wl-clipboard → arc-cua、LiteRT → plasma-camera、libcamera（及仍需要的qtmultimedia）→ Mesa（上游为所用分支的固定提交，补丁1条）。方法同71篇第二批：由vendor历史导出补丁，手机上从补丁重建并与发布中的包逐文件比较；版本改为`+rungic1`。全部完成后删除`vendor/`、清单与AGENTS中的vendor约定。

验收：构建结果与原包一致；Mesa迁完跑GPU与桌面性能验收；媒体组件迁完跑相机与媒体验收。

## 第三阶段：显示设置并入KWin后端

先核实KScreen能否只靠KWin的标准输出管理完成所需设置：刷新率作为普通模式，“自动刷新”对应KWin的自适应刷新（VRR）策略，渲染分辨率与缩放的对应。可行则把对应放进KWin Android后端，删除kscreen补丁，kscreen回到Ubuntu的包。

验收：显示设置中切换刷新率、自动刷新、分辨率；旋转与接电视后仍正确。

## 第四阶段：Android硬件接入标准系统服务

分项做、分项验收；未完成的项仍跳转Android设置。

1. **Wi‑Fi**：APK放行更多`cmd wifi`操作（扫描、连接、已保存网络）；NetworkManager模拟服务（`shared/platform/network-manager.py`）实现扫描、接入点列表、连接（密码走KDE的输入流程）、断开、忘记。
2. **电源**：电池已由真实UPower提供；息屏时间对应Android的息屏超时，挂起隐藏。
3. **移动数据**：ModemManager模拟服务：运营商、信号、数据开关。
4. **蓝牙**：BlueZ模拟服务：由APK调用Android蓝牙API完成开关、搜索、配对、连接。

四项完成后删除plasma-settings `android-hardware-settings`。验收：设置页、状态栏快捷设置，以及至少一个使用同一接口的其他应用。

## 第五阶段：VA-API可行性

调研Android编解码桥能否做成VA-API驱动，在没有DRM render节点时能否被FFmpeg、GStreamer、Firefox、Chromium正常初始化。可行则替换FFmpeg的2条补丁、Snapshot编码器补丁与Firefox的`LD_PRELOAD`；不可行则记录原因，维持现状。

## 长期规则

- 保留为补丁：KWin Android后端与挂钩及通用修复；plasma-mobile外屏桌面、窗口规则、面板等功能；plasma-keyboard、portal、plasma-camera、plasma-settings的小修复；libcamera的PipeWire画面源；Mesa的UBWC开关；typesafe-computer-use的适配开关。
- 升级上游时先核对新版本是否已包含我们的修复（如plasma-mobile的2条回移），已包含的删除。

## 进度

（按阶段记录，见下文各节。）
