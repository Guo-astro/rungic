# 零拷贝呈现与显式同步

2026-09-24。XT2537-4 / Android16 / APK1.10–1.22 / KWin 6.6.6+moto8。56篇的量化结论是：KWin改原生Vulkan只省CPU，更大的开销在宿主GLES合成和`glFinish`同步等待。本篇实施了其中两项共享层改动，并做同机A/B。

## 结论

| 3轮中位数，抽屉滚动，热状态0 | 原来 | 零拷贝 | **零拷贝 + fence** |
|---|---:|---:|---:|
| KWin Paint p50 / p95 | 6.74 / 12.00 ms | 7.16 / 13.86 ms | **2.05 / 3.87 ms**（复测2.03 / 3.91） |
| KWin `glFinish`等待 p50 | 4.27 ms | 4.39 ms | **无** |
| 宿主APK CPU（单核%） | 22.6 | 15.4 | **15.4–16.3** |
| 宿主GPU时间（8.5秒） | 481 ms | 0 | **0** |
| KWin / SurfaceFlinger CPU | 21.4 / 27.0 | 18.9 / 25.3 | 18.6–19.5 / 25.3–25.5 |
| KWin每轮绘制帧数 | 355 | 338 | 362–370 |
| SurfaceFlinger帧间隔 p95 | 16.7 ms | 16.8 ms | 16.8 ms |

- 零拷贝：宿主不再每帧用GLES全屏重绘一次（含BGR交换和它自己的`glFinish`），宿主GPU工作归零、APK CPU降约30%。SurfaceFlinger把这一层交给硬件合成（`dumpsys SurfaceFlinger`中`composition=DEVICE`），没有转成GPU合成。
- fence：KWin不再在`glFinish`上阻塞，每帧阻塞时间降约70%，缓冲约提前4.7ms交给Android。
- 两者必须同时开。只开fence、零拷贝关闭时，宿主要先在CPU上等fence再做GLES，SurfaceFlinger帧间隔p95劣化到25ms。
- 只开零拷贝时KWin Paint略变差（+0.4ms）：宿主GPU工作消失后，GPU停在低频档的时间从33–38%升到41–47%，平均频率约从630降到约550MHz，KWin自己的GPU工作变慢。GPU频率策略（见56篇）因此更重要。
- 显示节拍（SurfaceFlinger p95 16.7ms）不变，受宿主帧回调与呈现反馈影响，另行处理。

## 零拷贝

`native/plasma/src/android/surface_control.rs`：

- 从SurfaceView窗口创建子`ASurfaceControl`。帧内只有一个位于(0,0)、非光标、能在分配器中查到租约AHB的dma-buf（KWin输出）时，用`ASurfaceTransaction_setBufferWithRelease`（API36，dlsym）提交该AHB，设OPAQUE、SRGB、整幅damage；其余情况隐藏子层，回退原GLES合成。
- 释放：每个提交的缓冲持有Smithay `Buffer`（其最后一个引用释放时才发`wl_buffer.release`）和AHB引用。SurfaceFlinger的释放回调在binder线程发生，经通道回到合成线程；release fence signal后才放掉持有，KWin此时才能复用该缓冲。
- 分配usage由0x333改为0xB33，加`AHARDWAREBUFFER_USAGE_COMPOSER_OVERLAY`：NDK头文件说明直接用`setBuffer`的缓冲必须带这一位（框架只给自己分配的缓冲加）。
- 调研与坑点来自AOSP `surface_control.h`、Chromium `android_surface_control_compat.cc`/`gl_surface_egl_surface_control.cc`、Lindroid `ComposerImpl.cpp`（最接近的同类项目，未跟踪逐缓冲release，没有照搬）、高通参考gralloc/HWC。Termux:X11和Winlator仍是GLES绘制，不是零拷贝。
- 运行时开关：`setprop debug.moto.zerocopy 0`；`native-stats`显示零拷贝帧数、acquire fence数、回退次数与原因、在途缓冲数。
- 顺带修复：触屏模式下不再绘制回退光标（左上角箭头，55篇P1记录）；每帧的dma-buf info日志降为debug。

## 显式同步（sync_file）

KGSL不是DRM设备，linux-drm-syncobj-v1不可用。改用基于sync_file的`zwp_linux_explicit_synchronization_v1`（wayland-protocols unstable，仍在维护列表，Smithay与KWin客户端都未实现，本次两端各自实现）：

- KWin（moto8，`wayland_egl_backend.cpp`）：有该全局且处于Android flat-output模式时，用`EGL_ANDROID_native_fence_sync`导出本帧GPU完成fence，经`set_acquire_fence`随同一次commit发出，不再调用`glFinish`。`MOTO_KWIN_EXPLICIT_SYNC=-1`恢复旧路径。释放继续用`wl_buffer.release`（宿主在SurfaceFlinger释放后才发）。
- 宿主（`backend/wayland/explicit_sync.rs`）：acquire fence与release对象都是按commit双缓冲的表面状态。零拷贝把fence dup后交给SurfaceFlinger作为acquire fence；GLES回退路径在采样前等待（最多1秒）。`get_release`对象在该commit最后一个引用释放时发`immediate_release`，与`wl_buffer.release`同一时刻。
- 风险：同一App进程的所有SurfaceControl事务按FIFO排队，未signal的acquire fence会阻塞后续事务（AOSP `TransactionHandler`）。容器GPU挂死时宿主显示会一起停住；这与原来KWin在`glFinish`上挂住的后果相同。

## 事故：BGRA缓冲使SurfaceFlinger崩溃（已修复）

2026-09-24 01:08，APK1.11运行零拷贝时SurfaceFlinger在RenderEngine线程abort（tombstone_28）：`Unable to generate SkImage ... GrGLTextureInfo fTarget 36197 fFormat 32856 (GL_RGBA8) colorType 6 (kBGRA_8888)`。随后system_server、相机与指纹HAL相继退出，Android用户空间重启，无线调试与VPN（Swift wire）随之断开。

- 原因：KWin选择DRM `XR24`，分配器映射为HAL私有格式BGRA_8888（5）。该层平时由HWC overlay合成（`composition=DEVICE`）；一旦SurfaceFlinger必须用GPU合成它（转场、任务快照等），Skia对BGRA颜色类型与RGBA8纹理的组合无法创建图像而abort。截图路径恰好没有触发，所以此前的截屏验证没有发现。
- 修复（APK1.14起）：宿主dma-buf只通告`XBGR8888/ABGR8888`，分配器只接受这两种并映射为公开的`AHARDWAREBUFFER_FORMAT_R8G8B8A8`，拒绝BGRA。KWin随即改用`AB24`。compbench同步改为`XB24`。
- 验证：`service call SurfaceFlinger 1008 i32 1`关闭硬件overlay、强制该层走GPU合成（`composition=CLIENT`），滑动与截屏期间SurfaceFlinger与system_server进程号不变，画面颜色正确，随后恢复overlay。
- 教训：零拷贝层必须同时通过HWC与GPU（CLIENT）两条合成路径的验收；缓冲格式只用Android公开的AHB格式。

## 呈现反馈（第2项）：实测后默认关闭

APK1.12–1.18给零拷贝事务设`setOnComplete`，用present fence实际signal时间（`SYNC_IOC_FILE_INFO`）或latch时间报告`wp_presentation_feedback`。结果：

1. 冻结：一次无效时间（`getLatchTime()`返回负数被当作无符号数）使KWin把渲染安全余量算成极大值，桌面停止更新（时钟停住，KWin主线程在poll中空闲）。修复：只接受`[now-1s, now+5ms]`内的时间；任何反馈最迟60ms必定送出；零拷贝关闭或隐藏时立即送出全部挂起反馈。
2. 即使时间正确，KWin也变慢：KWin以“呈现时间−帧回调时间”作为安全余量提前开始渲染。真实时间包含1–2个vsync的显示流水线，余量增至约20ms以上，KWin每轮绘制帧数从约370降到106，SurfaceFlinger帧间隔p95升至50ms。
3. 结论：默认恢复“提交后立即报告”（APK1.19+），真实时间保留在`setprop debug.moto.present_feedback hw`下，且只有打开时才注册完成回调（每帧少一次binder往返）。要利用真实时间，需要同时修改KWin嵌套后端的余量逻辑，另行评估。

最终版本APK1.20（零拷贝+fence，立即反馈）3轮：KWin Paint p50/p95 2.03/3.81ms，每轮365帧，与1.11一致；SurfaceFlinger p95在16.7/25.0ms两档之间逐轮跳动（1.11同样出现过25ms），属于边界上的量化噪声。

## 按需vsync（第3项）

原来Java `DisplayPacer`每个vsync都重新注册Choreographer回调并调用`frameTick`，合成线程每个vsync跑一遍（排空命令、检查socket、dispatch、flush），桌面静止时也一样。APK1.22改为按需：

- 原生（`frame_clock.rs`、`compositor.rs`）：最近400ms内没有客户端commit、JNI命令（输入等）、按下的触点、未决的SurfaceFlinger释放fence/呈现反馈，就进入停泊状态。停泊时不再等vsync条件变量，而是`poll()` Wayland display fd、监听socket、XWayland事件循环和一个kick eventfd，最长1秒做一次例行检查；`send_command`和SurfaceFlinger的释放/完成回调都会kick。停泊时不再做500ms心跳重绘（它会重复提交同一缓冲）。唤醒后先立即处理本次事件，再回到vsync节拍。
- Java：`doFrame`中`NativeBridge.wantsVsync()`为false时不再重新注册回调；主Looper用`MessageQueue.addOnFileDescriptorEventListener`监听原生`vsyncWakeFd`（eventfd），原生离开停泊时写入它，Java排空后恢复回调。原生先置位再发信号，两边的先后顺序不会丢失恢复。停泊时补一次2.6秒后的刷新率投票复核，替代原来每秒采样的释放逻辑。
- 调研：Android官方做法就是按需`postFrameCallback`（Choreographer不会自行持续回调）；桌面合成器（KWin、wlroots、Weston）同样只在有损伤或frame callback时调度重绘，事件循环空闲时阻塞在Wayland fd上。本改动把宿主对齐到这一模型，没有引入新组件。
- 开关：`setprop debug.moto.ondemand_vsync 0`恢复每vsync唤醒；`native-stats`末尾显示`vsync_wanted`与累计停泊次数`parks`。

同一APK交替开关、主屏静止各10秒（热状态0，a11y按当时状态）：

| 单核% / 每秒运行次数 | 关 | 开 |
|---|---:|---:|
| APK合计 | 10.14 / 10.09 | **4.62 / 2.16**（首次测量2.67） |
| APK主线程 | 6.5% / 79–82次 | 1.4–2.6% / 16–30次 |
| APK合成线程 | 2.4% / 85–87次 | 0.1–0.7% / 1–21次 |
| SurfaceFlinger `app`（应用vsync分发） | 4.8–5.0% / 67–69次 | 0.7–1.3% / 14–20次 |

“开”的第一轮KWin有约10次/秒绘制（桌面上有零星更新），所以APK仍有4.6%。抽屉滚动3轮（`kwin_pipeline_run --zerocopy on`）：KWin Paint p50 2.07–2.24ms、p95 3.83–4.35ms，SurfaceFlinger帧间隔p95三轮均16.8ms，APK CPU 13.4–15.4%（1.20为14.7–17.7%），无退化。

按控件名启动/关闭检查：开关交替5次共10轮全部通过，停泊8秒后点击启动4/4、直接点击8/8。开发过程中另有两次“开”状态下的首轮失败（一次点到y=127的错误位置，一次点中图标但未启动），之后未能复现，也未能归因；检查脚本现已在启动失败时自动截图留证。

另外观察到plasmashell在静止时有时持续约10%单核、120–150次/秒唤醒（与本开关无关，1.22首次测量时只有0.6%），列为第6项调查。

## GPU频率（第4项）：本轮不改

- 本机电源HAL（高通/Moto MDPF）配置中，GPU最低功率档`/sys/class/kgsl/kgsl-3d0/min_pwrlevel`只由`INTERACTION_SEVERE/MODERATE_SCROLL`、`INTERACTION_SEVERE/MODERATE_TOUCH`（厂商交互hint）和`EXPENSIVE_RENDERING`（SurfaceFlinger在昂贵GPU合成时设置）触发，普通应用没有入口。ADPF（`PerformanceHintManager`）会话的MDPF配置只有CPU uclamp的PID参数，没有GPU项；会话线程还必须属于调用方进程，宿主不能替容器内KWin/plasmashell报告。`SessionHint.GPU_LOAD_UP`等提示在这里没有对应的GPU动作。
- 其余可行手段都是全局改动：KGSL `devfreq`的`mod_percent`（需要root、影响全机）、`min_pwrlevel`或频率锁定。它们违反49、51篇“不锁频、不改温控”的边界，未采用。
- 必要性也下降了：显式同步后KWin不再在CPU上等待GPU，滚动时GPU只有11–13%忙碌，平均约560MHz（295–816MHz之间来回），SurfaceFlinger帧间隔p95已稳定在16.8ms。频率只影响缓冲就绪的时刻，当前数据中看不到由它造成的丢帧。
- 以后如果出现明确由GPU低频造成的卡顿（KGSL轨迹中提交排队、`adreno_cmdbatch_retired`延后），再评估用户可选的`mod_percent`开关；默认不启用。

## 其他修复

- 开机左上角黑框光标：宿主seat在触屏模式下仍声明`wl_pointer`，KWin据此在(0,0)绘制自己的光标（透明区在不透明层中显示为黑框），直到有指针事件。宿主改为只在鼠标/触控板模式声明`wl_pointer`（触屏模式只走`wl_touch`，本来就不经过指针），切换模式时增删能力。开机截图已无光标；按控件名启动/关闭应用检查3/3及改变布局2/2通过。蓝牙鼠标模式尚未实机验证。
- 共享存储：Android用户空间重启后vold重新挂载外部存储，容器启动时绑定的`/storage/emulated/0/Plasma`失效，`moto-plasma-shared`每3秒失败重启。`shared-storage`启动时先卸掉失效的FUSE挂载；`moto-plasma start/restart-session`检测到共享目录不可读时先重启容器以重建绑定。

## 复现

```sh
source tools/work-env.sh
uv run --script tools/kwin_pipeline_run.py OUT --zerocopy on,off              # 同一APK交替开关零拷贝
uv run --script tools/kwin_pipeline_run.py OUT --zerocopy on --kwin-env MOTO_KWIN_EXPLICIT_SYNC=-1
```

数据：`benchmarks/zero-copy-20260924/`。原生宿主可在K8构建：`MOTO_PROXY= bash plasma/build-native-core.sh`（自动使用SDK中最新NDK，xkbcommon取自已安装APK）。
