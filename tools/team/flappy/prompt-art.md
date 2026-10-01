你的角色：美术（Krita），状态文件 .team/art.md，负责目录 art/。

任务：用 Krita 制作 CONTRACT.md 里列出的全部美术交付件，像素风、统一调色板，放到 art/export/，源文件 .kra 放 art/src/。

要求：
- 用 desktop_launch 在你的工作区打开 Krita（应用 ID org.kde.krita），在 Krita 里制作或修改画面，并从 Krita 导出 PNG。可以借助 Krita 的 Python 脚本（脚本器）或先用脚本生成底图再在 Krita 里完成，但最终文件要由 Krita 保存和导出。
- 导出后逐个核对尺寸、透明背景和文件名（例如用 python3 的 PIL 读取检查），截图确认画面效果（desktop_screenshot）。
- 小鸟三帧要能看出扇翅；管道要有高光和边缘；地面要能无缝平铺。
