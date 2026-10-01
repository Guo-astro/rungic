你的角色：游戏（Godot），状态文件 .team/godot.md，负责目录 game/。这是第二轮：集成。

美术和音效两位成员都已交付（见 .team/art.md、.team/audio.md，状态都是 done）。你的任务是把正式素材集成进游戏并验收：
1. 先读 .team/art.md 和 .team/audio.md，核对 art/export/ 的 6 个 PNG 和 audio/export/ 的 3 个 OGG 与 CONTRACT.md 一致（文件名、尺寸、格式）。不一致就在 .team/godot.md 写清楚问题，标 STATUS: blocked，然后结束，不要自己改别人的文件。
2. 把它们复制到 game/assets/art/ 和 game/assets/audio/，替换占位素材，让 Godot 重新导入（可用 godot --headless --import）。
3. 用 desktop_launch 在你的工作区打开 Godot 编辑器，运行游戏：至少扇翅几次、穿过一两组管道得分、撞一次管道看结束画面、再重新开始；每个阶段 desktop_screenshot 截图，截图保存到 game/verification/integrated-*.png。确认看到的是正式美术（小鸟三帧、管道高光、背景远景、平铺地面），听觉部分用日志或检查脚本确认三个音效在对应事件触发。
4. 再跑一遍你的玩法检查场景，确认 0 失败。
5. 运行完关闭 Godot。把 .team/godot.md 更新为集成结果（第一行 STATUS: done），列出截图和检查结果、发现的问题。最后用中文汇报。
