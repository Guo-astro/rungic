# 私有仓库与本地工作目录

2026-09-23。按用户要求，将需要同步的文件整理为源码、文档、测试数据和来源记录；其余材料集中在`.work/`。随后按用户新要求停止维护Phosh，仅保留Plasma及其共享依赖。目录整理完成后，用户指定同步到私有仓库`https://github.com/kevinzhow/range-dev`，使用`main`分支；本次本地整理与仓库同步不操作手机。

后续按用户要求已将13个上游组件及正式修改导入`vendor/`，该目录现在随Git同步；`.work/deps`中的旧源码仅为历史副本。最新源码边界与协作方式见[53篇](53-remote-system-development.md)。下方迁移统计是Vendor导入前的历史记录。

## 目录结构

```text
moto/
├── README.md / AGENTS.md       项目入口与工程约定
├── .agents/skills/            项目共享 Skill 与执行参考，随 Git 同步
├── docs/                      设备、ROM、容器、Plasma实施文档
│   └── research/              可复用的硬件接口与早期研究结论
├── plasma/                    KDE适配、Android APK、配置、构建脚本
├── native/plasma/             Rust/Smithay原生Wayland后端及锁定依赖
├── vendor/                    KWin、Mesa、Qt及桌面/媒体组件的正式源码
├── shared/                    共享媒体、网络、剪贴板和GPU诊断代码
├── tools/                     管理、刷机、审计和性能测试工具
│   └── toolchains/            Android编译器包装脚本
├── kernel/ lxc/ docker/ cutout/ 内核、容器、ROM相关配置和补丁
├── benchmarks/                选定的性能测试原始数据与结果
├── provenance/                上游来源、版本、包清单和校验值
├── signing/development/       用户指定同步的开发APK签名密钥
└── .work/                     全部不入Git的本地工作材料
    ├── build/                 Rust等构建缓存
    ├── deps/                  Mesa、FFmpeg、Snapshot和本地依赖库
    ├── downloads/             上游原始归档
    ├── secrets/               其他本地签名材料与凭据
    ├── cache/                 Python等缓存
    ├── artifacts/             其他本地产物
    ├── refs/                  原始日志、截图、媒体和历史构建材料
    └── migration/             本次路径映射、校验和删除清单
```

`plasma/native-apk/assets/xkb.zip`是APK必需的键盘资源，连同版权说明进入Git。用户后续明确要求同步开发用APK私钥，故`signing/development/launcher-signing.p12`也进入私有Git仓库；其他APK、DEB、镜像、压缩产物、密钥和实机媒体仍不入Git。工作区外已有ROM/SDK/内核工具链仍按原位置使用，本次只整理moto目录。

## Phosh移除范围

已移除Phosh专属Android入口、会话、桌面补丁、原生后端副本、部署工具、22–27篇专属安装记录，以及本地Phosh构建/测试目录。没有将这些实现作为待维护归档继续收入仓库。

以下仍被Plasma使用，先提取再清理原目录：

- `shared/media/`：Camera2到PipeWire的camera-source、麦克风/摄像头需求管理、MediaCodec客户端、GStreamer/FFmpeg适配、Snapshot补丁。
- `shared/platform/`：NetworkManager D-Bus桥和剪贴板桥。
- `shared/graphics/`：GPU及共享缓冲诊断。
- `native/plasma/`：Plasma正在使用的完整原生后端，含Smithay/Winit本地路径依赖及原许可证。
- `.work/deps/`：Plasma构建继续需要的Mesa、FFmpeg、Snapshot源码和Android/libxkbcommon依赖库；开发签名身份现位于`signing/development/`。

28–35篇中可复用的硬件接口研究移到`docs/research/`并标明历史状态。文档中保留的Phosh历史描述不代表该桌面仍受支持；最新实现看Plasma集成文档。原始排障记录已有删除，不能把历史路径当成可执行安装步骤。

## 构建与后续文件位置

原生构建入口仍为`bash plasma/build-native-core.sh`，现在从`native/plasma/`读源码，使用`tools/toolchains/`，输出到`.work/build/native-target/`和`.work/refs/plasma-mobile-20260923/native-libs/`。

APK入口仍为`bash plasma/build-apk.sh`，输出在`.work/refs/plasma-mobile-20260923/`，默认使用`signing/development/launcher-signing.p12`签名，也可用`MOTO_APK_KEYSTORE`指定同类型密钥路径。它不安装APK或重启手机。本次移动的是原有开发签名身份，没有重新生成密钥；`.gitignore`与审计工具仅对此指定文件增加例外。

日常开发先执行：

```bash
sh tools/dev-setup.sh      # 首次或依赖变化时：在 .work/venv 建开发用 Python
source tools/work-env.sh
```

这会将Python缓存和Cargo输出定向到`.work/`，并启用`.work/venv`。开发依赖列在`tools/dev-requirements.txt`，目前是PySide6（在无桌面环境下测试QML与Qt逻辑，例如`tools/tests/test_call_cards.py`）和pytest。用户于2026-09-29明确：PySide6这类依赖只服务于开发时的原型与测试，不进入镜像或软件包；进入生产的部分用C++等重写，或使用设备自带的库。项目Cargo配置也指定本地构建目录。新的日志、截图、录音录像和下载均应写到`.work/`；只有经过挑选、适合复算的证据再放入`benchmarks/`或`provenance/`。

## 校验与边界

搬迁前记录64,184个文件/符号链接、约5.17GB逻辑大小的路径、SHA256或链接目标；初次搬迁后逐项复核一致，再执行用户明确要求的Phosh删除。完整映射、删除清单和验证日志留在`.work/migration/20260923-layout/`。

重新检查Git候选范围：

```bash
python3 tools/audit_git_scope.py --output .work/audits/private-candidates.json
python3 tools/analyze_plasma_gpu.py benchmarks/plasma-vulkan-20260923
```

候选检查使用临时Git目录，不创建工作区仓库或修改索引。它检查有限的密钥/账户文件名、令牌格式、大文件及外部符号链接；不表示已经适合公开。私有文档仍保留设备身份、本机路径和局域网地址。

这次完成目录迁移和本机路径适配，不等于全新机器一键构建：SDK/NDK和部分容器构建依赖仍需准备，历史ROM一键包也未重新整合全部Plasma改动。Winland固定基线`4269ec048e83133102d00464fd4c23af44d84707`的本地归档缺少根LICENSE（README标MIT、当时元数据license为null）；保留来源与子依赖许可证，未自行为整棵树重新授权。公开前需另行核实来源记录。

本机迁移回归已通过：原生后端离线release构建、APK打包与签名验证、48个Python文件及35个Shell入口的语法检查；迁移后重新分析Vulkan数据，结果与原结果完全一致。当前Git候选约1,031个文件、17.6MiB；有限敏感模式检查及“被忽略文件是否落在.work之外”的检查均无发现。本次构建APK另存`.work/build/apk-migration-check/`，没有覆盖已验证的发布APK或安装到手机。
