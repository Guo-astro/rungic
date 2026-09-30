# X70：实际刷入 Android 后的独立安装验收

后续状态：新建 `.7` 独立载荷已定位并修复两类冷启动问题，通过全新账户、连续三轮重启和 9 项 smoke；详见 [93 篇](93-x70-independent-image-revalidation.md)。以下保留本轮原始失败与修补边界。

2026-09-30，用户明确要求“包含刷入 Android，然后再按照我们新路径走一遍端到端”。本轮与 [91 篇](91-x70-independent-install.md) 的复用底座验收分别记录，运行目录为 `.work/ci/runs/vantage-20260930-e2e/`。已实际刷入 Android、清数据并完成独立安装到桌面。首启发现的缺陷与修补分别记录；末轮重启后首次打开仍有一次启动失败，不能判为稳定全通过。

## 本轮路径

1. 保存原 Rungic 系统、账户及相关 Android 应用数据到开发机，校验备份。
2. 实际刷入该机原厂 Android 系统分区及辅助固件、已构建的 GKI v7 和普通 Magisk 31 引导。Android product 不包含 Rungic、Termux 或旧离线首启种子；不再组装 Android/Rungic 整包。
3. 核对 Android 启动、内核、模块、SELinux 与 root，确认没有旧 Rungic 安装环境。
4. 使用独立载荷安装普通 APK、Termux/prefix、LXC 宿主与 RungicOS，验证真实 loading、账户门槛、桌面、触摸、SSH 和整机重启。

重刷系统分区与清除 Android 用户数据是两个不同操作。用户随后明确选择“清空 Android 数据”，本轮将清除 userdata/metadata，并验证 Android 首次设置。原 Rungic 备份、共享存储及两个相关应用的数据副本，不是其他 Android 应用数据的完整备份。

## 固定输入和执行约束

- 开发机现场核验为 mibook / x86_64，默认路由 `192.168.5.1`，GNOME 代理关闭，Git 代理为 `http://192.168.5.45:6152`。
- 目标 USB ADB 5037 / `ZY22MHZKFT`，XT2603-1 / vantage，`W2WV36.55-75-15`，槽 a，电量 80%。同机 ADB 5037/5038 的另一台 Wi-Fi 手机不操作。
- 设备 spec、fastboot adapter 和历史失败记录以 [机型知识档案](../profiles/devices/motorola/vantage_cn/W2WV36.55-75-15-knowledge.md) 为入口；原厂 41 个 super 分片及辅助镜像逐项对照保留的 stock manifest 重新核验 SHA-256。
- GKI boot SHA-256：`5799040aa8447bf258dc912df9ebdc919630cf428d29b6b8f6e9d6b4ccb677cc`。复用已构建且本机验证的 v7，本轮不声称重新编译。
- 简单 Magisk init_boot SHA-256：`34bea306b6992f2b8faef266c1316d936caafd65e6ebd9e1943c67015d673635`。它不含旧 product 首启引导；底座 root 与 Rungic 安装解耦。
- 沿用该解锁设备已验证的 AVB flags=3 策略，两个 vbmeta 从精确原厂输入派生，仅改 flags。GPT 和 bootloader 版本未变，不重复写入。
- 刷写脚本在 run 目录中复用 `tools/ci/flash_release.py` 的精确身份检查、有界命令及实时日志；分启动分区、系统分片和最终重启三段保存结果，失败不自动重刷。
- 独立安装输入暂定为已校验的 `vantage-20260930.4`，manifest SHA-256 `0a590a52392e544018ef2f39b5d28b4e32e81920ace746e7100ae070e14d9e27`，具体组件与 CI2 构建结果见 91 篇。若实机暴露缺口并修改，另发新载荷，不改旧 manifest。

## 状态

15:39，电脑上的备份通过两端归档 SHA、gzip 完整性、tar 可读性及原 rootfs/APK 内容摘要核验，证据 `backup/verified.json`。随后执行精确目标的 `adb reboot bootloader`；主机只见 USB disconnect，30 秒只读 fastboot 探测超时，5037/5038 均无 X70，尚未写入或清数据。已请求用户重插 USB，复现本机历史模式切换限制。Android 实际刷写、无旧预装组件的首装以及本轮桌面/重启尚未授予通过。

16:02，用户要求重新检测，USB 已以 Motorola fastboot 重新枚举。重新核验产品、SKU、精确 bootloader、解锁状态、槽位、电压及启动分区容量后，boot/init_boot、两个 vbmeta、vendor_boot/dtbo/recovery/pvmfw 以及原厂 radio/bluetooth/dsp 均写入成功。原厂 radio 容器的实际操作还包括更新 modem/fsg 和擦除 modemst1/2，日志完整保留。进入 fastbootd 耗时 50.412 秒，产品、槽 a 和解锁状态复核一致；随后开始按数字顺序写入 41 个原厂 super 分片。此时 userdata/metadata 尚未清除。

16:11，41 个 super 分片全部返回 OKAY，七个逻辑分区容量与 stock verification 一致。随后在 fastbootd 执行 `erase userdata`、`erase metadata` 和 `reboot`，三项均返回 OKAY，三个阶段脚本均以 0 退出。未再刷入定制 product，未恢复旧首启种子或旧 Android/Rungic 数据。实际 Android 初始设置、root 准备和独立安装仍须继续验收，不能以 fastboot 成功替代。

16:14，用户明确确认“已经刷完机，进入初始化了”，因此本轮 Android 清数据启动到初始化界面已有现场确认。USB 首次枚举时 ADB 5038 曾显示 device，但 shell/sync 返回 `closed`；对精确目标 reconnect 后改由 5037 枚举，随后再次消失。没有将这些连接状态误判成 Recovery 或启动失败，也未重新刷机。下一步需完成 Android 初始设置、开启 USB 调试并授权电脑，再核验 root 和独立首装。

16:16–16:20，用户完成 Android 初始设置后，ADB 5037 恢复可用；`boot_completed`、`device_provisioned`、`user_setup_complete` 均为 1。简单 Magisk 清数据首启只安装了 versionCode=1 的占位应用，`su` 尚未就绪。以普通 APK 安装同一官方 Magisk 31.0 完整管理器，通过其“修复运行环境”界面完成初始化和自动重启，再在“超级用户”页启用 Shell；未查询可能触发 SQL NULL 崩溃的字段。

`fresh-base.json`：运行精确 v7 内核、Magisk 31.0、SELinux Enforcing、508 个模块，rust_binder 与 KGSL 存在。boot 和简单 init_boot 回读匹配上述哈希，整个 product_a 回读匹配原厂 `b529a42e4ef7a9abec1107eedc7e5f7fc72b183a0546ccac978706e1d13a59bf`。product 中没有 Rungic/Termux/种子目录，包管理器中两应用不存在，`/data/adb` 没有旧 Rungic runtime 或安装器。随后通过 `standalone.py install` 启动 `.4` 的普通应用独立安装。

这说明底座与 Rungic 交付已分开，但本轮底座准备仍包含 Android 初始设置/USB 授权、Magisk 管理器安装、环境修复和 Shell 授权步骤，不应描述成全无人值守刷机。

## 独立安装与验收结果

16:21:01–16:22:06，`standalone.py install` 从没有 Rungic/Termux 的底座安装两个普通 APK、全新 Termux prefix、LXC 宿主和 `.4` rootfs；完整镜像 SHA 验证、SSH 密钥生成与挂载准备完成，发布 schema=2、release=`vantage-20260930.4`、ready / complete / error=none。Rungic 2.26/74、Termux 0.118.3/1002 均为 `/data/app` 普通应用，没有 SYSTEM 标记。本轮状态采样观察到 verify → rootfs → ready；首次 UI 抓取遇到 Magisk root 提示，不能把它算作本轮安装 loading 截图通过。91 篇同载荷的 loading 证据单独保留。

账户表单曾显示 `configured=false`，两个密码字段均为掩码；随后检测到新 `kevinzhow` / UID1000 / sudo 账户。测试 helper 在等待表单时失败，尚未填入任何值；不能将此次账户创建归功于自动化测试，也未恢复旧账户。新账户保持原状，测试生成但未使用的密码文件已清除。

| 检查 | 证据与边界 |
| --- | --- |
| 桌面显示 | KWin 原生 1264×2780 截图与 Android 实际截图均显示 Plasma 主屏、Agent 组件及底部固定图标；本轮没有复现 91 篇的黑色截图，但没有定位旧异常根因 |
| 触摸 | Android 注入上滑后 KWin 截图显示应用抽屉；宿主 td=1 / tm=53 / tu=1，zero_copy=true、lastError=null |
| SSH | ssh.socket enabled、active；USB 转发实际读到 OpenSSH 10.2p1 banner；保持自动接入 |
| 软件 | `dpkg --audit` 无输出；安装清单确认 Angelfish、Haruna、Journald Browser、KleverNotes、Marknote 的五个独立包未安装；Emoji Selector 的文件排除见 91 篇离线检查 |
| 首轮整机重启 | 16:29 实际 Android reboot；boot_completed=1、SELinux Enforcing，独立 service.d 记录 already installed；账户保留、桌面及 SSH 恢复，没有旧 product 转发模块 |
| 修补后重启 | 16:40 实际 Android reboot，设备由 ADB 5038 接管；16:41:26 第一次打开出现 `MainActivity.control` 空消息 IOException，发生在 restart-session。诊断时运行 account-prepare 成功，UI 重试后恢复桌面；不算无干预首次打开通过 |
| 最终状态 | 新账户 kevinzhow 保留、桌面可见、SSH enabled/active、安装状态 ready；五个旧迁移 core 仍在，没有新增。临时 USB 转发移除，充电常亮恢复原值 0 |

### 安装授权时序修正

首次打开 loading 会启动原生 root 桥；原脚本直到安装最后才给 APK UID 设置 Magisk 策略，可能出现 root 弹窗。`standalone.py` 现在在发布 app-private 来源声明之前核验应用 UID，并用已核对的 Magisk 31 固定字段设置策略。没有执行可能返回 SQL NULL 的查询。

实测先 force-stop APK 并只移除其策略，再重入同 `.4` 安装：旧 firstboot 已安装分支在原授权位置之前退出，新前置逻辑仍成功恢复 policy=2。rootfs inode/容量、账户状态文件摘要及 account-status 前后相同，未重装镜像或重置账户。此为同载荷重试的授权测试，不是升级或再一次全新首装。

### 首次会话迁移崩溃与共享层修正

建议卡片的三条 kwin-common、两条 plasma 报告来自 16:23:58–59 的配置迁移 helper：`kwin-6.0-delete-desktop-switching-shortcuts`、`kwin-6.1-remove-gridview-expose-shortcuts`、`kwin-6.5-showpaint-changes`、`plasma6.0-remove-old-shortcuts`、`plasmashell-6.5-remove-stop-activity-shortcut`。它们在 `QGuiApplicationPrivate::createPlatformIntegration` SIGABRT，加载 Qt Wayland 插件；不是主 compositor 崩溃，也不是镜像混入旧 core。

对照固定 KWin 6.6.6 配方、已保存源码 `kconf_update/*.cpp` 和实机 Plasma 6.6.6 helper/`.upd`：这些迁移需要 `QGuiApplication`，但不显示窗口。KWin 前两个文件 GPL-2.0-or-later，showpaint 及 Plasma 对应 `.upd` 为 GPL-2.0-only / GPL-3.0-only / LicenseRef-KDE-Accepted-GPL 许可选择，未复制或修改上游实现。来源：[KWin 6.6.6](https://invent.kde.org/plasma/kwin/-/tree/v6.6.6/kconf_update)、[Plasma Workspace 6.6.6](https://invent.kde.org/plasma/plasma-workspace/-/tree/v6.6.6)。

自有 `desktop/session` 在 KWin 之前运行 kconf_update，继承全局 Wayland 且此时无 compositor。选择仅在迁移命令指定 `QT_QPA_PLATFORM=offscreen`；不延后到 KWin 读取配置之后，也不修改每个 helper。实机隔离 HOME、XDG 目录和 D-Bus 的五个 helper 均返回 0，showpaint 旧键确实被删除；完整 kconf_update 写出完成状态，无新增 core。隔离总线没有 kglobalaccel 服务，因此此测试不证明旧全局快捷键的在线迁移效果；它证明无显示启动及配置文件迁移。

修补以两份运行候选包部署：会话 `0.359+e2e1`、release `20260930.14+e2e1`。从固定 `.14` 的 Debian 包重建元数据，仅替换与当前源码一致的 session 脚本、相应版本/精确依赖及 release.json，复用未修改的二进制；不是完整当前源码包集重编译。原包、构建脚本、文件哈希及变更保存在 run 的 `session-fix/` 和 `build-session-fix.py`。部署、会话重启、整机重启后脚本 SHA 均为 `c968cf5b5de911f26c9694321d5492376c53c1c2f5b418c2be4bb261ed395cf4`，账户状态摘要不变。

检查修补包版本锁时另发现 CI2 输入树遗留了 20260928.2 的 APT pin。`build_rootfs_image.py` 现在按已校验的 manifest 重新生成 staging 内 `/etc/apt/preferences.d/rungic-release`，不影响其他源的策略。实机采用同一生成函数，`apt-cache policy` 的 Installed / Candidate 一致、优先级 1001，`apt-get check` 和 dpkg audit 通过。中间一次辅助部署脚本的换行转义错误发生在包安装后、写 pin 前；随后从实际状态恢复，没有重新安装或覆盖原备份。

**产物边界：** 原 `.4` rootfs/manifest 没有被原地修改；它仍包含上述首会话缺陷及旧 pin。修正源码和实机修补包已有证据，但尚未构建、全新首装验收包含这些修正的新独立镜像。不能把修补后的桌面结果倒填成原 `.4` 无缺陷首装。

### Magisk 为什么还需要补装

本轮刷入普通 Magisk init_boot，保留原厂 product；没有将完整管理器和离线 runtime 初始化随 CI1 一起交付。[官方安装指南](https://topjohnwu.github.io/Magisk/install.html) 也明确描述了清数据后的占位 App、补齐完整 App、修复环境及重启。因此这次行为符合所选引导方式，但不是我们产品必须保留的交互。

CI1 可以交付首启即就绪的 root，与 CI3 独立安装 Rungic 不冲突。既有 [13 篇](13-offline-magisk-user-app.md) 通过固件携带完整官方 APK、Magisk 自身启动流程安装为普通应用，并按缺失状态初始化环境；这不是把 Magisk 注册成 product 系统应用。此前验证机型/数据边界与本轮不同，X70 的全清首启仍需重新验证。仅修补 init_boot、完整管理器可见、root 授权可用是不同检查项；本轮不能声明 Magisk 离线自动就绪已完成。

### 保留材料与未通过项

`.work/ci/runs/vantage-20260930-e2e/backup/verified.json` 记录有效备份，原完整 Rungic tar、独立压缩副本、共享/应用归档及 root 配置均已离机验证。Android 清数据已删除旧手机备份路径，恢复必须用主机归档；本轮未执行旧版恢复。

修补后的桌面、账户和 SSH 当前正常，但末轮首次启动的空错误尚未定位，不能授予重启稳定通过。自助安装、完整镜像升级/自动回滚、Magisk 离线首启以及全部硬件能力仍未验收，APK 的 OCR 构建为 none。新增修改通过 23 项 Python 测试及 12 子检查、相关 shell 语法、Python 编译和 diff 检查；旧 JNI/APK 构建与 Java 检查见 91 篇。

## 备份传输教训

首次用 `adb exec-out su -c 'busybox tar -czf - …'` 导出，应用目录含 socket，tar 输出了忽略 socket 的警告。归档未通过 gzip CRC 和 tar 头部校验；在压缩流偏移 4,251,648 字节处找到原样的 `tar:` 诊断，确认 stderr 混入二进制流。ADB 命令返回 0 不代表归档可恢复，损坏文件没有作为刷写前备份使用。

改为手机先写归档文件，记录 SHA-256，再用 `adb pull` 传输；主机既校验归档摘要和可读性，也从归档读取原 rootfs/APK，与手机原文件摘要对照。socket 不需要恢复；账户、家目录、系统镜像及应用持久文件保留。此项不等同于已经执行旧系统恢复验收。
