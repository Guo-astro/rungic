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

## 13. 第二阶段：无头工作区在电视和全屏上的画面（呈现器，2026-10-02，实机）

**选型**（设计调研见本日对话，结论如下）：
- **方案 B：每个被宿主显示的工作区一个独立的呈现器进程**。宿主不用改，宿主冻结只会卡住呈现器，工作区 KWin 不受影响。
- 方案 A（呈现器做在 KWin 里）约 900–1400 行 KWin 补丁，线程和阻塞路径都在 KWin 里，风险最高。
- 方案 C（让 KWin 的录屏缓冲直接用租借的 AHB）还能省一次拷贝，作为以后在方案 B 基础上的优化。
- **同类项目**：最接近的是 wl-mirror（把另一个输出的 PipeWire 录屏画进自己的窗口）。但它画进的是自己的 EGL 窗口表面，我们要画进宿主租借的缓冲；而且它是 GPL-3.0。所以自己写一个小程序，复用 KPipeWire（LGPL，浮窗已在用）和我们 Android 后端的租借代码。

**宿主对 ws-N 客户端的要求**（`android/host`，`packages/android-host`）：
- 连接 `/mnt/android-wayland/ws-N`；
- 在制造商为 “Rungic” 的那个工作区输出上，开一个全屏 `xdg_toplevel`；
- 只提交从 `rungic-gpu-alloc` 租借的 XBGR8888 缓冲（宿主按 inode 认出，才走零拷贝），用 `zwp_linux_dmabuf_v1` v3 包装；
- 每帧通过 `set_acquire_fence` 交 GPU 栅栏；按宿主的 frame callback 控制节奏。
- 宿主的 `liveSources` 会自动把这个工作区算作有画面。

**实现**：
- **`agent/workspace/present.cpp` → `/usr/libexec/rungic-workspace-present N`**：
  - 子进程 `rungic-workspace-stream` 录取工作区输出（指针画在画面里）并给出节点号；
  - KPipeWire `PipeWireSourceStream` 接收 DMA-BUF 帧；
  - GLES（Qt 的 EGL 显示）画一个外部纹理四边形，画进 3 块租借的 AHB；导出 EGL 原生栅栏后提交给宿主；
  - 宿主要了帧、又有空闲缓冲时才画，否则丢弃该帧；
  - 宿主的指针事件转成子进程的 `pointer`/`button`/`axis` 输入；
  - 宿主前几次往返有 3 s 上限；宿主断开、子进程退出或 stdin 关闭时，呈现器结束。
- **keeper**：无头工作区被电视（`tvShown`）、导播台全屏或单屏全屏显示时，启动呈现器，否则停止。导播台全屏的判断放在“助理屏是否打开”之前，因为导播台与浮窗开关无关。呈现器很快结束时，重启等待从 30 s 起翻倍，最长 5 min。
- **APK `Director.poll`**：`live` 变了也重排，以便无头成员有了画面就换掉占位。
- **KWin 补丁 `screencast-finish-without-implicit-sync.patch`**：GPU 节点不是 `/dev/dri` 下的 DRM 设备时（KGSL），录屏帧交给 PipeWire 前先 `glFinish`（做法同 Nvidia 和 llvmpipe）。否则消费方可能读到 GPU 没画完的帧；这也影响 Android 后端工作区的浮窗。

**实测**（G100 S，测试槽 4，无头）：
- **导播台全屏**：焦点格是工作区 4 的实时画面（Kalk、壁纸、指针），占位已消失。
- **帧率**：工作区里放 30 fps 的测试动画，宿主呈现约 27.6 fps（10 s 内 276 帧），约 2.4 fps 因宿主没要帧或缓冲占满而丢弃。
- **冻结**：对 APK 发 `SIGSTOP`：
  - 工作区照常跑动画，桌面截图也成功；
  - 呈现器只是暂停；`SIGCONT` 后同一个进程自动恢复，30 fps（10 s 内 300 帧）。
- **退出全屏**：keeper 立即停止呈现器。
- **第一版的坑**：
  - Qt 在 Mesa 上默认建的是桌面 OpenGL 上下文，外部纹理扩展不可用，着色器编译失败，随后在 libgallium 里 SIGSEGV；keeper 每 3 s 重启一次，每次留下约 140 MB 的 core。
  - 已改为显式要求 GLES，着色器链接失败就退出，keeper 加重启退避；相关 core 已清理。
- **冻结期间 Agent 工具变慢**：上面那次截图在冻结期间用了 19 s。原因是路由和 `rungic-agent-screen` 每次请求平台桥都要等满超时（3 s、5 s）。
  - 已改：一次请求超时或被拒后，写入 `$XDG_RUNTIME_DIR/rungic-host-unreachable`，之后 15 s 内的请求立即失败；成功一次就清除。

## 14. Agent 工作区默认无头（2026-10-02）

- `rungic-workspace` 默认 `RUNGIC_WORKSPACE_BACKEND=virtual`，并把实际选用的后端导出给子进程，keeper 据此决定发心跳、开呈现器。`RUNGIC_WORKSPACE_BACKEND=android` 可退回旧方式。
- 观看方式：
  - 浮窗和导播台窗口：PipeWire（与以前相同）；
  - 电视和全屏：呈现器；
  - 远程：RemoteSurface（下一步）。

**默认无头的实机验收**（2026-10-02 15:20–15:35）：
- 去掉测试 drop-in 后，工作区 1 和 4 都按默认以 `kwin_wayland --virtual` 启动，成员为 `[1, 4]`。
- 导播台全屏：焦点格是工作区 1（KClock），缩略格是工作区 4（Kalk），两路画面都来自呈现器。
- **APK 冻结时 Agent 工具的耗时**：
  - 修改前每次截图要 16–19 s，原因：每次工具调用都同步等 `show_workspace` 的两个 `rungic-agent-screen` 子进程，而平台桥连接已排进 backlog、却永远等不到回复，每个请求都等满超时；
  - 已改：`show_workspace` 放到后台线程，宿主不可达时直接跳过；不可达标记的有效期由 15 s 延长到 60 s，因为 Agent 两次调用之间常常超过 15 s；
  - 修改后：冻结期间第一次截图 4.3 s（一次超时），之后每次约 1.0 s（含启动 MCP 进程）。
- 测完退出全屏，呈现器随即停止；屏幕超时恢复为 60000。

## 15. 远程观看：RemoteSurface Host（2026-10-02）

**用户要求**：整台设备只有一个 RDP Host，权限在工作区之上，不为每个工作区各开一个；连接时客户端知道设备上有哪些屏幕（手机桌面、各 Agent 工作区，以后还有导播台），观看端可以直接切换。

**ARM64 构建**（Mac mini，独立容器 `remotesurface-build`，镜像与 `rungic-build` 相同，没有动 `rungic-build`）：
- 工具链：Swift 6.4.0 `ubuntu2604-aarch64`，GPG 签名有效。
- FreeRDP：另编了共享库形式的 FreeRDP 3.31.0（只开 server）供 Host 链接。原因：`native/build.sh` 只产出静态客户端库，而 Ubuntu 26.04 的 freerdp3-dev 已是 3.32.0，与 Host 要求的版本不符。
- 测试全部通过。产物在 `.work/remotesurface/dist-arm64/`（90 MB，自带 Swift 运行库和 FreeRDP）；手机容器已有它需要的其余运行库（FFmpeg 8.0.1、libx264、ICU、PipeWire 等）。
- 需要提给 RemoteSurface 的问题：`host/build.sh:28`/`:178` 写死 x86_64（只影响 ASan 和 Weston）；`host/native/CMakeLists.txt` 写死 FreeRDP 3.31.0；`native/build.sh` 在装有 libopus-dev 时客户端构建失败；`pipewire_capture` 测试在 aarch64 上不稳定（14 次失败 8 次）。

**单工作区冒烟测试**（实测）：
- 在工作区 1（无头）的环境里运行 Host，监听回环 3391，经 `adb forward` 映射到 K8 的 13391，用 K8 上的 RemoteSurface 客户端连接。
- 结果：TLS 加凭据认证通过；1920×1080，libx264 软件编码（没有 DRM 渲染节点，自动退回软件），持续约 27 fps，几十秒内确认 823 帧。
- 测完已断开，并关闭 K8 上的客户端和手机上的测试 Host。

**设计**（调研结论，未实现）：
- **会话内切换屏幕，不重连**：
  - Plasma 后端改为按端点（Wayland socket、会话总线）创建，连接带超时；
  - 切换时先接通新屏幕，等到它的第一个 keyframe 再提交，然后停掉旧屏幕；约 4 s 内没有 keyframe 就回复失败，保留原屏幕，所以冻结的手机桌面不会造成黑屏；
  - 切换时重置帧准入、按住的键、光标序号和码率等设置。
- **屏幕列表和切换的通道**：复用现有 `RemoteSurface::Session` 通道，加 `screens` 功能（hello 里给出列表；请求 `{"command":"screen","id":…}`；列表变化时 Host 主动推送）。客户端在会话面板加 Screen 组，并加 Agent 命令和 `rsctl screens`/`rsctl screen`。
- **屏幕从哪来**：Rungic 维护注册目录 `$XDG_RUNTIME_DIR/remote-surface/screens.d/<id>.json`，Host 每秒读一次；格式由 RemoteSurface 定义，Host 里不写 Rungic 专有逻辑。
  - 工作区启动时写条目、停止时删除；
  - 手机桌面的条目由 Rungic 根据“宿主不可达”标记，写明当前是否可用。
- **授权**：KWin 按可执行文件的规范路径匹配桌面文件，所以 `~/.local/share/applications` 下一个桌面文件就覆盖所有 KWin。
- **部署**：一个 `rungic-remote.service`，运行在用户会话里，单端口。
- **预估规模**：Host 约 1000–1200 行，协议和客户端约 500–700 行，Rungic 侧约 150–250 行。
- **之前写的 `rungic-remote@N`**：每个工作区一个 Host，方向不对，已作废，没有提交。

## 16. 设计：手机浮窗的画面也由宿主图层显示（2026-10-02，已放弃，见 §17）

**目标**：手机上的显示路径（浮窗、导播台窗口）和电视、全屏统一走“呈现器 → 宿主图层”，PipeWire 只留给远程观看。浮窗因此少一次拷贝，也不必每个成员各开一路录屏。

**难点是同帧**：浮窗在用户的 KWin 里逐帧移动（拖动、捏合、收边、呼吸动画、圆角、字幕胶囊和编号压在画面上）。如果宿主图层按单独的消息摆放，拖动时画面会落后于窗口。

**方案**：用 KWin 现成的叠加层机制，并且只用“底层加挖洞”（underlay）一种方式。
- KWin 6.6 已有叠加层的分配、挖洞（含圆角）、设备坐标换算和失败回退。让 Android 后端把宿主的子 SurfaceControl 当作 KWin 的叠加层（新增 `HostSourceLayer`），层级在桌面层之下。
- 浮窗为每块画面放一个占位子表面（在窗口表面之下，单像素黑缓冲，用 `wp_viewport` 定大小），通过新协议 `rungic_host_picture_v1.set_source(slot)` 和 `set_corner_radius` 声明“这里显示宿主画面槽 N”。KWin 把它作为 underlay，在桌面帧上挖一个带圆角的透明洞。
- KWin 把子表面位置、viewport 和槽号，随同一次桌面 commit 交给宿主（同步子表面，加上宿主协议 `rungic_host_source_v1`）。宿主在**同一个 `ASurfaceTransaction`** 里提交桌面缓冲（有洞时改为半透明）和各画面图层的位置、alpha、显隐。所以拖动不会差帧。
- 画面图层的内容直接来自现有的呈现器（ws-N），工作区出帧时，用户的 KWin 和浮窗都不必醒来。
- 字幕胶囊、编号、工具栏和 KWin 画在上层的东西，都靠挖洞自然叠在画面上，不必把客户端界面拆成多层。
- **NDK 限制**：Android 16 的 NDK 没有图层圆角接口，所以圆角只能靠 KWin 挖洞时的圆角 alpha。
- **同类做法**：Android SurfaceView（窗口挖洞、内容在下层）、Chromium 的 SurfaceControl underlay、KWin DRM 后端的 overlay/underlay，都是同一个模型。

**回退**：KWin 不提供协议、呈现器没连上、或零拷贝关闭时，浮窗照旧用 PipeWire。宿主冻结时手机桌面本身也停了，没有可回退的；解冻后自动恢复。

**改动**（估计约 1.5–1.7 千行）：
| 部分 | 内容 | 估计 |
|---|---|---|
| KWin | 新补丁 `android-host-pictures.patch`：协议和服务端；放宽叠加层候选条件；`importHostSource`；洞的 alpha；`HostSourceLayer`；`hostScale` 位置修正 | 约 500 行 |
| 宿主 Rust | `render_phone` 沿子表面树收集宿主画面；多层共用一个事务；背景色层；只换缓冲的提交；画面路由和节奏 | 约 600 行 |
| APK | `agent-screen` 的回复增加 `live`、`phone` 字段，并触发 SCREENS 事件 | 约 30 行 |
| 浮窗 | `HostPicture` QML 类型，在 Qt 渲染线程里驱动占位子表面；宿主模式下画面区域透明；回退判断 | 约 400 行 |
| keeper | 手机显示时也启动呈现器 | 约 30 行 |

**风险**（大多待实测）：
- 缩略图从 1920 缩到约 190 设备像素，可能超出显示硬件的缩放上限，SurfaceFlinger 会退回 GPU 合成。对策：缩略图由呈现器租小缓冲。
- 硬件图层数可能不够。
- KWin 的叠加层分配全有或全无，失败时画面区域会短暂变黑。
- KWin 自己的截图或录屏里，画面区域是黑的。
- 必须按 docs/57 的教训，用 GPU 合成路径复验一次。

**实机测试**：会显示在用户屏幕上，要先约时间：
- 同帧：拖动、捏合、收边时录屏逐帧比较；
- 合成方式：`dumpsys SurfaceFlinger`；
- 强制 GPU 合成；
- 回退：杀呈现器、对 APK SIGSTOP、重装 APK；
- 效率：和 PipeWire 路径对比 CPU、GPU 和带宽。


## 17. 方向调整：浮窗、全屏和电视导播台全部放在 Linux 里（2026-10-02，用户决定）

**用户要求**：浮窗、放大的浮窗和它们的全屏模式，都在 Linux 系统里完成。将来 Linux 发行版运行在 PC 上时，这些功能可以直接用。

**结论**：§16 的“宿主图层”方案只适用于 Android，已停止。KWin 侧和宿主侧的两个实现子代理已经叫停，未完成的改动全部撤销，没有进入仓库。

**新的分工**：
- **Linux 负责**：
  - 浮窗，以及导播台窗口的浮窗、放大和全屏三种形态，都由同一个 QML 窗口完成；
  - 团队看板（`TeamBoard.qml`）、格子布局和焦点切换都在这个窗口里；
  - 全屏时的触摸转发，沿用浮窗现有的输入方式（fake input）。
- **电视**：是 KWin 的第二个输出（桌面模式的 CAST 输出；在 PC 上就是外接显示器）。
  - 电视显示导播台 = 导播台窗口全屏放在这个输出上；
  - 电脑模式 = 不放。
  - 投屏控件里“导播台 / 电脑模式”的切换改为控制这件事。
- **Android（Rungic 应用）只负责**：把 KWin 的输出帧零拷贝放到手机屏幕和电视上（已有）。导播台的状态、布局和绘制（`Director.java`、`DirectorArt`、`AgentFullscreen` 的导播台部分、宿主的电视格子图层 21-tv-director、呈现器）逐步退役。
- **代价**：
  - 工作区画面要经用户的 KWin 合成一次，多一次 GPU 拷贝；以后可用 KWin 标准的直接扫描、叠加层把这次拷贝省掉（在 PC 上本来就有）。
  - 横屏全屏要由 KWin 旋转输出，或请求 Android 旋转，不能由窗口自己强制。
  - 声音跟随焦点要改由 Linux 侧的导播台提供焦点。

**顺序**：
1. 导播台窗口在手机上全屏（Linux）；
2. 电视走 CAST 输出加导播台窗口；
3. 声音跟随和 keeper 的显示判断改用 Linux 侧状态；
4. 退役 Android 侧的导播台、全屏和呈现器；
5. 视情况做叠加层优化。

远程观看的硬件编码，等 RemoteSurface 多屏合并后再做。§16 第 2 项“录屏直接进借来的内存”在新方向下不再需要，取消。

### 17.1 第 1 步：浮窗的全屏在 Linux 里（2026-10-02，实机验证）

**做法**（`agent/screen/qml/Main.qml`）：
- 浮窗新增第三种形态 `fullscreen`，与 window、tab 并列。全屏按钮不再调用 APK 的 `fullscreen`（AgentFullscreen）。
- 进入全屏时，画面、触摸层和工具栏（`stage`）整体移进同一进程的一个**普通全屏窗口**（xdg_toplevel），退出时移回浮窗的图层窗口。
  - 实测：图层窗口即使改到 overlay 层，也压不住 Plasma Mobile 的状态栏和导航栏；对普通全屏窗口，桌面会自动收起面板。PC 上的 Plasma 同理。
  - PipeWire 画面项在两个窗口之间移动后照常出画。
- **不转手机，转窗口内容**：全屏窗口比宽更高（手机竖屏）时，`stage` 绕中心顺时针转 90 度，等于手机向左横放时的横屏画面。
  - 手机本身、桌面和其他应用不转，没有整机转屏动画，也不需要任何恢复步骤。
  - 触摸坐标由 Qt 换算到转后的方向，转发代码不用改。
  - 横屏显示器（PC）上不转。
  - 曾先试过经平台桥临时横屏（`orientation` 加 temporary/restore）；用户指出只转浮窗即可，已改回，APK 的这部分改动也已撤销。
- 背景用壁纸的模糊图，即 `rungic-agent-screen background` 另写的 `$XDG_RUNTIME_DIR/rungic-agent-screen/director-background.jpg`。
- 画面按 16:9 放到最大。导播台的其他屏幕排在右侧一列；缩放按钮沿用导播台的三级 `level`：标准、放大（列宽 15%）、单独（不显示列）。
- 触摸规则与 APK 的 DirectGestures（docs/66）一致：
  - 点按 = 左键；长按 = 右键；按住移动 = 从按下处开始拖动；
  - 双指点按 = 右键，三指点按 = 中键；双指移动 = 自然滚动（按工作区 1080 像素换算）。
  - 点其他格子 = 切换焦点；点画面旁边，或从底边上滑（转后即手机左边缘）= 显示工具栏（退出、缩放、电视、关闭）。底边的点按仍是点击。
- 离开全屏的方式：
  - 工具栏的退出按钮；
  - PC 上按 Esc；
  - 仅限助手屏：全屏窗口失去焦点 0.4 秒以上（切到别的应用、主页手势）。
    - 桌面模式不用这条规则：它的第二块屏幕属于用户自己的 KWin，在全屏里点一下就会激活那块屏幕上的窗口。
    - 用户实测：沿用这条规则时，桌面模式全屏随便一点就退回了浮窗。
- 浮窗和全屏同属一个程序，助手屏（`--workspace N`）和桌面模式（`--desktop`）共用。桌面模式的全屏是用户的第二块屏幕，应当铺满（用户要求）：
  - 不留边距、不要圆角，不显示壁纸和阴影，16:9 以外的部分是黑边；
  - 点黑边呼出工具栏。
- 浮窗画面下方加了柔和阴影（Qt 6.9 起的 `RectangularShadow`）。
- 浮窗位置和尺寸取整：落在小数像素时，画面边上露出过一条底下的黑底（用户发现）。黑底现在也只在还没有画面时显示。
  - 安卓的返回键由 Rungic 应用自己处理（打开它的菜单），菜单会让全屏窗口失去焦点，因此同样退出全屏。
- 修了一个旧问题：屏幕尺寸变化时，`onAreaChanged` 先于派生值 `minWidth` 更新执行，横屏转回竖屏会把浮窗撑到横屏宽度的一半。`settle()` 改为直接按 `area` 计算。

**实机验收**（G100 S，工作区 1，无头 KWin，Dolphin 在工作区内）：
- 进入全屏：面板收起、画面铺满、手机方向保持竖屏（`mCurrentRotation=ROTATION_0`）。
- 转后的长按：右键菜单出现在手指所在的文件上。
- 横屏版本中的点按和拖动（指针落点准确，拖动框选了 3 项）：在转手机的那一版上测的；转内容之后只复测了长按。
- 工具栏退出：回到浮窗，浮窗保持原来的位置和大小。

**未验证**：
- 双指滚动和多指点按（adb 只能模拟单指）；
- 导播台（多个屏幕）的全屏布局和缩放；
- PC 上的 Esc。

**暂未移植**：按重力感应选择向左或向右横放。触控板模式和惯性滚动见 §17.3。

### 17.2 进出全屏无缝过渡（2026-10-02，用户要求）

**用户反馈的问题**：
- 进入全屏时，画面从左下角斜着滑进来；
- 状态栏和导航栏先显示，再消失。

**原因**：
- 当时的全屏是一个普通全屏窗口。Plasma Mobile 的两个面板在 overlay 层，它们发现“当前应用全屏”后才自己滑走（`containments/panel`、`taskpanel` 的 `fullscreen` 状态）。
- 新窗口刚出现时还不是全屏尺寸，画面先按错误尺寸排了一次，又用位置动画滑过去。
- 浮窗原来的位置放进转过的坐标系后，对应的是屏幕上另一个地方，所以看起来是从角落斜着进来。

**过程中试过、但放弃的做法**：另开一个 overlay 层窗口来显示全屏。
- 实测（WAYLAND_DEBUG）：新窗口空的第一帧约 49 ms 画出；画面移进去之后，第一次连同画面一起画却又用了约 112 ms（要第一次建立画面流纹理、特效和着色器）。
- 这段时间里画面两边都不在，录屏可见浮窗消失了十几帧。

**最终做法：同一个窗口完成全部过渡**（`Floater::setFullscreen`）：
- **进入**：
  - 浮窗切到 overlay 层，并声明接收键盘（OnDemand）。
  - 按 KWin 6.6.6 源码：图层窗口开始接收键盘时会被激活（`handleAcceptsFocusChanged` → `activateWindow`），激活会无条件把它提到同层最上面（`raiseWindow`），因此盖在面板上面。
  - 只改图层不接收键盘时，KWin 会把它放到活动窗口下面，仍在面板之下，这就是之前那次尝试失败的原因。
- **面板不动**：面板看不到“全屏应用”，不会滑走，只是被盖住；背景淡入时它们随之被遮住。
- **变形动画**：布局立即换成全屏；画面通过变换（平移、缩放、旋转），从浮窗的位置、大小和角度连续变到全屏，耗时 0.32 秒，OutCubic 缓动。背景同时淡入。
- **退出**：动画反着播放，结束时画面正好回到浮窗的位置，再切回 top 层、不再接收键盘。
- **细节**：变形开始时工具栏立即隐藏（否则会跟着画面一起转）；桌面模式全屏没有阴影，阴影改为淡出。
- **电脑上**：Esc 退出全屏。

**取舍**：
- 全屏期间 Plasma 的下拉和主页手势不可用，因为面板被盖住了；
- 退出全屏后，键盘焦点不会自动交还给之前的应用（KWin 没有这样做），要点一下应用才恢复。

### 17.3 与 APK 全屏逐项对齐（2026-10-02，用户指出漏了触控板切换）

**教训**：做 Linux 全屏时只移植了直接触摸，把 APK 全屏已有的触控板模式记成了“暂未移植”。用户发现工具栏上的切换没了。替换旧机制前，必须先把旧实现的功能逐项列出来再对照，见下表。

| APK AgentFullscreen 的功能 | Linux（`qml/FullTouch.qml`、`Main.qml`） |
|---|---|
| 工具栏：退出、缩放（导播台）、触控板开关、电视、关闭 | 相同；触控板开关选中时高亮 |
| 触控板模式（TouchpadGestures）：libinput 的轻点状态机——轻点单击、点两下双击、点后按住拖动（按过轻点时限也算拖动）、双指或三指轻点右键或中键、双指滚动 | 移植，状态和时限相同（轻点 180 ms，拖动等待 160 ms） |
| 指针加速（PointerTransfer）：libinput 触控板曲线（低于 7 mm/s 降到 1/3，7–130 mm/s 为 1:1，最高约 5.3 倍）；速度取最近 60 ms 的最小二乘直线，停顿超过 40 ms 截断；按辛普森法求平均 | 移植；单位由 `Screen.pixelDensity` 换成毫米 |
| 模式记在 `agent_fullscreen_touchpad` | 记在 `~/.config/rungic-agent-screenrc` 的 `[Fullscreen] touchpad` |
| 移动阈值 1.3 mm，按每根手指相对自己的按下点计算 | 相同（`TouchPoint.startX/startY`） |
| 长按时限等于 `ViewConfiguration.getLongPressTimeout()` | 400 ms（Android 12 起的默认值） |
| 点击按下后 40 ms 再抬起（面板的应用启动器认不出同一瞬间的按下和抬起） | 相同 |
| 双指滚动松手后惯性滚动（宿主的 scrollStop） | 在客户端实现：取最近 80 ms 的速度，每 16 ms 衰减到 94% |
| 从底边上滑呼出工具栏，3 秒后隐藏；底边的点按仍是点击 | 相同 |
| 导播台：点其他屏幕切焦点；看板在焦点时不转发触摸 | 相同 |
| 导播台：各屏幕的名字按电视样式画出（DirectorArt） | 浮窗格子自带的标签（非焦点格子的编号或角色、状态点、焦点的说明条） |

**新增**：
- 直接触摸模式下，点画面旁边可以显示或隐藏工具栏；
- 进入全屏后工具栏先显示 1 秒，再淡出并向底边滑出（用户要求，用来告诉用户工具栏在哪里）。

## 18. 边缘手势与安卓系统手势的冲突（2026-10-02，调研，尚未实机验证）

**用户要求**：边缘第一次滑动只交给 Linux（全屏工具栏、Plasma 的状态栏下拉、底部面板），安卓什么都不显示；1~2 秒内再滑一次，才交给安卓（返回、通知栏、回到主页）。

**源码调研结论**（AOSP android15/16-release、Launcher3 android16-release；Moto 的 SystemUI 和桌面是闭源的，都需要实机核对）：
- **系统怎么判断边缘滑动**：Rungic 用的是 `hide(systemBars())` 加 `BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE`。系统的 `SystemGesturesPointerEventListener` 只观察、不拦截：从边缘 24 dp 内开始、移动 24 dp 以上、500 ms 以内算一次边缘滑动。对这种设置的应用，系统只把系统栏临时显示出来，触摸并不交给状态栏。
- **第一次滑动**：
  - 底边：Launcher 判定“导航栏已隐藏且不允许忽略”，交给不拦截触摸的 `ResetGestureInputConsumer`，整段触摸都到应用；
  - 左右边：导航栏隐藏时返回手势被禁用（`isBackGestureDisabled`）；
  - 顶边：触摸也全部到应用。
  - 但系统栏会半透明地显示约 2.25 秒（`AutoHideControllerImpl`）；用户点了栏外区域则 350 ms 后隐藏。
- **第二次滑动（系统栏还在显示时）**：底边执行回主页手势；左右边执行返回（此时会无视应用设的排除区）；顶边拉出通知栏。
- **结论**：原生安卓本来就是“第一次给应用、第二次给系统”，只是第一次会把系统栏显示出来。
- **用户说的 (a)**：全屏里从“底部”，也就是手机左边缘，上滑就触发返回。按原生代码，系统栏隐藏时第一次不可能触发返回。可能的原因有三：那其实是第二次滑动；Moto 改了这部分；或者当时系统栏并没有隐藏（例如输入法或对话框让系统栏重新显示了）。
- **手势排除区**（`setSystemGestureExclusionRects`）：
  - 只能用于左右边；
  - 导航栏处于这种临时隐藏状态时，不受每条边 200 dp 的限制；
  - 系统栏显示期间排除区会被忽略；
  - 增删大约在下一帧生效。
  - 顶边和底边，应用无法排除。
- **有 root 时可选的手段**：
  - `IStatusBarService.disable/disable2`（root 可调用）或 `cmd statusbar send-disable-flag`：
    - 可以关掉通知栏下拉（`statusbar-expansion`），以及回主页加最近任务（必须 `home` 和 `recents` 都关）；
    - 还可以把系统栏内容清空（`system-icons`、`clock`、`notification-icons`）；
    - 关不掉系统栏的显示本身，也关不掉返回手势。
  - 用 `send-disable-flag` 设的状态挂在 system_server 的固定 token 上：应用崩溃后不会自动恢复，而且对全机生效。`disable` 则可以用我们应用的 Binder 作为 token，应用一死就自动解除。
- **排除掉的手段**：屏幕固定或锁定任务（太重，又不拦主页手势）；`policy_control`（Android 12 起已删除）；切换导航模式（全局生效，要几秒）；调试属性。
- **同类项目**：Termux:X11、Moonlight、bVNC 都只靠原生的沉浸模式，没有自己做“两段式”。

**拟定方案**（待用户确认、实机验证）：
- **不需要 root 的部分**：
  - 应用自己按系统同样的阈值识别边缘滑动。第一次交给 Linux，并打开约 1.5 秒的“交给安卓”窗口；窗口内的第二次交给安卓。
  - 左右边：沉浸状态下整条边都设为排除区，第二次滑动时由应用自己执行返回时的动作（左边打开菜单，右边发 Alt+Left）。
  - 剩下的问题：第一次滑动时半透明系统栏仍会闪现。
- **需要 root 的部分（可选，实现“第一次安卓什么都不显示”）**：
  - Rungic 在前台时，由常驻 root 助手用应用的 Binder 作为 token 调用 `disable`：清空系统栏内容，关掉回主页、最近任务和通知栏下拉；
  - 第一次滑动后立即解除，让第二次滑动生效；
  - 应用暂停、失去焦点或退出时一律恢复；应用一死，token 失效，自动解除。

**需要实机核对的项目**：
- Moto 上的侧边配置、各项阈值和自动隐藏时长（看 `dumpsys activity service com.android.systemui` 和桌面的 TouchInteractionService）；
- 每条边第一次滑动时，触摸实际交给了哪个窗口（`getevent` 加 `dumpsys input`）；
- root 标志的显示效果和切换延迟；
- 崩溃以后能否恢复；
- 输入法打开时、手机旋转后的表现。

## 19. 方案：桌面模式改为独立的 KWin（2026-10-03，用户决定，待确认细节）

**决定**：桌面模式不再是用户 KWin 里的第二块输出 CAST-n，改为和助理屏一样的独立 KWin。原因：
- 同一个 KWin 里的中转窗口会被 KWin 当作“别的应用”：一碰就关菜单（`PopupInputFilter::touchDown`）、抢走焦点；
- 独立的 KWin 天然没有这个问题，输入从外面送进去，和真鼠标、真副屏一样。

**现状**（梳理结果，详见当时的调查）：
- **桌面模式**：
  - APK 的 `desktop-mode` 让宿主给用户 KWin 一块 Cast 输出（`cast.rs` `sync_user_cast`）；
  - Plasma Mobile 的 external-screen 补丁在第二块屏上放一个桌面外壳（Folder View 桌面加任务栏）；
  - 浮窗和全屏用 `zkde_screencast` 录这块输出，用 fake input 送鼠标；
  - 电视的“电脑模式”就是呈现这块输出（来源 0）。
- **助理屏工作区**：
  - `kwin_wayland --virtual`（1920×1080，KGSL）；
  - 私有 D-Bus 和私有 `XDG_CONFIG_HOME`；
  - 里面只有壁纸（`rungic-workspace-desktop`），没有 plasmashell、通知、剪贴板同步和输入法；
  - 画面流带指针，输入走 fake input（只有鼠标，没有键盘）；电视通过呈现器。
- **依赖 CAST 的地方**：
  - `rungic_cua` 的 `desktop_in_use`、`launch` 的 CAST 前缀、`agent_output`；
  - `audio-follow` 按窗口是否在 CAST 上分配声音；
  - 验收里的 `desktop_mode_output`、提示词和技能文档；
  - §17 计划中“电视等于 CAST 输出加导播台窗口”这一点。

**拟定方案（分阶段）**：
1. **桌面实例**：
   - 新增一种独立的 KWin，例如 `rungic-desktop.service`。复用工作区的启动方式：virtual 后端、KGSL、私有总线，Wayland socket 为 `wayland-desktop`。
   - 里面运行完整的 Plasma 桌面外壳（plasmashell 的桌面版，带任务栏、通知、系统托盘）。
   - 用户配置与手机共享，桌面布局单独保存。
   - 生命周期随桌面模式开关，不会因闲置被关闭。
2. **浮窗和全屏**：
   - 改用工作区那种画面流（`rungic-workspace-stream` 的同一套）；
   - 触摸屏模式下画面不带光标，触控板模式下带系统光标；流的指针模式可切换，切换时不闪黑。
   - 输入从外面送进这个实例。
3. **键盘和输入法**：把安卓输入法的文字和按键送进桌面实例（经它的输入法或虚拟键盘接口）。助理屏以后也可以复用这条路。
4. **电视**：“电脑模式”改为呈现桌面实例，和工作区同一套呈现路径；导播台不变。§17 中“电视等于 CAST 输出”的设想相应修改。
5. **剪贴板和声音**：
   - 剪贴板在手机会话和桌面实例之间双向同步；
   - 声音沿用工作区的独立声道，桌面模式显示在哪里，声音就跟到哪里。
6. **应用**：
   - 在桌面实例里打开的应用就在桌面实例里运行；
   - 微信、Firefox 这类同时只能运行一份的应用，在两边之间切换时沿用 `switch.py` 的“关掉再在另一边打开”；
   - 手机上的应用不能再直接拖到桌面屏。
7. **收尾**：
   - 更新 `rungic_cua`、`audio-follow`、验收、提示词和文档；
   - Plasma Mobile 的 external-screen 补丁保留，供接真显示器或在电脑上使用；
   - Linux 全屏和光标的在途改动按新结构收拢；为 CAST 加的第二路录屏流不再需要。

**待用户确认**：剪贴板同步、应用规则、配置共享、电视电脑模式、生命周期（见当天对话）。

### 19.1 原型（2026-10-03，实机，用 9 号工作区临时验证）

**用户确认**：剪贴板双向同步；应用在哪个实例打开就在哪里运行，单实例应用用 switch.py 的方式在两边切换；应用配置共用，桌面布局单独保存；电视“电脑模式”投独立桌面；生命周期随桌面模式开关（关闭时请应用退出，有未保存内容则通知、不强关）。

**做法**：
- 在工作区 KWin 里启动 `plasmashell -p org.kde.plasma.desktop --no-respawn`；
- `XDG_CONFIG_HOME` 指向私有目录，里面链接用户 `~/.config` 的全部文件，只排除 `plasmashellrc`、`kwinrc`、`kwinoutputconfig.json`、`plasma-org.kde.plasma.desktop-appletsrc`、`plasma-mobile/`、`kdedefaults/`；
- `XDG_CONFIG_DIRS` 去掉 plasma-mobile 那一层；去掉 `PLASMA_DEFAULT_SHELL` 和 `PLASMA_PLATFORM`。

**为什么 plasmashell 必须用私有配置目录**：它的程序名在 `main.cpp` 的 `KAboutData` 里固定为 "plasmashell"，所以 `plasmashellrc`（面板尺寸、屏幕编号与接口的对应）和手机的移动版外壳是同一个文件，会互相覆盖。KWin 的 `kwinrc` 在 `main.cpp` 里同样写死了文件名。

**结果**：
- 完整的桌面起来了：开始菜单、固定的应用、图标任务管理器（Dolphin 运行时显示为活动）、托盘、时钟，壁纸和用户的相同。
- 私有总线按需拉起了：通知（plasmashell）、klipper、门户（kde、gtk、kwallet）、kded6、ActivityManager、kglobalaccel、ksecretd（密码库）、plasma-nm、bluez-obex、dconf、StatusNotifierWatcher 等。

**发现的问题**：
1. ~~窗口盖住任务栏~~：**不是问题**，是截图方式造成的假象。`rungic-cua screenshot` 默认只截活动窗口（`server.py` `screenshot(scope='window')`），再按整屏尺寸输出。用 KWin 脚本打印的窗口信息：
   - 任务栏是 dock，层级 3，位于 y=1018，高 62；
   - Dolphin 是普通窗口，层级 2，最大化后为 1920×1034；
   - 最大化可用区域给任务栏留出了底部。
2. **重复的会话服务共用同一份数据**：
   - ksecretd（密码库文件）有两个实例同时运行，有损坏数据的风险；
   - kactivitymanagerd 共用同一个数据库；
   - klipper 共用同一份历史文件；
   - kglobalaccel、plasma-nm 也各起了一份。
   - 需要逐项决定：转发到手机会话（密码库必须只有一个实例），还是给桌面实例单独一份（活动、klipper 历史），或者禁用。
3. 日志里 `org.kde.plasma.icontasks` 缺少 `ui/main.qml`，但任务栏能正常工作，待查原因。

### 19.2 0 号工作区：独立桌面（2026-10-03，实机验收）

**身份**：独立桌面就是工作区 0。宿主、APK 和导播台里，0 号本来就代表“电脑模式”；`rungic-workspace-env 0`、声音、无障碍总线等工具都能直接复用。

**和助理屏工作区的不同**（`rungic-workspace`，slot 0 分支）：
- 配置和数据：`XDG_CONFIG_HOME`、`XDG_DATA_HOME` 都是镜像目录（`rungic-desktop-dirs`）。
  - 里面每一项都是指向用户 `~/.config`、`~/.local/share` 的链接；
  - 例外是桌面独有的几项：KWin 和桌面外壳的状态（文件名写死，手机的 KWin 和 Plasma Mobile 也写同名文件）、全局快捷键、活动数据、kded、klipper 历史、kscreen，以及手机专用的 plasma-mobile 配置层。
  - `watch` 每 3 秒同步一次：桌面这边新建、并且已经放置 10 秒的文件挪回用户目录，再换成链接；手机那边新增或删除的文件，桌面这边跟着增删链接。
  - 实测 KConfig（`kwriteconfig6`）会顺着链接写，链接保留，写的就是用户的原文件。
  - `XDG_STATE_HOME`、`XDG_CACHE_HOME` 是桌面私有的。
- 去掉 `PLASMA_DEFAULT_SHELL`、`PLASMA_PLATFORM`，所以桌面里的程序按桌面形态运行。
- 桌面外壳：运行 `plasmashell -p org.kde.plasma.desktop`，退出后自动重启；不启用看守进程（不冻结，也不因闲置关闭）。
- 总线：`dbus/desktop.conf`。服务目录 `desktop-services` 排在最前，把 `org.freedesktop.secrets`、`org.kde.kwalletd6`、`org.kde.kwalletd5`、`org.kde.secretservicecompat` 和 kwallet 门户后端交给 `rungic-bus-forward`。
- `rungic-bus-forward`：在桌面总线上占住这些名字，每个调用原样转给用户总线上的同名服务（需要时由那边启动），回复、错误和信号原样转回。测试见 `tools/tests/test_bus_forward.py`：两条真实总线，覆盖调用、错误名和信息、自省、信号。
- RemoteSurface 屏幕登记：`ws-0`，名称 "Computer desktop"，类型 desktop。

**实机验收**（G100 S，0 号以无头方式运行，不显示在手机上）：
- 单元处于 active；plasmashell 在运行；截图里有完整的桌面（任务栏、开始菜单、固定应用、托盘、时钟、用户壁纸）。
- 在桌面总线和手机总线上查询 `org.freedesktop.Secret.Service.Collections`，结果相同；桌面那边占用该名字的是 `rungic-bus-forward`；整台手机只有 1 个 ksecretd。
- 活动数据库在桌面私有目录；`kdeglobals` 链接到用户文件；`kwinrc` 是桌面私有的。
- 停止单元后，相关进程全部退出。
- 内存：0 号运行时手机可用内存约 2.5 GB。

**下一步**：
- 剪贴板双向同步；
- 键盘和输入法；
- 把桌面模式的开关、浮窗、全屏接到 0 号，按规则处理光标；
- 电视的电脑模式改投 0 号；
- 声音跟随，以及适配看守进程；
- 更新 `rungic_cua` 等依赖。

### 19.3 剪贴板（2026-10-03，实机验收）

- 0 号里运行一份 `rungic-clipboard`（和手机会话里的是同一个程序，每个显示一份），形成“手机会话 ⇄ 安卓剪贴板 ⇄ 独立桌面”：手机、安卓应用、桌面三边互通。
- 启动时以安卓剪贴板的当前内容为准；退出后自动重启。
- **实测**：
  - 手机上 `wl-copy` 复制，桌面里 `wl-paste` 读到相同内容；反过来也一样。
  - 测试前把用户的剪贴板存在手机上，结束后恢复；只检查了“不是测试字符串”，没有读取内容。
  - 第一次测试时，后台运行的 `wl-copy` 继承了输出管道，远程命令一直等它结束，导致超时；`wl-copy` 的输出要重定向。

### 19.4 桌面模式接到 0 号，以及键盘（2026-10-03，已部署，待用户实测）

**命令行（`rungic-desktop-mode`）**：
- `on`：启动 `rungic-workspace@0` 并打开浮窗。如果 APK 里还留着旧的桌面模式开关，顺手关掉，宿主就不再生成 CAST 输出。
- `off`、`close`、浮窗的关闭按钮：`rungic-cua close-workspace 0`，先请应用退出；如果有应用因未保存内容没有关掉，就发通知（查看 / 不保存直接关闭），不强行关闭。
- `toggle`、`ensure`、`status`：以 0 号是否在运行为准；是否在电视上，仍取 APK 的状态。

**浮窗（AgentScreen）**：
- 0 号也走工作区画面流（`rungic-workspace-stream --pointer-hidden`），主画面不带指针。
- 全屏触控板模式下，画面流程序按 `pointer-stream on` 另建一路带指针的画面（`pointer-node N`），叠在主画面上。
- 原来专门为 CAST 写的录屏、模拟输入、错位修正和按观看节流的代码全部删除。

**键盘（第一版：手动）**：
- 全屏工具栏新增键盘按钮，点了弹出安卓输入法，再点收起。
- 浮窗里有一个看不见的输入框接收输入：提交的文字经画面流程序的 `text` 命令，用 KWin 的 `VirtualKeyboard.commitText` 送进对应屏幕获得焦点的输入框，中文也行；退格（输入框为空时）、回车、Tab、Esc、方向键、Delete、Home、End、翻页，经 `key` 命令作为真实按键送进去。
- 助理屏的全屏同样可用。
- **以后再做**：在桌面里点中输入框时自动弹出键盘，需要一个小 KWin 补丁来报告“有输入框被点中”。
- 以前的桌面模式也不会在桌面屏的输入框上自动弹出键盘（`textInputOnExternalOutput`），所以第一版没有丢掉旧行为。

**暂未处理**：
- 电视的电脑模式仍然投 CAST，下一步改投 0 号；
- 声音跟随、看守进程对 0 号的处理；
- Agent 工具里以 CAST 为目标的逻辑。

**实机验收**（2026-10-03 00:07–00:26，G100 S，用户同意后进行）：
- **切换**：`rungic-desktop-mode on` 后，KWin 只剩 WL-0（kded 弹出一次“Display Removed”，来自旧 CAST 断开）；浮窗显示 0 号桌面，画面里没有光标。
- **全屏**：画面铺满并转成横向；工具栏先显示（退出、触控板（按用户设置高亮）、键盘、电视、关闭），随后自动隐藏。
- **触控板模式**：显示 KWin 自己画的系统光标，跟着手指移动。
  - 修复一：带指针的那路画面原来“ready 之后才可见”。但 KPipeWire 只在可见时接收数据，两边互相等待，那路流一直处于 suspended。改为一直可见，ready 之前透明度为 0。
- **底边上滑呼出工具栏**：
  - 修复二：从底边起手的触摸要先压住，直到走出 3.2 mm 再判断（APK 的 stripDecided）。移植时漏了这一步，结果手指刚动 1.3 mm 就被当成移动，永远等不到判断。
  - 起点落在安卓 24dp 的边缘区内（x=15 像素）时，安卓的系统栏会闪出来，触摸则被当成触控板移动；从边缘区之外、我们的条带之内起手，工具栏正常出现。
- **触摸屏模式**：没有光标。
  - 点任务栏的开始按钮，开始菜单打开；打开期间上滑呼出工具栏、点键盘按钮，菜单都不会关闭。
  - 点菜单里的 Dolphin，Dolphin 正常启动。之前“一碰菜单就消失”的问题不再出现。
  - 长按文件夹弹出右键菜单，点菜单外面菜单关闭。
- **键盘**：点键盘按钮后，用 `adb input text` 打出的 “dolphin” 进入了开始菜单的搜索框。
  - **未解决**：安卓输入法没有真正弹出来（`dumpsys input_method` 显示 `mInputShown=false`）。adb 的输入是直接按键，绕过了输入法，所以真实打字时能否弹出键盘还要再查。
- **收尾**：用户的触控板设置恢复为 true；测试打开的 Dolphin 已关闭；息屏时间改回 60 秒。

### 19.5 键盘被压住：输入法面板在 overlay 层最上面（2026-10-03）

- **现象**：全屏时点键盘按钮，KWin 的 `VirtualKeyboard` 报告 `active=true`、`visible=true`，plasma-keyboard 也在运行，但屏幕上看不到键盘。
- **说明**：手机上随文本框弹出的是 Linux 这边的屏幕键盘（plasma-keyboard，带 Rime）；安卓键盘要从 Rungic 菜单的“Android 键盘”切换。所以 `dumpsys input_method` 的 `mInputShown=false` 本身不说明问题。
- **原因**：输入法面板在 KWin 里属于 OverlayLayer（`Window::belongsToLayer` 中 `isInputMethod()`），和我们的全屏窗口同一层。全屏窗口是之后才被激活、提上来的，于是盖住了键盘。
- **修法**：KWin 补丁 `input-panel-above-overlay.patch`。在 `Workspace::constrainedStackingOrder` 里，把 OverlayLayer 中的输入法窗口排到这一层的最后（`std::stable_partition`）。需要重启用户会话的 KWin 才生效。

### 19.6 电视的电脑模式和声音（2026-10-03，已实现，待电视实测）

**电视**（只改 Linux，与 §17 的方向一致）：
- 电视投电脑模式时，宿主照旧在用户 KWin 里建出 CAST 输出，并零拷贝投到电视（`sync_user_cast`，来源 0）。
- 桌面模式的浮窗进程在 CAST 上放一个 overlay 层的图层窗口（`Floater::placeOnCast`，作用域 `rungic-agent-screen-tv`），显示 0 号的画面，盖住 Plasma Mobile 放在那里的桌面外壳。
- 投屏控制面板的触控板，经宿主落到 CAST 上，成为这个窗口收到的鼠标移动、按键和滚轮，再按比例转进 0 号（一格滚轮 120 = 15 个轴单位）。
- 键盘模式经 HostTextInput 提交的文字，由窗口里一个获得焦点的输入框接收，再经 `typeText`、`key` 转进 0 号。
- 电视上看到的光标是用户 KWin 自己的，位置和 0 号的指针一一对应；0 号的画面不带指针，所以不会出现两个光标。
- 桌面模式在电视上时，0 号的画面流继续运行，浮窗隐藏（状态为 tv）。

**声音**：
- 0 号启动后回环一直开着（`rungic-workspace-sound 0 listen`）：桌面开着就该听得到，不靠看守进程判断。
- `audio-follow`：投屏时，电视在电脑模式（`content == 'desktop'`）就把 0 号的回环送去电视，否则留在手机。测试见 `test_audio_follow.py`。

### 19.7 Agent 工具（2026-10-03）

- `router.desktop_in_use()`：0 号在运行，或电视在投电脑模式，就在“用户的桌面”上工作。
- 目标 `desktop` 的子进程改为在 0 号的环境里运行（`workspace_env(env, 0)`）；桌面模式没开时，先执行 `rungic-desktop-mode on`。`desktop_where` 返回 `workspace: 0`，以及 `rungic-workspace-env 0 COMMAND`。
- 0 号里需要显示画面时，执行 `rungic-desktop-mode ensure`，而不是打开助理屏。
- 发语音消息时，要求活动窗口在 Agent 当前工作的那块输出上，不再要求它在 CAST 上（以前在工作区里会误报）。
- 提示词（`agent.md`）和技能 `rungic-phone-desktop` 都按新的桌面模式更新。
- `test_router.py` 按新模型改写。
