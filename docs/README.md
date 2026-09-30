# Rungic 开发者指南与文档索引

面向开发者：项目沿革、能力与实现文档的对照、仓库目录、开发入口和全部文档索引。产品介绍见[项目首页](../README.md)，工程约定见[AGENTS.md](../AGENTS.md)。

## 项目沿革

Rungic是运行在Android手机上的AgentOS：Ubuntu容器中的Plasma Mobile桌面，加上Android宿主、硬件桥和语音/桌面自动化代理。开发设备是Motorola moto g100s（XT2537-4 / Adreno710）。2026-09-26起项目改名为Rungic（原名Moto Android / Plasma Mobile），名称迁移见[70篇](70-rungic-rebrand.md)。当前维护Ubuntu 26.04 ARM64、Plasma Mobile 6.6系列，以及Android宿主、GPU、输入、网络和媒体桥。

2026-09-23按用户要求停止维护Phosh。共享媒体/网络/剪贴板实现保留在`shared/`；本次仅整理本地项目，没有卸载或更改手机中的系统。

## Agent能力与文档对照

Rungic的核心是系统级AI助理：用户用语音或文字交代任务，助理在Linux桌面上实际操作应用完成它，并让用户随时看到它在做什么。

| 能力 | 说明 | 文档 |
|---|---|---|
| 语音对话 | 长按Home呼出；GPT Realtime负责对话和语音播报，Codex在后台执行任务 | [59](59-voice-agent.md)、[67](67-home-assistant.md) |
| 看得见的工作 | 聊天式界面（“主对话”与其他对话）；任务计划清单、按步骤的语音播报、回答里直接展示图片和文件 | [87](87-agent-app-redesign.md)–[89](89-agent-progress.md) |
| 操作桌面应用 | 按无障碍树（AT-SPI）和虚拟输入操作控件；GPT-6 Luna看画面决定点哪里；手机GPU做OCR | [60](60-computer-use.md)、[64](64-goal-computer-use.md)、[68](68-luna-computer-use.md) |
| 助理屏（工作区） | 助理自己的桌面：独立KWin、私有D-Bus和无障碍总线、自己的Xwayland，显示在手机浮窗或电视上，不碰用户正在用的屏幕 | [65](65-agent-screen.md)、[research/91](research/91-agent-workspaces.md) |
| 工作位置 | 用户开着桌面模式或投屏时在用户桌面上工作，否则在助理屏；用户可以直接指定 | [research/91](research/91-agent-workspaces.md) |
| 单实例应用切换 | 微信、Telegram等按需切到助理屏；关闭用户正在用的实例前先征得同意 | [research/91](research/91-agent-workspaces.md) |
| 手机能力 | 亮度、剪贴板、方向、振动、网络与显示信息、Android设置面板（`rungic-platform`）；投屏、截图 | [59](59-voice-agent.md) |
| 通话与语音代发 | 替用户打电话、接电话；在聊天应用里发语音消息 | [63](63-call-proxy.md) |
| 主动建议 | 采集故障和软件适配问题，结合兼容性知识库在Folio主屏小组件里给出建议，用户委托后由助理调查和处理 | [主动建议](research/proactive-system-care.md) |
| 可改的指令 | 行为准则和技能放在用户目录（`~/.config/rungic-voice-agent/prompts`、`~/.codex/skills`），改动随时生效；需要密码或会改变结果的绕路先问用户 | [59](59-voice-agent.md) |
| 原生诊断 | 合并日志、崩溃符号化、证据快照、按控件操作，以MCP工具供开发Agent调用 | [55](55-agent-native-debugging.md) |

## 系统特性与文档对照

| 领域 | 特性 | 文档 |
|---|---|---|
| 底座 | Android 16上用LXC运行Ubuntu 26.04 ARM64（glibc），Magisk提供root；`~/Shared`即Android共享存储 | [38](38-plasma-mobile.md)、[40](40-plasma-mobile-integration.md)、[69](69-filesystem-capabilities.md) |
| 桌面 | 官方Plasma Mobile 6.6.5，KWin 6.6.6加Android宿主后端；Rime中文输入、录屏、边缘返回 | [40](40-plasma-mobile-integration.md)、[41](41-plasma-rime-input.md)、[72](72-kwin-android-host-isolation.md) |
| 显示 | 零拷贝呈现与显式同步、UBWC压缩输出；触摸时请求120Hz；原生分辨率与显示大小策略 | [49](49-plasma-performance.md)、[57](57-zero-copy-explicit-sync.md)、[85](85-phone-display-size-policy.md) |
| 第二块屏 | 桌面模式（完整桌面在手机浮窗里）；自研Miracast发送端投屏到电视，手机当触控板和键盘 | [65](65-agent-screen.md)、[66](66-pointer-gestures.md)、[84](84-miracast-source.md) |
| GPU | Mesa KGSL（freedreno GL/GLES、Turnip Vulkan 1.4）；X11应用经Xwayland的glamor和DRI3用GPU；Flatpak自带GL扩展，`--device=dri`带上KGSL | [51](51-plasma-vulkan-benchmark.md)、[research/93](research/93-xwayland-kgsl-gpu.md)、[research/94](research/94-mesa-base.md) |
| 音视频 | 系统级扬声器与麦克风；摄像头经libcamera/PipeWire；H.264/HEVC/VP9硬解、H.264硬编；屏幕共享portal | [48](48-plasma-media-pipelines.md)、[62](62-linux-virtual-audio.md) |
| 系统服务 | 双向剪贴板与剪贴板历史；Wi-Fi、蓝牙、蜂窝状态接Android；SSH自动开启；容器内rootless Docker | [83](83-service-policy.md)、[85](85-lxc-rootless-docker.md)、[剪贴板历史](research/clipboard-history.md) |
| 应用 | Firefox（WebGL、硬解视频）、Blender（Vulkan视口）、Krita 6、Telegram、VS Code、微信；Discover与`pkgcli`安装，系统弹密码框 | [36](36-firefox-input-fix.md)、[45](45-plasma-app-store.md)、[90](90-blender-vulkan-incident.md) |
| 交付 | 上游组件以固定版本加补丁队列维护；本地APT仓库与发布元包，部署后自动验收，按包回退 | [61](61-delivery-diagnostics-plan.md)、[71](71-upstream-patch-queue.md)、[73](73-reduce-upstream-changes.md) |
| 刷机包 | GKI、rootfs、一键包三段式构建；G100清数据刷入后进入Plasma，X70 Air Pro在接入中 | [75](75-image-build-separation.md)、[80](80-g100-image-installation-retrospective.md)、[83](83-x70-air-pro-onboarding.md) |

各项的验收边界以对应文档为准。已知限制：Turnip在KGSL上的Wayland呈现会闪屏，桌面仍用GLES（[56](56-kwin-vulkan-quantification.md)）；Mesa仍基于社区分支，换到上游的尝试已退回（[research/94](research/94-mesa-base.md)）。

## 工作区

| 目录 | 内容 |
|---|---|
| `plasma/` | KDE与Android APK适配、会话配置、构建脚本 |
| `native/plasma/` | Rust/Smithay原生Wayland后端 |
| `packages/` | 已迁为补丁队列的上游组件：固定上游来源加DEP-3补丁（[71篇](71-upstream-patch-queue.md)） |
| `vendor/` | 仍直接跟踪的外来树（`native/plasma/`、`plasma/firefox-mobile/`）的来源记录与审计豁免 |
| `shared/` | Linux媒体、网络、剪贴板与GPU公共接口 |
| `tools/` | 管理、ROM、构建辅助和诊断工具 |
| `kernel/`、`lxc/`、`cutout/` | 内核、容器与设备相关配置 |
| `docs/` | 实施文档；`research/`保留可复用历史结论 |
| `benchmarks/` | 已选定的性能原始数据与分析 |
| `provenance/` | 上游来源、版本和校验记录 |
| `signing/development/` | 按用户要求同步的开发APK签名身份 |
| `.work/` | 不同步的下载、依赖、缓存、日志、媒体、安装包和其他密钥 |

完整边界与迁移说明见[目录与Git范围](52-git-repository-scope.md)。远程为私有仓库[kevinzhow/RungicCore](https://github.com/kevinzhow/RungicCore)（2026-09-28由`kevinzhow/range-dev`改名），默认分支为`main`。文档包含本机身份和网络配置，未作为公开发行材料脱敏。

## 当前状态与入口

- 原厂Android16 + Magisk31，全局SELinux Enforcing；LXC已部署，Docker改在容器内以rootless运行（[85篇](85-lxc-rootless-docker.md)）。三段式刷机包已在G100清数据刷入验证（[80篇](80-g100-image-installation-retrospective.md)）。
- Plasma独立APK和Ubuntu容器已运行；原生1080×2400与30/60/90/120Hz/自动策略已接入。正式KWin继续使用GLES，Vulkan对照与限制见[51篇](51-plasma-vulkan-benchmark.md)，KWin原生Vulkan收益量化见[56篇](56-kwin-vulkan-quantification.md)。
- 媒体和显示尚有剩余验收项，以[48篇](48-plasma-media-pipelines.md)、[50篇](50-plasma-display-settings.md)为准，不把安装成功等同于完整验收。
- 设备管理：`python3 tools/rungic_plasma.py status`。开发环境：`source tools/work-env.sh`。APK构建：`bash plasma/build-apk.sh`，产物写入`.work/`。
- 图形和后端架构见[40篇](40-plasma-mobile-integration.md)及[共享桥说明](../shared/README.md)。全新机器构建仍需准备SDK/NDK及部分依赖。
- 远程源码核对和多机协作见[53篇](53-remote-system-development.md)。修改过的上游组件（KWin、Mesa、Xwayland、flatpak等）都在`packages/`中以补丁队列维护（`tools/pq.py`），构建用`tools/build_on_device.py`；只有`native/plasma/`、`plasma/firefox-mobile/`仍直接跟踪（[Vendor说明](../vendor/README.md)）。

Vendor适配应放在哪一层、哪些可以抽离到共享后端，见[54篇架构评审](54-vendor-adaptation-boundaries.md)。

系统交付、验收与诊断见[61篇](61-delivery-diagnostics-plan.md)：容器rootfs上本项目的文件都来自包（`plasma/packaging`、补丁队列与vendor重建包），经本地APT仓库与发布元包部署（`tools/rungic_release.py deploy|rollback|status`），部署后自动验收（`tools/rungic_acceptance.py`），`rungic-integrity`检查漂移。rootfs是ext4镜像（`plasma/rootfs-image`），部署前自动建dm-snapshot，验收失败即回到快照；`/home`、崩溃报告与本地仓库不随之回滚。

跨手机的 Android 系统镜像、RungicOS rootfs 和内核构建拆分方案，以及设备能力探测与发布门槛，见[75篇](75-image-build-separation.md)。

## 文档索引

01–21包含设备/ROM/容器历史；早期Phosh专属安装文档已移除。28–35保留共享接口研究，38以后记录Plasma适配。历史“当时已验证”的状态不代表当前所有功能已经验收。

| 文档 | 内容 |
|---|---|
| [01-device.md](01-device.md) | 设备身份 |
| [02-linux-feasibility.md](02-linux-feasibility.md) | 为什么不做成 Linux 发行版 |
| [03-gsi-dsu.md](03-gsi-dsu.md) | 官方 Android 17 GSI 与 DSU 试验 |
| [04-permanent-gsi.md](04-permanent-gsi.md) | 永久刷入 Android 17 GSI |
| [05-magisk-root.md](05-magisk-root.md) | Magisk root（init_boot） |
| [06-pitfalls.md](06-pitfalls.md) | 踩坑清单 |
| [07-restore-stock.md](07-restore-stock.md) | 回到官方 MYUI |
| [08-commands.md](08-commands.md) | 命令速查 |
| [09-stock-magisk.md](09-stock-magisk.md) | 原厂 MYUI + Magisk 可行性核验 |
| [10-stock-debloat.md](10-stock-debloat.md) | 原厂固件精简版：W1WAA36.48-23-10 |
| [11-stock-install.md](11-stock-install.md) | 原厂精简系统与 Magisk 实机安装记录 |
| [12-offline-magisk.md](12-offline-magisk.md) | 原厂精简包 v2：已弃用的系统应用方案 |
| [13-offline-magisk-user-app.md](13-offline-magisk-user-app.md) | Magisk 离线首启 v3：普通应用安装 |
| [14-oneclick-package.md](14-oneclick-package.md) | v3 一键完整重装包（差分封装） |
| [15-container-reassessment.md](15-container-reassessment.md) | Docker / LXC 重新评估（2026-09-22） |
| [16-lxc-prerequisites.md](16-lxc-prerequisites.md) | LXC 运行条件实测（2026-09-22） |
| [17-lxc-installation.md](17-lxc-installation.md) | LXC 实机部署与验证（2026-09-22） |
| [18-termux-lxc.md](18-termux-lxc.md) | 用 Termux 管理 LXC（2026-09-22） |
| [19-docker-installation.md](19-docker-installation.md) | 原厂 Android 16 上运行 Docker（2026-09-22；已由 85 篇的容器内 rootless Docker 取代并移除） |
| [20-docker-storage.md](20-docker-storage.md) | Docker 卷与手机共享存储（2026-09-22） |
| [21-memory-audit.md](21-memory-audit.md) | 原厂系统 RAM 占用实测（2026-09-22） |
| [28-capability-audit.md](research/28-capability-audit.md) | Phosh 日常使用能力与 Android 硬件接口审计 |
| [29-reuse-research.md](research/29-reuse-research.md) | Phosh 适配前的现有方案调研与复用判断 |
| [30-feature-adaptation.md](research/30-feature-adaptation.md) | Phosh 功能逐项适配记录 |
| [31-backend-integration.md](research/31-backend-integration.md) | Phosh 与 Android 后端的连接：架构、研究过程和维护方法 |
| [32-network-integration.md](research/32-network-integration.md) | Android 网络接入 GNOME / Phosh |
| [33-capture-integration.md](research/33-capture-integration.md) | 麦克风、相机、拍照和录像接入 |
| [34-hardware-codec-audit.md](research/34-hardware-codec-audit.md) | 硬件视频编码、解码：实机核验与接入候选 |
| [35-hardware-codec-integration.md](research/35-hardware-codec-integration.md) | Linux 应用和 Firefox 接入 Android 硬件编解码 |
| [74-vaapi-feasibility.md](research/74-vaapi-feasibility.md) | 编解码桥做成 VA-API 驱动的可行性（结论：不能替换现有补丁） |
| [36-firefox-input-fix.md](36-firefox-input-fix.md) | Firefox 地址栏输入崩溃修复 |
| [37-linux-distribution-evaluation.md](37-linux-distribution-evaluation.md) | Alpine、Debian、Ubuntu 的取舍与迁移边界 |
| [38-plasma-mobile.md](38-plasma-mobile.md) | 独立 Plasma Mobile 环境：版本目标、发行版选择与部署状态 |
| [39-magisk-daemon-crash.md](39-magisk-daemon-crash.md) | Magisk 31.0 守护进程退出调查 |
| [40-plasma-mobile-integration.md](40-plasma-mobile-integration.md) | Ubuntu Plasma Mobile：桌面与 Android 后端集成 |
| [41-plasma-rime-input.md](41-plasma-rime-input.md) | Plasma Mobile 的 Rime 中文输入 |
| [42-plasma-runtime-acceptance.md](42-plasma-runtime-acceptance.md) | Plasma Mobile 运行修复与验收 |
| [43-plasma-panel-workarea.md](43-plasma-panel-workarea.md) | Plasma 状态栏高度与应用避让 |
| [44-plasma-user-account.md](44-plasma-user-account.md) | 首次账户与密码设置 |
| [45-plasma-app-store.md](45-plasma-app-store.md) | Plasma Mobile 应用商店 |
| [46-plasma-recording-and-edge-back.md](46-plasma-recording-and-edge-back.md) | Plasma 录屏与 Android 边缘返回 |
| [47-plasma-input-window-flicker.md](47-plasma-input-window-flicker.md) | Plasma Mobile 输入时窗口上下闪动 |
| [48-plasma-media-pipelines.md](48-plasma-media-pipelines.md) | Plasma 媒体共享接口与质量验收 |
| [49-plasma-performance.md](49-plasma-performance.md) | Plasma 动画、列表帧率与 Android 调度 |
| [50-plasma-display-settings.md](50-plasma-display-settings.md) | KDE 显示设置与 Android 原生分辨率 |
| [51-plasma-vulkan-benchmark.md](51-plasma-vulkan-benchmark.md) | Plasma Vulkan 链路与性能对照 |
| [52-git-repository-scope.md](52-git-repository-scope.md) | 私有仓库与本地工作目录 |
| [55-agent-native-debugging.md](55-agent-native-debugging.md) | Agent 原生调试：统一采集、崩溃现场、统一追踪与按控件操作 |
| [56-kwin-vulkan-quantification.md](56-kwin-vulkan-quantification.md) | KWin + 原生 Vulkan 收益量化 |
| [57-zero-copy-explicit-sync.md](57-zero-copy-explicit-sync.md) | 零拷贝呈现与显式同步 |
| [58-miracast-desktop-feasibility.md](58-miracast-desktop-feasibility.md) | Miracast投屏桌面与手机触控板可行性 |
| [59-voice-agent.md](59-voice-agent.md) | 语音Agent：GPT Realtime驱动Codex |
| [60-computer-use.md](60-computer-use.md) | 电脑操作：arc-cua + JEV的Linux后端（rungic-cua） |
| [61-delivery-diagnostics-plan.md](61-delivery-diagnostics-plan.md) | 系统交付、验收与诊断：打包、发布、回滚、验收、崩溃链、rootfs快照 |
| [62-linux-virtual-audio.md](62-linux-virtual-audio.md) | Linux扬声器与Linux麦克风（系统级虚拟音频设备） |
| [63-call-proxy.md](63-call-proxy.md) | 通话代理：语音助手替用户打电话、接电话 |
| [64-goal-computer-use.md](64-goal-computer-use.md) | 目标级电脑操作：typesafe-computer-use + 手机GPU OCR |
| [65-agent-screen.md](65-agent-screen.md) | 助理屏：按需开启、浮窗与投屏互转的第二输出 |
| [66-pointer-gestures.md](66-pointer-gestures.md) | 指针手势与移动算法：直接触摸、触控板、电视 |
| [67-home-assistant.md](67-home-assistant.md) | 长按Home呼出语音助手 |
| [68-luna-computer-use.md](68-luna-computer-use.md) | GPT-6 Luna Computer Use（看画面决定点哪里） |
| [69-filesystem-capabilities.md](69-filesystem-capabilities.md) | 文件系统与容器能力审计 |
| [70-rungic-rebrand.md](70-rungic-rebrand.md) | Rungic（AgentOS）改名：命名规则、迁移调研、分阶段计划与进度 |
| [71-upstream-patch-queue.md](71-upstream-patch-queue.md) | 上游组件改为补丁队列：业界做法、目录与补丁规范、工具与测试分层、KWin试点 |
| [72-kwin-android-host-isolation.md](72-kwin-android-host-isolation.md) | KWin的Android宿主适配：协议化与独立后端（调研、目标结构、试点） |
| [73-reduce-upstream-changes.md](73-reduce-upstream-changes.md) | 减少对上游源码的修改：补丁队列收尾、扩展点与共享系统服务替代（总方案与进度） |
| [78-g100-firmware-inventory.md](78-g100-firmware-inventory.md) | XT2533-4 G100 原厂固件来源、提取与离线校验记录 |
| [75-image-build-separation.md](75-image-build-separation.md) | Android 固件、RungicOS rootfs、内核构建拆分与跨设备兼容契约 |
| [76-g100-memory-audit.md](76-g100-memory-audit.md) | XT2533-4 G100 当前 Android 内存占用的实机审计 |
| [77-g100-three-ci-assessment.md](77-g100-three-ci-assessment.md) | 通用三条镜像 CI、G100 首个设备 spec、runner 分工与缓存清理 |
| [79-g100-ci-execution.md](79-g100-ci-execution.md) | G100 三段镜像 CI 首轮执行记录 |
| [80-g100-image-installation-retrospective.md](80-g100-image-installation-retrospective.md) | G100 完整镜像实施复盘：遇到的问题与最佳解决路径 |
| [81-end-to-end-user-experience.md](81-end-to-end-user-experience.md) | Rungic 用户全流程 UX 审查与改进方案 |
| [82-first-run-ux-refactor.md](82-first-run-ux-refactor.md) | 首启 UX 重构：第一批实施 |
| [83-service-policy.md](83-service-policy.md) | 系统服务页与可选 SSH 登录 |
| [83-x70-air-pro-onboarding.md](83-x70-air-pro-onboarding.md) | X70 Air Pro / vantage 首轮接入 |
| [84-miracast-source.md](84-miracast-source.md) | 自研Miracast发送端：不依赖厂商投屏组件 |
| [85-lxc-rootless-docker.md](85-lxc-rootless-docker.md) | Plasma容器内的rootless Docker：试验记录与打包方案 |
| [85-phone-display-size-policy.md](85-phone-display-size-policy.md) | 手机显示大小策略与实现 |
| [86-x70-miracast-assessment.md](86-x70-miracast-assessment.md) | X70 Air Pro Miracast 完善评估 |
| [87-agent-app-redesign.md](87-agent-app-redesign.md) | Agent 助手第三版：聊天式界面与独立的设计系统库（2026-09-29） |
| [88-agent-visible-work.md](88-agent-visible-work.md) | Agent 的工作要让用户看得见：对话里的图片、助理屏字幕、手机能力（2026-09-29） |
| [89-agent-progress.md](89-agent-progress.md) | Agent 工作时的进度：任务状态、按事件的语音汇报、对话归属（2026-09-29） |
| [90-blender-vulkan-incident.md](90-blender-vulkan-incident.md) | Blender 渲染事故与默认 CPU 渲染（2026-09-29） |
| [91-agent-workspaces.md](research/91-agent-workspaces.md) | 工作空间：Agent 各自独立的 GUI 空间（方案，2026-09-29） |
| [92-agent-task-speed.md](research/92-agent-task-speed.md) | Agent 做 Blender 这类任务为什么慢，业界怎么提速（调研，2026-09-30） |
| [93-xwayland-kgsl-gpu.md](research/93-xwayland-kgsl-gpu.md) | X11 应用在 KGSL 上用 GPU：Xwayland 的几种做法（2026-09-30） |
| [94-mesa-base.md](research/94-mesa-base.md) | Mesa 的底座：lfdevs 分支，还是上游加我们自己的补丁（调研，2026-09-30） |
