# 手机显示大小策略与实现

2026-09-28。用户在分析后授权重构。当前最新策略是末节的 Android density 优先方案；下文保留前一版物理密度策略的研究和验收记录。源码研究、当前账户升级、无显示配置测试和整包清数据首装分别记录。

## 实施前核实的现状

- 实机 ZY22MHZKFT，ADB 5038：内屏 1264×2780，scale=3；设备报告面板约 72×157 mm，xdpi=445.9111、ydpi=449.75797。Android 基础逻辑密度 480，无 override。逻辑密度不能当作面板 PPI，也不能假定 Android dp 与 KDE 控件具有相同设计尺寸。
- 已装 kscreen `4:6.6.5-0ubuntu0.1`，kwin-wayland `4:6.6.6-0ubuntu0.1+rungic4`。本轮读取时另有 CAST-1 输出，未修改它。
- `plasma/kwin` 给初始输出传入短边/360；`rungic-migrate-display.py` 对旧配置写入 scale=3；KWin 又有自动配置及已有用户配置。启动参数不能代表最终生效值，不能再新增一个登录后反复覆盖设置的脚本。
- KScreen v6.6.5 `OutputPanel.qml` 的滑块/输入框上限为 300%/3；本轮检查 master 的同一文件仍为 300%。固定版 OutputModel 接收倍率，没有该 UI 上限；它的 `setResolution()` 改模式、逻辑尺寸及相邻输出布局，没有按旧/新渲染比例补偿缩放。
- KWin v6.6.6 `chooseScale()` 使用手机目标逻辑密度 150、最小逻辑尺寸 360、上限 3、5% 步进。以本机报告值算出的自动倍率本来就接近 3，单独移除上限不会自动得到 3.5。
- 项目 AndroidBackend 显式拒绝用户 scale>3。Wayland 输出管理接收的是 `scaleSetting`，按 1/120 量化，后续生成有效 scale；修复时须覆盖这两个字段的完整路径，不能只改一处判断。
- KWin 固定版配置读取只接受 `0 < scale <= 5`。因此“后端改为无上限”会与重启恢复冲突；本轮不建议突破该现有持久化范围。
- KScreen ConfigHandler 已将逐输出缩放变化纳入 `shouldTestNewSettings()`；复用现有应用/确认/还原，不另做第二套控制器。
- 现有 `display_scale_roundtrip` 只测试到 2.75 并读回，未覆盖 >3、GUI 倒计时、首装默认值、模式补偿、输入及持久化，不能沿用它宣称新策略已验收。

## 推荐的计算方法

以物理大小为主，逻辑布局为约束。对确定是手机内屏的输出计算：

```
渲染像素密度 = 当前渲染短边 / 对应面板短边英寸
推荐倍率 S0 = 渲染像素密度 / 目标逻辑密度 D0
用户倍率 S = S0 × 用户大小系数 U
逻辑尺寸 = 渲染尺寸 / S
```

`D0` 是需要用实际字体、控件和触摸体验校准的产品参数，不是硬件给出的唯一正确常数。候选手机参数可从约 128 逻辑像素/英寸开始（一个假设的 48 逻辑像素区域约 9.5 mm）；本机约 446/128≈3.48，UI 可取 350%。旧手机在相同物理密度/尺寸下可能需要其他倍率。约 360 的逻辑短边适合作为本机校验结果或尺寸数据缺失时的手机回退值，不能强制所有手机、折叠屏和平板拥有 360 宽。

取整区分用途：UI 手动调整可用 5% 或明确的大小档位；模式补偿按协议 1/120 量化，不能每切一次分辨率都按粗步进取整，造成往返漂移。上下限须在量化后重新验证。

物理尺寸按可靠的设备数据使用，核对宽高与旋转；无效/明显异常时使用设备 spec 中已验证的面板参数，仍不可得才用保守的手机布局回退值。Android 逻辑 density 仅作交叉参考，不把 480 当作约 446 的真实 PPI。本机毫米值目前来自设备报告，尚未尺量；目标 D0 与实际应用布局均待验收。

## 分层实现建议

### 1. 统一策略与单一配置写入者

把纯计算和策略参数集中维护，例如 `shared/display-policy/`，通过配方 overlay 给需要它的 KWin 与 KScreen 使用同一实现。输入为输出类型、当前渲染尺寸、有效物理尺寸与手机策略；返回推荐值、普通 UI 的建议范围和解释。设备特例/已验证物理参数来自 spec 安装的配置，不在两个组件里分别硬编码型号或倍率。

KWin 保持用户输出配置的唯一写入者；KScreen 仍通过 libkscreen 和标准输出管理提交完整配置。无需另起后台轮询服务、改每个应用或增加 Android 私有“设置缩放”通路。Android 继续提供实际面板/渲染状态并处理已有的渲染模式请求。

若需要保存跨模式的大小意图，在 KWin 对应输出的配置中增加可选的归一化大小参数与策略版本，保留现有有效 scale 字段兼容旧读者。普通重启恢复已保存大小；只在没有该字段时从旧模式、旧倍率和物理尺寸推导一次。默认策略升级不自动重算已有用户偏好。此处是拟议的数据模型，字段与插入点须在实现时通过现有配置克隆、持久化和回滚路径核验。

### 2. 首次默认值只在没有用户配置时生成

在 KWin 生成 Android 手机输出配置的位置接入统一推荐值；通用桌面/电视计算保持各自策略。启动包装器只负责启动所需初始尺寸，若必须传初始倍率则调用同一规则。旧固定 3 倍迁移限制为可确认的旧嵌套配置转换，不用于新账户，也不能凭 `scale==3` 推断为旧默认值并覆盖。

新账户显示元数据未就绪时，不把错误回退结果永久写为用户选择。首次有效配置和用户主动选择需要可区分；这与干净首装验收一起覆盖。

### 3. 普通 UI 提供显示大小，后台保留真实倍率

手机内屏显示“小／标准（推荐）／大”等档位，支持预览；不要把 350% 改写成未说明基准的“100%”。高级入口可展示真实倍率及当前逻辑工作区。用户旧值落在建议范围外时应显示“自定义”，打开设置不能悄悄夹到范围内。

普通范围从最小可读/可触摸尺寸和最小可用布局得到；它是 UX 范围，不能直接变成后端通用限制。例如本机把最小逻辑宽暂定 320 时，最大倍率为 1264/320=3.95；400% 仅 316 宽，需要另验，不能直接宣布可用。下限也必须依据真实控件校准，不能把旧 100% 或新的 300% 当作所有机型/模式通用下限。

后端校验独立保持有限、正数、协议和配置可恢复的技术范围，并核对实际逻辑尺寸有效；修复用户请求、系统恢复等路径的不一致。不得因为手机 UI 的建议范围而拒绝低分辨率渲染下的合理 2 倍或破坏外屏。

实现选型：

| 方案 | 结论 |
|---|---|
| 只把 UI/后端 3 改为 4 | 修改少，但默认值、跨模式尺寸、恢复不一致，不能完成此任务 |
| 给现有 KScreen/KWin 加范围明确的策略补丁 | 推荐，复用显示模型、标准协议、应用/还原及多屏布局 |
| 新建完整 Rungic 显示 KCM | 本轮不选，会重复输出枚举、热插拔、确认/回滚、多屏等现成能力 |
| 设置 QT_SCALE_FACTOR、字体 DPI 或逐个应用放大 | 本轮不选，不能统一 Wayland 输出、GTK/Qt、触摸和外屏 |

73 篇已将 kscreen 恢复为 Ubuntu 原包。本方案若采用 KScreen UI 修改，需要重新建立 `packages/kscreen/` 的固定来源＋小型补丁队列；不恢复旧 Android 显示控制补丁，不直接修改手机上的 QML，不声称没有新增维护成本。KWin 修改仍放现有 Android 后端及必要的有限配置扩展点，避免改掉所有设备的自动缩放规则。

### 4. 分辨率、缩放和布局作为同一次配置变更

用户从原生渲染切换到 720 短边时保持大小意图：`S_new = S_old × 新渲染短边 / 旧渲染短边`。例如原生 350% 对应约 199.4%，协议量化后接近 2 倍，而非仍保持 3.5。完整配置包含模式、有效倍率和相邻输出位置，在预览、应用、确认或撤回中一起处理。

KScreen 应在预览阶段便计算出同一结果，让其已有布局与倒计时机制作用于正确的整体配置；KWin Android 后端也要处理宿主自行改变渲染尺寸/恢复旧模式的路径。只改变刷新率或旋转时，不重算用户大小。投屏输出各自保存，不按 `screens[0]` 或当前主屏判断手机；本机当前有 CAST-1，需覆盖同时在线的情况。

Android Surface 尺寸改变与 Linux 配置提交跨进程，不能仅因两项放在一次请求就宣称物理生效原子化。实现时核对宿主实际尺寸确认与失败行为；失败/超时恢复旧模式、倍率和位置，KScreen 还原也必须让 Android 的渲染偏好一起恢复，不留下“下次启动又变回新分辨率”的半完成状态。

## 落地顺序和验收

1. 写统一计算与配置迁移的边界测试，确定大小意图的数据模型。覆盖 1080/1264/1440、720 渲染、旋转、无效尺寸、已选自定义值、外屏与取整往返。
2. 实现 KWin 默认/应用/保存/恢复，再实现 KScreen 的手机 UI 和模式补偿；同时移除固定 3 倍的多头默认。用 `tools/pq.py prepare/export` 维护补丁。
3. 实机做 GUI 大小变化与倒计时撤回，读回 KScreen、Qt/GTK 的逻辑坐标；验证文字、触摸、挖孔、状态栏、键盘、对话框和横竖屏，至少跨 Qt/GTK 应用。不涉及摄像头。
4. 原生↔720 多次切换与撤回，大小不漂移；重开 APK、重开会话、重启后保持用户选择；带外屏时各屏大小及位置正确。异常请求、宿主拒绝/超时不能留下半配置。
5. 单独验证空 home/无显示配置的首启，以及已有用户配置升级。临时修好当前账户不代替整包清数据首装验收，也不为此直接清除当前用户数据。

## 来源与证据边界

- KDE [KScreen v6.6.5 OutputPanel.qml](https://github.com/KDE/kscreen/blob/v6.6.5/kcm/ui/OutputPanel.qml)、[OutputModel](https://github.com/KDE/kscreen/blob/v6.6.5/kcm/output_model.cpp)、[ConfigHandler](https://github.com/KDE/kscreen/blob/v6.6.5/kcm/config_handler.cpp)，GPL-2.0-or-later。
- KDE [KWin v6.6.6 配置存储](https://github.com/KDE/kwin/blob/v6.6.6/src/outputconfigurationstore.cpp)、[输出管理](https://github.com/KDE/kwin/blob/v6.6.6/src/wayland/outputmanagement_v2.cpp)，GPL-2.0-or-later。已下载固定 tag 对应的实际源码；实现前仍按项目 recipe 验证带发行版和 Rungic 补丁的最终树。
- Android [密度与 dp](https://developer.android.com/training/multiscreen/screendensities)。产品策略是本项目建议，不能称为 Android 或 KDE 的规定。
- 固定版源文件保存在 `.work/ci/runs/vantage-20260928-onboarding/research/display-scale/`；实机只读输出在该 run 的 `device/display-policy-current.json.txt`、`display-density-investigation.txt` 和 `display-scale-investigation.log`。
- 本轮检索未找到可直接替代上述整条链路的已核实方案；不据此宣称其他项目不存在实现。master 的 UI 仍有上限也不代表所有分支/待合并修改都已审计。


## 已实现的公共链路（2026-09-28）

`KScreen / 标准输出管理客户端 → libkscreen → KWin AndroidOutput → Android 显示宿主`。纯计算集中在 `shared/display-policy/handset-scale.h`，Qt 配置/身份适配在同目录 `handset-scale-qt.h`，通过 recipe overlay 同时进入 KWin 和 KScreen。配置 `/etc/xdg/rungic-display-policyrc` 采用目标 128、紧凑 150 逻辑像素/英寸、最小逻辑短边 320、无效面板数据回退短边 360。当前仍用设备报告的毫米值，没有把报告值称为尺量结果，也尚未加入新的 spec 面板毫米覆盖入口。

- KWin 保持输出配置写入者；Android 内屏通过标准 manufacturer=`Rungic`、model=`Handset` 标识。外屏沿用原策略。启动包装器只传 bootstrap scale=1；KWin 在生成输出配置时计算首次默认值。删除旧固定 scale=3 的 KConfig 迁移，不凭已有 3 倍判断用户是否选过。
- KWin `kwinoutputconfig.json` 增加可选 `logicalDpi`，保留原 mode/scale。已有配置根据旧模式、倍率和面板信息推导该字段。该值保持未取整，只有有效倍率按 1/120 量化；这样改变渲染尺寸不改变用户大小意图。当前字段代表明确的密度语义，没有额外策略版本字段；默认策略变更不会重算已有偏好。
- KScreen 重新建立固定 Ubuntu 6.6.5 来源的补丁队列，复用原配置模型、布局、应用/确认/倒计时恢复。手机显示五档大小，已有范围外值标为自定义；高级设置展示真实倍率，技术范围 50–500%。未重新引入 Android 私有 KCM 控制通路。
- 五档先按原生分辨率计算，再映射当前渲染模式。在 X70 Air Pro 原生模式为 300/325/350/375/395%；350% 的逻辑工作区约 361×794。720 模式的“标准”约 199.17%，仍约 362×795，不能把低分辨率的 200% 误当作另一种大小。
- KScreen 预览补偿 scale 和布局；KWin 同时处理 mode-only 客户端和宿主尺寸恢复。用户请求与系统恢复都校验倍率，技术范围与配置读取一致。宿主拒绝、回复缺失或尺寸不匹配时发送旧模式/刷新策略补偿并返回失败；若宿主已死亡，补偿仍可能失败，不能保证跨进程物理事务原子性。
- 刷新策略与大小分离：分辨率或 scale 变更不把动态 Hz 当成固定刷新率意图；显式 KScreen 选 Hz 会选择 Never/固定策略。显式 VRR 策略优先，后台自动刷新继续由 Android 决定。
- 状态栏安全区域通过 Qt 的同一 manufacturer/model 查手机内屏，不再取 `screens[0]`；切换主屏不应把手机挖孔应用到外屏。

最终候选包：KWin `4:6.6.6-0ubuntu0.1+rungic7`、KScreen `4:6.6.5-0ubuntu0.1+rungic4`、会话 `0.314`、配置 `0.308`，APT release `20260928.6`。Linux 上游补丁按 `tools/pq.py prepare/export` 维护，来源/哈希/许可证在各 recipe。构建使用 Mac mini ARM64 Ubuntu，增量同步改为 checksum 判断内容并保留未变文件的目标 mtime，避免 quilt 重生成时间戳触发全量编译；新增/变化内容仍同步。二进制构建成功；缺源包 `.dsc` 的打包 lintian 钩子未完成，不称为 lintian 通过。

## 实机证据与边界

仅操作 ADB 5038 / `ZY22MHZKFT`，未清除账户、未测试摄像头。证据目录 `.work/ci/runs/vantage-20260928-onboarding/device/`，安装前保存显示配置和旧 Debian 包以便恢复。实机脚本及原始 JSON 均留在该 run，不跟踪设备数据到 Git。

- 离线 `tools/test_display_policy.py` 编译实际生产头文件，覆盖原生/720、旋转、无效尺寸、边界及自定义值，48,100 次往返保存密度不漂移；两组件补丁队列 lint 通过。
- 已有用户从原版本升级保留 300%；GUI 实际点选“标准”得到 350%，15 秒未确认回到 300%，再次点击 Keep 后保持 350%。此前一次人工与脚本混合操作中读到未恢复，受控重测成功，未据此添加未经定位的回滚补丁。证据 `display-gui-timeout-trace.json`、`display-gui-result.json`。
- 原生↔720 三轮读回 scale=3.5↔1.9916666667、未取整 logicalDpi 一致；非法 6 倍请求未写入。测试发现渲染模式切换会误选固定刷新率，修复后另以 automatic 初值重测。随后 GUI 测试又发现旧 Hz 随 scale 提交的同类问题，最终 rungic7/kscreen4 修复该分支。
- 会话重启保留已有 350%；只临时移开 `kwinoutputconfig.json` 后重新生成默认值为 350%，再恢复原配置。证据 `display-default-test.json`。这是当前账户无显示配置测试，**不等同于新账户、整包清数据首装或整机重启验收**。
- 后续实机补充结果记录在本节末；未完成的物理电视、宿主断线/拒绝故障注入和所有应用 395% 布局均不宣称通过。395% 是 320 逻辑宽约束给出的候选上界，目标 128 DPI 也仍可依据真实触摸体验调整。


最终 `20260928.6` 安装后补测通过：

- GUI 自动倒计时恢复/Keep 再跑一次，逐次读回 VRR policy=2（automatic），未再改成固定 Hz；原生↔720 三轮、非法 6 倍拒绝也以 automatic 初值重跑，见 `display-refactor-final-roundtrip.json`。
- 助理输出 CAST-1 1920×1080、scale=1 在线时调整手机 300↔350%，外屏 scale 保持 1；将 CAST-1 临时设为主屏，手机 panel 高度配置保持不变，Qt 正确标识手机内屏。最后关闭本轮临时输出。见 `display-external-test.json`。这是宿主第二输出验收，不是物理电视连接验收。
- 独立 GTK4 探针与 Qt 均报告手机逻辑 361×794；GTK 的整数缓冲 scale_factor=4 不等同于输出的 3.5 倍，逻辑坐标一致。通过真实 Android 触摸注入点击 GTK 按钮，再触摸输入框并输入 `display-test`，Gtk.Entry 实际内容回读正确；见 `display-gtk-result.json`、`display-gtk-touch-keyboard-350.png`。Qt 则通过实际 KScreen 设置应用和 GUI 点击交叉覆盖。没有把测试探针称为所有 GTK 应用或键盘完整布局验收。
- 最后恢复用户原来的 300% 和 automatic，重开会话再次读回 scale=3、policy=2，dpkg audit 为空；辅助无障碍恢复关闭。见 `display-final-state.json`、`display-final-restored-300.png`。


## 第二轮：Android density 优先的首次默认值（2026-09-28）

用户认可方案比较后授权实施。APK 2.10 / versionCode 58 在既有 `android-display.json` version 1 中添加 `densityDpi`、`densityWidthPixels`、`densityHeightPixels`。Android 14+ 从同一个 `WindowManager.getMaximumWindowMetrics()` 快照取 density 和参考像素范围；API 30–33 回退既有 `Display.getRealMetrics()`。参考值描述显示区域，不取 720 Surface 的缓冲宽度，不乘 fontScale；`physicalWidth/Height` 和毫米字段保留兼容。

共享 `AndroidReference` 校验有限、合理范围；缺字段、旧 APK 或异常值回退前一版物理尺寸计算。KWin 和 KScreen 都通过共享 Qt helper 只读同一原子元数据文件，设置请求仍走 libkscreen/Wayland 输出管理，没有新增 Android 私有控制器。

计算先落到原生渲染模式，再映射到当前渲染分辨率：

```
候选倍率 = densityDpi / 160 × 原生渲染短边 / density参考短边 × AndroidSizeMultiplier
默认上限 = 原生渲染短边 / MinimumDefaultLogicalEdge
```

默认 `AndroidSizeMultiplier=1.25`、`MinimumDefaultLogicalEdge=360`。原生推荐按 5% 步进选择，上限向下取整；映射当前模式后按 1/120 量化，并重新核对推荐值不能跨过 360 的约束。1.25 是待跨设备校准的产品参数；1080@390 的 300% 已触及布局上限，不能据此独立拟合 k。原 `MinimumLogicalEdge=320` 只用于用户主动选择的较大档位，不代表默认布局保证或所有应用已经验收。

这是**首次默认值及显式“标准”选择**的策略，不新增持续跟随 Android 的自动模式。已有输出配置及未取整 logicalDpi 保持，Android density 改变不会重算用户选择。Android 有效元数据下，紧凑档以未乘 k 的 Android 倍率为参考；外屏仍按独立输出处理。

来源与选择：

- Android 官方 [Display.getRealMetrics](https://developer.android.com/reference/android/view/Display#getRealMetrics(android.util.DisplayMetrics)) 明确说明 API 31 已废弃，也明确区分真实显示区域、窗口区域、折叠屏分区和 `wm size` 模拟尺寸；因此新 Android 采用 WindowMetrics 快照，并保留旧 API 兼容路径。
- Android [WindowMetrics](https://developer.android.com/reference/android/view/WindowMetrics)、[DisplayMetrics.density](https://developer.android.com/reference/android/util/DisplayMetrics#density)、[Configuration.densityDpi](https://developer.android.com/reference/android/content/res/Configuration#densityDpi) 核对逻辑密度与字体缩放的区别。沿用公开框架接口；未引入第三方实现或许可证依赖。
- KWin 6.6.6 上游 `chooseScale()` 的手机自动配置使用 minSize=360。这是默认选值依据，不推断为所有 Plasma Mobile 应用的硬性最低宽度。现有补丁队列和标准输出管理链继续复用；无需重写显示 KCM。

离线测试在生产 C++ 头文件上覆盖 1080@390、1264@480、1440@560、1440@480、720@320、1600@320 的计算，另测不一致的面板 PPI、Android 系统分辨率参考、无效元数据、1281 种宽度的取整约束及原有 48,100 次偏好往返。样例结果不能写成对应实机验收。

实机固定 ADB 5038 / ZY22MHZKFT：

- 更新 APK 和 Linux 包后，已有 scale=3、automatic 保留；APK 实际发布 density=480、参考 1264×2780。
- 先等待旧 KWin 真正退出，再临时移开输出配置：480 密度首次推荐 3.5；改变 Android density 为 320 后已有 3.5 保留；再移开配置得到 2.5，KScreen 的“标准”档也匹配 2.5。
- 在 Android density=320、720 渲染下，倍率为 1.425；再次移开显示配置仍生成 1.425，证明不会把 Surface 短边重复当作 density 参考。最后恢复 Android density（无 override）、原生渲染和原显示配置（3 倍、automatic）。
- 首次测试只等待外层 session service 停止，旧 KWin 的 logind scope 尚未结束便移除了配置，得到旧值；短时间多次重启另触发 StartLimit。恢复桌面后修订**测试脚本**，等待 KWin 进程完全退出并清理测试触发的 start-limit 后重测；未用固定延时改产品默认算法。

版本：KWin rungic8、KScreen rungic5、配置 0.319、会话保持 0.314，APT release `20260928.7`。APK native 源码未变，三份 ARM64 库从已验证 2.9 APK 复用并逐一 SHA-256 核对；2.10 APK SHA-256 `e30f3e802b5047ab77c54c072f56cd9cf4d10ab357c5982641be255e6b749fc5`。二进制构建通过；与此前相同的缺少源包 `.dsc` 打包 lintian 钩子仍未验收。

本轮证据目录 `.work/ci/runs/vantage-20260928-density/`，核心为 `device/after-install.json`、`device/density-default-test.json`、`device/density320-standard250.png`，原始失败日志单独保留。新账号/整包清数据首装、第二台真实设备以及 API 30–33 回退路径仍需独立实机验收。

补充回归：新版本设置页的超时撤回和 Keep 保存通过；原生↔720 三轮保持 3.5↔1.9916666667，未取整 logicalDpi 不变，6 倍请求被拒绝。测试最初缓存了自动刷新率变化前的 mode ID；按实时分辨率和刷新率重新解析后通过，保留首轮失败日志。KScreen 的 VRR 枚举检查不能代替宿主策略检查：测试结束时枚举为 automatic，但宿主曾保留 90；显式切换 Never→Automatic 后回读宿主 refreshPolicy=0。未将此项称为所有刷新策略同步路径均通过，后续需单独定位客户端重复提交相同策略的边界。

最终 `device/final-state.json` 同时核对 Android density=480（无 override）、1264×2780、scale=3、KScreen vrrPolicy=2、宿主 refreshPolicy=0、无障碍关闭和 dpkg audit 为空。GUI 与往返日志分别为 `device/display-gui-test.log`、`device/display-roundtrip.log`；未清数据。

进一步回读原始证据：`device/before.json` 和 `after-install.json` 的宿主 refreshPolicy 都是 120，故枚举与宿主策略不一致在本轮 density 更新前已存在。不能把此前仅检查 KScreen 枚举的“自动刷新通过”推广成宿主策略通过。新增 `device/host-refresh-test.json` 从明确的宿主自动状态出发，逐步检查 300→350%、原生→720→原生及恢复 300%；每步 KScreen vrrPolicy=2 且宿主 refreshPolicy=0。该缩放路径通过，既有不一致的形成原因未据此认定已修复。

交付候选为 `.work/ci/runs/vantage-20260928-density/release/vantage-20260928.3/`，APK 2.10 / APT 20260928.7；84 项 manifest 文件及设备 spec 离线校验通过。此包尚未清数据首装，详细摘要、归档和清理见 83 篇。
