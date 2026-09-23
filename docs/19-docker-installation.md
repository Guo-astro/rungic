# 原厂 Android 16 上运行 Docker（2026-09-22）

设备 XT2537-4 / mumba_cn / ZY32MVJS25。沿用第 17 篇已经验证的容器内核，本次没有再次刷写 boot、init_boot 或系统分区。

Docker 29.8.1、containerd 2.3.5、runc 1.5.1、Compose v5.5.1 已部署。Docker 直接使用 Android 内核，在独立 mount namespace 内运行 Alpine 管理环境；没有套在 LXC 内，也不是虚拟机。原有 LXC 保留。

后续按用户对兼容性和维护成本的要求，Docker 专用域已改为 permissive，Android 全局仍 Enforcing；同时接通手机共享存储和普通卷两种挂载。当前存储入口与模式见 [20-docker-storage.md](20-docker-storage.md)。本篇保留初次严格模式的验证过程。

## 日常使用

Termux 中通过已授权的 Magisk root 执行：

```sh
docker ps
docker logs --tail 30 moto-nginx
docker compose -f /root/stacks/web/compose.yaml ps
docker-service status
docker-service restart
docker-service stop
docker-service start
docker-service shell
```

`docker-service shell` 进入 Docker 的管理环境，输入 `exit` 返回 Termux。这里 `/root/stacks/web/compose.yaml` 是 Linux 管理环境中的路径，位于手机 `/data/adb/moto-docker/runtime/root/stacks/web/compose.yaml`。Docker 命令中的文件、bind mount 路径也按此环境解释，并非 Termux 的 `$HOME`；编辑项目可进入这个 shell，或由电脑通过 ADB root 放入该目录。

已部署示例为官方 ARM64 `nginx:alpine`，Compose 项目 `moto-server`，容器 `moto-nginx`，持久化卷 `moto-server_webdata`。当前 Wi-Fi 地址下访问：

**http://192.168.5.60:18088/**

该地址可能随 DHCP 改变。端口发布于设备接口；需要仅本机访问的服务，使用 `127.0.0.1:端口:容器端口`。Docker 管理 API 仅监听 Unix socket，没有开放 2375/2376 TCP API。

电脑侧：

```sh
python3 tools/moto_docker.py status
python3 tools/moto_docker.py cli ps
python3 tools/moto_docker.py cli compose -f /root/stacks/web/compose.yaml ps
python3 tools/moto_docker.py shell
```

入口默认明确指定序列号 ZY32MVJS25。交互容器终端可用 `python3 tools/moto_docker.py --tty cli exec -it moto-nginx sh`。

## SELinux 与容器权限

系统保持 **Enforcing**，没有执行 `setenforce 0`。新增 `moto_docker` domain、`moto_docker_file` 文件类型及专用于 ext4 镜像的 `moto_docker_image` 类型。原生启动器完成挂载后，从 Magisk 域切换到 `u:r:moto_docker:s0`，才运行 Docker 用户空间。该域最初为 enforcing，现已按用户选择切换为 permissive。

不能只凭 `getenforce` 判定容器受到约束：现有 Magisk root 域本身是宽权限、permissive 的。本次 daemon 和实际工作负载均确认进入新的 enforcing domain，并用无敏感内容、标记为 `system_data_file` 的临时文件验证：Magisk root 能读，Docker 域被拒绝，AVC 明确为 `permissive=0`。测试后已删除 canary。

普通容器仍使用 Docker 默认能力集合及 seccomp：`CapEff=00000000a80425fb`，不含 `SYS_ADMIN`；`Seccomp=2`。设备过滤验证中，major 1/minor 5 的 zero 节点可读，major 1/minor 11 节点无法打开，返回 EPERM。

交互终端额外需要 devpts 的 `TIOCGPTN`、`TIOCSPTLCK`、`TIOCGPTPEER` 三个 ioctl，已根据实际拒绝记录单独放行。最终从真实 Termux 会话执行 `docker exec -it moto-nginx sh` 成功，`tty` 返回 `/dev/pts/0`，seccomp 仍为 2；输入 `exit` 返回 Termux。证据见 `.work/refs/docker-install-20260922/termux-pty.txt`，其中保留了修复前失败与修复后成功的对比。

保留的 allow 规则允许 Docker 域管理自己的进程、文件、网络和 cgroup，并提供所需的 proc/sysfs 读取、挂载权限。切为 permissive 后，这些规则主要减少正常操作的审计噪声；不能再将规则外访问当作被强制阻断的安全边界。实际规则在 [docker/sepolicy.rule](../docker/sepolicy.rule)。

**边界：daemon 和当前容器共用这个域，没有部署标准 Linux 的 `container_t` / 每容器 MCS 标签隔离，也没有 rootless UID 映射。** `docker info` 不会列出标准 Docker SELinux 集成；这里使用的是 Android 上的专用策略。适用范围是自己的可信服务，不能据此声称已经完成不可信多租户加固。

## 存储兼容修复

原始 `/data` 为支持 casefold 的 F2FS，当前 OverlayFS 拒绝使用它作为 backing filesystem。部署了 **8 GiB 稀疏 ext4 文件** `/data/adb/moto-docker/docker-data.ext4`，只在 Docker 私有 mount namespace 中挂载到 `/var/lib/docker`。8 GiB 是逻辑容量，实际磁盘占用随数据增长；当前没有自动扩容机制。

仅换 ext4 还不够：初始 `overlay2` 可以启动 `hello-world`，但普通容器在 `/etc`、`/tmp` 等镜像已有目录中写入会 EPERM，Nginx 创建缓存目录也失败。关闭 seccomp 无效，诊断时临时增加 `SYS_ADMIN` 才能绕过。

定位结果：当前本地内核源树 `fs/overlayfs/params.c` 定义 `ovl_override_creds_def=true`，但 `ovl_init_fs_context()` 没有把它复制到 `ofs->config.override_creds`。所以 sysfs 参数显示 Y 也不足以证明具体挂载启用了它。限定测试进程的临时 kretprobe 捕获到 `ovl_set_impure()` 中的 `vfs_setxattr()` 返回 EPERM；探针已清理。

最终使用标准 containerd overlayfs snapshotter，显式配置：

```toml
[plugins.'io.containerd.snapshotter.v1.overlayfs']
  mount_options = ['override_creds=on']
```

这恢复 OverlayFS 使用挂载者凭据进行底层操作的行为；没有给普通容器添加能力、替换 Docker 二进制或再次修改内核。修复后普通权限的 Alpine、Debian glibc 用户空间和官方 Nginx 均通过写入测试。

containerd 与 dockerd 必须由 [docker/runtime-start](../docker/runtime-start) 在同一私有 mount namespace 启动，否则 Docker 创建的容器 rootfs 挂载对 shim 不可见。当前 Docker storage driver 显示 `overlayfs` / `io.containerd.snapshotter.v1`，不是早期试验的 VFS 或 legacy overlay2。

## 网络与指定代理

HTTP、HTTPS 统一使用 **`http://192.168.5.45:6152`**。这是 HTTP CONNECT 代理，HTTPS 代理地址也应使用 `http://`。

配置位置：

- daemon 拉镜像：`runtime/etc/docker/daemon.json` 的 `proxies`。
- `docker run` / build 的默认代理环境：`runtime/root/.docker/config.json`。
- 管理 shell 中的下载命令：`runtime/etc/profile.d/50-moto-proxy.sh`。

官方 Nginx、Debian 镜像拉取经过此代理；容器通过代理访问 HTTP、HTTPS 均返回 200。该代理无需 ADB 转发，电脑断开 USB 后仍可通过局域网使用。

代理环境变量不是透明代理，也不会自动代理任意 TCP/UDP 协议。应用须支持相应变量或自行配置。内网服务间访问应绕过代理；BusyBox wget 不可靠地处理这里的 `NO_PROXY`，因此示例健康检查显式使用 `wget -Y off`，容器间测试同样如此。

Android 内核缺少 Docker 默认防火墙所需的部分功能，包括 `xt_addrtype` 和 bridge netfilter，且未开启 nftables。本部署关闭 Docker 对宿主 iptables/ip6tables 的自动管理，由 [docker/network.sh](../docker/network.sh) 管理自己的规则：

- 默认 bridge `172.30.240.1/24`；用户网络从 `172.30.0.0/16` 分配 `/24`。
- 优先级 9000/9010 的限定网段 policy-routing 规则，对接 Android 当前出口路由表。
- `MOTO_DOCKER_FWD` 仅放行容器网段到出口及已建立连接的返回包。
- `MOTO_DOCKER_NAT` 为容器出网做 MASQUERADE；发布端口使用 `docker-proxy`。
- 不清空 Android 的链、不修改默认防火墙策略；停止时只删除本部署自己的规则。
- 每 15 秒检查出口及规则是否存在，必要时重建；切换蜂窝网络/VPN 尚未完成专项验证。

Docker 的容器内部 DNS 仍需要 iptables。管理环境已安装签名验证通过的 Alpine `iptables-legacy` 及依赖，并将 `iptables` / `ip6tables` 指向 legacy 实现。DNS 的 DNAT/SNAT 发生在容器网络 namespace 内。已验证 Compose 网络中 `web` 解析到 `172.30.0.2` 并实际访问服务。

## 启动、停止与数据

管理脚本：[docker/moto-docker](../docker/moto-docker)。它校验 pid 文件对应的可执行文件，避免误杀复用 PID 的其他进程；启停有锁。启动时加载策略、寻找或创建属于本部署的 loop device，先启动 containerd，再启动 dockerd，最后配置网络。停止先让 Docker 结束容器，再停止 containerd；超时不会强杀。

开机入口为 `/data/adb/service.d/moto-docker.sh`，开关文件为 `/data/adb/moto-docker/autostart`：

当前已启用。整机重启后，不经手动启动，Docker 和 Nginx 自动恢复；HTTP、代理、内部 DNS、卷数据及 enforcing 策略再次验证通过。441 个原厂模块与重启前一致，声卡注册正常、Wi-Fi 恢复。原有 LXC 仍按原配置手动管理，本次重启后已手动恢复运行。

```sh
docker-service enable    # 以后开机启动
docker-service disable   # 取消开机启动，不停止当前服务
docker-service stop      # 停止当前服务，保留镜像和卷
```

示例 Nginx 使用 `restart: unless-stopped`。手动 `docker stop moto-nginx` 后，需要手动再次启动它；`docker compose down -v` 会删除示例持久化卷。普通 `docker-service restart` 保留卷和服务恢复状态。

## 验证范围与限制

| 项目 | 结果 |
|---|---|
| 官方 ARM64 Nginx | HTTP 200，Compose healthcheck healthy |
| 官方 Debian bookworm-slim | aarch64 / glibc 2.36，普通权限写入通过 |
| 本地导入 Alpine 3.22.6 | 普通权限写入、seccomp、设备过滤通过 |
| Compose 网络与 DNS | 服务名解析和跨容器 HTTP 访问通过 |
| 代理 | daemon 拉取、容器 HTTP 和 HTTPS 访问通过 |
| 持久化卷 | 容器重新创建、Docker 服务重启后标记文件保留 |
| 整机重启 | Docker/Nginx 自动启动，标记文件、代理、DNS 再次验证通过 |
| SELinux | 初始 enforcing 拒绝测试通过；现为全局 Enforcing、Docker 域 Permissive，见第 20 篇 |
| Termux 管理 | 真实应用 UID/域中完成 ps、Compose、exec、交互终端及特殊参数传递验证 |
| CPU / 内存 / I/O 配额 | 当前不支持，Docker info 有明确警告 |
| 内存统计 / Swarm / Kubernetes / rootless / GPU / Buildx | 未完成适配验证 |
| 熄屏、拔电、长时间运行及 VPN/蜂窝切换 | 未完成长期验证 |

Android 的 CPU、内存等控制器仍由原有 cgroup v1 层级占用，Docker 所见 cgroup v2 没有这些控制器；另有 CFS bandwidth、PIDS 等内核配置缺项。不要把当前设备当作已经具备标准 Linux 资源隔离能力的生产宿主机。

原始证据保存在 `.work/refs/docker-install-20260922/`。早期 `*-first*`、overlay2 和 VFS 试验文件可能包含失败，不能作为最终配置。静态 Docker、Compose 和 APK 的本地 SHA-256 记录为 `artifacts.json`；Compose 下载值与官方 release API 的 digest 一致，APK 验签见 `package-verification.txt`。

主要运行证据：`snapshotter-write-fixed.txt`、`dns-fixed.txt`、`server-security-validation.txt`、`termux-validation.txt`、`reboot-validation.txt`。Docker 启动日志中 `/proc/1/cgroup` 的 SELinux 拒绝来自宿主环境识别，没有为消除该提示而扩大对 Android init 的权限。

**现有 v3 一键 ROM 没有包含这次 Docker 用户数据部署或第 17 篇的容器内核。** 从该 ROM 完整重装并清数据会清除这里的 Docker 配置、镜像和卷。

官方参考：[Docker 静态安装](https://docs.docker.com/engine/install/binaries/)、[Docker 防火墙](https://docs.docker.com/engine/network/packet-filtering-firewalls/)、[containerd overlayfs 挂载配置实现](https://github.com/containerd/containerd/blob/v2.3.5/plugins/snapshots/overlay/overlay.go)、[Magisk 策略工具](https://topjohnwu.github.io/Magisk/tools.html)。
