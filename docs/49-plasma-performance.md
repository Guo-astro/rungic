# Plasma 动画、列表帧率与 Android 调度

2026-09-23，用户报告应用开启动画和滚动列表明显掉帧，并要求核查 Moto 的性能白名单。已部署APK1.7并完成第一轮同机对照，开启动画和滑动的长帧减少。本文区分已验证显示修正、调度实验和仍待定位的瓶颈；媒体任务的待办另见48篇。

## 已确认事实

- MotoPerfManagerService 把 `dev.moto.plasma`（UID10352）识别为 `TOP100 adj0 active bkt_active hasUI`；APK的CPU/cpuset组均为top-app，不能宣称APK被当作后台应用。
- LXC中KWin、plasmashell属于 `lxc.payload.plasma/user.slice/...`，在Android v1 CPU/cpuset控制器中仍为根组。允许使用CPU0–7，未发现只准用小核的限制。
- 本机CPU top-app竞争权重5120，根组1024；这是资源竞争时的相对权重，不代表速度或频率相差5倍。
- 采样时Android热状态为0，尚无证据把卡顿归因于温控。
- 旧版宿主DisplayPacer触摸请求最高120Hz，触摸后2秒降至活动60Hz，静止时释放请求，系统可能降到30Hz。1.7默认改为前台流畅优先；静止30Hz本身不是掉帧证据。
- 现有KWin→Android AHardwareBuffer协议还用glFinish保证GPU完成，没有跨进程显式fence；这也是候选瓶颈，不得直接删除同步造成画面竞争。

## 调研与复用入口

- [AOSP task profiles](https://source.android.com/docs/core/perf/cgroups)：平台用任务配置管理CPU组、cpuset等。设备已有 `/system/bin/settaskprofile`，可复用本机定义，而非为每个Linux应用编造厂商白名单。
- 本机 `/system/etc/task_profiles.json` 定义MaxPerformance→CPU top-app、ProcessCapacityMax→cpuset top-app；`/vendor/etc/task_profiles.json`另有Moto MDPF规则。配置副本及MotoPerf只读转储在 `.work/refs/plasma-performance-20260923/`。
- `/vendor/etc/perf/perfboostsconfig.xml`有应用启动、滚动、触摸加速配置。尚未证明这些配置存在适用于我们宿主的必要包名白名单，也未修改厂商配置。

## 对照方法与调度边界

同一手势/应用、无编译/录屏负载下采集SurfaceFlinger实际呈现时间，分别比较原配置、前台调度继承、稳定刷新率请求。临时调度实验只涉及KWin/plasmashell对应任务，随后恢复原组。没有把容器服务、编译、Docker等后台任务提升到top-app。若以后接入前台调度，应随Android前后台切换，保留温控与后台节能，且只作用于独立Plasma桌面进程，保留原cgroup以便退出恢复。


## 显示修正与第一轮对照

[Android帧率接口官方说明](https://developer.android.com/media/optimize/performance/frame-rate)明确提示频繁改变帧率请求可能在切换期间掉帧，且请求不保证被系统满足。通常优先Surface.setFrameRate；本机因Surface单独请求仍与90Hz类别竞争，额外匹配同物理分辨率的Window mode。没有更改显示分辨率。

`DisplayPacer.java`先前对每个Android display changed事件（包括刷新率没变的事件）都发送NativeBridge.setRefreshRate；原生层也无条件重新发布Wayland output mode。新Java层按实际刷新率去重，原生层另加相同mode不重复发布的保护。`plasma/adapt-native-presentation.py`保留了原生修复的可重建入口。

APK1.7/versionCode8新增菜单“显示流畅度”：默认流畅优先，在前台同时给SurfaceView和Activity请求同分辨率下的最高刷新率；自动模式保留原节能策略，离开/销毁Surface时释放请求。使用Android公开Window/Surface接口，未修改全局刷新率、温控或厂商白名单。

`tools/profile_plasma_frames.py`采集SurfaceFlinger呈现时间；固定8次滑动，或4次计算器启动/关闭。暂停也计入原始数据，不能用平均FPS掩盖长帧。新版本第一轮在桌面尚未准备好时的样本`display17-scroll.json`不作为有效对照，使用带实际抽屉界面确认的`display17-scroll-valid.json`。

| 场景 | 普通调度/旧显示策略 | 只把KWin/桌面临时移到top-app | 普通调度/新显示策略 |
|---|---:|---:|---:|
| 滑动P95帧间隔 | 11.19ms | 11.14ms | 8.78ms |
| 启动/关闭P95帧间隔 | 33.42ms | 22.39ms | 16.82ms |

这是一轮同机、无录屏/编译负载的对照，存在缓存/测试次序影响，不是全面性能基准。新显示策略下Android持续报告120Hz。所有数字只代表宿主Surface的实际呈现，不证明每个Linux客户端每帧都绘制了新内容。临时top-app配置已恢复，后续重开会话也恢复默认调度；尚未部署常驻调度代理。剩余大帧与复杂应用仍需跟踪CPU/GPU渲染、显式fence和冷启动路径。

## 最终版本生命周期复核

最终APK包含Java与原生两级刷新率去重，并在Activity.onStop清除Surface/View/Window请求；即使Surface已经销毁也会清除Window mode。onStart/Surface重建恢复请求。1.7最后一次构建哈希见 `.work/refs/plasma-performance-20260923/APK-SHA256SUMS`。

实际菜单切换“自动”后requested-hz=0；切回“流畅优先”，退到Android再返回后requested/actual均恢复120Hz，KScreen亦报告720×1600@120。后台Window不可见、无Surface、无preferred mode，帧计数采样停止。后台的android-refresh.ini保留最后一次前台样本，读取时需看sampled-uptime-ms，不能把旧的120Hz当作后台持续申请。证据：adaptive-idle.txt、lifecycle.json、background-window.txt、kscreen-final.txt、smoothness-menu.xml。

帧率请求仍服从Android显示调度；例如相机启动期间观察到短时实际60Hz、请求120Hz。流畅优先增加显示功耗，不绕过温控；可在左侧边缘菜单→显示流畅度切换自动。

后续APK1.8已改为原生1080×2400输出。本篇APK1.7的720×1600结果不能直接用于原生分辨率的性能判断；新的多轮GLES/Zink和原生Vulkan对照见[51篇](51-plasma-vulkan-benchmark.md)。

## 大核调度与空闲开销（2026-09-28，APK 2.9）

用户要求检查我们的系统是否始终在大核上运行，以及 CPU 开销是否足够低。测量方法、原始追踪和脚本在 `.work/diag/cpu-placement/`（`analyze.py`、`ours.py`、`experiment.py`、`results.md`）；追踪用 `tools/rungic_trace.py` 抓取，含 sched_switch 和 cpu_frequency。

### 现状

- SM6435：cpu0–3 为 Cortex-A55（1.8 GHz，容量 405），cpu4–7 为 Cortex-A78（2.4 GHz，容量 1024）。
- APK 在前台时属于 top-app（0–7），在后台时属于 foreground（0–6）；SurfaceFlinger 固定在 4–6 号核，uclamp.min 10。
- KWin、plasmashell 和整个容器都在 cpu/cpuset 的根组里，允许 0–7，uclamp 为 0。放置完全交给 EAS，所以它们几乎只在小核上运行：滑动开关应用抽屉时，plasmashell 96%、KWin 92% 的时间在小核上。

### 放到大核的对照（每种两轮，8 次滑动，统计超过 12 ms 的帧间隔）

| 设置 | 掉帧比例 | plasmashell / KWin CPU |
|---|---|---|
| 现状 | 10–14% | 21% / 12% |
| taskset 固定到 4–7 | 7–8% | 13% / 9% |
| uclamp.min 512 | 8–9% | 12% / 7% |

放到大核后掉帧大约减半，而且因为大核更快，CPU 时间反而更少。uclamp.min 512 高于小核容量 405，EAS 会把任务放到大核上。

### 采用的做法：前台提升，不常驻大核

- 如果始终放在大核，空闲和后台时的轮询也会跑到大核上，耗电更多。所以改为照 Android 对 top-app 的处理：只在 Plasma 位于前台时提升。
- `rungic-plasma boost on|off`：把桌面会话（uid 1000 的 systemd 用户管理器，以及它派生的全部进程）收进 Android v1 的 `/dev/cpuctl/rungic-desktop` 组。前台时 `cpu.uclamp.min` 50%、`cpu.shares` 5120；后台时恢复 0 和 1024。
  - 新进程继承父进程的组，所以只在用户管理器是新进程时扫描一次 /proc。
  - 容器里的系统服务和编译任务不收进这个组（沿用本篇前面定下的边界）。
- APK 在 `onStart`/`onStop` 时，经已有的常驻 root shell 调用它（`PlatformBridge.desktopBoost`），不会每次新开 `su`，也就没有 Magisk 的授权提示。
- 验收：前台时 KWin 和 plasmashell 的有效 uclamp.min 为 512，约 100% 的时间在大核上；回到 Android 桌面后为 0。滑动两轮掉帧比例为 7.2% 和 5.1%。

### 空闲开销：从约 30% 降到 2.6%（前台）和 4.0%（后台）

改动前，Plasma 在前台和后台空闲时，我们的进程合计都约占 30% 单核：

| 来源 | 占用 | 原因与改法 |
|---|---|---|
| `rungic-media-bridge` | 约 17%（含每秒约 7 个短命 `pactl`、PulseAudio 和媒体桥本身） | 主循环每 0.6 秒执行 5 次 `pactl`。它的 `pactl subscribe` 在中文环境下输出“事件…于 source”，英文匹配从未生效。改为 `LC_ALL=C` 订阅，只在 source/sink/server 事件时查询，另每 30 秒兜底一次 |
| 由上一项带动 | plasmashell 和 kded6 各被唤醒约 37 次/秒 | 每个 `pactl` 客户端的连接和断开，都会通知所有 PulseAudio 订阅者；修好上一项后 plasmashell 降到约 4 次/秒 |
| 助理屏磁贴 | 1.4% | 每 4 秒启动一次 Python。改为控制中心打开时每 2 秒、助理屏开着时每 15 秒各执行一次，屏幕数量变化时也立即执行 |
| 平台桥上的轮询 | 合计约 5% | 网络状态每 2 秒、蓝牙和蜂窝每 5 秒、剪贴板每 1 秒、媒体桥 `capture-info` 每 1 秒（每次都要列举相机），APK 每 5 秒执行一次 root `cmd wifi status`，网络服务每 10 秒执行一次 `cmd wifi` 列表。改为平台桥上的长轮询 `watch`（见下） |

平台桥新增 `{"op":"watch","topics":[…],"epoch":…,"seen":{…},"timeout":ms}`：
- APK 的 `HostEvents` 为 network、telephony、bluetooth、capture、clipboard 五个主题各维护一个版本号，由 Android 自己的回调递增：
  - network：`NetworkCallback`（能力变化只在类型、验证、门户、计费或信号格数变化时计入）和 Wi-Fi 开关广播；
  - telephony：`TelephonyCallback`（服务、信号格数、数据连接、移动数据开关）；
  - bluetooth：适配器、连接、配对和扫描广播；
  - capture：前台状态和权限；
  - clipboard：剪贴板变化，以及重新获得焦点（Android 只允许有焦点的应用读剪贴板）。
- 请求在独立线程上等待，直到版本变化或超时（最长 60 秒）才返回；epoch 随 APK 每次启动改变。
- 容器一侧的共享模块 `rungic_host_watch`（`shared/platform/host_watch.py`）供网络、蓝牙、蜂窝、剪贴板服务和媒体桥使用：收到变化才取完整状态，每 60 秒兜底一次。遇到不支持 `watch` 的旧 APK，就退回各自原来的轮询间隔。
- 相应地，Wi-Fi 的 SSID 在网络出现、消失或链路属性变化时读取，另外每 60 秒兜底一次；不再要求 15 秒内刷新过，只要网络句柄一致就沿用。相机列表只列举一次。

验收：
- 功能：
  - 录音时接上 Android 麦克风，停止后断开；
  - 播放到手机扬声器时接上，挂起后断开；
  - Plasma 回到前台后相机源立即恢复；
  - Android 蓝牙开关后，容器里的 BlueZ 在约 2–6 秒内跟上（改动前是 5 秒一次的轮询）；
  - Android 剪贴板变化后约 200 ms 同步到 Linux；
  - 网络状态中的 SSID 和信号正常。
- 开销（本项目进程的单核占比）：前台空闲从 30.0% 降到 2.6%（其中约 0.7% 是 Docker）；后台稳态从 29.9% 降到 4.0%。小核负载从 17–20% 降到 9%。

### 同时修复

- **宿主暂停渲染时的触摸取消**：暂停时 `clear_input_state()` 只清空了宿主自己记录的触摸点，没有给客户端发 `wl_touch.cancel`，之后到达的抬起事件又因为渲染已暂停被丢弃。于是按着的触摸点在 KWin 里一直处于按下状态。现在暂停前，先给还未抬起的触摸点发取消。
- **语音助手按住 Home 的上限**：测量开始时，语音助手收到“按住 Home”（05:00:49）后再也没收到松开，于是持续录音、覆盖层持续动画；那段时间 KWin 占 50%、SurfaceFlinger 占 44%，语音相关进程约 48%。当时的宿主日志级别不够，无法确认具体丢在哪一步。现在按住超过 60 秒就当作松开事件丢失，关闭覆盖层并取消录音。
- **系统设置最小化后空转**：一度每秒被唤醒约 112 次，全是定时器唤醒（多半是最小化时没停的动画）；把它切到前台再最小化后消失，无法复现，没有针对它修改代码。
