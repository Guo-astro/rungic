# Agent 的工作要让用户看得见：对话里的图片、助理屏字幕、手机能力（2026-09-29）

用户要求：
- 让助理把 Blender 渲染的图片发到对话里，对话窗口要能显示。
- 助理要知道手机的全部能力（助理屏、投屏等）。操作桌面软件时，把助理屏以浮窗显示出来，实时告诉用户它在做什么，不要让用户干等。

## 调查（实机记录，对话 01a0ebad）

- **图片没显示的原因**：
  - Codex 的最终回答写的是 `![小火箭渲染图](</home/…/小火箭_Blender渲染.png>)`，另外有两个本机文件链接。
  - 实时语音朗读过的回合，对话只显示语音的那句总结，Codex 的正式回答（连同图片）只在展开的步骤里。
  - 文本控件（Markdown）按 App 自己的 qrc 基址解析裸路径，图片加载不出来。
- **用户干等的原因**：
  - 助理用 `blender -b` 后台渲染，助理屏没有打开。
  - 语音进度只拿到命令行和少量 Codex 旁白，多半说成“我还在处理这个步骤，稍微等一下”。

## 对话里的图片和文件

- **设计系统新增控件**（`com.rungic.design`，各状态已在状态总览里核对浅色和深色）：
  - `Thumbnail`：图片按原比例缩放到限定框内，圆角。状态：loading、ready、pressed、error。error 状态显示“图片打不开”加文件名，只有文件名会被省略。
  - `FileChip`：文件卡片。状态：normal、pressed、disabled。
  - `ImageViewer`：全窗口看大图，顶部有关闭和“用其他应用打开”。状态：loading、ready、error。
- **App**：
  - `media.js` 从回答里取出本机图片（`![..](路径)`，以及指向图片的普通链接），本机文件链接改为 `file://`。支持绝对路径、`<…>` 包裹的路径、`file://` 和 `~/`。
  - 回合下方总会显示这些图片和文件，语音朗读过的回合也显示。点图片打开 `ImageViewer`；浮层里点图片交给系统看图应用打开。
  - 正文和展开的步骤都去掉了图片标记，不再出现加载失败的空图。
- **提示词约定**：发图、发文件就是在最终回答里写 Markdown 绝对路径；新生成的图片存到 `~/Pictures`。
- **实机验证**：
  - 小火箭和甜甜圈的渲染图都显示在对话里，`.blend` 文件以卡片显示在图片下方。
  - 点图片打开大图，关闭按钮有效。

## 助理屏的实时字幕

- **共享通道**：`rungic_cua.activity`。
  - 写入 `$XDG_RUNTIME_DIR/rungic-agent-screen/activity.json`：`state`（working、done、question、failed、stopped）、`text`、`task`、`time`，以改名的方式原子替换。
  - 状态为 working 且超过 120 秒没有更新，就视为写入方已不在。
- **写入方**：
  - `desktop_goal`（Luna）：提示词要求每批动作附一句不超过 15 个字的中文说明；模型没写时，按动作类型生成（点击、输入“…”、按回车……）。结束时写入结果。
  - `desktop_act` 新增 `note` 参数；`desktop_launch` 写“打开某应用”。
- **浮窗**（`rungic-agent-screen-window`）：
  - 用 `QFileSystemWatcher` 监视这个目录。
  - working 状态下，画面底部显示字幕胶囊，前面的绿点呼吸闪动。结束时显示“完成 / 需要你回答 / 没做成 / 已停止”4 秒。
  - 收到边缘时，标签上的圆点呼吸闪动。
  - 字幕用显式状态实现：hidden、working、done、question、failed、stopped。
- **语音**：
  - 进度检查每秒读一次这个文件，把新的字幕作为“在助理屏上：…”交给实时语音转述。
  - 回合结束时，如果字幕仍是 working，就改为 done。
- **实机验证**：
  - 手动写入的字幕正常显示。
  - `rungic-cua goal`（打开下载文件夹）依次写出“打开Dolphin → 看一下屏幕 → 打开下载文件夹并按时间查看 → 切换详细视图查看文件时间 → 完成 · …”，前两条之后都是 Luna 自己写的中文说明。

## 操作桌面应用改为在助理屏上可见地做

- **`desktop_launch`**：
  - 默认开在助理屏上，助理屏没开时先打开；只有 `screen: "phone"` 才开在手机上。原来默认是“投屏时开到电视，否则开到手机”。
  - 新增 `args`：用 `kstart --desktopfile <id> -- <程序> 参数…` 启动，应用在自己的 scope 里运行，语音服务重启不会把它一起结束。
  - 实测：Blender 5.0.1 的图形界面能在助理屏上运行。
- **提示词**（`agent.md`）：
  - 新增“手机能力”清单：助理屏、投屏、录屏、截图、语音代发、通话代理、平台功能，以及对话里发图和文件。
  - 新增“让用户看得见”：桌面应用在助理屏上操作；需要脚本时，在可见的应用里运行（`Blender --python`），只有看不见也能做的事才用后台方式。
  - 较长的步骤前写一句中文旁白，这句旁白会被转述为语音进度。
- **提示词**（`realtime.md`）：能力清单同步更新，并说明“在助理屏上”开头的进度是什么。
- **提示词修正**：`agent.md` 里写的主目录 `/home/linux` 早已不对，改为 `~`。

## 动图（2026-10-01）

**问题（源码核对）**：`Thumbnail`、`ImageViewer`、对话里用户自己发的附件，以及输入栏和相册里的预览，用的都是 Qt 的 `Image`。`Image` 只显示 GIF 和动态 WebP 的第一帧。附件按扩展名把 `.gif` 归为图片，后端把它作为 `localImage` 交给 Codex。

**调研**：手机容器里是 Ubuntu 26.04 的 Qt 6.10.2。源码在 `.work/refs/qt-6.10.2/`，均为 qtdeclarative / qtbase 的 v6.10.2 标签。核对结论如下：

- **`AnimatedImage` 不能直接替换 `Image`**（`qquickanimatedimage.cpp`）：
  - 本地文件在界面线程里同步用 `QMovie` 打开，不管 `asynchronous`。一张大照片会卡住界面。
  - `sourceSize` 原样交给 `QMovie::setScaledSize`。`QImageReader` 对不支持缩放的格式（GIF）按 `IgnoreAspectRatio` 平滑缩放每一帧（`qimagereader.cpp`）。传一个限定框，画面会被拉伸。
  - 默认 `cache: true`，会把所有帧都留在内存里。
  - 改 `sourceSize` 会重新加载文件。
- **`Image` 能异步给出帧数**：异步读取线程里的 `readImage` 记下 `QImageReader::imageCount()`（`qquickpixmapcache.cpp`），通过 `Image.frameCount` 读到。TIFF 这类多页格式的帧数也会大于 1。
- **`Image` 的解码尺寸**：设了 `sourceSize` 时，按原图比例缩放（`qquickimageprovider.cpp` 的 `loadSize`）。在 Fit/Crop 模式下会盖满整个限定框，小图也会被放大。

**实现**：设计系统新增 `Picture`（`desktop/design/qml/Picture.qml`），`Thumbnail`、`ImageViewer` 和 App 里的三处预览都改用它。

- 先用 `Image` 异步加载，状态、隐式尺寸和 `sourceSize` 都取自它。
- 帧数大于 1，而且不是 TIFF/ICO/ICNS/CUR 时，`Loader` 再建一个 `AnimatedImage` 叠在上面。它的第一帧出来后，才隐藏静态图。
- `AnimatedImage` 的设置：
  - `cache: false`，内存里同一时间只有一帧。
  - 先按原尺寸读入。原图比静态图的解码尺寸大时，才把 `sourceSize` 设为那个尺寸，所以比例不变，也不会放大小图。
  - 自己不可见或所在窗口隐藏、最小化时暂停。
- 动画读不出来（比如格式插件不支持动画）时，静态图仍然保留。

**离线验证**（本机 PySide6 6.11.2，`tools/tests/test_design_picture.py`，5 项通过）：
- GIF 和动态 WebP 会播放，帧号在变化。
- 600×400 的 GIF 帧尺寸跟随静态图的 450×300；60×40 的小 GIF 不放大。
- 静态 PNG、单帧 GIF 和多页 TIFF 不建动画。
- 不显示时暂停，显示后继续。
- 状态总览的 `Thumbnail`、`ImageViewer` 两节渲染正常（`.work/verify/2026-10-01-moving-pictures/gallery/`）。软件后端不画 `MultiEffect`，所以示例图是空的，与改动前相同。

**手机验证**（G100 S，开发覆盖 `rungic-design 0.514+dev20261001t074243`）：
- 测试方式：以桌面用户身份、offscreen 平台运行 `qmltestrunner`，测试文件在 `.work/verify/2026-10-01-moving-pictures/device/`，不在用户屏幕上开窗口。
- Qt 6.10.2 上的结果：
  - GIF 会播放，帧号在变化；帧尺寸 450×300，跟随静态图；
  - 60×40 的小 GIF 不放大；
  - 静态 PNG 和单帧 GIF 不建动画；
  - 隐藏后暂停。
- **WebP 读不出来**：容器的 Qt 图片插件只有 gif、ico、jpeg、pdf、svg，没有装 `qt6-image-formats-plugins`。所以 WebP 图片无论动静，在所有 Qt 应用里都打不开。已给 `rungic-design` 加上这个依赖，重新部署后插件里有了 webp、tiff 等格式，手机上 7 项测试全部通过，动态 WebP 也能播放。

**未验证**：
- 在真实对话界面里看动图。
- 长 GIF 的 CPU 和内存占用。

## 让 Agent 看懂动图和视频（2026-10-01）

**问题（源码核对）**：Codex 0.159.2 的 `codex-rs/utils/image` 只接受静态图，源码见 `.work/refs/codex-0.159.2/image-lib.rs`。

- **GIF**：用 `DynamicImage::from_decoder` 解码，只得到第一帧，再转成 PNG。注释里写明 API 只支持非动画 GIF。
- **WebP**：不需要缩放时按原字节透传，动态 WebP 也原样发出。
- **视频**：我们的后端原来只在文本里附一行路径，模型看不到画面。

**实现**（`agent/assistant/media_frames.py`，在 `send_text` 里调用）：

- **抽帧规则**：
  - 视频按扩展名识别：用 ffprobe 读时长、尺寸、旋转和有无声音，再用 ffmpeg 在每个时间点快速定位后取一帧。
  - 动图（GIF、WebP、APNG）用 Pillow 读帧数和每帧时长；单帧的仍按原图发送。
  - 取帧数量：约每 2 秒一帧，至少 2 帧、最多 8 帧，不超过实际帧数，取各段的中点。
  - 帧图片的长边不超过 1024，不放大，存为 JPEG。
- **发给 Codex 的内容**：这些帧作为 `localImage` 发送。文本里每个文件写一行，例如 `/…/clip.mp4 (video, 5 s, 1280x720, with sound): 3 frames from it are attached as images, at 0.83 s, 2.5 s, 4.17 s`。帧文件名形如 `<文件名>@<时间>s.jpg`，Codex 标注图片时会带上这个路径。
- **缓存**：放在 `~/.cache/rungic-voice-agent/frames/<路径、大小和修改时间的哈希>/`。文件变了就重新抽帧，一周没用到的自动删除。
- **出错时**：缺少 ffmpeg 或文件读不出来，就按原来的做法只附路径。
- **先显示消息**：用户消息先显示在对话里，再抽帧，界面不用等。
- **依赖**：deb 显式依赖 `ffmpeg` 和 `python3-pil`。Pillow 原本经 rungic-cua 间接安装；容器里是否已有 ffmpeg 命令行待上机核对。

**离线验证**（本机 Ubuntu FFmpeg 8.0.1、Pillow 12.1.1，`tools/tests/test_media_frames.py`）：

- 10 项通过，覆盖以下情况：
  - GIF、动态 WebP、APNG 都能抽出帧；单帧图片不抽帧；
  - 帧的数量、时间和尺寸符合规则；
  - 带声音的 1280×720 视频抽出 3 帧；
  - 带旋转标记的竖屏视频，尺寸按竖屏报告；
  - 缓存会复用，文件变化后重新抽帧，旧缓存会被清理；
  - 没有 ffmpeg 或文件损坏时不抽帧。
- 测试发现 `scale` 会把小视频放大，已改为限定框取原尺寸与 1024 中较小的值。
- 本机全部离线测试共 145 项通过。

**手机验证**（开发覆盖 `rungic-voice-agent 0.514+dev20261001t074243`）：
- 部署时 apt 按新依赖装上了 Ubuntu 的 `ffmpeg 8.0.1`。
- 以桌面用户身份直接调用已安装的 `media_frames`：
  - 20 秒 1080p、带声音的 H.264 视频抽 8 帧用时 4.0 秒，再次调用命中缓存；
  - GIF 用时 0.18 秒；
  - 静态 PNG 不抽帧。

**未验证**：在对话里实际发送视频，以及 Codex 对这些帧的回答。

## 视频在对话里显示（待做）

现在视频附件和回答里的视频都只显示为文件卡片。做法需要上机核对后再定：

- 容器里有没有装 Qt Multimedia 的 QML 模块；
- 默认的视频应用是什么；
- 封面图用 KIO 的共享缩略图（ffmpegthumbs），还是用 `MediaPlayer` 暂停在第一帧。核对结论：6.10.2 的 FFmpeg 后端停止状态下不建解码对象，暂停后才出第一帧，所以每个封面要常驻一套解码器。

## 已知限制与遗留

- **恢复的对话仍用创建时的提示词**：
  - Codex 的 `thread/resume` 虽然传入了新的 `developerInstructions`，这条对话的 rollout 里仍然找不到新内容，所以只有新对话才会用到新提示词。
  - 在旧对话（13:40 创建）里再做甜甜圈，Agent 仍用了 `blender -b`，因此这次不能算作可见 Blender 流程的验收。
- **语音进度的质量**：
  - 旁白少时，只剩“还在处理中，抱歉久等”这类空话。
  - 有一次语音把 Codex 的计划说成了“已经开始渲染了”，其实还没开始。
  - 汇报的频率、详细程度和后台工作的界面表现，另行设计。
- **列表跳动**：一次点图片时，列表跳到了较早的内容，没有复现。可能是缩略图加载完成后高度变化引起的。
- **其他修复**：
  - 服务重启后遗留的“正在处理”回合，在下一回合开始时标为“已停止”，不再一直计时。
- **尚未发布**：以上改动尚未打包发布，手机上是临时安装的版本。
