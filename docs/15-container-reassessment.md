# Docker / LXC 重新评估（2026-09-22）

> 后续进展：LXC 第一阶段及直接 Docker/Compose 均已实机运行，见 [17-lxc-installation.md](17-lxc-installation.md) 和 [19-docker-installation.md](19-docker-installation.md)。当前 Docker 保持 SELinux Enforcing，已解决存储、代理、基础 bridge/DNS/端口发布；下文是部署前的评估记录，不能当作最新状态。

结论：这台设备已有原生容器的实验基础，Docker hello-world 在之前的定制内核上跑通过。但当前原厂 Android 16 精简/Magisk v3 恢复了原厂 boot，缺少 PID、IPC、USER namespace，当前不能按常规方式运行 Docker/LXC。先恢复容器内核基线，再解决运行环境、SELinux、存储、联网和资源限制。

本次为历史记录核对、当前设备诊断和离线镜像/ABI 检查；没有刷写 boot、清数据、运行旧 Docker 启动脚本或关闭 SELinux。

## 当前设备实测

设备 XT2537-4 / mumba_cn / ZY32MVJS25，Android 16 `W1WAA36.48-23-10`，槽 a，Magisk root 正常，SELinux Enforcing。

内核：`6.6.87-android15-8-g3f57bfb65ab4-ab14067820-4k`。

| 项目 | 当前结果 | 对容器的影响 |
|---|---|---|
| Mount / UTS / Network namespace | 配置存在，unshare 探针成功 | 基础功能可用 |
| PID namespace | CONFIG_PID_NS 未启用，unshare 返回 Invalid argument | 常规容器进程隔离受阻 |
| IPC namespace / SYSVIPC | 未启用，unshare 返回 Invalid argument | 常规 IPC 隔离受阻 |
| USER namespace | CONFIG_USER_NS 未启用，unshare 返回 Invalid argument | rootless Docker、非特权 LXC 受阻；rootful Docker 不一定要求 USER_NS |
| Seccomp | SECCOMP、SECCOMP_FILTER 已开启 | 配置层面具备基础 |
| OverlayFS | CONFIG_OVERLAY_FS=y | 仅代表编译支持，不能据此认定 Android /data 上的 Docker 存储已可用 |
| Veth / bridge / NAT | 对应配置存在 | 仍需适配 Android 路由、防火墙及网络切换 |
| cgroup | v1/v2 混合；CPU、内存、cpuset、blkio 在 Android 的 v1 层级；cgroup2 controllers 为空 | 资源限制需要专门适配 |
| PIDs / CPU quota | CGROUP_PIDS、CFS_BANDWIDTH 未启用 | 进程数上限、CPU 配额不完整 |
| 设备访问控制 | CGROUP_DEVICE 未启用；CGROUP_BPF、BPF_SYSCALL 已启用 | 必须区分 v1 devices 与 v2 BPF，不能只看一个配置开关 |
| Docker / LXC 用户空间 | /data/adb/docker 不存在，没有发现正在运行的 daemon | 上次安装并未保留到当前系统 |
| 网络 | Wi-Fi 已连接，存在 Wi-Fi 默认路由；Android 32000 unreachable 规则仍存在 | 比上次仅 USB 无 WAN 的场景更适合验证真实联网 |

当前没有尝试启动 dockerd：已由配置和 namespace 系统调用确认前置内核条件不足。

初次使用 Android mount 命令准备私有挂载时返回 EINVAL，未进入 OverlayFS 挂载。**后续原生系统调用探针已证明私有挂载、pivot_root、PTY 均可用**，该早期命令失败不能当作内核不支持挂载的证据。后续实际测试的 F2FS 路径上 OverlayFS mount 返回 EINVAL，但 LXC 可以先用目录 rootfs。详见 [LXC 条件实测](16-lxc-prerequisites.md)。

## 之前具体做到哪里

历史资料：[kernel/README.md](../kernel/README.md)，主机工具：`/home/kevinzhow/a17-gsi/docker/`。

1. 基于 android15-6.6 / KMI 8 / 4K 编译 GKI，原厂 vendor_dlkm 加载和 Android 启动通过。
2. 使用 SYSVIPC 的 kABI 保留槽修补，加入 PID_NS、IPC_NS、SYSVIPC、POSIX_MQUEUE、DEVTMPFS；随后加入 USER_NS。保存的 USER_NS boot 曾刷机成功。
3. Docker 29.8.1 aarch64 静态工具在该环境下跑通 hello-world。采用 chroot、vfs 存储、runc --no-pivot 适配。
4. 建过 docker0 和 Android 策略路由/NAT 规则，但历史记录未完成真实外网验证；正常端口映射和网络切换也不能视为已验证。
5. 旧 `start-dockerd.sh` 明确执行 `setenforce 0`。因此旧 hello-world 成功不等于 SELinux Enforcing 下可用，不应直接把旧脚本做成当前系统自启动服务。
6. 本地这套资料中未找到 LXC 容器实际启动成功的记录，不能将 Docker 成功外推为 LXC 成功。

## 可以复用的内核与应避开的产物

当前原厂 `boot.img`、设备当前 `boot_a`、之前实验使用的原厂 `boot.img` 三者 SHA-256 完全相同：

```text
f0af1c76dba07456d4b3f33342e58efecac18f54c0590705402771fec5a3139e
```

已保存并曾实机成功的候选：

```text
/home/kevinzhow/a17-gsi/boot-gki-userns/boot-gki-userns.img
SHA-256: e6e7f697749db66e253f659c2460420069406ab40c67b3cf77ec286fdd8fc184
```

从该 boot 内核重新提取配置，确认 PID_NS、IPC_NS、USER_NS、SYSVIPC、POSIX_MQUEUE、DEVTMPFS 均为 y。其保存的 Module.symvers 与原基线相比：**已有符号 CRC 变化 0，删除 0，新增 6 个 UID/GID 转换符号**。

这支持把该镜像作为下一轮测试基线；它尚未在当前原厂 Android 16 用户空间重新启动验证，不能以 ABI 检查代替实机验证。

特别注意：`/home/kevinzhow/android-kernel/out/kernel_aarch64/dist/` 最后留下的产物不是上述已验证快照。该目录的 Module.symvers 与基线有 **3,252 个已有符号 CRC 变化**，与历史补充 cgroup 功能的失败尝试一致。不得按“最新文件”直接选来刷机，也不能靠忽略模块版本检查规避这个问题。

## 下一轮实施顺序

1. 用保存的 USER_NS 内核验证当前 Android 16：启动、显示/触控、Wi-Fi、原厂模块、Magisk 和 namespace；保留当前原厂 boot 作为回退。Magisk 所在 init_boot、精简 product 和用户数据不需要随这一步重刷。
2. 以独立的挂载环境重做 Docker 启动器，先跑本地 ARM64 最小镜像；清理旧脚本对全局 SELinux、挂载树和网络规则的直接修改。
3. 优先在 Enforcing 下定位需要的 SELinux 权限，针对容器服务适配，不把全局 permissive 作为最终方案。
4. 对比 vfs 与独立 ext4 容器存储的 OverlayFS 可行性；独立 ext4 是待验证方案，不承诺自动解决所有挂载限制。
5. 分别验证 bridge、DNS、真实出网、端口映射，以及 Wi-Fi/移动网络切换。旧固定路由规则只能作为实验记录。
6. 接入 LXC 用户空间和最小 ARM64 系统容器，验证 init、/proc、/dev、PTY、cgroup、启动停止与清理，再考虑完整 Debian/Ubuntu。
7. 若需要 CPU/内存/PIDs 限额和可靠设备隔离，单独处理 Android cgroup 层级与 kABI 兼容性，逐项测试；完成后才纳入新 ROM / 一键恢复包。

Docker 和 LXC 依赖 Linux namespaces、cgroups 等内核能力，LXC 官方列出的机制见 [LXC introduction](https://linuxcontainers.org/lxc/introduction/)。Docker rootless 还依赖 user namespace 和 UID/GID 映射，见 [Docker rootless requirements](https://docs.docker.com/engine/security/rootless/)。

cgroup v2 的设备控制由 BPF 实现，没有 v1 那样的 devices 接口文件，见 [Linux cgroup v2 device controller](https://docs.kernel.org/admin-guide/cgroup-v2.html#device-controller)。因此当前 CGROUP_DEVICE=n 不能单独证明 v2 设备过滤不可用，仍需检查运行时、BPF 加载和 SELinux 权限。

OverlayFS 对 upper 文件系统的 xattr、d_type 等有要求，见 [Linux OverlayFS](https://docs.kernel.org/filesystems/overlayfs.html)。Docker 29 起默认镜像存储也有变化，迁移旧 vfs 实验配置时应显式确认实际 storage driver / snapshotter，见 [Docker storage documentation](https://docs.docker.com/engine/storage/drivers/overlayfs-driver/)。

## 原始证据

目录：`/home/kevinzhow/moto/.work/refs/container-audit-20260922/`。

- `kernel.config` / `kernel-config.gz`：设备实际内核配置。
- `namespace-probes.txt`：namespace 系统调用结果。
- `kernel-state.txt`：cgroup、文件系统、挂载和进程权限。
- `container-files.txt`：容器文件与进程检查。
- `controllers-network.txt`：控制器、路由和当前模块。
- `boot-device-sha256.txt`：当前 boot 分区 SHA-256。
- `kernel-comparison.json`：原厂 boot 与已验证/最后编译产物的对比。
- `tested-userns.config`：从已验证候选 boot 提取的配置。
- `overlay-probe.sh` / `overlay-probe.txt`：临时挂载准备探针及失败范围。
- `final-state.txt`：检查结束后 SELinux / cgroup2 状态。
