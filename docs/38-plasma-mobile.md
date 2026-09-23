# 独立 Plasma Mobile 环境：版本目标、发行版选择与部署状态

2026-09-23。用户要求第二套桌面达到 **Plasma Mobile 6.5**，随后明确回答 **“可以用更新稳定版”**。当前不再锁定6.5.x；此前6.3.6方案已撤回。以下保留6.5.6源码调查作为历史基线，发行版建议已调整为Ubuntu26.04LTS ARM64。

**本轮实施更新：Ubuntu26.04、Plasma Mobile6.6.5、定制KWin6.6.6已部署；桌面、GPU、触摸和Rime中文输入均已通过实机验收。当前实施状态以[40篇](40-plasma-mobile-integration.md)为准，以下“仅研究/未部署”描述属于实施前的选型记录。**

部署目标保存在 [plasma/target.json](../plasma/target.json)。它同时记录原始目标与已部署版本；实际验收边界以40–42篇为准。

## 实施前的发行版选型：Ubuntu26.04LTS ARM64

结合用户希望较新桌面、标准Linux软件兼容和后续少手工配置的诉求，推荐最小Ubuntu26.04LTS用户空间，加官方仓库配套的Plasma Mobile 6.6系列。判断依据是包供应和维护成本，尚未进行本机Ubuntu性能、会话或GPU验收。

- [Ubuntu包搜索](https://packages.ubuntu.com/plasma-mobile)列出resolute及updates中的6.6系列，支持ARM64；比Debian13默认6.3更符合目标，避免先自行回移整套Qt/KF依赖。[KCoreAddons](https://packages.ubuntu.com/resolute/libkf6coreaddons6)为6.24，并依赖Qt至少6.10.2。单包页/搜索缓存可能存在更新时差，实际ARM64索引核对另存 `upstream/ubuntu-evaluation/arm64-package-check.json`，安装时仍需APT签名与依赖求解。
- Ubuntu保留glibc、APT和常规systemd用户空间，可在独立LXC中按需安装移动桌面。建议不是给手机刷Ubuntu原生系统，也不要求安装完整PC桌面元包。
- [Ubuntu生命周期](https://ubuntu.com/about/release-cycle)列明26.04LTS支持ARM64，基础系统Main的标准安全维护到2031；Plasma Mobile等属于Universe，不能将Main的维护承诺套用到全部KDE包或我们的自编补丁。
- Debian13/Mobian稳定版：默认桌面低于目标，自行回移Qt/KF/Plasma的成本较高；Mobian配置经验仍可参考。
- Fedora：官方有Plasma Mobile包，包页当前已进入6.7系列；[官方包页](https://packages.fedoraproject.org/pkgs/plasma-mobile/plasma-mobile/)能证明更新供应，但本轮没有核对Fedora ARM64完整依赖索引。其更新节奏更适合追随新桌面；当前更看重减少维护变动，故Ubuntu优先。
- KDE neon：此前已核对Noble/ARM64索引中的Plasma Mobile6.7.0，新版现已符合版本要求；其持续更新Qt/KDE栈带来的适配回归频率，是本项目将其列为备选的原因。
- postmarketOS：移动配置成熟，但仍是Alpine/musl路线；v25.12当时提供6.5，现已在[官方生命周期](https://docs.postmarketos.org/pmaports/main/releases.html)列为EOL，不能为了6.5固定到已结束维护的旧系统。若选它应研究当前受支持版本；本项目偏向glibc兼容因此不优先。

最终桌面包的小版本按同一发行版已发布稳定更新统一解析；不能因各网页更新时差要求所有包字符串完全相同，更不能人为混入其他发行版库。KGSL定制Mesa、KWin的嵌套Wayland输出及Android音视频/设备桥仍要单独移植验证，发行版升级不等于这些适配自动完成。

本轮仅更新目标与选型研究，没有向设备添加Ubuntu源、替换rootfs或改动原Phosh。

实际从Ubuntu ports的resolute、resolute-updates下载并读取ARM64 Universe索引后的候选版本如下。此处是同一发行版提供的维护版本差异，不是手工跨源混库；后续仍需完整APT求解。

| 软件包 | 本轮ARM64候选版本 |
|---|---|
| plasma-mobile | 6.6.5-0ubuntu0.1 |
| kwin-wayland | 4:6.6.6-0ubuntu0.1 |
| plasma-workspace | 4:6.6.6-0ubuntu0.1 |
| plasma-keyboard | 6.6.6-0ubuntu0.1 |
| libqt6core6t64 | 6.10.2+dfsg-7 |
| libkf6coreaddons6 | 6.24.0-0ubuntu1 |

索引URL、SHA256、完整所选包Depends与Filename均在上述研究JSON中；尚未执行Ubuntu根文件系统部署。

## 先前6.5.6目标的源码依赖核对

[KDE 6.5.6发布公告](https://kde.org/announcements/plasma/6/6.5.6/)日期为2026-03-10；[源码发布清单](https://kde.org/info/plasma-6.5.6/)包含plasma-mobile。使用KDE官方GitHub镜像的v6.5.6标签核对CMakeLists，原文件保存在 `.work/refs/plasma-mobile-20260923/upstream/target-6.5/`。

| 组件 | 6.5.6源码要求 | Debian 13默认仓库核对结果 |
|---|---|---|
| Plasma Mobile | 6.5.6目标；显式依赖匹配的KWin与KPipeWire | plasma-mobile 6.3.6-3 |
| Qt | 至少6.9.0 | Qt Core 6.8.2，低于要求 |
| KDE Frameworks / ECM | 至少6.18.0 | KCoreAddons 6.13.0，低于要求 |
| KWin | 6.5.6；Wayland至少1.24、Wayland protocols至少1.45 | 需连同图形和协议依赖重新核对、打包 |

直接源码证据：[Plasma Mobile](https://github.com/KDE/plasma-mobile/blob/v6.5.6/CMakeLists.txt)、[KWin](https://github.com/KDE/kwin/blob/v6.5.6/CMakeLists.txt)、[Plasma Workspace](https://github.com/KDE/plasma-workspace/blob/v6.5.6/CMakeLists.txt)、[libplasma](https://github.com/KDE/libplasma/blob/v6.5.6/CMakeLists.txt)。它们共同要求Qt6.9/KF6.18，Workspace还显式要求同版本的一批Plasma库；不能仅替换桌面外壳。

发行版对照：[Debian plasma-mobile](https://packages.debian.org/trixie/plasma-mobile)、[Qt Core](https://packages.debian.org/trixie/libqt6core6t64)、[KCoreAddons](https://packages.debian.org/trixie/libkf6coreaddons6)。实施时还需以实际ARM64 APT索引和依赖求解为准。

## 固定6.5.x时的软件来源调查（历史基线）

1. 首选可验证的ARM64完整配套包；每个来源都要核对版本、架构、依赖和签名，不能仅凭“提供Plasma”认定满足6.5目标。
2. Debian13默认仓库本身不满足目标。本轮Debian全套件搜索页也没有列出trixie-backports的plasma-mobile；这是查询结果，不表示以后不会提供。
3. Debian Snapshot接口返回的6.5历史源包为6.5.0至6.5.4。它可用于复用Debian打包规则；尚未证明6.5.6存在可直接安装的Debian二进制闭包。冻结旧testing整套系统也不等同于Debian13稳定版。
4. Mobian适合借鉴移动端包选择和配置。已读取mobian-trixie的 `include/packages-plasma-mobile.yaml` 与base配方；其中移动桌面通过 `mobian-plasma-mobile` 元包选择。实际查询trixie、trixie-updates、staging的main/ARM64索引，前后两个分别提供0.5.3和0.5.6元包，三个索引均未列出plasma-mobile本体。元包版本不是桌面版本，此轮未找到Mobian直接提供6.5的证据。
5. KDE neon提供ARM64索引，但它的仓库以Ubuntu noble为基础；不能将其当作Debian13的兼容软件源直接加入。本轮user/noble/main/ARM64索引的plasma-mobile为6.7.0，不能直接实现指定的6.5目标。仅研究，未向设备添加此源；未核查其所有历史池或其他通道。
6. 若无合适现成配套包，采用Debian稳定基础上的受控源码回移：固定Qt/KF/Plasma来源、生成ARM64 deb包和本地仓库，统一依赖解析与运行时搜索路径。此路径尚未构建验证，也不能描述为“只编译一个包”。

研究索引保存在 `upstream/target-6.5/repository-research.json` 与 `repository-package-check.json`；仅查询的仓库元数据尚未进行安装用签名验证。源码、研究结论和部署验收分别记录。

## 实施前的设备状态（历史记录）

- 已安装独立Android入口APK，应用ID `dev.moto.plasma`；现有Phosh保持 `dev.moto.phosh`。
- 新容器名 `plasma`，独立rootfs、显示socket、音频路径和共享目录。容器引导成功过，但尚未安装完成Plasma/KWin桌面。
- 设备当前rootfs仍是早期forky引导环境，已停止；Debian trixie rootfs归档已下载、校验，尚未部署切换。不能把计划的Debian13或Plasma6.5.6写成已安装状态。
- 独立APK、管理脚本和C启动器为后续部署准备，不能以存在图标代替桌面可用验收。
- 原Phosh完整运行环境继续保留。Magisk故障及用户授权重启的恢复过程见[39篇](39-magisk-daemon-crash.md)。

## 当时提出的实施与验收约束

先核对所选发行版的ARM64包依赖与实际源码版本，再部署新容器；需要同时处理KWin嵌套Wayland、KGSL/定制Mesa的glibc构建、正常用户会话、触摸与输入法、顶部挖孔、全屏、刷新率和Android硬件桥。

KWin的嵌套Wayland渲染后端与现有Phoc不同，Phoc补丁不能直接当作KWin支持证据。此前6.3.6、6.5.6源码分析保留作历史材料，实际适配应重新对照最终所选包的源码版本。

Phosh重启恢复发现Android GPU设备号会变化，见39篇。Plasma启动器部署前也需采用当前节点major/minor生成精确设备规则，不能继续使用引导配置中的478:0快照值。

需要实机验收独立入口与回退、正常用户GPU绘制、中英文输入、锁屏退出、声音、网络信息、摄像头/麦克风、视频编解码、浏览器与后台恢复。不会把Alpine musl库直接复制给Debian glibc使用，也不会因安装某个桌面元包就标记这些硬件能力完成。

Plasma软件各组件许可按上游LICENSES与Debiancopyright文件保留；本轮仅归档源码片段供分析，未打包发布改版二进制。
