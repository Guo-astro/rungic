# G100 完整系统增量更新（2026-09-29）

用户发现设置中的服务页缺失，要求更新到最新版本。本次目标为保留账户及数据的运行中系统升级，不涉及固件刷写或清数据安装。

## 升级前核实

目标为 ADB 5037 / `ZY32M9MRVP`，G100 / portov_cn，Android 16 `W1VT36H.1-51-8`。G100 S 与 X70 的部署结果不作为本机验收。

| 组件 | G100 升级前 | 本轮目标 |
| --- | --- | --- |
| release | 20260928.1+clipboard1 | 20260929.2，66 个精确依赖 |
| KWin | +rungic3 | +rungic8 |
| KScreen | Ubuntu 原包 | +rungic5 |
| Plasma Mobile | +rungic6 | 保留 +rungic6 |
| 设置 → 服务 | 包、策略、KCM 均未安装 | 安装最新 rungic-plasma-services / config |
| 会话 | 0.281，后补重启顺序修正 | 当前源码的完整会话包 |
| 剪贴板 | 0.278 桥包上直接替换脚本 | 当前源码的正式桥包与宿主载荷 |
| Agent | 0.278 | 新设计系统、界面、事件进度与对话归属修复 |
| APK | 2.15 电话实验版 | 2.16：最新已提交 APK 源码，仅提高版本号以保留数据覆盖安装 |

仓库 fetch 后，合入 origin/main `c99c84b2` 的 8 个提交，同时保留本地已提交的剪贴板和欢迎流程修复；合并后补上 release Android 清单遗漏的 `android-clipboard`，提交 `e726cfbe`。未提交的电话实验不进入本次正式 APK；其他工作区修改保留。

## 构建与回退

- 按包源树标识复用现有构建，变化的 ARM64 包在 Mac mini 原生构建，按 `scutil --proxy` 的系统代理联网；宿主构建产物仅进 `.work/`。
- APK 从提交归档构建，不扫描工作区中的实验 Java 文件。版本覆盖为 versionCode 64 / versionName 2.16；JNI 沿用已核验的 G100 三个库，OCR 仍与原设备一样为 none。精确来源、版本覆盖与哈希单独记录。
- 升级前 `rootfs state=none`；16 GiB 根镜像约用 3.8 GiB，独立 home/包仓库所在存储约余 209 GiB。发布器保存根文件系统快照、旧 Android 载荷和包清单；家目录不随 rootfs 快照回退。
- 通过版本化发布器同时更新 Linux 精确依赖和宿主清单；相机按用户既有要求跳过，其余冒烟检查保留。

证据目录：`.work/experiments/g100-system-update-20260929/`。`source.json`、工作区补丁摘要、`apk-source.json`、构建日志、升级前完整性报告、`deploy.log` 记录本轮范围；发布器另保存 `.work/deploy/` 下的事务与回退记录。

## 已部署与验收

- 第一次安装因旧 rootfs 没有 Ubuntu 软件源索引，无法解析新增依赖，在实际安装前失败并成功回退，新增 ext4 错误为 0。通过手机指定代理更新索引后，模拟安装通过：20 个升级、50 个新装、0 个移除。
- 第二次发布事务 `.work/deploy/20260929-162618-20260929.2/` 完成，结果 `ok`；最终为 `20260929.2` / APK 2.16。66 个依赖与发布清单相符、dpkg audit 为空、包内修改数为 0，容器完整重启后 KWin、plasmashell、Agent 与浮层服务 active。
- 冒烟：会话、服务、无新崩溃、1080×2400 / 120 Hz / 保存的 300% 缩放、idle inhibitor、播放及麦克风采样通过。输入检查首轮未找到抽屉搜索框，重试实际输入/OCR 通过，记录为 flaky，不能称一次全过；相机显式跳过。
- 实际打开“系统服务”页和新版 Agent，截图分别为 `services-ui.png` 与 `agent-ui.png`。此处证明界面与启动，不代表未配置 API key 的 Realtime 对话已验收。
- 最新投屏宿主载荷同步并通过摘要检查，报告 android-native / supported=true；本轮未连接电视，不增加投屏实机验收结论。
- 原镜像遗留的 313 个翻译文件缺失，以及 initctl 本地 diversion / 其他原有文件仍被完整性工具记为 drift；已与升级前对照，不宣称整机 integrity clean。

## SSH 用户纠正与候选撤回

用户于本轮明确要求 SSH 自动开启。此前执行者误按历史“默认关闭”记录停用 socket，并新增关闭顺序依赖（`ab62de6e`）；这是未经用户要求的错误。已恢复 `ssh.socket enabled + active`、IPv4/IPv6 22 端口监听；连接触发 ssh.service 正常启动。

错误源码改动由 `5dc23c21` 撤回；基于它生成的 `20260929.3` 和 config 0.360 **未部署**，已移出有效发布池，隔离在证据目录 `withdrawn-ssh-default/`。不得将该候选作为最新可部署版本。SSH 开启选择由已有逐单元标记保留；后续遵循 AGENTS 的最新用户要求。

回退快照仍对应第二次发布之前的根系统，Android 旧载荷备份也在上述第二次事务目录。家目录独立保留；投屏与 APK 另有本轮备份。局域网连通性排查见 [网络记录](g100-ssh-connectivity-20260929.md)。
