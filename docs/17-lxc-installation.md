# LXC 实机部署与验证（2026-09-22）

> 改名说明（2026-09-27）：Rungic改名C阶段之后，`/data/adb/moto-lxc`、`moto-lxc`、`moto-lxc-enter`改为`/data/adb/rungic-lxc`、`rungic-lxc`、`rungic-lxc-enter`（enter程序改用NDK静态编译，`tools/build_enter.sh`），Alpine主机名`rungic-alpine`。对照见[70篇](70-rungic-rebrand.md)。下文按时间记录的内容保留当时的名称。

**已在原厂 Android 16 上运行 LXC 6.0.4 + Alpine 3.22.6 ARM64 容器。** 内核已刷入，容器已安装，当前 `alpine` 为 RUNNING。SELinux 全程 Enforcing；Magisk 31.0 的 `init_boot_a` 未改变。

这是第一个可用的最小容器版本：支持启动、进入、执行命令、交互终端、正常停止和持久化。网络目前只有独立 namespace 内的 loopback；没有配置外网、端口映射、CPU/内存配额或自动启动。

## 设备与最终状态

| 项目 | 实测结果 |
|---|---|
| 设备 | Motorola XT2537-4 / mumba_cn，ZY32MVJS25，slot a |
| 系统 | 原厂 Android 16 W1WAA36.48-23-10，保留 v3 精简及离线 Magisk |
| 内核 | 6.6.87-android15-8-maybe-dirty-4k，PID_NS / IPC_NS / USER_NS 等开启 |
| 启动 | `sys.boot_completed=1`，修复后的内核再次整机重启通过 |
| 模块 | 441 个模块，与切换前集合完全一致；缺失 0、新增 0 |
| 声卡 / Wi-Fi | parrot-qrd-snd-card 注册成功；Wi-Fi 恢复连接 |
| Root / SELinux | Magisk 31.0，Enforcing |
| LXC / rootfs | 官方 Alpine 仓库的 LXC 6.0.4-r0、Alpine 3.22.6 aarch64 |
| 存储 | 普通目录 rootfs，不依赖 OverlayFS；设备占用约 25 MiB |
| 容器 init | BusyBox `/sbin/init`，容器内 PID 1 |
| 隔离 | 独立 mount、PID、IPC、UTS、network、cgroup namespace |
| 设备 / syscall 过滤 | cgroup v2 BPF 与 seccomp 实测通过 |
| 管理方式 | Magisk root 启动的 rootful 容器，继承 `u:r:magisk:s0` |

模块能加载、声卡能注册不等于已穷尽相机、音频播放、休眠等所有硬件回归测试。此轮确认的是 Android 正常开机、上述驱动状态、Wi-Fi 连接及容器生命周期。

## 日常使用

手机上现已安装 Termux，可直接使用 `lxc status`、`lxc start`、`lxc shell`、`lxc stop` 和 `lxc log`，见 [18-termux-lxc.md](18-termux-lxc.md)。

在电脑 `/home/kevinzhow/moto` 中执行：

```bash
python3 tools/rungic_lxc.py status
python3 tools/rungic_lxc.py shell
python3 tools/rungic_lxc.py exec /bin/cat /etc/alpine-release
python3 tools/rungic_lxc.py stop
python3 tools/rungic_lxc.py start
python3 tools/rungic_lxc.py log
```

`shell` 进入后用 `exit` 退出终端，容器继续运行。工具明确指定本机序列号，不会选中另一台 ADB 设备。电脑工具在 [tools/rungic_lxc.py](../tools/rungic_lxc.py)。

设备内也可通过 Magisk root 使用：

```sh
su -c '/data/adb/moto-lxc/moto-lxc status'
su -c '/data/adb/moto-lxc/moto-lxc start'
su -c '/data/adb/moto-lxc/moto-lxc shell'
su -c '/data/adb/moto-lxc/moto-lxc stop'
```

手机重启后容器处于 STOPPED，手动 `start` 即可；没有写入 Magisk 自动启动服务。当前已在重启验证后手动启动。

路径：

- 管理入口：`/data/adb/moto-lxc/moto-lxc`
- 原生启动器：`/data/adb/moto-lxc/moto-lxc-enter`
- 管理环境：`/data/adb/moto-lxc/runtime`
- 配置：`runtime/var/lib/lxc/alpine/config`
- 容器文件：`runtime/var/lib/lxc/alpine/rootfs`
- 日志：`runtime/var/log/lxc/alpine.log`

## 实施中解决的两个问题

### 原厂 GKI 模块信任证书

旧 `boot-gki-userns.img` 虽然在 GSI 上启动过，直接用于这次原厂 Android 16 时，只有 344 个模块加载。声卡等待依赖，系统服务反复重启，不能作为可用的原厂系统内核。

原厂与自编译内核使用不同的自动生成模块签名证书。内核配置包含 `CONFIG_MODULE_SIG_PROTECT=y`，未被信任的 GKI 模块会受到受保护符号规则限制。相关实现见本机 `android-kernel/common/kernel/module/signing.c`、`kernel/module/main.c`，尤其是模块受保护符号导入和导出检查。

本次从原厂 boot 的 kernel 中提取 X.509 公钥证书，用 OpenSSL 实际验证了原厂 `bluetooth.ko` 的 CMS 签名。原厂证书与候选内核内置证书都为 **1,357 字节**，因此只替换候选 Image 中这段等长证书。候选 boot 大小不变，证书范围以外所有字节逐字节一致，实际变化 1,096 字节。

这没有关闭模块签名校验，也没有修改内核代码、配置或符号 CRC。启动后 `.builtin_trusted_keys` 中恢复原厂密钥，441 个原厂模块全部加载，Android 正常启动。此镜像应搭配当前原厂模块使用；以后自行编译的新模块也必须考虑其签名信任关系。

复现脚本：[restore_gki_module_certificate.py](../tools/restore_gki_module_certificate.py)。输入 SHA-256、证书长度、偏移及输出 SHA-256 均有硬校验。证书和字节差异记录在 `.work/refs/lxc-install-20260922/certificates/` 与 `kernel-certificate-manifest.json`。

### 管理环境必须使用真正的 pivot_root

最初在私有 mount namespace 中仅 `chroot` 进入 Alpine 管理环境。容器 init 自身位于正确 rootfs，但其 mount namespace 的顶层根仍包含旧 Android 根；LXC 的 pidfd `setns` 附加路径没有另行 chroot，导致进入命令得到宿主根视图。

最终启动器先新建 mount namespace，以原生 `mount(NULL, "/", NULL, MS_PRIVATE|MS_REC, NULL)` 隔离挂载，再绑定管理环境及需要的 `/proc`、`/sys`、`/dev`，**pivot_root 进入管理环境并卸载该私有 namespace 中的旧根**。之后 LXC 自行建立容器的独立 rootfs、namespace 和设备目录。

修复后标准 `lxc-attach` 正常，附加进程也进入容器 cgroup、应用 seccomp 和 capability 限制。没有用裸 `nsenter` 代替最终管理入口；裸 nsenter 不会自动应用这些限制。Android PID 1 的 mountinfo 中没有 `moto-lxc` 挂载。

源码：[moto_lxc_enter.c](../tools/moto_lxc_enter.c)、[配置](../lxc/alpine.config)、[管理脚本](../lxc/moto-lxc)、[inittab](../lxc/inittab)。

## 验证内容

- `lxc-info` RUNNING，容器中 `/sbin/init` 为 PID 1，hostname 为 `moto-alpine`，release 为 3.22.6。
- 容器和 Android 的 mount/PID/IPC/UTS/network/cgroup namespace 编号不同。当前是 rootful 容器，user namespace 与宿主相同；内核 USER_NS 的创建另行实测通过，但未部署非特权 UID/GID 映射。
- 标准 `lxc-attach` 中 `Seccomp: 2`、`Seccomp_filters: 1`，capability 中移除了配置指定的高权限项。
- BPF 设备过滤：允许创建并读取 major 1/minor 5 的 zero 节点；未列入 allowlist 的 major 1/minor 11 节点创建返回 EPERM。手机重启后再次验证拒绝成功。
- 容器没有 `/system`、`/data` 宿主目录；独立 `/dev`、devpts；交互终端为 `/dev/pts/0`，stdin/stdout 均通过 `test -t`。
- 独立网络 loopback ping 成功。普通目录 rootfs 可写。
- `stop` 约 2.3 秒返回 STOPPED，payload/monitor cgroup 清理；LXC 会保留空的 `lxc.pivot` 管理目录。
- 再次 `start` 成功；标记文件在容器启停、整机重启后仍存在。验证后已删除测试标记。
- 整机重启后再次确认 Android 开机、声卡、Wi-Fi、模块集合、Magisk、Enforcing 和容器启动。

详细日志、签名核验材料、刷机前备份和最终状态均在 `.work/refs/lxc-install-20260922/`；最终摘要为 `final-verification.json`。早期失败试验文件保留用于定位，不能当作最终结果。最终证据主要为 `container-validation.txt`、`pty-validation.txt`、`stop-cleanup.txt`、`restart-validation.txt`、`reboot-validation.txt`、`final-device-state.txt`。

## 已保存的部署材料与回退

目录：`/home/kevinzhow/moto-lxc-20260922/`。

| 文件 | 用途 |
|---|---|
| `boot-lxc-stockcert.img` | 当前实机验证的容器内核，36,663,296 字节 |
| `boot-stock-rollback.img` | 修改前完整原厂 boot，100,663,296 字节 |
| `moto-lxc-runtime-v1.tar.gz` | 已验证运行环境、LXC、配置、最小 rootfs 和入口，10,454,717 字节（已同步 Termux 阶段的日志路径修正） |
| `rungic_lxc.py` | 电脑端操作工具 |
| `SHA256SUMS` / `artifacts.json` | 文件校验与大小 |

当前 boot 镜像 SHA-256：

```text
e158018b80b409df94254110ca3b82f09235b1a8ad901f478f61bae83767ae13
```

已从设备 `boot_a` 读取镜像长度的前缀并核对这个值。完整分区比镜像大，所以不能直接要求整个分区的哈希与短镜像相等。

Magisk `init_boot_a` 前后 SHA-256 不变：

```text
6ed2ac5572c3f3c82c298dada2bb3c3af33210375a392ee49ed332aacf7f7943
```

若回退，进入 bootloader 后，仅对当前已验证的这台设备/slot a 使用：

```bash
/home/kevinzhow/Android/Sdk/platform-tools/fastboot -s ZY32MVJS25 flash boot_a /home/kevinzhow/moto-lxc-20260922/boot-stock-rollback.img
/home/kevinzhow/Android/Sdk/platform-tools/fastboot -s ZY32MVJS25 reboot
```

回退不清数据、保留 Magisk，但原厂内核缺少 namespace，LXC 将无法启动。

**此前约 9.78 GB 的 v3 一键完整刷机包尚未更新。** 它仍恢复原厂 boot，而且完整刷机会清空 `/data`。未来若先刷 v3，再恢复此 LXC 版本，需要另外刷此 boot 并部署运行包；本目录材料是补充包，不是新的一键完整 ROM。具体恢复步骤放在该目录的 README.md。

## 当前边界与后续工作

当前运行的是适合受信任负载的 rootful 容器，继承 Magisk 的 SELinux 域，没有独立受限容器域；不能把当前结果等同于非特权多租户隔离。

本轮保持 Android 原有 cgroup 布局：LXC 使用 `/sys/fs/cgroup` 的 v2 层级和设备 BPF。v1 memory/cpu 在 Android `/dev` 下，未接入 LXC 的配额管理；CPU 硬配额和 PIDs controller 仍是现有内核的缺项。之前的 v1 读写探针成功不等于这里已经有容器资源限额。

后续可依次验证独立 veth 出网、DNS 与端口映射，明确的内存/CPU 资源管理，非特权 UID/GID 映射和 SELinux 域，以及 Debian/Ubuntu、systemd、开机自动恢复。Docker 本轮没有部署或验证。

## 来源与构建

所有下载经本机代理，使用 Alpine 官方 v3.22 仓库。Minirootfs 3.22.6 的 SHA-256 已与官方 release metadata 核对，APK 使用官方签名公钥验证后安装；下载和元数据保存在 `.work/refs/lxc-install-20260922/downloads/`。

官方来源：[Alpine ARM64 releases](https://dl-cdn.alpinelinux.org/alpine/v3.22/releases/aarch64/)、[Alpine ARM64 packages](https://dl-cdn.alpinelinux.org/alpine/v3.22/main/aarch64/)、[LXC 配置说明](https://linuxcontainers.org/lxc/manpages/man5/lxc.container.conf.5.html)、[LXC 6.0.4 attach 源码](https://github.com/lxc/lxc/blob/v6.0.4/src/lxc/attach.c)。

原生启动器以本机 hermetic Clang 和官方 musl-dev ARM64 静态库编译。构建命令保存于 [lxc/build-launcher.sh](../lxc/build-launcher.sh)。不需要安装 Android App、替换系统 libc 或关闭 SELinux。
