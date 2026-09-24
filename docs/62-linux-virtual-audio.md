# Linux 扬声器与 Linux 麦克风（系统级虚拟音频设备）

目标：让程序能代替人参与音频通信。例如由语音助手代接微信电话：它听对方说话，替你开口；手机的真麦克风只留给你给助手下指令。按用户要求，设备做成系统级、名称中性，任何通信软件（微信、浏览器里的会议、Telegram等）都可以选用，不针对某一个应用。

## 设备

由`shared/media/media-bridge.py`（`moto-plasma-media`用户服务）在Android输出（隧道sink `android`）出现后创建，与“手机本机”输出、Android麦克风由同一处管理：

| 名称 | PulseAudio | 作用 |
|---|---|---|
| Linux 扬声器 | sink `linux_speaker`（`module-null-sink`，48 kHz立体声） | 应用把声音输出到这里；需要“听”的程序录`linux_speaker.monitor` |
| Linux 麦克风 | source `linux_microphone`（`module-remap-source`，48 kHz单声道） | 应用把它选作麦克风 |
| Linux 麦克风输入 | sink `linux_microphone_input`（`module-null-sink`，单声道） | 需要“说”的程序往这里播放，声音从 Linux 麦克风出来 |

- **不会成为默认设备**：创建后如果默认输出或默认输入落到这些设备上，立即交还`android`和`android_microphone`。Android输出是异步出现的，在它出现之前不创建，避免默认值还没定下来就被占用。
- **与原有设备隔离**：创建失败只记一条警告，不影响Android麦克风和“手机本机”输出。首版出现过：创建失败被当成“音频服务不可用”，连带停掉了手机输出。
- **描述写法**：描述里有空格时，整个属性列表要加引号（`sink_properties='device.description="Linux 扬声器"'`），否则`Module initialization failed`。
- 两端都是虚拟设备，没有声学路径，因此没有回声问题。空闲时由`module-suspend-on-idle`挂起。

## 实测（2026-09-25）

- 创建后默认设备仍是`android` / `android_microphone`。
- 往`linux_microphone_input`送1 kHz正弦波（24 kHz单声道，幅度10000），从`linux_microphone`录回：每100 ms有效值7069（理论值7071），即无损、增益为1。
- 往`linux_speaker`播放语音，从其monitor录回，峰值与送入“Linux 麦克风输入”那一路相同。
- 用默认缓冲录音时，结束录音进程会丢掉尾部数据。测量应使用`--latency-msec=20`。

## 微信通话实测（2026-09-25）

- 微信4.1的通话音频来自内置的Chromium WebRTC模块，在PulseAudio中表现为：
  - 播放流`application.name="Chromium"`（float32，单声道，44.1 kHz）；
  - 录音流`"Chromium input"`（s16le，单声道，16 kHz）；
  - 两者的`application.process.binary="wechat"`。
- 用户打通一通语音电话后：
  - 用`pactl move-sink-input`和`move-source-output`把这两路切到 Linux 扬声器和 Linux 麦克风；
  - 向“Linux 麦克风输入”播放一句合成语音“……如果你听到了，请随便说一句话”，同时录`linux_speaker.monitor`；
  - 约8秒后切回`android`和`android_microphone`。
- 结果：
  - 录音中在测试语音播完后出现约0.6 s对方的声音，转写为“我听到了。”，即双向都通。
  - 录音含第三方声音，验证后已删除。
- 注意：
  - 用`pactl move`切换会被`module-stream-restore`按应用名记住，名称是通用的“Chromium”，会波及其他Chromium和Electron应用。本次已切回原设备。
  - 正式功能应按`application.process.binary`匹配流，并使用不保存的移动（由客户端库发起、不写入stream-restore），挂断后恢复原设备。

## 应用音频临时路由：`moto-audio-route`

`shared/media/audio-route.py`，安装为`/usr/local/bin/moto-audio-route`（与`moto-media-bridge`一样手动安装）。

- 用法：`moto-audio-route --binary wechat --microphone [--speaker]`。
- 行为：运行期间，把该程序（按`application.process.binary`匹配）的录音流移到 Linux 麦克风，加`--speaker`时播放流移到 Linux 扬声器。靠`pactl subscribe`，程序之后新建的流也会跟上。收到SIGTERM/SIGINT，或调用方关闭标准输入管道时，把每条流移回原设备。
- 输出：启动后打印`ready`，每次移动打印`routed …`或`restored …`。
- stream-restore会按应用名记住移动。结束时移回原设备，应用在之后的默认设备与原来相同。

## 语音代发（2026-09-25）

微信4.1发语音：点`Send Voice`立即开始录音，出现`Cancel`、`Play Recording`、`Send voice message`，最长60秒。初次探查时，录音用手机真麦克风录满了60秒，已取消，没有发出。

moto-cua新增MCP工具`desktop_voice_message`（`plasma/cua/moto_cua/server.py`，CLI：`moto-cua voice '<json>'`）。步骤：

1. 用OpenAI TTS（`gpt-4o-mini-tts`，`speech.py`，使用语音助手的密钥，走代理）生成24 kHz PCM，前后各留0.3 s静音。
2. 读取活动窗口，由其pid取得进程名，启动`moto-audio-route --microphone`。
3. 点开始控件；`hold`模式下是按住开始控件，适用于按住说话的应用。
4. 等路由报告该应用的录音流已移到 Linux 麦克风，才向“Linux 麦克风输入”播放语音；4秒内没有移过来，就不播放，点取消并报错，保证真麦克风录到的内容不会被发出。
5. 点发送控件（或松开），关闭路由，恢复原设备。

控件名由调用方给出（微信：`Send Voice`、`Send voice message`、`Cancel`），不绑定某个应用。

实测：在“文件传输助手”发送“这是语音助手代发的测试语音……”，得到一条8秒的语音消息，总耗时14 s。结束后微信没有残留的录音流，默认输入仍为`android_microphone`。语音内容需要用户在手机上收听确认。

## 待做

## 待做

- 通话代理：第二个实时语音会话接这两个设备，你的指令由现有语音助手转给它；界面上有接管、挂断按钮（方案见对话记录，待用户确认后另立章节）。
