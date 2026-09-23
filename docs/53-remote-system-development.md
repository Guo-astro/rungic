# 远程系统功能开发所需材料

2026-09-23，核对私有仓库range-dev及本地.work。范围为Plasma/Android宿主/Linux系统功能，不涉及ROM刷机或内核移植；未假设远程K8的CPU架构和已安装工具链。

## 已在仓库的主要实现

| 功能 | 源码入口 |
|---|---|
| Android窗口、挖孔、触摸、刷新率、网络、相机、音频和MediaCodec服务 | plasma/native-apk/ |
| 原生Wayland/GPU共享缓冲与输入后端 | native/plasma/，包含Smithay/Winit本地依赖 |
| Linux媒体、编解码、网络与剪贴板桥 | shared/ |
| KWin/KScreen、Qt、libcamera、Portal、桌面设置与键盘修改 | plasma中的patch、libcamera/及对应构建脚本 |
| Rime、录屏、账户设置、亮度/电源/显示管理 | plasma/rime、recording、account及各Python服务 |
| 图形对照数据与分析脚本 | benchmarks/、plasma/bench、tools/ |
| 开发APK签名 | signing/development/launcher-signing.p12，按用户要求同步 |

本轮发现的实际漏项是Firefox移动配置：39个JS/CSS/配置文件、约73KB，原来只在.work，其中包含Android16移动UA及站点兼容规则。现已移入`plasma/firefox-mobile/`，逐文件哈希核对未改内容。它属于运行代码，不能随着Phosh移除而遗漏。

## 仍未同步或尚未形成可复现入口

| 项目 | 当前实际情况 | 远程开发需要补什么 |
|---|---|---|
| 上游桌面与库源码 | KWin、KScreen、Plasma Settings/Keyboard、Qt Multimedia、libcamera、FFmpeg、Snapshot完整源码留在.work；仓库主要保存补丁与版本 | 按固定版本获取源包，验证哈希，按顺序应用补丁；不需要把所有下载缓存提交Git |
| Mesa KGSL源码 | .work/deps/mesa-kgsl，固定lfdevs提交98f3d6229d61452cef80f8563af7c56ae599dc14；本地树与保存的该提交归档逐文件比较无差异 | 下载这个固定分支提交，使用仓库的Mesa构建/打包入口；不能用任意发行版Mesa替代 |
| Android工具链与依赖 | APK脚本引用本机SDK路径；编译器包装仍默认使用本机Clang/NDK。libxkbcommon及Android链接库目前只有.work中的现成so | 补SDK/NDK固定版本安装入口、libxkbcommon Android源码构建及依赖准备，统一环境变量 |
| Linux构建环境 | 有Ubuntu包清单和组件脚本，尚无完整开发容器或统一bootstrap；一些路径为/root/moto-* | 准备匹配的Ubuntu ARM64/Qt/KF6环境；远程架构不同时安排交叉构建或受支持的仿真 |
| 诊断与回归程序 | 主性能工具已同步；若干音频时钟/注入/停止探针和输入故障试验脚本仍在.work | 挑选能复用的程序变成fixtures/tests；不上传实机录音、录像、profile来充当测试夹具 |
| 统一部署/验收入口 | 组件构建安装流程分散，部分需已有rootfs和已安装包；管理工具依赖本机ADB与设备编号 | 补参数化部署和版本清单。GPU/触摸/摄像头/麦克风最终回到实际手机验收 |

因此，目前远程可以开展源代码审阅、功能实现和部分纯逻辑测试，但不能仅凭clone就保证完整构建、启动并验收与手机相同的系统。原厂ROM、分区镜像和用户数据不属于这项远程系统开发的必要代码。

建议下一项工作是完善远程开发环境与依赖bootstrap，并将可复用诊断脚本整理成测试入口。该工作尚未在本次审计中实现，不能把上面的清单当作已有一键CI或完整开发容器。
