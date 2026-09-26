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

### B阶段实施（2026-09-26）

提交`c65f7ef9`（改名）与`a5b9d781`（残留验收）。先用`tools/rebrand.py`按规则整体替换，再逐区人工审查。规则无法区分、审查后恢复为原名的有：
- **迁移代码要读取的旧状态**：kconf_update迁移脚本里旧工具写下的标记与备份名、旧的`/usr/local`路径与drop-in名、各包`obsolete`列表中的历史路径。
- **Android侧的名称**：Termux PulseAudio的`moto-plasma-audio`目录（enter程序中写死）、APK的logcat标签`MotoWayland`/`MotoPlasma`、ROM与产品分区工具（主机上的真实目录、增量文件格式标识）、`lxc/`、`docker/`、`shared/android/`。
- **Motorola自己的名称**：如`MotoPrcPermissionService`。
- **历史**：`plasma/*.patch`等导入证据、补丁标题中的`KWin moto15`等构建名。

规则漏掉、审查时补改的有：FFmpeg编解码器的注册名与`wrapper_name`、D-Bus对象路径`/com/rungic/*`、APT仓库的Origin/Label与pin、`Rungic.Rime` QML模块、`preferences.d`文件名、元包名`rungic-release`、显示文字与版权行。

**包与系统状态**：`package.json`的`formerly`生成对旧包名不带版本的`Conflicts`+`Replaces`；首次安装时，若旧单元有记录且被管理员禁用，新单元保持禁用，否则启用。本机手工放置的APT代理`80moto-proxy`由`rungic-plasma-config`复制为`80rungic-proxy`（旧文件保留）。旧包的conffile在rc状态下保留，内容与新文件相同，直到D阶段purge。

**用户状态**：`/home`不在rootfs快照中，快照回滚也不会带回。`plasma/rebrand-user.py`（安装为`/usr/libexec/rungic-rebrand-user`）双向迁移：
- `up`：会话脚本在kconf_update之前运行一次（标记`~/.local/state/rungic-rebrand`）。把KDE配置与Codex配置中的名称（快捷设置磁贴、desktop ID、输入法路径、相机ID、MCP服务与命令）换成新名称；把`~/.config`、`~/.local/share`、`~/.local/state`下的目录复制到新名称（旧目录保留）；Codex技能链接改为新名称；把`kconf_updaterc`中`moto.upd`、`moto-voice-agent.upd`的完成记录复制到新文件名下，已执行的迁移不再重复。
- `down`：`rungic_release.py`在部署或快照回滚到改名前的发布（元包`moto-plasma-release`）之前运行，先停会话（程序退出时会写回设置），把名称换回，把新目录中改名后变化的内容复制回旧目录并删除新目录。
- 单元测试`tools/test_rebrand_user.py`覆盖往返：`up`→修改→`down`后配置与原来逐字节相同，修改被带回。

**桌面账户**（用户要求，2026-09-26）：home跟随登录名，为`/home/<登录名>`，首次启动时用户在账户设置中选定用户名后即生效；主组固定为`rungic`（NetworkManager的D-Bus策略按组名授权，不能随用户名变）；首次设置前的占位登录名为`rungic`（home为`/home/rungic`）。改名前一律是`/home/linux`、组`linux`、占位登录名`linux`。
- 首次账户设置（`plasma/account/setup.py`）改登录名时用`usermod --login --home --move-home`一起移动home（事先停止会话、用户管理器与挂在home中的共享存储；目标目录已存在时拒绝），再以该用户运行`rungic-rebrand-user rehome`改写设置中指向旧home的路径；失败时连同home一起退回。
- 会话脚本、会话单元（`WorkingDirectory=~`）、共享存储都在运行时从`getent passwd 1000`取home，不再写死路径。
- 已有系统由`plasma/rebrand-system.sh`（`/usr/libexec/rungic-rebrand-system up|down`）迁移：`/home`在Android侧，不在快照中。容器init在任何服务启动前执行`up`（组改名、占位登录名改名、home移到`/home/<登录名>`，本机为`/home/kevinzhow`）；`down`由`rungic_release.py`在用户设置迁回之后、停掉用户管理器与共享存储后执行，把home移回`/home/linux`并改回组名。从`/home/linux`移出的系统在D阶段之前保留`/home/linux`链接，供应用数据中的绝对路径使用；KDE设置、文件对话框位置与GTK书签中的路径由`rungic-rebrand-user`改写（home本身以及其下的路径都会改，前缀相同的其他目录不受影响）。
- 在Ubuntu容器中模拟了已配置账户、占位账户、首次设置改名、再回滚四种情况；账户设置与设置迁移都有单元测试。

**主机工具**：`rungic_device.prog()`/`first_path()`先用新名称，找不到时用旧名称；部署、验收与诊断工具据此在回滚后的旧发布上仍可用（发布元包名按目标发布选择，关键单元、相机节点、编解码器名均兼容两种名称）。

### B阶段首次部署与快照回滚事故（2026-09-27）

发布`20260927.1`三次部署都没有完成，手机回到`20260926.20`：
1. APT拒绝仓库Origin由`moto`变为`rungic`，安装前中止。`rungic_release.py`的`apt-get update`加上`--allow-releaseinfo-change`（仓库是本项目本地的可信源）。
2. 包全部装上，重启容器后桌面没有就绪，验收失败，自动回滚到快照。原因未查明：证据包没有会话与KWin的用户日志。
3. 再次部署时，删除`moto-cua`文件时dpkg报ext4 `Structure needs cleaning`。第2次的快照回滚没有恢复被重写的块：第2次部署删除`moto-cua`、`moto-codec`、`moto-codex`后，这些块被新包复用。第2次部署开始时完整性检查为clean，回滚后为drift。只读`e2fsck -fn`发现76个目录损坏，`e2fsck -fy`修复（456个无主文件进入`lost+found`），按原版本重装这3个包后`moto-integrity`恢复clean，smoke验收通过。home在Android侧，不受影响。

**快照回滚的根因尚未查明。** `plasma/rootfs-image`的`detach`原来先删快照再删origin，`attach`先建origin再建快照，都留有“origin上没有快照”的窗口；`tools/rootfs_rollback_test.sh`在测试镜像上演示了：设备仍被占用时，旧代码会删掉快照、origin却删不掉。但事故中的那次停止打印了“stopped”（`set -eu`下`detach`失败不会打印），说明当时并未发生这种情况；测试镜像在私有挂载命名空间下，新旧代码都没有复现损坏。已做的防护：
- `detach`先删origin（被占用时等待，最多30秒，超时即失败），再删快照；`attach`先建快照再建origin；origin已存在而快照缺失时拒绝继续。
- `rungic_release.py`的三处快照回滚统一为`rollback_to_snapshot()`：回到改名前的发布时先`rebrand_down`（原来验收失败的回滚路径缺这一步，第2次回滚后home留在了`/home/kevinzhow`，已手工移回）；回滚后比较内核的ext4错误数并运行完整性检查，结果写入部署记录。
- 在查明之前，B阶段的部署不依赖快照回滚：以`--acceptance none`部署并保留现场，需要退回时按包回滚（部署上一个发布）。

### B阶段部署与验收（2026-09-27，发布`20260927.5`）

从`20260926.20`升级到`20260927.5`，再按包回滚到`20260926.20`，最后升级回`20260927.5`，两个方向都通过。最终的完整验收18项中17项通过；`recording.quicksetting`是已知的收尾超时（pulsesrc EOS），单独重跑一次通过。`rebrand.residue`通过：已安装的包、单元和包名中都不再有`moto`名称，剩下的只有已移除的`moto-plasma-config`留下的conffile（D阶段purge）和C阶段的名称。home为`/home/kevinzhow`，组为`rungic`，用户设置已是新名称，4个系统单元与6个用户单元都已启用。

部署中发现并已修正的问题：
- APT拒绝仓库Origin变化：`apt-get update --allow-releaseinfo-change`。
- 改名后的系统单元全部是disabled（桌面不启动）：旧包已被移除、旧的启用链接已被obsolete清理，`was-enabled`无法判断旧单元。改为读取deb-systemd-helper的记录（`.dsh-also`及其链接镜像），继承后purge旧记录；在容器中验证了5种情况。
- 用户设置迁移没有执行：`kconf_updaterc`第一行是不属于任何组的键，configparser拒绝读取。改为按KDE配置格式读取；首次设置步骤已按新名称重新执行过时，重复的节会删除旧节，快捷设置列表会去重。
- `libmotocodec`、`libgstmotocodec`的库名没有改（规则要求`moto`前不是字母），而GStreamer按插件文件名查找入口符号，编码器因此全部不可用；package.json描述中`\n`后的名称同理。
- `packages.json`中残留的`version`字段，把plasma-mobile、plasma-settings、kscreen钉在了`+moto`构建上，旧的录屏快捷设置去调用已删除的程序。补丁队列组件的版本改为一律取changelog。
- 桌面仍在运行时移除旧包，plasmashell会把桌面文件已被删除的收藏（语音助手）清理掉。现在跨越改名升级时先停止桌面；本机已手工补回该收藏。
- 按包回滚到较早的发布需要检出其提交：部署时Android侧文件改从发布的提交中读取，并按sha256核对。
- 另见上一节的快照回滚事故，那次回滚也没有执行`rebrand_down`，已修正。

新出现的崩溃：`9891060f148d`（plasmashell在KWayland客户端处理Wayland事件时SIGSEGV），发生在完整验收的录屏场景中，只出现过一次，重跑没有复现。


### C阶段方案（2026-09-27）

盘点（设备与仓库）：APK `dev.moto.plasma`（UID 10352；私有数据只有`shared_prefs/MainActivity.xml`；相机、麦克风运行时授权，悬浮窗`appops`，Magisk su授权）；`/data/adb/moto-plasma`（启动脚本、enter程序、`rootfs-image`、挂载hook、音频桥、SELinux规则）；`/data/adb/moto-lxc`（LXC控制环境，含plasma的镜像`images/`与`state/{home,host,moto-cores,moto-apt}`，以及alpine与已停用的phosh）；`/data/adb/moto-wfd`（投屏工具`moto-cast`与jar）；`/data/adb/moto-docker`（独立运行、开机自启）；`service.d`中3个脚本；Termux音频目录`moto-plasma-audio`；APK提供给KWin的`moto-gpu-alloc` socket；`debug.moto.*`属性；镜像当前状态`none`（无快照）。

**两步切换，分开验收**

1. **C1 Android侧切换（容器发布不变，仍是`20260927.5`）**：新APK `com.rungic.plasma`与新的`/data/adb/rungic-*`布局一次切换。新的启动脚本、LXC配置和APK在D之前向旧名称兼容：状态目录同时挂载到`/var/lib/rungic-*`和`/var/lib/moto-*`，APK在`rungic-gpu-alloc`旁放一个`moto-gpu-alloc`链接。因此`20260927.5`及更早的容器发布在新布局上照常运行，C1可以单独验收。
2. **C2 容器发布**：容器改用`/var/lib/rungic-{host,cores,apt}`，KWin改连`rungic-gpu-alloc`（重建`+rungic2`），APT源、账户、诊断随之修改。按包回滚到C1之前的容器发布仍可用（上面的兼容挂载）；这种回滚跳过旧发布中`/data/adb/moto-*`路径的Android侧文件，保留当前（向后兼容的）启动脚本。发布在Android侧还是旧布局的设备上部署时拒绝，提示先切换。
3. Docker（`rungic-docker`、SELinux `rungic_docker*`）与APK无关，C1、C2验收后单独切换，需要在停止状态下`chcon -R`整个runtime与数据镜像。

**C1步骤**（`tools/rungic_cutover.py up`，每步记录到`.work/cutover/`，`down`按相反顺序恢复）：
1. 留存现状：`dumpsys package`、`appops get`、`rootfs-image status`、`/data/adb`列表；要求镜像状态`none`。
2. 停止：`moto-plasma stop`（容器、镜像、音频），确认无`moto-plasma-root`、镜像无loop；停止alpine；`am force-stop`旧APK与投屏监视进程。
3. 目录改名（同一f2fs，O(1)）：`moto-plasma`→`rungic-plasma`，`moto-lxc`→`rungic-lxc`，`moto-wfd`→`rungic-wfd`；镜像目录移到`/data/adb/rungic-lxc/images/`（`rootfs-image`检查路径不超过63字节）；`state/moto-{cores,apt}`→`state/rungic-*`。
4. 安装新文件：启动脚本`rungic-plasma`、enter程序（NDK静态编译）、`rootfs-image`（dm `rungic-root`/`rungic-before`，SELinux `rungic_image`，下次attach时chcon）、挂载hook、音频桥（Termux目录`rungic-plasma-audio`）、LXC配置（主机名`rungic`）、`rungic-lxc`、`rungic-cast`；`service.d`中换成`rungic-cast-watch.sh`与`rungic-wfd-sepolicy.sh`。
5. APK：安装`com.rungic.plasma`；复制`MainActivity.xml`；`pm grant`相机、麦克风；`appops set SYSTEM_ALERT_WINDOW allow`；Magisk授权用`magisk --sqlite "INSERT OR REPLACE INTO policies (uid,policy,until,logging,notification) VALUES(<uid>,2,0,1,1)"`（不返回行，不触发docs/39的NULL问题；不执行`SELECT *`与`PRAGMA`）；旧APK `pm disable-user`（保留数据与授权供`down`，D阶段卸载）。
6. 启动新APK，验收：桌面、触摸、GPU、音频、相机/麦克风、投屏、OCR、Android侧残留检查；重启手机后再验收一次。

主屏上的APK图标需要用户重新放置。ROM中的Magisk引导脚本在仓库中改名为`tools/rungic-magisk-bootstrap.*`，随下次刷ROM生效。

### C1部署与验收（2026-09-27）

`tools/rungic_cutover.py up`一次完成（记录`.work/cutover/20260927-043656-up`）：安装APK 2.0约3分钟（无线adb），停止到桌面就绪共约80秒，新APK启动后9秒桌面就绪。新APK UID为10350，悬浮窗、相机、麦克风与Magisk授权都已生效，没有弹出授权提示；旧APK已停用，数据与授权保留供`down`使用。镜像标签为`rungic_image`，dm设备为`rungic-root`；容器同时挂载`/var/lib/rungic-*`和旧名；`moto-gpu-alloc`链接可用。

在容器发布仍为`20260927.5`的情况下跑完整验收：18项中17项通过，Android侧残留检查通过（剩下的都属于Docker、D阶段或ROM）。`rungic-lxc status`（alpine）、`rungic-cast status`和Termux中的`lxc`快捷方式都可用。

发现并已修正：`pkill`只结束了旧投屏监视进程的读取子进程，父进程阻塞在logcat管道上，没有退出（已手动结束，工具改为先结束其子进程）。

未通过的`recording.quicksetting`：停止录屏时`pulsesrc`（系统声音）的EOS没有返回，收尾12秒超时。切换前`20260926.20`和`20260927.5`上已出现同样的失败（`.5`上重跑一次通过），切换后连续3次失败。单独用`gst-launch-1.0 -e pulsesrc device=android.monitor`测试时EOS正常，问题在录屏管线内部，与改名无关，另行处理。

还未做：重启手机后的验收。手机通过无线调试连接，重启后端口会变化，可能需要用户重新打开无线调试，所以等用户在场时进行。
