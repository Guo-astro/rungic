# 系统监视器的 GPU 与磁盘：ksystemstats 补上 KGSL 与 mountinfo（2026-10-03）

用户反馈：系统监视器（plasma-systemmonitor）的“概览”和“历史”页顶部提示“This page is missing some sensors and will not display correctly.”，GPU 饼图和磁盘条没有数据。

标注：“源码”指核对过的上游源码；“离线”指本机（K8，x86）与 Mac mini 构建机上的构建和测试；“实机”指 G100 S（XT2537-4，Adreno 710，Android 16，Ubuntu 26.04 容器）。

## 现象与原因

- **提示条的来源**（源码：libksysguard 6.6.5 `faces/SensorFaceController.cpp`，plasma-systemmonitor `src/page/PageContents.qml`）：面板里的传感器查询（可以是正则）在 ksystemstats 中一个也匹配不到时，记为 missing；页面有任何 missing 就显示这条提示。
  - 概览页：GPU 饼图查 `gpu/all/usage`，磁盘条查 `disk/(?!all).*/used`；
  - 历史页：GPU 曲线查 `gpu/gpu\d+/usage`；
  - 用户自己的 `~/.local/share/plasma-systemmonitor/overview.page`（9 月 24 日）覆盖系统页面，内容同样查这些传感器，所以不能靠改页面解决。
- **GPU：插件只认 DRM 设备**（源码：ksystemstats 6.6.6 `plugins/gpu/LinuxBackend.cpp`）：
  - 用 udev 枚举 `drm` 子系统的 `card*`，按 PCI 厂商号选 AMD、Intel、NVIDIA；
  - 本机 GPU 由 Android 内核的下游驱动 KGSL 驱动：只有 `/dev/kgsl-3d0` 和 `/sys/class/kgsl/kgsl-3d0`，没有 DRM 渲染节点；
  - sysfs 里的 `card0` 是显示控制器（msm SDE），没有 PCI 父设备，被当作“不支持的 GPU”跳过；
  - 没有任何 GPU 设备，就不创建 `gpu/all`，所以 `gpu/all/usage` 也不存在。
- **磁盘：Solid 在容器里找不到卷**（源码：`plugins/disks/disks.cpp`）：
  - 插件只用 Solid 列出的 StorageVolume；
  - 容器里没有 udev、UDisks2，也没有磁盘的 `/dev` 节点（没有 `/dev/block`），Solid 一个卷都列不出；
  - 于是 `disk/<卷>/*` 都不存在，`disk/all/*` 是空的聚合。
- **两个桌面都受影响**（实机，另一位 agent 的前期调查）：手机会话和独立桌面（工作区 0，自己的 D-Bus）用的是同一个 `/usr/bin/ksystemstats`，各自按需由 D-Bus 激活；容器里 `/sys/class/kgsl/kgsl-3d0/*` 对普通用户可读。

## 调研：上游和现有做法

| 来源 | 内容 | 结论 |
|---|---|---|
| ksystemstats MR !149（2026，Leon Silcott，未合入） | 新增 `LinuxMsmGpu`：识别上游 msm DRM 驱动（freedreno 的内核侧），按 `/proc/*/fdinfo` 的 `drm-engine-gpu` 汇总使用率，频率读 devfreq | 前提是 DRM 设备和 fdinfo，KGSL 两者都没有，不能直接用；借鉴了“只在订阅时轮询”和 devfreq 频率的做法 |
| 上游 `LinuxAmdGpu`/`LinuxIntelGpu` | AMD 读 sysfs `gpu_busy_percent`；Intel 由辅助进程读 perf 计数 | 设备类的写法照搬：继承 `GpuDevice`，名称、频率、温度用同样的传感器 ID |
| KGSL 驱动（源码：msm-kgsl gfx-kernel.lnx.13/14/15 `kgsl_pwrctrl.c`、`kgsl_pwrscale.c`） | `gpu_clock_stats`：各功率级累计的忙时间（微秒），读时持 `device->mutex` 调 `kgsl_pwrscale_update_stats`，GPU 活动时读一次硬件计数并累加；`gpubusy`：最近满 1 秒“上电时间”里的忙/总，GPU 断电时读一次清零；`gpu_busy_percentage` 同源；`temp`：GPU 各温区最高值（毫摄氏度，无温区时为 0）；`devfreq/gpu_load` 读后重置调频器的统计 | 使用率用 `gpu_clock_stats` 的增量除以墙钟时间；读不到时退回 `gpubusy`；不碰 `gpu_load` |
| Solid / UDisks2 | 容器里没有后端 | 不在容器里补 udev 或 UDisks2：只为监视器要拉起整套设备管理，且 Android 的块设备节点本不该进容器 |
| `/proc/self/mountinfo` + `statvfs` + `/proc/diskstats` | 内核直接给出挂载、容量和读写量 | 只在 Solid 没有任何卷时作后备，正常 Linux 不受影响 |

`gpubusy` 只按“上电时间”计，GPU 大部分时间断电时会把短暂工作的比例放大；`gpu_clock_stats` 按墙钟时间计，与 CPU 使用率的含义一致，所以作首选。

许可证：ksystemstats 为 GPL-2.0-only OR GPL-3.0-only OR LicenseRef-KDE-Accepted-GPL（新增文件沿用）；测试夹具 CC0-1.0。

## 实现：`packages/ksystemstats`

固定 Ubuntu `ksystemstats 6.6.6-0ubuntu0.1`（resolute-updates，`.dsc` sha256 `5cab390a…`、orig `a1892442…`、debian `64b3967a…`），补丁在 `debian/patches/rungic/`，版本 `+rungic1`；`release/packages.json` 的 `rebuilt` 加入 `ksystemstats`。

**`kgsl-gpu.patch`**：

- `LinuxBackend::start()` 在 udev 枚举之后，若 `/sys/class/kgsl/kgsl-3d0/gpu_model` 可读，加入一个 `LinuxKgslGpu`，ID 取第一个未用的 `gpuN`（本机 `gpu0`，对象名“GPU 1”）；有了设备，`AllGpus` 自动给出 `gpu/all/usage`。
- 传感器：
  - `name`：`gpu_model`，`Adreno710v1` 显示为 `Adreno 710`；
  - `usage`（%）：`gpu_clock_stats` 各级之和的增量 ÷ 经过时间；订阅时取基线，计数回退时重取；
  - `coreFrequency`（MHz）：`devfreq/cur_freq`，范围取 `devfreq/available_frequencies` 的最小、最大值（`min_freq`/`max_freq` 是当前策略，会变，只作后备）；
  - `temperature`（°C）：`temp` ÷ 1000，0 视为无温区不更新；
  - `totalVram`、`usedVram`、`memoryFrequency`、`power` 保持空：内存与 CPU 共用，驱动也不报功耗，不编造。
- 每个文件只在对应传感器被订阅时读取，与 MR !149 相同。
- 解析在 `KgslStats.{h,cpp}`，测试 `plugins/gpu/autotests/kgsl.cpp`（`kgsltest`）：型号、`gpu_clock_stats`、`gpubusy`、频率表、采样器（基线、回退、超过 100% 截断），以及用临时目录模拟 sysfs 的设备测试（未订阅不读、订阅后数值、`gpubusy` 后备、不给显存）。

**`disks-mountinfo-fallback.patch`**：

- Solid 列不出任何可用卷时，`addMountInfoVolumes()` 读 `/proc/self/mountinfo`：
  - 只要块设备上的文件系统：主设备号 0 的（proc、sysfs、tmpfs、FUSE、overlay 等）不要；btrfs 显示匿名的 0 号设备，来源是 `/dev/…` 时保留；squashfs、erofs、iso9660 这类只读镜像不要；
  - 同一设备挂了多处（本机数据分区 `dm-53` 在容器里挂了九处）只算一次，挂载点依次选 `/`、整个文件系统挂载的位置、含家目录的位置、最短的路径；
  - ID 用 device-mapper 名（`/sys/dev/block/M:m/dm/name`：`rungic-root`、`userdata`，重启后 dm 编号会变，名字不变），否则用内核设备名；
  - 名称：`/` 叫“System”（系统），家目录所在的卷叫“Home”（主目录），其他用挂载点；补丁同时加了这两条 zh_CN 翻译。
- 容量用 `statvfs`（总量 `f_blocks`，可用 `f_bavail`，已用 = 总量 − 可用，与原插件经 KIO 得到的口径相同）；读写速率沿用原插件对 `/proc/diskstats` 的处理（键为 `/dev/<内核名>`，取自 `/sys/dev/block/M:m/uevent` 的 `DEVNAME`）。
- 解析和挑选在 `MountInfo.{h,cpp}`，测试 `plugins/disks/autotests/mountinfo.cpp`（`mountinfotest`），夹具是本机容器的 mountinfo（用户名改为 user）和一份 btrfs 桌面样例。
- 挂载只在启动时读一次；容器里没有热插拔的块设备。

**开发覆盖工具**：`tools/rungic_dev.py` 原先只覆盖已在已装发布里的包；ksystemstats 是新加入 `rebuilt` 的组件，已装发布 `20260930.10` 里没有它。现在对这类组件，以手机上已装的发行版版本为基准（`base`，第二次覆盖沿用第一次记下的）；`reset` 时按这个版本装回 Ubuntu 的包。测试 `tools/test_rungic_dev.py` 新增两项。

## 离线验证

- x86（`rungic-build-kwin:26.04` 镜像加装构建依赖，`BUILD_TESTING=ON`）：`kgsltest` 14 项、`mountinfotest` 6 项通过；全部 ctest 中 `TestLinuxCpu`、`ksystemstatstest` 失败，未打补丁的基线在同一环境里同样失败（环境原因），其余通过。
- Mac mini（arm64，Ubuntu 26.04 容器）`build_on_device.py ksystemstats full`：`ksystemstats_6.6.6-0ubuntu0.1+rungic1_arm64.deb` 构建成功，含两个插件与 zh_CN 翻译。Ubuntu 打包关闭了测试（`-DBUILD_TESTING=OFF`），L1 测试在单独的测试构建里运行（docs/71）。
- `pq.py lint ksystemstats`、`tools/test_rungic_dev.py`、`tools/test_pq.py` 通过。

## 实机验证（G100 S，2026-10-03）

- **部署**：开发覆盖 `rungic_dev.py deploy ksystemstats --restart never`（Mac mini 增量构建 54 s），`ksystemstats 6.6.6-0ubuntu0.1+rungic1+dev20261002t185632.266f40b.dirty` 装在发布 `20260930.10` 之上；记录 `.work/dev-deploy/20261003-035632-deploy/`。`[verify] apt=ok`；完整性 `drift` 来自已有的开发覆盖和一个与本次无关的无主文件（`/usr/lib/rungic-cua/rungic_cua/keyring.py`），`release_mismatch` 为空。之后结束两个会话里的 ksystemstats，由 D-Bus 按需重新激活；没有重启 Plasma 会话。
- **两条总线都有传感器**：`kstatsviewer --list` 在手机会话和 `rungic-workspace-env 0` 下都列出 `gpu/gpu0/{name,usage,coreFrequency,temperature,…}`、`gpu/all/usage`、`disk/rungic-root/*`、`disk/userdata/*`、`disk/all/*`（名称 System / Home）。
- **数值**：
  - `gpu/gpu0/name` = `Adreno 710`；空闲时 `usage` 0–0.02%，频率 345 MHz，温度约 35 °C；
  - 用容器里无窗口的 EGL surfaceless 负载程序（GLES2 着色器画进 FBO，8 s，渲染器 FD710；源码留在 `.work/verify/20261003-ksystemstats/gpuload.c`）加载 GPU：`gpu/gpu0/usage` 与 `gpu/all/usage` 在 0.5 s 内升到 67%，随后稳定在 85–89%，频率 500 MHz，温度升到 40 °C；负载结束后一帧内回到 18%，再回到约 0%。同时直接读 sysfs：`gpu_clock_stats` 增量算出 86.9%，`gpubusy` 为 87.8%，一致；
  - 磁盘：`disk/rungic-root` 总量 168 029 433 856 字节、已用 22.2%，`disk/userdata` 总量 238 233 300 992 字节、已用 41.6%，与 `df -B1 / /home` 的总量一致（已用 = 总量 − 可用，含保留块，与原插件口径相同）；写 200 MiB 时 `disk/userdata/write` 与 `disk/all/write` 达到约 331 MB/s，读速率也随实际读取变化；
  - 工作区 0 的 ksystemstats 给出相同的名称、频率和磁盘值。
- **读 sysfs 的代价**：在手机容器里用 Python 循环读，空闲时每次约 19–27 µs；GPU 满载时 `gpu_clock_stats` 每次约 35 µs（要持 KGSL 设备锁、读硬件计数），`gpubusy` 24 µs。每个 ksystemstats 每 0.5 s 读一次，可以忽略，因此不改用 `gpubusy`。
- **ksystemstats CPU（手机会话，每次 60 s，`/proc/<pid>/stat` 的 utime+stime，订阅时才计）**：

| 订阅的传感器 | CPU（单核占比） |
|---|---|
| 原包：CPU、内存、网络，加上当时不存在的 GPU/磁盘传感器 | 0.42% |
| 新包：CPU、内存、网络 | 0.37% |
| 新包：再加 GPU 4 项 | 0.48% |
| 新包：再加磁盘 6 项 | 0.80% |
| 新包：概览页那一套（GPU + 磁盘全部） | 0.85%、0.88% |

  - GPU 约多 0.1%；磁盘约多 0.4%，主要是原插件每 0.5 s 解析一遍 `/proc/diskstats`（本机 216 行，大多是 loop 设备），statvfs 两次很便宜。正常 Linux 上原插件也是这个做法。只在系统监视器或小组件打开时发生，没有订阅时 ksystemstats 不读这些文件（客户端都退出后进程自己退出）。
- **未做**：没有打开系统监视器界面截图（用户在用手机，不在用户屏幕上开窗口）；提示条消失和饼图变化要由用户在界面上确认。
- **用户验收（2026-10-03）**：用户打开系统监视器确认，红色的缺少传感器提示已经消失，GPU 有数据。

## 映射与边界

| 应用 | 接口 | 共享后端 | Android 硬件 |
|---|---|---|---|
| 系统监视器（概览 GPU 饼图、历史 GPU 曲线）、System Monitor 小组件 | ksystemstats D-Bus `org.kde.ksystemstats1`：`gpu/gpu0/{name,usage,coreFrequency,temperature}`、`gpu/all/usage` | ksystemstats GPU 插件 `LinuxKgslGpu` | `/sys/class/kgsl/kgsl-3d0`（`gpu_clock_stats`、`gpubusy`、`temp`、`devfreq/*`）→ KGSL 驱动 → Adreno 710 |
| 系统监视器（概览磁盘条）、Disk Usage 小组件 | `disk/<id>/{total,used,free,usedPercent,freePercent,read,write}`、`disk/all/*` | ksystemstats 磁盘插件（Solid 无卷时的 mountinfo 后备） | `/proc/self/mountinfo`、`statvfs`、`/proc/diskstats` → `rungic-root`（loop 上的 ext4 镜像）与 `userdata`（f2fs 数据分区） |

- 根文件系统镜像本身是 `userdata` 上的文件，`disk/all/total` 把两者相加，物理空间有重叠；各卷的数值是对的。
- 只看得到 GPU 的总体使用率，没有按进程的 GPU 使用（KGSL 没有 DRM fdinfo）。
- 显存、显存频率、功耗不提供。
- 磁盘只在 ksystemstats 启动时读挂载；之后新挂的块设备要等它下次启动。
- 正式发布时 ksystemstats 会随 `rebuilt` 进入发布；在此之前它只是开发覆盖，`rungic_dev.py reset ksystemstats` 会装回 Ubuntu 的 `6.6.6-0ubuntu0.1`（新增的回退路径只经离线测试，实机未执行 reset）。
- 尚未向上游提交（按项目约定不计划上游）；上游 MR !149 合入后，KGSL 设备与其 msm DRM 设备不会重复（本机没有 msm DRM 渲染节点）。
