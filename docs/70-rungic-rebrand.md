# Rungic改名（AgentOS）

2026-09-26，用户把本系统定名为**Rungic**，定位为AgentOS。用户选择**全部改名**：对外名称和内部标识（包、APK包名、路径、工具、MCP服务、环境变量、SELinux与device-mapper名称）都改；反向域名前缀由用户定为`com.rungic`。本文记录命名规则、迁移方案、实施进度和验收。

## 命名规则

| 类别 | 原名 | 新名 |
|---|---|---|
| 显示名称 | Moto Android / Plasma Mobile（APK标签“Plasma Mobile”） | Rungic；说明文字“AgentOS” |
| APK | `dev.moto.plasma`（Java包`dev.moto.plasma`） | `com.rungic.plasma`（Java包一起改） |
| 反向域名（APK包名、D-Bus名称、desktop文件ID、快捷设置ID） | `dev.moto.*` | `com.rungic.*` |
| Debian包 | `moto-*`、`moto-plasma-release` | `rungic-*`、`rungic-release` |
| 重建包版本后缀 | `+motoN` | `+rungicN`（从1开始；dpkg中`+rungic1`排在`+moto19`之后） |
| 可执行文件、单元、目录 | `moto-*`、`/usr/share/moto`、`/var/lib/moto-*`、`/usr/lib/moto-codec` | `rungic-*`、`/usr/share/rungic`、`/var/lib/rungic-*`、`/usr/lib/rungic-codec` |
| 用户数据目录 | `~/.config/moto-*`、`~/.local/{share,state}/moto-*` | `~/.config/rungic-*` 等 |
| 环境变量 | `MOTO_*` | `RUNGIC_*` |
| Android属性 | `debug.moto.*` | `debug.rungic.*` |
| Android侧路径 | `/data/adb/moto-plasma`、`/data/adb/moto-lxc`、`/data/adb/moto-wfd`、`/data/adb/moto-docker` | `/data/adb/rungic-plasma`、`/data/adb/rungic-lxc`、`/data/adb/rungic-wfd`、`/data/adb/rungic-docker`；rootfs镜像移到`/data/adb/rungic-lxc/images/`（见下文63字节限制） |
| docker SELinux域 | `moto_docker`、`moto_docker_file` | `rungic_docker`、`rungic_docker_file` |
| SELinux类型、dm设备 | `moto_plasma_image`、`moto-plasma-root` | `rungic_image`、`rungic-root` |
| C/Java符号、GStreamer与FFmpeg名称 | `moto_codec_*`、`motoh264enc`、`h264_moto` | `rungic_codec_*`、`rungich264enc`、`h264_rungic` |
| 主机工具、MCP服务 | `tools/moto_*.py`、MCP服务`moto` | `tools/rungic_*.py`、MCP服务`rungic` |

**不改的内容**

- 指这台Motorola硬件的名称：moto g100s、XT2537-4、`motorola`、`mumba`等设备与厂商标识，以及描述硬件的文字。
- 历史记录：`benchmarks/`、`provenance/`和文档中带日期的实测记录保持原文；它们记录的是当时的名称。现行说明（README、架构、操作入口）改为新名称。
- 上游组件自身的名称（Plasma Mobile、KWin、Mesa等）；只改我们在vendor中加入的标识。
- GitHub仓库名`range-dev`：用户未要求。

## 迁移原则

- 一个名称在跨组件协议中（APK与容器之间的socket/ABI、KWin与会话之间的环境变量、GStreamer元件名等）改动时，两端在同一组提交中修改并一起发布（AGENTS.md）。
- 用户数据与设置不丢：用户目录、API密钥、会话记录、快捷设置列表、KDE配置中的desktop ID由迁移脚本搬移或改写；迁移可重复执行。
- 每一步用发布与快照部署，验收失败自动回滚；验收覆盖改名涉及的路径，并确认旧名称不再出现（`moto-integrity`/`rungic-integrity`增加残留检查）。
- 调研结论见`.work/research/rebrand/`（Debian包改名、Android包名迁移），摘要写入下文。


## 调研结论（2026-09-26）

报告：`.work/research/rebrand/debian/report.md`（dpkg 1.23.7、apt 3.2.0、init-system-helpers 1.69源码，并在`ubuntu:26.04`容器中用仿制包实测）、`.work/research/rebrand/android/report.md`（AOSP android16、Magisk v31.0、toybox 0.8.12源码与只读实机查询）。

**Debian包**

- 不做过渡包：每个`rungic-X`对`moto-X`写不带版本的`Conflicts`+`Replaces`，`rungic-release`对`moto-plasma-release`同样处理。实测按精确版本部署新发布时apt自动移除全部`moto-*`（留下`rc`状态），回滚到旧发布时自动移除`rungic-*`。依赖旧名的`*-dbgsym`会被一并移除；旧版本的deb必须留在仓库中，否则无法回滚。
- 同一路径的conffile：dpkg把属主和校验和交给新包，用户修改保留；回滚时再交回。路径改名时`dpkg-maintscript-helper mv_conffile`跨包不生效，需要在新包首次configure时复制旧文件（保留旧文件以便回滚）。
- firefox divert：经apt时旧包postrm先撤销divert，新包preinst再建立，两个方向都正常；单独`dpkg -i`会冲突。新包preinst遇到`moto-firefox`的divert时报错说明，postrm只撤销自己的divert；使用Conflicts而非Breaks。
- **systemd单元的启用状态**：我们的生成器在prerm对`remove`执行`deb-systemd-helper disable`，postrm从不purge，用户单元每次configure都`--global enable`。结果是任何卸载再安装都会丢失管理员的启用/禁用选择，改名时同样如此。先发一个“桥接”的moto发布，把生成器改成debhelper的方式（prerm只停止、postrm在purge时清理、用户单元也由deb-systemd-helper管理），rungic包再在首次安装时按旧单元`was-enabled`设置新单元。管理员对旧单元的mask和`~/.config/systemd/user`中的覆盖需要单独迁移。
- 版本：`+rungic1`高于`+moto19`，低于Ubuntu的`0ubuntu0.2`；Ubuntu无改动重建（`build1`）排在两者之前，需构建`build1+rungic1`。

**Android**

- 项目只有一个APK：`dev.moto.plasma`。`dev.moto.VoiceAssistant`、`VoiceAgent`、`AgentScreen`等是容器内的D-Bus/QML/desktop名称，随容器阶段改。该APK不持有角色、无障碍、通知监听或省电豁免。
- 改applicationId会得到新UID和新的SELinux MCS类别；`moto-plasma start`每次启动都重新读取APK数据目录的标签，所以换APK后要重启容器。私有数据只有`shared_prefs/MainActivity.xml`（7项界面设置）需要迁移；Magisk su授权按UID记录，需要重新授权；悬浮窗权限当初是手动`appops set`的，需要重设；相机、麦克风由应用内请求。
- Java包一起改：`Activity.getPreferences()`按类名生成文件名，只改applicationId会把偏好文件名变成全限定类名；JNI只影响`OcrBridge`的4个符号，`com.winland.server.NativeBridge`保持不变。
- **镜像路径63字节限制**：toybox losetup把路径写入64字节的`lo_file_name`，超长时在`LOOP_SET_FD`之后才失败。`/data/adb/rungic-lxc/runtime/var/lib/lxc/plasma/images/rootfs.img`为65字节，所以镜像目录移到`/data/adb/rungic-lxc/images/`，`rootfs-image`增加长度检查。`/data/adb`、镜像与docker数据在同一f2fs上，目录改名是O(1)，不复制160G镜像。
- APK与Magisk脚本互相写死路径（APK调用`/data/adb/moto-plasma/moto-plasma`，enter程序绑定APK的`files/tmp`），因此改名要在容器停止、旧APK仍在时进行；旧APK用`pm uninstall`卸载，避免留下像`dev.moto.phosh`那样只删了APK、数据目录与su授权仍在的半删除包。
- Magisk引导脚本`tools/moto-magisk-bootstrap.*`在ROM中，只能随下次刷ROM改名。

## 分阶段计划

| 阶段 | 内容 | 验收 |
|---|---|---|
| A 主机工具（不改设备） | `tools/moto_*.py`→`rungic_*.py`，MCP服务改名`rungic` | 工具与MCP全部可用 |
| B0 桥接发布（moto名下） | 包生成器改为debhelper式单元管理 | 卸载重装后单元状态保留；冒烟验收 |
| B 容器侧 | `rungic-*`包与`rungic-release`；`/usr/share/rungic`、`/var/lib/rungic-*`（连同LXC配置中的挂载点）；`RUNGIC_*`环境变量；`com.rungic.*` D-Bus/desktop/快捷设置ID；用户目录与KDE配置迁移（kconf_update）；vendor重建`+rungic1`（KWin、plasma-mobile、Mesa、FFmpeg、Snapshot等）；显示名称（kcm-about-distrorc、主机名） | 完整验收；旧名残留检查；回滚到moto发布再前进 |
| C Android侧 | APK `com.rungic.plasma`；`/data/adb/rungic-*`与镜像新路径；enter程序；SELinux `rungic_image`/`rungic_docker`；dm名称；`debug.rungic.*`；APK与容器之间的socket文件名 | 桌面、触摸、GPU、相机/麦克风、投屏、OCR、docker；重启后仍正常 |
| D 清理 | 回滚窗口结束后purge `moto-*`残留；卸载旧APK；残留检查纳入`rungic-integrity` | 残留检查为零 |

## 进度

- **A（2026-09-26完成）**：11个主机Python工具改名，MCP服务改名为`rungic`（`.mcp.json`），引用它们的工具、文档与注释同步修改。`moto_*_enter.c`与Magisk引导脚本属于C阶段。新的MCP实例列出全部21个工具并调用成功，`rungic_release.py status`正常。
- **B0（2026-09-26完成）**：`tools/rungic_package.py`按debhelper 14的autoscripts生成单元脚本：postinst用`was-enabled`/`enable`/`update-state`（用户单元加`--user`，不再`systemctl --global enable`；不执行debhelper的遗留`unmask`，避免覆盖管理员的mask），prerm只在`remove`时停止系统单元，postrm只在`purge`时清理记录。带单元的4个包（bridges、diagnostics、session、voice-agent）重建后发布20260926.15，冒烟验收通过，全部10个单元保持启用。实测：禁用`moto-coredump.path`后`dpkg -r`再`dpkg -i`，仍为disabled（旧脚本会重新启用），随后恢复启用。
- **B（暂停，2026-09-26）**：用户决定先把上游组件改为补丁队列（docs/71），vendor中的改名等迁移完成后以修改补丁的方式进行。已完成的前置修复：快照回滚同时恢复部署改动的Android侧文件（`restore_android`，单元测试`tools/test_rungic_release.py`）。
- **B（2026-09-26恢复）**：用户要求继续改名。重新盘点后发现，上游组件里需要改的标识集中在6个组件：KWin（补丁中的`MotoDisplay`命名空间与注释；`moto-gpu-alloc`属C）、kscreen（`MotoDisplay`）、plasma-mobile（语音助手D-Bus名、`Moto:`注释）、plasma-settings（`/usr/bin/moto-platform`）、FFmpeg（编解码器名）、Snapshot（编码器与相机名）、typesafe-computer-use（`moto_cua`模块与路径）。用户决定先把这6个组件迁成补丁队列（docs/71第二批，提交`baef71f4`），改名时直接修改相应补丁，每条补丁仍只属于一个功能；其余vendor组件没有需要改的标识。

### B阶段的边界与步骤

**划分原则**：名称的读写两端都在容器（或主机工具）中的，在B改；Android侧（APK、原生宿主、Magisk脚本、SELinux、`/data/adb`）读写或创建的，留到C与APK一起改。启动脚本`/data/adb/moto-plasma/moto-plasma`与LXC配置随发布部署、回滚时一起恢复，它们引用的容器内程序与单元在B同步修改，文件本身的名称与位置留到C。

留到C的名称：APK包名与Java包（`dev.moto.plasma`、JNI符号、日志标签）；`/data/adb/moto-*`及其中的程序（`moto-plasma`启动脚本、enter程序、`moto-cast`投屏工具、`moto-wfd`）；Android侧创建的绑定挂载点`/var/lib/moto-host`、`/var/lib/moto-cores`、`/var/lib/moto-apt`（部署只重启会话，挂载点改名要等容器重启才生效）；LXC的`lxc.uts.name`；`/mnt/android-wayland`下APK提供的socket（如`moto-gpu-alloc`）；`debug.moto.*`；SELinux与dm名称；APK构建变量`MOTO_ANDROID_*`/`MOTO_APK_*`；原生宿主的`MOTO_GPU*`等。

**B的内容（一次发布）**：
1. 包：14个项目包`moto-X`→`rungic-X`，发布元包`moto-plasma-release`→`rungic-release`；各自对旧名写不带版本的`Conflicts`+`Replaces`（调研结论）。
2. 容器内文件与标识：程序、单元、`/usr/share/moto`→`/usr/share/rungic`、`/usr/lib/moto-*`、`/var/lib/moto-*`（上述挂载点除外）、`/etc/moto-*`、运行时文件（`/run/user/1000/moto-session.env`等）、`MOTO_*`环境变量、`dev.moto.*` D-Bus名称/desktop ID/快捷设置ID→`com.rungic.*`、GStreamer与FFmpeg元件名（`motoh264enc`→`rungich264enc`、`h264_moto`→`h264_rungic`）、C/C++/QML符号与命名空间、Rime插件、配色方案名。
3. 补丁队列组件重建为`+rungic1`（KWin、kscreen、plasma-mobile、plasma-settings）；FFmpeg、Snapshot、typesafe-computer-use随构建它们的项目包改名。其余vendor组件没有标识改动，版本后缀在它们迁入补丁队列、下次重建时一起改。
4. 状态迁移（复制而不是移动，旧数据保留，以便回滚到moto发布）：
   - 系统：旧单元的启用状态（B0后的`was-enabled`）带到新单元；`/var/lib/moto-*`、`/etc/moto-*`中的状态与改过的配置复制到新路径。
   - 用户：`~/.config/moto-*`、`~/.local/share/moto-*`、`~/.local/state/moto-*`复制到`rungic-*`；KDE配置中的desktop ID、快捷设置列表、全局快捷键、收藏、配色方案名用新的kconf_update脚本改写。`moto.upd`、`moto-voice-agent.upd`改名时，把`~/.config/kconf_updaterc`中已完成的记录搬到新文件名下，避免迁移重新执行（例如重新加回用户移除的快捷设置磁贴）。
5. 主机工具：设备上的路径和程序先试新名称，再试旧名称，保证回滚到moto发布后仍然可用。
6. 验收：完整验收；残留检查（容器中我们的文件与运行中的配置不再出现`moto`名称，C阶段名称与硬件名称除外）；回滚到`20260926.19`再前进一次，两个方向都验收会话与关键功能。


