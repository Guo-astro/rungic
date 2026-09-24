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

## 待做

- 微信通话实测：通话中把微信的输入、输出切到这两个设备（可在微信的音频设置里选，也可在Plasma音量小程序里按应用切换），确认对方能听到送入的语音、Linux一侧能录到对方的声音。
- 通话代理：第二个实时语音会话接这两个设备，你的指令由现有语音助手转给它；界面上有接管、挂断按钮（方案见对话记录，待用户确认后另立章节）。
