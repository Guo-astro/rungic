# G100 当前内存占用审计

2026-09-27 20:04–20:08 CST，只读实机采样。设备为 moto G100 **XT2533-4 / `portov_cn`**，Android 16 `W1VT36H.1-51-8`，原厂内核 `6.6.87-android15-8-g86c6642d582e-ab14676406-4k`；不是先前 [21 篇](21-memory-audit.md)中的 G100 S `mumba_cn`。通过已授权 ADB shell 读取两次 `dumpsys meminfo`、`/proc/meminfo`、`dumpsys pinner`、`/proc/slabinfo`、重点进程及服务。未杀进程、清缓存、卸载应用或更改设备配置。原始输出在 `.work/g100/memory-audit-20260927/`。

采样时开机约 1 小时 27 分，设置和其他应用曾运行；不是清空数据后的冷启动基线。ADB shell 无 root，`/proc/pressure/memory`、`/proc/vmallocinfo`、zram 细项和 DMA-BUF 逐缓冲列表没有读取权限。两次采样间 `system_server` PSS 有约 44 MiB 波动，下面使用区间而非伪精确的单一数值。

## 总账

| 项目 | 两次采样 | 解释 |
| --- | ---: | --- |
| 内核可见总量 | 11.19 GiB | `MemTotal=11,727,552 KiB`；与标称 12 GB 的十进制/二进制换算相符 |
| Android `Used RAM` | 3.46–3.52 GiB | 非缓存进程 PSS 2.51–2.57 GiB，加 Android 口径的内核约 0.94–0.95 GiB；不可再加下面的各项 |
| 缓存进程 PSS | 0.77 GiB | Android 能在压力下结束这些进程；不是持续运行成本 |
| Android 缓存内核口径 | 2.60–2.79 GiB | 主要含文件缓存和可回收池；与下述 `Cached`、DMA 池等交叠 |
| 纯空闲页 `MemFree` | 4.06–4.33 GiB | 不含可回收缓存 |
| `MemAvailable` | 7.90–7.97 GiB | 内核估算新负载可使用的内存，含可回收页；与 Android `Free RAM` 7.62–7.69 GiB 口径不同 |
| 文件/共享页缓存 `Cached` | 3.74–3.93 GiB | 已计入内核页统计，可在需要时回收相当一部分 |

此时 Android 报 `status normal`，zram 只有约 **51 MiB 物理内存**在保存约 144–146 MiB 的交换内容；8.39 GiB 是 zram 的逻辑容量，不是实际 RAM 占用。没有足够证据称当前发生内存压力。当前未发现 Rungic、Magisk、LXC、Docker 或 Plasma 进程，因此这份账是 Android 原厂用户空间的当前负担，尚不含未来 RungicOS。

## 谁在占进程内存

以下为第一次采样的 **PSS**（MiB），把共享页按进程分摊；不要使用 RSS 相加。两次采样的主要排名稳定。

| 进程/功能 | PSS | 状态与证据 |
| --- | ---: | --- |
| `system_server`（`system`） | 285.5，第二次 329.9 | Android 系统框架；包含厂商扩展，不能从进程名分出每个服务的成本 |
| SystemUI | 277.0 | 通知、状态栏、锁屏等 |
| `com.motorola.myscreen` | 155.4 | 前台；`MyScreenService` 被原厂 Launcher 绑定 |
| `com.lenovo.octopus`（智享家） | 132.5 | **Cached**；详细 meminfo 中约 104 MiB PSS 为 Code，不能当成 132.5 MiB 永久常驻 |
| SurfaceFlinger | 131.6 | Android 显示合成；其图形缓冲与下述 GPU/DMA 报告不能重复相加 |
| 高通 Camera Provider | 109.6 | 原厂摄像头服务 |
| 搜狗 Moto 输入法 | 109.1 | Perceptible，当前输入服务 |
| Android 设置 | 89.9 | B Services；采样前使用过设置 |
| 原厂 Launcher | 79.5 | 前台；另有应用预测进程约 8.4 MiB |
| `com.motorola.deviceguard` | 67.4 | Persistent；同时提供 MyScreen 插件、电池与屏幕时间服务，受系统绑定 |
| Moto Mobile Desktop | 66.6 | Perceptible Low，另有 core 约 9 MiB |

268–270 个可见进程合计约 3.33–3.39 GiB PSS，这包括缓存进程。按包名前缀计算，Motorola、Lenovo、ZUI 共 **76 个进程、约 1.46 GiB PSS**，其中 **约 0.62 GiB 为 Cached，约 0.84 GiB 非缓存**；Moto 输入法另约 109 MiB。前缀统计包含必需和可选服务，不能直接解释为可删除量。`system_server` 中厂商代码、Qualcomm HAL、图形缓冲和内核开销不在这个前缀统计里。

## 内核、图形、固定页

| 指标 | 实测 | 解读 |
| --- | ---: | --- |
| `SUnreclaim` | 366–367 MiB | 不可回收 Slab；`Slab` 总数约 535–541 MiB，含可回收部分 |
| 页表 | 143–144 MiB | 进程地址空间管理开销 |
| 内核栈 | 72 MiB | 已在内核总量中，不单独加到 Used RAM |
| DMA-BUF | 188 MiB | 其中约 116 MiB 未映射到进程；设备共享缓冲 |
| GPU | 226 MiB | 主要为 DMA-BUF 口径，与上项交叠 |
| DMA-BUF heap pool | 811 MiB | 池/缓存口径，不能当成 811 MiB 额外常驻应用内存 |
| Pinner 实际固定 | 124 MiB | Launcher 14.5、WebView 20、系统文件 89.7 MiB；总配额约 1,145 MiB 不是实际占用 |
| `Lost RAM` | 233–242 MiB | Android 统计残差，不足以归因某个应用或断言泄漏 |

`/proc/slabinfo` 中较大的对象为 `vm_area_struct` 约 74 MiB、`erofs_pcluster-1` 约 53 MiB、`inode_cache` 约 32 MiB、`vma_lock` 约 24 MiB、`task_struct` 约 21 MiB；这些是 Slab 的内部构成，不能再加一遍。内核相关占用会随进程数、文件映射和 EROFS 使用变化；没有 root 级 vmalloc/DMA 明细，暂不进一步指定“是谁分配了全部内核内存”。

## 结论与后续核验

当前这台 G100 的主要非缓存成本来自 **Android 框架/SystemUI、原厂桌面与其绑定服务、显示和摄像头服务、输入法，以及约 0.95 GiB 的内核口径**。同时有约 0.77 GiB 缓存应用和数 GiB 文件/缓冲池缓存，系统仍有约 7.9 GiB `MemAvailable`。把 OEM 进程 PSS、GPU、DMA-BUF pool、Slab、Pinner 或 zram 容量全部相加会严重重复计算。

若后续目标是减少 RungicOS 底座的常驻成本，应先建立相同开机/解锁/等待条件的基线，再逐组研究原厂桌面/MyScreen、桌面互联、输入法和可选厂商服务的依赖，调整后用相同口径重测。`deviceguard` 与系统、MyScreen 有明确绑定；本次审计不是删除清单。刷入自编 GKI 或完整 RungicOS 后，还需要单独建立新基线，不能把原厂 Android 的这些数值当作新系统的实测结果。

计量口径参考：[Android `dumpsys meminfo` 与 PSS](https://developer.android.com/tools/dumpsys#meminfo)、[Linux `/proc/meminfo` 与 `MemAvailable`](https://docs.kernel.org/filesystems/proc.html)、[Android 图形缓冲架构](https://source.android.com/docs/core/graphics/architecture)。

## 可关闭项目的初步分级（尚未在实机停用验收）

这里的“正常运行”指保留开机、解锁、通话、短信、联网、通知、原厂桌面、相机、基础设置和文字输入。停用附加应用仍会失去该应用的功能；以下只是依据本机 `dumpsys package`、`dumpsys activity services`、当前输入法和内存状态作出的候选分类，**不是已验证的安全停用清单**。

| 类别 | 包名 | 本次 PSS / 进程状态 | 关闭后的明确代价与判断 |
| --- | --- | --- | --- |
| 首轮候选 | `com.lenovo.octopus`（智享家） | 132.5 MiB，Cached | 失去智享家及其设备/小组件功能。当前服务仅见自身绑定；因属缓存，不能预期释放同量常驻内存。 |
| 首轮候选 | `com.lenovo.leos.appstore` | 32.5 MiB，Cached | 失去联想应用商店及其应用更新入口；Android 安装器本身仍是另一组件。 |
| 首轮候选 | `com.motorola.help` | 35.3 MiB，Cached | 失去原厂帮助/说明入口。 |
| 视使用情况 | `com.motorola.personalize` | 39.7 MiB，Cached | 失去原厂个性化/主题设置入口；当前没见活跃绑定，但需验收桌面外观和设置页。 |
| 视使用情况 | `com.motorola.cn.gallery` | 38.0 MiB，Cached | 失去原厂图库；如有替代图库，再核验相机拍摄、预览与分享。 |
| 视使用情况 | `com.motorola.timeweatherwidget` | 29.4 MiB，Visible | 失去原厂时钟/天气桌面小组件及 MyScreen 天气插件；服务被 `com.motorola.process.system`、MyScreen 绑定。 |
| 视使用情况 | `com.motorola.gamemode` | 27.8 MiB，Perceptible Low | 失去 Moto 游戏模式、游戏悬浮工具；服务被 `com.motorola.process.system` 绑定。可先在功能设置中关闭游戏工具。 |
| 视使用情况 | `com.motorola.mobiledesktop`、`com.motorola.mobiledesktop.core` | 66.6 + 9.0 MiB，Perceptible Low | 失去 Smart Connect/Ready For 的电脑、外屏、投屏或跨设备功能；`.core` 被厂商系统服务绑定，应成组测试。 |
| 视使用情况 | `com.motorola.cn.wallet` | 24.0 MiB，Visible | 失去 Moto 钱包、公交卡/NFC 支付；NFC 服务正绑定其卡模拟服务。不能仅凭包名推断基础 NFC 是否完全不受影响。 |
| 暂不碰 | `com.motorola.myscreen`、`com.motorola.deviceguard` | 155.4 + 67.4 MiB，Foreground/Persistent | 前者被原厂 Launcher 绑定；后者由系统屏幕时间、厂商电池服务和 MyScreen 使用。删除会触及原厂桌面/管理链路，需先替换或拆解依赖。 |
| 暂不碰 | `com.sohu.inputmethod.sogou.moto` | 109.1 MiB，Perceptible | 当前默认输入法；虽然另装有 `com.android.inputmethod.latin`，在完成中文输入验收并切换默认输入法前不能关闭。 |

前三项是**对 Android 核心运行风险较低的首轮候选**，但其占用均为可回收缓存，不应承诺可降低 200 MiB 常驻内存。其余活跃功能有明确绑定或用户功能损失，需要按一组一个包（桌面互联两包为一组）停用、重启、复测通话/数据/Wi-Fi/通知/相机/桌面，并对照同条件 `dumpsys meminfo`；任一异常立即恢复。尚未执行这些停用和复测，因此这里不把“推测可关”写成“已验证可关”。

功能边界参考：[Motorola Smart Connect 功能](https://help.motorola.com/hc/apps/smartconnect/sc90/en-us/T0478368505.html)、[Motorola Moto Gametime](https://help.motorola.com/hc/3232/11/global/en-us/CGT2002244032.html)。本机绑定关系、安装位置和启用状态原始输出在 `.work/g100/memory-audit-20260927/all-services.txt`、`package-detail/`，这些是此机型当前固件的证据；官方网页只帮助确认对应附加功能，并未验证本机停用后的行为。

## 小天语音智能体：2026-09-27 首轮停用

用户明确表示不用 G100 的 AI 智能体。20:17–20:21 CST 重新连接 XT2533-4，采集完整包、进程、服务、默认助手状态到 `.work/g100/ai-pruning-20260927/`。停用前 `assistant` 与 `voice_interaction_service` 都指向 `com.lenovo.menu_assistant/.msgreport.LeVoiceInteractionService`；该服务由 Android 系统绑定。`com.lenovo.levoice_agent` 是 Persistent 包；`com.lenovo.xiaotian.trigger` 未运行进程。三包用途对应[联想小天语音唤醒设置](https://iknow.lenovo.com.cn/detail/437345)，但此处的具体包映射来自本机包与服务信息，而非官方网页。

已通过 `pm disable-user --user 0` 停用 `com.lenovo.menu_assistant`、`com.lenovo.levoice_agent`、`com.lenovo.xiaotian.trigger`，**没有卸载或清除数据**。Android 自动清空了默认助手与语音交互服务设置，默认搜狗输入法未变化。随后确认原厂 Launcher、SystemUI、电话进程仍运行，Wi-Fi 设置仍启用，SIM 状态为 `LOADED,ABSENT`，HOME、拨号、相机和短信 Intent 仍能解析。尚未实际拨号、拍照、收发短信或重启，因此这些检查不构成完整功能验收。

停用前语音入口两个进程 PSS 为 35.4 MiB（Cached）和 12.1 MiB（活跃）；停用后均不在进程表。`levoice_agent` 仍以原 PID 存活，执行 `am force-stop` 后也未退出，预计需要重启才能核验其最终状态；其采样 PSS 仅 5.5 MiB。全机 `Used RAM` 采样反而从约 3.52 GiB 波动至 3.60 GiB，**不能宣称本轮净节省 47 MiB 或更多**。

`com.motorola.aicore`、`com.motorola.motointelligence`、`com.lenovo.xiaotian.trigger` 在停用前都没有独立运行进程；`com.motorola.cn.searchintelligence` 是约 16 MiB 的 Cached 进程。这些包即使停用也没有可证实的当前常驻收益。`com.motorola.aiservices` 两个活跃进程合计约 42 MiB PSS，`MayaManagerService` 被厂商系统服务绑定，另有语义位置、睡眠模式和上下文引擎服务；[Motorola 官方说明](https://help.motorola.com/hc/apps/privacy/product/en-us/)还将优化充电、自适应亮度列为 Moto AI Services 所支持的能力。因此未将 AI Core、AI Services 或名称带 Smart 的桌面/无障碍服务一并停用。

如需恢复首轮三包：依次执行 `pm enable --user 0 com.lenovo.menu_assistant`、`pm enable --user 0 com.lenovo.levoice_agent`、`pm enable --user 0 com.lenovo.xiaotian.trigger`，并把 `settings put secure assistant` 与 `settings put secure voice_interaction_service` 的值都设回 `com.lenovo.menu_assistant/.msgreport.LeVoiceInteractionService`。原始设置值保存在 `.work/g100/ai-pruning-20260927/before-disable.json`。
