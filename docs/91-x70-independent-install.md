# X70 Air Pro 独立三段式安装验证

2026-09-30，用户指定本机 USB X70 Air Pro。执行记录在 `.work/ci/runs/vantage-20260930-standalone/`。本轮复用兼容 CI1、重建 CI2，并补齐 CI3 的开发用 USB/ADB 首装入口；不刷 Android 分区、不清 Android 数据。用户自助安装、通用完整镜像升级和跨机型兼容不在本轮完成范围。

后续用户明确要求重刷 Android 并清数据，执行结果另见 [92 篇](92-x70-android-base-end-to-end.md)。下文保留本轮复用底座的边界；手机上的旧系统副本已在后续清数据前导出并校验，现存开发机，不能再依赖下文手机备份路径。

## 实际输入

- 开发机现场核验：mibook、x86_64；默认路由 192.168.5.1，系统代理关闭，Git/下载使用本机已配置的 `http://192.168.5.45:6152`。这不是其他开发机的固定配置。
- 手机：ADB 5037 / `ZY22MHZKFT`，`vantage`，固件 `W2WV36.55-75-15`，槽位 `_a`，SELinux Enforcing，Magisk 31.0。精确 spec 与历史证据见 [机型知识档案](../profiles/devices/motorola/vantage_cn/W2WV36.55-75-15-knowledge.md)。
- CI1：复用已部署的 6.12.38 Android 16 GKI；boot_a 前 40,161,280 字节回读 SHA-256 为 `5799040aa8447bf258dc912df9ebdc919630cf428d29b6b8f6e9d6b4ccb677cc`，与保留构建报告相同，508 个模块已加载。没有重新编译或刷写 CI1。
- CI2：包版本 `20260930.14`，1538 包；16 GiB 稀疏 ext4，gzip 1,809,660,984 字节。rootfs SHA-256 `355ffdcdfd02c1ce397d7e4612806ee5cdf417c09884e421f60bb4ae6dde5ed3`，gzip `465e45f49951b0eb11f4ecfe14ef7141bc5f59217c5aa0cdb49e0b3dd6d34f1c`。这是固定包集合的流程验证候选，不代表所有最新桌面改动。
- CI3：当前源码重建 JNI 与 APK 2.26/74，OCR 构建选项为 none；LXC 宿主包 SHA-256 `a4820ea0dc72b9d62e1db30c99b08e42a52ccfddbae0c267ac7ee452cdd12770`。独立包 `vantage-20260930.4` 的 manifest SHA-256 `0a590a52392e544018ef2f39b5d28b4e32e81920ace746e7100ae070e14d9e27`。

## 复用研究与实现边界

核对 [RAUC 的迁移与回滚说明](https://github.com/rauc/rauc/blob/master/docs/advanced.rst)（GPL-2.0）及 [systemd-sysupdate 实现接口](https://github.com/systemd/systemd/blob/main/man/systemd-sysupdate.xml)（LGPL-2.1-or-later）。它们提供版本化资源及更新机制，但当前 Android PID 1、Magisk root、LXC 私有挂载和 app-private 就绪状态仍需适配。此次复用项目已有稀疏写入、rootfs mapper、账户准备和原子 release 状态，不引入另一套更新守护进程；这不等于已实现通用 A/B 升级。

核对 Magisk 31.0 已部署引导脚本及 [官方模块指南](https://topjohnwu.github.io/Magisk/guides.html)（Magisk GPL-3.0）：旧 init_boot 每次启动都从 product 重写 service.d，单独替换 service.d 不足以接管独立安装。采用官方 `system/product` 模块覆盖方式，把旧 firstboot 调用转发到选定的新载荷；原脚本单独保存在 root-only 目录，没有选定独立安装时可回退旧入口。没有修改 Magisk 上游或 Android 分区。模块的重启生效必须实测，不能以文件写入成功替代。

`tools/ci/standalone.py` 提供 `pack / verify / install / status`：

- 显式固定 serial/ADB port，校验完整 fingerprint、运行内核、SELinux、槽位、电量和 boot 回读；可信 manifest 摘要由调用者传入，逐文件核验后才执行安装。
- 普通 APK 安装和权限使用 Android shell，载荷落入 root-only 持久目录。root 控制器使用 `active.env`，APK 使用不含凭据的 app-private 来源声明；两边都按 release 拒绝过期 ready。
- 首装不覆盖已有 runtime；只允许同 release、同 manifest 的安装重试。已有账户的完整镜像替换不是该命令的隐式功能。
- 镜像构建去除 SSH 主机密钥，首装在设备生成；保留 `ssh.socket` 自动启用。

## 旧系统保护与验收记录

旧运行实例先停止容器并分离 mapper，再将完整 `rungic-lxc`、`rungic-plasma` 目录移到 `/data/adb/rungic-acceptance-20260930/`；旧 APK、入口数据、安装标记、服务脚本及私有身份导出同处保存。备份目录权限 0700，凭据不进入 Git/日志。Android 应用和共享存储不清除。旧 home 的逐文件 SHA 清单仅保存在手机私有备份目录。

旧 rootfs 的 SSH server 尚未安装，尝试安装时发现已存在的 `rungic-release → rungic-cast` 精确版本依赖不一致，未强行修改旧包集。新 CI2 镜像已包含 openssh-server 并通过 dpkg 检查。

离线已通过：rootfs fsck 返回 0、fresh account/home/排除应用检查、28 项 Python 测试及 12 子检查、项目 venv 的 pip check、Java 安装状态测试、Android JNI/APK 构建。实机显示与 `rootfs` 阶段对应的“正在展开桌面系统” loading；账户、桌面和重启结果如下。


### 本轮发现与修正

- `.2` 在 configure 阶段因临时 chroot 没有 `/dev/null`，SSH 密钥生成失败；UI 正确显示 failed，没有提前进入账户表单。临时脚本确认原因后，将 dev/proc/sys 的挂载与清理纳入正式脚本；`.3`、`.4` 均重新从无 runtime/账户的状态执行，无临时修补到达 ready。
- 表单 UI 层发现 `setSingleLine` 覆盖密码转换器，APK 2.26 将输入类型/密码转换器放在单行设置之后。`.4` 的 UI hierarchy 两个密码字段均为 `password=true`。FLAG_SECURE 保留。测试凭据随机生成，仅用于本轮临时账户。用户随后明确选择保留全新安装、重新配置账户，因此不迁入原账户或密码。
- Android 16 自带旧 UI Automator runner 缺失 `android.test.base.jar` 的显式 classpath，报测试中断却同时打印 `OK`；必须检查异常与实际账户状态，不能只 grep OK。传入系统提供的 base jar 后再执行。


## `.4` 实机验收与交付边界

| 检查 | 结果 |
| --- | --- |
| 独立载荷安装 | rootfs 全镜像 SHA 校验、SSH 密钥生成、宿主与共享挂载准备自动完成，release `.4` 状态 ready / complete / error=none |
| 账户门槛 | ready 后进入表单；提交前 `configured=false`；两个密码框均掩码，原生表单提交后 `configured=true`、UID1000 |
| 桌面 | KWin/Plasma 会话 active，KWin 截图为实际桌面/应用抽屉；Android 触摸滑动到达 KWin，宿主计数 td=1/tm=6/tu=1；用户确认手机上可见桌面 |
| SSH | ssh.socket enabled、active；USB 转发 TCP22 返回 OpenSSH 10.2p1 banner，服务按连接触发。没有关闭 SSH |
| 软件与依赖 | dpkg audit 无输出、项目 venv pip check 通过；移除的五个独立包及 Emoji Selector 入口均不存在 |
| Android 重启 | boot_completed=1、Enforcing；product 的旧 firstboot 路径实际看到转发脚本，新 `.4` 只记录 already installed；容器/会话与 SSH 恢复，账户仍配置完成 |
| 最终状态 | 按用户选择，将测试账户所在 runtime 单独移走，再用同一个 `.4` 安装包初始化；最终留给用户创建自己的账户，旧系统完整备份保留 |

**截图限制：** Android `screencap` 在本轮桌面阶段显示黑色或停留在启动画面，而 KWin ScreenShot2 返回正常实时桌面，用户也确认手机可见桌面。开关零复制、重开入口未消除截图差异；测试后恢复默认开关，重启日志确认 zero_copy enabled。尚未定位该截图路径异常，不能把 Android 截图当成实际屏幕黑屏的充分证据，也不能宣称截图接口验收通过。

**首装范围：** 旧 runtime 与 Linux 账户被完整移走，因此验证的是独立 rootfs/宿主的首装；Android 底座仍带旧 product 基础 APK 与 Termux，Termux prefix 被复用，Rungic 使用 `pm install -r` 更新。没有验证没有这些旧预装组件的纯底座、重新刷 GKI、清 Android 数据、终端用户无需 ADB 的安装、完整 OS 升级/自动回滚，也未重新验收摄像头、投屏和全部硬件。APK 本轮 OCR=none；不能据此声称 Android OCR 已验收。

## 开发入口

先构建 CI2、APK 和宿主 seed，再用 `standalone.py pack --help` 所列参数显式绑定 spec、rootfs/host/kernel 报告、包锁、package release、APK 与 Termux/稀疏写入器依赖。`pack` 拒绝覆盖已有产物目录，输出可信 manifest SHA；SHA 必须从可信发行记录取得，而不是仅相信下载包内自带清单。

```sh
python3 tools/ci/standalone.py verify "$payload_dir"
python3 tools/ci/standalone.py install "$payload_dir" \
  --adb-port "$adb_port" --serial "$device_serial" \
  --manifest-sha256 "$trusted_manifest_sha256"
python3 tools/ci/standalone.py status \
  --adb-port "$adb_port" --serial "$device_serial"
```

`install` 返回 installing 只代表后台任务已启动；必须继续核对 ready、账户和真实桌面。已有 runtime 会被拒绝；本轮停容器、保存旧目录的受控验收准备不是自动升级功能，不要把手动删除 runtime 写成用户日常更新步骤。同 release/manifest 可重试，新的 release 不能覆盖既有安装；部署命令应串行执行。

回退材料保留在手机 root-only `/data/adb/rungic-acceptance-20260930/`：旧 rootfs、宿主、home、APK/入口数据、完成标记和服务脚本。回退须先停当前容器、分离 mapper，恢复成套旧目录与旧安装来源/标记；旧 Magisk 转发模块在没有 active.env 时可转回保留的旧脚本。该恢复方案的材料已保存，**本轮没有执行完整旧版回退**，不记为回滚验收通过。

最终现场复核：`.4` ready / complete / error=none，`account-status` 为 `configured=false`，UI 为“创建 Rungic 账户”。调试实例、临时测试账户与传输暂存已清理，原系统备份约 7.0 GiB、全部原 home 普通文件的 SHA 校验通过；独立持久载荷约 1.9 GiB，手机剩余约 403 GiB。用户后续创建账户不改变本次首装验收记录。
