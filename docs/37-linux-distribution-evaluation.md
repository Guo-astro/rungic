# Alpine、Debian、Ubuntu 的取舍与迁移边界

2026-09-23 评估，尚未创建或切换 Debian/Ubuntu 桌面容器。当前运行环境见30/31篇，Firefox输入修复见36篇。

## 对当前目标的判断

Alpine并非有普遍的“系统缺陷”。它使用 [musl、BusyBox、OpenRC](https://www.alpinelinux.org/about/)，轻量、便于控制组成；但我们的目标已从小型Linux容器变成完整Phosh/GNOME移动桌面。对这一目标，建议下一阶段优先验证Debian：使用glibc和常规桌面服务栈，预计能减少外部二进制兼容与会话服务拼接的工作。这是基于架构和生态的判断，不是本机Debian性能/稳定性实测结论。

一个具体差异是 [Mozilla Firefox 154 官方 ARM64 Linux 二进制要求 glibc 2.28 或更新](https://www.firefox.com/en-US/firefox/154.0/system-requirements/)；Alpine使用自己适配musl的发行版构建。换Debian/Ubuntu可减少这类差异，但仍要求软件提供ARM64版本，不能直接运行普通x86_64二进制。

当前部分GNOME会话/login1/polkit缺项，与容器启动和服务集成有关。Debian/Ubuntu的常规systemd用户空间能提供更接近上游桌面的基础，但Android内核、cgroup和LXC服务配置仍需实机验证，不能承诺安装发行版即全部修复。

## 候选与版本取舍

| 选择 | 对本项目的价值 | 需要承担的成本 |
|---|---|---|
| 继续Alpine edge | 现有GPU/输入/音视频已适配，保留成果最直接 | musl兼容、桌面服务拼接、edge版本更新和自编包维护 |
| Debian stable | glibc、稳定基础和标准桌面服务 | 最新Phosh/GNOME可能需要受控回移/自编；不能混装大量testing库假装仍是stable |
| Debian testing | 较新桌面依赖，适合继续跟随新Phosh/GNOME | 滚动变化，不具有stable的稳定性承诺；需要快照、固定版本与回归 |
| Ubuntu LTS | glibc、常见第三方安装说明与常规桌面服务 | LTS仓库桌面组件未必最新；同样需要Android硬件桥与部分自编组件 |

[Mobian](https://www.mobian.org/)及其[开发说明](https://wiki.debian.org/Teams/Mobian/DevelopersGuide)提供Debian移动桌面集成经验，可复用包选择和服务配置。这不表示Mobian能原生驱动本机，也不建议直接刷其他手机镜像。

查询时 [Ubuntu 26.04 Phosh包页](https://packages.ubuntu.com/resolute/phosh)列0.54.0-1，低于本机0.57。[Debian testing包页](https://packages.debian.org/forky/phosh)及不同语言的缓存页面分别出现0.56/0.57，实施时必须再以ARM64实际APT索引核对，不把网页缓存当作确定安装版本。[Debian维护跟踪](https://tracker.debian.org/pkg/phosh/news/)可用于核对更新。最新GNOME应用要逐包核对，不能以GNOME Shell版本替代全部应用版本。

## 怎么换

推荐新建并行LXC容器进行迁移，旧Alpine rootfs保留。无需从头刷Android、重新root或重装宿主Docker。

| 层 | 迁移方法 |
|---|---|
| Android ROM、Magisk、内核、APK显示/设备后端 | 初始保留，核对现有socket和共享目录接口 |
| Debian/Ubuntu rootfs与服务 | 新建ARM64用户空间，配置UID1000、D-Bus、登录/用户会话、共享挂载、代理及启动服务 |
| 定制Mesa/KGSL、Phoc、Phosh、Stevia/portal | 将现有补丁移植到目标版本，使用目标glibc工具链重编；禁止把musl二进制与glibc库混放 |
| GStreamer/MediaCodec、FFmpeg、Snapshot、Firefox集成 | 重编Linux客户端和插件，核验库路径/ABI/沙箱；Android端协议尽量沿用 |
| 用户文件和浏览器数据 | 停止相关应用后复制/备份，检查UID及浏览器版本兼容；共享文件继续使用既有目录 |
| 切换与回退 | 全部关键功能验收后再切APK后端指向；切换时只启动一套接入同一硬件的桌面，失败回到旧容器 |

主要工作量集中在Linux侧重新打包和验收，不是重新发明所有硬件桥。需要逐项测GPU、触摸/中英文输入、顶部挖孔、刷新率、网络设置、音频、摄像头、视频硬编解码、浏览器与休眠恢复。硬件由Android掌握，这些适配不会因换glibc而消失；标准Docker镜像本身有独立用户空间，也不要求跟随桌面发行版迁移。

建议把自编组件变成版本明确的deb包、让依赖由包管理器表达，以减少后续升级时手工复制库。尚未实施，也未测量迁移后的RAM、功耗和性能，不能据发行版名称推断会更省。
