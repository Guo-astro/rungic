# 原厂系统 RAM 占用实测（2026-09-22）

后续变更：用户随后要求删除“智享家”，已从当前手机机主用户卸载 `com.lenovo.octopus`，确认安装列表与进程中均不再存在。下文数值是卸载前的分析快照，操作记录见文末。

当前约 3.43 GiB 的 Android 已用 RAM，来自非缓存进程约 2.49 GiB 和内核/驱动等约 0.94 GiB。原厂功能进程是明确的额外开销来源：按 Motorola、Lenovo、ZUI、搜狗和百度包名前缀统计，69 个进程合计约 1.40 GiB PSS，其中约 572 MiB 是缓存进程，约 863 MiB 为非缓存进程。这个分类包含桌面、定位、硬件接口等有实际功能的组件，不能视为全部可删除。

Docker + 当前 Nginx 工作负载约 138 MiB PSS，最小 LXC 约 2.7 MiB，不能解释数 GiB 的差距。

## 测量条件和口径

- 设备：XT2537-4 / mumba_cn，8 GB RAM，原厂 Android 16 `W1WAA36.48-23-10`。
- 当前使用支持容器 namespace 的内核；Docker 专用域 permissive，Android 全局 Enforcing。
- 两次采样为 22:45、22:49 CST，开机约 7、11 分钟。Docker/Nginx、最小 LXC 正在运行，之前使用过设置、Termux 和文件管理器；这不是清空数据后、完全未操作的首启基线。
- 本轮只读取运行状态与 APK 资源，未禁用应用、杀进程、清缓存或修改系统配置。
- 进程排名使用 `dumpsys meminfo` 的 **PSS**，按共享比例分摊内存；不能把 RSS 直接相加。例如 SystemUI 的 RSS 约 512 MiB，而 PSS 约 245 MiB。
- 文中 KiB/MiB/GiB 为二进制单位。手机界面也可能使用十进制 GB 或平均值，不能仅比较页面数字。

| 指标 | 第一次 | 第二次 | 含义 |
|---|---:|---:|---|
| 内核可见总 RAM | 7.35 GiB | 7.35 GiB | `MemTotal`，不同于标称容量 |
| Android `Used RAM` | 3.430 GiB | 3.436 GiB | 非缓存进程 PSS（含图形口径修正）+ 内核统计 |
| 其中非缓存进程 | 2.493 GiB | 2.498 GiB | 应用、系统服务、native 服务等 |
| 其中内核相关 | 960.4 MiB | 960.3 MiB | 内核分配、页表、共享内存、未映射 DMA-BUF 等 |
| 缓存应用 PSS | 658.2 MiB | 681.3 MiB | 未计入上述 `Used RAM` |
| Linux `MemAvailable` | 4.25 GiB | 4.28 GiB | 内核估算可供新负载使用的内存，不等于完全空闲页 |
| ZRAM 实际 RAM 占用 | 49.6 MiB | 50.0 MiB | `dumpsys` 统计；5.51 GiB 是交换空间逻辑容量 |

两次采样主要占用接近。`/proc/pressure/memory` 的 avg10/60/300 均为 0，采样时没有明显内存压力。低 `MemFree` 不意味着只剩约 0.5–0.7 GiB 可供服务使用，因为文件缓存等可以回收。

不能把所有表格相加：厂商进程、Docker 等是进程总量的子集；GPU、DMA-BUF、缓存池和 pinned 页也与总量有交叠。Android 会修正 memtrack 与 DMA-BUF/GPU 统计，第一次原始逐进程 PSS 总和为 3,346,326 KiB，修正为 3,287,490 KiB，再减缓存进程 673,956 KiB，得到 used PSS 2,613,534 KiB。

## 主要进程

以下是第一次采样，名称优先使用设备 APK 的中文标签；状态取 Android OOM 分组。`Foreground` / `Visible` 是进程重要性分组，不表示用户正在操作其界面。

| 组件 | PSS（MiB） | 状态 / 说明 |
|---|---:|---|
| `system_server`（dump 名为 `system`） | 289.4 | 系统核心，包含基础 Android 和厂商扩展 |
| SystemUI | 244.8 | 状态栏、通知、锁屏等系统界面 |
| 我的屏幕 `com.motorola.myscreen` | 146.3 | 非缓存，被原厂桌面的 `MyScreenService` 绑定 |
| 智享家 `com.lenovo.octopus` | 134.3 | Cached，约 105 MiB 为私有 Code 分类 |
| 高通相机 provider | 113.8 | native 硬件服务，没打开相机也存在 |
| SurfaceFlinger | 113.6 | 显示合成服务，包含图形相关统计 |
| 搜狗输入法 | 85.4 | Perceptible，输入服务 |
| 原厂桌面 | 78.7 | 另有应用预测进程 8.8 MiB |
| 原厂浏览器 | 73.6 | Cached，另有沙箱进程 11.3 MiB（Cached） |
| 系统设置 | 70.5 | B Services，曾使用过设置 |
| 超级互联 Smart Connect | 61.4 | 非缓存，另有 core 进程 8.9 MiB |
| `com.motorola.deviceguard` | 58.3 | Persistent；APK 标签为“设备信息”，实际含电池、屏幕时间等管家服务 |
| Magisk root Java 服务 | 56.8 | 本次 root/管理操作环境的一部分 |
| 个性化 | 39.4 | Cached |
| Moto 反馈 | 37.2 | Cached |
| 家庭空间 | 32.9 | Cached |
| 联想应用商店 | 30.9 | Cached |
| 天气时钟组件 | 27.7 | 非缓存 |
| 游戏模式 | 26.4 | 非缓存 |
| 钱包 | 24.2 | 非缓存 |
| AI 出行 | 23.2 | 非缓存 |
| 智能插件 | 18.8 | 非缓存 |

厂商前缀合计 1,435.3 MiB，包括非缓存 863.3 MiB、缓存 571.9 MiB。缓存进程可由系统在压力下回收；它们的当前 PSS 不能直接当作禁用后稳定节省的内存。约 863 MiB 的非缓存部分也包含需要保留或替换的桌面、输入法、通信/定位和厂商基础服务。

之前的 [第三方预装精简](10-stock-debloat.md) 删除了抖音、视频、资讯等 15 个明确应用；保留了原厂桌面、钱包、应用商店、游戏模式、互联、输入法等系统功能。因此“删除推广预装”不会自动把 MYUI 的后台功能栈变成 AOSP。

## 内核、驱动和缓存占了什么

Android 汇总的内核相关占用约 960 MiB。相邻 `/proc/meminfo` 采样显示：

| 项目 | 约占用 | 说明 |
|---|---:|---|
| 不可回收 Slab | 342–349 MiB | 内核对象，包含内存映射、任务和文件系统等结构 |
| VmallocUsed | 209 MiB | 包含虚拟映射的内核栈、模块等，不可再重复加 KernelStack |
| 页表 | 131–132 MiB | 为大量进程和虚拟内存映射提供地址转换 |
| Shmem | 102 MiB | 共享内存、tmpfs 等统计 |
| 未映射 DMA-BUF | 180 MiB | 图形/显示/硬件缓冲的一部分 |

这些来自接近但非完全同时的采样，不应强行精确相加。`vmallocinfo` 可归因部分包括内核栈约 65 MiB、加载模块约 53 MiB、F2FS 段管理约 28 MiB、ZRAM 初始化约 22 MiB、shadow call stack 约 16 MiB。这里的 ZRAM 元数据与压缩页数据也不能简单视为同一项。

Slab 中较大对象包括 `vm_area_struct` 72.5 MiB、`erofs_pcluster-1` 52.8 MiB、`inode_cache` 31.1 MiB、`task_struct` 23.7 MiB、`vma_lock` 22.8 MiB。此清单含可回收和不可回收对象，不能把它们全部加到不可回收 Slab 上。

另外观察到：

- DMA-BUF heap pool 约 564–566 MiB，是缓存池报告值；AOSP 将可回收池纳入缓存口径，不能再作为一笔独立“常驻 App 内存”加到 Used RAM。
- Pinner 实际固定约 **145.5 MiB** 文件页：桌面及依赖约 35.8 MiB、WebView 20 MiB、系统框架约 89.7 MiB。752 MiB 是配额上限，不是实际锁住的量。这些页已经在总内存统计中。
- GPU 总使用约 190 MiB，其中大部分本来就是 DMA-BUF；再次相加会重复计算。
- `Lost RAM` 约 175–188 MiB 是统计残差项，不能据此命名为某个隐藏 App，也不能直接判断为泄漏。
- 属性中存在 `zram_wb_size=4096M`、ramboost 配置，但实际压缩 RAM 数据约 50 MiB，不能据“4G 扩展内存”配置推断 RAM 被固定占了 4GB。

## Docker / LXC 的贡献

| 项目 | 第一次 PSS |
|---|---:|
| dockerd | 74.9 MiB |
| containerd | 36.9 MiB |
| containerd shim | 10.9 MiB |
| Nginx 主进程 + 8 个 worker | 10.2 MiB |
| 两个 docker-proxy | 4.2 MiB |
| 共享存储 bindfs | 1.0 MiB |
| 上述 Docker 合计 | **138.2 MiB** |
| LXC 管理进程 + 容器 init/sleep | **2.7 MiB** |

这是对应进程 PSS，并未宣称涵盖所有容器引起的内核开销和可回收文件缓存。Docker 的 8 GiB ext4 文件是磁盘容量，不是预留 RAM。

## 如何理解与 GSI 的差距

工作区记录过 Android 17 AOSP GSI + 原厂 Android 15 vendor；现在是原厂 Android 16 用户空间和不同 vendor 基线。没有找到能与本轮对齐的历史 GSI `dumpsys meminfo` / `/proc/meminfo`，用户提到的约 900MB 目前作为观察值保留。

基于本轮证据，可以确认原厂保留了很多额外功能进程，也有较重的桌面/系统界面和内核结构开销。GSI 缺少许多这类厂商功能，是差距的合理解释之一。但还不能把 4GB 与 900MB 的全部差值精确归因给某些 APK：系统版本、采样时机、屏幕状态、使用历史、后台服务，以及 UI 的平均/瞬时/缓存口径都需要一致。

GSI 仍然需要 system_server、SystemUI、图形服务和设备驱动；本轮测得的这些占用不能全部当作 GSI 可省掉的量。原厂框架内部增加了多少，也需要 GSI 对照才能拆分。

## 面向服务器用途的精简顺序建议

1. 优先评估无需使用的厂商附加功能：我的屏幕、智享家、超级互联、家庭空间、游戏模式、AI 出行/智能插件、钱包、应用商店、反馈等。分别记录它们的非缓存与缓存占用。
2. 输入法、桌面和文件管理器属于用户仍可能使用的功能。需要先决定保留或替换，不能为了降低读数直接全部关闭。
3. `deviceguard` 有 system_server 的服务绑定；UI、电话、定位、网络、存储和硬件 HAL 等不能按包名前缀批量删除。具体禁用方案需要检查依赖并逐组验证，不能把本清单当成删除白名单。
4. 不用频繁清缓存或关闭 ZRAM 来制造低占用截图。目标应是减少不需要的常驻和唤醒，并保持 Android、文件管理、Termux、Docker、Wi-Fi 正常。
5. 本轮没有执行精简，也没有承诺降到 900MB。实际收益必须以调整后相同启动/解锁/等待条件的测量为准。

## 本地证据及参考

证据目录：`.work/refs/memory-audit-20260922/`。

- `baseline.txt`、`meminfo.txt`、`meminfo-second.txt`：两次总量及逐进程 PSS。
- `pss-processes.json`、`summary.json`：整理后的数值、分组、APK 标签和第二次进程采样。
- `activity-processes.txt`、`oem-services.txt`：重要性状态、服务绑定和包配置。
- `framework-extras.txt`：Pinner、procstats 和重点进程详细内存。
- `kernel-extra.txt`、`kernel-pools.txt`：Slab、vmalloc、ZRAM、DMA pool、压力等。
- `apk-labels/`：从设备 APK 仅提取 manifest/resources 生成的标签查询文件；这些精简 APK 只供分析，不可安装。

联网参考通过指定的 `http://192.168.5.7:6152` 代理获取，原文已保存在证据目录：

- [Android dumpsys 内存说明](https://developer.android.com/tools/dumpsys#meminfo)：PSS/RSS 和内存分类。
- [Android 内存管理说明](https://developer.android.com/topic/performance/memory-management)：共享内存与回收。
- [Linux /proc 文档](https://docs.kernel.org/filesystems/proc.html)：MemAvailable 等字段的含义。
- [AOSP Android 16 MemInfoReader](https://android.googlesource.com/platform/frameworks/base/+/.work/refs/heads/android16-release/core/java/com/android/internal/util/MemInfoReader.java)：内核/缓存汇总公式。
- [AOSP Android 16 ActivityManagerService](https://android.googlesource.com/platform/frameworks/base/+/.work/refs/heads/android16-release/services/core/java/com/android/server/am/ActivityManagerService.java)：Used RAM、DMA-BUF/GPU 修正和 Lost RAM。
- [AOSP Android 16 RunningProcessesView](https://android.googlesource.com/platform/packages/apps/Settings/+/.work/refs/heads/android16-release/src/com/android/settings/applications/RunningProcessesView.java)：开发者选项中运行服务的显示口径；原厂页面可能另有定制。

## 后续操作：卸载智享家

同日按用户明确指令，对唯一的机主用户（user 0）执行：

```sh
pm uninstall --user 0 com.lenovo.octopus
```

返回 `Success`。随后验证：`pm list packages --user 0 com.lenovo.octopus` 无匹配项，`dumpsys package` 报告找不到该包，`dumpsys meminfo` 报告无对应进程，进程列表也无该包或其子进程。没有为此重启手机或停止 Docker/LXC。

这是当前设备上的应用卸载。原厂只读镜像中的 `/product/preinstall/LenovoSmartHome/` 及现有 v3 一键包尚未重建；未来制作新版精简镜像时应将这个目录加入移除清单。不能把本轮操作当作已从固件镜像物理删除。

证据：`.work/refs/memory-audit-20260922/octopus-before-uninstall.txt`、`octopus-uninstall.txt`、`octopus-after-uninstall.txt`。未把卸载前约 134 MiB PSS 宣称为卸载后恒定的净 RAM 节省量。
