# 通用三条镜像 CI：以 G100 为首个设备 spec 的构建与发布计划

> 2026-09-30：当前交付目标已改为“底座/GKI → 独立 RungicOS → 单独安装/升级”，见 [75 篇](75-image-build-separation.md#2026-09-30rungic-独立安装的三段式目标)。本文保留当时整包方案、runner 与工具评估；其完整包/清数据要求不再默认适用于新的 CI3。

2026-09-27，只读检查本地仓库、XT2533-4 实机、完整原厂包及 `macmini.wire.net` 的 Docker。按用户确认的分工，**Mac mini 仅原生编译 Rungic ARM64 软件包；当前 Linux x86_64 工作站执行通用 GKI、RungicOS image、整机刷入包三条 CI，并连接 G100 做首个设备验收**。三条 CI 的实现和产物契约不按 G100 写死；`portov_cn` 是通用设计下的第一个设备/固件 spec。此文是实施计划与放行门槛，尚未新增 CI、编译 G100 内核或刷写手机。远程检查使用临时交互式 SSH；凭据没有写入仓库或构建配置。

## 通用架构和 spec 边界

三个概念分别建模，避免今后新增机型时复制流水线：

| 层级 | 归属 | 典型内容 |
| --- | --- | --- |
| 通用引擎和契约 | `tools/kernel/`、`tools/image/`、`tools/compat/`、CI 模板 | 源码锁定、交叉构建、ABI/模块检查、rootfs 制作、动态分区与 AVB 组装、刷机前校验、能力报告、验收状态机、缓存生命周期。所有设备走同一组入口和产物 schema。 |
| 设备/固件 spec | 拟建的 `profiles/devices/<厂商>/<代号>/<固件>.json`，引用 `kernel/targets/...` 的配方 | 型号/SKU/渠道/指纹、OEM 基线 SHA、GKI/KMI/页大小、ACK/Kleaf 来源与补丁、模块及证书关系、boot/分区/AVB 布局、驱动/图形后端适配、首启部署策略、刷写顺序及设备特定验收项。不同固件基线各有不可变 spec；同 SoC 不自动共享内核。 |
| 运行实例 | CI 参数和实机探测结果 | `run-id`、目标测试机序列号、当前槽位、当前固件/bootloader 状态、实际分区大小、能力探针证据、产物摘要与验收结论。这些动态事实不能被写成静态 spec 里的 `supported: true`。 |

通用 `spec` schema 应版本化，并在构建前完成**结构校验、引用解析、OEM 哈希校验和能力需求匹配**。一个 spec 只能引用精确版本的 OEM 基线、内核配方、RungicOS 用户空间变体及纯净化策略；继承公共模板后要展开成一份不可变的 `resolved-spec.json`，记录每个值的来源和摘要，不允许 CI 从目录名、当前手机状态或“最新”产物猜测。内核、rootfs、组包各自输出相同格式的产物清单，其中包含 `schema_version`、输入摘要、输出 SHA-256、架构、所需能力和已验证等级。CI3 只根据这些清单与 `resolved-spec.json` 合包；不匹配时停止。设计对应 [75 篇](75-image-build-separation.md)的设备 profile/能力契约，具体字段和探针仍须在首个实现中以源码与实机证据定稿。

RungicOS 的 ARM64 rootfs 尽量以相同包仓库快照复用；GPU 驱动、桥接后端或启动配置若确实依赖设备，则作为显式变体/适配器输入，不能反向把整个 rootfs CI 变成按机型复制的流程。通用纯净化策略定义“可删除的第三方消费应用、默认关闭的助手、必须保留的 Android 核心角色”等规则；具体 APK 哈希、依赖和例外由设备 spec 固定，规则引擎遇未知包或冲突时不作猜测。新增手机首先新增并核验 spec，只有出现当前引擎无法表达的分区/启动机制时才扩展一个有测试的通用接口或独立适配器。

实施顺序先于 G100 专项构建：① 定义并校验 spec、内核/rootfs/固件产物和能力报告的版本化 schema；② 将旧 `mumba` 脚本里可复用的固件解析、分区重建、刷机前检查抽成通用引擎，硬编码移到各自 spec，保留旧机型回归 fixture；③ 建立三条参数化 CI 和不可变产物库、容量门槛及清理 job；④ 对 G100 的精确来源完成上游/源码/接口核验后填入第一个真实 spec，跑离线和实机验收；⑤ 用第二种机型或固件基线的独立 fixture 验证同一工作流能拒绝错配并正确解析另一份 spec。没有完成④之前，不把它标记为已适配。

## 首个设备 spec：G100 基线和机器现状

目标仅为 **XT2533-4 / `portov_cn` / RETCN / `W1VT36H.1-51-8`**，指纹 `motorola/portov_cn/portov:16/W1VT36H.1-51-8/e9ec8-e96731:user/release-keys`；原机是 Android 16、ARM64、4K、`6.6.87-android15-8`（KMI 8）、解锁的 bootloader。原厂包 SHA-256、六个动态分区和 AVB 的主机侧核验见 [78 篇](78-g100-firmware-inventory.md)；尚未刷入。`boot`、`init_boot`、`vendor_boot` 均为 header v4；`boot` 的 ramdisk 长度为 0，`init_boot` 含约 2.46 MB ramdisk，`vendor_boot` 含设备 DTB 和 vendor ramdisk。G100 S `mumba_cn` 的内核、模块、固件哈希及刷写脚本均不可挪用。

仓库没有 `.github/workflows` 或其他成型 CI。`tools/prepare_g100_stock.py`、`verify_g100_stock.py` 只完成 G100 原厂包提取及离线校验；`tools/build_clean_product.py`、`assemble_clean_rom.py`、`oneclick_flash.py` 的固定路径、固件、哈希和 `mumba` 检查属于旧 G100 S。`tools/rungic_release.py` 已能从正在运行的系统发布 APT 包，`plasma/rootfs-image` 管理现有 ext4 镜像；从空白 Ubuntu 构造 RungicOS rootfs 和清数据后自动安装仍未实现。[75 篇](75-image-build-separation.md)规定三层分离和单设备最终组包。

Mac mini 是 Apple M4 ARM64、16 GB 物理内存；OrbStack Docker 为 Linux/ARM64、10 CPU、约 **8 GB VM 内存**。当前仅有一个运行中的 `rungic-build` 容器，镜像 `rungic-arm64-host:4bde4b381f5d`（`tools/pq/arm64-host.Dockerfile`，按Dockerfile、ddebs源与包清单的哈希打标签），供 Ubuntu 26.04 ARM64 上游软件包、项目软件包构建和崩溃符号化；没有 GKI、rootfs 或固件组装镜像。2026-09-27 起镜像除工具链、Mesa构建依赖、gdb与Ubuntu调试符号源外，还按 `tools/pq/arm64-host-packages.txt` 装有手机的整套 Plasma Mobile 与桌面环境（约2700个包，与手机容器的已装QML模块一致，见71篇“构建机”）；仍没有 `repo`、`bazel`、`mmdebstrap`、`avbtool`、`lpmake`、`simg2img`、Clang。Mac mini 上的任务按AGENTS.md读取并使用macOS系统代理（Surge，容器内经 `host.docker.internal`）。宿主可用约 37 GiB，Docker VM 内约 36 GiB；现有 Docker 卷约 4 GiB。G100 原厂 ZIP 约 9.5 GB，验证后展开目录约 31 GB，`super.raw.img` 单文件 18,924,699,648 字节。因此当前 Mac mini 容量连同时保留展开固件和实用构建空间都不足。

当前 Fedora Linux 工作站是 x86_64、16 个逻辑 CPU、30 GiB RAM（检查时可用约 26 GiB）、`/home` 可用约 392 GiB；有 Podman、`repo`、Clang、ADB/fastboot，既有 ACK 树内有 `tools/bazel` 与 `avbtool`、`lpmake`、`simg2img`。目前缺 `mmdebstrap`、EROFS 工具和 ARM64 用户空间执行环境；可以放到固定 OCI 镜像中补齐。目标 G100 `ZY32M9MRVP` 正通过 USB 连接此机，另有一台 `mumba_cn` 同时在线，所有实机命令必须强制精确序列号。故 CI1、CI3 的主机构建及 G100 硬件验收可在本机落地；CI2 **也可**在本机构建完整 ARM64 rootfs，只需先建立并验收 QEMU/binfmt 的 ARM64 安装环境。原生编译 Plasma/Mesa 等 ARM64 软件包仍更适合 Mac mini；这两类工作不必放在同一个 runner。

更关键的是，AOSP 当前 Kleaf/Clang/内核构建工具的预编译**执行平台是 Linux x86_64**；ARM64 Mac mini 的原生 Linux 容器不能直接视为合适的 GKI builder。可实测 amd64 虚拟化，但这不是首选发布路径。本机 Linux x86_64 已有 15 GB 的旧 ACK 工作树和约 392 GiB 空间，适合先做独立 x86 runner；它的旧树只作工具缓存和方法参考，不能直接作为 G100 源码基线。[Kleaf 工具链约束](https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+/refs/tags/android-15.0.0_r6/kleaf/)、[AOSP GKI 构建说明](https://android.googlesource.com/kernel/build/+/refs/heads/main-kernel/kleaf/docs/kleaf.md)。

## 三条通用 CI 的契约

| CI | 固定 runner | 输入 | 成品与门槛 |
| --- | --- | --- | --- |
| `gki`（G100 的运行参数为 `portov_cn/W1VT36H.1-51-8`） | 当前 Linux x86_64 工作站上的固定 OCI builder | 已解析设备 spec、**精确** ACK/Kleaf manifest 与工具链、补丁、对应原厂 boot/模块和证书事实 | `Image`、`Module.symvers`、配置、ABI/模块比对报告、该 spec 专属 `boot.img`、SHA-256 清单。静态通过仍标记为候选，须在对应设备实机启动、模块/基础硬件/SELinux/LXC 验收后才供最终发布使用。 |
| `rungic-image`（首版输出 `arm64` 变体） | 同一工作站的独立 x86_64 OCI builder；QEMU 用户态/binfmt 执行 ARM64 安装脚本 | 锁定的 Ubuntu 26.04 仓库快照、Mac mini 发布的**已构建 ARM64 `.deb` 仓库快照及摘要**、Plasma Mobile 6.6.5 或更新稳定配套版本、APK/桥协议、显式用户空间变体 | 从零构造 ARM64 rootfs，输出可安装载荷、ext4 镜像及文件/包清单和压缩后大小；验证 `e2fsck`、包/架构、依赖与离线启动前置条件。rootfs 不携带自己的内核；同一变体可被多个设备 spec 按摘要引用。Mac mini 的运行容器不能作为 rootfs 输入。 |
| `firmware`（G100 的运行参数为 `portov_cn/W1VT36H.1-51-8`） | 同一工作站的独立 x86_64 OCI builder；USB 刷写验收在本机宿主的专用受控步骤 | 精确原厂包、前两条 CI 的不可变 SHA-256 产物、通用纯净化规则与 spec 例外、设备 spec、Android 宿主 APK/首启组件 | 按 spec 修改必要的 Android 分区、组装专属 `boot`/`init_boot` 与 AVB/fastboot 计划，输出单入口刷机包及追溯清单。先做完整离线恢复校验，再在对应专用测试机**清数据、从 bootloader 刷入、首启安装并验收**；未通过不标记为一键可用。 |

三条都是当前工作站的逻辑 CI，分别使用固定版本的 OCI 镜像和相互隔离的 `.work/ci/runs/<run-id>/` 工作空间；Mac mini 原有 `rungic-build` 只充当**上游软件包生产者**，不承担镜像 CI 或刷机。可用 GitHub Actions 或等效控制面按提交 SHA 编排一个 x86_64 自托管 runner，同一个工作流通过 `device_spec` 参数选择目标，重型任务在该 runner 上串行，避免同时占用大量磁盘。测试机序列号是受控部署参数而非 spec 内容；本轮刷机步骤只允许精确 USB 序列号 `ZY32M9MRVP` 和现场识别出的 `portov_cn`。不把 ZIP、构建缓存、设备私有材料或密钥推入 Git。Mac mini 的账号密码不进入 CI：工作站以 SSH 密钥登录（2026-09-27 起）；开发手机容器另有一把受限密钥，只能从手机地址调用构建容器里的 `tools/pq/rungic-transfer`，在 `/root/rungic-build` 下收发文件（71篇）。正式包交接沿用专用受限密钥或受控只读产物库，不复用这些开发密钥。各任务在 spec、固件 SHA、KMI、包仓库快照或产物摘要不一致时拒绝组合。

### 产物交接与触发顺序

```text
Mac mini：ARM64 软件包构建与 APT 仓库快照 ──┐
                                               ├── 当前工作站 CI2：RungicOS 变体 ──┐
当前工作站 CI1：所选 spec 的 GKI/boot ──────────────────────────────────────────┤
当前工作站：所选 spec 的 OEM 包与纯净化策略 ─────────────────────────────────────┘
                                               ↓
                            当前工作站 CI3：镜像组包 → 离线校验 → 对应测试机刷入/验收
                                               ↓
                            正式发布 → 本次构建缓存清理 → 容量核对
```

一次发布固定 `source_commit`、`resolved_spec_sha256`、OEM ZIP SHA-256、Mac mini 包仓库 `snapshot_id`、CI1/CI2 产物摘要和 Android 宿主 APK/桥协议版本，形成不可变 `release-inputs.json`。Mac mini 先把 `.deb`、`Packages`/`Release` 索引、包版本表和 SHA-256 清单发布到受控暂存区（**目标流程**；现状是Mac mini构建后由工作站的 `build_on_device.py collect` 取回，逐文件核对大小与SHA-256，再收进工作站 `.work/apt` 的发布仓库，由 `rungic_release.py` 出版本。改为Mac mini发布不可变快照属待办）；CI2 在本机**先验证清单，后消费包**。CI1 与 CI2 的源码/清单检查可并行，但在当前工作站的重型编译/镜像阶段串行；CI3 只读取两者经校验的产物，不从工作目录“取最新文件”。发布包内保留 `manifest.json`、逐文件 SHA-256、已解析 spec、能力报告和验收记录。CI1/CI2 的候选成功只说明各自产物有效；整个流程的发布状态只能由 CI3 的实机验收授予。

### 容量门槛与部署成功后的缓存清理

每次运行使用 `device-spec-id + source SHA + package snapshot ID + run-id` 组成唯一目录和 OCI/卷标签。启动前按该 spec 的 OEM 压缩包、展开分区、内核输出、rootfs、整包及回退材料估算峰值；首个 G100 流程建议先以**本机至少 200 GiB 可用且始终保留 60 GiB 安全余量**为保守闸门，再根据首次运行实测调参。构建期间按阶段监控剩余空间；低于余量就安全停止新阶段，不删除正在使用的产物或其他人的缓存。Mac mini 的 ARM64 包构建也单独检查宿主和 Docker VM 容量。

发布状态机为 `candidate → offline-verified → flashed → android-accepted → rungic-accepted → bundle-validated`。**只有发布包及恢复包已落在持久产物区、逐文件 SHA-256 回读验证通过、对应测试机完成清数据刷入和 Android/RungicOS 验收、报告已保存，才触发本次运行的成功清理 job。**清理要紧跟 `bundle-validated`，不等待下一次构建或定期人工维护；成功清理后的容量核对和 `df` 结果进入本次报告。CI1/CI2 中间输出在 CI3 消费并验收前仍保留，避免清理过早导致重跑或无法审计。

成功清理按 `run-id` 白名单删除：临时源码检出、Bazel 输出树/构建缓存、QEMU/binfmt rootfs 暂存、解开的 `super`/逻辑分区和 EROFS/AVB 临时镜像、仅本次创建的 Podman 层/卷，以及 Mac mini 本次软件包的临时构建目录。**保留**当前 OEM 原厂恢复包、正式发行包、已发布的 ARM64 APT 快照、输入/输出哈希和来源许可证清单、能力与实机验收记录；可复用只读源码镜像另设容量上限和独立淘汰规则。绝不执行全局 `podman system prune`、Docker 全局清理或按路径通配删 `.work`；现有 `rungic-build` 和其他机型运行不能受影响。

失败时不赋予发行状态；先留小体积诊断日志和必要证据，按短保留期（建议 24–48 小时）清理可重建的大型暂存物，恢复包和上一次已验证发行包始终保留。清理动作应有 dry-run 清单、路径/标签归属核对、删除日志和结束后的容量门槛复查；若清理失败或磁盘仍低于安全余量，阻止下一次重型任务并报警，而非继续把工作站撑满。

**“交叉编译 RungicOS”需要分成两件事。** 制作 rootfs 主要是下载/安装已有 ARM64 `.deb`、运行安装脚本、写文件系统，不需要在构建机原生编译 Ubuntu 全部源码。`mmdebstrap --architectures=arm64` 支持跨架构；完整安装需要 QEMU 用户态加 `binfmt_misc` 执行 ARM64 程序，并对实际包集的 maintainer scripts 做验证。[mmdebstrap 手册](https://manpages.debian.org/trixie/mmdebstrap/mmdebstrap.1.en.html)、[Debian ARM64/QEMU 指南](https://wiki.debian.org/Arm64Qemu)。仅 `extract` 模式不等于完成安装；`chrootless` 模式对维护脚本的支持有限，不作为本项目发布捷径。把项目的 KWin、Mesa、Qt 等源码包都从 x86_64 **真正交叉编译**到 ARM64 则需要多架构依赖、交叉工具链和逐包修正构建脚本；当前 `packages/`/`tools/build_on_device.py` 尚未提供这套配方。[Debian 交叉构建概述](https://wiki.debian.org/CrossCompiling)。首版建议保留 Mac mini 原生编译项目 ARM64 `.deb`，在本机用这些精确版本包构造和验收 rootfs；若日后希望完全摆脱 Mac mini，再评估逐包交叉编译或整套 QEMU 模拟构建的时间成本。

## G100 spec 的首个硬门槛

先从这台 G100 的原厂 `boot`、`system_dlkm`、`vendor_dlkm`、`vendor_boot` 提取 `Image`/模块信任与版本证据，对应 Motorola **此版本**公开源码和 AOSP ACK tag/manifest 才能固定内核配方。首轮检索发现 Motorola 发布了较新 `W1VT36H.22-20` 的 `portov` 构建说明，但它**不是当前 `W1VT36H.1-51-8` 配方**，也未核对其源码/接口，不能替代精确版本。已有 G100 S 实验出现 97 个模块缺失、3,252 个 CRC 变化，证明相同 `android15-6.6`/KMI 代数并不足以放行。要以原厂模块全量加载、签名信任、ABI、Android 开机和 LXC 所需配置为双重门槛；第一版只最小修改 ACK，保留原厂 vendor 分区和设备 DTB。[AOSP KMI 规则](https://source.android.com/docs/core/architecture/kernel/stable-kmi)、[Motorola 较新 portov 构建说明](https://github.com/MotorolaMobilityLLC/readme/blob/master/W1VT36H.22-20.txt)。

## G100 spec 的纯净系统策略

不按 `/product/preinstall` 路径一刀切。该目录同时包含默认搜狗输入法、原厂相机相关服务的用户入口、钱包/桌面互联等；另有硬件、电话、权限和无障碍服务在 `/system_ext`、`/product/priv-app`。每个条目写入版本化策略，字段至少为 `package`、原始 APK 路径和 SHA、处理方式 `remove|disable|keep`、原因、依赖/角色、验收场景和恢复来源。最终 `pm list packages`/`dumpsys package` 必须与策略核对。

**第一批实际移除候选**为 `/product/preinstall` 的 15 个独立消费类第三方 APK：高德、百度搜索、最美天气、抖音、番茄小说、爱奇艺、快手、美图秀秀、网易云音乐、今日头条、QQ 音乐、小红书、微博、优酷、哔哩哔哩。包名分别为 `com.autonavi.minimap`、`com.baidu.searchbox`、`com.icoolme.android.weather`、`com.ss.android.ugc.aweme`、`com.dragon.read`、`com.qiyi.video`、`com.smile.gifmaker`、`com.mt.mtxx.mtxx`、`com.netease.cloudmusic`、`com.ss.android.article.news`、`com.tencent.qqmusic`、`com.xingin.xhs`、`com.sina.weibo`、`com.youku.phone`、`tv.danmaku.bili`。这是实机 APK 路径审计后的**候选清单**，尚未在重建镜像上验收；若发现组件是其他功能的唯一入口，应由依赖/功能测试拦下。联想智享家、俱乐部、想帮帮等 OEM 附加应用另列候选，不混入“第三方消费 APK”。

**默认禁用 AI 助手**首先覆盖本机已试停的 `com.lenovo.menu_assistant`、`com.lenovo.levoice_agent`、`com.lenovo.xiaotian.trigger`；重建包不能依赖当前手机 `/data` 中的 `pm disable-user` 状态。Android 16 的首选是镜像内的 `sysconfig` `disabled-in-sku` 或 `install-in-user-type` 策略，依本机 `ro.boot.hardware.sku=XT2533-4` 与系统配置实际行为选择并在**擦除数据后**验证；必要时由可回放的首启提供者补足默认助手角色清理。Android 16 已移除旧的按 SKU RRO 禁用 APK 机制。[AOSP Android 16 共用系统镜像/按 SKU 禁用说明](https://source.android.com/docs/core/architecture/partitions/shared-system-image)。`com.motorola.aicore` 当前无进程、`com.motorola.cn.searchintelligence` 为缓存进程，不应为了假想内存收益立即移除；`com.motorola.aiservices` 还受厂商系统绑定并支持充电/亮度等能力，待功能验收后再决定。默认搜狗输入法虽是第三方 APK，目前仍是唯一已验证的中文 Android 输入入口；替代 IME 安装、切换和中文输入验收前保留。[实机 AI 审计](76-g100-memory-audit.md)。

物理删除产品分区 APK 应重建 EROFS、文件权限/SELinux 标签、动态分区元数据并重新验证 AVB；删除 `/system_ext`/`system` 的内容另有对应分区与 VINTF/权限 XML 的工作量。初版只改明确需要的分区，保留原厂 modem、vendor、dtbo、`vendor_boot` 与其他设备私有内容。[AOSP 动态分区](https://source.android.com/docs/core/ota/dynamic_partitions/implement)、[AVB](https://source.android.com/docs/security/features/verifiedboot/avb)。

## G100 spec 的一键刷入未决设计与实机验收

RungicOS 位于 `/data/adb/rungic-lxc/images/`，`userdata` 有设备级加密；不能在主机上把 rootfs 塞进通用 `userdata.img`。CI2 应先量出压缩载荷、镜像实际占用和原厂 `product` 可用空间：如能容纳，优先复用经验证的只读分区首启种子，在首次清数据开机时原子写入 `/data` 并可断电重试；如不能容纳，须验证可从 bootloader 进入的恢复/安装阶段将包内 rootfs 写入新格式化的 `/data`。这两条目前都只是候选，必须以**无需先打开 USB 调试和手动 ADB 拷贝**为成功条件。现有 v3 的 Magisk 首启种子只验证了 Magisk，没有验证 Rungic rootfs。[75 篇](75-image-build-separation.md)、[AOSP 加密](https://source.android.com/docs/security/features/encryption/file-based)。

此外，现有 Rungic Android 宿主依赖 root/Magisk，而 [Magisk 官方说明](https://topjohnwu.github.io/Magisk/install.html)要求在目标设备本机修补对应 boot/init_boot/recovery。初始试验可以限定为**这一台**已核对序列号和固件的 G100，并将目标机生成的 `init_boot` 产物作为受保护输入；不能把它宣称为同型号任意手机的通用镜像。长期方案要另做设备侧修补/安装路径或重新设计 root 入口。

通用工作流按阶段放行；下列值为 G100 首个 spec 的实例：

1. **来源锁定**：确认当前 G100 的精确内核/模块源码、许可证、工具链与 OEM 固件 SHA；保存 profile 和不含私有设备数据的恢复包。
2. **内核候选**：CI1 基线重编与 ABI/签名/模块检查，然后只在专用 G100 上试 boot；记录触摸、显示、电话/数据/Wi-Fi、摄像头、SELinux、LXC 条件及回退。
3. **RungicOS 候选**：CI2 从零建立 Ubuntu ARM64 rootfs，核验包、文件系统、桥协议，先在已验证内核上安装并完成 Plasma/GPU/输入、音视频与资源释放验收。
4. **整包候选**：CI3 按纯净化策略重建分区、AVB 与刷机计划，离线比对完整固件；从 bootloader 清数据一键刷入，首启自动得到 RungicOS，无手工 ADB 步骤；核验被移除 APK 不存在、AI 助手默认未启用、核心 Android 功能和 RungicOS 均可用。
5. **发布及清理**：输出 `portov_cn/W1VT36H.1-51-8` 单入口包、逐文件 SHA-256、来源/许可证与能力报告、刷写/实机验收记录；完成回读、实机部署与验收后立即执行本次运行的缓存清理。任一步失败不得把产物标为“完整可刷”。

将来接入第二款手机时，按相同入口先生成独立设备/固件 spec 与原厂恢复基线，核实精确内核源码、模块/AVB/分区和许可证，定义必要的后端适配与纯净化例外，再依次运行三条 CI、离线校验和专用测试机的完整擦除验收。RungicOS 变体若能力需求与包摘要一致可直接复用；GKI/boot 和整机发行包必须按新 spec 重新构建。用第二款设备的离线 fixture 与实机结果检验通用接口，禁止通过复制 G100 工作流、替换字符串或跳过能力检查实现“适配”。

尚缺的不是 Docker 镜像标签，而是精确 G100 GKI 来源和兼容证据、可复现 rootfs 配方、首启 rootfs 安装、Android 16 纯净化镜像重建及完整实机验收。涉及再分发的 Motorola/高通原厂二进制和各 Rungic 软件包，发布前必须分别核对其许可证及分发范围；当前方案不把私有固件或签名密钥写入 Git。
