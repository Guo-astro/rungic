# 硬件视频编码、解码：实机核验与接入候选

> 历史研究记录：Phosh 专属实现已于2026-09-23移除。本篇保留共享硬件接口与研究结论；当前代码见 `shared/`、`native/plasma/`、`plasma/`，现行集成见 [40篇](../40-plasma-mobile-integration.md)。旧Phosh路径和已删除的原始日志不再作为可执行入口。

2026-09-23，ZY32MVJS25，Android16 / Phosh0.57 / APK2.5。本轮回答硬件编解码的实际状态，完成上游研究、运行时能力枚举、真实硬编→硬解图像校验；**没有把这些能力部署进Linux播放器、相机或Firefox**。原有桌面配置和运行中的服务保持。

## 已经确认的结果

| 格式 | Android硬件解码 | Android硬件编码 | 本轮实测 |
|---|---|---|---|
| H.264 / AVC | c2.qti.avc.decoder | c2.qti.avc.encoder | 1920×1080、30fps时间戳、90帧，编码/解码均完整通过，逐帧抽样亮度匹配 |
| H.265 / HEVC | c2.qti.hevc.decoder | c2.qti.hevc.encoder | 同上；实际产出MP4并在电脑完整解码通过 |
| VP9 | c2.qti.vp9.decoder | 未枚举到硬件编码器 | 解码能力由MediaCodecList上报；尚未喂真实VP9流实测 |
| VP8 | 本机列表只有软件组件 | 本机列表只有软件组件 | 不宣称可通过配置变成硬件编解码 |
| AV1 | 本机列表只有软件组件 | 本机列表只有软件组件 | 同上 |

高通AVC/HEVC主组件的API上报1080p60可支持，3840×2160@30不支持；此轮只验证1080p30样本，不能将上报范围当成长时间性能证明。API的硬件标志用 `isHardwareAccelerated()` / `isSoftwareOnly()`读取，测试用 `createByCodecName`明确指定高通组件，失败不会自动改用软件组件。[Android MediaCodecInfo](https://developer.android.com/reference/android/media/MediaCodecInfo)

实验以 **ADB shell UID2000** 运行独立Java探针，全程 **SELinux Enforcing**；没有调用摄像头、麦克风，没有改设备节点权限、容器设备白名单或SELinux规则。它证明Android硬件组件可运行，不等同于完成桌面APK普通应用域、跨进程帧传输或Linux应用的验收。

测试输入是合成的逐帧变化亮度、固定色度图像；编码后通过Android硬件解码器取出真实Image，逐帧抽样验证Y平面。不是仅configure/start，也不是只查看XML。AVC/HEVC各90帧输入、90帧编码输出、90帧解码输出、90张Image校验通过，最大抽样亮度误差分别0.03125/0.1875。电脑FFprobe确认两份MP4均1080p、30fps、3秒、90帧，FFmpeg完整解码无错误。

AVC编码阶段约1.913秒，HEVC约1.551秒；包括Java向输入Image填像素。低复杂度样本不能用于比较真实视频吞吐、功耗、温控、CPU占用或长时间音画同步。没有因这次测试承诺1080p60/4K、HDR、10-bit或DRM视频。

## Linux当前为什么仍然软件编解码

容器内的GStreamer未注册Android MediaCodec、gst-droid、V4L2编解码元素；目前有x264enc、x265enc、openh264enc和libav软件解码器。当前Vulkan枚举也未出现视频编解码扩展。GPU绘制链路和视频编解码链路是分开的。

存在两种可继续验证的硬件入口，不能简单地把“容器没有/dev/video”推断为“手机没有硬件视频设备”：

1. **Android公开MediaCodec API**：已经实测工作；GNU/musl程序不能直接链接Android/Bionic的libmediandk/JNI并假定可运行，需要合适的进程边界或兼容层。
2. **原厂内核V4L2接口**：本轮找到 `/dev/video32`、`/dev/video33`，驱动 `msm_vidc_driver` / `msm_vidc_v4l2`。QUERYCAP/ENUM_FMT已成功，解码器输入H264/HEVC/VP90，输出Q12C/NV12/NV21；编码器输入Q12C/NV12/NV21，输出H264/HEVC等。当前未映射入LXC。

第2项**只验证到能力和格式枚举**；尚未验证buffer allocation、DMA-BUF/MMAP、STREAMON、帧队列与GStreamer/FFmpeg通用插件兼容。不能仅凭NV12就宣布可直接硬解。`/dev/video0/1`分别是cam-req-mgr/cam_sync，也不是可以当作USB摄像头读取的普通视频流。Android的DRM节点属于显示控制器，不能替代这些视频编解码节点。

## 本轮重新调研的已有工作

| 路线 | 核对到的实现 | 对本机的判断 |
|---|---|---|
| GStreamer androidmedia 1.28.5 | 官方已有编码/解码插件，NDK和JNI后端；meson明确要求Android host、JNI和Android库 | 可复用codec状态、格式、排空逻辑；不是向Alpine补装一个.so就能工作 |
| FFmpeg MediaCodec 8.1.3 | 已有硬编和硬解，支持命名codec、NDK路径等；Termux构建启用相关能力 | Android侧工具/实现可复用；不自动成为Linux GNOME或Firefox的后端 |
| Sailfish gst-droid / droidmedia | droidmedia #133于2026-09-02合入Android15/16支持；gst-droid #87修复NV12 stride/slice-height和buffer bounds导致的崩溃 | 不能再以“没支持Android16”排除它；但依赖Android平台库、libhybris及服务适配，与保留完整Android主系统的架构不同，需要单独评估裁剪和资源所有权 |
| Linux V4L2插件 | 成熟的stateful/stateless编解码框架；本机原厂msm_vidc节点已可枚举 | 值得先做短帧流验证；若通用插件兼容，新增自定义代码可能更少。暂未选为已可部署方案 |
| Firefox平台后端 | 当前官方PDMFactory源码将AndroidDecoderModule置于MOZ_WIDGET_ANDROID路径；Linux使用自己的平台/FFmpeg后端 | GStreamer插件不能直接让Linux Firefox获得MediaCodec硬解；网页播放解码和WebRTC硬编码还需分别对接和验收 |

来源与许可：GStreamer androidmedia LGPL-2.1-or-later、FFmpeg相关文件LGPL-2.1-or-later（完整构建的许可取决于启用选项）、droidmedia所查核心文件Apache-2.0、gst-droid所查插件LGPL-2.1-or-later、Mozilla所查文件MPL-2.0；以文件头为准。此轮未把这些项目代码并入产品。

- [GStreamer硬件编解码概览](https://gstreamer.freedesktop.org/documentation/tutorials/playback/hardware-accelerated-video-decoding.html)
- [GStreamer1.28.5 Android插件构建条件](https://github.com/GStreamer/gstreamer/blob/1.28.5/subprojects/gst-plugins-bad/sys/androidmedia/meson.build)
- [FFmpeg MediaCodec编码实现](https://github.com/FFmpeg/FFmpeg/blob/n8.1.3/libavcodec/mediacodecenc.c)
- [droidmedia Android15/16合并PR](https://github.com/sailfishos/droidmedia/pull/133)
- [gst-droid NV12修复](https://github.com/sailfishos/gst-droid/pull/87)
- [Sailfish多媒体架构](https://docs.sailfishos.org/Reference/Core_Areas_and_APIs/Multimedia/)
- [Firefox PDMFactory](https://github.com/mozilla-firefox/firefox/blob/main/dom/media/platforms/PDMFactory.cpp)

固定版本源码、PR补丁及内容SHA256在 `.work/refs/phosh-codec-20260923/upstream/sources.json`；Firefox main是当时下载快照，不冒充当前安装154.0包的逐行一致源码。第29篇的初步研究不足以替代本轮这些变化的核对。

## 下一阶段怎样接入

先用隔离的短测试验证原厂V4L2节点能否由现有GStreamer/FFmpeg完成编码和解码，核对帧数、PTS、NV12布局、flush/EOS与失败释放，再决定是否作为默认入口。当前不为尚未验证的接口扩大LXC权限。

若原厂驱动依赖私有控制或buffer接口，使直接适配成本更高，则复用已工作的Android MediaCodec，增加APK侧codec服务及Linux GStreamer后端：

```text
播放器/相机的GStreamer流水线
  ↔ Linux编解码元素
  ↔ 私有本机协议（控制/PTS/缓冲FD）
  ↔ APK MediaCodec
  ↔ Android原厂高通硬件编解码器
```

普通共享内存可以先验正确性，但解码后的1080p NV12约3.1MB/帧，30fps单向约93MB/s；BGRA更大。最终还要评估AHardwareBuffer/DMA-BUF共享、格式导入、Fence、释放及软件回退，不能把“计算放到硬件”与“端到端已经省电”混为一谈。

实施顺序可先覆盖GNOME播放器硬解与相机硬编码，再单独处理Firefox播放和WebRTC。相机可以研究Camera2→encoder input Surface，但让GNOME Snapshot自动使用它仍需适配应用流水线，不能把Android端独立录像冒充GNOME相机硬编码。所有路线均以保持全局SELinux Enforcing为前提，最终用应用实际选中的codec与真实产出验收。

## 本地证据

目录 .work/refs/phosh-codec-20260923（历史材料已移除）：探针源和dex、硬件能力JSON、两份MP4、电脑解码验证、V4L2格式查询、Linux插件审计、上游来源和校验清单。探针及样本已从手机临时目录清理；无新增常驻服务、无APK重装、无容器重启。本轮没有改成硬编硬解默认，也没有更新ROM或刷机包。
