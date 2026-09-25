# KWin + 原生Vulkan收益量化

2026-09-24。XT2537-4 / Adreno710 / Android16 / Ubuntu26.04，KWin 6.6.6+moto7（GLES/freedreno），Turnip Mesa26.3.0-devel，APK1.9，原生1080×2400、KDE缩放3。用户要求量化KWin改用原生Vulkan合成能带来的收益，可先单独写Vulkan合成器测试。本篇给出实测数据和据此的估算；**没有实现Vulkan版KWin**，估算部分会明确标注。

## 结论

1. **原生Vulkan在合成器层面只节省CPU，不节省GPU，也不缩短帧延迟。** 在与KWin完全相同的Android输出路径上，同一场景用GLES和Vulkan渲染，每帧GPU执行时间相同（差异<2%，在轮次波动内）；进程CPU稳定降低33–37%，折合每帧约0.7ms。
2. **KWin目前一帧的瓶颈不是API。** 真实桌面滚动时，KWin Paint p50 7.0ms，其中4.5ms是`glFinish`等待（GpuWait），只有约2.5ms是KWin自己的CPU工作；整个GPU只有11%忙碌。等待时间由GPU频率策略和同步方式决定，Vulkan不改变这两点。
3. **估算：** KWin改为原生Vulkan，每帧约省0.7–1.5ms CPU（KWin每帧绘制调用多于原型，按比例放大；属于估算），滚动时约为单核3–6%（KWin当前约21%）。GPU时间、`GpuWait`、呈现间隔预计不变。维护KWin Vulkan分支（ItemRenderer、特效、Qt Quick互操作、录屏，见51篇）的成本不值得这个收益，**当前不建议为性能fork KWin做原生Vulkan**。
4. 只把plasmashell（Qt Quick）切到Vulkan：plasmashell CPU从34.9%降到18.0%，但其GPU提交合并为大块，KWin同步等待变长，SurfaceFlinger帧间隔p95从16.7ms劣化到33.4ms，不应启用。
5. 同一批数据中出现了更大的可改进项（按量级排序，均未实施）：宿主APK每帧CPU 5–8ms（原型场景中占47–66%单核），GPU频率在中等负载下停在最低档295MHz，宿主帧回调与合成串行导致40fps节拍，输出缓冲强制为线性无压缩布局。详见“更大的瓶颈”。

## 方法

### A. 真实桌面分段（moto7 FTrace + KGSL）

`tools/kwin_pipeline_run.py`：从主屏打开应用抽屉，关闭无障碍，Android热状态为0时开始，每轮10秒内8次滑动，取第1.5–10秒。perfetto记录KWin标记（Paint、GpuWait=`glFinish`、Import）、宿主外层`queueBuffer`、SurfaceFlinger帧、各进程CPU；tracefs实例记录KGSL提交。3轮取中位数。追踪基础设施见55篇P2。

### B. 独立合成原型 compbench

`plasma/bench/compbench/`（C，MIT）。与KWin的Wayland后端一样：连接Android宿主Wayland服务，从宿主分配器租用线性XRGB8888 AHardwareBuffer，渲染后经linux-dmabuf提交；GLES路径与KWin相同（`/dev/kgsl-3d0`上的GBM、`EGL_PLATFORM_GBM_KHR`、dma-buf EGLImage）；Vulkan路径在Turnip上以`VK_EXT_image_drm_format_modifier`导入同一dma-buf，动态渲染，队列族所有权交给`FOREIGN`。两者着色器逻辑、场景、缓冲数完全相同，只换渲染API与完成等待方式：

- `finish`：GLES `glFinish` / Vulkan `vkQueueWaitIdle`，即KWin目前的做法；
- `fence`：GLES `EGL_ANDROID_native_fence_sync`后poll sync_file / Vulkan等待本帧fence，只等本帧，不清空管线。

场景：不透明壁纸 + N个带alpha的近全屏窗口层，每帧移动（全屏重绘，相当于KWin滚动/动画时）。`tools/compbench_run.py`停止Plasma会话，使宿主只服务原型；变体按ABBA交错，每变体3轮（预热3秒、测12秒），每轮前等待热状态为0，每轮同时录制perfetto+KGSL，结束后恢复会话。宿主分配器与KWin相同，未修改宿主。

在mesa/Turnip之外还核对了现成方案：wlroots有成熟的Vulkan渲染器，同一合成器可切换GLES/Vulkan，但两种渲染器都需要从DRM设备取得GPU（`VK_EXT_physical_device_drm`、GBM/EGL device），KGSL不是DRM设备；KWin为此另有AHB分配补丁。因此没有采用wlroots，而是写只替换渲染API的最小原型。

## 结果

### A. 真实桌面（3轮中位数，热状态前后均为0）

| 指标 | 值 |
|---|---:|
| KWin Paint p50 / p95 | 7.00 / 11.86 ms |
| 其中 GpuWait（`glFinish`）p50 / p95 | 4.46 / 8.96 ms |
| Import（dma-buf导入与提交）p50 | 0.05 ms |
| KWin每轮绘制帧数（8.5秒） | 352（约41帧/秒） |
| 宿主提交缓冲 / 秒；相邻间隔 p50 / p95 | 47.8；8.59 / 19.1 ms |
| 宿主`queueBuffer` p50 | 0.38 ms |
| SurfaceFlinger显示帧间隔 p95 | 16.7 ms |
| CPU（单核%）KWin / plasmashell / 宿主APK / SurfaceFlinger | 21.2 / 34.1 / 23.2 / 30.5 |
| GPU忙碌（所有提交的并集） | 11.1% |
| GPU频率时间分布 | 最低两档295/345MHz约占35–45%，最高816MHz约占30–40% |

GPU只有11%忙碌，而KWin每帧仍在`glFinish`上等4.5ms：GPU多数时间空闲、频率降到低档，同步等待被拉长。注意各进程的KGSL“start→retire”区间之和大于并集忙碌时间，说明区间包含与其他上下文的重叠/抢占，只能作相对比较，不能当作独占GPU时间。

### B. 原型：GLES对Vulkan（各3轮中位数）

| 场景 | 帧率 GLES / Vulkan | 进程CPU单核% | 每帧CPU ms | 每帧GPU（KGSL）ms | GPU频率 |
|---|---|---|---|---|---|
| 3层，宿主节拍，`finish` | 40.0 / 40.1 | 8.96 → 5.92 | 2.24 → 1.48 | 9.53 / 9.63 | 全程295MHz |
| 3层，宿主节拍，`fence` | 39.9 / 40.0 | 8.73 → 5.78 | 2.19 → 1.45 | 9.66 / 9.64 | 全程295MHz |
| 3层，不节流，`fence` | 120.8 / 125.6 | 20.64 → 13.08 | 1.71 → 1.04 | 6.12 / 6.08 | 全程816MHz |
| 1层，宿主节拍，`fence` | 59.6 / 59.7 | 12.22 → 8.07 | 2.05 → 1.35 | 4.33 / 4.30 | 全程295MHz |

- 每帧GPU时间两种API相同；每帧CPU稳定少0.67–0.78ms（−33%到−37%）。与51篇Qt Quick客户端的结论一致（Vulkan每帧CPU降低20–32%，帧率区间重叠）。
- `glFinish`比只等本帧fence多约1.2ms（10.52对9.29ms）；Vulkan两种等待几乎相同。KWin改用fence等待即可拿到这部分，与API无关。
- 不节流时GPU升到816MHz，但时钟提高2.77倍、每帧GPU时间只缩短1.57倍（9.6→6.1ms）：3层全屏线性缓冲的场景受内存带宽限制。
- 帧率被宿主节拍限制在40fps（3层）或60fps（1层），与API无关，见下节。

### C. 只把plasmashell的Qt Quick切到Vulkan

KWin保持GLES，plasmashell经运行时drop-in设置`QSG_RHI_BACKEND=vulkan`，从进程映射确认加载`libvulkan_freedreno.so`，测完删除drop-in并确认恢复GL。紧接着用默认GL同条件复测3轮对照（各轮热状态为0）。

| 3轮中位数 | plasmashell GL | plasmashell Vulkan |
|---|---:|---:|
| plasmashell CPU（单核%） | 34.9 | **18.0** |
| plasmashell每次GPU提交（KGSL区间均值） | 2.5 ms | 8.7 ms |
| KWin GpuWait p50 / p95 | 4.34 / 8.97 ms | **6.43 / 10.62 ms** |
| KWin Paint p50 | 6.93 ms | 8.96 ms |
| 宿主缓冲/秒；间隔p50 | 50.8；8.7 ms | 43.4；10.8 ms |
| SurfaceFlinger显示帧间隔 p95 | 16.7 ms | **33.4 ms** |

plasmashell的CPU减半，但它把一帧合并成约8.7ms的大GPU提交；KWin的`glFinish`排在其后，合成等待变长，整体呈现反而变差（第3轮宿主一度只有16.9缓冲/秒）。这再次说明瓶颈在GPU调度与同步，而不在渲染API；也说明不能只看单个进程的CPU下降就全局切换RHI。51篇没有全局修改应用RHI的决定维持不变。

## KWin原生Vulkan的估算

| 部分 | 当前（真实桌面） | Vulkan预期 | 依据 |
|---|---|---|---|
| KWin自身CPU（Paint−GpuWait−Import） | 约2.5ms/帧 | 约减少0.7–1.5ms/帧 | 原型每帧省0.7ms（2–4次绘制）；KWin每帧绘制项更多，按比例放大为上限估算 |
| KWin进程CPU | 21.2%单核 | 约15–18% | 41帧/秒×上行节省；估算 |
| KWin的GPU执行 | 与原型同类工作 | 不变 | 原型四组GPU时间差异<2% |
| GpuWait（同步等待） | 4.5ms/帧 | 不变 | 由GPU频率和同步方式决定；fence等待可省约1.2ms，GLES也能做到 |
| 呈现间隔 / 帧延迟 | 宿主节拍决定 | 不变 | 原型GLES/Vulkan帧率与间隔相同 |

以上为估算，没有实现Vulkan版KWin。完整实现的工作范围（ItemRenderer、GL特效与着色器、Qt Quick纹理互操作、颜色管理、录屏）见51篇；51篇2026-09-23核对的上游KWin主线（a5a83437）仍以OpenGL为唯一GPU场景渲染器。

## 更大的瓶颈（实测，均未实施）

1. **宿主APK的CPU开销**：原型运行时宿主APK占47.7%（60fps）到65%（120fps）单核，即每帧5–8ms CPU，是KWin改Vulkan所省CPU的约10倍；SurfaceFlinger另占约39%。宿主每帧用GLES把KWin输出全屏重绘一次（含BGR交换）再`eglSwapBuffers`。候选方案：用Android `ASurfaceTransaction_setBuffer`把KWin的AHardwareBuffer直接交给SurfaceFlinger（零拷贝，可带acquire fence），同时去掉宿主GPU合成；颜色通道顺序改由分配正确格式解决。需要验证触摸坐标、旋转、光标层与HWC合成。
2. **GPU频率策略**：宿主节拍下GPU全程停在最低295MHz（忙碌36–46%，未达升频门限），不节流时全程816MHz。真实桌面中频率在两端来回。`glFinish`的4.5ms很大程度来自低频下的串行等待。候选：宿主渲染线程使用Android性能提示（ADPF `PerformanceHintManager`）报告目标帧时长，研究KGSL/Moto的GPU升频提示；不锁频、不改温控（沿用49、51篇边界）。
3. **宿主帧回调串行**：宿主在呈现后才发帧回调，客户端收到后才开始渲染，宿主再等下一个Choreographer vsync合成。原型中3层场景因此只有40fps（120Hz的1/3），1层60fps。候选：按vsync预测提前发帧回调（与KWin的渲染时刻预测配合），并在宿主支持显式同步后让客户端不必在CPU上等待GPU。
4. **线性缓冲**：分配器用CPU读写用途（0x333）强制线性无压缩布局。带宽受限的现象（上节2.77倍时钟只换来1.57倍速度）表明UBWC压缩/分块布局值得评估；需要双方支持对应modifier，且不能破坏CPU读回的录屏路径。
5. **同步方式**：KWin在`glFinish`上阻塞渲染线程。改为导出sync_file等待本帧即可省约1.2ms（原型实测），若宿主接受acquire fence，KWin线程可完全不等。

这些都位于宿主、分配器与KWin输出边界，属于共享层修改，GLES和将来的Vulkan都会受益，符合AGENTS.md“优先修复共享系统能力”的要求。

## 局限

- 原型场景是KWin工作的代理：全屏纹理层混合，没有KWin的窗口装饰、阴影、模糊等特效；特效较重时GPU占比会变化，但本数据中两种API的GPU时间相同，结论方向不受影响。
- 原型运行时停止了Plasma会话，GPU上没有其他进程竞争；真实桌面中`GpuWait`还包含排在其他进程之后的时间。
- 不锁频、不改温控和调度；频率由Android决定并被记录。每轮前后热状态均为0。
- 真实桌面数据使用Android input滑动，为51篇场景的同类手势，不是逐帧相同的回放。

## 数据与复现

精简结果（各轮JSON、汇总、会话元数据）在`benchmarks/kwin-vulkan-20260923/`；完整perfetto与KGSL追踪较大，保存在`.work/refs/kwin-vulkan-20260923/`及`.work/diag/`，清单与SHA256见基准目录。

```sh
source tools/work-env.sh
uv run --script tools/kwin_pipeline_run.py .work/refs/NEW/pipeline
uv run --script tools/compbench_run.py .work/refs/NEW/l3 --variant gles:finish --variant vulkan:finish --variant gles:fence --variant vulkan:fence --layers 3
uv run --script tools/compbench_run.py .work/refs/NEW/l3u --variant gles:fence --variant vulkan:fence --layers 3 --unthrottled
uv run --script tools/compbench_run.py .work/refs/NEW/l1 --variant gles:fence --variant vulkan:fence --layers 1
```

原型需先在容器内构建并安装为`/usr/local/bin/moto-compbench`（`plasma/bench/compbench/build.sh`）。

后续：第1、5项（宿主零拷贝与fence同步）已实施，KWin每帧阻塞约降70%，见[57篇](57-zero-copy-explicit-sync.md)。

## 复测：Qt 应用改用 Vulkan（2026-09-26）

当年只把 plasmashell 切到 Vulkan 时，SurfaceFlinger 帧间隔 p95 从 16.7 ms 劣化到 33.4 ms，原因是 KWin 的 `glFinish` 排在 plasmashell 的大块 GPU 提交之后。57 篇把 KWin 改为 fence 等待、宿主改为零拷贝以后，这个前提已经变了，所以重测。

- **方法**：
  - 语音助手：两种后端交替启动（OpenGL、Vulkan、Vulkan、OpenGL），每次启动先等 25 秒，让 Codex 在后台恢复完线程（57 篇），然后连测 3 轮。每轮是同样的三次滑动，记录宿主零拷贝层的 `SurfaceFlinger --latency`（每轮约 126 个显示间隔中间隔超过 10 ms 的数量）和 App 进程 CPU。`QSG_INFO` 确认 Vulkan 实例用的是 Turnip Adreno 710。
  - plasmashell：用临时 drop-in 设置 `QSG_RHI_BACKEND`，按同样的顺序重启 plasmashell，在应用抽屉里滑动；通过 `/proc/PID/maps` 里是否有 `libvulkan_freedreno` 确认后端。
- **结果**（6 轮）：

  | 对象 | 迟到数（中位数） | p95 | 进程 CPU（单核，中位数） |
  |---|---|---|---|
  | 语音助手 OpenGL | 26、8、8、7、4、4（7.5） | — | 61.6% |
  | 语音助手 Vulkan | 5、14、0、9、9、8（8.5） | — | 37.6% |
  | plasmashell OpenGL，抽屉 | 8、6、19、20、28、5（13.5） | 16.7 ms | 21.5% |
  | plasmashell Vulkan，抽屉 | 21、16、27、4、21、22（21） | 16.7 ms | 16.7% |

  - 语音助手的 RSS：Vulkan 118.8 MB，OpenGL 127.3 MB；Vulkan 下自定义着色器（光效）渲染正常。
- **结论**：
  - 当年 plasmashell 的 p95 劣化已经不再出现。
  - 语音助手改用 Vulkan，出帧节奏不变，CPU 约少 40%。
  - plasmashell 改用 Vulkan，CPU 少约 22%，但迟到数的中位数偏差（区间重叠），继续使用 OpenGL。
  - 全局切换需要更多应用的对照，本轮不做。
- **测量过程中的事故**：前一次重启会话时，旧 plasmashell 在退出途中崩溃（SEGV），之后没有被重新拉起，约 20 分钟里没有状态栏和导航栏。第一轮语音助手对照就是在这种状态下测的，已作废并重测（上表是重测结果）。另外，plasmashell 重启后要等前台窗口下一次被激活，才能重新拿到应用配色（59 篇），这个问题待改进。

### 全局切换（2026-09-26，用户决定）

看过上面的数据后，用户决定所有 Qt Quick 应用都改用 Vulkan。`plasma/gpu-env` 由 `QSG_RHI_BACKEND=opengl` 改为 `vulkan`，经会话脚本导入整个会话。

- **验证**（重启会话后查 `/proc/PID/maps`）：plasmashell、语音助手 App、`plasma-settings` 都加载了 `libvulkan_freedreno`；语音浮层要等首次显示才创建渲染器，唤出后也是 Vulkan，光效渲染正常。重启后 plasmashell、语音浮层和语音服务都在运行。
- **不在范围内**：
  - KWin 仍用 OpenGL ES（`KWIN_COMPOSE=O2ES`）：它没有 Vulkan 渲染器，经 Zink 实测更差（51 篇）。
  - Firefox 156：WebRender 在 Linux 上只有 OpenGL（EGL）和软件两条路径，`libxul.so` 和默认配置里都没有 Vulkan 的合成选项。可行的只有经 Zink 把 GL 翻译成 Vulkan，而这条路在 KWin 上实测更慢，不采用。
  - GTK4（4.22）支持 `GSK_RENDERER=vulkan`，但本轮没有测，仍为 `gl`。
- **回退**：把 `gpu-env` 改回 `opengl` 并重启会话。
