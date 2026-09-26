# 用户要求与工程约定

## 适配前先调研（用户于 2026-09-23 明确要求）

每一项 Android / Linux / Plasma 适配开始实现之前，先广泛调查上游、类似项目和同类设备的已有工作，寻找最适合本机的可复用方案。

- 查实际源码、近期版本、已知问题及其修复状态，不能仅凭 README 的功能声明或旧教程决定。
- 比较直接使用、少量修改和自行实现的成本，优先保留成熟组件。已有实现质量不好、架构不适合或维护成本更高时，可以重写必要部分。
- 结合本机 Android 16、ARM64、Alpine musl、LXC、原生 Wayland、Mesa/KGSL 和 SELinux 状态核对兼容性。
- 本地记录来源/版本、许可证信息、选用或放弃原因、剩余问题和实机验收办法。研究结果与已验证可用的功能要明确区分。
- 一次初步检索不代表该项已经完成选型；在实际适配前继续完成对应源码和接口核验。没有搜到适配方案，只能记为本轮未找到，不能宣称不存在。
- 这项要求是工作顺序与质量要求，不增加逐项请求用户确认的流程。

当前设备能力审计见 `docs/research/28-capability-audit.md`；首轮复用研究见 `docs/research/29-reuse-research.md`。

已部署能力与验收范围见 `docs/research/30-feature-adaptation.md`；桌面与 Android 后端的实际连接、启动/挂载、接口契约、研究方法及扩展入口见 `docs/research/31-backend-integration.md`。后续适配先对照当前架构，保留源码/补丁与实机证据，并同步更新这两篇的相应内容。

## 优先修复共享系统能力，避免逐个应用重复适配

用户于2026-09-23明确要求：不要 case by case 地修复各个 App；尽量利用 Linux 与桌面系统已有的标准接口、服务及 Pipeline 扩展机制，在共享层解决问题，避免不同 App 反复遇到同类故障。

- 发现某个应用不能使用硬件或桌面功能时，先追踪它实际调用的接口与完整链路，区分共享后端缺失、标准接口未接入、能力协商/时序错误与应用自身缺陷。其他应用能用，不代表所有标准接口已经兼容；安装成功也不等于功能验收通过。
- 优先复用并完善系统机制，例如 libcamera Pipeline Handler、PipeWire、PulseAudio、GStreamer、Qt Multimedia、XDG Desktop Portal、Wayland 协议与桌面服务。适配应放在能让同类应用共同受益、职责正确的最低公共层；不要把硬件访问、权限处理、格式转换或时钟同步复制进多个应用。
- Android 摄像头、麦克风、编解码等能力继续共用已有后端。在 Linux 接口层补齐入口和能力协商，避免为每个 App 再造一条私有硬件通路。不能为了统一入口而破坏其他已工作的桌面或容器。
- 只有确认属于应用自身缺陷，或现有系统扩展机制不能合理解决时，才采用范围明确的应用补丁；记录证据、未采用共享层方案的原因、上游状态与维护/退出办法。功能设置和界面交互可以留在应用层，不能把它们与共享硬件适配混为一谈。
- 修改共享层后，除接口/协议级测试外，还应选取使用同一接口的多个独立应用交叉验收，并回归已有工作路径。媒体能力分别验证实际采集、编码文件、播放、时序、声音来源及停止后的资源释放；单个 App 出画面、生成文件或测试程序退出成功不足以代表整条能力可用。
- 本地文档记录“应用 → 标准接口/桌面服务 → 共享后端 → Android 硬件”的映射、已验证范围与缺口，后续适配先查此记录，避免重复研究和修复。

## 网络

用户指定代理为 `http://192.168.5.45:6152`，用于 HTTP 与 HTTPS；优先于上级目录中的默认代理配置。

## 独立 Plasma Mobile 环境的目标版本

用户于2026-09-23要求达到 **Plasma Mobile 6.5**，随后明确澄清 **可以采用更新稳定版**。当前要求是6.5或更新稳定版本，不再锁定6.5.x；此前6.3.6方案已撤回。

- 发行版按ARM64、glibc兼容、现成配套桌面依赖与维护成本选型，不因最初Debian13方案锁死底座。现已部署Ubuntu26.04LTS ARM64和官方Plasma Mobile6.6.5，定制KWin图形适配已显示桌面并通过GPU/触摸验收；不能把GPU单独探针通过当成桌面可用。选型见38篇，实施见40篇，Rime输入见41篇，运行补丁与验收见42篇。
- Plasma使用独立容器和Android入口。用户于2026-09-23后续明确停止维护Phosh，已移除本地Phosh专属实现；共享硬件能力保留在shared/。新桌面完成部署、硬件接入和实机验证前，不能以APK图标或rootfs引导成功代表可用。

## Magisk 31.0 数据库查询

2026-09-23 实际 `magisk --sqlite 'PRAGMA table_info(policies)'` 查询后 root 守护进程退出；源码与隔离复现定位到 SQL NULL 被直接转换为 `rust::Str`。见 `docs/39-magisk-daemon-crash.md`。

- 在此版本上，不向运行中的守护进程提交可能返回 SQL NULL 的查询，包括直接 `PRAGMA table_info(...)` 和未经检查的 `SELECT *`。
- 查询字段先查固定版本源码；确需数据库查询时选择明确非空列，或逐列使用 `COALESCE`，先在独立内存数据库核验结果。
- 不在实机复现该崩溃。不要将后续 `su` 的 SIGTRAP 当作 magiskd 最初退出的崩溃栈。

## 本地目录与同步边界

- 需要同步的源码、文档、基准数据和来源记录分别放在plasma/native/shared/tools、docs、benchmarks、provenance等目录；当前只维护Plasma桌面。
- 下载、构建缓存、安装包、日志、截图、实机媒体、私钥与本机配置统一放在`.work/`，不得新增到源码目录。Python/Cargo开发可先`source tools/work-env.sh`。
- 用户于2026-09-23明确要求同步开发用APK签名密钥：`signing/development/launcher-signing.p12`是上述规则的指定例外，随私有仓库跟踪，构建脚本默认使用它。此授权不包含其他密钥或`.work/`内容。
- 目录说明见`docs/52-git-repository-scope.md`。不要恢复旧refs目录，也不要为了旧脚本重新引入Phosh；修复当前共享接口和路径。

## Vendor源码与多机协作

- 用户于2026-09-23选择直接Vendor。本仓库`vendor/`保存固定上游组件及已应用的正式修改；原生后端`native/plasma/`、Android宿主和共享代码仍在各自目录。版本、来源和许可证入口见`vendor/manifest.json`，协作与核对结果见`docs/53-remote-system-development.md`。
- 直接修改这些跟踪的源码；历史patch是导入证据，不能重复应用到vendor，也不能与源码各自维护。`plasma/qt-video-duration.patch`是未验收实验，未进入正式Qt源码。
- 用`tools/stage_vendor.py`生成`.work`构建副本；不要把唯一修改留在忽略目录。保留符号链接所指的共享文件，避免同一桥接代码出现多份。
- 上游导入和本机修改分别提交，升级时更新基线和许可证记录。跨组件协议变更在同一组Git提交中同步；本机和K8用功能分支及提交SHA协作。
- Vendor中原始测试素材、发布包自带Cargo依赖及必要quilt状态属于源码；本机生成的产物仍只能进入`.work`。审计仅按精确哈希豁免已核对的上游公开文件，不豁免整个vendor目录。
- 2026-09-26起逐步改为业界通行的“固定上游＋补丁队列”（docs/71）：已迁移的组件（KWin、kscreen、plasma-mobile、plasma-settings、FFmpeg、Snapshot、typesafe-computer-use）只在`packages/<名称>/`维护，用`tools/pq.py prepare/export`修改补丁，不再有vendor目录；共享文件用配方的`overlay`放入源码树，不复制进补丁。其余组件迁移前仍按上面的vendor规则。
