# 编解码桥做成VA-API驱动的可行性（docs/73第五阶段）

2026-09-27，只读调研：未操作手机与容器，未改动已跟踪文件。源码快照、克隆与索引在`.work/research/vaapi/`。

问题：能否把现有Android MediaCodec编解码桥包装成libva后端驱动`*_drv_video.so`，让FFmpeg、GStreamer、Firefox、Chromium按标准方式初始化VA-API，从而删掉FFmpeg的2条补丁、Snapshot的编码器补丁和Firefox的`LD_PRELOAD`。

## 结论

**按第五阶段的目标，不可行，维持现状。** VA-API驱动本身能做出来（同类设备已有先例，见“已有工作”），但它替换不掉要删除的这三项：

1. **Firefox过不了自己的能力探测。** Firefox先用glxtest探测GPU，探测结果不含DRM节点时，VA-API硬解会被强制关闭。本机Mesa在KGSL上只提供软件EGL设备，glxtest因此记为`MESA_ACCELERATED FALSE`，也拿不到`DRM_RENDERDEVICE`，vaapitest根本不会运行。`media.hardware-video-decoding.force-enabled`绕不过这一关（源码见下文）。要过这关，只能让Mesa把KGSL谎报成DRM设备，这违反[54篇](../54-vendor-adaptation-boundaries.md)“不能伪造DRM设备”的边界。
2. **Firefox 156在Linux上没有VA-API编码路径。** 编码器不建立硬件设备上下文，输入格式固定为YUV420P，`h264_vaapi`无法打开。WebCodecs/WebRTC的H.264硬编仍要依赖私有FFmpeg中的`h264_rungic_auto`等编码器，因此FFmpeg的2条补丁和预加载都得保留。
3. **RDD沙箱仍然挡着桥接连接。** Firefox的RDD沙箱不允许新连接`codec.sock`，也不允许打开`/dev/dma_heap`。VA驱动在RDD里同样需要“沙箱前预连”；否则就得关闭沙箱，已有先例正是这么做的（`MOZ_DISABLE_RDD_SANDBOX=1`），但这违背本项目的原则。
4. **Snapshot是唯一可替换的一项，但得不偿失。** Snapshot 51原生识别`vah264enc`，但前提是：VA编码入口（EncSlice）映射到MediaCodec编码器；设置`GST_VA_ALL_DRIVERS=1`；把Android的msm_drm render节点映射进容器。换来的只是删除一个17行的补丁，却要新增并长期维护数千行驱动代码。

VA-API驱动可作为**另一项新增能力**单独评估，服务对象是mpv、FFmpeg命令行、GStreamer `va`和Chromium等VA-API消费者。它**不能作为减少补丁的手段**。评估时还应比较“驱动内直接调用原厂V4L2”的做法；已有项目声称该做法在Android 15/内核6.6的新版msm_vidc上可用，与本机条件接近。

## 现有实现（仓库内）

| 项 | 挂接的接口 | 提供的能力 |
|---|---|---|
| 编解码桥 | APK中的`CodecBridge`调用MediaCodec（`c2.qti.*`）；容器侧[`codec-client.c`](../../shared/media/codec-client.c)经`/mnt/android-wayland/codec.sock`通信，用32MiB SharedMemory传帧，并做I420的CPU复制 | 有状态的“码流进、帧出”接口（FRAME/DRAIN/FLUSH/CLOSE），支持H.264/HEVC编解码和VP9解码；非零复制，见[35篇](35-hardware-codec-integration.md) |
| FFmpeg 2条补丁 | `packages/ffmpeg`：`android-codec-registration.patch`在`allcodecs.c`/`Makefile`中登记7个`*_rungic*`编解码器；`libx264-software-name.patch`把x264改名为`libx264_sw` | 私有FFmpeg 8.1.2，服务对象只有Firefox。按名字选`libx264`的调用方会拿到硬件优先、失败回退软件的混合编码器 |
| Snapshot补丁 | `packages/snapshot` `android-h264-encoder.patch`：在`aperture/src/utils.rs`和`viewfinder.rs`中识别`rungich264enc`（17行） | Snapshot的“硬件编码”开关对我们的GStreamer元素生效 |
| Firefox包装 | [`plasma/firefox`](../../plasma/firefox)：设置`LD_LIBRARY_PATH`，用`LD_PRELOAD=librungiccodec.so:libavcodec.so.62`，并设`RUNGIC_CODEC_PRECONNECT=1` | 沙箱建立前连上broker，fork出的子进程各持一条连接；各进程统一使用私有FFmpeg |
| GStreamer | [`gst-rungic-codec.c`](../../shared/media/gst-rungic-codec.c)，属于自有插件，不修改上游 | `rungich26{4,5}{enc,dec}`、`rungicvp9dec`，rank为PRIMARY+32 |

## 源码版本与许可

| 组件 | 版本（依据） | 来源 | 许可 |
|---|---|---|---|
| libva | 2.23.0-1ubuntu1（resolute main `Sources.xz`） | intel/libva 标签2.23.0，`dbf83dc3` | MIT |
| libdrm | 2.4.131-1 | mesa/drm `libdrm-2.4.131`，`6bfcfc72` | MIT |
| FFmpeg | Ubuntu 8.0.1-3ubuntu2；私有8.1.2 | ffmpeg-8.0.1.tar.xz（sha256 `05ee0b03…`）；8.1.2的`vaapi_device_create`逻辑与8.0.1相同（已diff） | LGPL-2.1+（整体构建依选项） |
| GStreamer va | gst-plugins-bad 1.28.2-1ubuntu1(.1) | gstreamer 标签1.28.2，`43421c2a` | LGPL-2.1+ |
| Firefox | 156.0.1（Mozilla APT，[40篇](../40-plasma-mobile-integration.md)） | mozilla-firefox/firefox `FIREFOX_156_0_1_RELEASE`，按文件取 | MPL-2.0 |
| Chromium | Ubuntu只有snap过渡包`2:1snap1-0ubuntu4`；上游稳定版154.0.8037.57（chromiumdash） | chromium.googlesource.com 标签154.0.8037.57 | BSD-3-Clause |
| Mesa（本机） | KGSL分支`98f3d62`（`packages/mesa/recipe.json`） | `.work/pq/mesa` | MIT |
| GKI配置 | android15-6.6 `gki_defconfig` | aosp-mirror/kernel_common分支快照（sha256 `b7e4a8fe…`），不等于本机厂商内核 | GPL-2.0 |

## 源码核实的事实

### libva 2.23.0

- `vaGetDisplayDRM`只要求`drmGetNodeTypeFromFd(fd) >= 0`（`va/drm/va_drm.c:94`）：render节点记为`VA_DISPLAY_DRM_RENDERNODES`，不做认证；primary节点需要`drmGetMagic`和认证（`va_drm.c:56-64`）。认证失败只让`vaGetDriverNames`失败，`va_new_opendriver`会记错误后继续（`va/va.c:681-686`）。
- 驱动名取自`drmGetVersion()->name`：不在映射表中时，直接用内核驱动名作VA驱动名（`va/drm/va_drm_utils.c:78-108`）。Android的`msm_drm`对应`msm_drm_drv_video.so`，**不设环境变量也能加载**。`LIBVA_DRIVER_NAME`会覆盖探测结果，但探测仍会先执行（`va.c:689-704`）；`LIBVA_DRIVERS_PATH`只对非setuid进程生效（`va.c:381-385`）。
- Wayland后端`vaGetDisplayWl`：从linux-dmabuf feedback的`main_device`取`dev_t`，用`drmGetDevices2`匹配render节点后打开（`va/wayland/va_wayland_linux_dmabuf.c:71-157`），否则尝试wl_drm。本机KWin没有通告wl_drm，也没有v4 feedback的main device（Mesa KGSL分支`platform_wayland.c:2724-2728`的注释说明了这一点），因此Wayland路径拿不到设备。FFmpeg、GStreamer、Firefox、Chromium都走DRM路径，不用这条。

### libdrm 2.4.131：能否用假节点

- Linux上`drmNodeIsDRM`**不检查主设备号226**，而是检查`/sys/dev/char/M:m/device/drm`是否存在（`xf86drm.c:3321-3329`）；`drmGetMinorType`按minor号检查`/dev/dri/card<minor>`或`renderD<minor>`是否存在（`xf86drm.c:1052-1061`）；另外要求是字符设备（`3356`）。
- 所以要仿冒节点，需要：一个能响应`DRM_IOCTL_VERSION`的字符设备（FFmpeg、GStreamer、Chromium都会调用`drmGetVersion`）、伪造的sysfs `device/drm`目录，以及匹配的`/dev/dri`文件名。GKI android15-6.6 defconfig**没有`CONFIG_CUSE`和`CONFIG_DRM_VGEM`**，只有`CONFIG_DRM=y`和`CONFIG_UDMABUF=y`。用户态没有办法提供字符设备；即使有vgem，FFmpeg（`hwcontext_vaapi.c:1803-1809`）和Chromium（`vaapi_wrapper.cc:117-120`）也会主动跳过vgem。

### FFmpeg 8.0.1

- 指定设备时直接`open(device)`后调用`vaGetDisplayDRM`（`libavutil/hwcontext_vaapi.c:1740-1746,1848`）。不指定时扫描`/dev/dri/renderD128..135`，`drmGetVersion`失败或驱动为vgem就跳过；可用`kernel_driver`/`vendor_id`过滤（`1757-1843`）。没有render节点时VA-API无法初始化；没有libdrm的构建里X11路径另论。
- 复制路径：`vaDeriveImage`/`vaGetImage`再`vaMapBuffer`（`hwcontext_vaapi.c:867,894`），不需要DMA-BUF。零复制映射到DRM用`vaExportSurfaceHandle(DRM_PRIME_2)`（`1372`）。
- **解码的抽象层级不同。** VA解码是“应用解析、驱动加速”：H.264和HEVC只把各slice的原始NAL交给驱动（`h264dec.c:674`、`hevc/hevcdec.c:3046`），SPS/PPS只以解析后的参数结构传递；VP9则交整帧（`vp9.c:1669`）。MediaCodec是有状态解码器，需要完整码流，驱动必须**从参数重建SPS/PPS**。VA结构中缺少部分字段：H.264没有POC type 1的`offset_for_ref_frame`等（`va/va.h:3594`起的结构）；HEVC只给`num_short_term_ref_pic_sets`的个数和`st_rps_bits`，不给SPS中的RPS内容（`va/va_dec_hevc.h:166-186`）。因此**使用SPS内RPS的HEVC流和POC type 1的H.264流无法重建**，只能返回不支持，由应用回退软件。
- 编码要求`hw_frames_ctx`（`hw_base_encode.c:784-788`）。驱动不支持packed header时，FFmpeg不写全局头，并警告封装可能不可用（`vaapi_encode.c:1958-1965`）。帧类型、GOP和参考结构由FFmpeg决定，而MediaCodec只能接受“请求关键帧”，不保证落在指定帧上；驱动只能声明1个前向参考、不支持B帧来降级。

### GStreamer va（1.28.2）

- 通过gudev按`drm`子系统枚举，只保留名字以`renderD`开头的节点（`sys/va/gstvadevice_linux.c:80-101`）；不带gudev的构建则固定扫描`/dev/dri/renderD128..135`（`123-127`）。打开节点后，`drmGetVersion`失败就报“not a DRM render node”并放弃（`gst-libs/gst/va/gstvadisplay_drm.c:140-163`）。**没有render节点，GStreamer va就用不了。**
- 厂商字符串不是Mesa Gallium或Intel的驱动一律拒绝，除非设置`GST_VA_ALL_DRIVERS`（`gstvadisplay.c:184-188`）。插件注册依赖`/dev/dri/renderD*`、`LIBVA_DRIVER_NAME`和`GST_VA_ALL_DRIVERS`，这几项变化会触发重新扫描（`sys/va/plugin.c:66-90`）。
- Snapshot 51原生处理`vah264enc`和`v4l2h264enc`（`aperture/src/utils.rs:180-186`、`viewfinder.rs:933,981-995`）。

### Firefox 156.0.1

- `DRM_RENDERDEVICE`只来自glxtest的EGL设备查询（`toolkit/xre/gfxtest/glxtest.cpp:606-624`）。EGL设备带`EGL_MESA_device_software`时，只记录`MESA_ACCELERATED FALSE`，不记录节点。本机Mesa在KGSL上强制使用软件设备（`src/egl/drivers/dri2/egl_dri2.c:855`：`if (disp->Options.Kgsl || ...) software = true`），Firefox因此把`mIsAccelerated`置为false（`widget/gtk/GfxInfo.cpp:435`）。
- 硬解状态只有在`mIsAccelerated`成立时才会探测VA-API/V4L2；探测失败即`FEATURE_BLOCKED_PLATFORM_TEST`（`GfxInfo.cpp:1628-1642`）。vaapitest只打开glxtest给出的节点（`GfxInfo.cpp:733`，`vaapitest.cpp:89-115`）。`BLOCKED_PLATFORM_TEST`会被`ForceDisable`（`gfx/thebes/gfxPlatform.cpp:3068-3070`），优先级高于`force-enabled`的`UserForceEnable`（`3046-3048`）。另外，没有EGL或DMABUF时也会强制关闭（`gfxPlatformGtk.cpp:236-249`）。`MOZ_DRM_DEVICE`只影响DMABufDevice（`widget/gtk/DMABufDevice.cpp:253`），不影响vaapitest。
- 解码输出**必须**用`vaExportSurfaceHandle(DRM_PRIME_2)`，失败就放弃硬解，没有复制回退（`dom/media/platforms/ffmpeg/FFmpegVideoDecoder.cpp:2120-2145`）。VADisplay通过`DMABufDevice::OpenDRMFd()`打开节点后创建（`VALibWrapper.cpp:113-129`）。
- Linux上的硬件编码只按codec能力挑选FFmpeg编码器（`FFmpegDataEncoder.cpp:122-162`），`pix_fmt`固定为YUV420P（`FFmpegVideoEncoder.cpp:403`），全程不建立`hw_device_ctx`/`hw_frames_ctx`，所以`*_vaapi`编码器打不开。
- RDD沙箱：`/dev/dri`可读写，`/sys/dev/char/M:m`系列只读（`SandboxBrokerPolicyFactory.cpp:82-135,410-416,1045`）；**没有`/dev/dma_heap`**，只在Vulkan视频路径中放行`/dev/udmabuf`（`983-985`）；没有任意路径的`MAY_CONNECT`。aarch64构建默认启用`MOZ_ENABLE_V4L2`（`toolkit/moz.configure:642-651`）。

### Chromium 154

- arm64 Linux构建启用`use_vaapi`（`media/gpu/args.gni:16-19`），`AcceleratedVideoDecoder`默认开启，编码默认关闭（`media/base/media_switches.cc:1486-1498`）。
- 自动枚举**跳过非PCI设备**（`media/gpu/vaapi/vaapi_wrapper.cc:1674-1677`），msm_drm是平台设备。只能用`--hardware-video-device-path=`（`drmGetVersion`失败也强制使用，`1633-1645`）或`--render-node-override=`（`1647-1655`）绕过。VaapiVideoDecoder在GL上默认允许（`media/mojo/services/gpu_mojo_media_client_linux.cc:108-114`）。输出帧是GBM分配的NativePixmap：驱动要支持DRM PRIME导入（`vaapi_wrapper.cc:2656`）和导出（`2756`），没有CPU复制回退。
- Ubuntu resolute没有Chromium deb，本项目也没有安装Chromium。GPU进程能否在KGSL上跑硬件GL、能否创建GBM设备都没有验证过。

## 已有工作（第三方声明，未在本机验证）

| 项目 | 版本/提交 | 许可 | 与本题的关系 |
|---|---|---|---|
| [droidspaces-media-decode](https://github.com/Re-s/droidspaces-media-decode)（本次克隆的是镜像[Yizhou147](https://github.com/Yizhou147/droidspaces-media-decode)，`df848341`） | 0.1–0.3.7由VA驱动代理到Android侧MediaCodec守护进程；0.4.0起改为驱动内直接调用msm_vidc V4L2；0.4.5适配Android 15、内核6.6.118的新msm_vidc（DMABUF、`/dev/dma_heap/system`）、Ubuntu 26.04容器和FFmpeg 8.0.1 | Apache-2.0 | 最接近的先例。驱动命名为`msm_drm_drv_video.so`，依赖把`/dev/dri/renderD128`（msm_drm）映射进容器；表面用msm_drm的dumb buffer，经PRIME导出（`vaapi-driver/src/export.c`、`decode.c:281-320`），解码结果先CPU复制再导出。Firefox需要`force-enabled`，**并且关闭了RDD沙箱**（`doc/browser-vaapi-guide.md`第二章第2节）；Chrome需要`--render-node-override`。他们也遇到了SPS/PPS重建问题：HEVC的`num_short_term_ref_pic_sets>0`直接拒绝（`hevc_bitstream.c:331-338`），POC type 1无法支持（`h264_bitstream.c:183-188`），I帧的`num_ref_idx`默认值错误（CHANGELOG v0.4.6）。另外，Chrome从不调用`vaSyncSurface`，驱动必须在`vaEndPicture`返回前把帧写进surface（v0.4.6）。代码规模约1.1万行C |
| [venus-vaapi-driver](https://github.com/super617/venus-vaapi-driver) | `47744788`（2026-09-13） | MIT | 骁龙855旧Venus有状态V4L2的VA驱动，自述通过重建SPS/PPS完成H.264 VLD，并实现了EncSlice |
| [rockchip-vaapi](https://github.com/woodyst/rockchip-vaapi)（另有[defcom5分支](https://github.com/defcom5-rockchip/rockchip-vaapi)） | `08559e8a` / `e1f0d37d` | LGPL-2.1 | 代理到有状态的MPP；HEVC同样受SPS RPS限制，只能用哑RPS加检测来规避（`defcom5 src/hevc.c:27-29,170-175`） |
| [nvidia-vaapi-driver](https://github.com/elFarto/nvidia-vaapi-driver) | v0.0.14，`effa3af0`（Ubuntu有0.0.14-1） | MIT | 后端NVDEC本身是参数级接口，不需要重建码流；libva给出的DRM fd只作为设备句柄（`src/vabackend.c:2262-2265`） |
| [libva-v4l2-request](https://github.com/bootlin/libva-v4l2-request) | `a3c2476d`（2019，已停止维护） | LGPL-2.1/MIT | 用环境变量自选`/dev/video*`和`/dev/media*`（`src/request.c:149-173`），完全不使用DRM fd，说明DRM节点可以“只作句柄” |

本轮**未找到**基于libhybris、Halium、Ubuntu Touch、Waydroid或Droidian媒体栈，把MediaCodec包装成Linux VA驱动的项目（它们用gst-droid/droidmedia）；也未找到libva `VA_DISPLAY_ANDROID`在Linux容器里的用法。这只代表本轮没有搜到，不能断言不存在。

## 三种做法

| | (a) 映射msm_drm renderD128作为句柄 | (b) vgem或伪DRM节点 | (c) 只做复制路径的VA驱动 |
|---|---|---|---|
| 做法 | LXC增加`c 226:128 rw`并绑定`/dev/dri/renderD128`；驱动名自动为`msm_drm`；sysfs已按`sys:ro`挂入 | 自造设备 | 与(a)配合，驱动只实现`vaGetImage`/`vaDeriveImage`/`vaPutImage` |
| FFmpeg | 可以（`-hwaccel vaapi`等需应用主动开启） | GKI没有CUSE/vgem，做不到；FFmpeg也会跳过vgem | 可以，靠hwdownload复制 |
| GStreamer va | 需要`GST_VA_ALL_DRIVERS=1` | 同左，做不到 | 可以，使用系统内存 |
| Firefox | **不行**：卡在KGSL软件EGL设备这一关；编码没有VA路径；RDD需预连 | 做不到 | 不行，Firefox必须导出 |
| Chromium | 需要`--render-node-override`；没有安装，GBM与GL未知 | 做不到 | 不行，Chromium必须用DMA-BUF |
| 零复制 | 可行但需验证：由APK把MediaCodec输出到AHardwareBuffer，再经已预连的socket把dmabuf交给驱动导出（涉及UBWC/NV12布局与fence，见[57篇](../57-zero-copy-explicit-sync.md)）；或像先例那样用dumb buffer，但解码输出仍有CPU复制 | — | 没有零复制 |
| 风险 | 节点属于显示驱动（SDE），不是GPU。Mesa loader、GBM、KWin、Firefox的DMABufDevice、Chromium都可能开始使用这个节点：例如GBM对`msm_drm`建设备失败或回落到dumb/kms_swrast，从而改变已经工作的应用路径。`CREATE_DUMB`在上游不属于render允许的ioctl，下游是否放行未知。dumb buffer计在显示驱动名下。容器进程是`u:r:magisk:s0`，SELinux预计不拦截，但未验证。必须回归KWin、Firefox、相机和录屏 | — | 与(a)相同 |

维护成本对比：现有补丁合计约35行，另有5行包装脚本和私有FFmpeg运行库。VA驱动要按codec分别重建码流、映射DPB与输出顺序、处理flush/seek、分辨率切换、导出与同步；先例约1.1万行，并且多次修正了只在浏览器里出现的时序问题。编码侧还要把VA的逐帧参数控制压缩到MediaCodec的有限接口上。即使驱动全部做成，Firefox的预加载和私有FFmpeg仍要保留，所以要维护的东西只增不减。

## 若以后单独立项做VA-API驱动（新增能力），需要的实机验证

1. 只读检查：`ls -l /dev/dri`，`/sys/dev/char/226:128/device/drm`，在Android上对renderD128运行`drmGetVersion`（name应为`msm_drm`），读`/proc/config.gz`确认CUSE和VGEM未启用、udmabuf存在。
2. 在隔离的测试容器配置中映射renderD128：确认`vainfo`能加载`msm_drm_drv_video.so`；回归KWin启动、Firefox与GTK渲染、相机、录屏，确认没有任何组件改用该节点（例如检查进程`/proc/*/maps`与已打开的fd）；检查avc拒绝。
3. 在renderD128上验证`DRM_IOCTL_MODE_CREATE_DUMB`与`PRIME_HANDLE_TO_FD`能否工作、内存算在谁名下；以及在`/dev/dma_heap/system`上分配、导出并经EGL导入NV12。
4. MediaCodec能否按解码顺序输出：高通`vendor.qti-ext-dec-picture-order`或`KEY_LOW_LATENCY`（未验证）；手机相机和常见网站的HEVC流中`num_short_term_ref_pic_sets`的分布。
5. 评估不经MediaCodec、由驱动直接调用原厂V4L2（先例0.4.5）：本机`/dev/video32/33`在内核6.6上能否按DMABUF和标准`SOURCE_CHANGE`完成整段解码。这会改变[34篇](34-hardware-codec-audit.md)中“先验V4L2”的判断依据，需要单独立项。

## 未能核实

- 第三方仓库所述的实机结果（Chrome、Firefox出画，0.4.5在内核6.6上的md5一致）没有在本机复现。
- 本机厂商内核的实际配置（GKI片段来自GitHub镜像分支，不是本机`/proc/config.gz`）；msm_drm render节点允许哪些ioctl。
- Google Chrome是否提供ARM64 Linux官方包（先例文档使用了`google-chrome-stable`，本轮未核对）；本机Chromium的GPU进程与GBM是否可用。
- `switches::kRenderNodeOverride`的定义文件没有取回，开关名`--render-node-override`来自先例文档。
- MediaCodec的解码顺序输出参数、`REQUEST_SYNC_FRAME`能否精确落在指定帧，均为假设。
