# G100 向 UGREEN 投屏被 Moto 外屏界面覆盖

2026-09-29。用户报告投屏显示 Moto Ready For，未显示 Linux。执行端现场为 mibook / x86_64，系统代理 none；USB G100 `ZY32M9MRVP` 在 ADB 5038，设备 `portov` / XT2533-4 / Android 16 SDK 36 / `W1VT36H.1-51-8`，SELinux Enforcing。另一台无线 G100 S 未操作。

## 当前结论

用户要求通用化后，已撤回 G100/X70 的 UI 固件名单，改为共享运行时窗口冲突规则。当前 `adapter=android-native`、`ui_policy.mode=runtime-window-conflicts`；修正 SYSTEM 标志误判后，自动识别和清除 Moto 遮挡、断开恢复、再次连接均在 G100/UGREEN 验证。下面先保留定位与临时修复历史，最终实现与边界见文末。

## 根因与复用核验

- 当前 APK 2.20，投屏 root 组件已安装且摘要健康检查通过。设备和仓库的 `adapters.json` 只有 X70 `vantage`、G100 S `mumba`，没有 G100 `portov`。能力报告选中 `android-native`，因此不改变厂商 UI 包状态。是已安装配置缺少当前固件适配，不能归因为 APK 回退或接收端只支持 Moto。
- 用户刚才连接的接收端为 UGREEN-52BCCF3C。18:41 日志记录外屏 ID 3、1920×1080@60，同时存在 `PlasmaCastDesktop`、`MotoDesktopSplash: 3` 与 `MotoTaskBar: 3`。18:41:43 会话断开。检查时已无外屏，随后一次重新连接超时；此时不能说已重新看到修复后的画面。
- 对照 [X70 已验收的租约机制](../86-x70-miracast-assessment.md)和 [G100 S 既有研究](../58-miracast-desktop-feasibility.md)。本次复查 `CastAdapter.java`：按 device/build-id/SDK 精确匹配、保存原 enabled state、原子租约、连接前 claim、断开 release、watcher 异常恢复。`CastDesktop.java` 在外屏创建后也执行 claim，覆盖从 Android 设置发起连接。
- [Android 官方 TYPE_APPLICATION_OVERLAY 文档](https://developer.android.com/reference/android/view/WindowManager.LayoutParams#TYPE_APPLICATION_OVERLAY)明确普通应用 overlay 仍在关键系统窗口之下。检查 AOSP Android 16 的 [DisplayContent.java](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android16-release/services/core/java/com/android/server/wm/DisplayContent.java)和既有 Moto 窗口证据；AOSP 不等同于本机私有窗口策略。加大 Linux 窗口或重做编码器不能解除已存在的厂商外屏 UI 遮挡。

## 第一阶段：固件配置临时修复（已被运行时方案替代）

`profiles/cast-adapters.json` 增加 `motorola-portov-w1vt36`，只匹配上述本机固件。复用现有租约，在 Rungic 投屏期间暂停 `com.motorola.mobiledesktop` 与 `com.motorola.systemui.desk`，断开恢复原状态；两包本次原值均为 enabled=1。保留 `.core`、高通 WFD、主屏 launcher 和锁屏机制。暂停范围是两个完整 UI 包，期间其其他界面也不可用，不能描述为只关一扇窗口。未知机型仍走默认路径，不按 Motorola 品牌扩大匹配。

用 `tools/deploy_cast.py` 及统一载荷清单更新当前账户；jar 复用已部署的同一 SHA-256 `19ce922dc7967c2e4eddc38f06c53ea8684b5fd6e321288b4e73567248724a91`，不重装 APK/容器。备份在 `.work/experiments/g100-ugreen-cast-20260929/deploy/backup/`；原始日志、配置摘要和包状态均在同级目录。5 项现有首启安装回归通过。镜像种子共用此配置，实际整包清数据验收另做。

动态编码配置继续共用既有生成器。修改前本机已有自己的 bind，日志显示各项上限调整至 2560×1440@60；本次不新增编码算法或沿用 X70 的 unchanged 结论，也不把该上限当作 UGREEN 实际协商分辨率。

回退先正常断开、确认租约已恢复两个包，再以共享安装器安装备份载荷；恢复旧配置会重新失去 G100 UI 遮挡处理。不要删除尚未释放的租约，不停用整个 Moto/高通服务组。

## 实机验收

用户说明 UGREEN 始终可以连接，无需手动切换等待页。此前一次超时原因尚未确定，不能据此归因于接收端没有准备好。

配置部署后重新连接同一地址，11.2 秒成功（`connect-1.txt`）。状态选中 `motorola-portov-w1vt36`、active_state=2、外屏 ID 4；KWin 的 CAST-1 为 1920×1080@60。租约保存两个 UI 包原值 1，连接期间均变为 3（disabled-user），`.core` 不在租约中。`final-window.txt` 的外屏可见窗口为 PlasmaCastDesktop，无 MotoDesktopSplash/MotoTaskBar；`linux-external.png` 保存 Android 合成输出。用户明确确认电视正确显示 Linux，载荷健康检查返回 0。

本次差异是连接前已部署 G100 配置并执行现有 claim；不是用户操作顺序有误，也不是改用另一套投屏引擎。修复不限于接收端名称，配置没有写入 UGREEN 的名字或地址。

为保留用户正在使用的投屏，本轮没有主动断开做恢复/重连回归。断开恢复复用已验的共享租约机制，但 G100 本机的断开恢复、异常断开和多轮重连仍待实测。声音、输入、锁屏和长时稳定性不随画面修复自动记为通过。


## 第二阶段：按实际窗口处理冲突，不按手机型号启用

用户明确要求规则通用，不能继续逐机型补名单。最终 `profiles/cast-adapters.json` 移除 X70 和本轮 G100 的 UI 适配项；固件 adapter 只保留原有 G100 S 的独立 legacy Qualcomm 例外，不将其旧 SELinux/编码配置逻辑扩大到其他固件。新的 `ui_rules` 描述两类已确认 Moto UI（包名、窗口标题前缀和类型），没有 device、build-id、接收端名称或地址条件。

公共流程是：Android 报告真实已连接的 WFD display → 当前外屏上的 Rungic overlay → WindowManager 记录的冲突窗口 → 包 UID 校验 → 原子租约与可恢复暂停。`CastWindows.java` 解析有超时和大小上限的 `dumpsys window windows`，要求同一非默认外屏、真实可见且有 Surface、窗口 owner 与 PackageManager UID 相符、已知标题/类型、base layer 高于 PlasmaCastDesktop。只有实际出现的冲突包才进入租约；不因安装了 Moto 软件就暂停它，不接管没有 Rungic 外屏窗口的普通 Android 投屏。

窗口观测不是稳定公开 API。解析字段缺失或未知时不匹配、不停包；新厂商的 UI 仍需依据实际窗口添加可复用规则，不能称为所有品牌已自动适配。继续复用标准显示框架、PackageManager 和共享后端，项目新 Java 为 MIT，无复制第三方代码。普通 overlay 无法覆盖关键系统层、Moto display flag 会覆盖关闭装饰请求的源码证据见前文和 86 篇；不改厂商 framework 或特权窗口类型。

既有 APK claim 继续兼容；resident watcher 每 2 秒在当前外屏检查后来出现的窗口，支持同一租约增量加入冲突包。改动前保存每个包精确原值及窗口证据；断开后恢复，跨 display/boot 的旧租约先恢复。状态增加 `ui_policy` 的模式、已处理包和窗口层级证据。原始窗口 dump 临时文件执行后删除，实机调查日志仍只在 `.work/`。

### 首个候选失败与修正

首个运行时候选只移除了任务栏，用户再次看到 Moto 欢迎页。`runtime-failed-windows.txt` 证明欢迎页确在同一外屏、layer 161000 高于 Linux 的 111000，包/UID/类型匹配。漏判来自新增的 `ApplicationInfo.FLAG_SYSTEM` 条件：`com.motorola.mobiledesktop` 位于 `/product/preinstall/MotoDesktop`，却没有 SYSTEM 标记。不能把工厂预装、系统权限窗口与 Android 的 SYSTEM 安装标志等同。

最终移除该错误前提，保留真实窗口 owner/UID、类型、可见性及层级核验。热更新仅替换载荷和 resident observer，保留当前 WFD 会话与编码配置挂载；随后的 claim 将实际出现的欢迎页增量加入同一租约。不是恢复机型名单或常驻停用包。

### 最终验收

- 最终 jar SHA-256 `454ff4356d08299bb1b063f66b71d0af02f3814de7bb4994b7dd8b88f2e123ed`，部署记录 `runtime-deploy-2/`，未重装 APK 2.20 或容器。Android 36 SDK 编译通过，16 项实际 Java 窗口匹配测试及 5 项既有首启安装测试通过。
- 首次候选连接 15.97 秒、display 5，仅任务栏处理成功，明确记为失败；修正后同一会话两个覆盖窗口均消失。
- 正常断开后，两包从 disabled-user 恢复到原 enabled=1，租约释放；随后 28.08 秒重新连接。此轮没有手动 claim，watcher 自动识别并处理欢迎页和任务栏。`runtime-final-status.json` 显示 **android-native** 与两个实际匹配证据，`runtime-final-window.txt` 无 Moto 覆盖窗口，`runtime-final-linux.png` 显示 Plasma 桌面。
- 最新一次协商为 **1280×720@60**（前一轮为 1920×1080@60），没有固定输出分辨率。显示模式随实际协商读取；本次只验证遮挡、租约和布局，不据此宣称画质/码率自适应已优化。
- 首次识别要等待窗口出现，故开始投屏时可能短暂露出 Moto UI；当前没有缓存固件/应用版本的预判结果，也没有证明零闪屏。未知厂商窗口、owner user 以外的多用户、异常重启、声音/输入/锁屏及长时稳定性仍另验。X70 旧窗口快照用于研究，未在本轮对 X70/G100 S 部署或重验。

## KScreen 缩放被布局间隙阻止

用户调整投屏 scale 时遇到 “Gaps between displays are not supported”。实际 `kscreen-doctor -j`：手机 1080×2400 / scale 3，逻辑宽 360、位置 (0,0)；外屏在 (416,0)，所以中间有 56 逻辑像素空隙。该错误是整个输出配置的校验失败，并非缩放倍率不支持。

核对本地固定 KScreen 6.6.5 源码：`kcm/kcm.cpp::checkConfig` 拒绝孤立输出，`kcm/output_model.cpp` 的 ScaleRole 已调用 `maintainSnapping` 按新旧逻辑尺寸调整相邻位置。上游页面本轮访问失败，结论依据配方固定并校验的本地源文件。已有空隙不会被该相对位移自动消除；初始 416 位置产生于哪次修改尚未定位，不能武断归因于本次用户操作。

通过标准 kscreen-doctor 将外屏位置调整到手机逻辑右边界 (360,0)，手机 300%、外屏 100% 保留。`layout-aligned.json` 与 `layout-after-reconnect.json` 证明重新连接后仍相接。未删除 KScreen 校验、未添加登录后强制布局脚本、未覆盖用户新倍率；已打开的设置页可能需重新进入以读取最新配置。GUI 再次修改倍率的操作验收与最初空隙来源尚未完成，不以位置修复代替它们。


### 后续断线观察（尚未定因）

18:58:58，已正常显示 Linux 的会话出现 `WifiHAL: Received fatal event` / `WifiVendorHal: onDebugErrorAlert 12`，紧接 P2P 对端离线、外屏移除与 WFD NETWORK_RUNTIME_ERROR。此时不是 Moto 窗口重新覆盖。watcher 在这次非本测试脚本发起的断开后释放租约，两包恢复 enabled=1；原始记录为 `later-logcat.txt`、`later-status.json`、`later-restored.txt`。尚未确认接收端/用户操作、Wi-Fi 驱动或环境因素，不把日志中的 fatal 一词直接当作已定位固件崩溃。后续一次连接未完成；投屏稳定性与重连失败仍是独立缺口，不能用 UI 处理通过替代。

补充离线解析验证：实际 X70 旧窗口快照识别 2 个冲突窗口，G100 漏判时快照识别 1 个仍存在的欢迎页；这验证解析器跨快照的行为，不等于对 X70 重新部署验收。


后续状态：诊断重连命令退出 143，同期有更新连接请求；未确定发起者，不自动归因于用户。最新快照 `latest-status.json` 已为 active_state=2、display 7，运行时规则再次自动识别两个覆盖包，说明此轮恢复后 UI 处理仍生效。断线根因尚未解决，不将恢复成功写成稳定性修复。

## 后续视频模式核验

[视频模式记录](miracast-video-modes.md)保存接收端真实 RTSP 回复及逐模式实验。本文前面的 `720/1080@60` 来自 Android/KScreen，表示显示刷新率，不能作为编码视频60fps的证据；后续抓包确认默认1080p30，再通过会话接口实测切换为1080p60。当前支持由共同能力生成选项，不使用 UGREEN 或 G100 模式名单。
