# LXC 运行条件实测（2026-09-22）

> 后续进展：已完成内核兼容修复并实际启动 LXC，见 [17-lxc-installation.md](17-lxc-installation.md)。下文保留部署前审计结果；旧候选必须先恢复原厂 GKI 模块信任证书，不能直接用于原厂 Android 16。

结论：**有实现基础。当前最明确的内核门槛是 PID_NS 和 IPC_NS；非特权容器还需要 USER_NS。已保存并曾在本机启动的 USER_NS 内核包含这三项。** 当前原厂内核上的挂载、PTY、seccomp、BPF 设备过滤及基础网络已通过原生系统调用或实际操作验证。

这还不是“LXC 容器已经运行成功”：本次没有刷入候选内核，也没有部署 LXC 用户空间。下一步应先在当前 Android 16 上验证保存的候选内核，再启动最小 LXC 容器。

## 方法与边界

- 设备：XT2537-4 / mumba_cn / ZY32MVJS25，当前原厂 Android 16 W1WAA36.48-23-10。
- 内核：6.6.87-android15-8-g3f57bfb65ab4-ab14067820-4k。
- 使用 LXC 官方 stable-6.0 的 `lxc-checkconfig` 检查当前配置和保存的候选配置。
- 候选配置检查只是静态核验；其中显示的 cgroup 挂载、namespace 数量和用户空间工具仍来自当前运行系统。
- 编译了无 libc 依赖的 ARM64 原生探针：[lxc_kernel_probe.c](../tools/lxc_kernel_probe.c)。避免把 Android mount 工具的参数行为误判为内核缺陷。
- 所有设备操作在 Magisk root 的 `u:r:magisk:s0` 上下文运行，**全程 SELinux Enforcing**。这证明该启动上下文具备测试权限，不代表独立受限容器 SELinux 域或普通 Android App 也具备相同权限。
- 挂载和网卡测试在新建 namespace 内进行。资源配置仅写新建的空 cgroup；BPF 过滤只施加到专门的测试 cgroup，并仅迁入探针自身。
- 已清除临时 cgroup、挂载测试目录和设备上的诊断文件；宿主没有遗留测试网桥/veth。没有修改 boot、SELinux 策略、Android 全局网络规则或启动服务。

## 条件逐项核验

| 条件 | 检测结果 | 判断 |
|---|---|---|
| PID / IPC namespace | 原厂缺失，官方脚本标记 required；候选配置均为 y | 必须先使用具备这两项的内核 |
| USER namespace | 原厂缺失；候选配置为 y | 非特权 LXC 需要；UID/GID 映射仍须实测 |
| Mount namespace | unshare 成功；原生 mount(MS_PRIVATE\|MS_REC) 成功 | 通过 |
| 目录挂载 / tmpfs / proc | 实际挂载成功 | 通过 |
| pivot_root | 换入临时 rootfs 并卸载旧根成功 | 通过 |
| /dev 与终端 | tmpfs 上创建并打开设备节点成功；独立 devpts、PTY 打开/解锁成功 | 通过 |
| Seccomp | NO_NEW_PRIVS 和过滤器安装成功 | 基础机制通过 |
| cgroup v2 设备过滤 | BPF 加载、附加、拒绝设备访问、解除均成功 | 不需要先启用 v1 CGROUP_DEVICE 才能拥有设备过滤机制 |
| 内存限制 | 新建空 v1 cgroup，写入并读回 64 MiB 限制成功 | 配置机制可用；未做压力测试 |
| CPU 权重 | 新建空 v1 cgroup，写入并读回 cpu.shares=256 成功 | 相对权重可用；不是 CPU 硬配额 |
| CPU 硬配额 / PIDs 限额 | CFS_BANDWIDTH、CGROUP_PIDS 未启用 | 完整资源控制仍有缺口 |
| 网络设备 | 隔离网络 namespace 中创建 veth 和 bridge，并挂接/拉起成功 | 基础机制通过；真实出网、DNS、端口映射仍须验证 |
| OverlayFS / F2FS | 实际 OverlayFS mount 返回 EINVAL | 该测试路径未通过；可先采用 LXC 的普通目录 rootfs |
| LXC 用户空间 | 当前未安装 | 需要部署 ARM64 liblxc/工具、rootfs 和启动器 |
| LXC 真正启动 | 本次未执行 | 不能宣称已经跑通 |

LXC 默认可使用 `dir` 存储，rootfs 是普通目录，见 [lxc-create 官方说明](https://linuxcontainers.org/lxc/manpages/man1/lxc-create.1.html)。因此 OverlayFS 失败不是基础 LXC 启动的硬门槛。

官方检查脚本中的 macvlan、IPv6 MASQUERADE、CRIU/checkpoint 等缺项对应特定功能，不应全部当作启动最小容器的必要条件。`enabled, not loaded` 对内建为 y 的功能也不表示需要加载模块；本次 veth 和 bridge 已实际创建成功。

## BPF 设备隔离的实际证据

在新建的空 cgroup2 中加载拒绝设备访问的程序，仅将探针自身迁入：

```text
bpf_device_prog_load=3
open_test_cgroup=4
bpf_device_attach=0
move_only_probe_to_cgroup=1
open_dev_null_with_deny_expected_minus1=-1
bpf_device_detach=0
open_dev_null_after_detach=5
```

正数 3/4/5 是打开的 fd；move 返回 1 是写入字节数。过滤时打开 `/dev/null` 返回 -EPERM，解除后恢复成功。这是过滤效果实测，而不只是配置显示 CGROUP_BPF=y。

## 仍需适配的 LXC cgroup 布局

Android 把 memory、cpu 等 v1 控制器挂在 `/dev/memcg`、`/dev/cpuctl`，而 `/sys/fs/cgroup` 是控制器列表为空的 cgroup2。检查的 LXC stable-6.0 源码主要在 `/sys/fs/cgroup` 下寻找标准布局。

源码还显示：`cgfsng_setup_limits()` 在非纯 unified 布局下会忽略 cgroup2 配置。因此不能简单把所有 v1 控制器绑定到标准位置，再假定 `lxc.cgroup2.devices.*` 一定会同时生效。

可供实际启动阶段验证的路线：

1. 首个最小容器先使用 LXC 可识别的 cgroup2 和设备 BPF；不要求完整 CPU/内存/PIDs 配额。
2. 若需要利用现有 v1 memory/CPU 权重，可研究由启动器管理独立 v1 父 cgroup，或针对 LXC 的 Android 混合布局做明确适配。配置读写已经通过，但 LXC 生命周期、继承和实际限额效果仍需验证。
3. 保留 Android 原有控制器布局，避免为了容器把整台手机的 cgroup 强行迁移到 v2。

上述是源码分析得到的实施路线，尚未经过 LXC 实际容器验证。官方配置机制见 [LXC cgroup 和 SELinux 配置](https://linuxcontainers.org/lxc/manpages/man5/lxc.container.conf.5.html)。

## 可复用内核与最小实施顺序

候选：`/home/kevinzhow/a17-gsi/boot-gki-userns/boot-gki-userns.img`。

该候选曾在此机上实机启动；与旧基线相比已有符号 CRC 变化为 0。当前原厂 boot 与此前实验底包完全相同。详细 SHA-256 与 ABI 结果见 [上一轮评估](15-container-reassessment.md)。不要使用最后一次含 3,252 个 CRC 变化的 dist 实验产物。

1. 在当前 Android 16 上验证已保存 USER_NS 内核的启动、原厂驱动、Magisk 和 namespace。
2. 部署 ARM64 LXC 与最小 rootfs，先使用目录存储、独立 /dev 和 PTY，验证启动、进入、停止、清理。
3. 首轮可由 Magisk root 管理可信测试容器；随后单独验证非特权 UID/GID 映射和容器 SELinux 域。当前设备没有 newuidmap/newgidmap，普通用户启动路线还涉及 Android /data 的 nosuid 和授权设计。
4. 加入联网、端口映射和可验证的资源限制；成功后再验证完整 Debian/Ubuntu、systemd 和开机恢复。

## 本地证据与复现

目录：`.work/refs/lxc-audit-20260922/`。

- `lxc-checkconfig-stock.txt`、`lxc-checkconfig-candidate.txt`：官方配置检查输出。
- `runtime-probes.txt`：挂载、pivot_root、PTY、seccomp 原始结果。其末尾 BPF 初版的 open 标志错误已经修正，BPF 最终结果以下一项为准。
- `bpf-device-probe.txt`：修正 ARM64 open 标志后的完整设备过滤测试。
- `cgroup-v1-probe.txt`、`network-probe.txt`：资源配置及基础网络测试。
- `final-device-state.txt`、`summary.json`：最终状态和结构化结论。
- 官方脚本与 `cgfsng.c` 的源码快照和 SHA-256 保存在此目录及 summary.json。

探针编译：

```bash
/home/kevinzhow/android-kernel/prebuilts/clang/host/linux-x86/clang-r510928/bin/clang \
  --target=aarch64-linux-gnu -fuse-ld=lld -nostdlib -static \
  -ffreestanding -fno-builtin -fno-stack-protector -O2 -Wall -Wextra \
  tools/lxc_kernel_probe.c -o .work/refs/lxc-audit-20260922/lxc-kernel-probe
```

官方源码：[lxc-checkconfig](https://github.com/lxc/lxc/blob/stable-6.0/src/lxc/cmd/lxc-checkconfig.in)、[cgfsng](https://github.com/lxc/lxc/blob/stable-6.0/src/lxc/cgroups/cgfsng.c)。
