# X70 Air Pro Miracast 完善评估

2026-09-28；范围：同步最新代码、源码与上游研究、当前手机只读检查。本轮未安装组件、修改权限/无线开关、连接电视或刷机。结论是继续使用 Android 无线显示框架＋高通 WFD，先补齐交付与首次使用流程，再做 X70 专属能力验证。真实电视端到端尚未验收。

## 代码与设备基线

远端更新至 `58af0930`。本地 `f77bc7ce` 与远端分叉，快进失败后合并为 `40143e1a`，保留本地 density、账户准备和镜像隔离改动。`build_host_seed.py` 的冲突按并集解决：种子加入 `rungic-wfd`，保留 home/fresh-account 检查报告。两边内容不同的 APK 都曾使用 2.10/58，合并源码改为 **2.11/59**。15 项首启/隔离测试及 shell 语法检查通过；未构建/部署新版 APK。

目标为 XT2603-1 / `vantage` / `W2WV36.55-75-15`，平台属性 `canoe`，Android 16，SELinux Enforcing。本轮 USB 归 ADB **5037**，序列号 `ZY22MHZKFT`；5038 只有另一台手机，后续操作必须重新枚举。证据位于 `.work/research/x70-miracast-20260928/`。

| 本机只读事实 | 含义与边界 |
| --- | --- |
| `/data/adb/rungic-wfd`、两个 WFD `service.d` 脚本均不存在 | Linux 快捷入口缺少 root 控制端；需要单独补装或新镜像交付 |
| `SYSTEM_ALERT_WINDOW: default`，有近期 rejectTime | 外屏 overlay 权限缺失；Android 连接成功也不能据此认定 Linux 桌面能接管 |
| 活动 APK 2.10/58；预装旧包 2.9/57 | 本地 density 版 2.10 不包含远端同版本号新增的 overlay 自恢复；不能只看版本号判断功能 |
| `wifi_display_on=0`，`mWfdEnabled=false`，`mWifiP2pEnabled=true`，featureState=2 | 无线显示关闭；不是框架报告“不支持” |
| Qualcomm WFD 包、Wfdvndservice 与 Motorola Smart Connect 包存在；系统 CAST_SETTINGS 可解析 | 原厂框架路径可复用；不代表连接与编码已通过 |
| Android 记忆中有 TCL 85Q6H 的 R2 接收端，当前无活动显示、无连接 | 记忆记录不能代替本轮发现或电视在线证据 |
| `wfdvndservice` 运行域 `vendor_wfdvndservice`；WFD APK 域 `vendor_wfd_app` | 与现有 G100 S 规则中的部分域不同；需要按实际调用与 AVC 核对 |

本机 `/vendor/etc/wfdconfig.xml` 有 8 个视频项：6 个 H.264（Profile 0–5，Level 索引 7）、2 个 H.265（Profile 0–1，Level 索引 4），均宣告 4096×2160@60。按现有解析器分别映射为 AVC 5.2/HEVC 5.1。**这是厂商配置，不是 X70 实际编码能力或电视协商结果**；尚未运行 MediaCodec 能力探针与实际编码测试。静态日志未找到相关 AVC 不能证明投屏期间不需要策略适配。

现有 `vantage-20260928.3` 离线验证整包生成于本次远端修复之前，不包含新增投屏种子。不能把源码合并或当前账户补装计为新整包清数据验收。

## 复用方案与上游核验

| 来源 / 固定版本 | 核验与选用理由 | 许可证 / 状态 |
| --- | --- | --- |
| [AOSP WifiDisplayController，android-16.0.0_r1](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-16.0.0_r1/services/core/java/com/android/server/display/WifiDisplayController.java) | 已读 `requestStartScan`、`updateWfdEnableState`、`updateScanState`：扫描请求本身不启用 WFD，扫描要求 `mWfdEnabled`。本机 dumpsys 与这条状态链吻合；Motorola 私有改动仍须实测 | Apache-2.0；复用手机已有 framework，不替换 framework |
| [Android VideoCapabilities](https://developer.android.com/reference/android/media/MediaCodecInfo.VideoCapabilities)、`CodecCapabilities.profileLevels` | 按 codec/profile/level、尺寸和帧率核对候选能力；API 声明不能替代真实 WFD 编码和持续性能测试 | 官方接口文档；运行时值待测 |
| [GNOME Network Displays 0.99.0 源码包](https://download.gnome.org/sources/gnome-network-displays/0.99/gnome-network-displays-0.99.0.tar.xz) | 已读 `nd-wfd-p2p-sink.c` 与 `nd-nm-device-registry.c`，P2P 路径使用 NetworkManager 的 Wi-Fi P2P 设备、连接与 WFD IE。当前 Wi-Fi 由 Android 管理，直接装入 LXC 不能补齐控制路径；改写 P2P/编码桥成本高于完善现有路径 | GPL-3.0-or-later；只研究，无代码复制 |
| 项目引擎 A / G100 S 最新实测，[58 篇](58-miracast-desktop-feasibility.md) | 已有 Linux 发起、外屏桌面、手机输入、后台继续渲染及声音路径；最新记录 Ready For 停用时 4/4 连接成功。复用公共层，在 X70 重新验收 | 项目源码；厂商 WFD 为原机闭源组件，不推广 G100 S 的能力/策略数值 |
| 自研发送端，[84 篇](84-miracast-source.md) | RTSP/推流原型仍未让电视显示视频，且已有用户决定暂缓。重建协议、封装、音频和接收端兼容会扩大当前任务 | 继续暂缓；历史来源及许可证见 84 篇 |

GNOME 源码包 SHA-256：`1ece4a1bc822c7ebf725e8847b8ce8998b47d1ec1715a4b4ddb9ddd71691ed85`。源码和下载存入上述 `.work/research/`。最初 GitHub 版本标签未找到，随后改用官方发布包核验；不能将镜像标签不全当作上游没有新版本。

目标公共链路：Plasma 投屏 UI → 平台桥/root `rungic-cast` → Android DisplayManager/Wi-Fi P2P/高通 WFD → 电视；画面由 KWin 外屏 → Android 宿主 `CastDesktop`/Surface → WFD 编码提供。Linux 音频仍经已有共享 Android 音频后端，必须验收电视路由。LXC 不接管无线网卡，不为单个应用新增投屏通路。保留 Ready For 包，只有实测证明具体副屏组件遮挡时才采用精确、可回退处理。

## 修改顺序

### 通用化约束（用户于本轮明确要求）

目标是同一套方案支持更多机型。新增设备应主要补充探测结果、必要的适配器和验收记录，不能复制整套 X70 投屏实现。

| 层 | 公共职责 | 允许的设备差异 |
| --- | --- | --- |
| UI 与平台桥 | `capabilities/status/scan/connect/disconnect`、选电视、统一状态/错误、取消与重连；兼容扩展现有命令 | 根据能力显示入口，不判断品牌、SoC 或硬编码电视名字 |
| Android WFD 后端 | 服务/接口探测、权限、按用户动作启用、框架调用、显示监听 | 按接口存在性选择调用方式；隐藏 API 不兼容时明确报错，并提供系统 CAST_SETTINGS 入口，系统连接后仍复用公共外屏渲染 |
| 厂商适配器 | 仅处理经证据确认的配置、服务差异及冲突 | Qualcomm XML 方言、实际 WFD codec 映射、精确副屏组件和 SELinux 规则，按 firmware/spec 选择 |
| KWin/宿主外屏 | Surface 生命周期、输出身份/模式、帧反馈、桌面和手机输入、音频路由协作 | 按 display 能力工作，不依赖 Motorola 名称；内屏 density 与电视设置分开维护 |
| 交付与健康检查 | 版本化载荷、统一安装/升级/修复入口、摘要、原子状态和回退 | root 提供者/启动钩子由安装适配器处理；当前验证目标是 Magisk，其他实现不能提前标为支持 |

能力报告至少区分原生 WFD、直接扫描/连接、系统连接页、overlay、codec 配置识别状态、所选适配器及证据版本。区分 `unsupported`、`disabled`、`permission-required`、`component-missing`、`negotiation-failed`、`encoder-failed` 和 `timeout`；错误附带阶段与可恢复性，不把 logcat 文本当作 UI 契约。

运行时接收端、display id、codec 列表、开关与连接状态不写死进 spec。spec 保存固件身份、来源与已验证例外；未知平台先走无厂商修改的框架路径，不能自动挂载 Qualcomm XML、加载其他机型 SELinux allow 或停用 Motorola 组件，也不能只按品牌/进程名判定能力缺失。

无原生 WFD 的设备需要未来独立后端，保留相同接口并明确报告当前边界。自研引擎电视实测通过前，不能称为“通用回退已完成”。实现以 X70 与 G100 S 为两组回归基线，公共测试覆盖无 WFD、缺权限/组件、不同 profile/level、未知 XML、无接收端、取消及部分安装恢复；真实验收仍按机型/固件记录。

### P0：现有手机可用与首装完整性

1. **组件部署与升级独立于账户安装。** 远端已把 jar、控制器、watch 和策略加入 host seed；当前手机需要保留账户的独立升级入口，不能重跑整套首启来补 WFD。新包重新构建种子与 product，manifest 记录来源及哈希。
2. **安装健康检查。** `rungic-firstboot.sh` 仅用控制脚本是否可执行跳过安装，存在脚本但缺 jar/service 或旧版本时不会修复；而 service.d 文件先于载荷落位，有中断窗口。增加组件版本/摘要及完整性检查、暂存校验后切换、幂等修复，保留 `last-sink` 状态。可选能力失败继续允许桌面启动，但投屏 UI 应显示未就绪及恢复入口。
3. **权限闭环。** 合并源码已有首启 appops 授权及 APK root 尝试、系统授权页回退；部署后核对 appops 与实际 Surface 绑定。验证从未授权状态恢复和新包首启两条路径，不能仅凭 default-permissions XML 判定 overlay 已允许。
4. **无线显示开关与首次选电视。** 当前 helper 的 scan/connect 没有启用 WFD；扫描前区分 unsupported、Wi-Fi/P2P 不可用、WFD 关闭。用户主动投屏时完成启用并等待功能 ready，或引导系统开关；失败要显示原因。不要在开机时无条件开启或关闭用户的无线设置。首次没有 remembered/last-sink 时直接展示扫描列表，多台电视可明确选择；保留快速连接上次电视。

### P1：X70 能力与运行可靠性

5. **按实际 WFD 编码器求能力交集。** 当前 `WfdConfig.java` 选同 MIME 中声明最大面积的硬件编码器，跨所有 profile 取最高 level，却不读取每个 XML 项的 Profile；不能证明它就是厂商 WFD 使用的编码器。先核对运行时 codec 身份、profile/level/tier、尺寸/帧率、码率和 Surface 输入，再映射本固件 XML。
   现有算法还存在源码可见的边界：没有候选尺寸时保留原尺寸；将 level 降低后不重新求兼容尺寸；没有硬件编码器时保留原条目。应对整个组合校验并输出明确“不支持/未识别”，不能宣称自动钳制已保证有效。用实际支持的 H.264 模式建立首个电视基线，再验证更高分辨率/HEVC，不能直接套 G100 S 1080p60 上限。
6. **按本机 AVC 处理 SELinux。** 现有 `wfd.sepolicy.rule` 明确针对 XT2537-4，不能机械将新域名代入旧 allow。Enforcing 下记录连接阶段 AVC、进程域、目标类型，必要的最小规则进入 spec/适配器选择。检查生成配置在 init mount namespace 中可见及标签正确；只替换自己持有的挂载，保留原配置与精确回退。
7. **连接状态和重连共用服务。** 快捷开关当前把失败压成“没有连上电视”，长按进入 KScreen 而非接收端选择；首次用户缺完整操作入口。统一 expose 组件/权限/扫描/协商/显示就绪/断开状态和原因，显示“请让电视停留在 Miracast 等待页”。watch 依赖 logcat 字符串顺序，电视主动退出也会被当成异常恢复；增加会话标识、用户取消优先、有限退避，权限或确定编码失败不循环重试。对现有重连行为做回归后再替换。
8. **外屏生命周期与显示设置。** 保留现有后台投屏、独立帧反馈、触控板/键盘和手机移动布局。核对真实 WFD display 与助手虚拟显示的身份；当前 `onDisplayChanged` 为空，需验证电视重新协商模式时 Surface/刷新率能否更新。检查不同电视配置是否因复用 CAST-1 串用。手机 density/720 渲染策略不应用于电视。

以上是源码评审与建议，不是已实现修复，也不表示每个边界已在 X70 触发。

## 分阶段实机验收与回退

- **阶段 1，保留账户：** 新组件健康报告、APK 实际版本与 overlay；未授权、WFD 关闭、无历史电视、多接收端四种入口。用户选择电视后记录发现、P2P、RTSP、编码、display、Linux 首帧各阶段时延和失败原因。Android 连接成功不能代替电视显示 Linux 桌面。
- **阶段 2，真实桌面：** 手机触控板/中文键盘、窗口在正确输出打开、电视缩放与重连；至少两个独立 Linux 应用交叉验证。分别测试真实视频和声音、电视/手机音量及音画同步，覆盖前后台、手机息屏、APK/会话重启和 30 分钟持续播放。记录协商编码、实际帧率/丢帧、延迟、温度与功耗，不预先承诺 4K/60。
- **阶段 3，失败恢复：** 电视退出/屏保、Wi-Fi 波动、手动取消、反复连接断开、无电视时不重试风暴；停止后编码器、P2P、overlay、wake lock 和音频路由释放，手机界面/显示大小恢复正常。有第二接收端时补兼容验证；否则明确仅覆盖所测电视。
- **阶段 4，新整包：** 清数据安装到新账户后，直接从 Plasma 发现并投屏；无需手工拷贝脚本、appops 或残留 last-sink。现有 `.3` 的离线校验不能替代新包与这项验收。

实施前保存现有 APK/组件版本、appops、无线设置、配置挂载和精确组件启用状态；回退只还原本次改变的项目，不停用整组 Motorola 包。需要刷写的阶段沿用三段式 skill 的机型核验与授权范围。本次仅保存只读证据，没有执行上述部署或验收动作。


## 部署实验与实现（2026-09-28，后续更新）

用户随后授权部署实验，并要求继续复用动态编码配置生成。证据目录 `.work/experiments/x70-cast-20260928/`；没有刷机、清数据或改写 rootfs 镜像。已部署 APK 2.12/60，原生三份库复用已验的 2.10 并记录逐文件哈希。

**实际根因与对照：** 补装 root helper、开启无线显示后，原厂 WFD 已连接 TCL 85Q6H R2，1920×1080@60；overlay 自动授权且 KWin 建立 CAST-1，但用户仍看到 Moto 界面。WindowManager/SF 截图证实 `MotoDesktopSplash`（2938）和 `MotoTaskBar` 在 `PlasmaCastDesktop` 上方。标准 `setShouldShowSystemDecors(false)` 仍返回 true，与 58 篇记录的显示标志覆盖一致，实验后恢复原值。关闭 splash 只能暂时露出桌面，停止 UI 进程后进程又被系统重启，不能当作持久方案。

修复在已匹配固件的适配器中，于 Rungic connect 前保存两个 UI 包 `com.motorola.mobiledesktop`、`com.motorola.systemui.desk` 的 enabled state，投屏期间设为 disabled-user，断开后恢复精确原状态。`.core`、高通服务及主屏 launcher 保留。APK 在框架产生外屏后也请求 claim，覆盖从系统设置连接的路径；这种事后接管可能有短暂窗口，本轮无闪屏证据来自 Rungic 发起连接。租约在修改前原子写入，文件锁串行化，部分执行可重试；resident watcher 在异常断开后恢复，连接建立阶段有 65 秒保护。用 boot ID/单调时钟区别重启和正在连接；安装升级不覆盖租约与接收端记录。此例外仍暂停了整个 Smart Connect UI 包，期间该包的其他界面不可用，不能描述为只关闭一个窗口；更细粒度入口尚未找到稳定接口。

**通用层：** `profiles/cast-adapters.json` 通过 device/build-id/SDK 精确选择例外，未知设备为 `android-native`，不修改厂商包或加载旧规则。G100 S 的旧 SELinux/副屏启动器/重连处理保留在其已记录固件适配器；本轮只读复核其身份 W1WAA36.48-23-10、SDK 36、mumba，没有向 G100 S 部署或重做连接验收。X70 没有加载额外 SELinux allow，全程 Enforcing。动态 `wfd-config` 仍是发现厂商配置时的公共检查，不按机型写分辨率；本机输出 `changed:false`，生成/原厂 SHA-256 同为 `7ae2803bc882a0a7f386aa9565a38889aecacbc290cec04b4f278b46107900b4`，因此没有 bind 修改。profile/实际厂商 codec 对应的算法边界仍是前文列出的后续问题，不能将此次 unchanged 当作 4K 端到端验收。

helper 增加 capabilities/settings、明确错误码、按主动 scan/connect 启用 WFD、单调时钟超时和超时取消；status/开机不自行开启无线显示。UI 显示原因、长按进入系统接收端选择，首次无历史电视也进入该页，连接中再次点击可取消，过期请求不覆盖新状态。CastDesktop 响应外屏尺寸变化；刷新率变更的完整 renegotiation 尚未单独验证。

**交付：** `tools/cast_payload.py` 统一镜像与开发部署的载荷清单，`install.sh` 校验 SHA 后逐文件原子替换，最后发布清单；这是可恢复的文件级更新，不是整目录事务切换。首启检查载荷完整性与 service.d 副本；`tools/deploy_cast.py --serial ... --port ... --jar ... --output ...` 备份旧组件/开机脚本，独立更新当前账户并启动服务。首启的整 release 完成标记仍会跳过后续安装逻辑，因此已有完成状态设备的更新应使用独立部署器，不重跑整套首启。新镜像尚未构建/清数据验收。

**目前验证：** 用户确认电视正常；Linux 平台桥三轮断开/重连全部成功，耗时约 6.15/6.02/6.33 秒，均有 Plasma overlay、没有 Moto splash/taskbar，断开后两个 UI 包恢复。第一轮从 WFD 关闭状态自动启用并连接。手机原生分辨率与已保存 300% 保持；编码配置原样，未出现旧机型的 level 设置失败。5 项首启测试（含缺 jar/service 修复、保留 last-sink）＋11 项隔离测试通过。后台测试的实际时钟/动画画面持续更新；手机进入 Dozing 后，Android 在电视显示锁屏时钟，不能把这次结果记为息屏继续显示 Linux 通过，也不是以两张相同截图就判定编码冻结。唤醒后恢复桌面。声音已有 proxy 路由和 Linux paplay 成功，电视实际发声仍待用户确认；手机触控板/中文输入与长时媒体稳定性尚不能从画面正常推定通过。


### 锁屏分析与用户介入的验收边界

用户说明测试中手动解锁了手机，因此自动脚本的唤醒/恢复不能单独作为无人介入验收。20:50 的系统日志记录 `MotoKeyguardPresentation: 7` 覆盖电视、`wm_set_keyguard_shown` 同时作用于手机和电视，用户解锁后该窗口移除；WFD 全程 active_state=2。X70 当前 `secure=false`、`locksettings get-disabled=false`，即没有密码类安全锁但仍有锁屏。

核对 AOSP `android-16.0.0_r1` 的 [KeyguardDisplayManager.java](https://github.com/aosp-mirror/platform_frameworks_base/blob/android-16.0.0_r1/packages/SystemUI/src/com/android/keyguard/KeyguardDisplayManager.java)：普通非默认显示会得到 KeyguardPresentation，PRIVATE/ALWAYS_UNLOCKED 等条件才排除。X70 的 WFD 显示没有这些排除标志。该路径与 Moto splash/taskbar 的适配器是不同职责，不能通过停用 SystemUI 或改写整机锁屏去假装修好。当前结论是后台更新已验、锁屏遮挡已定位、用户解锁后桌面恢复；没有证明锁屏期间底层 Linux 新帧是否持续生成。以后如需“手机黑屏而电视继续工作”，应单独设计投屏息屏入口，与真正锁定设备区分；本轮未实现。G100 S 旧记录只证明当次息屏场景，不能据此断言它在相同 keyguard 状态下一定不同。

### 最终部署与异常断开补测

实现提交 `96282a7ab83cf9446ba21a11b447f7bfa525f850` 的 root 载荷已部署，摘要健康检查通过；对应 `rungic-cast 0.331` 已替换容器中的 0.278，并重启 `plasma-plasmashell.service` 加载快捷开关。APK 为 2.12/60。只关闭本次 Firefox 测试窗口并卸载临时 KWin 脚本；保留用户账户与主屏设置。备份和证据见实验目录 `linux-cast-backup.tar.gz`、`linux-install.txt`、`deploy-final/`、`final-health.txt`、`final-validation.json`。

20:58 补测直接关闭 Android 无线显示开关，绕过 helper 的正常 disconnect：resident watcher 恢复两个 Moto UI 包并删除租约，证明这条异常退出清理路径生效。但紧接着两次 connect 均超时，不能把它计入前三次成功回归。日志在关闭时出现 framework `Failed to disconnect ... reason=2`，随后建立连接请求而未完成 P2P/RTSP；最后状态为目标 TCL `available=false`。这不足以判断是接收端退出等待页还是框架清理时序问题，已请求用户核对电视画面；没有据此添加固定延时、重置整机 Wi-Fi 或改写编码参数。失败后的租约/包状态恢复与 Plasma 主屏正常已核验。该异常重连场景尚未解决，不应宣称所有失败恢复已通过。
