# GKI baseline（零修改）

> Docker 后续验证已完成基础部署：见 [2026-09-22 Docker 记录](../docs/19-docker-installation.md)。沿用 LXC 容器内核，保持 SELinux Enforcing；通过 containerd 的显式 OverlayFS 挂载参数修复普通容器写入，并适配 Android 网络。下段“本次仅 LXC”及下文 Docker 脚本均属于此前阶段。

> 2026-09-22 最新状态：已在原厂 Android 16 上运行 LXC，见 [实机部署记录](../docs/17-lxc-installation.md)。当前 boot 是 `~/moto-lxc-20260922/boot-lxc-stockcert.img`。旧 `boot-gki-userns.img` 直接用于原厂系统会缺少 97 个模块并阻碍开机；已通过恢复内核中的原厂 GKI 信任证书解决，441 个模块完整加载。下面“已刷/当前”均为 2026-09-17 历史。`out/kernel_aarch64/dist/` 最后一次实验有 3,252 个符号 CRC 变化，仍不能使用。旧 Docker 脚本执行 `setenforce 0`，不代表本次 Docker 验证；本次仅 LXC，保持 Enforcing。

目标：先证明「用 AOSP hermetic 工具链编出来的 android15-6.6 / KMI 8 / 4K Image」能带着 stock `vendor_dlkm` 开机。不开 Docker 相关 CONFIG，不打 kABI patch。

## 机器上的 stock kernel

```
6.6.87-android15-8-g3f57bfb65ab4-ab14067820-4k
```

- KMI generation：**8**
- 页大小：**4K**（`CONFIG_LOCALVERSION="-4k"`）
- kernel 在 **`boot`**，Magisk 在 **`init_boot`**
- 回退：`fastboot flash boot ~/a17-gsi/dumps/stock/boot.img`

## 源码

```
repo init -u https://android.googlesource.com/kernel/manifest \
  -b common-android15-6.6-2025-05 --depth=1
```

本机 `uname` 里的 `g3f57bfb65ab4` 对应 tag **`android15-6.6-2025-05_r16`**（6.6.87）。manifest 的 `android15-6.6-2025-05` 分支已 deprecated，`common` 改成这个 tag。

树：`~/android-kernel`

## 构建（不要系统 clang）

Kleaf + prebuilts `clang-r510928`：

```
cd ~/android-kernel
tools/bazel run --config=fast //common:kernel_aarch64_dist
```

默认 `kernel_aarch64` 是 4K。不要编 `kernel_aarch64_16k`。

产物一般在 `out/kernel_aarch64/dist/` 或 bazel 的 `Image` / `Image.lz4`。

## 打包 / 已刷入（2026-09-17）

只用新 kernel 替换 stock `boot.img` 里的 kernel，ramdisk 为空（GKI header v4）。

- 产物：`~/android-kernel/out/kernel_aarch64/dist/Image`（未压缩 ARM64 4K，与 stock 一致）
- 新 boot：`~/a17-gsi/boot-gki-baseline/boot-gki-baseline.img`
- 已 `fastboot flash boot` 到 slot a

开机后：

```
Linux localhost 6.6.87-android15-8-maybe-dirty-4k
```

`maybe-dirty` 是因为源码来自 googlesource tarball、没有 git。Magisk 31 仍在 `init_boot`。`vendor_dlkm` 已加载（触控 ilitek/chipone、audio、rmnet 等），显示 1080×2400@120Hz。dmesg 无 unknown symbol。

回退：`fastboot flash boot ~/a17-gsi/dumps/stock/boot.img`

## namespace kernel（已刷，2026-09-17）

Droidspaces SYSVIPC kABI：把 `sysvsem`/`sysvshm` 挪到 `ANDROID_KABI_RESERVE(6..8)`，中间 `task_struct` 不再位移。

`gki_defconfig` 最小改动（savedefconfig 顺序）：

- `CONFIG_SYSVIPC=y`
- `CONFIG_POSIX_MQUEUE=y`
- 去掉 `# CONFIG_PID_NS is not set` → 默认 `PID_NS=y`，`IPC_NS=y`
- `CONFIG_DEVTMPFS=y`

**当时未开** `USER_NS`（这张 `boot-gki-ns` 上 `unshare -U` 仍 Invalid argument）。

ABI：`Module.symvers` / `vmlinux.symvers` 相对 baseline **0 CRC 变化、0 增删**。

刷入：`~/a17-gsi/boot-gki-ns/boot-gki-ns.img` → `boot_a`

实测：

```
unshare -p --fork -- echo pid-ns-ok   # ok
unshare -i -- echo ipc-ns-ok          # ok
unshare -m -u -n                      # ok
unshare -U                            # Invalid argument（此镜像预期）
```

vendor_dlkm 仍加载，Magisk 31 仍在。回退：

- namespace 核：`fastboot flash boot ~/a17-gsi/boot-gki-ns/boot-gki-ns.img`
- 零修改 baseline：`fastboot flash boot ~/a17-gsi/boot-gki-baseline/boot-gki-baseline.img`
- 原厂：`fastboot flash boot ~/a17-gsi/dumps/stock/boot.img`

## USER_NS kernel（历史实机验证，2026-09-17）

在 ns 核之上只加 `CONFIG_USER_NS=y`。ABI：0 CRC 变化，多 6 个 kuid 符号（`from_kuid` / `_munged` / `make_kuid` / `kgid`），vendor_dlkm 仍加载。

**不要**顺手开 `CONFIG_CGROUP_DEVICE` / `CONFIG_CGROUP_PIDS`：会改 3252 个 CRC，没刷。

刷入：`~/a17-gsi/boot-gki-userns/boot-gki-userns.img` → `boot_a`（当前 boot）。

```
uname -a   # 6.6.87-android15-8-maybe-dirty-4k
zcat /proc/config.gz | grep USER_NS   # CONFIG_USER_NS=y
unshare -U id   # uid=65534 overflowuid（ns 已建，未写 uid_map）
```

## Docker 29.8.1（静态 aarch64，vfs）

二进制和脚本在 `~/a17-gsi/docker/`，设备上 `/data/adb/docker/`。

```
adb shell 'su -c "sh /data/adb/docker/start-dockerd.sh"'
adb shell 'su -c "sh /data/adb/docker/run-hello.sh"'
# 停 daemon：su -c "sh /data/adb/docker/stop-dockerd.sh"
```

要点：

- Android `/` 只读且不是可 `MS_REC|MS_SLAVE` 的 mountpoint → chroot 到 `/data/adb/docker/chroot`，**先** self-bind ROOT，再挂 nested。
- storage：`vfs`（`overlay2` 在 f2fs `/data` 上 EINVAL）。网络：`--iptables=false --bridge=none`，容器用 `--network=none`。
- vfs 的 rootfs 不是 mountpoint，`pivot_root` EINVAL。`runc` 换成静态 wrapper（`runc-nopivot.c`），只在 `create|run|restore` 后插入 `--no-pivot`。chroot 里不能跑 bionic shell 脚本（缺 linker）。
- **禁止** `umount -l` rbind 的 `/sys`：会把主机 `/sys/fs/cgroup` cgroup2 一起拆掉，dockerd 接着报 `Devices cgroup isn't mounted`。
- 没有 `CONFIG_CGROUP_DEVICE`，cgroup v2 的 memory/cpu 限制也没有（hybrid v1 在 `/dev/memcg` 等）。hello-world 已跑通。
- **docker0 标准桥已开**（默认 `bridge` 网络，`172.17.0.0/16`）。`--iptables=false`：Android 的 filter 表写不进去（`tetherctrl_FORWARD` 仍 DROP），NAT MASQUERADE 可以。必须加 `ip rule pref 9999 from/to 172.17.0.0/16 lookup main`，否则命中 Android `32000: from all unreachable`。出网还要手机自己有默认路由，目前 USB 无 WAN。
