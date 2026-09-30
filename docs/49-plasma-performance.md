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

## Flatpak 应用的 GPU（2026-09-28，rungic-flatpak-gl）

用户反馈 Telegram（Flatpak `org.telegram.desktop`，Qt 6，GNOME 50 运行时，即 Freedesktop 25.08）滑动时掉帧明显。

### 原因：Flatpak 里没有 KGSL 驱动，应用在 CPU 上渲染

- Flatpak 应用不使用系统的 Mesa，而是使用运行时的 GL 扩展 `org.freedesktop.Platform.GL.default`。那份 Mesa 没有 KGSL 后端，于是退回 llvmpipe，用 CPU 渲染。Telegram 日志里的 RHI 探测结果就是 llvmpipe。
- 滑动时 Telegram 占约 196% 的 CPU（两个大核），超过 12 ms 的帧间隔约 42%，10 秒只出 377 帧。
- 不能直接把系统 Mesa 挂进沙箱：系统 Mesa 链接 Ubuntu 26.04 的 glibc 2.43，而运行时只有 glibc 2.42。

### 做法：本项目的 Mesa 作为运行时的 GL 扩展

[Flatpak 的 GL 扩展机制](https://docs.flatpak.org/en/latest/extension.html)规定：运行时的 `[Extension org.freedesktop.Platform.GL]` 声明了 `directory=lib/aarch64-linux-gnu/GL`、`subdirectories=true` 和 `enable-if=active-gl-driver`。`FLATPAK_GL_DRIVERS` 里列出的名字就是启用的子目录。扩展可以不经 OSTree，直接放在 `/var/lib/flatpak/extension/<id>/<arch>/<branch>/`（即 unmaintained 扩展，已在 flatpak 1.16.6 上核对）。

同一做法的先例：
- [mponcet/org.freedesktop.Platform.GL](https://github.com/mponcet/org.freedesktop.Platform.GL) 用于其他 GPU 的自建扩展；
- 本项目 Mesa 的上游 [lfdevs/mesa-for-android-container](https://github.com/lfdevs/mesa-for-android-container) 提供 KGSL 后端。

实现：
- 包 `rungic-flatpak-gl`（`plasma/packaging/rungic-flatpak-gl/`）：
  - 用系统 Mesa 的同一份补丁源码（`packages/mesa`）和同一组 meson 选项（`plasma/mesa-meson-options`），另外加上 softpipe。
  - 在 Freedesktop SDK 的容器镜像 [`freedesktopsdk/sdk:25.08-aarch64`](https://hub.docker.com/r/freedesktopsdk/sdk) 里构建，因为扩展必须链接运行时的库。这个镜像由 Mac mini 上的 Docker 运行：`rungic_package.py` 的 `image` 字段让 `build.sh` 在构建容器旁边的另一个镜像里运行，两者共用构建卷。
  - 安装到 `/var/lib/flatpak/extension/org.freedesktop.Platform.GL.rungic/aarch64/25.08/`：
    - EGL 供应商文件 `glvnd/egl_vendor.d/10_rungic.json` 和 Vulkan ICD 都写成扩展内的绝对路径；
    - 运行时的 `merge-dirs` 会把它们合并进 glvnd 和 Vulkan loader 的搜索目录。
- `/etc/plasma/gpu-env`：只有这个扩展存在时才设置 `FLATPAK_GL_DRIVERS=rungic`。会话把它导入用户 systemd 管理器，并写进 `rungic-session.env`，所以从 Plasma 启动的 Flatpak 应用都会用上它。
- 软件兜底：设置 `FLATPAK_GL_DRIVERS=rungic` 后只挂载这一个 GL 扩展。拿不到 `/dev/kgsl-3d0` 的应用会退到扩展里的 softpipe，不至于没有 GL。
  - 只有带 `--device=all` 权限的应用能拿到 KGSL。flatpak 1.16.6 的 `--device=dri` 设备列表（`common/flatpak-run.c` 的 `dri_devices`）里没有 `/dev/kgsl-3d0`。
  - 这类应用原来用 GL.default 的 llvmpipe，现在只有更慢的 softpipe。目前装的 Telegram 和 VS Code 都是 `devices=all`。
  - 若以后出现只有 `--device=dri` 的应用，应当在 flatpak 的设备列表里加入 KGSL，而不是逐个应用放宽权限。

### 验收

用试构建包 `rungic-flatpak-gl` 0.302 的文件验证（尚未进入发布）：
- Telegram（GNOME 50 运行时）日志：`RHI: Probe backend=OpenGL device=freedreno FD710 4.6 (Core Profile) Mesa 26.3.0-devel`。
- 以 `--nodevice=all --device=dri` 启动，也就是拿不到 KGSL 时：`device=Mesa softpipe 3.3`。兜底有效。
- VS Code（`org.freedesktop.Sdk` 25.08 运行时，Electron）：GPU 进程映射了扩展中的 `libEGL_mesa`、`libgallium`、`libgbm`，并持有 3 个 `/dev/kgsl-3d0` 描述符，窗口正常绘制。

同一聊天列表滑动 8 次、采样 10 秒，Telegram 在前台：

| | Telegram CPU | 超过 12 ms 的帧间隔 | 帧数 |
|---|---|---|---|
| GL.default（llvmpipe） | 约 196% | 42% | 377 |
| rungic（FD710） | 34–59% | 26–39%（多轮） | 约 300–550 |

剩余的开销主要在 Telegram 主线程，占大核 24–42%。Telegram 的界面用 Qt Widgets 在 CPU 上光栅化，再交给 GL 合成。它的动画节拍是 8 ms（lib_ui `universalDuration: 120`），并不限制在 60 Hz。这部分属于应用自身，没有再改。

### `--device=dri` 与 KGSL，没有 GPU 时的兜底（2026-09-30）

起因：助理装的 Flathub Krita 5.3.3 只有 `--device=dri`。

- **沙盒里没有 GPU**：容器没有 `/dev/dri`，所以 `--device=dri` 什么都不给。
- **兜底反而崩溃**：Krita 一启动就段错误（139），助理于是给它加了 `LIBGL_ALWAYS_SOFTWARE=1`，画布从此一直用 softpipe。

原因（实测加源码）：
- **崩溃**：
  - core 显示崩在扩展 `libgallium` 的 `drisw_init_screen+0x38`：`screen->swrast_loader` 为空。
  - 来源是 lfdevs 分支从 termux-packages 引入的改动（`b355d4d41a86`）：`dri3_x11_connect()` 在拿不到 DRI3 设备时也返回成功。这是为了让 zink 继续走 kopper，但其他驱动因此带着 DRI3 的加载接口创建了软件屏幕。
  - 上游 Mesa 在这里返回失败，之后由 `eglInitialize` 改用软件渲染重试。
- **卡住**：给了 `/dev/kgsl-3d0` 之后，X11 GL 程序又会一直卡住。分支的 `x11_dri3_open()` 在环境变量为 `kgsl` 时自己打开 KGSL，却不先检查 X 服务器有没有 DRI3；缓冲随后仍要经 DRI3 请求交给服务器，于是客户端一直等。本机工作区的 Xwayland 没有 DRI3，见 research/93。

修改：
- `packages/flatpak`（新补丁队列，Ubuntu 1.16.6-1，`rungic/dri-kgsl-dma-heap.patch`）：`--device=dri` 在节点存在时也绑定 `/dev/kgsl-3d0` 和 `/dev/dma_heap/system`。只带 system 堆，Android 的其他堆（安全堆等）仍在沙盒外。
- `packages/mesa`：
  - `egl-x11-dri3-fallback-software.patch`：只有 zink 在没有 DRI3 设备时继续，其他驱动照上游返回失败，退到软件渲染。
  - `x11-kgsl-needs-dri3.patch`：先确认服务器有 DRI3，才本地打开 KGSL。
- 以上 Mesa 补丁已进入 Flatpak GL 扩展 `rungic-flatpak-gl` 0.399。系统 Mesa 尚未重建：X11 程序在容器里直接运行时仍走原来的路径。

验收（实机，2026-09-30）：
- 补丁版 flatpak 1.16.6-1+rungic1 下，Krita 沙盒里能看到 `/dev/kgsl-3d0` 和 `/dev/dma_heap/system`。
- Flatpak Krita 5.3.3，去掉 `LIBGL_ALWAYS_SOFTWARE`：
  - `--device=dri` 和 `--nodevice=dri` 两种情况下，`krita --version` 都正常退出（exit 0），没有崩溃，也没有卡住，都退到 softpipe。
  - 修改前分别是崩溃（139）和卡住（超过 2 分钟，主线程在等 X 服务器的回复）。
- 走原生 Wayland 的 Flatpak 应用（Telegram、VS Code）走 EGL Wayland 路径，本次修改不涉及，这次没有重测。
- 只走 X11 的 Flatpak 应用要真正用上 GPU，还要等 Xwayland 有 DRI3（research/93）。

### Qt Flatpak 应用始终开着无障碍（未修改）

- Telegram 顶部一直显示 “Telegram is working in Screen Reader”。
- 原因：flatpak 给沙箱设置 `AT_SPI_BUS_ADDRESS=unix:path=/run/flatpak/at-spi-bus`。Qt 只要看到这个变量，就无条件开启 AT-SPI 桥（qtbase `QAtSpiDBusConnection` 构造函数），不看 `org.a11y.Status IsEnabled` 的值（本机为 false）。Telegram 用 `QAccessible::isActive()` 判断读屏器，所以一直提示。上游认为这是预期行为：[tdesktop#30511](https://github.com/telegramdesktop/tdesktop/issues/30511)。
- 用 `flatpak run --no-a11y-bus` 启动 Telegram 后提示消失。滑动测量中 CPU 为 48% 和 34%，开着无障碍时为 48%，帧间隔没有明显差别。它不是掉帧的主因。
- 若要在共享层去掉，可以让 flatpak 在 `IsEnabled` 和 `ScreenReaderEnabled` 都为 false 时不接无障碍总线。代价是：这些应用在无障碍关闭时启动，之后 rungic-cua 打开无障碍也无法自动化它们。尚未决定。
- 单个应用可在 Telegram 设置 → 高级里关闭读屏模式。
