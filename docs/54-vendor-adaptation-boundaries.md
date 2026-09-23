# Vendor适配的职责边界与可下沉项

2026-09-23。用户问：现有修改是否必须发生在Vendor，哪些可以下沉。本轮检查`dffc717e..d1301f2e`实际diff、固定版本扩展接口和已有桥接代码；这是架构评审，没有改变运行源码或重新部署。下方“可迁移”是建议，不是已经完成的重构/验收。没有完成所有补丁在最新上游的修复状态核查，实际实施前仍须逐项继续研究。

Vendor解决源码同步。修改是否属于上游组件，要看接口与职责。目标是让设备能力尽量通过标准服务/插件共享，同时保留必要的组件接入与组件自身缺陷修复。把一个函数移到`shared/`但仍依赖同一内部接口，并不代表消除了对vendor的修改或版本耦合。

## 逐项判断

| 当前修改 | 判断与合适位置 | 不能跳过的条件 |
|---|---|---|
| Settings根据KCM名字检查platform.sock，直接启动Android网络/蓝牙/电源界面 | 优先抽离为独立KCM插件；Android特有控制调用共享平台服务。普通网络状态继续补已有NetworkManager桥等标准接口 | 不需要把Android路由硬编码进Settings宿主；模块发现、分类、隐藏不能使用的原模块、权限与现有入口必须回归。独立KCM不能替代尚未实现的标准网络/蓝牙服务 |
| KScreen读取android-display.json、轮询、调用display-set、保存/回滚策略 | 硬件能力查询和策略执行下沉到统一显示后端。分辨率、模式、缩放继续走KWin/LibKScreen标准链路；界面仅保留展示和用户选择 | 当前有KWin和KScreen两个控制入口。后端须处理事务、异步状态、回滚和宿主变化；不能仅共享一个socket头文件就认为职责已统一 |
| “自动”刷新率与当前物理刷新率展示 | 策略执行属于后端，选项属于UI。可保留薄KCM扩展或独立模块 | Android在30/60/90/120间切换的策略，不等于VRR/Adaptive-Sync。不能谎报标准VRR能力来免除UI修改；保留当前“显示”页面体验可能仍需少量UI接入 |
| Snapshot中的Moto摄像头时钟特判、motoh264enc码率/rank | 优先核查共享PipeWire/GStreamer时钟、设备创建和编码协商层。码率默认值已存在于共享GStreamer插件，重复默认设置可评估删除 | Snapshot另有硬编码的H.264/硬件编码器检测名单；提高插件rank不会自动修正这份名单或硬件开关逻辑。应将应用探测改为通用能力查询，必要时保留可上游化的通用补丁。时钟问题需实测，尚不能保证只调PipeWire配置就能去掉应用补丁 |
| FFmpeg中的Moto codec注册和libx264_sw命名 | MediaCodec的实现和IPC已在shared；vendor中保留薄FFmpeg codec入口。软件回退命名可进一步审查是否能恢复标准名称 | 当前8.1.2的codec_list是构建生成的静态列表，不是GStreamer式任意外部codec插件加载器。另写.so不能直接消除注册改动。更换VA-API/V4L2等接口需要真实后端、能力和应用验收，不只是换名字 |
| libcamera virtual pipeline消费已有PipeWire摄像头 | 已处于正确共享层：所有libcamera客户端共同受益。可以收拢成独立pipeline模块，减少对virtual代码的侵入 | 固定0.7.0的Pipeline Handler使用内部API、Meson源码列表和工厂注册，仍编译进libcamera。它不是稳定的独立外置.so插件。完全消除libcamera修改需要不同标准硬件入口或上游接纳，成本并不更低 |
| KWin直接实现AHardwareBuffer租约socket与DMA-BUF分配 | 可先提取共享分配/租约库；更进一步研究Mesa GBM外部backend，让使用GBM的消费者共同复用 | 当前Mesa确有GBM_BACKEND/GBM_BACKENDS_PATH及版本化backend接口。但KGSL不是DRM render node；EGL设备发现、导入导出、format/modifier、stride、生命周期、跨进程同步都要验证。存在接口不代表插件方案已打通 |
| KWin的flat-output、绕过subsurface与部分协议限制 | 优先完善Android原生Wayland宿主，恢复符合协议的surface tree、缩放、buffer/damage及呈现语义，再评估撤销对应KWin特判 | 不把“宣布支持协议”当实现。DMA-BUF v4反馈与设备身份尤其需要KGSL实证，不能伪造DRM设备；部分设备选择接入仍可能保留 |
| KWin中两处glFinish等待 | GPU同步与缓冲生命周期应由共享图形边界协同解决，KWin保留渲染提交点的必要接入 | Android/GL/Vulkan双方必须真实传递并等待兼容fence。不能直接删glFinish，也不能假定KGSL支持DRM syncobj。需检查破帧、提前复用和泄漏，再量化延迟/CPU/GPU占用 |
| KWin idle inhibition经私有D-Bus方法转发 | 可改为通用嵌套Wayland idle-inhibit转发，Android宿主管理实际屏幕常亮；D-Bus应用的抑制仍由共享电源服务处理 | 目前宿主handler只计数/日志，没有完整执行常亮。KWin仍需聚合子客户端可见性并向外层传递；不能把所有窗口一律永久常亮 |
| 录屏屏蔽plasmashell、SHM读回翻转 | 属于KWin录屏语义和纹理变换边界，先保留并研究通用修复；截图/录屏消费者应共同受益 | 外层Android只看见嵌套桌面表面，不掌握KWin内部窗口排除语义。不能简单把录屏移到Android来替代Portal行为。翻转应以纹理变换约定修正，不复制到每个播放器 |
| KWin SHM与libcamera DMA heap权限访问 | 属于分配/权限接口边界，可与共享分配层一并研究；当前窄范围修改保留 | 不能靠放宽整个SELinux来换取少改vendor。需验证来源标签、映射/读写能力、释放以及同接口的其他客户端 |
| Qt PulseAudio缓冲、Plasma Camera帧元数据/时钟、键盘焦点与菜单生命周期、Settings模型、Portal宽度 | 这些是组件自身缺陷或UI行为。修复应留在对应组件，后续核对上游、回移或升级消除维护负担 | Qt错误的maxlength不能要求所有服务端迁就；应用反复改写已提交帧的元数据，也不能要求硬件后端猜测原始意图 |
| Plasma面板排他工作区、convergentwindows键盘避让 | 属于桌面布局和窗口脚本层；通用修复可提交上游。脚本打包也可使用桌面扩展机制，但不应重建Android硬件通路 | Android提供挖孔几何；桌面决定状态栏布局、窗口工作区及输入法避让。把补丁改为覆盖整份QML仍然要维护上游差异 |

## 源码证据

- `vendor/plasma-settings/src/modulesmodel.cpp:43`：KAuthorize、FormFactors过滤以及三个KCM插件目录；`src/settingsapp.cpp:262`是现有硬编码路由。
- `vendor/kscreen/kcm/kcm.cpp:83`及`vendor/kwin/src/backends/wayland/wayland_backend.cpp:563`：显示查询、策略和输出修改现分布在两侧。共享头仅提供传输，尚不是统一事务后端。
- `vendor/snapshot/aperture/src/camera.rs:151`、`utils.rs:174`、`viewfinder.rs:1002`：时钟特判与codec名单；`shared/media/gst-moto-codec.c`已有硬件分类、rank和4000kbit/s默认值。
- `vendor/ffmpeg/libavcodec/allcodecs.c:962`：生成的codec列表。IPC和主要适配实现已通过符号链接来自`shared/media/`。
- `vendor/libcamera/include/libcamera/internal/pipeline_handler.h:143`及`src/libcamera/pipeline/meson.build`：编译期注册；不要与IPA模块加载混为一谈。
- `vendor/mesa/src/gbm/main/backend.c:113`：外部GBM backend加载；这只是可复用入口的证据，不是本机兼容验证。
- `vendor/kwin/src/core/androidgraphicsbuffer.h`、`src/backends/wayland/wayland_egl_backend.cpp:106`：现有分配租约与同步特判。
- `native/plasma/src/android/backend/wayland/handlers.rs:149`：idle-inhibit目前仅计数/日志；`plasma/power-policy.py`是实际共享电源服务入口。

## 上游机制核验

[KDE KCM官方文档](https://develop.kde.org/docs/features/configuration/kcm/)说明设置模块可独立提供，由plasma-settings/systemsettings/kcmshell6加载；结合本地源码，独立模块是替换宿主硬编码路由的可行方向。

[GStreamer encodebin文档](https://gstreamer.freedesktop.org/documentation/encoding/encodebin.html)提供按profile自动选择和配置编码器的机制；[GstDevice文档](https://gstreamer.freedesktop.org/documentation/gstreamer/gstdevice.html)定义设备创建已配置element的接口。它们支持把设备策略收拢到公共入口，但应用绕过能力枚举、自己维护codec名单时，仍要修复该应用逻辑。

[libcamera Pipeline Handler指南](https://docs.libcamera.org/master/guides/pipeline-handler.html)明确需要将handler加入构建并注册；这一点已对照本地0.7.0源码核实。新增handler沿用上游内部API及其许可，不能当作独立稳定ABI承诺。

## 优先顺序与验收

1. 先拆Settings的设备路由，保留模型bug修复；再统一显示能力/策略后端，保留标准显示KCM的已有功能与必要UI扩展。
2. 收拢GStreamer时间戳、编码默认值与能力查询；交叉验收Snapshot、独立GStreamer客户端、Qt/Firefox各自实际使用的链路。不能以一个应用成功代表全部媒体栈都通过。
3. 针对性能建立共享GPU分配、同步与Wayland宿主改善的独立验证，再逐个撤销KWin特判。验证画面、触摸/缩放、录屏、旋转、休眠恢复、缓冲释放及GLES/Vulkan性能。
4. 应用/框架通用bug修复留在所属组件，逐项追踪上游并设置删除本地补丁的条件。

原生Vulkan桌面合成涉及KWin自己的渲染后端、场景和效果管线，不能仅靠Mesa或外部服务完成。共享图形分配/同步能够让GLES和Vulkan共同受益；真正的Vulkan合成实现仍需在KWin对应层开发。是否值得实施继续以51篇基准及后续端到端验证为准。
