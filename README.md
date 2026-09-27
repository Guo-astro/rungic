# Rungic

Rungic是运行在Android手机上的AgentOS：Ubuntu容器中的Plasma Mobile桌面，加上Android宿主、硬件桥和语音/桌面自动化代理。开发设备是Motorola moto g100s（XT2537-4 / Adreno710）。2026-09-26起项目改名为Rungic（原名Moto Android / Plasma Mobile），名称迁移见[70篇](docs/70-rungic-rebrand.md)。当前维护Ubuntu 26.04 ARM64、Plasma Mobile 6.6系列，以及Android宿主、GPU、输入、网络和媒体桥。

2026-09-23按用户要求停止维护Phosh。共享媒体/网络/剪贴板实现保留在`shared/`；本次仅整理本地项目，没有卸载或更改手机中的系统。

## 工作区

| 目录 | 内容 |
|---|---|
| `plasma/` | KDE与Android APK适配、会话配置、构建脚本 |
| `native/plasma/` | Rust/Smithay原生Wayland后端 |
| `packages/` | 已迁为补丁队列的上游组件：固定上游来源加DEP-3补丁（[71篇](docs/71-upstream-patch-queue.md)） |
| `vendor/` | 尚未迁移的上游组件（Mesa、Qt、libcamera等）的完整源码，已包含本机适配 |
| `shared/` | Linux媒体、网络、剪贴板与GPU公共接口 |
| `tools/` | 管理、ROM、构建辅助和诊断工具 |
| `kernel/`、`lxc/`、`docker/`、`cutout/` | 内核、容器与设备相关配置 |
| `docs/` | 实施文档；`research/`保留可复用历史结论 |
| `benchmarks/` | 已选定的性能原始数据与分析 |
| `provenance/` | 上游来源、版本和校验记录 |
| `signing/development/` | 按用户要求同步的开发APK签名身份 |
| `.work/` | 不同步的下载、依赖、缓存、日志、媒体、安装包和其他密钥 |

完整边界与迁移说明见[目录与Git范围](docs/52-git-repository-scope.md)。远程为私有仓库[kevinzhow/range-dev](https://github.com/kevinzhow/range-dev)，默认分支为`main`。文档包含本机身份和网络配置，未作为公开发行材料脱敏。

## 当前状态与入口

- 原厂Android16 + Magisk31，全局SELinux Enforcing；LXC与Docker已部署。历史v3完整刷机包尚未整合当前全部容器/桌面修改。
- Plasma独立APK和Ubuntu容器已运行；原生1080×2400与30/60/90/120Hz/自动策略已接入。正式KWin继续使用GLES，Vulkan对照与限制见[51篇](docs/51-plasma-vulkan-benchmark.md)，KWin原生Vulkan收益量化见[56篇](docs/56-kwin-vulkan-quantification.md)。
- 媒体和显示尚有剩余验收项，以[48篇](docs/48-plasma-media-pipelines.md)、[50篇](docs/50-plasma-display-settings.md)为准，不把安装成功等同于完整验收。
- 设备管理：`python3 tools/rungic_plasma.py status`。开发环境：`source tools/work-env.sh`。APK构建：`bash plasma/build-apk.sh`，产物写入`.work/`。
- 图形和后端架构见[40篇](docs/40-plasma-mobile-integration.md)及[共享桥说明](shared/README.md)。全新机器构建仍需准备SDK/NDK及部分依赖。
- 远程源码核对和多机协作见[53篇](docs/53-remote-system-development.md)。已迁移的上游组件在`packages/`中以补丁队列维护（`tools/pq.py`），其余组件直接修改[Vendor源码](vendor/README.md)；历史patch不再重复应用。

Vendor适配应放在哪一层、哪些可以抽离到共享后端，见[54篇架构评审](docs/54-vendor-adaptation-boundaries.md)。

系统交付、验收与诊断见[61篇](docs/61-delivery-diagnostics-plan.md)：容器rootfs上本项目的文件都来自包（`plasma/packaging`、补丁队列与vendor重建包），经本地APT仓库与发布元包部署（`tools/rungic_release.py deploy|rollback|status`），部署后自动验收（`tools/rungic_acceptance.py`），`rungic-integrity`检查漂移。rootfs是ext4镜像（`plasma/rootfs-image`），部署前自动建dm-snapshot，验收失败即回到快照；`/home`、崩溃报告与本地仓库不随之回滚。

## 文档索引

01–21包含设备/ROM/容器历史；早期Phosh专属安装文档已移除。28–35保留共享接口研究，38以后记录Plasma适配。历史“当时已验证”的状态不代表当前所有功能已经验收。

| 文档 | 内容 |
|---|---|
| [01-device.md](docs/01-device.md) | 设备身份 |
| [02-linux-feasibility.md](docs/02-linux-feasibility.md) | 为什么不做成 Linux 发行版 |
| [03-gsi-dsu.md](docs/03-gsi-dsu.md) | 官方 Android 17 GSI 与 DSU 试验 |
| [04-permanent-gsi.md](docs/04-permanent-gsi.md) | 永久刷入 Android 17 GSI |
| [05-magisk-root.md](docs/05-magisk-root.md) | Magisk root（init_boot） |
| [06-pitfalls.md](docs/06-pitfalls.md) | 踩坑清单 |
| [07-restore-stock.md](docs/07-restore-stock.md) | 回到官方 MYUI |
| [08-commands.md](docs/08-commands.md) | 命令速查 |
| [09-stock-magisk.md](docs/09-stock-magisk.md) | 原厂 MYUI + Magisk 可行性核验 |
| [10-stock-debloat.md](docs/10-stock-debloat.md) | 原厂固件精简版：W1WAA36.48-23-10 |
| [11-stock-install.md](docs/11-stock-install.md) | 原厂精简系统与 Magisk 实机安装记录 |
| [12-offline-magisk.md](docs/12-offline-magisk.md) | 原厂精简包 v2：已弃用的系统应用方案 |
| [13-offline-magisk-user-app.md](docs/13-offline-magisk-user-app.md) | Magisk 离线首启 v3：普通应用安装 |
| [14-oneclick-package.md](docs/14-oneclick-package.md) | v3 一键完整重装包（差分封装） |
| [15-container-reassessment.md](docs/15-container-reassessment.md) | Docker / LXC 重新评估（2026-09-22） |
| [16-lxc-prerequisites.md](docs/16-lxc-prerequisites.md) | LXC 运行条件实测（2026-09-22） |
| [17-lxc-installation.md](docs/17-lxc-installation.md) | LXC 实机部署与验证（2026-09-22） |
| [18-termux-lxc.md](docs/18-termux-lxc.md) | 用 Termux 管理 LXC（2026-09-22） |
| [19-docker-installation.md](docs/19-docker-installation.md) | 原厂 Android 16 上运行 Docker（2026-09-22） |
| [20-docker-storage.md](docs/20-docker-storage.md) | Docker 卷与手机共享存储（2026-09-22） |
| [21-memory-audit.md](docs/21-memory-audit.md) | 原厂系统 RAM 占用实测（2026-09-22） |
| [28-capability-audit.md](docs/research/28-capability-audit.md) | Phosh 日常使用能力与 Android 硬件接口审计 |
| [29-reuse-research.md](docs/research/29-reuse-research.md) | Phosh 适配前的现有方案调研与复用判断 |
| [30-feature-adaptation.md](docs/research/30-feature-adaptation.md) | Phosh 功能逐项适配记录 |
| [31-backend-integration.md](docs/research/31-backend-integration.md) | Phosh 与 Android 后端的连接：架构、研究过程和维护方法 |
| [32-network-integration.md](docs/research/32-network-integration.md) | Android 网络接入 GNOME / Phosh |
| [33-capture-integration.md](docs/research/33-capture-integration.md) | 麦克风、相机、拍照和录像接入 |
| [34-hardware-codec-audit.md](docs/research/34-hardware-codec-audit.md) | 硬件视频编码、解码：实机核验与接入候选 |
| [35-hardware-codec-integration.md](docs/research/35-hardware-codec-integration.md) | Linux 应用和 Firefox 接入 Android 硬件编解码 |
| [74-vaapi-feasibility.md](docs/research/74-vaapi-feasibility.md) | 编解码桥做成 VA-API 驱动的可行性（结论：不能替换现有补丁） |
| [36-firefox-input-fix.md](docs/36-firefox-input-fix.md) | Firefox 地址栏输入崩溃修复 |
| [37-linux-distribution-evaluation.md](docs/37-linux-distribution-evaluation.md) | Alpine、Debian、Ubuntu 的取舍与迁移边界 |
| [38-plasma-mobile.md](docs/38-plasma-mobile.md) | 独立 Plasma Mobile 环境：版本目标、发行版选择与部署状态 |
| [39-magisk-daemon-crash.md](docs/39-magisk-daemon-crash.md) | Magisk 31.0 守护进程退出调查 |
| [40-plasma-mobile-integration.md](docs/40-plasma-mobile-integration.md) | Ubuntu Plasma Mobile：桌面与 Android 后端集成 |
| [41-plasma-rime-input.md](docs/41-plasma-rime-input.md) | Plasma Mobile 的 Rime 中文输入 |
| [42-plasma-runtime-acceptance.md](docs/42-plasma-runtime-acceptance.md) | Plasma Mobile 运行修复与验收 |
| [43-plasma-panel-workarea.md](docs/43-plasma-panel-workarea.md) | Plasma 状态栏高度与应用避让 |
| [44-plasma-user-account.md](docs/44-plasma-user-account.md) | 首次账户与密码设置 |
| [45-plasma-app-store.md](docs/45-plasma-app-store.md) | Plasma Mobile 应用商店 |
| [46-plasma-recording-and-edge-back.md](docs/46-plasma-recording-and-edge-back.md) | Plasma 录屏与 Android 边缘返回 |
| [47-plasma-input-window-flicker.md](docs/47-plasma-input-window-flicker.md) | Plasma Mobile 输入时窗口上下闪动 |
| [48-plasma-media-pipelines.md](docs/48-plasma-media-pipelines.md) | Plasma 媒体共享接口与质量验收 |
| [49-plasma-performance.md](docs/49-plasma-performance.md) | Plasma 动画、列表帧率与 Android 调度 |
| [50-plasma-display-settings.md](docs/50-plasma-display-settings.md) | KDE 显示设置与 Android 原生分辨率 |
| [51-plasma-vulkan-benchmark.md](docs/51-plasma-vulkan-benchmark.md) | Plasma Vulkan 链路与性能对照 |
| [52-git-repository-scope.md](docs/52-git-repository-scope.md) | 私有仓库与本地工作目录 |
| [55-agent-native-debugging.md](docs/55-agent-native-debugging.md) | Agent 原生调试：统一采集、崩溃现场、统一追踪与按控件操作 |
| [56-kwin-vulkan-quantification.md](docs/56-kwin-vulkan-quantification.md) | KWin + 原生 Vulkan 收益量化 |
| [57-zero-copy-explicit-sync.md](docs/57-zero-copy-explicit-sync.md) | 零拷贝呈现与显式同步 |
| [58-miracast-desktop-feasibility.md](docs/58-miracast-desktop-feasibility.md) | Miracast投屏桌面与手机触控板可行性 |
| [59-voice-agent.md](docs/59-voice-agent.md) | 语音Agent：GPT Realtime驱动Codex |
| [60-computer-use.md](docs/60-computer-use.md) | 电脑操作：arc-cua + JEV的Linux后端（rungic-cua） |
| [61-delivery-diagnostics-plan.md](docs/61-delivery-diagnostics-plan.md) | 系统交付、验收与诊断：打包、发布、回滚、验收、崩溃链、rootfs快照 |
| [62-linux-virtual-audio.md](docs/62-linux-virtual-audio.md) | Linux扬声器与Linux麦克风（系统级虚拟音频设备） |
| [63-call-proxy.md](docs/63-call-proxy.md) | 通话代理：语音助手替用户打电话、接电话 |
| [64-goal-computer-use.md](docs/64-goal-computer-use.md) | 目标级电脑操作：typesafe-computer-use + 手机GPU OCR |
| [65-agent-screen.md](docs/65-agent-screen.md) | 助理屏：按需开启、浮窗与投屏互转的第二输出 |
| [66-pointer-gestures.md](docs/66-pointer-gestures.md) | 指针手势与移动算法：直接触摸、触控板、电视 |
| [67-home-assistant.md](docs/67-home-assistant.md) | 长按Home呼出语音助手 |
| [68-luna-computer-use.md](docs/68-luna-computer-use.md) | GPT-6 Luna Computer Use（看画面决定点哪里） |
| [69-filesystem-capabilities.md](docs/69-filesystem-capabilities.md) | 文件系统与容器能力审计 |
| [70-rungic-rebrand.md](docs/70-rungic-rebrand.md) | Rungic（AgentOS）改名：命名规则、迁移调研、分阶段计划与进度 |
| [71-upstream-patch-queue.md](docs/71-upstream-patch-queue.md) | 上游组件改为补丁队列：业界做法、目录与补丁规范、工具与测试分层、KWin试点 |
| [72-kwin-android-host-isolation.md](docs/72-kwin-android-host-isolation.md) | KWin的Android宿主适配：协议化与独立后端（调研、目标结构、试点） |
| [73-reduce-upstream-changes.md](docs/73-reduce-upstream-changes.md) | 减少对上游源码的修改：补丁队列收尾、扩展点与共享系统服务替代（总方案与进度） |
