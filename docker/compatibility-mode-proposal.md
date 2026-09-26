# Docker 专用 permissive 域方案（2026-09-22）

> 改名说明（2026-09-27）：Rungic改名C阶段之后，`/data/adb/moto-docker`、`moto-docker`、`moto-docker-enter`、SELinux类型`moto_docker`/`moto_docker_file`/`moto_docker_image`、iptables链`MOTO_DOCKER_*`、开机脚本`moto-docker.sh`改为`rungic-*`/`rungic_docker*`/`RUNGIC_DOCKER_*`（运行时目录与数据镜像内的文件已整体重标）；示例项目`moto-server`/`moto-nginx`、`moto-storage-demo`、卷`moto-shared-example`、镜像标签`moto-alpine`改为`rungic-*`。对照见[70篇](70-rungic-rebrand.md)。下文按时间记录的内容保留当时的名称。

状态：用户认可后已落实。设备全局 Enforcing，`moto_docker` 域为 permissive；实际状态由内核策略查询确认。与共享存储的最终配置见 [docs/20-docker-storage.md](../docs/20-docker-storage.md)。下面保留方案的设计与回退说明。

目标：今后更换标准 ARM64 镜像、增删服务、修改 Compose 时，免去针对 Docker 进程逐项维护 SELinux allow 规则的工作。

## 固定方案

- Android 全局保持 Enforcing。
- Docker CLI、dockerd、containerd、runc 和普通容器继续进入现有 `moto_docker` 域，只将该域设为 permissive。
- 保留默认 namespaces、capabilities、seccomp 与设备过滤；不增加 `--privileged` 或 `SYS_ADMIN`。
- 保留已经验证的 ext4、OverlayFS 挂载参数、Android 网络适配和 HTTP CONNECT 代理，将这些作为固定运行环境。

`docker/sepolicy.rule` 中的核心修改为：

```diff
-enforce moto_docker
+permissive moto_docker
```

开机入口和手动启动都会加载该文件，所以必须同步持久化策略，不能只临时执行一次 live 命令。状态命令应分别显示“Android 全局模式”和“Docker 域模式”，不能把 `getenforce=Enforcing` 误解为 Docker 仍受 SELinux 强制约束。

保留已有 allow 规则和文件类型以减少正常操作日志及维持其他主体所需的权限，尤其是 kernel loop worker 对 ext4 镜像文件的访问。无需为了切换模式删除整套策略。后续 Docker 域中未覆盖的访问将不再因为 SELinux 拒绝而失败，通常仍可能记录审计日志。

## 已确认的基础

- 当前内核启用 `CONFIG_SECURITY_SELINUX_DEVELOP=y`，SELinux 实现检查源进程类型的 permissive 位。
- 现有原生启动器在 exec 用户空间之前切换到 `u:r:moto_docker:s0`。
- daemon 与普通容器实际已经处于该域，没有为每个镜像分别设置 SELinux 域。
- Magisk 的策略工具提供按类型设置 permissive/enforce 的操作。
- 当前存储、网络、Compose、代理、重启恢复及 Termux 交互终端已有独立验证记录。

因此，正常应用配置应回到 Docker/Compose 的镜像、端口、卷和环境变量层面，不需要为每个镜像新增 Android SELinux 规则。

## 切换验证与回退

实施时先备份当前策略；同步设备和本地策略后应用新模式。使用不含敏感内容的 canary 验证原先被拒绝的 Docker 域访问现在成功，并核对审计记录中的 `permissive=1`；同时确认全局仍为 Enforcing，普通容器 caps、seccomp 和设备过滤仍有效。验证现有服务、交互终端与整机重启后的持久化模式。

回退仅需恢复该行的 `enforce moto_docker` 并重新加载策略。已有 enforcing 模式的允许规则应保留，以便回退，不需要删除镜像和卷。

## 实际边界

permissive 只减少 SELinux 带来的阻断，不能补齐内核功能。CPU/内存配额、特殊 GPU/USB/内核模块需求仍需要另行适配；Docker 或 Android 基础版本升级也可能涉及底层兼容性。不能承诺任意镜像和任意 Compose 都无需调整。

Android 其他域的强制策略仍生效，但 Docker 自身对可见宿主资源的 SELinux 访问约束被撤除。它不会自动给普通容器 root 宿主权限，原来的其他隔离仍在；然而 Docker daemon 本来是 root，一旦其失守，将少一层保护。定位为运行自己可信服务的专用设备，不作为不可信多租户隔离平台。

参考：[Android SELinux 概念](https://source.android.com/docs/security/features/selinux/concepts)、[Magisk 策略工具](https://topjohnwu.github.io/Magisk/tools.html)。
