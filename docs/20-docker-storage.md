# Docker 卷与手机共享存储（2026-09-22）

两种存储挂载都已接通：Docker 管理的普通卷，以及手机“内部存储”目录的 bind mount。同一个容器可以同时使用它们；命名卷还可以显式指向共享目录。

## 选哪种

| 用途 | 配置方式 | 手机文件管理器 | 文件特性 |
|---|---|---|---|
| 数据库、依赖 Linux 权限的应用数据 | 普通命名卷 `app_data:/data` | 不直接显示，可导出备份 | ext4，保留 UID/GID、chmod、链接 |
| 配置、下载、照片、静态网站、备份 | `/sdcard/Docker/shared:/data` | 直接查看和操作同一份文件 | Android 共享文件语义 |
| 想用卷名管理、同时能在手机查看 | local driver 的 bind-backed 命名卷 | 直接查看对应共享目录 | 同样是 Android 共享文件语义 |

原生卷共用当前 **8 GiB 稀疏 ext4** 数据盘；这是逻辑容量上限，不是预先占满 8 GiB，也不会自动扩大。共享目录直接使用手机 userdata 的剩余容量，不受这 8 GiB 限制。两者物理上都在手机闪存，只是文件系统和访问方式不同。

Docker 镜像层、containerd 元数据继续使用私有 ext4。把完整 `data-root` 改到 `/sdcard` 并不能获得可靠的 Linux 存储语义，也不能把镜像层当作普通业务文件直接编辑。

## 路径与例子

已创建 `内部存储/Docker/`：

```text
Docker/
  README.txt
  compose-example.yaml
  shared/
    web-example/index.html
    named-example/
    compatibility-check/
  exports/
```

Docker 中同一个位置为 `/sdcard/Docker` 或 `/storage/emulated/0/Docker`。其他共享目录也可以明确挂载，例如 `/sdcard/Download`；已用 UID 101 在 Download 下的独立临时测试目录验证读写，并清理测试目录。

下面是最常用的目录挂载，先在文件管理器创建 `Docker/shared/myapp`：

```sh
docker run --rm \
  --mount type=bind,src=/sdcard/Docker/shared/myapp,dst=/data \
  moto-alpine:3.22.6 ls -la /data
```

只需要读取的照片、配置等可在 `--mount` 中加 `readonly`，或在 Compose 的短写法末尾加 `:ro`。容器只能看到明确挂入的目录，不会因为接通共享存储就自动看到整个内部存储。

普通命名卷保持标准写法：

```yaml
services:
  app:
    image: YOUR_ARM64_IMAGE
    volumes:
      - app_data:/data
volumes:
  app_data:
```

如果希望使用卷名，同时让文件管理器看到内容：

```yaml
services:
  app:
    image: YOUR_ARM64_IMAGE
    volumes:
      - shared_data:/data
volumes:
  shared_data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /sdcard/Docker/shared/myapp
```

这最后一种配置使用 Docker 的标准 local volume driver，并非自定义 volume 插件。它只有“卷名”管理方式的变化，底层仍是共享目录，不能因此获得 ext4 的文件特性。

## 文件管理器中的 Compose 示例

已放置可直接使用的 [compose-storage-example.yaml](../docker/compose-storage-example.yaml)，手机文件名为 `Docker/compose-example.yaml`。它同时使用普通缓存卷、共享 HTML 目录和共享目录命名卷：

```sh
docker compose -f /sdcard/Docker/compose-example.yaml up -d
docker compose -f /sdcard/Docker/compose-example.yaml ps
docker compose -f /sdcard/Docker/compose-example.yaml down
```

启动后访问 `http://手机IP:18089/`。修改 `Docker/shared/web-example/index.html` 后刷新网页即可验证；应用自己的监听重载机制另当别论。示例与原有 `moto-nginx` 的 18088 端口独立。

验证结束后已停止此演示服务，保留示例配置和数据；执行上面的 `up -d` 即可再次启动。原有 18088 服务继续运行。

## 一次性兼容处理

Android 原始 FUSE 共享存储会拒绝部分非 Android 用户 ID。实际测试中，UID 0 和 1000 可读写，UID 101 返回 `Bad address`；增加 `media_rw` 组没有解决。这与 SELinux permissive 无关。

因此在 Docker 私有 mount namespace 内，用 bindfs 1.18.4 提供统一的共享存储视图。所有底层 Android 文件访问由管理进程执行，普通容器中的 UID 则看到可读写的共享文件。**用户不需要为每个镜像另设 Android UID、增加共享存储组或添加 SELinux allow 规则。**

此视图覆盖 `/storage/emulated/0`，`/sdcard` 是其别名。Android 原来的挂载和文件管理器保持原有视图；只在 Docker namespace 内适配。`moto-docker` 统一管理 bindfs、containerd、dockerd 的启动和停止。

bindfs 使用上游未修改的 1.18.4 源码，交叉编译为 ARM64 musl；libfuse3 3.16.2-r1 来自签名验证通过的 Alpine APK。来源与 SHA-256 在 `.work/refs/docker-install-20260922/shared-adapter-artifacts.json`，编译脚本和日志同目录保留。启动参数在 [docker/runtime-start](../docker/runtime-start)。

## 共享目录的边界

- 普通文件的创建、读写、重命名、删除都支持，文件管理器和容器操作同一份数据。
- 共享视图统一呈现权限；`chmod/chown` 不用于保存真实 Linux 权限，符号链接仍不支持。不要把数据库、`node_modules` 等强依赖这些特性的目录放在这里。
- 保留 `nosuid,nodev,noexec`；共享目录定位于数据，容器程序和依赖应放在镜像或普通卷中。
- 额外 FUSE 层不适合高频小 I/O 的数据库；文件变更通知/inotify 也不保证像原生 Linux 目录一样工作，需要应用重载或轮询。
- 加锁设备首次开机时，共享存储可能需要先解锁；启动脚本等待共享目录出现。当前设备的实际重启结果另记在验证记录中。
- 普通 Docker 卷不会自动变成公共文件夹。数据库内容要在文件管理器查看，优先使用数据库自己的导出；文件型卷可通过容器读卷、写入 `Docker/exports`。

例如，把已停止写入的文件型卷归档到共享目录：

```sh
docker run --rm \
  --mount type=volume,src=YOUR_VOLUME,dst=/source,readonly \
  --mount type=bind,src=/sdcard/Docker/exports,dst=/backup \
  moto-alpine:3.22.6 tar -czf /backup/volume-backup.tar.gz -C /source .
```

运行中数据库的文件归档不等于一致的数据库备份；使用其备份工具或先停止相关服务。

## SELinux 与验证

根据用户认可的方案，`moto_docker` 专用域已改为 **Permissive**，Android 全局保持 **Enforcing**。`docker-service status` 通过内核实际策略查询分别显示这两项，不是仅检查配置文件。普通容器的默认 capabilities、seccomp 和设备过滤保留。

已完成：普通卷 UID 999/chmod 0700/符号链接读写；共享目录 UID 0、101、999、1000、10001、65534 读写及重命名；bind-backed 命名卷；真实系统文件管理器中查看容器创建的文件；Nginx 非 root worker 读取共享网页，以及 Android 修改后 HTTP 返回新内容；默认 seccomp 和设备拒绝测试；专用域 canary 放行且审计 `permissive=1`。

实际整机重启验证也已通过：boot ID 改变后 Docker 自动启动，Android 仍为 Enforcing、Docker 域为 Permissive；普通卷和共享目录的标记文件保留；UID 101 可继续写入共享目录，Android 侧可立即读取；该非 root 进程的有效 capabilities 为 0，seccomp 为 2。原有 18088 服务和共享目录示例 18089 均在重启后返回 HTTP 200。原有 LXC 也已恢复运行。

证据目录为 `.work/refs/docker-install-20260922/`，主要文件：`storage-semantics.txt`（含原始 FUSE 的失败边界）、`shared-uid-validation.txt`、`shared-files-ui.xml`、`shared-volume-validation.txt`、`arbitrary-shared-path.txt`、`storage-compose-validation.txt`、`storage-reboot-validation.txt`、`storage-reboot-http.txt`、`storage-final-status.txt`。

官方参考：[Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)、[Docker volumes](https://docs.docker.com/engine/storage/volumes/)、[bindfs 手册](https://bindfs.org/docs/bindfs.1.html)。
