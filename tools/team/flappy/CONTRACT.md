# Flappy Bird 团队交付规格（组长：Claude，2026-10-01）

三位成员各在自己的工作区里并行工作，只改自己负责的目录；跨目录只通过下面的“交付件”交接。

| 成员 | 工作区 | 负责目录 | 应用 |
|---|---|---|---|
| 游戏（Godot） | 2 | `game/` | Godot 4.7.2：`~/.local/opt/godot/4.7.2-stable/` |
| 美术（Krita） | 3 | `art/` | Krita 6 |
| 音效（Ardour） | 4 | `audio/` | Ardour 9 |

## 美术交付件：`art/export/`（PNG，RGBA，透明背景，像素风，按 1 倍尺寸）

| 文件 | 尺寸（宽×高） | 内容 |
|---|---|---|
| `bird_0.png` `bird_1.png` `bird_2.png` | 34×24 | 小鸟三帧扇翅动画（翅膀上、中、下），朝右 |
| `pipe.png` | 52×320 | 管道（开口朝上，游戏里翻转得到上方管道） |
| `background.png` | 288×512 | 天空和远景，不透明 |
| `ground.png` | 336×112 | 可以水平平铺的地面，不透明 |

源文件（`.kra`）放 `art/src/`。

## 音效交付件：`audio/export/`（OGG Vorbis，48 kHz，单声道或立体声，峰值不超过 −1 dBFS，开头不留空白）

| 文件 | 时长 | 内容 |
|---|---|---|
| `flap.ogg` | ≤ 0.3 s | 扇翅膀（短促的“嗖”） |
| `score.ogg` | ≤ 0.5 s | 穿过一组管道得分（清脆上扬的“叮”） |
| `hit.ogg` | ≤ 0.6 s | 撞到管道或地面 |

Ardour 工程放 `audio/src/`。

## 游戏：`game/`（Godot 4 工程）

- 视口 288×512，`canvas_items` 拉伸，保持比例。
- 素材从 `res://assets/art/` 和 `res://assets/audio/` 按上面的文件名加载。集成前这两个目录可以放占位素材，集成时由游戏成员把 `art/export/`、`audio/export/` 复制进来。
- 玩法：点击或空格扇翅；重力；管道从右向左移动，开口位置随机；穿过一组管道加 1 分并播放 `score.ogg`；撞到管道或地面游戏结束，播放 `hit.ogg`，显示分数，点击重新开始；地面水平滚动；小鸟循环播放三帧动画并随速度倾斜。

## 状态与交接：`.team/`

每位成员维护 `.team/<角色>.md`（`godot.md`、`art.md`、`audio.md`）：
- 第一行是状态：`STATUS: working`、`STATUS: blocked <原因>` 或 `STATUS: done`；
- 下面写进度、做了什么、交付件清单、已知问题。
交付件全部就绪后才写 `STATUS: done`。
