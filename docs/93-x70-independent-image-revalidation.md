# X70 新独立镜像重建与首装复验

2026-09-30，承接 [92 篇](92-x70-android-base-end-to-end.md)，用户要求构建新镜像并重新验证。运行目录 `.work/ci/runs/vantage-20260930-revalidate/`。本轮复用已经实际刷写、核验的 Android/GKI/Magisk 底座，不再次清空 Android；从空白 Rungic runtime、账户和入口数据开始安装。

## 启动故障的复现与修正

现场核对 mibook / x86_64、默认路由 192.168.5.1、GNOME proxy none；下载使用现有代理 192.168.5.45:6152。USB 目标仍为 ZY22MHZKFT / XT2603-1 / vantage，固件 W2WV36.55-75-15、slot a、GKI v7、SELinux Enforcing。重启期间 ADB 5037/5038 会交替接管，每条命令绑定精确序列号。

记录原控制器并临时增加仅针对 start/restart-session 的诊断。复现时 `/sys/fs/cgroup` 为 0700、root:root；用户 systemd 无法创建 `user@1000.service/init.scope`，日志为 Permission denied，KWin/plasmashell 未就绪。读取 APK 的 `/proc/<pid>/status` 确认其 umask=0077。诊断包装器也使用 0077，因此不能只靠包装器推断来源；APK 自身状态和以下固定源码提供独立证据。

下载并核对 [LXC 6.0.4 原始源码](https://linuxcontainers.org/downloads/lxc/lxc-6.0.4.tar.gz)：`src/lxc/cgroups/cgfsng.c` 的 `__cgroup_tree_create` 使用 mkdirat，调用者传 0755，受调用进程 umask 影响；文件为 LGPL-2.1+。对照 [systemd 容器接口](https://systemd.io/CONTAINER_INTERFACE/) 与 [cgroup 委派接口](https://systemd.io/CGROUP_DELEGATION/)，用户会话需要能够遍历容器 cgroup 入口。选用自有 Android 控制器的调用环境修正，不改 LXC/systemd 源码，不放宽 Android 整棵 cgroup 权限，不给各个桌面程序补权限。

`system/rungic-plasma` 仅在启动 lxc-start 的子 shell 中设置 umask 022，其他控制文件仍沿用调用者的私有权限。对照实机中 APK 仍为 0077，新建 payload/cgroup 入口变为 0755，user@1000、KWin、plasmashell 启动成功，无需 ADB account-prepare。新增启动阶段/退出码诊断，APK 2.27 为非零退出补上 action 和 code，避免空 IOException。

这确认了一种可重复的冷启动故障并修复；92 篇最后一次空错误当时缺少内部阶段日志，不能倒推那一次必然仅由此原因造成。本轮以新产物重复冷启动作为验收。

## 第二个故障：Android 音频的旧 PID

`.5` 前两轮整机重启正常，第三轮第一次打开失败。新诊断明确为 `phase=android-audio exit=1`，尚未启动容器；PulseAudio 日志指出无法确认 PID 7368 的身份，假定 daemon 已运行。root 核对旧 PID 实际已经属于 `com.android.imsserviceentitlement` 的 Binder 线程，exe 为 `/system/bin/app_process64`，并非音频进程。Termux 包为 pulseaudio 17.0-4。

对照 [PulseAudio v17.0 pid.c](https://github.com/pulseaudio/pulseaudio/blob/v17.0/src/pulsecore/pid.c)（LGPL-2.1-or-later），`pa_pid_file_create` 在进程存在但无法读取身份时保守拒绝启动。我们将私有 runtime 放在持久化 `/data`，重启后 PID 文件留存；受限 Termux UID 无权查看另一个 Android 应用。复用现有 PulseAudio，修正自有 root 控制器，不改上游库、不删除其他应用的 PID、不杀那个 Android 进程。

`system/android-audio` 在既有控制锁内，先核对 UID、exe 和专用配置命令行，只停止本系统的私有音频 daemon；等待退出后清理已核验的失效 PID。无法检查的活进程会阻止清理。已退出但未被父进程回收的 zombie 可以清理。健康服务直接复用。故障现场验证：旧 PID 7368 对应的 Android 进程仍存活，新音频 PID 9080 成功提供 SLES sink，再执行 start 仍为 9080，没有重复 daemon。

新增测试使用真实进程分别验证 PID 被其他进程复用、仍活跃的私有 daemon、损坏 PID。最初测试还发现停止后短暂 zombie 无 exe 的边界，已补齐；最终 31 项与 12 子检查通过。`.6` 已构建并完成安装，但补齐 zombie 处理后另生成不可变 `.7`；以 `.7` 做最终首装/重启验收，不覆盖 `.5`/`.6`，也不把 `.5` 第三轮失败省略。

## 固定产物

| 项目 | 新输入 |
| --- | --- |
| 独立载荷 | vantage-20260930.7，manifest SHA-256 `c676032c6bbff6487f921899f166a4d2924e070021a0a6ff0f26081bc4771389` |
| OS 包集合 | 20260930.15、1538 包；沿用 .14 固定基线，会话包 0.359+e2e1 包含 offscreen 迁移修复 |
| rootfs | 16 GiB 稀疏 ext4；SHA-256 `3135fc155ca6be3266b7ee10ad553213fe98193803284330854a9a6a57401ddf` |
| 压缩 rootfs | 1,809,664,667 字节；SHA-256 `75d3adec525fa6116111ae9a063ecaa8415c14a85f3b57d84bf4946319f7b5c3` |
| Android 入口 | APK 2.27 / 75；Java 重新构建，复用 2.26 中未改变的 JNI，每个库的摘要见 native-reuse.json；OCR=none |
| 宿主 | 从当前源码重建 host seed，包含 umask、音频旧 PID 修复、启动阶段诊断、独立安装入口与前置授权 |

没有覆盖旧 `.4` 载荷。源码未提交的修改、固定输入、包锁、APK/JNI 和 host 摘要在 run 中归档；不是全部上游组件重新编译。CI2 明确生成当前 release 的 APT pin、去除 SSH 主机密钥，首装在设备生成身份。

构建时发现旧准备树的 `/dev/null` 曾被重定向创建为普通文件；新构建从经过清理的 root-tree 开始，`arm64_chroot.py` 在私有挂载命名空间绑定真实 `/dev`，退出清理。包安装检查实际字符设备，最终镜像仍为空 `/dev`，由运行容器提供设备。dpkg audit、apt-get check、ext4 检查通过；31 项 Python 测试及 12 子检查、shell 语法通过。

## 首装证据

完整保留当前 kevinzhow 账户与旧运行实例到手机 `/data/adb/rungic-revalidate-20260930/`。停止容器并分离 mapper 后记录 rootfs SHA、5682 个 home 文件摘要，再移动成套 runtime/controller/install 来源；私有账户及 home 另做压缩归档，拉回开发机后核对 SHA 和 8212 个归档项。旧 APK 数据也保存。只清除已备份的 Rungic 入口数据；Termux/prefix 与 Android 数据保留，属于兼容底座上的新 Rungic 首装，不声称再次验证无 Termux 的 Android 底座。

`.5` 在 17:05–17:06，安装自动经历 verify → rootfs → ready，界面实际显示“正在展开桌面系统”，没有 Magisk 授权弹窗。随后 account-status=false、进入原生账户表单，两个密码字段均掩码。临时账户 acceptance 通过原生表单创建，未调用 root 账户配置命令绕过 UI；桌面实际截图、UID1000 用户会话和 SSH 正常，cgroup 根为 0755，core 目录为空。

测试工具的边界：旧 UI Automator helper 填写成功后点击按钮返回 false；根据当前 UI hierarchy 的按钮位置发送触摸后提交成功。Junit 本身仍记录失败，不写成 Junit 通过。桌面图像探针最初会把 KDE splash 当作有画面，随后加入亮区和颜色检查并人工查看实际主屏；只采用最终主屏证据。

最终 `.7` 于 17:24–17:25 再次从空白 runtime 和入口数据开始安装，verify → rootfs → ready，release 精确一致，error=none。重新确认 account-status=false；新版验收 helper 只负责填写受保护字段，UI hierarchy 确认按钮 enabled 后发送实际触摸。UI Automator 填写测试通过，账户创建通过，首装实际桌面截图通过。全部使用打包产物，未在最终手机 runtime 追加修补。

## 重启、交互与账户保留

`.7` 的三轮 Android 整机重启均通过：每轮一次打开入口、无需重试，账户状态一致，cgroup 0755，自动 SSH 启用，core 目录为空。三次从应用启动后的探针计时到完整主屏约 37.1 / 37.2 / 37.5 秒；保留 screenshot 与服务状态，不用 KDE splash 或仅有进程代表桌面通过。每轮整机重启只打开一次入口，不手动运行 account-prepare/start，不点重试；探针只读检查服务、画面和账户。首次探针曾在 am start 后进程尚未创建时用 PID=0 查询 logcat，已修正为等待实际 PID；继续观察同一次启动，没有再次打开应用或干预控制器。

项目 `rungic_acceptance.py smoke` 的 9 项全部通过、无跳过、无失败：会话就绪、关键用户服务、无新崩溃、显示几何、Android 文本输入、摄像头帧、Wayland 空闲抑制、播放链路和录音链路。报告 `.work/acceptance/vantage-20260930.7/20260930-173035/report.json`，另复制进本轮 run。1264×2780 / 120 Hz 输出与 Android 匹配。摄像头验证连续帧/时序/释放，音频验证实际流及停止后挂起；不等同于全部应用、镜头或主观音质验收。

用户在验收期间明确选择“新镜像回到首次账户设置，由我重新配置”。因此不执行准备好的原账户恢复脚本；保留手机与开发机上的旧账户备份，另保存已通过验收的临时实例，再从同一 `.7` 载荷清洁安装，以空白账户状态交付。最终同载荷再次安装为 ready / error=none；account-status=false，原生表单默认用户名 linux、两个密码栏为空且掩码，临时 acceptance 账户不存在，root/模板账户均锁定，SSH socket enabled/active。屏幕常亮恢复为原值 0。账户表单使用 FLAG_SECURE，Android 截屏会遮黑；未解除密码保护，最终页面以 UI hierarchy、活动窗口及 account-status 核验，不能把黑色截屏当作页面画面通过。详情见 final-state.json / acceptance-report.json。

## 验收边界

本轮针对新独立镜像的安装、账户、桌面、SSH 和冷启动稳定性。Magisk 已就绪底座被复用；不包含 CI1 离线 Magisk 首启、再次 Android 清数据、自助安装器、通用完整镜像升级/回滚或全部硬件测试。本轮最终不恢复旧账户，也不宣称已验证通用迁移器。首启日志仍有 root 上下文的可选 overlay appops Binder 警告；安装器已用 Android shell 处理基础授权，投屏授权与投屏链路不在本轮验收范围。
