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

从说完到开始播报约11 s。给线程加`developerInstructions`、给语音会话加`realtimeStartInstructions`要求使用简体中文后，Agent与播报均为简体。

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

## 待办

- **输入转写为繁体**：app-server不能设置转写语言，只影响显示；显示时做简繁转换。
- **真人说话实测**：原型已支持麦克风模式（不带参数运行）。外放时的回声、服务端VAD的打断行为需实测，必要时改用GStreamer `webrtcdsp`回声消除或按住说话模式。
- 快捷设置和悬浮控制条上的入口；识别文字的简繁转换；对话标题可改。
- **第3步**：本机桌面操作工具（窗口、AT-SPI控件、截图、启动应用、平台桥）经MCP挂给Codex。
- **费用**：实时语音按API用量计费（`gpt-realtime`音频输入$32、输出$64/百万token；mini版$10/$20）。
