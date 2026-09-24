# 通话代理：语音助手替用户打电话、接电话

用户要求（2026-09-25）：
- 在语音助手里随时可以进入：由助手发起微信电话，或者接过正在进行的通话。
- 助手作为对方听到的“麦克风”，自己听、自己说；手机的真麦克风只用来听用户的指令。
- 开场表明是 AI 助理；可以旁听；约定、答应事情、涉及钱，一律先问用户。
- 下一步做什么由 JEV 判断。

## 结构

```
微信通话 ─ 对方的声音 ─▶ Linux 扬声器 ─monitor─▶ 通话助手（OpenAI Realtime 直连，gpt-realtime-2.1-mini，只负责听和说）
         ◀─ Linux 麦克风 ◀─ Linux 麦克风输入 ◀────── 通话助手的声音
                    每句话之后 ─▶ JEV（TypeSafe SystemOne）选下一步 ─▶ 程序执行
用户 ─ 按住说话（真麦克风）─▶ 转写 ─▶ “[主人指示]”或“[主人答复]” ─▶ 通话助手（对方听不到）
通话助手要问的话 ─▶ 对方原话经 TTS 在用户一侧播放，并显示在聊天卡片里
旁听：module-loopback，Linux 扬声器 monitor 与 Linux 麦克风输入 monitor → 手机本机输出
```

- 音频路由：`moto-audio-route --binary wechat --microphone --speaker`（[62篇](62-linux-virtual-audio.md)）。微信通话音频全部关闭3 s后，判定对方已挂断，代理随之结束，这样之后的通话不会被误接管。
- 通话助手：`plasma/voice-agent/call_proxy.py`，安装到`/usr/local/lib/moto-voice-agent/`。
  - 不经Codex：Codex的实时会话只提供两个固定工具，而这里需要自定义控制。
  - websocket-client经用户代理连接`wss://api.openai.com/v1/realtime`。
  - 使用服务端VAD：对方说话时打断助手，并丢弃未播放的语音。
  - 转写统一转为简体（python3-opencc）。
- JEV做调度：每当对方或助手说完一句、用户说话后，把目标、最近12句对话、待回复的问题、未转达的答复作为状态，从6个选项中选一个：
  - `CONTINUE`：继续；
  - `ASK_OWNER`：把对方原话转给用户，并记下正在等答复；
  - `RELAY_ANSWER`：提醒助手转达；只在用户答复后、助手说过话仍未转达时才提醒；
  - `WAIT_OWNER`：等用户答复；
  - `END_CALL`：等助手说完后挂断，再生成文字摘要；
  - `HAND_OVER`：助手说一句转交的话后，把麦克风和扬声器还给微信。
- 程序侧的保护：
  - 动作阈值：`ASK_OWNER`、`RELAY_ANSWER`为0.6；`END_CALL`、`HAND_OVER`为0.9/0.8。
  - 对方的同一句话只问用户一次。
  - 决策返回时对话已有新内容，则作废重判。JEV约1.2 s，曾因此把答复重复转达了一次。
  - `END_CALL`还要求用户最后一次说话之后对方又说过话；用户亲口说“挂”时除外。
- 语音服务（`moto_voice_agent.py`）：
  - D-Bus新增`StartCall(json)`和`CallCommand(monitor-on|monitor-off|take-over|hang-up)`，命令行为`moto-voice-agent --start-call '{...}'`和`--call-command …`。
  - 通话中按住说话不再送往助手自己的实时会话，松开后转写并交给通话助手。
  - `State`增加`call`字段。
- 挂断：`moto-cua press-control wechat 'Hang Up' …`。它按名字在该应用的所有窗口中找控件并点击。微信通话窗口里挂断按钮的实际名称，要在真实通话中确认。
- 界面：聊天中的通话卡片。
  - 显示对象和目的，并逐行列出“对方/助理/你/问你/记录”；结束后显示结果。
  - 按钮：旁听/停止旁听、我来接、挂断。
  - 通话中，按键下方提示“按住对通话助理说（对方听不到）”。
- 助手的用法写在技能说明中：打出电话时，先按读音找人、核对对话标题，再点`Voice Call`，然后`--start-call`；通话中用户说“你来接”，直接`--start-call`；只打用户要求打的电话。

## 验证

- JEV决策探针（6个典型场景），每次约1.1–1.3 s：
  - 对方提出时间 → `ASK_OWNER` 0.97
  - 用户已答复 → `RELAY_ANSWER` 1.0
  - 已转达并互相道别 → `END_CALL` 1.0
  - 对方要找本人 → `HAND_OVER` 0.99
  - 已问、在等 → `ASK_OWNER` 0.49 / `WAIT_OWNER` 0.40，由“同一句只问一次”兜住。
- 离线测试（`python3 call_proxy.py --test`：往 Linux 扬声器播放合成的“对方”，录 Linux 麦克风）：
  - 最终版本：开场表明身份并说明来意 → 对方提出“周六晚上七点可以吗” → 助手说“我跟凯文确认一下” → `ASK_OWNER`，用户听到对方原话 → 用户答复后助手转达“凯文说可以，周六晚上七点见” → 对方道别后助手道别 → `END_CALL`，挂断并生成摘要。
  - 过程中修正的问题：
    - 未转达就挂断：由要求对方再次说话的规则兜住。
    - 口头说要问用户、却没有真正去问：改由JEV判断，不再依赖语音模型调用工具。
    - 重复提问：同一句只问一次。
    - 重复转达：作废过期的决策。
    - 摘要角色混淆：通话记录改用中文角色名。
    - 繁体转写：统一转为简体。
- 服务冒烟测试（对不存在的应用`StartCall`）：
  - 状态`call: true`；旁听建立2个回环。
  - `hang-up`后`call: false`，回环与路由进程都已清除。

## 首次真实通话后的修正（2026-09-25）

用户实测后反馈了四个问题：
1. 接通后十几到二十秒没有反应；
2. 点“我来接”后双方都听不到；
3. “我来接”之后卡片里没有了挂断按钮，状态结束不了，语音助手也可能用不了；
4. 分不清是自己在打电话，还是在和语音助手说话。

- **听不到的原因**：
  - 代理把微信通话流移到 Linux 设备时，PulseAudio的`module-stream-restore`按应用名记住了这次移动；微信通话流的应用名是通用的“Chromium”和“Chromium input”。
  - 微信重建通话流时，新流被直接放到 Linux 设备上。路由工具认为它“已经在目标设备上”，没有记录，挂断或接管时也就不会还原。
  - 当时查证：新建的“Chromium”播放流直接落在`linux_speaker`上，也就是说，此后普通的微信通话也会没有声音。
- **修复**：
  - `plasma/pulse.pa`改为`module-stream-restore restore_device=false`，并在运行中重新加载该模块。现在各应用跟随默认设备，只保留音量记忆；复查确认“Chromium”落在`android`、“Chromium input”落在`android_microphone`。
  - `moto-audio-route`：已经在目标设备上的流也记录下来，结束时还原到默认设备（`@DEFAULT_SINK@`、`@DEFAULT_SOURCE@`）；`ready`改为第一行输出。原先这类流会在`ready`之前输出一行，调用方于是判定路由没有启动。
  - 旧代码在这种情况下留下了孤儿路由进程；现在通话代理启动失败时会撤掉路由。
- **先准备，再拨号**：`StartCall`等Realtime会话`session.updated`之后才返回，并可带`"dial": "Voice Call"`，由代理自己用`moto-cua press-control`拨号。技能说明改为不再手动点拨号。
- **三个状态**：
  - `agent`：助理通话中。
  - `user`：你在通话中。点“我来接”后路由撤掉，语音助手的实时会话暂停，按住说话不可用，并提示“你正在通话中，挂断后语音助手自动恢复”；卡片只保留“挂断”；每秒检查一次微信通话音频，连续3秒不存在即判定通话结束。
  - `ended`：通话结束，语音助手自动重新连上。
  - `State`增加`callPhase`字段。
- **自动测试**（`fakecall`，即改名后的`pacat`，作为独立的通话应用）：
  - 预先把一条录音流放在 Linux 麦克风上，再启动代理：播放和录音都在 Linux 设备上，`callPhase: agent`。
  - 执行`take-over`后，两路都回到`android`和`android_microphone`，`callPhase: user`。
  - 关闭流后`callPhase`为空，也没有残留的路由进程。
  - 打开一个对话后重复上述流程：语音助手的状态依次为`ready`（助理通话中）→`connecting`（你在通话中，已暂停）→`ready`（结束后自动恢复）。

## 第二次实测：电视黑屏、没打出去却以为打了（2026-09-25）

- **电视黑屏**：
  - 日志：`PowerGroup: Powering off display group due to timeout (groupId=2, millisSinceLastUserActivity=300000)`。
  - 电视是独立的显示组，有自己的息屏计时。对电视的操作都经宿主进入 Linux，Android 看不到任何操作，所以5分钟后就关了电视。与通话无关，只是时间恰好碰上。
  - 修复（APK 1.36）：投屏悬浮窗加`FLAG_KEEP_SCREEN_ON`。Android 14起每个显示屏各自持有亮屏锁。
  - 复查：`dumpsys power`中有`SCREEN_BRIGHT_WAKE_LOCK 'WindowManager/displayId:19'`（持有者dev.moto.plasma）。超过5分钟不黑屏还需再观察确认。
- **误报已拨号**：
  - `dial`用`press-control`，按名字点第一个匹配的“Voice Call”：不看是哪个窗口、哪个对话，点完也不检查结果，却返回`"dialed": "Voice Call"`。Agent据此告诉用户“通话正在进行中”。
  - 改为三步：
    - `moto-cua focus-showing wechat <联系人>`：把显示该联系人对话的窗口切到前台；找不到就拒绝拨号，不让执行器在别人的对话里操作。
    - 由JEV执行子任务“在这个对话里给<联系人>发起语音通话（不是视频）”。
    - 以系统信号确认：8 s内微信打开了通话音频（路由看到新的流），才返回`"dialed": true`；否则如实返回失败，并附上JEV的动作记录。
  - 卡片显示“正在拨号… / 已拨出，等待接听 / 没能拨出 / 助理通话中”。
  - 测试：用不存在的联系人拨号，6 s内拒绝，没有点击任何东西，也没有残留路由。
- **根本方向（用户要求）**：整个操作电脑的过程，都应由JEV逐步决定做什么、点哪里；参考[typesafe-computer-use](https://github.com/awlevin/typesafe-computer-use)（MIT，24eb292）。评估见下一节。

## 待验证## 待验证## 待验证

- 与真人进行微信通话：接通前的铃声是否会被当成说话（提示词要求对方先开口后助手才说话）；微信通话窗口挂断按钮的名称；来电接管；端到端延迟。
- 已知的语音问题：mini模型偶尔有生硬措辞或多一句过渡语。如果真实通话中明显，可以试完整版`gpt-realtime-2.1`（`MOTO_CALL_MODEL`）。
