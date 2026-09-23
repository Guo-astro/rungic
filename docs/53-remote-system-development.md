# 远程系统开发：源码核对与Vendor同步

2026-09-23。范围为Android宿主、原生Wayland/GPU、Plasma及Linux系统能力，不包含ROM。用户要求核对实际修改，随后选择直接vendor到本地。当前采用**一个私有集成仓库保存完整开发源码**：`kevinzhow/range-dev`。

## 本次核对的结果

这次比较了固定版本原始归档、Git里的补丁和本地保存的修改树，并以`patch --fuzz=0`实际重放。不能把`.work/build`里某份历史快照当成最新版本。

| 范围 | 核对结果与处理 |
|---|---|
| KWin | 五组正式补丁全部从Ubuntu 6.6.6源包重放成功。旧本地工作树缺少后来的SHM录屏和显示设置修改；撤销这两组补丁后，与旧树的源代码一致。已vendor完整moto5源码和打包修改 |
| Mesa / Turnip / Zink | 本地源码与保存的KGSL提交归档一致，无额外未保存修改；整个固定提交已vendor |
| Android原生Wayland后端 | `native/plasma/`的701个跟踪项已在远端。相对Winland基线，11个文件有改动，新增`frame_clock.rs`和`gpu_allocator.rs`；Smithay/Winit保留在本仓库，不另设子模块 |
| KScreen | 四个修改文件和Android协议头已被补丁/共享文件覆盖；构建时的依赖版本调整现直接保存在vendor |
| Plasma面板、窗口、键盘、Settings | 补丁重放结果与保存的Panel-fixed.qml、fixed-main.qml、inputlisteneritem-fixed.cpp、settingsapp.cpp逐字节相同，均已vendor |
| libcamera / Plasma Camera | 生产源码改动被现有补丁覆盖。保存树的许可证/Flatpak文件差异是符号链接被展开，内容相同；vendor保留上游链接与版权 |
| Qt Multimedia | PulseAudio修复已进入正式vendor；视频duration候选可重放且与保存文件相同，但未验收，因此不混入正式源码 |
| FFmpeg / Snapshot | 编解码注册和软件回退命名原先藏在FFmpeg构建脚本的字符串替换中，现直接保存到vendor源码；Snapshot重放与本地修改树一致 |
| Firefox移动配置 | 前一轮发现39个运行文件未跟踪，已在`0b7325c`补入`plasma/firefox-mobile/` |
| 自有桥和运行服务 | Android APK、共享媒体/网络/剪贴板、账户、Rime、录屏、显示/电源服务已跟踪；旧发布归档中没有另一个遗失的plasma/tools源码文件 |

详细逐文件比较见[审计记录](../provenance/source-sync-20260923.json)，组件版本和源码哈希见[Vendor清单](../vendor/manifest.json)。比较针对本机保存的源码；没有声称已重新抓取手机全部运行文件或完成远端全量编译。

## 现在到哪里改代码

| 修改内容 | 唯一源码入口 |
|---|---|
| KWin合成、Wayland输出、AHB分配、录屏 | `vendor/kwin/` |
| KGSL/Freedreno、Turnip、Zink | `vendor/mesa/` |
| Android EGL呈现、帧时钟、DMA-BUF租约 | `native/plasma/src/android/` |
| Java宿主、Surface、触摸、刷新率、Android硬件服务 | `plasma/native-apk/` |
| KDE设置、键盘、面板、Portal、Qt及相机标准接口 | `vendor/`内对应组件 |
| 共享硬件桥、服务配置、构建和部署 | `shared/`、`plasma/`、`tools/` |

KWin + Vulkan开发至少同时需要前三行与Android宿主。当前生产KWin仍为GLES，Turnip/Zink及性能工具已经在仓库；原生Vulkan KWin合成器尚未实现，不是代码漏传。量化基准见[51篇](51-plasma-vulkan-benchmark.md)。

几个共享文件使用仓库内相对链接，构建准备工具将它们展开。历史补丁仅供查来源，规则见[补丁说明](../plasma/PATCHES.md)。

## 两台机器与其他仓库如何同步

1. 本机和K8都clone同一个私有`range-dev`；普通`git pull --ff-only`即可得到完整源码，不需初始化子模块，也不依赖本机`.work/refs`。
2. 每项工作开功能分支，直接修改vendor及自有代码。一个功能若同时改变KWin、宿主和共享协议，放在同一组可审阅提交中，避免分别同步导致版本不匹配。
3. 提交前运行`python3 tools/audit_git_scope.py`，查看`git status`与diff。构建用`tools/stage_vendor.py`生成`.work`副本，产物不提交。
4. commit并push功能分支，另一台机器fetch同一提交。`range-dev`提交SHA是整套源码的版本；不要用scp/rsync覆盖另一台机器的工作代码。
5. 其他产品仓库需要使用这套实现时，记录消费的`range-dev`提交SHA，修改回到这里合入，再更新引用。当前不建立第二份可独立修改的副本。

上游升级时保留许可证和来源，以独立提交记录新基线及我们的适配，使用Git合并处理冲突。首个纯上游导入提交是`dffc717e57e4db2396b9b137c1e1b7fcb6633f14`，可直接对比：

```sh
git diff dffc717e57e4db2396b9b137c1e1b7fcb6633f14 HEAD -- vendor/kwin
python3 tools/stage_vendor.py kwin
```

这采用Git普通目录和提交的工作方式；没有额外引入repo管理器、submodule或多个GitHub fork。[Git官方分支工作流](https://git-scm.com/book/en/v2/Git-Branching-Branching-Workflows)作为协作参考。此前评估过固定补丁队列和submodule，现按用户选择直接vendor。

## 已完成与仍有边界的部分

已完成13个组件的源码导入、正式修改落盘、上游基线分离、构建准备入口及现有主要构建脚本切换。SDK/NDK、Rust依赖下载、Android链接库、Ubuntu ARM64开发包和完整构建环境仍要准备；原媒体/显示重打包脚本仍依赖已有基础deb和构建路径。源码齐备不等于已具备一键CI或可在任意机器编译。

部分历史诊断探针仍在`.work`，不属于运行实现；后续可整理为回归测试。ROM、分区镜像、用户媒体和完整rootfs不是这次远程系统开发的必要代码。此次只变更本地/Git源码，没有重新编译安装手机系统或改变GPU后端。
