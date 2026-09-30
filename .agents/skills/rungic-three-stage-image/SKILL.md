---
name: rungic-three-stage-image
description: 本项目三段式构建与独立安装：按机型和固件准备 GKI/设备底座，构建 RungicOS rootfs，并在兼容底座上单独安装或升级 Rungic。用于新机型接入、分段构建、安装与首启排障；完整 Android 刷机包仅用于明确指定的历史流程或恢复任务。
---

# Rungic 三段式构建与独立安装

2026-09-30 用户调整目标：**CI1 设备底座 → CI2 RungicOS 镜像 → CI3 Rungic 独立安装/升级**。不再以将 Android、内核和 Rungic 合成一个完整刷机包为默认交付。复用已兼容的底座时，更新 Rungic 不重新刷 Android 分区，不默认清空 Android 数据。新流程的契约和现有工具缺口见 [75 篇](../../../docs/75-image-build-separation.md#2026-09-30rungic-独立安装的三段式目标)。

这是项目内 skill；源码路径相对仓库根目录。先读 `AGENTS.md`。源码、spec 和记录随 Git；产物、缓存、日志与凭据只放 `.work/`。保留现有 skill 名称，兼容已有调用。

## 进入任务

1. 区分底座准备、OS 构建、Rungic 首次安装、升级和恢复。沿用用户已有目标与授权；构建请求不附带设备写入。独立安装不授权重刷 Android、解锁或清数据，明确要求的底座刷写另按机型执行。
2. 读 `profiles/devices/<vendor>/<device>/<firmware>.json`、配套知识档案与本次路径的实机记录。新机型/固件变化读 [新机型接入](references/device-onboarding.md)；执行前读 [工具地图](references/tool-map.md)；首启问题读 [首启指南](references/first-boot.md)。旧整包验收只能证明当时的整包，不能当作新独立安装已通过。
3. 按 `AGENTS.md` 核验本机/远端身份、架构、路由与代理。适配前核对固定上游源码、同类方案、许可证和本机接口，保留复用或修改依据。设备差异进入 spec/适配器，不套用 G100 的槽位和分区命令。
4. 在 `.work/ci/runs/<run-id>/` 绑定源码 SHA（未提交修改另留补丁）、spec SHA、各阶段产物摘要、包锁和本次目标。CI3 记录实际使用的底座版本与能力，不要求无变化的 CI1 重跑，也不能仅凭型号相同跳过兼容核验。
5. 内核 ABI/CRC/Rust 差异读 [内核兼容对照](references/kernel-compatibility.md)；rootfs/宿主载荷、账户模板和清理读 [构建隔离](references/build-isolation.md)。具体设备数值留在 spec 档案，通用经验写入对应参考。

## CI1：设备底座与 GKI

- 基于该机型原厂固件，固定 ACK/Kleaf、工具链、页大小、内核配置、补丁和 boot 格式；验证 OEM 模块 ABI/CRC、签名信任与 root 提供者。只增加 Rungic/LXC 必需能力，修改过的上游继续用 `packages/` 补丁队列。
- 使用该设备已核验的候选启动或刷写路径，不能默认支持 `fastboot boot`。核验 Android 启动、SELinux、存储、LXC 所需机制及选定硬件后端。
- 交付 GKI/boot 候选、必要的底座准备/恢复材料、来源与兼容报告。解锁或特定底座安装可能清数据，按实际操作说明；这不是后续 Rungic 升级的固有步骤。
- 底座已兼容时复用其已验证产物和本次状态。仅 Android 版本、KMI 名称或 SoC 相同不能证明兼容；底座变化时重新验证受影响链路。

## CI2：独立 RungicOS 镜像

- 锁定 Ubuntu ARM64、Plasma 和 Rungic 包版本、架构、图形/媒体后端及宿主桥协议。rootfs 与 Android 共用 CI1 内核，不另带内核，也不是 Android `system.img`。
- 在干净 root 树安装精确依赖；x86 runner 使用 QEMU/真 chroot 执行 ARM64 安装脚本，ARM64 软件包可在合适的原生 runner 构建。runner 与设备配方分离。
- 检查包锁、`dpkg --audit`、项目 venv 的 `pip check`、权限/xattr、日志目录和文件系统；遵守 `system/ubuntu-excluded-packages.txt` 的预装选择。排除个人账户、密码、凭据和家目录备份。
- 交付 ext4 镜像、压缩载荷、包锁、摘要和报告，不依赖把它嵌入 `product` 或复制加密 userdata。镜像容量与后端需求按目标核验，不能固定推广 G100 的 16 GiB/KGSL。
- 当前 `build_rootfs_image.py` 只打包已准备的 root 树，不是包下载与全自动安装器。

## CI3：Rungic 独立安装与升级

目标是在已准备的兼容 Android 底座上，单独交付并安装 Rungic。**统一的独立首装包/安装器尚未实现并验收**；现有入口与缺口以 [工具地图](references/tool-map.md) 为准，不把旧 `flash.sh` 当作独立安装器。

- 独立交付范围：CI2 rootfs、需要的 Rungic APK/JNI、LXC/宿主桥运行时、版本/协议/摘要、安装器及恢复说明。Android OEM 分区和 GKI 是外部前提，不重复塞进日常 Rungic 发布包。
- 安装前核验实际固件/内核能力、root 授权、SELinux、架构、后端/宿主协议、APK 签名、容量和现有安装状态。选择本次已验证的传输入口；USB/ADB 可以是开发安装入口，不能提前宣称已实现用户自助安装。
- 首装须从“底座就绪、Rungic 尚未安装/配置”开始，完成载荷校验、存储/挂载准备、账户和真实桌面。沿用现有 release 原子状态与真实 loading；APK 普通安装与旧 product 预装的权限/JNI差异需实际核验。
- 既有安装优先用 `rungic_package.py` / `build_on_device.py` 构建包，`rungic_release.py` 执行版本化 APT 部署、验收和回滚。完整 rootfs 替换是另一条待实现/验证路径，不把首次种子脚本直接用于覆盖已有安装。
- 完整镜像更新应停容器、保存旧版本、在独立位置写入并核对摘要，再切换和验证；失败可恢复旧镜像及匹配的宿主版本。保留用户账户、文件、Agent 登录状态和 Android 数据；数据/schema 迁移的回滚范围须单独验证，不能仅靠换回 rootfs 宣称完整恢复。
- 底座能力不足时回到 CI1 处理，不能让 CI3 自动扩大为重刷 Android 或清数据。所有设备命令精确绑定端口和序列号。

## 首次进入与验收

`兼容底座就绪 → 验证独立载荷 → 安装/挂载准备 → 发布 ready → account-prepare → 账户表单 → 桌面 loading → Plasma`

完成标记由 root 控制器独立核验；状态关联 release，缺失、旧版或失败状态不提前放行。共享存储与账户工具按真实就绪状态检查，不能只等待固定时间。账户配置、正常启动和重试复用公共准备层，密码不写日志或 argv。

分别记录候选、离线通过、已安装、首装验收、升级验收与恢复验收；这些是工作流状态，现有工具未必全自动生成。每项绑定产物摘要和设备，不能将安装成功、普通重启或临时补装当作首装流程完整通过。升级核验数据保留、功能和回滚；不再以 Android 全清作为每个 Rungic 版本的验收门槛。用户指定的验收范围优先，不擅自扩大硬件测试。

## 历史整包与恢复

`assemble_product.py`、`assemble_release.py`、`flash_release.py` 及 product 首启种子仍用于明确指定的历史整包或恢复工作，保留其来源和实机证据；不作为当前默认 CI3。只有任务明确选择该路径时，才查 [77 篇](../../../docs/77-g100-three-ci-assessment.md)、[80 篇](../../../docs/80-g100-image-installation-retrospective.md) 和工具地图的机型假设，按已授权范围执行。旧 G100 清数据首启的成功不能迁移为独立安装结论。

交付时说明产物、源码/spec/摘要、底座前提、实际验收与待办。按 run-id 清理可重建暂存，保留正式产物、恢复材料及报告；不全局 prune，也不删除其他任务依赖来续跑。
