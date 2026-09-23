# 用 Termux 管理 LXC（2026-09-22）

> 后续：同一 Termux 现已增加 `docker` / `docker-service` 入口，Docker/Compose 基础部署、代理和网络验证见 [19-docker-installation.md](19-docker-installation.md)。下文的“Docker 待验证”是本篇完成时的阶段记录；LXC 本身仍保持原来的手动启动与 loopback 配置。

设备 ZY32MVJS25 已安装 Termux 0.118.3 ARM64，并配置 `lxc` 快捷命令管理现有的 Alpine 容器。Termux 是普通 Android 应用，容器操作通过 Magisk 授权取得 root。

## 手机上的操作

打开 Termux 后执行：

```sh
lxc status
lxc start
lxc shell
lxc stop
lxc log
lxc exec /bin/cat /etc/alpine-release
lxc --help
```

`lxc shell` 进入后显示 `moto-alpine:/#`，输入 `exit` 回到 Termux，容器仍运行。重启手机后需要 `lxc start`，没有配置容器自动启动。当前只管理名为 `alpine` 的容器；这里的 `lxc` 是本项目快捷脚本，不是 LXD 客户端。

Termux 的 root 权限已通过 Magisk 的“超级用户”界面开启。若以后重装 Termux 或撤销授权，需重新允许；首次提示超时可能被记为拒绝，可在 Magisk → 超级用户 → Termux 中开启。

当前 LXC 仍只有独立 loopback，没有外网、DNS 或端口转发，所以容器里的 `apk add` 和对外服务尚不能按普通联网服务器使用。安装终端没有改变这项限制。

## 安装来源与文件

- 官方版本：[Termux v0.118.3](https://github.com/termux/termux-app/releases/tag/v0.118.3)。
- APK：`~/moto-lxc-20260922/termux/termux-app_v0.118.3+github-debug_arm64-v8a.apk`，35,106,607 字节。
- SHA-256：`72fdb596045116bf5ba1b5bdf5b26fddb9acc0bd074ad9f2da9eb0ae85e83a4e`，与官方 release 校验表相符，APK 签名验证通过。
- 下载遇到代理超时后，复用了本地同版本缓存；官方校验表通过 GitHub release asset API 重新取得，来源写在 APK 目录的 `provenance.json`。
- 手机快捷命令：`/data/data/com.termux/files/usr/bin/lxc`，源码为 [lxc/termux-lxc](../lxc/termux-lxc)。
- root 后端：`/data/adb/moto-lxc/moto-lxc`，源码为 [lxc/moto-lxc](../lxc/moto-lxc)。

无需安装 Termux 插件、开放外部命令执行权限或授予共享存储权限。首次启动使用 APK 内置 bootstrap 完成初始化。

## 实机验证与修正

验证从真实 Termux 会话发起，初始身份为 `u0_a348` / `untrusted_app_27`，没有用 ADB root 代替应用侧调用。

- `status`、`stop`、`start`、`exec`、`log` 已验证。
- `shell` 进入 Alpine 3.22.6；`tty` 返回 `/dev/pts/1`，交互输入和 `exit` 正常。
- 空参数、空格、单引号、美元括号、星号和分号按原样传入容器，没有在 root shell 中被二次执行。
- 退出容器 shell 后容器继续运行；强制停止 Termux 后，已启动的容器仍运行。
- SELinux 保持 Enforcing，未改内核、容器网络、cgroup 或 seccomp 配置。

修正了两处管理入口问题：

1. Magisk 的普通 `su -c` 没有为交互式 attach 分配终端，`shell` 改用 `su -i -c`；其他操作继续使用普通 `su -c`。
2. 管理环境的 `tail` 位于 `/usr/bin/tail`，修正后端 `log` 路径，并同步补充材料中的脚本和 runtime 压缩包。

原始记录位于 `.work/refs/lxc-apk-20260922/`，包括官方校验表、安装结果、Termux 调用验证、交互终端和关闭应用后的状态。

## 用作服务器时的定位

| 需求 | 优先方案 | 说明 |
|---|---|---|
| 少量已移植到 Termux 的服务、脚本、开发工具 | Termux 直接运行 | 简单，但不是通用 Debian/Ubuntu 用户空间 |
| 使用现成 ARM64 Docker 镜像、Compose 部署多个服务 | Docker | 不需要再套 LXC；仍须完成当前 Android 系统上的兼容验证 |
| 使用标准发行版包、系统目录布局、多个传统 Linux 服务 | LXC | 可提供 Linux 用户空间；发行版及 init 系统要分别验证 |
| 在完整 Linux 环境里统一管理 Docker 与其他服务 | LXC 内 Docker | 有用途，但需嵌套权限、cgroup、存储和网络适配，当前未验证 |

建议把 Termux 作为管理入口，优先验证直接 Docker 作为服务运行层；LXC 按需保留。ARM64 只是 CPU 架构，普通 glibc Linux 二进制不等于能在使用 Android Bionic 的 Termux 中直接运行。纯 Termux 也不会自动提供 Docker daemon 所需的内核和权限。

当前证据只有 LXC 基础生命周期通过，不能称为完整服务器方案。Docker、可靠外网/端口映射、熄屏长期运行、断网恢复、服务自启动及资源限制仍需专项验证。具体 Docker 比较与当前内核配置见 `.work/refs/lxc-apk-20260922/docker-comparison.md`。

依据：[Termux 执行环境](https://github.com/termux/termux-packages/wiki/Termux-execution-environment)、[LXC 介绍](https://linuxcontainers.org/lxc/introduction/)、[Docker 静态安装说明](https://docs.docker.com/engine/install/binaries/)。
