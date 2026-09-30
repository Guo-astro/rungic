# X11 应用在 KGSL 上用 GPU：Xwayland 的几种做法（2026-09-30）

状态：方案 B 已实施并实测（见文末“B 的实施与实测”），已进入发布 20260930.2（Xwayland 2:24.1.10-1+rungic2，Mesa 26.3.0~devel20260824+rungic3）；长时间运行和 Flatpak X11 应用尚未验收。标注说明：“实测”指在本机（XT2537-4，FD710，Ubuntu 26.04 容器）上运行的结果；“源码”指读到的代码位置；“二手”指只见于 PR/issue 文字。

## 起因

助理装的 Flathub Krita 5.3.3 很卡。原因有两层（实测）：
- Flatpak 的 `--device=dri` 在这台机器上什么也不给：容器没有 `/dev/dri`，GPU 只有 `/dev/kgsl-3d0`。这一层已在 flatpak 补丁里修掉（docs/49 “--device=dri 与 KGSL”）。
- 工作区的 Xwayland 起不来 glamor，也就没有 DRI3。日志：`glamor: 'wl_drm' not supported and linux-dmabuf v4 not supported` → `Failed to initialize glamor, falling back to sw`。KWin（Android 宿主后端）只提供 `zwp_linux_dmabuf_v1` v3，没有 `wl_drm`。所以经 Xwayland 的 X11 程序只能用 CPU 画 GL（softpipe；本机 Mesa 没编 LLVM，没有 llvmpipe）。

受影响的是只能走 X11 的 GL 程序：Qt5 程序、微信、Wine、老游戏，以及 Flatpak 里只声明 `x11` 套接字的应用。Qt6、GTK、Firefox、Blender 等已经走原生 Wayland（会话设了 `QT_QPA_PLATFORM=wayland`、`GDK_BACKEND=wayland`），不受影响。Krita 6（Ubuntu 包）原生 Wayland 下渲染器为 FD710（实测）。

## Xwayland 24.1.10 为什么起不来（源码）

- `xwayland-glamor.c:124`：没有 `wl_drm`、dmabuf 又低于 v4，直接放弃 glamor。
- `xwayland-glamor-gbm.c`：
  - `init_main_dev` 需要 dmabuf v4 反馈里的 DRM 主设备（:1683）；
  - 之后对设备 fd 调 `drmGetDevice2`（:1700）；
  - `wl_drm` 路径另有 `drmGetNodeTypeFromFd` 和 `drmGetMagic`（:1343–1354）。
- libdrm 对非 DRM 字符设备（`/sys/dev/char/M:m/device/drm` 不存在）一律失败，所以给 KWin 加 dmabuf v4 或 `wl_drm` 广告 `/dev/kgsl-3d0` 都不够，Xwayland 自己必须改。

## 做法比较

| | 做法 | 规模 | 呈现方式 | 主要风险 |
|---|---|---|---|---|
| A | lfdevs/xwayland 0001–0004：新增 KGSL surfaceless 后端（`XWAYLAND_FORCE_KGSL_SURFACELESS=1`） | 约 1700 行补丁 | 关掉 Present 翻页，每帧 GPU 拷贝；只用 LINEAR；为“陈旧帧回调”加恢复逻辑 | 为 PRoot 环境设计；issue #96 有 glmark2 掉 48–61%、卡死的报告（二手） |
| B | 保留上游 GBM glamor 路径，只改“找设备”：dmabuf v3 也允许 glamor（anland 0001 的一部分），没有主设备时用 `/dev/kgsl-3d0`，对非 DRM 设备跳过 `drmGetDevice2`/`drmGetMagic` | 估计 60–100 行 | 上游 GBM 分配、DRI3、Present 翻页（可零拷贝）照旧 | 隐式同步（见下）；GBM-on-KGSL 在 Xwayland 里未经验证 |
| C | 能走 Wayland 的尽量走 Wayland（Qt、GTK 已是；Electron `--ozone-platform-hint=auto`；SDL `SDL_VIDEODRIVER=wayland`） | 配置 | 原生 Wayland | 只减少受影响的程序，解决不了纯 X11 程序；与 A/B 互补 |
| D | 客户端用 zink：`MESA_LOADER_DRIVER_OVERRIDE=zink LIBGL_KOPPER_DRI2=1 MESA_VK_WSI_DEBUG=sw` | 环境变量 | GPU 渲染后每帧 CPU 回读，再经 X 套接字 `PutImage` | 大窗口开销大；zink 在本机不稳（docs/90 Blender）；要逐个程序设置 |
| E | 内核里给 KGSL 做一个 DRM render 节点 | 内核模块 | 上游 Xwayland 不改 | 维护 GKI 模块，代价远大于收益 |

lfdevs 的补丁说明写明 surfaceless 后端是给 “PRoot KGSL 环境” 用的：那里没有可用的 DRM 节点，而 “GBM 路径仍是默认，面向 chroot 和桌面”。本机是 LXC，能直接打开 `/dev/kgsl-3d0`，而且本机 Mesa 的 GBM 已支持 KGSL（`platform_drm.c:631` 的 `Options.Kgsl`、`loader.c:730`）。所以 B 更贴近上游、改动更小。

## 可行性探针：GBM 直接跑在 `/dev/kgsl-3d0` 上（实测，2026-09-30）

用 ctypes 按 Xwayland glamor 的调用顺序执行（`MESA_LOADER_DRIVER_OVERRIDE=kgsl FD_KGSL_ENABLE_DMABUF=1`）：
- `gbm_create_device(open("/dev/kgsl-3d0"))` 成功，后端名 `drm`；
- `gbm_bo_create(1920×1080, XR24, RENDERING)` 成功，导出 dma-buf fd，修饰符 `0x0`（LINEAR），stride 7680；加 `SCANOUT` 也成功；
- `eglGetPlatformDisplayEXT(EGL_PLATFORM_GBM_MESA)` 加 `eglInitialize` 成功；
- 桌面 GL 上下文可设为当前：`FD710`，`4.6 (Compatibility Profile) Mesa 26.3.0-devel`；
- 扩展：
  - `EGL_EXT_image_dma_buf_import`（含 `_modifiers`）；
  - `EGL_MESA_image_dma_buf_export`；
  - `EGL_KHR_no_config_context`、`EGL_KHR_surfaceless_context`；
  - `EGL_ANDROID_native_fence_sync`。

只有一条 `MESA-LOADER: failed to retrieve device information`（找不到 PCI 信息），不影响结果。结论：B 所需的 Mesa 一侧都在，差的只是 Xwayland 的设备发现。

## B 的已知风险与验收

- **同步**：KGSL 不在 dma-buf 的 reservation 上挂隐式 fence，Xwayland 的 `DMA_BUF_IOCTL_EXPORT_SYNC_FILE` 拿不到有效等待。原生 Wayland 客户端今天也在同一处境（同一 GPU、同一内核驱动），目前没有发现由此引起的问题，但也没有专门测过。若出现，就在 Xwayland 提交前用 `EGL_ANDROID_native_fence_sync` 等 fence，或者 `glFinish`。
- **陈旧采样**：lfdevs 在 PRoot 路径上遇到长期存在的 EGLImage 采样到旧内容，于是每次呈现前重新导入。B 需要用 glmark2 和一个持续动画的 X11 程序专门检查。
- **Mesa 客户端**：本机 Mesa 的补丁 `x11-kgsl-needs-dri3.patch` 让客户端只在服务器有 DRI3 时才自己打开 KGSL。B 让 Xwayland 有了 DRI3 之后，客户端会自动改走 GPU，不需再改。
- **验收**：
  - glmark2-es2（X11）、glxgears；
  - 以 X11 运行的 Flathub Krita 5.3.3、微信；
  - 一个纯 2D 的 X11 程序（xterm），检查 glamor 的 2D 加速；
  - 改变窗口大小、多窗口同时运行；
  - 30 分钟连续运行，观察是否卡死；
  - 与 softpipe 对比 CPU 占用和帧间隔。

## 建议

先做 B（Xwayland 补丁队列 `packages/xwayland`，Ubuntu `2:24.1.10-1`）。如果 B 在同步或陈旧采样上出现无法解决的问题，再看 A 中对应的处理（重新导入、帧回调恢复），只借用需要的部分，不整体引入 surfaceless 后端。C 作为共享层配置同时推进。

## B 的实施与实测（2026-09-30）

实现（都在补丁队列里）：
- `packages/xwayland`（Ubuntu 2:24.1.10-1，`rungic/glamor-gbm-kgsl.patch`，约 55 行）：
  - dmabuf v3、`MESA_LOADER_DRIVER_OVERRIDE=kgsl`、`/dev/kgsl-3d0` 可用时，glamor 用这个节点；
  - 不查 `drmDevice`，不做认证，不用 DRM syncobj；
  - Mesa 分支的 1274 标记按 LINEAR 处理。
  - 另在 `debian/rules` 关掉文档生成（构建机装有文档工具时，会多出打包规则没安排的文件）。
- `packages/mesa` `rungic/kgsl-import-is-shared.patch`：导入的 dma-buf 标为共享。

实测时遇到的问题，按顺序：
1. **DRI3 返回 BadAlloc**：Mesa 分支在 `loader_dri3_helper.c:1599` 把 LINEAR 写成 1274（给 Termux:X11 的标记），`gbm_bo_import` 不认。已在 Xwayland 补丁里改回 LINEAR。
2. **GL 窗口全黑，2D 正常**：
   - 探针：在 KGSL 上 `gbm_bo_import` 后 `gbm_bo_get_fd`，得到的是另一个 dma-buf（inode 不同）。
   - 原因：分支的 `fd_resource_get_handle()` 在 `kgsl_dmabuf` 路径上，会把没有 `PIPE_BIND_SHARED` 的资源先影子复制成新缓冲再导出，导入的资源也不例外。Present 翻页时，Xwayland 交给 KWin 的是这块新的空缓冲。
   - 修复：导入时标为共享（Mesa +rungic3）。
   - 探针本身第一次崩在 `glsl_array_type`：进程里没有 GL 上下文时，GBM 导出会创建辅助上下文，GLSL 类型表没初始化。Xwayland 有 glamor 上下文，不受影响。

实测结果（工作区，FD710，Xwayland 2:24.1.10-1+rungic2，Mesa +rungic3）：
- `xdpyinfo` 列出 DRI3 和 Present。
- `glxinfo -B`：direct rendering: Yes，Accelerated: yes，FD710，Core 4.6。
- `eglinfo -p x11`：驱动 kgsl，FD710。
- glxgears、glmark2 terrain 同时运行：两个窗口内容正确，连续截图画面在变化。
- Dolphin 以 xcb 运行，由 glamor 绘制 2D：显示正确。
- glmark2 全套（1280×720）：

| | X11（Xwayland） | 原生 Wayland |
|---|---|---|
| GL | 218 | 193 |
| GLES | 224 | 185 |

- 同样两个场景：GPU 下 257 和 267 FPS；`LIBGL_ALWAYS_SOFTWARE=1`（softpipe）2 分钟内一个场景也没跑完。

未做：
- 30 分钟连续运行；
- 改变窗口大小；
- Krita 5 等 X11-only 的 Flatpak 应用：Flatpak GL 扩展还没用 +rungic3 重建；
- 微信；
