# Agent 使用 SIM 代打电话：可行性研究

2026-09-29。下文初步研究基于只读检查；后续获用户授权测试 10000，开发与实验进展另记于文末。

## 当前部署结论（2026-09-29，第四次实验后）

G100 / `portov_cn` / `W1VT36H.1-51-8` 已增量安装 **APK 2.20（68）与 Agent 0.367**，底座仍为 20260929.2。获授权的 10000 实测中，Realtime 说出“湖南电信”后，远端进入业务菜单，证明本机双向语音链路已工作；随后接管保持原电话、释放 Agent 音频并恢复静音状态，挂断确认回到空闲。通用通道选择、原对话卡片与转写也已部署。具体证据见文末；以下早期“未部署/上行未通过”均是对应阶段的历史状态。

这不是完整自主代办验收：开场时机、指令措辞、自动决策、真人通话、故障恢复与其他机型仍有缺口。私下语音指令和独立旁听保持关闭。能力接口的 `endToEndVerified` 暂未接入按设备持久化的验收记录，仍为 false，不能因本次实验把通用默认值改成 true。

## 初步结论与当时实现

有明确路径：Android Telecom 控制电话，Android 系统通话音频接口传输双向 PCM，再复用 Linux 通话 Agent。G100 已暴露相关音频端口；这支持进入音频实验，不能记为真实电话代谈已可用，也不能推广为 X70 / G100 S 已通过。

- [62 篇](../62-linux-virtual-audio.md)的微信路径是 Linux 微信 WebRTC → PulseAudio → 虚拟扬声器/麦克风；SIM 电话由 Android 厂商音频实现与基带处理，不会自动出现在这些设备中。
- [63 篇](../63-call-proxy.md)和 `plasma/voice-agent/call_proxy.py`已有实时对话、决策、询问主人、摘要及旁听/接管交互。后续接管与旁听修正有部分仅通过合成流测试，不能全部标记为真实通话验收。
- `AndroidTelephonyBridge.java`只提供 SIM/信号/移动数据状态与数据开关，没有拨打、接听、挂断或 PCM。现有 ModemManager 桥不是蜂窝语音后端。
- `CallProxy`仍通过 `rungic-audio-route --binary <app>`接入应用音频，接通检查绑定微信窗口。需要抽出通话后端接口。

## 上游接口与选型

核对 AOSP `android16-release`，以下源码为 Apache-2.0。源码与设备证据在 `.work/research/cellular-call-20260929/`，下载来源和 SHA-256 见 `source-manifest.json`。尚未引入上游补丁。

1. [AudioManager.java](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android16-release/media/java/android/media/AudioManager.java)：`isPstnCallAudioInterceptable()`查询能力；`getCallUplinkInjectionAudioTrack()`向正在进行的电话注入音频；`getCallDownlinkExtractionAudioRecord()`读取对方音频。隐藏的系统 API，要求 `CALL_AUDIO_INTERCEPTION`，支持 PCM16/float、8–48 kHz、单/双声道；实际设备能力可能更窄。
2. [AudioService.java](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android16-release/services/core/java/com/android/server/audio/AudioService.java)：能力查询检查权限，再检查可用设备是否同时存在 `DEVICE_OUT_TELEPHONY_TX`与 `DEVICE_IN_TELEPHONY_RX`。即使返回 true，也不是实际双向通话验收。
3. [AudioTrack.java](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android16-release/media/java/android/media/AudioTrack.java) / [AudioRecord.java](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android16-release/media/java/android/media/AudioRecord.java)：PSTN 分支设置通话重定向标志；VoIP 分支采用动态 AudioPolicy。不是普通屏幕录音。
4. [权限声明](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android16-release/core/res/AndroidManifest.xml)：`CALL_AUDIO_INTERCEPTION`和 `CONTROL_INCALL_EXPERIENCE`均为 `signature|privileged|role`。普通麦克风权限、默认拨号器角色、root shell 都不等于整个链路已获权限。发行方案应采用最小特权宿主服务，核验 priv-app、权限白名单、隐藏 API、UID/AppOps 与 SELinux；普通 `product/app`预装不是特权安装。
5. [InCallService](https://developer.android.com/reference/android/telecom/InCallService)提供 Call 对象与状态。[Android 16 InCallController](https://android.googlesource.com/platform/packages/services/Telecomm/+/android16-release/src/com/android/server/telecom/InCallController.java)（blob `6cfa4fdeabd888802ed3f02cf14c90e09aa4bc21`）允许满足权限条件的 non-UI InCallService。优先验证与原厂拨号界面共存；InCallService 本身不提供 PCM。

| 方案 | 选择与成本 |
|---|---|
| Telecom + 系统通话音频 API | 首选，复用 Android SIM/IMS/运营商与音频管理，新增宿主桥和 Agent 后端 |
| 完整替换默认拨号应用 | 增加来电界面等职责，没有消除音频权限要求；暂不优先 |
| 直接操作高通 PAL/AGM、混音器或调制解调器 | 厂商依赖大，可能与 Android 争用；仅在通用接口失败有证据后研究局部适配 |
| 扬声器与麦克风声学回环 | 隔离、回声、私下指令体验不可靠，不作为目标架构 |

本轮尚未完成厂商源码/同类项目双向音频实现对照，不能把接口存在当作跨机型选型全部完成。实现前继续核验 Android 16 原生音频策略的权限、静音行为和本机 HAL 路径。

## G100 只读结果

- 两个 ADB server 均检查：USB G100 当前在 **5037**，不是上轮剪贴板工作的 5038；序列号 `ZY32M9MRVP`。另有 G100 S Wi-Fi 连接，本轮未操作。
- 指纹：`motorola/portov_cn/portov:16/W1VT36H.1-51-8/e9ec8-e96731:user/release-keys`；默认拨号应用 `com.android.dialer`。
- `dumpsys media.audio_policy`：配置来自 **AIDL HAL**，当前 `AUDIO_MODE_NORMAL`。
- available output 有 `telephony_tx`，available input 有 `telephony_rx`。
- 有 `voice_tx`、`voice_rx`、`in_call_music`，后者带 `AUDIO_OUTPUT_FLAG_INCALL_MUSIC`；`STRATEGY_CALL_ASSISTANT`选中 `TELEPHONY_TX`，系统支持 `AUDIO_USAGE_CALL_ASSISTANT`。
- TX 声明 PCM16、8/16 kHz、单/双声道；RX 声明 PCM16、8/16/48 kHz、单声道。首次实验可从共同声明的 16 kHz PCM16 单声道开始。

据 AOSP 判断实现，这些端口符合能力查询的结构条件；**未直接调用能力查询，未创建录音/播放轨道，未证明权限、真实 PCM 或音频隔离成功**。已打开但不活动的通道也不是通话验收。

## 建议架构与验收顺序

控制链：Agent → 共享通话服务 → Android Telecom / InCallService → 原厂电话栈 → SIM。

音频链：对方 → Android 通话下行 → 宿主 PCM 桥 → Linux Agent；Agent → 宿主 PCM 桥 → Android 通话上行 → 对方。Linux 侧可复用现有虚拟设备，须验证隔离、时钟、缓冲与生命周期。

1. 抽出 `dial / answer / hangup / send_dtmf / call_state / audio / take_over`后端，微信与蜂窝分别实现，共用对话与 UI。蜂窝根据真实 Call 状态与 call ID 确认接通/结束，重连不自动重拨。服务独立于 Activity 焦点；双卡明确 PhoneAccountHandle，不能从数据卡推断语音卡。
2. 先做受控真实电话双向音频实验：读取对方，远端听到注入语音，双向同时运行不串音。需用户指定测试对象，本轮不发起电话。
3. 单独验证物理麦克风是否混入上行、电话静音是否连 Agent 注入一起静音；不能假设注入自动替代真人麦克风。私下语音指令还受通话期间并发采集限制，未通过前可先提供文字指令，但不能标称完整复刻微信体验。
4. 再验忙线/拒接、接通前彩铃、DTMF、旁听、我来接、远端挂断、进程死亡后的资源释放和原厂电话恢复。只拨号成功或有非零样本不足以验收。
5. 回归普通电话、Linux 微信和桌面音频；分别验证 VoLTE/VoWiFi、双卡、蓝牙/耳机、后台息屏及通话期间 Agent 联网。紧急呼叫保留原厂处理。

能力按控制、下行、上行、物理麦克风隔离、私下指令、接管分别暴露；差异进入 spec/适配器，不能按 Moto/高通名字宣布支持。权限/路由实验前保存配置，初步实验不修改原厂 HAL/混音器；临时服务应可停止、释放轨道、撤销包/权限配置并回归原厂电话。上述为待实施方案，非已部署功能。

## 授权后的开发实验（尚未完成）

用户插入中国电信 SIM，明确授权使用 10000 开发测试。证据目录 `.work/experiments/g100-cellular-20260929/`。

- 独立 root app_process 调用能力查询返回 true；第一次实际拨打 10000，以系统下行接口取得约 20 秒 PCM。宿主本地 whisper.cpp 转写识别出湖南电信客服提示，确认声音来源，非仅凭 RMS 判断。
- 两次离线中文语音注入，AudioTrack 写入成功，但客服没有识别短语。本地 ASR 对 espeak 中文也识别错误，故不能判为远端上行已通过，亦不能据此判为硬件不支持。
- APK 2.15 第一版已增量安装，备份在 `deployment-1/`；加入 non-UI InCallBridge，保持原厂拨号器。root CallDaemon 提供受限本地接口与独立 PCM 连接，尚未接入正式 Agent。
- app_process 未初始化 TelephonyServiceManager，第一版紧急号码判断出现 NullPointerException，尚未发起拨号。源码已补初始化，实验时临时 daemon 使用 `/data/local/tmp/rungic-call-candidate.dex`；**修正尚未重新装回 APK**，不能把本轮候选当作已完成发行版本。下述桌面恢复时已停止实验后端。
- 候选后端测试观察到真实 Call 状态 9 → 1 → 4，重复 requestId 未二次拨号；24 kHz PCM 双向连接运行约 46 秒，英文测试语音远端结果尚待核验。音频连接释放、精确 call ID 挂断后，phoneState/audioMode 均恢复 0，audioActive=false。
- G100 用户配置和运行中语音服务均无 OpenAI API key，本机也未找到已有配置；本轮尚未调用 GPT Realtime。目标继续复用 `call_proxy.py`，保留现有 Realtime 模型选择。
- 额外参考 gsm2sip `aa5e1444fe443d90868b1ad8390ade79cc9af0ca` 的 GsmCallManager / DeviceProfile / GsmCallService：其路径包含厂商混音器与设备配置。仓库元数据未声明许可证，本轮仅对照架构，不复制源码；我们的首选仍为 Android 系统通话接口。

## APK 实验后的桌面恢复（2026-09-29）

用户报告无法进入 Rungic。G100 容器仍运行，KWin 活跃，但 APK 升级切断图形连接后，kactivitymanagerd 未正常启动、plasmashell 退出 255，入口最终报告 Desktop did not become ready。不能把容器或 KWin 单独 active 当作部署成功。

- 撤去实验电话的宿主启动 hook，停止 watcher 与经完整主类核验的临时 CallDaemon，并禁用实验 InCallBridge；保留剪贴板后台桥。重复启动日志另由正式 watcher 与临时候选竞争 socket 引起，不据此认定电话后端导致了桌面崩溃。后续开发须修复 daemon 在 socket 绑定成功前覆盖 PID 文件的问题。
- 重启 kactivitymanagerd、plasmashell 后实际恢复桌面。旧 G100 会话脚本还缺少仓库已有的旧 startplasma-wayland 退出等待，增量补入这段顺序修正后，force-stop APK 再打开可进入 Plasma；等待加载完成后的截图已保存。
- 用户进一步指出“设置 → 服务”缺失。核实设备是 `20260928.1+clipboard1`，大部分项目包仍为 0.278；`rungic-plasma-services`、服务策略及 KCM 均不存在。此前该功能只在 G100 S 验收。不能混同机型和单组件增量更新与整套发布。
- 恢复证据：`.work/experiments/g100-rungic-recovery-20260929/`；随后按用户要求进行完整版本升级，记录另见 [G100 系统更新](g100-system-update-20260929.md)。电话 Agent、上行远端语音效果和微缩通话 UI 仍未完成验收。

## 通话微缩交互要求（2026-09-29）

用户要求通话时使用微缩模式，不占全屏。纳入本次电话功能目标，**尚未实现或验收**：

- Agent 通话默认显示可移动、贴边的小型通话条，显示对象、状态与计时，保留挂断入口。
- 点开显示通话详情与可用的接管/旁听控制，收起后通话继续；只有用户主动打开详情时才展开。
- 需要用户答复时突出提示，不自动抢占全屏；通话结束后显示结果提示并收起。
- 通话条之外不遮挡、不模糊、不拦截桌面触摸；切换应用与屏幕不改变通话生命周期。
- 现有 `AssistantOverlay.qml` 是全屏 LayerShell 窗口，input mask 覆盖导航栏以上区域，不能只把视觉卡片缩小就声称实现微缩。须配套缩小输入区域或使用独立小窗。
- Android 原厂通话界面和 Linux Agent 界面分别处理：Agent 发起电话后应能回到 Linux 小窗，仍保留原厂电话入口；不能用持续抢前台的方式覆盖用户正在操作的应用。

## Realtime 接入与第二轮部署（2026-09-29，未完成双向验收）

执行时现场核验：开发机 `mibook` / x86_64；目标仍为 5037 / `ZY32M9MRVP` / G100。Mac mini 构建端现场返回 `chou-Mac-mini.local` / arm64，`scutil --proxy` 的 HTTP/HTTPS 端口为 6152。这里只记录本次事实。

用户指定的 `/home/kevinzhow/.config/rungic-voice-agent/openai-api-key` 实际在 **G100 的 Linux 容器**，本机同路径不存在。按容器原路径读取，权限从 0644 收紧到 0600；未复制、输出或提交密钥。真实 WebSocket 返回 `session.created`、模型 `gpt-realtime-2.1-mini`；保留项目既有模型。

官方协议对照：[Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)。本轮实测 `session.update` 的 nested audio 配置、24 kHz 单声道 PCM、输入转写及输出音频事件可用。通话端继续复用 `call_proxy.py` 的 Realtime 对话、文字指示和摘要，蜂窝运输放在 `cellular_audio.py` / `cellular_call.py`，不经过微信的 PulseAudio 路由。

### 当前已安装候选

- APK **2.18 / versionCode 66**，`rungic-voice-agent` **0.365**，源码提交 `c6f92bc0`；底座仍为 `20260929.2`，这不是新的完整发行包。
- `plasma/android-calls` 生命周期进入宿主控制器、host seed 与 release Android 清单。实际部署保留数据覆盖安装；备份 APK / controller / helper 在 `deployment-2/`。源码 APK 内的 non-UI InCallService 保留原厂电话界面，实验阶段禁用的 component 已重新启用。
- root daemon 绑定 socket 成功后才写 PID，避免第二实例覆盖有效 PID。拨号 request ID 写入本地持久文件后才调用 Telecom，不在网络恢复时重拨。
- 音频拥有者断开时释放 AudioRecord/AudioTrack、恢复原静音状态。InCallService 持有独立的 4 秒静音租约；daemon 每秒续期。SIGKILL 恢复机制已实现，但本轮未做实机故障注入，不能标为通过。
- 用户态 `StartCall` / `--start-call` 支持 `app=cellular, number=...`，Realtime 就绪后才拨号；`--call-text` 为文字指示，`--call-dtmf` 为按键，`take-over` / `hang-up` 绑定真实 call ID。
- 私下语音指令及独立旁听开关明确关闭。未证明物理麦克风隔离，UI/能力报告不能宣称已验证。
- Plasma 实际重新进入成功；SSH `ssh.socket` 保持 enabled / active，没有修改关闭策略。

### 两次 10000 实验

证据统一在 `.work/experiments/g100-cellular-20260929/`：`realtime-1.jsonl`、`realtime-2.jsonl`、`realtime-call-2.png`、`compact-touch-2.png`、构建/安装日志及 APK。

1. **第一次**（APK 2.17 / Agent 0.364）：拨号、接通、打开通话音频成功；从 root app_process 的 system Context 启动 MainActivity 被 Android 拒绝。异常使 Agent 提前交回通话，未完成 Realtime 代谈。观察到静音恢复为 false，按 call ID 挂断后 phoneState/audioMode=0、audioActive=false。不能把这次当作上行测试通过。
2. **第二次**（APK 2.18 / Agent 0.365）：改用宿主控制器同类的 `am start --user 0` 返回 Linux，一次执行而非持续抢前台；UI 失败也不再中断音频。Realtime 识别出湖南电信 10000 的归属地转接菜单；Agent 生成语音，并接受私下文字指示后生成“湖南电信”。远端后续仍播报“没有听清”，**上行远端语义响应未通过**。可能涉及静音影响、实际 TX 路由、音量/格式或菜单时序，当前证据不能选定根因。
3. 第二次的电话由测试结束流程挂断。最终记录 `calls=[], phoneState=0, audioMode=0, audioActive=false`，没有残留通话。摘要只是模型对转写的归纳，不能用摘要替代远端听到声音的证据。
4. 微缩条在 Linux 桌面显示对象、通话状态和挂断；条外点击应用抽屉成功。该次抽屉截图取得时电话已结束，所以仅与点击时序共同作为初步触摸证据，尚需在同一截图/记录中确认持续通话与其他应用并存。拖动、详情输入、接管及多输出完整回归未完成。首次截图的计时被对象名挤掉，后续本地改为独立两行，尚未部署。

### 受限环境下的后续源码检查（尚未部署）

用户继续时执行环境切换为 workspace-write / network restricted / approval never。现场 `ip route` 的 netlink 与 ADB 5037 socket 均报 `Operation not permitted`；并非设备断线的证据。自此没有继续发起电话、修改手机或远程构建。`.git` 只读，新修改未提交；不能把源码工作树等同于手机已安装版本。

用户随后指出自己使用 `--yolo`。2026-09-29 复查本条会话的 rollout `turn_context`（只读取权限元数据，未复制对话正文）：北京时间 09-28 11:09 为 `danger-full-access / permission_profile=disabled`；14:56 变成 `workspace-write / network_access=false`；15:05 恢复完整访问；09-29 17:13:37 再次变为受限策略。`approval_policy` 一直是 `never`。因此 `--yolo` 对应的权限曾实际生效，不能说用户没有授权或把 never 单独当作完整访问。现场 CLI 为 0.157.1，实际命令沙箱来自 app-server-daemon 0.159.0；版本差异仅作线索，不作为已确认原因。现有元数据没有说明由哪个客户端/恢复请求触发切换，不能断言升级、IDE 或用户操作导致。排查应核对会话恢复/后续 turn 的权限传递；拔插手机不会修复这一层限制。官方参数说明见 [Agent approvals & security](https://learn.chatgpt.com/docs/agent-approvals-security)。

本地已补：

- Android 最后一个 Call 结束后会解绑 InCallService；`phoneState=IDLE` 仍能确认通话结束。不能因 `available=false` 永远留下接管后的通话条，也不能把 busy 状态下丢失/重建 call ID 当成已挂断。
- Realtime 就绪前用户取消时禁止随后拨号；状态回归还覆盖彩铃不打开 PCM、UI 失败保持音频、失去 call ID 只交回不重拨，以及接管幂等。
- 增加无音频正文的诊断：写入/采集字节数、PCM 峰值、播放帧数、underrun、实际路由设备类型、采样率及系统静音状态。它们用于排查，不等于远端可听验证。
- daemon 检测通话途中系统解除静音后释放 Agent 音频，避免继续声称隔离。此行为未做实机验收。

验证边界：第一次受限切换前 5 项 socket-pair 音频测试通过。切换后重跑，其中 4 项在 `sendall` 被沙箱拒绝，1 项纯缓冲测试通过，不能记录为代码回归失败或全部通过。新增 `tools/tests/test_cellular_state.py` 的 **8 项无 I/O 状态测试通过**；Android 36 SDK 上三个 Java 类编译通过。QML 修改尚未完成新构建/实机验收。

### 上行下一步实验与研究线索

先固定 PCM、菜单提示后的发送时机和当前通话 ID，保存 AudioFlinger/AudioPolicy 与上述诊断，再比较“系统静音”与“短暂取消静音”的远端响应。取消静音只是授权 10000 的受控实验，不作为产品修复；绝不能为了听到上行而默默把用户房间声音混入代打电话。应使用独立 root 探针并恢复原静音状态；新版租约守卫会在解除静音时退出，不能把它的退出误判为硬件失败。不要沿用旧 `CallProbe.java` 的全局 endCall watchdog，后续清理仍绑定精确 call ID。

一个历史源码线索：[AOSP qcom audio 合并提交 6c480d7 的 voice.c 修改](https://android.googlesource.com/platform/hardware/qcom/audio/+/6c480d775814f3b9182180fdce3808e7df2e0703%5E1..6c480d775814f3b9182180fdce3808e7df2e0703/)在 incall music 活跃时区分设备 TX mute 与混合后 voice stream mute。这支持“静音可能连注入一起静音”作为待验证假设；它是 **2019 旧 Qualcomm HAL 的实现**，不是 G100 Android 16 AIDL HAL 的来源证明。本轮未找到并核验当前设备对应 PAL/AIDL 实现，未修改 mixer、HAL 或 SELinux。不得直接照搬该旧实现。

另外，现有共享对话监督依赖 TypeSafe key；本次 `call-step` 一直为 CONTINUE / 0.0。没有该 key 时，GPT Realtime 会说话但尚无完整自动询问主人/结束通话决策的替代路径。此缺口、远端上行、打断时的已播/未播语音同步、租约故障恢复和普通电话/微信回归仍需完成，不能宣称“电话 Agent 已完成”。

## 按用户意图选通道与共享卡片（2026-09-29，本地实现，未部署）

用户明确要求：**“打电话”走手机卡，“打微信电话”走微信**。查询当前能力只核验指定方式的前提；不可根据可用性、上次成功的 App 或机型自动改换通道。联系人/号码有歧义时只澄清该歧义。此规则进入 `rungic-phone-desktop/SKILL.md` 和按需引用的 `calls.md`，不把 10000、G100、开发机名或本轮未验收能力写成通用默认。

本轮先对照 63 篇的微信代理和 89 篇的会话记录实现，并检查 `CallProxy`、`VoiceAgent`、`ChatModel`、`ChatEntry` 与打包脚本。复用项目现有 Realtime 引擎、卡片和两个音频后端，不引入第三方组件或另一套硬件通路；项目 Python 为 MIT，QML 为 GPL-2.0-or-later，许可证不变。

- 新增 `call_backends.resolve`，接受显式 `backend=cellular + number` 或 `backend=app + app`。兼容原来明确指定 `app=cellular` / `app=wechat` 的调用；缺少通道信息不再默认微信。冲突参数在创建代理前拒绝，不拨号、不回退。
- 新增 D-Bus `CallCapabilities` / CLI `--call-capabilities`。读取本次 Telecom 账户、音频接口与应用路由前提，不拨号、不输出 key。连不上后端保留为未知，不能推断硬件不支持；`audioInterfaceAvailable` 与 `endToEndVerified` 分开，后者当前为 false。
- 每次通话有独立 `callId` 和发起它的 `conversation`。转写、状态、错误、文字指示及结果始终写入原对话；切换对话不迁移卡片。历史与状态快照按 ID 恢复同一张卡片，不把旧通话复活为新通话。
- 卡片显示实际通道/对象，从接通时计时；提供文字指示、接管、挂断和按后端能力显示的旁听。蜂窝失败提示指向系统电话，其他 App 指向通话应用。卡片/微缩条命令携带 `callId`，服务拒绝旧卡片操作下一通通话；既有面向当前通话的 CLI 保持兼容。
- 共享事件写入器尊重显式 conversation，不再把标着旧会话的事件存进当前会话。延迟到达的旧通话事件不会暂停新通话或在另一个对话播报结果。
- 打包纳入 `call_backends.py`；现有技能 Markdown 打包通配符包含 `calls.md`。

离线验证：`test_call_backends.py` 5 项、`test_call_conversations.py` 5 项、`test_call_cards.py` 7 项、`test_cellular_state.py` 8 项，共 **25 项通过**。卡片测试实际执行 Qt/QML 的 ChatModel，并加载真实 ChatEntry 与共享设计控件；仅原生 SystemTheme/AgentClient 适配器使用替身，不代替完整 Plasma 窗口与 D-Bus 验收。技能 quick_validate、Python 语法与 diff 空白检查通过。

本节所有新修改尚未部署、未提交；设备安装版本仍以前一节为准。SIM 上行与完整微信回归等未验收项仍保留，不能用离线卡片测试代替真实双向通话。恢复可访问设备的执行环境后，先核验当前主机/连接/设备/安装版本，再部署并核对原对话卡片、切换会话、微缩条、接管/挂断，以及获授权测试目标的真实远端响应。

## 权限恢复后的部署与第三次 Realtime 实验（2026-09-29）

重新现场核验为 mibook / x86_64，系统代理 none、路由可读；G100 `ZY32M9MRVP` 的 USB 当前在 **5038**，5037 仅列出另一台无线设备。固件仍为 `W1VT36H.1-51-8`。Mac mini 实际为 `chou-Mac-mini.local` / arm64，构建继续按 `scutil --proxy` 使用 6152 系统代理。不能沿用早先的 5037 命令。

- 提交 `207b7ec2` 包含通用入口、技能、卡片、状态修复及 Android 诊断；APK **2.19 / versionCode 67** 保留上一候选的 JNI 库和无 OCR 模式，覆盖安装成功。回退 APK 在 `deployment-3/before.apk`。
- Agent 先构建/安装 **0.366**；实机发现旧卡片转写 delegate 同时把 `text` 用作模型角色和富文本输出，文字绑定冲突，记录存在但屏幕留空。改为外层持有角色、内层 Text 渲染，加入真实 ListModel 转写的 QML 断言。提交 `a6b7f7b4` 构建/安装 **0.367**。`call-card-fixed.png` 已确认双方转写和结果实际显示。
- 技能 SKILL.md、calls.md 与 call_backends.py 的设备 SHA-256 均与源码一致。助理与 overlay 服务 active；`ssh.socket` 仍 enabled / active。权限恢复后 5 项 socket 音频测试全部通过，前述 25 项离线测试中的 QML 用例进一步覆盖转写正文与 HTML 转义。
- `--call-capabilities` 实机返回 cellular reachable/audioInterfaceAvailable=true、1 个中国电信语音账户，keyConfigured=true；endToEndVerified 仍 false，未改变未经验证能力的标注。

第三次 Realtime 10000 实验（`realtime-3.jsonl`）：真实拨号、接通；原助理对话中的卡片显示“手机电话 · 10000”、接通计时与文字指示/接管/挂断。文字指示发给通话 Agent 后产生对应转写；切换到新建测试对话，再回原对话，call ID 和 connectedAt 保持一致，已保存的 9 项事件全部属于原对话。测试通过携带 card callId 的命令挂断，得到 hanging-up → call-ended，最终 phoneState/audioMode=0、audioActive=false、State.callInfo=null。未把控制请求当作挂断确认。微信真人通话本轮未重拨，不增加其端到端验收范围。

上行仍未通过：24 kHz PCM 确有非零样本，写入峰值 15934、播放帧数增长、underruns=0，TX/RX 都是 TYPE_TELEPHONY。远端仍重复“没有听清”。`audio-policy-3.txt` 显示 CALL_ASSISTANT 的轨道进入 `voice_tx`，另有 `in_call_music` 输出（AUDIO_OUTPUT_FLAG_INCALL_MUSIC）却未活动。此为后续路由实验线索，不能把已消费 PCM 等同于基带已发送。原厂 HAL、SELinux、mixer 均未修改。


## 显式通话上行路由与第四次 Realtime 实验（2026-09-29）

### 源码核验与选型

对照 [LineageOS Android 16 / lineage-23.0 的 AudioPolicyManager.cpp](https://raw.githubusercontent.com/LineageOS/android_frameworks_av/lineage-23.0/services/audiopolicy/managerdefault/AudioPolicyManager.cpp)（Apache-2.0，读取版本 SHA-256 `1f07dc56cc013c68ceea3fcc6fddc72d6159759a1dcb68836e51bdaf7c9fcb99`）：显式请求 TELEPHONY_TX、VOICE_COMMUNICATION 用途、线性 PCM 且通话音频允许访问时，策略选择 INCALL_MUSIC。该源码是可复用机制的核验，**不是已安装 Motorola 固件源码的证明**；AOSP frameworks/av 对应分支本轮抓取失败。源文件及来源清单保存在 `.work/research/cellular-call-20260929/`。

选择复用 AudioTrack / AudioPolicy 的显式设备路由，不修改厂商 HAL、mixer 或 SELinux。直接使用 CALL_ASSISTANT 重定向接口虽接收 PCM，却在本机选到未产生远端响应的 voice_tx；自行操作 PAL/AGM 的厂商维护成本更高，本次标准路由实测成功后无需引入。

### 隔离实验

所有拨号仅为用户授权的 10000，清理绑定每次真实 Telecom call ID，无全局挂断。固定语句为“湖南电信”，24 kHz / PCM16 / mono，探针与原始媒体只放 `.work/experiments/g100-cellular-20260929/`。

- `mute-probe-1/` 的两次发送与客服提示重叠，不能用于判断静音因果。`mute-probe-2/` 调整时机后，旧路由下静音及短暂解除静音均未进入下一菜单；取消静音不是有效产品修复，也不证明所有设备的静音行为。
- `route-probe/` 改为 VOICE_COMMUNICATION + 运行时发现的唯一 TYPE_TELEPHONY 输出，保持系统静音。实际路由类型为 18；`audio-policy-route-probe.txt` 记录 in_call_music 活跃、AUDIO_OUTPUT_FLAG_INCALL_MUSIC。远端随后询问湖南宽带、手机号码激活或报故障，构成远端识别语句的语义证据。端口编号只留作该次诊断，不进入产品代码。

### 部署实现

APK **2.20 / versionCode 68** 的 `CallDaemon.AudioSession` 枚举本次可用通话输出；无输出或多个输出时明确失败，不猜测机型、卡槽或端口。通过 `setPreferredDevice` 请求该输出，确认 Telecom/AudioManager 静音后以静音 PCM 建立路由，再校验实际设备类型与本次设备 ID，才开放 Agent PCM 连接。监听路由变化，并在每块语音写入前检查；失去目标路由即释放音频。租约继续绑定精确通话，接管/关闭恢复原静音状态。部分初始化失败时也分别尝试停止和释放录音/播放对象，避免 stop 异常跳过 release。

APK SHA-256：`43c8bb6ec64e9417b193166feca06990965e8d36bc76214fa84c26ceb771d8b0`；Agent 0.367 deb SHA-256：`eaac2d285f1f94084483df04af8bd485e556f1662814422822a65b2f66a6623a`。当前 APK、构建日志与覆盖安装记录在 `apk-2.20/`、`build-2.20.log`、`deployment-4/`；前一版 2.19 APK 为 `deployment-4/before.apk`。必要回退须先确认无通话，停止 android-calls watcher，以 Android shell 上下文安装回退 APK，再启动 watcher 并核验状态；回退会恢复旧上行缺陷，不记作可用通话版本。无需刷写或修改底座，SSH 自动开启保持不变。

### 第四次实机验收与边界

证据：`realtime-4.jsonl`、`call-card-4.png`。安装版本 APK 2.20 / Agent 0.367，模型 `gpt-realtime-2.1-mini`，设备上的 key 留在原配置位置，未输出或复制。

1. 使用正式 Agent、共享卡片和新音频后端拨打 10000。Agent 说出“湖南电信”后，远端进入宽带/号码激活/报故障菜单，`remoteMenuAdvanced=true`。发送 PCM 峰值 22555、underruns=0，系统静音保持 true；后两项只是诊断，菜单响应才是远端听到的证据。
2. 通过携带卡片 ID 的“我来接”命令，原 Telecom call ID 仍为 ACTIVE；Agent 音频已关闭，静音恢复 false，callPhase=user。未做接管后的真人听说验收。
3. 随后同一卡片挂断，收到 hanging-up → call-ended。最终 `calls=[]`、phoneState/audioMode=0、audioActive=false、State.callInfo=null。未办理业务或转人工。
4. Android 36 SDK 全量 APK 编译通过；卡片/通道/会话/状态共 25 项测试通过，权限恢复后另有 5 项 socket 音频测试通过。这些离线测试不替代通话验收。

剩余问题：自动开场可能打断 IVR，Agent 对“保持安静”等主人指示可能多说一句确认；共享监督缺少 TypeSafe key 时没有完整自主询问/结束决策替代路径，本次结束由测试命令控制。专门的物理麦克风隔离挑战、租约强杀恢复、蓝牙/耳机、真人通话和其他手机/运营商未验收，私下语音指令及独立旁听仍关闭。微信本轮没有重拨真人联系人，其既有验收范围不扩大。今后继续按实际设备能力探测与远端响应验收，不能把本机成功写成所有 Android 手机支持。

## G100 S（mumba_cn）增量部署（2026-09-29 21:15–21:26，未做通话验收）

- 设备：`motorola/mumba_cn/mumba:16/W1WAA36.48-23-10`，SELinux Enforcing，未插 SIM。这是 G100 S，不是上文实验用的 G100（portov_cn）；上文所有实验结论不适用于本机。
- **APK 2.23（71）**：包含剪贴板后台和本通话栈，由 `tools/deploy_clipboard.py` 与剪贴板后台一起安装，备份在 `.work/deploy/moto-2.23-clipboard-*`。
- **宿主**：
  - `plasma/android-calls` 放入 `/data/adb/rungic-plasma/`；控制器按仓库 `plasma/rungic-plasma` 的位置插入启停钩子（停止时先于剪贴板，启动时在剪贴板之后），用 rename 原子替换。
  - 原控制器备份在 `.work/deploy/moto-2.23-calls-20260929-222525/controller.before`。
  - `CallDaemon` 以 app_process 运行，日志无错误。
- **容器**：语音服务及 `call_proxy`、`cellular_audio`、`cellular_call`、`call_backends`、语音助手 App（通话卡片、微缩通话条）、技能 `calls.md`，按打包脚本的位置临时安装，未重新打包。
- **只读能力检查**（`rungic-voice-agent --call-capabilities`）：
  - cellular 后端：reachable，通话音频接口可用；账户只有“紧急呼叫”（无 SIM），`endToEndVerified: false`。
  - app 路由可用；已配置 OpenAI key。
  - 没有拨号，也没有做任何真实通话测试。
- 部署后用户主屏幕、plasmashell、工作区和语音服务都正常。
- **回退**：`android-calls stop`，恢复 `controller.before`；容器文件按旧版本重装。
