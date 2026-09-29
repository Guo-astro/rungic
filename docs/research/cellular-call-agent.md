# Agent 使用 SIM 代打电话：可行性研究

2026-09-29。下文初步研究基于只读检查；后续获用户授权测试 10000，开发与实验进展另记于文末。

## 结论与现有实现

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
