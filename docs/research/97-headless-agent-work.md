# 97. 锁屏、息屏下的 Agent 工作（无头模式）调研

2026-10-02。用户要求：Agent（单个任务和团队）必须能在手机锁屏、息屏时继续工作。用户可能远程发起任务，只通过 RDP 等方式查看，不能强依赖 Android 解锁或 Rungic APK 在前台。远程观看用自有项目 RemoteSurface（`~/github/RemoteSurface`），不用 KRdp。

**标注**：
- 【实测】：本机实测；
- 【源码】：读过源码或反编译；
- 【文档】：其他文档或论坛的说法；
- 【推断】：未验证。

本轮调研没有改设备设置，只有两处例外：一是第 1 节的息屏实验；二是临时把 `com.rungic.plasma` 加进了 deviceidle 白名单，至今仍在，见第 6 节。

## 1. 现象（实测，G100 S / XT2537-4，中国版 ROM，Android 16）

触发点是 docs/research/91 §14 的第一次团队验收：art 成员报“受阻”。随后用 `KEYCODE_SLEEP` 息屏复现，手机平放：

| 时刻 | 屏幕 | deviceidle | APK 进程 | `platform.sock` |
|---|---|---|---|---|
| 亮屏 | Awake | ACTIVE | procState 2（顶层），未冻结 | 正常 |
| 息屏 20 s | Dozing | INACTIVE | procState 4（前台服务），未冻结 | 正常 |
| 息屏 90 s | Dozing | IDLE（深度） | procState 4，**`isFrozen=true`** | 无响应 |
| 唤醒后 | Awake | ACTIVE | procState 2，解冻 | 正常 |

- 用 root 执行 `dumpsys deviceidle whitelist +com.rungic.plasma` 后再测：90 s 和 180 s 时仍是冻结状态。
- 冻结期间容器照常运行：成员的 Codex 继续联网、发言。停下来的只是需要 APK 的部分。
- 本机属性：`ro.config.smart_freezer_enabled=true`、`ro.config.use_freezer=true`、`freezer_cutoff_adj=900`；待机分桶 10；RUN_ANY_IN_BACKGROUND 为默认允许。

## 2. 谁冻结了 APK：Motorola SmartFreezer（源码）

**来源**：
- AOSP `frameworks/base`：android-16.0.0_r1（99b01a65）和 r4（45034f06）；
- Motorola 固件公开 dump：`4mede/motorola_mumba_dump`，分支 `user-16-WWAAS36V.48-12-ST12.1-88187-release-keys`（b00538ad），用 jadx 1.5.6 反编译 `services.jar` 和 `framework.jar`。
- 注意：这个 dump 不是本机 `mumba_cn` 的固件，要用本机的 `/system/framework/services.jar` 复核（见第 7 节）。

**AOSP 本身不会冻结前台服务**：
- r1 和 r4 都只冻结 adj ≥ 900 的进程；
- 有前台服务的进程拿到 CPU_TIME 能力，不冻结；
- 冻结逻辑没有和 Doze 挂钩；
- `isFreezeExempt` 只来自 `freezer_exempt_inst_pkg` 加 `INSTALL_PACKAGES`，或 adj < 0 的持久化进程。

**冻结来自 Motorola**：
- `ro.config.smart_freezer_enabled` 是 Motorola 的属性（init.mmi.product.rc 注释为 `# moto_freezer`）。
- 实现在 `com.motorola.server.perf.proactive.freezer.SmartFreezer`、`UidStateController` 和 `com.android.server.am.MotoAMS`。
- 开关只在类初始化时读一次：先读 `persist.sys.smart_freezer_enabled`，没有再读 `ro.config.*`。
- SmartFreezer 开启后，AOSP 的 `CachedAppOptimizer.freezeAppAsyncInternalLSP()` 直接返回，所有冻结都由 Moto 执行（日志带 `reason = moto_freezer`）。`am freeze` 在这台机上不起作用。

**中国版 ROM 的判定规则**（`UidStateController.updateUidPerceptibleState()`，以 `ro.product.is_prc` 区分）：

| 条件 | 判定为“可感知”（不冻结）的条件 |
|---|---|
| 中国版，息屏或快速启动模式 | 仅 adj < 101 |
| 中国版，亮屏 | adj < 251 |
| 非中国版 | importance < 400 或 adj < 600 |

- Rungic 前台服务的 adj 是 200：息屏后被判为不可感知，可以冻结。国际版 ROM 上则不会冻结。
- 冻结延迟：中国版且 adj ≤ 250 时取 max(10 s, `smart_freezer_delay`)。失败后重试，重试间隔从 10 s 起翻倍，最长 600 s。
- Unix socket 的流量不会让被冻结的进程解冻（只有 binder 会），所以连接 `platform.sock` 先排队，排满后报 `EAGAIN`。

**SmartFreezer 放过一个 uid 的条件**：
- 进程 `isFreezeExempt`，或 adj < 0；
- 包名在 `EXEMPTED_APPS`，或在 `POWER_EXEMPTED_APPS` 里（= deviceidle 全量白名单 + Moto 中国版的 `getMotoFreezeExemptList()`）；
- uid 持有未被禁用的 PowerManager wakelock：推迟冻结；
- uid 拥有 VirtualDisplay：推迟冻结。

**刚才加白名单为什么无效**：`POWER_EXEMPTED_APPS` 只在开机完成时，以及“设置”或 `com.motorola.deviceguard` 离开前台时刷新。shell 执行 `dumpsys deviceidle whitelist +` 不会触发刷新。

## 3. 网络、CPU 与其他系统（源码）

- **Doze 下的网络**：netd 的 `bpf_owner_match()` 对 `uid % 100000 < 10000` 的系统 uid 直接放行。
  - 容器里的 root（0）和用户（1000，特权容器、无 idmap）不受 Doze 限制，与实测相符；
  - 容器里的 `nobody`（65534），以及 rootless Docker 里 uid ≥ 10000 的部分，会被 Doze 阻断。
- **CPU 挂起**：本项目没有任何地方持有 wakelock（power-policy 明确不建，APK 里没有 `PARTIAL_WAKE_LOCK`）。
  - root 写 `/sys/power/wake_lock` 可以阻止整机自动挂起（GKI android15-6.6 开了 `CONFIG_PM_WAKELOCKS`）；
  - 但它没有 uid 归属，挡不住 Moto 冻结 APK。
- **cgroup 冻结**：root 直接写 `cgroup.freeze=0`，或把进程移到别的 cgroup，会让 AMS 的状态和 binder 冻结状态不一致，不采用。
- **同类项目**：
  - Termux：前台服务，加 `termux-wake-lock`（`PARTIAL_WAKE_LOCK` 加 WifiLock），并申请电池优化豁免；
  - Termux:X11：X server 不在 app 进程里，用 `app_process` 单独起，app 只负责显示；
  - Linux Deploy：提供“息屏保持 CPU”选项（持有 wakelock）；
  - AOSP 的 Linux Terminal（AVF）：只有 specialUse 前台服务，在 Pixel 上不被冻结，只是因为 AOSP 不冻结前台服务。

## 4. 本仓库的 Agent 路径对 APK 的依赖（源码）

APK 进程提供：`platform.sock`、`capture.sock`、`codec.sock`、`wayland-0`、`ws-N` 和 `rungic-gpu-alloc`。冻结早期，连接先排进 backlog（最多 50），客户端各自等到超时；排满后，带超时的客户端立即收到 `EAGAIN`，不带超时的阻塞式 `connect()` 永久阻塞。power-policy（每 2 s）、keeper、`host_watch` 都在轮询，几分钟内就会排满。

**会卡住 Agent 的**：
1. **在冻结期间启动工作区**：`kwin_wayland --android-host` 在宿主的第一次 Wayland 往返上无超时阻塞（60 s 的连接超时只覆盖 socket 不存在的情况）。之后在该工作区启动的应用也卡在第一次往返，KWin 的 D-Bus 名字不出现，桌面工具全部失败。团队验收中 art 的“受阻”就是这个原因。
2. **宿主被杀（不只是冻结）**：工作区 KWin 以 133 退出，unit 重启；应用的 scope 因为 `BindsTo` 一起被停掉，Agent 的应用和未保存的工作丢失。
3. **`codec-client.c`**：阻塞式 `connect` 没有超时，backlog 排满后永久阻塞。
4. **`rungic-cast`**：每条命令最多等 350 s。

**出错但 Agent 能继续的**：
- 每次桌面工具调用最多多等 3 s（`router.bridge`）；
- OCR 先等 20 s，再降级到 CPU；
- `user_watching()` 在连不上时返回 `{}`，`.get('foreground', True)` 会把用户当成“在看”，从而**压住团队的通知**（第 2 步代码的缺陷，要修）；
- 团队和 Agent 的系统通知只画在 Plasma 里，APK 冻结时用户看不到，目前没有 Linux 到 Android 的通知通道；
- NetworkManager 的模拟层会发布“未知”连接状态，个别应用可能以为自己断网。

**不受影响的**：已经在运行的工作区 KWin 里，桌面工具照常工作：ScreenShot2 是离屏渲染，fake input 与后端无关，KWin 的 D-Bus 也不等宿主。只是画面和客户端的帧回调停住。

## 5. 无头工作区与远程观看（源码与文档，未上机）

### 5.1 工作区实际从宿主拿什么

工作区 KWin 从宿主只拿三样：帧时钟（`wp_presentation` 反馈）、缓冲分配（`rungic-gpu-alloc` 租借 AHB，录屏缓冲也走这条路）、可选的零拷贝呈现。前两样在容器里可以自己解决。

### 5.2 KWin virtual 后端（kwin v6.6.5 `b04d59c0`）

- `--virtual` 用 Noop session，每个输出自带软件 vsync 定时器，不依赖宿主。
- 支持 `zkde_screencast`、fake input、EIS、ScreenShot2 和 Xwayland，运行中可以用 custom modes 改尺寸。
- 本项目的计算机操作工具（截图、fake input、KWin 脚本）都与后端无关。
- **原样不能用**：
  - GPU 节点只靠 `drmGetDevices2()` 枚举 `/dev/dri`，而容器里只有 `/dev/kgsl-3d0`；
  - Mesa 没有 llvmpipe，softpipe 太慢。
- **需要的补丁**（约 50–100 行，大多复用 docs/72 的钩子）：
  1. 指定渲染节点为 `/dev/kgsl-3d0`；
  2. EGL 使用该节点；
  3. linux-dmabuf 只开放 v3（与 Xwayland glamor 补丁一致）；
  4. 录屏缓冲交给 PipeWire 前的同步（KGSL 没有隐式 fence），这一项要实测。
- GBM、EGL 在 KGSL 上已有探针实测通过（docs/research/93）。
- **后端不能热切换**：只在启动时选定。重启 KWin 会结束 Xwayland 及其应用，所以 Agent 工作区只能启动时就定为无头。

### 5.3 一律无头之后的代价

| 去处 | 现在 | 改为无头之后 |
|---|---|---|
| 手机浮窗、手机导播台 | 本来就是录 PipeWire（约 52 fps） | 不变 |
| 手机全屏、电视的焦点格 | 宿主零拷贝（49–54 fps） | 失去零拷贝，多一次录屏渲染和一次合成 |
| 电视导播台的缩略格 | 宿主零拷贝 | 改为 PipeWire 后由 Linux 合成 |

**第二阶段：把零拷贝找回来**（设计，2026-10-02 与用户讨论，未实现）

- **约束**（docs/57）：今天的零拷贝要求 KWin 画进从宿主租借的 AHB（`rungic-gpu-alloc`），宿主再把它直接设到自己的子图层上。Android 的 SurfaceControl 只接受 AHB，app 不能把任意 dma-buf 包成 AHB，所以**只有宿主分配的缓冲能零拷贝呈现**。
- **做法**：给 virtual 后端加一个“可脱离的呈现端”。

  | | 没人看，或 APK 冻结 | 手机全屏或电视在看 |
  |---|---|---|
  | 时钟 | KWin 自己的软件 vsync | 仍是 KWin 自己的；宿主的反馈只作参考 |
  | 缓冲 | KWin 用 GBM 在 KGSL 上自己分配 | 向宿主租借 AHB（沿用今天的路径） |
  | 画完一帧之后 | 不做别的 | 把缓冲交给宿主呈现，不阻塞 |
  | 效果 | 工作区照常运行 | 和今天一样零拷贝 |

  - **挂上和摘下**：有人看时连接宿主，下一帧起把交换链换成租借的缓冲（KWin 改分辨率时本来就会重建交换链）；没人看或宿主不响应时，换回自有缓冲。
  - **宿主冻结不能卡住 KWin**：
    - 与宿主的连接放在独立线程，非阻塞写，KWin 主线程不等它；
    - 宿主扣着缓冲不还时，KWin 换别的空闲缓冲；全被扣住，就立即摘下呈现端；
    - 用 release 和 feedback 超时（约 200 ms）判断宿主停住了，并且在再次租借之前就判断，避免卡在租借的 3 s 超时上。
  - **已租的缓冲在冻结后仍可用**：AHB 背后是 dma-buf，KWin 持有 fd，内核就不会释放【推断，待实测】。
- **复用**：呈现部分复用今天 Android 后端的代码（租借分配器、`set_acquire_fence` 显式同步、AHB 的 release 跟踪）。宿主收到的仍是租借的 AHB，几乎不用改；电视导播台的格子图层不变。
- **退而求其次的方案**：工作区的录屏流改用宿主租借的缓冲，宿主直接呈现这些缓冲。代价是每帧多一次 GPU 拷贝（从输出拷进录屏缓冲），还要另做一条通知，告诉宿主哪块缓冲是最新帧。
- **先验证**：
  1. APK 冻结或被杀后，已租的 AHB 是否仍然有效；
  2. KWin `EglSwapchain` 在宿主扣住缓冲时能否按需加缓冲（读源码核对）；
  3. 时钟解耦后的零拷贝帧率是否保持今天的 49–54 fps。

### 5.4 RemoteSurface Host（Swift 服务、FreeRDP 3.31、`zkde_screencast` 加 fake input）

**能否接到工作区**：
- 它读 `WAYLAND_DISPLAY` 和会话总线，所以给它工作区的环境变量即可（与 `rungic-workspace-stream` 相同）。
- 每个实例服务一个显示器、一个客户端；用 `--config`/`--socket` 可以多开。
- 授权靠桌面文件里的 `X-KDE-Wayland-Interfaces`，要在工作区的 ksycoca 里登记。

**能否在手机上运行**：
- swift.org 有 Swift 6.4.0 的 `ubuntu2604-aarch64` 包；
- FreeRDP 需要自己构建（Ubuntu 的包关了 H.264）；
- `host/build.sh` 写死了 x86_64，要改。

**编码器**：
- 本机没有 DRM 渲染节点，自动选择会落到“MemFd 采集，加 libx264”。
- VA-API 不可能；V4L2 M2M 只支持 DMABUF 队列，FFmpeg 原样用不了；`codec.sock` 的 MediaCodec 随 MainActivity 生灭，不能用于无头场景。
- **第一阶段**：先用软件 x264，720p，损伤驱动。
- **超出预算时**：仿照 `ClipboardDaemon`，用 app_process 以 shell uid 起一个独立的 MediaCodec 编码守护进程。

**导播台**：现在的状态在 APK 的 `Director.java` 和用户会话里。无头导播台需要：
- 一个“导播台工作区”（virtual KWin），里面全屏跑 `--director` 窗口；
- 导播台状态在 Linux 侧维护一份；
- RemoteSurface 接到这个导播台工作区。

**声音**：Host 从 PipeWire 取声音，而容器用的是 PulseAudio（工作区进 null sink），第一阶段先不做声音。

## 6. 方案比较与建议

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **A. 让 APK 不被冻结** | 电池优化豁免（经系统对话框，离开“设置”或重启后生效）；Agent 工作期间 APK 持有 `PARTIAL_WAKE_LOCK`（同时阻止 CPU 挂起）；根控制器补发 `cmd activity unfreeze --sticky` 兜底 | 成本最低，保留零拷贝和全部宿主功能 | 依赖 Moto 的启发式规则，每个机型和 ROM 都要重验；APK 不冻结时，息屏后宿主是否还给工作区帧回调待实测；远程观看仍要经 APK 的画面 |
| **B. 宿主中与显示无关的功能移出 APK** | 用 `app_process`（root 或 shell uid）运行平台请求、通知、编码守护进程 | 脱离 APK 生命周期 | 改动面大，只能逐项迁移 |
| **C. Agent 工作区一律无头** | KWin virtual 后端加 KGSL 补丁；手机和电视观看走 PipeWire；远程走 RemoteSurface | 最稳，完全不依赖 APK，最符合“息屏加远程”的要求 | 失去电视和全屏的零拷贝（第二阶段找回）；KWin 新增补丁维护点；内存和功耗要实测 |

**建议**：
- **立即修（与方案无关）**：
  - `user_watching()` 在连不上时按“不在看”处理；
  - `codec-client.c` 的 `connect` 加超时；
  - `rungic-cast` 改为分阶段的短超时；
  - 工作区启动的第一次往返加上限，宿主无响应时明确报错，不要无限挂住。
- **近期：方案 A**，让现有架构先能在息屏时跑完团队任务，同时为方案 C 争取时间。
- **主线：方案 C**，配合 RemoteSurface 实现远程观看；方案 B 按需补齐（OCR、通知、编码）。
- **CPU 不挂起**：Agent 忙时需要持有 wakelock（方案 A 由 APK 持有；方案 C 由 root 侧 `/sys/power/wake_lock` 加 keeper 和 busy 标记控制，空闲即释放）。
- **远程入口**：如果走 VPN 应用，那个应用本身也要豁免冻结和 Doze。

**当前设备状态**：本轮实验把 `com.rungic.plasma` 加进了 deviceidle 白名单（root），至今仍在，正是方案 A 需要的。如果不采用方案 A，用 `dumpsys deviceidle whitelist -com.rungic.plasma` 撤销。

## 7. 上机验证顺序（都还没做；涉及息屏的步骤先征得用户同意）

1. **只读核对**：
   - `getprop ro.product.is_prc`、`persist.sys.smart_freezer_enabled`；
   - 从本机拉 `services.jar`，复核第 2 节的结论；
   - 息屏后 logcat 过滤 `SmartFreezer|UidStateController|moto_freezer`；
   - 用 `/sys/kernel/wakeup_sources` 区分“APK 被冻结”和“整机挂起”。
2. **方案 A**（息屏实验）：
   - 白名单生效（离开“设置”或重启）后，重测 90 s 和 180 s；
   - 只持有 wakelock 时的效果；
   - `unfreeze --sticky` 的效果；
   - APK 不冻结时，宿主的帧回调和画面是否继续。
3. **方案 C**：
   - 在 Mac mini 构建带 KGSL 补丁的 KWin，在不显示的测试槽位以 `--virtual` 启动；
   - 核对 GLES 和 FD710、dmabuf v3、glamor；
   - 启动 Kalk、Krita、Blender；
   - 跑一遍 `rungic_cua` 的截图、输入和脚本；
   - 测 `rungic-workspace-stream` 的帧率和同步。
4. **息屏下跑真实团队任务**：息屏 5–30 分钟，记录 CPU、GPU、电流和温度。
5. **RemoteSurface Host**：
   - 构建 ARM64 版，在测试工作区监听回环地址，从电脑接入；
   - 测 720p 和 1080p 时 x264 的 CPU 和延迟；
   - 测断开重连；
   - 在 Dozing 状态下远程接入。
6. 对比电视和全屏走 PipeWire 与走零拷贝，决定是否做第二阶段。

## 8. 风险

- **内存**：
  - 一个工作区的 KWin 约 146–185 MB，加上 Xwayland 和私有服务；
  - 每个 RDP Host 估计再加 50–100 MB；
  - 容器 memcg 上限 4 GiB。
  - 所以 RDP 按需启动，同时只开一个。
- **功耗和发热**：息屏后 GPU 继续合成，软件 x264 会占大核。靠损伤驱动出帧、没人看时降刷新率、空闲冻结（keeper）来控制。
- **维护**：
  - 方案 A 要按机型和 ROM 重验；
  - 方案 C 新增 KWin 后端补丁，要随 KWin 6.7 升级。
- **未解决**：
  - KGSL 下录屏缓冲的同步待实测；
  - 声音路径；
  - 锁屏时的通知通道。

## 9. 已修：冻结宿主时的卡死（2026-10-02）

先修与方案无关的四处卡死，方案 C 另行推进：

1. **工作区启动**（`agent/workspace/rungic-workspace`）：启动 KWin 之前，先用 3 s 超时向 `platform.sock` 发一次 `status`。宿主不答就不启动 KWin，并把原因写进 `$XDG_RUNTIME_DIR/rungic-workspace-N.failed`。
   - `workspace.ensure` 看到这个文件立即返回失败，不再等满 10 s；
   - 路由把原因放进错误信息（“workspace N did not start: the Android host is not responding …”），Agent 能如实报告；
   - 以前 KWin 会在第一次往返上无限挂住。
2. **`codec-client.c`**：`connect` 前设 2 s 的 `SO_SNDTIMEO`。Unix socket 的 `connect` 按发送超时等待，backlog 满时最多等 2 s，连上后恢复原设置。
   - 私有 FFmpeg（`packages/ffmpeg`）以 overlay 引入同一文件，下次构建时带上。
3. **`rungic-cast`**：先用 3 s 做一次健康检查，宿主不答就立即返回 `host-unreachable`，不再一条命令等满 350 s。
4. **语音助手的 `user_watching()`**：`platform.sock` 不答时按“没人在看”处理，团队的提问、受阻、完成照常发通知。以前被当成“在看”，通知被压住。

**实机验证**（2026-10-02 12:52）：用 root 对 APK 发 `SIGSTOP` 模拟冻结，几秒后 `SIGCONT`，期间不息屏。
- `rungic-cast status` 3.1 s 返回 `host-unreachable`；
- `workspace.ensure(4)` 3.2 s 返回失败，原因为“the Android host is not responding …”；
- Plasma 会话随后正常。
- 中途还修了 `ensure` 的一处问题：单元之前失败过、自动重启次数用完后，新的 `start` 会被 systemd 拒绝，脚本根本不运行，`ensure` 因此等满超时。现在先 `reset-failed` 再启动，单元一进入 failed 状态就停止等待。
- **没有在实机上验证的**：`codec-client.c` 的超时（编译通过，没有构造 backlog 排满的场景）；`user_watching()` 的通知路径（还要在锁屏下实测团队通知）。

## 10. 方案 C 第一步：无头工作区实机实验（2026-10-02 13:55–14:10）

**实现**：
- **KWin 补丁** `packages/kwin/debian/patches/rungic/virtual-render-device.patch`：设置 `RUNGIC_KWIN_RENDER_DEVICE` 后，virtual 后端打开指定的 GPU 节点，EGL 显示用这个节点，客户端最多拿到 dmabuf v3；不设置时行为不变。
- **工作区脚本**：`RUNGIC_WORKSPACE_BACKEND=virtual` 时，以 `kwin_wayland --virtual --width 1920 --height 1080` 启动，`RUNGIC_KWIN_RENDER_DEVICE=/dev/kgsl-3d0`，不检查、不探测宿主。默认仍是 Android 后端。
- **实验方式**：用 systemd drop-in 只给测试槽位 3 和 4 打开，测完已删除。
- 测试脚本在 `.work/diag/headless/`。

**结果**（实测）：

| 项目 | 结果 |
|---|---|
| 启动 | 1.4 s 就绪 |
| KWin 渲染 | OpenGL ES 3.2，渲染器 FD710（GPU，不是软件渲染） |
| Xwayland | GLX 直接渲染，FD710，OpenGL 4.6 core |
| 桌面工具（经 `rungic-cua mcp`，与 Agent 相同的路径） | `desktop_launch` 启动 Kalk 6.7 s；`desktop_windows` 看到它在 `Virtual-0` 上；`desktop_screenshot` 0.3 s |
| 录屏（`rungic-workspace-stream` 的 PipeWire 节点） | 手动 `pw-link` 接到 GStreamer：指针每 30 ms 动一次时，2.05 s 收到 60 帧（约 29 fps）；存下的帧画面正确：壁纸、Kalk 窗口、指针，没有撕裂或黑块 |
| 内存 | 无头 KWin RSS 约 152 MB；同时运行的 Android 后端工作区 KWin 约 142 MB |
| **APK 冻结时** | 实验中途手机进入 Dozing，APK 冻结（平台桥 `EAGAIN`）。无头工作区照样启动、截图、录屏，正是方案 C 要的效果 |

**注意**：
- 本机 WirePlumber 0.5.13 加 PipeWire 1.6.2 不让 GStreamer 的 `pipewiresrc` 按 id、serial 或名字连到 KWin 的录屏节点（报 “target not found”）。Android 后端工作区也一样，与无头无关。生产中的浮窗经 KPipeWire 消费，不受影响。测试时用 `autoconnect=false` 加 `pw-link`。
- 浮窗程序（`rungic-agent-screen-window`）先问 APK 平台桥，桥不通时不会去取画面。

**还没做**：
1. **导播台、浮窗、电视要知道无头工作区**：现在成员列表来自宿主的 `liveSources`，无头工作区不在里面。成员状态和画面要改由 Linux 侧提供，APK 只是其中一个呈现端。
2. **默认启用无头**：先解决第 1 条，并确认浮窗和电视的观看体验，再把 Agent 工作区默认改为无头。
3. 第二阶段的零拷贝（§5.3）；RemoteSurface Host（§5.4）；Agent 忙时持有的 wakelock（§6）。
4. 没有核对 dmabuf v3：手机上没装 `wayland-info`。

## 11. 导播台识别无头工作区（2026-10-02 14:00–14:15，实机）

**做法**：
- **keeper 心跳**（`agent/workspace/keeper.cpp` 的 `announce()`）：无头工作区（`RUNGIC_WORKSPACE_BACKEND=virtual`）的 keeper 每次 `check()`（约 3 s）都向 APK 发 `{"op":"director","alive":N}`，连接超时 0.5 s，APK 冻结时不会拖住 keeper。
  - 用心跳而不是一次性通告：APK 重启或解冻后会自动重新得知。
- **APK `Director`**：
  - 记录无头工作区最近一次心跳；
  - 成员 = 宿主有表面的工作区 ∪ 10 s 内有心跳的无头工作区；
  - `picture()` 一律取宿主真正有画面的成员。焦点是看板、无头工作区或还没打开的成员时，电视和全屏改呈现旁边有画面的那块；
  - 无头工作区的格子显示占位“在后台运行”（`tile_headless`），等第二阶段零拷贝（§5.3）补上画面。

**实测**：
- 无头工作区 4 启动后 1–2 s 进入成员列表（`[1, 4]`）；停止后约 10 s 心跳过期，回到 `[1]`。
- **Linux 导播台窗口**：焦点格是工作区 4 的实时画面（Kalk 窗口加壁纸），由 Linux 侧经 PipeWire 录取；右侧是工作区 1 的缩略格。
- **APK 全屏导播台**（与电视同一套画法）：工作区 4 是“在后台运行”占位，工作区 1 的缩略格正常。

**过程中发现的问题**：
1. **工作区随用户会话一起停止**：工作区单元有 `PartOf=graphical-session.target`，装 APK 等原因重启 Plasma 会话时，无头工作区也一起停掉。无头的 Agent 工作不该因为手机界面重启而中断，要把无头工作区和用户图形会话的生命周期分开（待做）。
2. **APK 文件名**：另一个会话把版本号提到了 2.29，构建输出变成 `Rungic-2.29.apk`。第一次装成了旧的 2.28，所以心跳没被处理。安装前要核对输出文件名和时间。
3. **调用顺序**：已有工作区 1 的浮窗时，给工作区 1 再调 `rungic-agent-screen on` 不会切换到导播台。要给新工作区调（`RUNGIC_WORKSPACE=4`），这与 Agent 工具的实际调用一致。

## 12. 工作区独立于用户会话；Agent 忙时保持唤醒（2026-10-02，实机）

**工作区与用户会话分开**：`rungic-workspace@.service` 去掉了 `PartOf=graphical-session.target`。
- 以前装 APK 或 Plasma 崩溃导致用户会话重启时，Agent 工作区会一起停掉（§11 中实际发生过）。
- 现在工作区只由 Agent 工具和 keeper（空闲冻结、长时间空闲后关闭）结束。
- Android 后端的工作区在宿主断开时自己退出（133），再由 `Restart=on-failure` 重连。

**息屏后系统其实没挂起，只是碰巧**：
- 深度空闲 4 分钟内 `suspend_stats/success` 一次没增加。
- 原因是 `audioserver` 一直持有 `AudioMix` 部分 wakelock，归属 uid 10348，推测是 Termux PulseAudio 常开的音频流。
- 所以此前息屏时 Agent 还能继续，只是碰巧。这条常开音频流本身也耗电，另立问题处理。

**`rungic-agent-wakelock`**（容器里的 root 系统服务，`agent/workspace/`）：
- 每 5 s 检查忙碌标记：`/run/user/*/rungic-workspace-*.busy`（工作区认领）和 `rungic-agent.busy`（语音助手在跑 turn 或后台 turn 时写入，结束时删除），只认持有者进程还活着的标记。
- 有忙碌就写内核 wakelock `rungic_agent`，带 60 s 超时，每 5 s 续一次；服务自己挂了，锁最多 60 s 后自动失效。没有忙碌就立即 `wake_unlock`。
- 容器的 `/sys` 是只读的，所以单元用 `unshare --mount` 在服务自己的挂载命名空间里把 `/sys` 重新挂成可写。`ReadWritePaths=` 做不到：只读挂载下的路径它不会改成可写，实测报 EROFS。
- **实测**：写入一个活进程的忙碌标记后，Android 侧 `/sys/power/wake_lock` 出现 `rungic_agent`；删掉标记约 5 s 后释放。
- 有单元测试（`tools/tests/test_agent_wakelock.py`）。
