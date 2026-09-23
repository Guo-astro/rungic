# Plasma Vulkan 链路与性能对照

2026-09-23，XT2537-4 / Adreno710 / Android16 / Ubuntu26.04。

用户要求把桌面合成也纳入Vulkan，并根据量化结果选择GLES或Vulkan；如果原生Vulkan优势足够，可以考虑维护KWin分支。本轮先复用现有标准接口，验证可行性并做交叉对照，不把“加载Vulkan驱动”视为性能提升。

## 已经实测的能力

| 层次 | 实测结果 | 范围 |
|---|---|---|
| Linux Vulkan驱动 | UID1000识别Turnip Adreno710，API1.4.359，Mesa26.3.0-devel | 实际硬件，不是lavapipe |
| 原生Vulkan窗口 | `vkcube --wsi wayland`显示旋转立方体 | Wayland WSI及现有KWin接入 |
| Qt原生Vulkan | Kalk以`QSG_RHI_BACKEND=vulkan`显示；日志确认QRhi Vulkan、Turnip及1080×2178交换链 | 单个Qt应用，未全局更改应用环境 |
| Zink共享缓冲 | EGL绘制/像素读回、GBM DMA-BUF导出、Android AHB DMA-BUF导入及像素读回均通过 | 同一套已部署Mesa，未混入其他图形库 |
| KWin经Zink合成 | 桌面、应用抽屉和应用开关显示；KWin实际renderer为`zink Vulkan 1.4(Turnip Adreno (TM) 710 (MESA_TURNIP))` | KWin保留GLES接口，Zink将命令转换为Vulkan |
| Android Vulkan | 厂商驱动报告1.3.284，具备AHardwareBuffer、外部fence/semaphore FD及swapchain扩展 | 能力枚举；APK尚未改成Vulkan呈现 |

所有探测沿用现有权限，全局SELinux保持Enforcing。设备原有`/dev/kgsl-3d0`及DMA heap路径继续使用，没有添加假DRM节点。

## 上游核验与选型边界

- 当前KWin6.6.6源码的合成选项是OpenGL和QPainter，内部Qt Quick特效强制匹配OpenGL；没有可通过`KWIN_COMPOSE=Vulkan`启用的原生Vulkan场景后端。
- 核对2026-09-23的[KWin主线源码](https://github.com/KDE/kwin/blob/a5a83437d09024c802eb6db738cfd9cbfd97e41c/src/compositor.cpp)，提交`a5a83437d09024c802eb6db738cfd9cbfd97e41c`：仍通过`ItemRendererOpenGL`渲染场景，Wayland嵌套后端也仍创建EGL后端。
- [KWin MR8926](https://invent.kde.org/plasma/kwin/-/merge_requests/8926)在2026-03-26合并，内容是DRM后端的多GPU复制交换链。不能把它解读为整个KWin已完成原生Vulkan合成。[开发者说明](https://planet.kde.org/xavers-blog-2026-07-31-fixing-multi-gpu-performance-part-1/)同样明确该用途。早期MR5602已关闭，部分基础设施进入8926。
- [Qt6.10 QRhi文档](https://doc.qt.io/qt-6.10/qtquick-visualcanvas-scenegraph-renderer.html)提供成熟的OpenGL/Vulkan共用场景后端，适合用同一界面比较原生API。KWin特效/缩略图仍存在GL纹理和上下文耦合，不能据此全局强行修改所有进程。
- [Mesa Zink](https://docs.mesa3d.org/drivers/zink.html)是已有的OpenGL到Vulkan实现。现有统一Mesa包已经编译Zink和Turnip，无需重写KWin即可验证“桌面绘制最终提交Vulkan”的路径；它的性能不能代表尚未实现的KWin原生Vulkan后端。
- APK当前使用GLES/EGL导入AHB并呈现。厂商Vulkan支持[Khronos AHB扩展](https://docs.vulkan.org/refpages/latest/refpages/source/VK_ANDROID_external_memory_android_hardware_buffer.html)，可作为后续宿主Vulkan实现基础；完整替换还要实现交换链、尺寸/前后台重建、缓冲租约、色彩/方向及跨进程GPU同步。
- [Smithay renderer源码](https://github.com/Smithay/smithay/blob/master/src/backend/renderer/mod.rs)和当前vendored代码中，Vulkan分配器不等于已有Vulkan合成器。第三方Volcanic分支面向X11，与本项目保留原生Wayland的目标不符，未采用。

来源的源码、MR元数据、提交日期、驱动枚举及进程映射保存在`benchmarks/plasma-vulkan-20260923/`。KWin源码按GPL许可保留，Mesa按其原许可，新增诊断工具为MIT。

## 对照方法

共同条件：1080×2400渲染，KDE缩放3，Android请求120Hz；普通桌面用户，不锁CPU/GPU频率，不修改调度/温控。没有录屏和编译负载。每轮记录实际KWin renderer、显示尺寸和刷新率、温度/热状态；采集原始时间戳。

1. **真实桌面合成对照**：GLES / Zink按ABBAAB顺序，每种3轮，每轮独立重启并预热。固定12次抽屉滚动及6次计算器打开/关闭，逐次确认进程确实启动和退出。SurfaceFlinger记录宿主Surface实际呈现；单独采样KWin和plasmashell的CPU时间/RSS。CPU百分比以一个核为100%，不是整机CPU百分比。
2. **原生API对照**：固定KWin为GLES，同一个Qt Quick程序只改变`QSG_RHI_BACKEND`，比较GLES3.2和原生Vulkan。包含带文字/圆角的滚动卡片，以及6个缓存半透明窗口层移动叠加。每场景每后端3轮交叉执行，预热约4秒、测量约12秒，按实际时长归一化。首版Qt粗粒度定时器实际测量约11.5秒，原程序保留为quick-render-v1.cpp。为了复核窗口叠加场景的波动，第二版采用精确定时器并每500ms记录Android实际刷新率，再各测3轮；实际采样约12秒，全部刷新率样本为120Hz。程序收集实际`frameSwapped`时间、渲染命令阶段CPU耗时及进程CPU时间，不在每帧打印日志。
3. **统计边界**：Surface呈现不保证每个Linux客户端都画了新内容；Qt的frameSwapped也不是物理扫描时间。桌面宏中固定暂停和抽屉准备动作保留在原始数据中，不能把P99中的人为暂停称为卡顿。QRhi的GLES后端不支持同等GPU timestamp测量，本轮不把CPU提交时间冒充GPU执行时间。没有量化整机功耗。

脚本：`tools/compare_plasma_gpu.py`、`tools/benchmark_plasma_compositor.py`及`plasma/bench/`。临时KWin切换仅使用`/run/user/1000/systemd/user/plasma-kwin_wayland.service.d/90-moto-zink-audit.conf`，对照结束恢复原GLES配置。原生API探测只在诊断进程设置变量。

19:03–19:11的早期单轮测试用于连通性探索，不进入最终统计。尤其`native-zink-launch-warm.json`未验证点击命中，`paired/zink-1`遇到Android息屏；均不能用来评价性能。新的测试增加唤醒/前台检查及逐次启动、退出检查，最终只采纳完整通过的正式轮次。

## 结果与决策

正式结果：当前生产桌面保留GLES。Zink已证明可以让KWin绘制最终提交Vulkan，但现有路径的帧时间和CPU成本更差。原生Vulkan有可重复的CPU成本优势，窗口叠加场景提交吞吐也提高，值得继续做最小原生合成原型；现有证据不足以保证完整KWin重写的收益。

下表采用每种3轮的**中位数**，不是选取最好一轮。温度记录的Android Thermal Status均为0；保留自动调度，不据此断言不存在任何频率波动。

| 真实桌面：同一KWin场景 | GLES / freedreno | GLES经Zink / Turnip |
|---|---:|---:|
| 手势期间呈现间隔P99 | 8.50ms | 16.72ms |
| 手势期间超过12.6ms的帧间隔占比 | 0.57% | 5.06% |
| 打开/关闭操作窗口内P95 | 25.08ms | 33.45ms |
| KWin CPU占用，单核100% | 29.97% | 31.25% |
| KWin末次采样RSS | 137.1MiB | 152.4MiB |

手势统计仅取输入开始100ms后至手势结束；应用打开取开始100–1200ms，关闭取100–850ms，排除宏中的显式等待/抽屉准备。Android原生CLOCK_MONOTONIC探针与主机做15次校准，以低RTT样本估算时钟差；最短RTT约32.8ms。将时间窗口整体平移±20ms重算，GLES慢帧占比中位数仍为0.49–0.57%，Zink为4.98–5.24%，结论不依赖精确边界。12.6ms约为120Hz帧预算的1.5倍；这里衡量Surface呈现间隔，不称为每个客户端的真实掉帧率。

| 原生API：相同Qt场景 | GLES3.2 | 原生Vulkan |
|---|---:|---:|
| 滚动界面，每提交帧CPU时间 | 6.117ms | 4.174ms |
| 滚动界面，提交帧率中位数 | 113.5fps | 116.5fps |
| 六层窗口叠加，提交帧率（严格12秒复测） | 76.8fps | 84.7fps |
| 六层窗口叠加，每提交帧CPU时间 | 3.943ms | 3.170ms |
| 六层窗口叠加，提交间隔P95 | 15.20ms | 16.16ms |

滚动界面的CPU成本约降低32%，但帧率范围有重叠（GLES101.8–114.9，Vulkan99.1–116.6fps），不能宣称稳定提高了帧率。窗口叠加严格复测的帧率范围为GLES61.7–77.3、Vulkan82.8–84.9fps，中位数约提高10%，每帧CPU成本约降低20%。全部144次Android刷新率采样均为120Hz，所以该复测的吞吐差异不是物理屏幕在60/120Hz间切换造成的。Vulkan的P95并没有同时变好，不能只凭平均吞吐宣传更顺滑，也不能据CPU占用推出整机功耗。

原始数据：compositor/含6轮桌面与CPU采样；quick/含12轮原生API；quick-controlled/含6轮带物理刷新率采样的复测。results.json、clock-calibration.json、clock-sensitivity.json保存计算结果。当前KWin已恢复freedreno/GLES，临时Zink服务覆盖已删除；测试程序退出，未全局修改应用RHI。

目前KWin→Android输出仍有`glFinish`等待，宿主仍进行一次GLES呈现。更换API不会自动消除这些步骤。后续原型应直接针对这一输出链：复用上游Vulkan device/texture基础设施，完成Wayland嵌套输出、AHB/DMA-BUF导入及fence交接，先比较相同窗口纹理场景的呈现长帧与CPU成本，再决定扩成KWin分支。

完整KWin原生后端还涉及ItemRenderer、GL着色器/帧缓冲特效、Qt Quick内部纹理互操作、颜色管理、旋转缩放、录屏导出及恢复。这些都不是设置QSG_RHI_BACKEND即可完成的。正式维护fork的判断应以实际桌面收益明显超过轮次波动、无输入/缩放/媒体回归、可继续跟随上游为准；本轮没有宣称已实现该原生后端。

后续（2026-09-24）：在KWin输出路径上用独立GLES/Vulkan合成原型和KWin分段追踪完成了量化，结论与建议见[56篇](56-kwin-vulkan-quantification.md)。
