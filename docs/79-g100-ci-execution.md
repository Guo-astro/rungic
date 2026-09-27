# G100 三段镜像 CI 首轮执行记录

2026-09-27，目标仅为 XT2533-4 / `portov_cn` / RETCN / `W1VT36H.1-51-8`，USB 序列号 `ZY32M9MRVP`。本篇记录本轮实际产物与验收；通用设计和放行条件见 [75 篇](75-image-build-separation.md)、[77 篇](77-g100-three-ci-assessment.md)，原厂输入核验见 [78 篇](78-g100-firmware-inventory.md)。运行材料位于 `.work/ci/runs/portov-20260927-86c6642d/`，不进入 Git。

## 操作前对照的已有经验

最新结果（2026-09-28）：`portov-20260928.5` 完整刷写并清数据后，用户确认重新安装正常进入 Plasma。问题与最佳解决路径的集中总结见 [80 篇实施复盘](80-g100-image-installation-retrospective.md)；以下按时间保留各候选当时的状态。

- [11 篇](11-stock-install.md)：Motorola bootloader 曾拒绝重封装 `super.img`；更新逻辑 `product` 应走 fastbootd，`oem fb_mode_set` 后转换前清标志。
- [12 篇](12-offline-magisk.md)、[13 篇](13-offline-magisk-user-app.md)：只给 `init_boot` 打补丁不能保证清数据后离线拥有完整 Magisk 运行环境；Magisk APK 不能放成系统应用，已验证方案是只读分区中的完整 APK 种子和 Magisk 自身的首启安装时序。
- [17 篇](17-lxc-installation.md)、[61 篇](61-delivery-diagnostics-plan.md)：原厂模块信任证书、真正的 `pivot_root`、rootfs ext4 与 loop/device-mapper 快照均有实机经验；不能用单独 namespace 探针代替 LXC 生命周期测试。
- [39 篇](39-magisk-daemon-crash.md)：Magisk 31.0 的 SQL NULL 查询会使守护进程崩溃，本轮没有向实机提交这类查询。

## CI1：GKI 候选

`profiles/devices/motorola/portov_cn/W1VT36H.1-51-8.json` 锁定原厂包、机型/固件指纹、Android/ARM64、内核 release、证书、纯净化白名单。GKI 上游为 Android common commit `86c6642d582ed37f3132f23728ec152157dc373f`，来源/许可证/补丁见 `packages/gki-android15-6.6/recipe.json`；GKI/Kleaf 源码在 `.work`，不跟踪上游树。使用与原厂相同的 `BUILD_NUMBER=14676406`、4 KiB 页与配置增量 `kernel/targets/gki/lxc_defconfig`。

第一次直接打开 IPC/namespace 加上额外 cgroup 配置，363 个原厂模块对照出现 9,768 个 CRC 不匹配，已拒绝。之后删除不必要的 cgroup 配置，并以 `task_struct` 原有的 Android KABI reserve 槽承载 SYSVIPC 字段（DEP-3 补丁队列）。最终报告 `gki/module-abi-lxc-kabi.json`：363 个原厂模块、20,741 个版本符号引用，其中 19,009 个能与 GKI 导出比对，**0 个 CRC 不匹配**；其余 1,732 个是 GKI 不导出的 OEM 间引用，不能误记为已经核验。

从同版本原厂 `boot` 的 Image 恢复原厂模块信任证书，候选 Image 只在证书区域内变化 1,098 字节；证据为 `gki/trust-report.json`。重封装的 `boot-candidate.img` SHA-256 为 `8a2aca1b9a6e98982e28d283d780031076260f8cac4a39a7f68217931e75f591`。在这台 G100 上使用 `fastboot boot` 临时启动成功，Android 完成开机、SELinux Enforcing、442 个模块已载入、Wi-Fi、摄像头服务、音频服务、KGSL 和触摸设备均在；`/proc/config.gz` 显示 SYSVIPC、POSIX_MQUEUE、IPC_NS、PID_NS、USER_NS、DEVTMPFS 已启用。Magisk root 下合并创建 mount/PID/IPC/network/UTS/user namespace 返回 uid 0。随后部署 LXC 6.0.4 和 Ubuntu 26.04/Plasma Mobile 6.6.5 候选，`lxc-info` 为 RUNNING，`kwin_wayland` 与 `plasmashell` 运行，Android 屏幕实际显示 Plasma 应用抽屉并响应滑动（`device/desktop-drawer.png`）。这证明临时组合可启动桌面；**还不是清数据后的一键包验收**。

## CI2：RungicOS ARM64 用户空间候选

在 x86_64 主机的私有 rootless Podman mount/user namespace 中注册 QEMU AArch64 binfmt，使用官方 Ubuntu 26.04 ARM64 OCI 基础层和 `tools/ci/arm64_chroot.py` 执行 ARM64 apt/dpkg。初试 PRoot 的系统文件绑定导致 `systemd` postinst 的原子改名遇到 EXDEV，已改为上述独立挂载命名空间的真 chroot。`plasma/ubuntu-packages.txt` 中已删除发行版不再提供的旧 `qtspeech6-speechd-plugin` 名称，改用当前 `qt6-speech-speechd-plugin`。基础 Plasma Mobile 6.6.5 与约 1,220 个依赖包已完成安装，`dpkg --audit` 仍需在全部定制包完成后复核。

Mac mini 仅作为原生 ARM64 软件包构建机：KWin、Mesa KGSL、Qt Multimedia、libcamera、Plasma Mobile/Keyboard/Camera、Portal 等固定配方及 14 个 Rungic 项目包已编译并收集至 `.work/apt/repo`。该仓库生成候选 `rungic-release=20260927.1`，56 个精确依赖；基础 Ubuntu 的 `kscreen` 精确版本从其已签名 APT 源补入池。`tools/rungic_release.py build --coupled-json` 可读取新 rootfs 中的三个 Plasma 耦合包版本，不依赖另一台正在运行的手机。Mozilla Firefox 采用官方签名 APT 源和既有 `plasma/mozilla.pref`，候选固定为 `156.0.1~build1`；未加该偏好时 apt 会错误选择 Ubuntu 的 snap 过渡包，模拟安装时已发现并修正。

定制包安装后共 1,430 个包，`dpkg --audit` 为空。`tools/ci/build_rootfs_image.py` 检查精确发布依赖、UID 1000 家目录属主、`e2fsck` 与包锁，产出 16 GiB 稀疏 ext4；修正早期 `/var/log/plasma` 缺失后的 v3 原始镜像 SHA-256 为 `b6ee481f652f0953332bd37a22061b0cae655ea46e8a3b392cdf840bd80e16c2`，gzip 种子 1,633,966,885 字节、SHA-256 `4b8b89ecff132d55dcc7b25636f011b9234e0818c1995f5bb553eb54a601abe1`。此前临时部署的是 v2，加日志目录与设备代理后通过上述桌面启动；**v3 尚待清数据首启验证**。完整 Ubuntu/Mozilla 依赖闭包仍需冻结包哈希并在干净目录重跑。

## CI3：原厂精简候选与 Magisk

`tools/ci/clean_product.py` 按上述 spec 对逐项核对过的 OEM EROFS 文件清单执行纯净化：仅删除 15 个明确哈希和包名的第三方预装目录及 8 个渠道配置文件，添加 `disabled-in-sku` 策略默认禁用三个出厂 AI 助手。保留 Android 核心服务、输入法及其他未验证可删项。候选 `product-clean.img` 为 4,830,572,544 字节、SHA-256 `b8862c0388216c396b7d0c12f1946dade10e2393c18e28c641db07130e0292ef`；已通过 `fsck.erofs` 和重提取静态核验。清数据后的手机上尚未验证这些包的最终启用状态。

Magisk 31.0 官方 APK SHA-256 为 `2c8a488b9a5293e578e95ae4f07e3c57aba4feec4a52ca4dd852a2692d6dd4e8`。本轮在**目标 G100 本机**用与当前固件匹配的 8 MiB 原厂 `init_boot.img` 修补，`KEEPFORCEENCRYPT=true`，候选 SHA-256 `3d83ee1c3f5166f4c4b47998c4c6530eeef2f5fb63504a983d3711d4b22e6084`。刷入槽 a 后 Android 正常启动；Magisk 首次要求在管理器中修复环境并重启，管理器/核心均为 31.0。Shell 授权开关初始关闭，开启后 `su -c id` 返回 uid 0、SELinux 仍 Enforcing。这只是该台手机的临时实机根权限链，**还不是清数据后免手工步骤的完整镜像**。

本轮一度并行运行 ADB 端口 5037/5038：USB G100 实际被默认 5037 接管，5038 只显示 Wi-Fi G100 S。已关闭多余 server 并恢复以精确序列号操作；以后不能把某个端口没有列出设备误判为启动失败。此经验已写入 `AGENTS.md`。

已用通用 `tools/ci/build_host_seed.py`、`assemble_product.py`、`assemble_release.py` 将 LXC、Rungic Android APK、Termux/PulseAudio、rootfs gzip 种子、Magisk 31.0 离线种子和首启脚本放入 `product`。最终 EROFS 大小 6,787,354,624 字节，低于本机 `product_a` 的 7,445,790,720 字节；SHA-256 为 `12d3a9fc9b38b8a1fddad7f64bc02c541cfcfdc131ca1d4b59a5759bf4948d9c`。`fsck.erofs`、原有 inode 权限/SELinux/mtime 元数据核对和刷机目录全文件 SHA 校验通过。完整目录绑定序列号 `ZY32M9MRVP`，包含原厂 32 个 super 分片、候选 boot/init_boot、AVB flags=3 派生镜像及 fastbootd 用 product sparse 镜像。此时仍是**离线候选**，不是已验收发行版。

首次完整试刷从 bootloader 开始。Motorola 的 `version-bootloader` fastboot 输出按 `[0]`/`[1]` 分段，拼接后比 Android `ro.bootloader` 少末尾一字符；脚本初版两次在任何写入前安全拒绝。修正后将实机 fastboot 原样值与 Android 属性分别写入运行实例并严格比对。bootloader 写入第一个原厂 `super` 分片后在第二片 USB 传输中失联，主机 `strace` 显示卡在 `USBDEVFS_REAPURB`、USB reset 后枚举报 `error -71`。用户恢复 bootloader 后改用 fastbootd 写入 32 片原厂 `super`，再写候选 `product`、GKI `boot` 和 Magisk `init_boot`；完整刷机命令成功返回。

但 Android 首启进入 Recovery 的“Cannot load Android system”。用户在 Recovery 执行恢复出厂设置，屏幕显示 `Data wipe complete`，再次启动仍进入 Recovery。只把 `init_boot` 换回原厂后 Android 能启动；刷入仅 Magisk 修补的 `init_boot` 后也能启动；加入原有 Magisk 离线种子引导脚本且不加 Rungic 自动部署触发器后同样能启动。这把故障范围缩到新增的 `init_boot` 触发器及其首启交互，不能据此断言具体是哪一行导致 Android 恢复模式。原组合在 Magisk overlay rc 加了 `on property:sys.boot_completed=1` 的 `exec_background`；修订版改为 Magisk 自身的 `service.d` 脚本等待 Android 完成开机，再执行 Rungic 种子部署。

当前设备上，使用上述可启动的仅种子引导镜像和临时修补后的首启脚本，已手工验证 rootfs 解压与 SHA、LXC 6.0.4 启动、Rungic APK 的账户设置界面出现。过程中发现 Magisk root 上下文的 `pm install`/`pm grant`/`appops set` 返回 Binder `Failed transaction (2147483646)`；修订版将 Termux 与 Rungic APK 预装进 `product/app`，用 `product/etc/default-permissions` 声明运行时权限。另修复了 Magisk BusyBox 锁文件调用、脚本 `PATH` 中的 `magiskpolicy`、以及 Android 应用文件目录的 UID/MCS 标签。手工部署只能证明这些局部路径可行，不代表清数据后一键安装与桌面已验收。

修订包 `portov-20260928.1` 的 `product` EROFS 为 6,826,098,688 字节，SHA-256 `1349f721562a937861c8f0a0f19cb9d5ed6ba695e7c180fe01f77877265b236a`；仅种子引导的 `init_boot` SHA-256 为 `f527b70fdf9f6e357d014f630a8e33e650d2711ea588bd06476d23e0f7b6f4e1`。`fsck.erofs`、原厂 inode 元数据核对、刷机目录全文件 SHA 和设备 spec 校验已通过。清数据实机复刷与完整验收仍在进行，不得提前清理构建缓存或宣称发行完成。

## v4 复刷失败后的分析更正（2026-09-28）

`release-v4-flash-console.log` 记录 32 个 super 分片、六个逻辑分区尺寸、26 段 product 写入、boot/init_boot 和 userdata/metadata 擦除均成功，刷机进程退出 0。fastbootd 转换约 61 秒，与 11 篇约 62 秒的既有经验相符。随后 ADB 枚举为 `recovery`，用户也确认进入 Recovery，**v4 仍未通过首启**。

不能再把之前的相关性写成已经定位的触发器故障：v4 同时改了 init_boot 脚本、product 预装方式并清空了数据，缺少相同数据状态下的单变量对照。当前候选方向包括 Magisk 离线引导在空白 /data 上的初始化、擦除后的 F2FS/加密初始化，以及 v4 product 新增的系统应用。自制 GKI 曾成功启动 Android 与桌面，其一般运行能力已有证据，但干净首启路径尚未单独排除。没有根因日志，不能仅根据 Recovery 的数据损坏提示断言文件系统损坏。

Recovery 的 `adb shell` 报 `Could not set SELinux context for subprocess`，`adb root` 被 production build 拒绝，文件同步读取 `/tmp/recovery.log` 与 `/cache/recovery/last_log` 被拒绝，`/sys/fs/pstore` 未取到文件。已有 `device/boot-logcat-after-firstboot-fail.txt` 中 PID 1045/4416 的 `init` SIGABRT 是子进程，不能误称 PID 1 崩溃；该日志后段 Android 已完成启动，也不能直接代表这次 v4 的失败现场。

后续诊断顺序：保留当前失败现场，优先取得 Recovery 启动原因；固定 v4 product、自制 GKI 与数据状态，仅将 init_boot 换为已验证的简单 Magisk或原厂版本作对照。若仍失败，再分别对照原厂 GKI 与 product；只有在相同启动组合下对照擦除和 Recovery 格式化，才能判断清数据方式的影响。排障阶段不再每次恢复整套 super 并清数据。根因明确后再跑完整一键清数据验收。

G100 S 的历史边界也须完整表述：11 篇确实验证了简单 Magisk、精简 product 与清数据首启；13 篇最终的离线种子方案通过移走运行文件和管理器来模拟首启，保留了其他用户数据。不能笼统说 G100 S 从未做过清数据测试，也不能把两次不同组合的验收合并成最终离线整包的全清验收。

## 固定其余分区的 init_boot 对照（2026-09-28）

用户授权后，从 Recovery 经 `adb -P 5037 -s ZY32M9MRVP reboot bootloader` 切换成功。核对 product=portov、sku=XT2533-4、current-slot=a、已解锁、bootloader 版本及电压 4357 mV，再校验简单 Magisk 镜像 SHA-256 `3d83ee1c3f5166f4c4b47998c4c6530eeef2f5fb63504a983d3711d4b22e6084`。仅写入 `init_boot_a` 并重启，没有擦除数据、改槽或重刷其他分区。写入日志为 `device/v4-compare-simple-initboot.log`。

用户确认 Android 已启动，USB 随后枚举为 Android 的 `22b8:2e82`。这证明当前自制 GKI、v4 product 与当前数据状态至少能够启动 Android，优先调查定制 init_boot 与简单 Magisk 镜像之间的差异。它还不能定位到某条脚本，也不能替代完整清数据首启验收；切换镜像前后的启动尝试可能已改变数据状态。当前等待重新开启 USB 调试，以采集系统、Magisk 和 Recovery 留存日志；不要先手工补装运行文件而覆盖诊断现场。

ADB 重新授权后实测 `sys.boot_completed=1`、SELinux Enforcing，init_boot 分区读回 SHA 与上述简单 Magisk 镜像一致。通过 Android shell 的 DropBox 和 root 采集日志，材料为 `device/v4-simple-*`。当时 `/data/adb` 只有授权数据库，Magisk 运行文件、service.d 和 Rungic 初始化日志均不存在。`/cache/magisk.log` 明确记录早期 `/data/adb is not present, abort`，随后仍有 `boot-complete triggered`。为读取 root 日志，仅将镜像内官方完整 Magisk APK 安装为普通应用并开启 Shell 授权；取消了管理器的“修复运行环境”操作。

随后保持所有其他分区和用户数据，只将**同一个** v4 init_boot (`f527b70…`) 刷回。Android 再次正常启动，这次 Magisk 离线运行文件成功初始化、service.d 启动，`sys.boot_completed=1`。证据为 `device/v4-compare-initialized-data.log`、`v4-initialized-root-diagnostics.txt` 和 `v4-initialized-dmesg.txt`。由此明确：v4 引导并非在所有启动条件下都会失败；故障与干净首启条件相关，尚未得到失败调用的直接日志。不可把“已有数据重启成功”标为“一键清数据首启修复”。

当前部署还暴露并修正了两个独立缺口：

- Termux 在种子执行前已创建空 `files/usr`，旧脚本直接拒绝。首启脚本改为仅允许 `rmdir` 删除空目录，对非空目录和符号链接仍拒绝；使用临时脚本续跑后，16 GiB rootfs 解压、整镜像 SHA 校验与种子部署于 00:54:48 完成，仍属手工修订后的验证。
- 预装 Rungic APK 首次启动报 `UnsatisfiedLinkError: libc++_shared.so not found`。APK 的 ARM64 JNI 库使用 ZIP 压缩，product/app 中缺少配套 `lib/arm64`，Termux 也有相同打包缺口。`assemble_product.py` 已增加从 APK 提取 ARM64 `.so` 到各自预装应用目录的通用逻辑，待重新组包验证。当前手机临时以 Android shell `pm install -r` 安装同一个 Rungic/Termux APK，JNI 问题消失并出现 Linux 账户设置界面；这不能替代修正后只读 product 的预装验收。

`product/etc/default-permissions/rungic.xml` 的相机、麦克风、通知、蓝牙和电话状态权限已在实机查询为 `GRANTED_BY_DEFAULT`。桌面显示与硬件回归尚未完成，完整清数据路径仍未放行。

## 首次账户设置的挂载前置条件（2026-09-28）

账户对话框反复提交失败，实际错误为 `bind Android audio socket directory: No such file or directory`。核对 `AccountSetup.java`、`MainActivity.control()`、`plasma/rungic-plasma` 和 `tools/rungic_plasma_enter.c`：`account-setup` 会先启动 LXC，入口固定绑定 Termux 的 `tmp/rungic-plasma-audio`；全新安装时目录尚不存在。普通桌面启动先执行 `android-audio start`，账户设置却没有这一步，因此在调用 Python 账户助手之前已退出，与用户输入的密码无关。

复用现有目录权限初始化：`plasma/android-audio` 增加 `prepare` 操作，仅准备目录；公共 `start_container()` 先执行它，再调用容器入口。两个脚本通过 `sh -n` 并部署到当前手机。用与 APK 相同的 `su --mount-master` 控制入口提交空 JSON，得到账户助手的预期用户名校验错误，未写入账户或密码；LXC 为 RUNNING，容器 `systemctl is-system-running` 为 running。此时 `account-status` 仍为 configured=false，等待用户在手机上提交，尚不能视为账户创建和桌面启动已验收。

此修复需随宿主种子重新打包；当前设备上的脚本修正不改变 v4 只读 product，也不解决前述干净首启 Recovery 问题。排查账户界面仅读取非密码 TextView，不保存用户输入框或凭据。

用户随后反馈账户设置已“搞定”。继续验收时，本机 ADB 5037 设备列表为空，USB 枚举也没有 Motorola 手机，未能重新读取 account-status 或桌面服务状态。当前记录为用户确认账户操作成功；桌面显示、服务与硬件回归待设备重新连接后核验，不能据此推断手机启动失败或整包验收完成。

## 账户与桌面基础验收（2026-09-28，重新连接后）

USB 恢复为 `ZY32M9MRVP` / XT2533-4 / portov 后完成以下检查，原始材料保存在 `device/v4-account-acceptance.txt`、`v4-account-desktop.png`、`v4-account-drawer.png`、`v4-purity-acceptance.json`、`v4-ai-package-state.txt`：

- `account-status` 为 configured=true，UID 1000 的账户与家目录均已更新；不读取或记录密码。
- Android `sys.boot_completed=1`、SELinux Enforcing；LXC RUNNING，容器 systemd 为 running，系统级和 UID 1000 用户级 failed units 均为 0，`dpkg --audit` 无输出。
- KWin 与 plasmashell 运行；实际截图显示 Plasma 桌面，ADB 注入滑动后应用抽屉正确显示，验证本次会话的显示与滑动输入通路。尚不等于实体触屏、全部应用或硬件验收。
- 内存限制 4096 MiB，首次采样使用 2594 MiB、峰值 3777 MiB；rootfs 为 16 GiB，已用约 3.7 GiB，宿主 /data 约余 210 GiB。
- 专用音频服务可查询，`android_output` 使用 `module-sles-sink`；空闲 SUSPENDED 为当前观测，本轮未播放或录音，不能记为声音验收通过。
- spec 的 15 个第三方预装包均不在当前用户已安装列表。三个出厂 AI 包仍保留在只读分区，用户 0 的状态全部为 `installed=false stopped=true notLaunched=true`；这是 SKU 排除安装策略已生效，不能误写成 APK 已删除或 `enabled=disabled-user`。

结论：当前经手工修订的安装已通过账户创建、桌面显示与基础运行检查。仍需将宿主脚本/JNI 修正纳入新包，解决干净首启 Recovery 问题并完成整包复测和硬件回归；保留诊断材料及必要构建缓存，不把当前结果标记为完整 CI 发行验收。

## v5 首启时序修订与组包（2026-09-28）

用户明确授权完成本轮完整一键包。核查官方 Magisk v31.0 `native/src/core/bootstages.rs`：Android API≥24 且 /data/adb 不存在时，post-fs-data 明确退出；boot-complete 才创建该目录，注释说明此时才安全。`native/src/init/rootdir.cpp` 把自定义 rc 插在主 init.rc 后、Magisk 自身 rc 前。Android16 的 init.rc 及设备实际 rc 包含 installkey、init_user0 等初始化；没有取得上次失败调用的直接日志，因此仍不把某个加密调用当作已证实根因。来源为 [Magisk v31.0](https://github.com/topjohnwu/Magisk/tree/v31.0)（GPL-3.0）和 [AOSP Android16 init.rc](https://android.googlesource.com/platform/system/core/+/refs/heads/android16-release/rootdir/init.rc)（Apache-2.0）；固定源码副本、哈希与选用理由位于 `.work/refs/magisk-firstboot-20260928/`。

v5 复用官方完整 APK 安装和 Magisk 生命周期，不修改 Magisk 二进制：早期若缺少 /data/adb，只在 ramdisk tmpfs 记下延迟标志；Android 完成启动后由独立 oneshot 服务准备运行文件、安装下次启动的 service.d 入口并自动重启一次。下次启动已有 /data/adb，不再设置临时标志；Rungic 种子由 Magisk service.d 等 Android 开机完成后部署。与直接提前创建目录相比，此方案遵守上游的干净数据保护；额外成本为首次安装的一次自动重启。**该变更正在组包，尚待完整清数据实测，不能提前记作已修复。**

v5 同时纳入 Termux 空目录处理、APK ARM64 JNI 预装、账户启动音频目录准备；发行组装增加 rootfs/宿主种子/init_boot 报告与载荷哈希交叉核验、包锁、内核 ABI 报告及 `flash.sh` 入口。待刷版本 `portov-20260928.2`。刷前只读预检通过，电量 100%；账户和家目录备份位于本机 `.work/secrets/g100-before-v5/`，权限 0700/0600，不进入发行包或 Git。

### 组包前的自动回归与 rootfs 依赖修正

对当前手工修订安装运行 smoke，报告 `.work/acceptance/portov-v4-diagnostic/20260928-013026/report.json`：会话、服务、无新崩溃、1080×2400/120 Hz 显示、Wayland 亮屏租约及释放、默认声音输出和麦克风非零采样通过。`input.text` 的失败来自验收 OCR 进程导入 `requests` 失败，不能解释为触屏或键盘故障。设备 venv 的 `pip check` 发现 requests/anyio/sniffio/typing-extensions/distro/httpx 未随包声明；`--system-site-packages` 在已有构建机上掩盖了缺口。按 [Python venv](https://docs.python.org/3/library/venv.html) 和 [pip install](https://pip.pypa.io/en/stable/cli/pip_install/) 的依赖行为核查后，补入 Debian Depends，保留原 venv 和系统 gi/onnxruntime；无需重写 OCR。干净 rootfs 补入对应 Ubuntu 包后 `pip check` 返回 No broken requirements found。新构建 rungic-cua=0.280、rungic-plasma-session=0.281，rootfs 发布版本 20260928.1；替代旧 rootfs 后重新组包，旧 v5 product 不作为最终发行。

摄像头测试收到递增时间戳但画面接近全黑，原检测未通过；用户随后明确要求本轮跳过摄像头验收（手机在卧室）。后续报告显式记录 camera.frames 的用户排除及原因，不再启动摄像头，不把它记成通过。声学质量、真实触屏手感和外部投屏仍不由自动探针代替。

补齐系统依赖后再次运行 smoke（报告 `.work/acceptance/portov-v4-diagnostic-deps/20260928-013731/report.json`），8 项通过，camera.frames 按用户要求显式 SKIP，failed_ids 为空。该报告仅证明修订依赖在当前安装上工作，不替代新包清数据验收。最终待刷候选版本更新为 `portov-20260928.3`，rootfs=20260928.1（1450 个包，16 GiB ext4，fsck=0；SHA-256 `43d565d8c48f4368fff3eb4f9287b0588ae0579ccab4abac4237ee0aa7823633`）。`init_boot` 延迟初始化版本 SHA-256 为 `0d6df906961a66c2f9ede6f4d2a47b78a175eaddfb6f4a4cb37bc815738fdfcc`。

`tools/ci/test_magisk_bootstrap.py` 隔离验证：空白数据早期不创建任何 /data 文件，未完成启动的 late 调用拒绝执行，late 准备种子后仅发出一次重启请求，重复调用不重复请求，已有升级文件保持原内容而缺失文件得到补齐。测试不代替 Android SELinux 或真实冷启动验证。`tools/ci/accept_release.py` 增加刷后只读检查，包括各分区实际内容哈希、首启完成与种子摘要、Magisk 官方 env_check/普通应用/完整 APK、预装应用直接位于 product、纯净化状态、账户和容器依赖。

## portov-20260928.3 完整刷写开始

新 product 为 6,938,972,160 字节（分区余量 506,818,560 字节），SHA-256 `43cf711aeef866d27504d3af71180c81c5e51fecceb19c47b97b3adc630d0f3d`。EROFS fsck、原厂元数据保持、所有输入报告交叉核验及发行目录 55 个文件的 SHA 校验通过。发行组装源码提交 `bf2f52383f9274b0bdb4fd24c5c750edb442b58f`；目录为 `.work/ci/runs/portov-20260927-86c6642d/release/portov-20260928.3/`。

再次核对 USB 序列号、XT2533-4、电量 100% 后停止 LXC，同步数据并自动重启到 bootloader。使用发行包自身 `flash.py --serial ZY32M9MRVP --yes-wipe` 开始完整刷写；fastbootd 转换成功，正在顺序写入原厂分片。此段只记录刷写已开始，首启/安装/桌面验收尚未完成。日志为 `release-v6-flash-console.log` 和发行目录 `flash.log`；状态 `device/v6-release-status.json` 仍禁止清理缓存。

### 清数据首启结果及首次账户重试

`portov-20260928.3` 发行包自身刷写器完成全部分片、product 和启动分区写入及 userdata/metadata 擦除，退出码 0。实机日志显示 01:55:54 完成延迟 Magisk 种子准备，随后自动重启；01:57:01 开始 Rungic 种子，01:58:56 完成。用户确认 Android 启动和 Magisk 正常；`device/v6-firstboot-diagnostics.txt` 保存启动日志。此次确实通过清数据首启，未人工替换 init_boot 或修复 Magisk，但不据此断言前版失败的具体加密调用。

用户首次提交账户时报告 `bind shared ... no such file`。源码将该错误定位到 `/storage/emulated/0/Plasma` → 控制环境 `/mnt/plasma-shared` 的挂载；检查时两端均存在，同一 `--mount-master` 入口已经能启动 LXC，并对空 JSON 返回预期用户名校验错误。随后用户重试成功，configured=true、UID=1000。未捕获首次报错的时间或目录状态，因此“首次部署未结束”和“共享存储挂载可用时序”仍是可能原因，不能记为已证明。没有重设密码或手工创建账户。安装检查 `device/v6-install-acceptance-configured.json` 全部通过：三个实机分区摘要、种子、完整普通 Magisk APK/环境、直接 product 预装、纯净化、账户、systemd、dpkg/pip。

补强公共控制入口：当 product 存在种子时，账户查询/创建和桌面启动要求完成标记与本次 release 一致；未完成时显示安装状态提示。容器启动检查 Android 共享存储已可用，再幂等准备 Plasma 共享目录。隔离执行实际控制脚本覆盖无 product 种子的旧部署、未完成、旧版本标记和完成四种状态；shell 语法检查通过。该改动进入后续 `.4` 候选，不能把 `.3` 的分区摘要写成新候选摘要。

首次 smoke 的 `input.text` 未通过：原工具固定从 y=2000 滑动，在本机当前桌面布局落入底部导航区域。实际从桌面内部 y=1700 滑动后，AT-SPI 已能取得 Search 输入框；修改主机验收工具按 Android 屏幕尺寸从 70% 高度滑向 25%，保留原有抽屉稳定/实际文字输入/OCR 检查。其余会话、显示、声音项目通过，摄像头依用户要求 SKIP；完整报告保留在 `.work/acceptance/portov-20260928.3/20260928-020410/`，修订后的复测另行记录。

### 用户收窄本轮验证范围

2026-09-28 用户明确要求停止其他功能验收，优先保证重启后正常显示桌面、打开 Plasma Mobile 和创建用户。本轮后续仅围绕启动/首启/账户三条链路，不再运行音视频或其他功能 smoke。之前已产生的报告保留；修正滑动起点后的 `.3` smoke 8 项通过、摄像头 SKIP（020634），不继续扩大范围。

`.4` 控制脚本已在当前安装测试共享目录缺失恢复：停止容器后，仅在目录为空时 `rmdir /storage/emulated/0/Plasma`，再次正常启动自动重建目录，返回 `Plasma Mobile ready (native Wayland)`；账户仍为 configured=true。证据 `device/v7-controller-recreation.log`。随后开始不清数据的整机重启检查。`.4` product 正在重新生成；不把当前运行中的脚本修改描述为已刷入新的只读镜像。

### 首次安装等待界面与账号放行（替代普通重启验证方案）

用户再次明确：需要验证**完整一键包清数据刷入 → 首启初始化 → 创建用户 → Plasma 桌面**，普通重启或对已有账户的增量部署不能代替。撤回以保留数据更新 `.4` 作为最终验证的计划；`.4` 仅保留诊断产物，后续 `.5` 候选纳入真正的首次安装等待界面，必须重新走整包刷入路径。

方案复用 Android 原生 ProgressBar（[官方接口](https://developer.android.com/reference/android/widget/ProgressBar)）和应用私有文件，不引入下载器或新的后台服务。未知耗时的阶段显示不定进度动画和实际阶段文字，不显示虚构百分比。Magisk 的首启服务继续负责部署；应用只读取原子发布的 `rungic-install.properties`（release/state/phase，不含凭据），无需先弹 su 授权。状态与 product 的 release 必须一致。所有载荷校验、展开、目录/权限和挂载预检完成，写入 root 完成标记并授权应用后，才发布 ready。root 控制器仍独立校验完成标记，UI 状态不是安全授权。

APK 2.6 在 surface 初始化与账号查询前等待 ready，未就绪持续轮询，退出/重新打开可恢复；显式失败显示安装未完成提示，不进入账户表单。首次 ready 后调用公共 `account-prepare`，提前启动容器并等待 systemd/账户工具/UID 1000/共享目录就绪，才显示用户名密码表单；创建完成后显示桌面启动 loading，桌面可用才移除遮罩。首启服务等待真实 Android 存储就绪，不在未挂载目录下创建共享文件。

边界检查覆盖旧部署、状态缺失、旧 release ready、六个安装阶段、失败、截断和格式错误，均不提前放行。当前设备上的受控状态测试显示“正在展开系统镜像，首次安装需要几分钟…”并阻止账号界面；发布 ready 后自动继续进入 Plasma 欢迎界面。此为已有数据的 UI 验证，图片 `device/v8-install-loading.png`、`v8-loading-to-desktop.png`；新包的清数据流程尚待刷入。

`.5` product 已生成：6,938,972,160 字节，SHA-256 `42d540c7d0f406eb6b5f88017a35c82154968816c483f307885e63cdd60bc3a1`；host seed SHA-256 `cf69c6b3e5de7e15443f23cfd366ca57ed959ef37475ee1cc0b7e2ebf3d83ee8`，APK 2.6/54。GKI、init_boot、共同 rootfs 与 `.3` 相同。本地组装提交 `e1f862aa`，目录 `release/portov-20260928.5`；当前账户/家目录另备份到 `.work/secrets/g100-before-loading-release/`，gzip 检查通过，备份不进入发行包。于 02:22 开始用 `.5` 自带 flash.py 再次执行完整刷入及清数据，尚未报告通过。日志 `release-v8-flash-console.log`。

### 刷写进度与手机端显示的边界

`.5` 完整刷写（32 个原厂 super 分片、定制 product、GKI/init_boot、userdata/metadata 擦除）在 02:31 完成，进程退出 0；正在等待新系统首次配置结果，不据此宣布整个流程成功。

用户指出原厂 fastbootd 手机上没有进度，容易误以为卡死。核查发现电脑工具另有一个缺口：`subprocess.run(capture_output=True)` 把整条大分区命令的输出积到结束才显示。已改为流式转发发送/写入确认，增加八个阶段、分片编号、无输出期间的等待说明，并保留超时中止。隔离假设备测试验证命令结束前日志已可见、超时和设备拒绝均停止、Motorola 分段 bootloader 信息仍可解析。此变化只影响主机工具，设备镜像不变；不能写成已解决手机屏幕进度。

手机端源码调研：AOSP `system/core` android16-release 的 `fastboot/device/{commands,fastboot_device}.cpp` 将 INFO/OKAY/FAIL 写回 USB；`bootable/recovery` main 的 `fastboot/fastboot.cpp` 显示菜单，`recovery_ui/ui.h` 已提供 Print/SetProgress，`recovery_main.cpp` 的现有 recovery socket 只接 r/f 模式切换。本地源码副本位于 `.work/refs/fastboot-progress-20260928/`，许可证 Apache-2.0。结论是可复用 RecoveryUI 做手机日志/进度，但要连接 fastbootd 的真实传输/刷写事件；原厂 Motorola 的对应接口、二进制兼容和恢复镜像适配尚未核实，不能宣称已有可直接启用的手机日志开关，也不能把普通 INFO 输出当作屏幕输出。本轮 recovery 仍使用已核验原厂镜像。

### 最终用户反馈（2026-09-28）

用户确认：“重新安装之后，已经正常进入 Plasma 的界面了，我觉得效果挺好。”据此将 `.5` 的末端结果更新为**完整刷写及清数据后，用户确认正常进入 Plasma**。此反馈替代上面的“等待首次配置结果”；不将 `.3` 的设备探针报告算作 `.5` 的新报告，也不补写未单独记录的账户 UID 或其他硬件验收。手机端刷写进度、独立发行归档及部署后的缓存清理仍按各自状态跟踪。

应用户要求，问题、修复依据和后续可复用路径集中整理在 [80 篇](80-g100-image-installation-retrospective.md)。
