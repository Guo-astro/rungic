你的角色：音效（Ardour），状态文件 .team/audio.md，负责目录 audio/。

任务：用 Ardour 制作 CONTRACT.md 里列出的三个音效，导出到 audio/export/，Ardour 工程放 audio/src/。

要求：
- 用 desktop_launch 在你的工作区打开 Ardour（应用 ID ardour），新建工程放在 audio/src/，在 Ardour 里完成编辑（剪辑、包络、淡入淡出、音量），并从 Ardour 导出。素材可以先用脚本合成（例如 python3 生成 wav，或 ffmpeg 的 sine/anoisesrc 等滤镜），再导入 Ardour 加工。
- Ardour 的音频后端用不需要 JACK 的那种（如 PulseAudio 或 None/Dummy），能正常导出即可。
- 导出后用 ffprobe 核对格式、采样率和时长，并检查峰值（例如 ffmpeg 的 volumedetect）。截图确认（desktop_screenshot）。
- 三个音效要能区分：flap 短促、score 清脆上扬、hit 低沉有冲击感。
