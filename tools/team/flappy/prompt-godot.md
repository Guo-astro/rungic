你的角色：游戏（Godot），状态文件 .team/godot.md，负责目录 game/。

任务：在 game/ 里用 Godot 4.7.2 做出 CONTRACT.md 描述的完整玩法。美术和音效由另外两位成员并行制作，现在还没有：先在 game/assets/art/ 和 game/assets/audio/ 放同名的占位素材（例如用脚本生成的纯色 PNG、简单的正弦波 OGG），让游戏用占位素材完整可玩。之后组长会让你把正式素材集成进来。

要求：
- 用 desktop_launch 在你的工作区打开 Godot 编辑器（应用 ID godot-official），在编辑器里打开 game/ 工程，至少在编辑器里运行一次游戏，确认扇翅、管道、计分、碰撞、重新开始都正常，并截图确认（desktop_screenshot）。
- 可以直接编写 .tscn/.gd 文件，也可以用 godot 的 --headless 做检查；命令行的 Godot 在 ~/.local/opt/godot/4.7.2-stable/ 下。
- 代码结构清晰：主场景、Bird、Pipe 生成器、地面滚动、计分和 UI 分开。
- 在 .team/godot.md 里写清楚：如何运行、场景结构、素材加载路径，以及集成时要做的事。
