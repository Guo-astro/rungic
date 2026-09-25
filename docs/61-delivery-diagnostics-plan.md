# 系统交付、验收与诊断改进方案

2026-09-26。本文是改进方案，**尚未实施，也没有操作手机**。基线是`origin/agent-native-debugging`（`817e4a7d`），下文55–59篇均指该分支中的文档。方案遵循AGENTS.md：优先使用Linux与发行版的标准机制，在共享层解决问题；修改后用多个独立应用交叉验收；研究结论与已验证功能分开写。

## 目标

1. **可重建**：容器rootfs上属于本项目的每一项修改都有版本，都能从仓库重新生成，并能查出它来自哪个提交。
2. **升级安全**：Ubuntu底座升级不会悄悄破坏本地修改；每次发布都能回到上一版本。
3. **回归可重复**：每次发布后自动运行交叉验收，结果可以和上一版本比较。
4. **故障可追溯**：崩溃有符号，能按签名归并，并能对应到发布版本。

不在范围内：更换发行版或改用声明式系统；修改Android全局设置；改变用户用Discover/apt安装应用的方式。

## 现状与问题

| 类别 | 现状（分支源码） | 问题 |
|---|---|---|
| vendor组件出包 | kwin用`dpkg-buildpackage`，但设了`nostrip`与`-g0`（`plasma/build-kwin.sh`）；Mesa由`package-mesa.py`手工组包，包之间有精确版本依赖；display、media组件改装Ubuntu原包（`package-display.py`、`package-media.py`）；`dpkg -i`安装后靠hold锁住12个包 | 三种出包方式并存；没有调试符号；hold只阻止升级，不表达依赖关系 |
| 热替换 | 至少8处dpkg-divert：Panel.qml、convergentwindows、录屏quicksetting、mobileshell与taskpanel插件、`libkscreenosdplugin.so`、`CompactApplet.qml`、Mesa libgallium（`build_on_device.py divert`及各`install*.sh`） | 底座升级后被覆盖的文件与新版本不匹配，只能靠文档提醒人工核对 |
| 自有程序 | 约40个文件装在`/usr/local/{bin,libexec,lib,share}`，由`build-desktop-fixes.sh`、`recording/`、`rime/`、`voice-agent/install.sh`、`deploy_plasma_diagnostics.py`等分别安装 | 没有统一清单，`dpkg -S`查不到归属，无法整体卸载或回退 |
| 系统配置 | systemd单元与drop-in、`/etc/plasma/gpu-env`、tmpfiles、APT源与Pin；部分“按本机已存配置”手工部署（42篇） | 设备状态与仓库可能不一致 |
| 用户配置 | 每次会话都改写`kscreenlockerrc`（`plasma/session`）；`display.py`持续写`plasmamobilerc`；`migrate-display.py`自带标记 | 强制覆盖用户选择；迁移机制是自制的 |
| 本机配置与凭据 | `/etc/profile.d/proxy.sh`、`/etc/plasma/audio-cookie`、`/etc/moto-plasma/account.json`、语音agent的API Key | 必须保持不入包、不入仓库，但目前没有清单说明它们应当存在 |
| 完整性 | 55篇偶然发现`/`、`/usr`属主为UID1000 | 没有例行的漂移检查 |
| 崩溃 | 容器内能取得core，由`moto-coredump-collect`用gdb回溯（55篇P1已验收） | 库帧大多是`??`；报告与发布版本无关联；同一问题无法归并 |
| 验收 | MCP、AT-SPI、perfetto追踪与证据包已具备（55篇） | 验收仍按次手工组织；48、50篇有大量待验收项 |
| 协作 | `main`落后活跃分支44个提交 | 容易按过时的基线做判断 |

## 总体结构

```text
Ubuntu 26.04底座（官方源，apt管理）
  └─ moto本地APT仓库（+motoN重建包与moto-*新增包，版本精确耦合）
       └─ 发布元包 moto-plasma-release（版本=一次发布，记录git提交）
本机配置（代理、音频cookie、账户、API Key）：不入包，由清单声明
用户数据与配置（/home）：不随系统回滚
```

## 1. 包与本地仓库

**包的划分**

| 类型 | 包 | 说明 |
|---|---|---|
| 替换型 | kwin、mesa、kscreen、plasma-mobile、qtmultimedia、libcamera等 | 版本为“Ubuntu版本+motoN”；vendor中补齐Ubuntu对应的`debian/`，按vendor规则先提交上游导入，再提交本机修改。目前被divert的文件回到所属包内重建 |
| 新增型 | `moto-plasma-session`（init、会话、单元与drop-in）、`moto-plasma-bridges`（platform、媒体、剪贴板、网络、亮度、显示）、`moto-plasma-input`（Rime与键盘）、`moto-plasma-recording`、`moto-plasma-diagnostics`（core采集、a11y、tracing）、`moto-voice-agent`、`moto-plasma-config`（`/etc/xdg`默认值与`kconf_update`脚本） | 取代现在的`/usr/local`与各安装脚本；文件装到`/usr`或`/etc`的标准位置 |
| 第三方二进制 | `moto-codex`（封装Codex官方发行包，构建时核对SHA256） | 保留59篇的版本目录与切换方式 |
| 发布 | `moto-plasma-release` | 以`=`依赖本次发布的全部包；在`/usr/share/moto/release.json`记录git提交与构建信息 |

**版本耦合**

- 与底座存在ABI或QML耦合的包，对相关Ubuntu包写精确依赖，例如插件依赖`plasma-workspace (= …)`。
- 底座想升级时，apt会拒绝或要求一起升级，这取代hold和“记得重新divert”。

**仓库**

- 在构建侧用`apt-ftparchive`生成文件型仓库，同步到设备后以`file:`源提供。
- 按origin设Pin，优先级1001，使我们的版本优先，并允许回退降级。
- 仓库保留最近几次发布的旧版本。

**调试符号**

- 改为带调试信息构建，交给debhelper自动生成`-dbgsym`包（Ubuntu为`.ddeb`），放在同一仓库，按需安装。
- 为控制手机上的编译内存与时间，先评估`-g1`（函数名与行号表）是否够用于回溯。

**开发迭代**

- `build_on_device.py divert`继续作为开发期的快速手段。
- 发布前的完整性检查若发现本项目的divert仍存在，就判定为“开发态”，不能作为发布状态。

## 2. 配置与迁移

| 类别 | 机制 | 首批对象 |
|---|---|---|
| 系统默认值 | `/etc/xdg/*rc`，KConfig级联，由`moto-plasma-config`以conffile安装；用户修改自然覆盖默认值。只有必须锁定的项才用`[$i]` | `kscreenlockerrc`：改为默认值，不再每次会话都写 |
| 用户一次性迁移 | `kconf_update`的`.upd`（`Version=6`），由kded6在启动和发现新文件时执行，按用户记录在`kconf_updaterc`（已核对KF6 6.24的`kded.cpp:50,527,586`） | `migrate-display.py`改写为kconf_update脚本，兼容已有的标记 |
| 系统迁移 | 包的maintainer脚本，用`dpkg --compare-versions`判断版本 | 随包变动逐项加入 |
| 运行时硬件值 | 仍由共享服务维护，例如挖孔与面板高度 | `display.py`；在文档中说明这不是用户偏好 |
| 本机配置与凭据 | 不入包；`.work/device/`中的清单只声明路径与属主，不保存内容；部署时只检查是否存在 | 代理、音频cookie、`account.json`、API Key |

## 3. 发布与部署

主机侧增加一个统一入口，名称待定，例如`tools/moto_release.py`，经`moto_device.py`访问设备：

- `build`：出包，生成仓库索引，写入`.work`；
- `deploy <版本>`：按下面的步骤部署；
- `rollback`：回到上一个发布；
- `status`：当前发布、git提交，以及和仓库是否一致。

`deploy`的步骤：

1. **预检**：容器运行中；没有未完成的dpkg操作；可用空间足够；完整性检查通过，或把差异记录下来。
2. **记录**：当前发布与`dpkg -l`写入`.work/deploy/<时间>/`。
3. **同步与安装**：同步仓库，在`systemd-run`与锁内执行`apt-get install moto-plasma-release=<版本>`。
4. **迁移**：随包执行，用户级迁移在下次会话由kded执行。
5. **重启**：按包触发器的要求重启会话。
6. **复核**：完整性检查与冒烟验收。
7. **保存**：全过程运行记录。

回滚：`apt-get install --allow-downgrades moto-plasma-release=<上一版本>`，回到本项目各包的上一版本。Ubuntu底座包的回退取决于旧版本是否仍能取得，完整回退依赖第7节的快照。

底座更新策略：Ubuntu更新只经发布流程进入；须确认容器内unattended-upgrades的状态（未核验）。

## 4. 完整性与漂移检查

以只读MCP工具提供，部署前后各运行一次，也可以随时调用，输出JSON：

- `dpkg --verify`：包内文件被改动或缺失；
- `dpkg-divert --list`：本项目的divert（开发态）；
- `/usr`、`/etc`中不属于任何包、也不在本机配置清单里的文件；
- `/`、`/usr`、`/etc`、`/var`的属主与模式异常（例如UID1000事件）；
- 实际安装的版本与发布元包的依赖是否一致。

## 5. 发布后自动验收

- 场景用数据文件描述，每个场景包括前置条件、步骤（调用现有MCP与`moto_agent`能力）、判定和证据。
- 结果写入`.work/acceptance/<发布>/<时间>/`；性能指标与上一发布比较。
- 分三级：
  - 冒烟：每次部署运行，目标5分钟内；
  - 完整：发布候选运行；
  - 人工：明确列出，不由自动结果替代。

| 能力 | 自动判定 | 仍需人工 |
|---|---|---|
| 会话 | 重启会话后KWin与plasmashell就绪；期间无新崩溃签名 | — |
| 显示 | `kscreen-doctor`应用并撤销模式、缩放与刷新率；截图尺寸与Android报告一致 | 视觉瑕疵 |
| 输入 | AT-SPI聚焦文本框；Rime提交中文后读回文本 | 候选界面体验 |
| 相机 | 经PipeWire取N帧，帧内容不是纯色、时间戳单调；停止后设备和`capture.sock`客户端已释放 | 画质 |
| 声音 | 播放流进入目标sink；录音源有非零电平；停止后sink与source恢复空闲挂起 | 实际声学效果 |
| 录屏与编解码 | 用AT-SPI按下录屏按钮；ffprobe核对时长、帧率、音轨；GStreamer与FFmpeg硬件编解码路径各测一次 | 音画同步主观检查 |
| 性能 | 沿用`kwin_pipeline_run.py`、`compbench_run.py`、帧统计，与上一发布设定阈值比较 | — |
| 投屏 | — | 需要真实接收端（58篇） |

每个场景结束时恢复现场，包括无障碍开关、显示模式和亮度，只使用可恢复的操作。

## 6. 崩溃诊断链

1. **标准格式**：采集脚本在现有文本行之外，再写一条systemd-coredump格式的journal条目：
   - `MESSAGE_ID=fc2e22bc6ee647b6b90729ab34a250b1`、`COREDUMP_PID/UID/SIGNAL/EXE/COMM/CMDLINE/TIMESTAMP`，以及指向`core.zst`的`COREDUMP_FILENAME`；
   - 依据：systemd v259的`coredumpctl.c`只按MESSAGE_ID选取条目（:116），按`COREDUMP_FILENAME`读取任意路径的core，并支持`.zst`（:999-1015）；
   - 这样`coredumpctl list/info/debug`可以直接使用。
   - 需要安装systemd-coredump包：
     - 要屏蔽它的`sysctl.d/50-coredump.conf`，不能依赖容器的`/proc/sys`只读来防止修改Android全局`core_pattern`；
     - 还要核对它与apport-core-dump-handler能否共存（未核验）。
2. **关联信息**：`info.json`增加发布版本、exe与各库的build-id，以及崩溃签名（符号化后前几帧的规范化结果；无符号时用“模块+偏移”）。
3. **符号化**：本项目的包用第1节的`-dbgsym`；Ubuntu的包优先使用ddebs仓库，须核对arm64是否可用；debuginfod直连慢、经代理超时（55篇），只作后备。gdb开启debuginfod时要用`-iex`。
4. **归并**：MCP按签名给出次数、首次与最近出现时间、涉及的发布，并能筛选“某发布之后新出现”的签名，用于判断回归。
5. **不装drkonqi**：KCrash 6.24在`core_pattern`不是管道且找得到drkonqi时，会改走DrKonqi实时调试并以`_exit(253)`结束（`kcrash.cpp:207`、`:753-755`），KDE程序将不再留下core。现在正因为没有drkonqi，才由`raise(sig)`交给内核写core（`:620-626`）。确需DrKonqi时，必须同时设置`KCRASH_DUMP_ONLY=1`。
6. **隐私**：
   - 持有凭据的服务（语音agent、codex app-server）在单元中设`LimitCORE=0`；
   - core只留在设备和`.work`，给云端agent的只有回溯与摘要。

## 7. rootfs镜像与快照（后置）

放在1–4之后实施：只有状态已知、可重建，回滚才有意义。

**先用ext4镜像**

- 做法：rootfs迁入`/data/adb`下的稀疏ext4镜像，经loop挂载，挂载只在Plasma的mount namespace内生效；SELinux仿照Docker的专用镜像类型（19篇）。
- 好处：不需要改内核，还能避开casefold F2FS对OverlayFS的拒绝。
- 回滚：内核已有`DM_SNAPSHOT=y`，可以做单个升级前快照，并用snapshot-merge回滚。
- 独立存放：`/home`、core目录（`/data/app_dump`、`/var/lib/moto-cores`）和本地仓库放在单独的镜像或目录，不随系统回滚。

**btrfs，满足条件后再做**

依据是已读的`android15-6.6-2025-05_r16`源码：

- `gki_defconfig`没有btrfs，且`BUILD.bazel`设置`trim_nonlisted_kmi = True`，另编模块无法加载，只能编进自编Image并重刷boot；
- btrfs会`select BLK_CGROUP_PUNT_BIO`，这会改变`struct blkcg_gq`（`block/blk-cgroup.h:76-79`），可能改变块层导出符号CRC，使原厂vendor模块无法加载；
- 候选修复：去掉该select，并在`fs/btrfs/bio.c:468-471`未启用时直接`submit_bio`；
- 前提：与当前boot相比KMI符号CRC零变化，441个原厂模块全部加载，性能对照可以接受。

btrfs的收益是多快照、廉价克隆的测试容器、send/receive增量备份以及压缩。

**从零重建**

有了第1节的仓库，用mmdebstrap按“Ubuntu包清单＋发布元包”生成rootfs镜像，用于空白机安装和K8上的可复现构建。

## 8. 协作

- 功能分支验收后尽快合入`main`，发布打tag；发布元包记录的提交SHA与tag对应。
- 开始调研前先执行`git fetch`并查看活跃的远端分支；是否写入AGENTS.md由用户决定。

## 分阶段计划

| 阶段 | 内容 | 验收 |
|---|---|---|
| 0 准备（不改设备） | 合入基线分支；在设备上只读执行`dpkg -S`等命令，生成现有文件清单并分类；决定仓库信任方式；测量`-g1`对kwin、Mesa构建时间与内存的影响 | 清单覆盖第3节所列全部安装脚本的产物 |
| 1 仓库与发布骨架 | 本地仓库；把现有kwin、Mesa、display、media的deb原样纳入发布元包；完整性检查工具；`deploy/rollback/status` | 从仓库安装发布后`dpkg -l`与现状一致；回滚与再部署成功；完整性检查只报出已知项 |
| 2 自有程序与配置入包 | `/usr/local`、单元、drop-in改为moto-*包；`kscreenlockerrc`改为默认值；`migrate-display`改为kconf_update | `dpkg -S`能找到本项目全部文件的归属；冒烟验收通过；用户修改在重新部署后保留 |
| 3 消除divert | 为被divert的组件补齐`debian/`并重建；libgallium并入Mesa包 | `dpkg-divert --list`没有本项目项；模拟底座升级时apt拒绝或一起升级 |
| 4 崩溃诊断链（可与1–2并行） | 标准格式、dbgsym、签名归并、发布关联、`LimitCORE=0` | KDE程序、非KDE程序和KWin的可控崩溃都能在`coredumpctl`与MCP中一致出现；自建组件帧已符号化；持有凭据的服务不产生core |
| 5 自动验收 | 冒烟与完整两级场景、与上一发布比较 | 连续两次发布得到可比较的报告；人为注入的回归能被判定为失败 |
| 6 rootfs镜像与快照 | ext4镜像与dm-snapshot；btrfs按第7节的条件决定 | 迁移前后验收一致；升级失败后可回到升级前状态；性能对照记录在案 |

每一阶段的证据写入`.work`，实施后同步更新40、42、55篇与README。

## 风险与待定

- **手机上的构建成本**：完整打包plasma-mobile、Mesa、kwin（带调试信息）的时间和内存需要实测。K8若为x86主机，需要另建ARM64构建环境。
- **安全更新延迟**：精确依赖会让相关Plasma包的安全更新必须等我们重建后才能进入，这是有意的取舍，需要约定重建节奏。
- **仓库信任**：root所有的本地`file:`源加`trusted=yes`，还是用本地密钥签名。密钥规则见AGENTS.md，目前只有APK签名密钥允许同步。
- **未核验项**：systemd-coredump与apport能否共存、ddebs的arm64可用性、unattended-upgrades状态、容器内`/proc/sys`在各启动路径下是否都只读。
- **自动验收的边界**：画质、声学效果、投屏无法自动判定，保留人工清单。
- **存储占用**：调试符号、旧版本和core都占空间，需要设置保留上限并纳入完整性检查。
