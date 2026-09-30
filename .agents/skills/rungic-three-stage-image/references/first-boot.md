# 首启契约与已知故障处理

详证见 [79 篇](../../../../docs/79-g100-ci-execution.md)，综合结论见 [80 篇](../../../../docs/80-g100-image-installation-retrospective.md)。按症状读取相关段落，避免重新执行失败操作。

## 实现入口

- `tools/rungic-magisk-bootstrap.rc` / `.sh`：当前 Magisk 离线引导。
- `tools/ci/rungic-firstboot-service.sh` / `rungic-firstboot.sh`：部署、锁、状态、载荷校验与完成标记。
- `system/rungic-plasma`：公共控制入口、release 门槛、`start_container` 和 `account-prepare`。
- `system/android-audio`：共用目录准备与音频服务。
- `tools/rungic_plasma_enter.c`：控制环境挂载；`android/app` 中 `FirstBootState.java`、`MainActivity.java`、`AccountSetup.java`：等待状态、启动与账户表单。

改动前追踪整条实际调用链，先修最低公共准备层，避免分别给账户和桌面入口打补丁。

## 当前 Magisk/首启机制应保持的条件

1. **空白 /data**：Magisk 31 缺少 `/data/adb` 时，早期只在 tmpfs 记延迟状态；到 Android boot-complete 后准备离线运行环境，再自动重启一次。对其他版本或 root 机制先查源码，不机械套用此时序。
2. **部署持有锁**：校验当前 release 与载荷摘要，展开到规定位置，保留权限/标签。失败记录真实阶段，不能提前写完成标记。
3. **真实挂载就绪**：Android boot-complete 不是存储 ready。等待实际共享存储可用，准备音频/Wayland/共享目录并执行挂载预检；不要在尚未挂载的路径上创建一个假目录。
4. **状态发布**：完成标记由 root 写入；应用私有 `rungic-install.properties` 原子写入，包含 release/state/phase 且 UID/MCS 正确。应用只读状态，控制器另验 marker，错误状态不开放表单。
5. **账户准备**：先启动容器，核对账户工具、目标 UID/共享目录与服务状态。当前入口接受 systemd running/degraded，因此 degraded 本身不证明必需服务正常，仍须核验相关依赖。当前 180 秒准备界限及 APK 240 秒超时是实现值，调整须同步两端。
6. **用户交互**：准备期间显示真实阶段和不定进度。ready 后完成 account-prepare 才显示表单；创建后显示桌面启动 loading。密码经受保护输入通道传递，不写 argv、日志或测试截图。
7. **最终验证**：从包自身清数据安装，观察上述顺序。应用重开恢复等待、重复准备幂等；未测试的断电恢复不得宣称通过。

## 症状 → 先检查什么

| 症状 | 已知原因/边界 | 处理路径 |
| --- | --- | --- |
| 清数据后 Recovery，已有数据能启动 | G100 旧引导违反安全初始化时序；失败的具体加密调用未证实 | 保留日志，固定其他输入对照 init_boot，核对 root 生命周期；不要反复擦除并猜测数据损坏 |
| 账户页报 bind audio/shared 不存在 | 音频目录初始化遗漏已定位；共享目录首次竞争缺少直接现场 | 先查部署 release/完成状态，再查真实存储、公共目录与挂载链；失败发生在账户助手前不要求用户换密码 |
| 合法用户名显示不可用，但系统没有该账户 | X70 镜像曾带入宿主 Python 缓存，提前占用了同名 home | 分别查 passwd 与 home 内容及来源；在 `arm64_chroot.py` 隔离宿主环境，并由 rootfs/host 两端构建检查拒绝污染；不能删除未经核对的用户目录 |
| 照片等应用报告 Pictures 不存在 | 首装没有统一准备 XDG 目录 | 复用 `system/user-dirs`，在真实 Shared 挂载后由账户准备/会话公共入口调用，保留已有目录；不要给每个 App 单独建目录 |
| 预装 APK 缺 libc++_shared | 压缩 JNI 库未随 product/app 安装 | 在组包中生成对应 lib/arm64 并核对标签；普通 pm install 修好只算诊断 |
| Termux usr 已存在 | 应用曾提前生成空目录 | 仅允许 rmdir 删除空目录；非空或符号链接不能盲目清除 |
| rootfs 展开异常/容量暴涨 | toybox 的 sparse 支持与帮助不一致 | 使用已验证写入器，核验完整镜像摘要与实际占用 |
| 容器再次启动失败 | loop autoclear 后留下失效 dm 映射 | 检查现有 rootfs attach 的重建逻辑，不在使用中的映射上盲目删除 |
| ADB 没设备 | 端口、USB/Wi-Fi、授权或模式变化 | 核对 server/序列号和 USB 状态；不能直接判定 bootloop |
| fastboot 长时间无输出 | 模式转换/传输耗时、日志缓冲或实际失联 | 流式日志和有界等待，超时停止；恢复后重新核验，禁止循环重刷 |

Magisk 31 禁止向实机守护进程提交可能返回 SQL NULL 的查询，按项目 39 篇处理。root 多命令走已验证的 shell stdin 通道，二进制备份使用无 PTY 的传输；不得把权限/转义问题误判为设备缺能力。

## 回归证据如何使用

G100 `.3` 有清数据首启与详细安装检查；`.5` 纳入 loading/账户准备，用户确认重新安装进入 Plasma。两者报告不能混用。G100 S 的既有数据离线种子实验也不能代替最终整包全清验证。

X70 `.1` 清数据部署后因 home 污染需人工修复才完成账户和 Plasma；`.2`/`.3` 修订包仅完成离线校验，当前账户的目录/缩放更新通过也不能授予它们 clean-install 通过。详证见目标 spec 的知识档案和 [83 篇](../../../../docs/83-x70-air-pro-onboarding.md)。首装模板和首次显示默认的离线/实机检查见 [构建隔离](build-isolation.md)。

手机端 fastbootd 进度仍未实现；主机实时日志已改进。RecoveryUI 源码研究是可行方向，不是现成可启用的手机日志选项。若任务只涉及制作/首启，不扩展到修改 recovery UI。
