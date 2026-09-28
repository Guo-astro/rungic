# KDE 显示设置与 Android 原生分辨率

2026-09-23，正在实施；未完成下方实机验收前，不把界面选项等同于生效。

## 本机事实与目标

Moto XT2537-4的Android DisplayManager及dumpsys display报告1080×2400，实际模式为30/60/90/120Hz；hasArrSupport=false，不宣称支持连续VRR。旧宿主以720×1600生成Surface，放大至物理屏幕，模糊有明确的缩放来源。用户要求原生清晰度、60/90/120及自动刷新率，并将分辨率/刷新率/缩放放入KDE设置。保留真实30Hz选项。

默认目标1080×2400渲染、KDE 300%缩放，使逻辑工作区保持360×800；720×1600保留为低负载选择。渲染像素数提高2.25倍，需在最终版本重测帧时间，不能沿用720p测试数据保证性能。

## 调研与共同接口

- KDE官方[KScreen 6.6.5源包](https://download.kde.org/stable/plasma/6.6.5/kscreen-6.6.5.tar.xz)及[OutputPanel](https://github.com/KDE/kscreen/blob/Plasma/6.6/kcm/ui/OutputPanel.qml)：已有分辨率、缩放、固定刷新率、应用/还原机制，插件元数据支持handset。Ubuntu kscreen原先未安装，现已从签名APT安装4:6.6.5-0ubuntu0.1及其依赖。
- 现有KWin6.6.6 Wayland嵌套后端只发布当前模式；applyChanges故意忽略scale，因为普通嵌套窗口会跟随上层fractional-scale。本设备平面输出已把显示控制交给Android，需在MOTO_KWIN_FLAT_OUTPUT条件内提供模式枚举及真实设置。非Android后端保留上游行为。
- Android[帧率接口](https://developer.android.com/media/optimize/performance/frame-rate)允许应用提出刷新率偏好，最终受系统调度/温控限制。自动模式是Android策略，不冒充KScreen Adaptive Sync / VRR。

路径：KDE显示KCM / kscreen-doctor → libkscreen → KWin输出管理协议 → Android显示适配 → 宿主Window/Surface公开接口。应用窗口缩放由KWin/Wayland处理，不逐个修改App。

## 实现入口

- APK1.8：DisplayPacer按实际模式枚举固定档位与自动；MainActivity支持原生/720短边渲染，更新Surface尺寸、输入换算和挖孔数据；platform.sock增加display-get/display-set；android-display.json提供只读能力/实际状态。Android设置和Linux请求使用同一套持久化偏好。
- `plasma/android-display-client.h`：KWin和KCM共用客户端，认证沿用平台socket的UID检查，请求限定500ms总期限；渲染帧路径不做同步IPC。
- `plasma/kwin-display-settings.patch`：标准模式枚举、用户模式设置转发、真实缩放；系统重放配置不能覆盖Android实际刷新率与旋转。
- `plasma/kscreen-android-policy.patch`：扩展原版KCM的刷新率策略，显示物理屏幕/渲染分辨率/当前刷新率，复用标准分辨率、缩放、应用和还原。

## 验收清单

KDE主设置可进入显示页；固定30/60/90/120与自动实际生效；原生与720渲染切换、150–300%缩放及还原；重开会话持久化；前后台释放；横竖屏触摸和挖孔；原生分辨率的列表/开启动画帧时间。证据目录refs/plasma-display-settings-20260923/。

构建补充：KScreen源码来自KDE官方HTTPS源包，SHA256保存在证据目录。Ubuntu已安装libkscreen/LayerShellQt6.6.4，KScreen6.6.5原包也依赖这套库；仅将源码的构建最低版本检查对齐6.6.4，实际头文件/链接编译通过。未替换Qt/KF6/图形库。脚本 `build-display-settings.sh`、`build-kwin.sh`、`package-display.py` 保留构建/打包入口。

旧KWin配置的scale=1与实际scale=2不一致，迁移时先保存原文件；新默认原生分辨率和scale=3写入一次性迁移标记，后续不覆盖用户选择。内置屏幕的物理毫米尺寸采用Android报告的xdpi/ydpi换算，供KWin自动缩放识别。

## 19:03实机进展

APK1.8/versionCode9、KWin+moto5、KScreen+moto1已部署。实际渲染1080×2400，KScreen和Qt均为scale3、逻辑360×800。KDE显示页已显示物理/渲染分辨率、缩放和自动/30/60/90/120Hz；四个固定档位经kscreen-doctor设置后，Android物理mode分别为4/3/2/1，实际刷新率吻合。GUI应用“自动”后policy=0，触摸升至120Hz，随后交还Android调度，观察到60/90Hz。证据为rate-validation.json、display-*.txt及auto-validation.json。

用户随后要求量化Vulkan并评估桌面合成，当前转入51篇。缩放/分辨率的完整GUI应用与倒计时还原、方向切换仍需继续验收，不能因此把本篇所有验收项标记完成。固定120Hz/原生尺寸在后续KWin重启测试中持续复核。

## 后续回归记录

KScreen+moto2拆分刷新率选项、已选策略和实时显示信息的变更信号，避免每秒更新实际刷新率时重建选项模型。退出旧设置进程、重新启动后，GUI选择自动并应用，实际refreshPolicy=0；证据为moto2-gui-auto.json和moto2-auto-dialog-later.png。此时的固定120Hz切回检查遇到前台被安卓相机/文件选择器替换，已停止自动点击；moto2-gui-fixed120.json仍为0，不能视为切回成功。完整应用/还原及缩放/方向回归仍待完成。

六个当前显示组件安装包已收集至refs/plasma-display-settings-20260923/packages/，附SHA256SUMS；包含KWin+moto5五包及KScreen+moto2，未重新封装整套ROM。安装后dpkg --audit无输出，apt-get check通过。

## 2026-09-28 X70 Air Pro 的 300% 上限核查

用户反馈 300% 仍偏小。本轮只读核查，未修改用户缩放或重启桌面。精确设备 ZY22MHZKFT（ADB 5038）的 KScreen 实际输出为 WL-0、1264×2780、scale=3，逻辑工作区 422×927；Android display.ini 同样报告 1264×2780。证据：`.work/ci/runs/vantage-20260928-onboarding/device/display-scale-investigation.log`。

上限有两层：KDE KScreen Plasma/6.6 的 [OutputPanel.qml](https://github.com/KDE/kscreen/blob/Plasma/6.6/kcm/ui/OutputPanel.qml) 中 Slider `to: 300`、SpinBox `to: 3.0 * factor`（GPL-2.0-or-later）；项目当前 `packages/kwin/debian/patches/rungic/android-backend.patch` 的 `AndroidBackend::applyOutputChanges` 也拒绝用户请求 `scale > 3.0`。旧的一次性迁移脚本仍使用 `SCALE = 3.0`。本篇原来的默认值依据是 1080 像素短边配 360 逻辑像素，并非 X70 Air Pro 的硬件上限。

按本机原生尺寸计算，350% 约为 361×794 逻辑像素，400% 为 316×695；这只是布局尺寸计算，尚未验收这些档位。提高可选范围须同时核对设置界面和 KWin 后端，沿用标准输出缩放与应用/还原机制；不能仅改 UI 或只放大字体便宣称解决。后续实现前核对固定上游版本和协议校验，验证缩放读回、触摸、旋转、挖孔、键盘及设置还原，默认策略须区分机型且保留用户已选值。

### 密度与手机显示大小策略的进一步核查

本机 `wm density` 报告基础逻辑密度 480（无 override），`dumpsys display` 报告 xdpi=445.9111、ydpi=449.75797，即面板报告的物理尺寸约 72×157 mm；这些是设备报告值，未用尺实测。证据：同目录 `display-density-investigation.txt`。Android 的逻辑密度并非面板 PPI，480/160=3 是 Android dp 到像素的倍率，不能据此保证 Plasma 控件与 Android 控件等大；两者的字体、布局和触摸区域设计不同。参考 [Android 密度说明](https://developer.android.com/training/multiscreen/screendensities)。

进一步查 KDE Plasma/6.6 [OutputConfigurationStore::chooseScale](https://github.com/KDE/kwin/blob/Plasma/6.6/src/outputconfigurationstore.cpp)：手机内屏使用目标逻辑密度 150、最小逻辑尺寸 360，自动缩放另有限幅 3.0，并以 5% 取整。因此前述沿用旧机默认值不是 300% 的唯一来源；上游自动策略按本机报告值计算也接近 3。项目启动包装器已有短边/360 的初值，但最终输出还受 KWin 保存配置、自动生成和迁移影响，不能仅据启动参数认定默认值实际生效。

后续策略建议（尚未实现）：以实际可读性和触摸尺寸校准默认值，使用 `逻辑尺寸=渲染像素尺寸/倍率`，并以 `控件毫米数=逻辑尺寸×倍率/渲染像素密度×25.4` 核验。以 48 逻辑像素的假设点击区域作计算示例，本机原生模式 100%/300%/350% 分别约为 2.7/8.2/9.6 mm；这不是声称所有 Plasma 按钮均为 48。约 360 的手机逻辑短边可作为本机候选，1264/360≈3.51，取 350% 后需验证布局。不能将所有尺寸的平板、折叠屏、外屏统一为 360。

普通用户设置宜提供相对本机推荐值的显示大小档位，必要时在高级设置展示真实倍率，避免将像素一比一的 100% 当作手机推荐值。可选边界按文字/触摸下限及最小可用布局确定，不按固定百分比截断；400% 的逻辑宽仅 316，需验证窄屏布局。切换到 720 短边渲染时，为维持约 360 逻辑短边，倍率应同步约为 2；旋转不改变用户显示大小，外屏使用独立策略。这些为研究建议，未修改当前设备。
