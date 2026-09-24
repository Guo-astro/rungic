# 语音Agent：GPT Realtime 驱动 Codex

2026-09-24。目标：用户点按钮后说话，由 Agent 在本机 Linux 桌面上完成工作。第1步原型已在实机跑通。

## 选型与来源

| 组件 | 版本/来源 | 许可证 | 说明 |
|---|---|---|---|
| Codex CLI 完整包 | `codex-package-aarch64-unknown-linux-musl.tar.gz`，[rust-v0.156.1](https://github.com/openai/codex/releases/tag/rust-v0.156.1)（2026-09-23），SHA256 `fdd47ed6aade0360796fd3f6f95a45096f327c15e19e8c7339f9dc5633041786`（与GitHub发布摘要一致） | Apache-2.0 | 含`bin/codex`、`bin/codex-code-mode-host`（执行命令必需；单独的CLI二进制缺它时Agent无法执行命令）、rg、bwrap、语音运行时 |
| 实时语音 | OpenAI Realtime（Codex默认`gpt-realtime-1.5`，协议v2），输入转写`gpt-4o-mini-transcribe` | 云服务 | 经Codex app-server使用 |

调研时核对的是Codex源码`29f056c`（2026-09-24），调研范围也包括其他语音识别与语音合成方案。

## Codex 如何用实时语音调用 Agent（源码核实）

- 实时会话只给语音模型两个工具：`background_agent`与`remain_silent`（`codex-api/src/endpoint/realtime_websocket/methods_v2.rs`）。
- 语音模型调用`background_agent(用户原话)`时，Codex在同一线程开始一轮Agent任务。若Agent正忙，这段话会作为补充指示并入当前任务（steer）。
- Agent的进度和结果作为该函数调用的返回值送回语音模型，由它播报；不值得播报时调用`remain_silent`。
- 语音模型使用服务端VAD：检测到用户说完就开始回应，用户开口则打断当前播报。
- 这一切都在`codex app-server`（JSON-RPC，实验性接口需在初始化时声明`experimentalApi`）中实现：
  - `thread/realtime/start`、`appendAudio`（base64 PCM）、`appendText`（只追加对话项，不触发回答）、`stop`；
  - 通知`thread/realtime/outputAudio/delta`、`transcript/done`等；
  - Agent执行命令、改文件时的审批以服务端请求形式发给客户端。

## 认证与代理

- 用户用ChatGPT账号经设备码登录（`codex login --device-auth`），Agent任务使用该账号。
- Codex 0.156的WebSocket实时会话必须使用API Key（`realtime_api_key`：ChatGPT登录时临时从`OPENAI_API_KEY`读取）。WebRTC传输可以用ChatGPT账号，但媒体走UDP，用户的HTTP代理无法转发，因此不用WebRTC。
- 用户提供的API Key只保存在容器内`~/.config/moto-voice-agent/openai-api-key`（目录700、文件600），仅在启动`codex app-server`子进程时传入，不进仓库、文档或日志。
- **代理**：
  - 所有Codex流量必须经用户指定的`http://192.168.5.45:6152`。`/usr/local/bin/codex`是包装脚本（`plasma/codex/codex-wrapper`），每次先加载`/etc/profile.d/proxy.sh`。
  - 源码核实：reqwest与实时WebSocket拨号器（`websocket-client/src/dialer.rs`，tokio-tungstenite proxy特性）都遵循`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY`。
  - 实测：登录（在清空所有代理变量的情况下启动）、`codex exec`、实时会话期间，Codex进程的TCP连接只有`192.168.5.45:6152`。

## 安装位置

- `/usr/local/lib/codex/0.156.1/`：完整包原样解开。
- `/usr/local/lib/codex/current -> 0.156.1`。
- `/usr/local/bin/codex`：包装脚本。
- `/usr/local/bin/moto-voice-agent`：原型（`plasma/voice-agent/moto_voice_agent.py`）。

升级时解开新版本，再切换`current`链接。

## 第1步原型与实测

`moto-voice-agent`的工作流程：

1. 启动`codex app-server`，线程工作目录为家目录、沙箱为`read-only`、审批策略为`on-request`（原型阶段一律拒绝提权）。
2. 以WebSocket开启实时会话。
3. GStreamer从PulseAudio `android_microphone`取24 kHz单声道S16LE，每100 ms送一次。
4. 回复音频送往扬声器；播放期间及其后0.6 s暂停上传麦克风，作为最简单的防回声措施。

参数：`--audio-file`把录音按实时速度当作麦克风输入，用于自动测试；`--text`只追加文字。

实测（用`gpt-4o-mini-tts`合成的“帮我看一下磁盘还剩多少空间”作为输入）：

1. 转写得到“幫我看一下磁盤還剩多少空間”。
2. 约5 s后语音模型移交任务，Agent在bwrap只读沙箱中运行`df -h`。
3. Agent回答“还剩193 GB……”。
4. 语音模型播报“磁盘总容量大概222GB，用了30GB，还剩193GB……”。

从说完到开始播报约11 s。给线程加`developerInstructions`要求使用简体中文后，Agent与播报均为简体。（当时也传了`realtimeStartInstructions`，后来核实它只进入Agent上下文，见第2步。）

## 第2步：对话列表与按住说话（2026-09-24）

- **后台服务**：`moto-voice-agent --service`，systemd用户单元`moto-voice-agent.service`，D-Bus按需启动，服务名`dev.moto.VoiceAgent`。
  - 接口：`ListConversations`、`OpenConversation(id)`（空id为新对话）、`CloseConversation`、`DeleteConversation`（同时归档Codex线程）、`StartTalking`/`StopTalking`、`Interrupt`、`Approve(id, allow|allow-session|deny)`、`State`；信号`Event`（JSON）。
  - 每个对话就是一个Codex线程：工作目录为家目录，沙箱`workspace-write`，审批策略`on-request`。
  - 界面历史按对话存为`~/.local/share/moto-voice-agent/conversations/<id>.jsonl`，内容包括双方话语、Agent消息、命令及输出、文件改动、审批。说出第一句话后才进入列表，并以这句话作标题。
  - 打开对话即开启实时会话，空闲10分钟后关闭。
- **按住说话**：
  - 按下时停止正在播放的回答（打断），并开始采集；只在按住期间打开麦克风，自然避免外放回声。松开后补0.9 s静音，让服务端VAD判定一句话结束。
  - 采集数据拼成100 ms一块，由单一线程按顺序上传。起初每块各开一个线程上传，服务器收到的音频乱序，无法识别。
- **系统提示词**（`plasma/voice-agent/prompts/`）：
  - `realtime.md`作为语音模型指令，经`thread/realtime/start`的`prompt`传入。它会整体替换Codex默认指令，因此保留Codex默认内容（Apache-2.0，注明出处），后面追加本机环境、位置、能力和语言要求。
  - 源码核实：`realtimeStartInstructions`注入的是Agent上下文，不是语音模型指令。改用正确的`prompt`之前，语音模型仍回答“无法查看你的手机”；改后直接把请求交给Agent。
  - `agent.md`作为Agent的`developerInstructions`：手机硬件、Android宿主、LXC中的Ubuntu、Plasma Mobile、共享存储、投屏、代理、权限和回答方式。
- **技能**：`skills/moto-phone-desktop/SKILL.md`，安装到`/usr/local/share/moto-voice-agent/skills`，并链接到`~/.codex/skills/`。内容包括平台桥全部操作、电量/内存/存储、窗口与截图（新装`kde-spectacle`）、启动应用、通知（新装`libnotify-bin`）、AT-SPI操作（`moto-a11y`）和录屏。
  - 实测Agent在处理“手机还剩多少存储”时自己先读取了该技能，再执行`df`。
- **界面**：Kirigami应用`moto-voice-assistant`，桌面入口“语音助手”（`dev.moto.VoiceAssistant.desktop`）。
  - 列表页：新建、打开、删除对话。
  - 聊天页：你的话、助手的话（均含实时转写）、Agent消息（Markdown）、命令卡片（运行中/成功/失败，可展开输出）、文件改动卡片、审批卡片（允许/本次对话都允许/拒绝）、状态行，底部按住说话按钮。
- **实测**：
  - 直接注入音频：从说完到Agent执行`df`再到播报，事件全部到达界面。
  - 界面长按3 s后，服务收到开始与结束，约2.7 s音频。
  - 用手机扬声器外放合成语音再由手机麦克风录入的自测不成立：Android采集启用回声消除，会抵消本机播放的声音，识别结果成了乱码。真人说话已在第1步实测中识别准确。

## 回复从发起的一端播放（2026-09-24）

用户实测按住说话后听不到回复。原因不在语音：服务收到并播放了回复音频（一轮约5.3 s），但投屏连接时Android把所有媒体声音（包括容器经Termux PulseAudio的音轨）放在`AUDIO_DEVICE_OUT_PROXY`上送往电视。此外，手机扬声器的媒体音量当时为1/15。

用户要求：**从哪一端发起语音交互，回复就从哪一端播放。**

- **共享层**：新增始终在手机本机播放的PulseAudio输出`android_phone`（“手机本机”），任何应用都可以选用。默认sink仍是跟随Android路由的`android`。
  - 调研：Termux PulseAudio 17.0-4的`module-aaudio-sink`与`module-sles-sink`都不能指定输出设备（参数只有sink名、格式、延迟、性能模式等）；OpenSL ES也只能选流类型。因此没有改Termux模块。
  - 做法与麦克风对称：容器内`module-pipe-sink`（PulseAudio 17，LGPL-2.1+）→ `media-bridge`在sink未挂起时读FIFO → 私有`capture.sock`的`phone-output` → APK的AudioTrack（`USAGE_MEDIA`）。`setPreferredDevice`优先选有线/USB/蓝牙耳机，没有时用扬声器；设备增减时重新选择。
  - 延迟：pipe-sink由读取速度计时，按FIFO内未读数据上报延迟。FIFO缩到16 KiB，socket收发缓冲各16 KiB（各约85 ms）。sink空闲3 s挂起后停止读取，并丢弃FIFO残留。
  - 播放不要求Plasma在前台（与Termux输出一致），采集仍要求。
  - PulseAudio 17的`pactl -f json`遇到UTF-8描述（“手机本机”的monitor source）会报错。media-bridge改用`pactl list short`查麦克风source，否则主循环会一直走异常分支，麦克风也会停用。
- **语音助手**：`StartTalking(s screen)`由按钮传入所在屏幕名。KWin把投屏输出命名为`CAST-n`，此时回复用默认sink（跟随Android路由，在电视上）；否则用`android_phone`，该sink不存在时退回默认。
- **实测**（投屏连接中，用合成语音）：
  - 从手机屏`WL-0`发起：回复8.9 s，APK音轨（uid 10352）在`AudioOut_15`（SPEAKER）上。
  - 从电视屏`CAST-1`发起：回复6.25 s，Termux音轨在`AudioOut_D`（PROXY）上。
  - 两路并存互不影响；麦克风回归：`parec`取到3.8 s有效信号。
  - 以上以Android路由证据为准，尚待用户实听确认。
- **音量**：投屏时手机音量键和设置里的媒体音量调的是电视那一路（PROXY）。扬声器的媒体音量要在未投屏时调节。本机当时是1/15，需要调大才听得清。Android没有给普通应用按设备设置音量的公开接口。

## 等待时先回应并播报进度（2026-09-24）

用户要求：提出请求后不要让人干等；先回应要去做什么，处理中告知进度。

- **源码核实**（Codex rust-v0.156.1，`core/src/realtime_conversation.rs`的`handle_handoff_output`）：
  - 协议v2下，Agent执行中的消息（`HandoffUpdate`/`HandoffAppend`）只作为`[BACKEND]`用户消息加入对话，不发`response.create`，所以语音模型不会开口。只有任务完成（`CompletedHandoff`）时才触发回答。
  - `thread/realtime/appendSpeech`（`StandaloneSpeech`）会加入一条`[BACKEND]`消息并请求`response.create`。语音模型正在回答时，Codex会把请求排到当前回答结束后。
- **先回应**：`realtime.md`新增“Responsiveness”一节，作为用户的持续偏好覆盖默认提示词中“不要宣布计划”的要求。移交任务前先说一句很短的确认，再在同一回答中调用`background_agent`。
- **播报进度**：服务在Agent工作期间每秒检查一次，满足条件时通过`appendSpeech`发“进度（已用时N秒，任务仍在进行）……”，并要求语音模型用一句话说明当前在做什么、不要说成结果。
  - 工作不足8 s的任务不播进度。
  - 有新的过程说明（`agentMessage`且`phase`不是`final_answer`）、且距离上次出声至少6 s时，播报这条说明。说明超过8 s未播就视为过时并丢弃，避免播报已经完成的步骤。
  - 长时间没有新说明时，说“还在处理”和当前命令：先等20 s，此后间隔依次为30 s、45 s，最长60 s。
  - 按住说话期间不插话；回复音频和上一次进度请求都算作“出声”。
- **等用户审批时**：出现审批卡片立即播报，请用户在屏幕上点“允许”或“拒绝”。等待期间不再说“还在处理”。
- **实测**（合成语音，手机端发起）：
  - “找共享存储里最大的五个文件”：转写完成后0.3 s回应“好，我来帮你找一下。”；第8 s播报“正在扫描文件并按大小排序”；完成后播报结果。修正过时说明之前，还多播了一条已完成的步骤。
  - “截屏并告诉我屏幕上有什么”：先回应，第8 s播报进度，第19 s出现审批，2 s后播报“请在屏幕上的提示卡里点一下‘允许’或‘拒绝’”。
- **发现的问题**：Agent的`workspace-write`沙箱禁止连接Unix socket（D-Bus、Wayland、平台桥都返回EPERM），因此截图、AT-SPI、`moto-platform`等桌面操作每次都要审批提权。可以用“本次对话都允许”，根本解决办法是第3步把桌面工具放在沙箱外作为MCP提供。

## 待办

- **输入转写为繁体**：app-server不能设置转写语言，只影响显示；显示时做简繁转换。
- **真人说话实测**：用“语音助手”应用按住说话，验收识别、Agent执行、审批和打断。
- 快捷设置和悬浮控制条上的入口；识别文字的简繁转换；对话标题可改。
- 投屏时调节手机扬声器音量的入口。
- **第3步**：本机桌面操作工具（窗口、AT-SPI控件、截图、启动应用、平台桥）经MCP挂给Codex。
- **费用**：实时语音按API用量计费（`gpt-realtime`音频输入$32、输出$64/百万token；mini版$10/$20）。
