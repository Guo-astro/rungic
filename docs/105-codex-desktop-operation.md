# 默认由 Codex 操作桌面，保留 API 执行器

2026-10-03。用户指定：开发手机部署当前改动，computer use 默认使用 Codex，API 方式保留。

## 当前功能与验收范围

| 功能 | 当前行为 | 本轮验收 |
|---|---|---|
| 默认桌面操作 | 当前 Codex 登录与所选模型逐步看图和执行动作，计划、进展和结果在来源对话显示 | 开发 G100 常驻 Agent 启动 Kalk、点击 137 × 29、再次截图确认 3,973 通过 |
| API 备选 | 显式 Luna API 执行器，保留旧 API 及 AT-SPI/OCR 选择 | Luna 只读识别同一计算器结果、恢复 Codex 通过；未验证 API 模式的完整多步任务 |
| Agent App 设置 | 桌面操作方式、Codex 登录、OpenAI API key 分开；任务或通话进行中拒绝切换 | 新页面四状态离线渲染、服务接口切换和忙时拒绝通过；未验完整页面触控流程 |
| 语音消息 | Codex 决定录音和发送动作，本地辅助程序管理路由和一次播放，TTS 使用 API key | ARM64 假音频进程的生命周期测试通过；未向真实联系人发语音 |
| 电话界面 | 默认 Codex 执行拨号/挂断和画面判断，通话音频与调度保留 API | 实现已部署，辅助线程模型/租约离线测试通过；未拨真实电话 |

本轮为开发覆盖 `20260930.19+dev20261003t061714`，不是正式发布或所有机型的验收。G100 S 日常机未更新。下文保存实现、部署和逐次失败/修正证据。

## 执行与认证是两个选择

- 默认 `codex`：Agent 当前的 Codex 线程使用所选模型，看 `desktop_screenshot`、调用 `desktop_act`，逐步判断和核验。MCP 只提供本地截图、输入、窗口与音频能力，不为桌面判断另发 Responses 请求。模型、登录、进展和实际观察到的 Codex token 用量沿用 Agent。
- 显式 `luna`（CLI 别名 `api`）：保留现有 `desktop_goal` 和语音消息执行器，独立通过 OpenAI API key 调用 Luna。原来明确保存的 `luna`、`atspi` 选择不被覆盖；没有配置或配置无效时默认 Codex。
- Codex 可以登录 ChatGPT，也可以使用 API key。选择 Codex 执行不等于切换为 ChatGPT 计费；登录页负责登录，桌面操作页负责执行方式。语音、转文字和 TTS 继续使用 API key。

这复用的是 Linux 的截图、RemoteDesktop portal、KWin 和 Codex MCP 接口，不依赖 Codex macOS/Windows 桌面插件。原始 API 方案、截图范围和上游调查见 [68](68-luna-computer-use.md)；登录与计费入口见 [101](101-codex-sign-in-and-api-key.md)。

## 实现

`rungic_cua/mode.py` 管理持久化选择；`screen.py` 共享截图和输入执行，`luna.py` 保留 API 决策循环。Codex 模式隐藏且拒绝 `desktop_goal`、旧语音执行器和 AT-SPI/OCR 的 API 工具，避免任务无提示地回退为独立 API 决策。

Agent App 设置新增“桌面操作”，显示 Codex（默认）和 Luna/OpenAI API，并说明登录与费用归属。`SetDesktopMode` 在任务、后台线程或通话仍在进行时拒绝切换；空闲时保存并替换 app-server，使 MCP 工具列表更新，不切换认证。OpenAI API key 单独成组，不再藏在语音设置里。

普通桌面任务留在原来的 Codex 对话。代打电话的拨号/挂断属于服务生命周期，由现有认证 app-server 创建短期 Codex 线程，继承模型并绑定应用桌面；只启用桌面 MCP。复用 native `rungic-task-tools` 的进程组和租约，停止时先撤销租约再 interrupt，完成后 unsubscribe；进展送回通话来源对话。连接判定仍看实际画面，接受拨号请求不代表接通。

Codex 模式的语音消息用 `desktop_voice_recording` 管理音频，Codex 自己点击录音和发送。C++ `rungic-voice-recording` 等真实 Linux 麦克风路由后才播放，播放只尝试一次；失败、EOF 或超时释放路由。TTS 使用 API key。它不点击界面，不替用户发送。按住说话类流程尚未验收。

## 离线与构建核验

- Python：配置默认值、API 选择保留、模式工具边界、忙时切换拒绝、电话辅助线程认证/模型复用及租约清理；并回归模型、app-server、phone session、后台简报、工作空间和登录。
- ARM64 native helper：无录音时拒绝播放、一次播放及 EOF 清理、失败后不重复播放。用假音频进程，不访问硬件或发消息。
- 设置页离线渲染 Codex、API、无 key、忙时错误；截图在 `.work/verify/20261003-codex-desktop/ui/`。
- ARM64 包在 Mac mini 的 `rungic-build` 构建，不向手机安装编译依赖。

## 开发部署与实机

验收记录继续写在本节。设备为 G100 / portov_cn / ZY32M9MRVP，Android 16、Ubuntu ARM64；G100 S 日常机未部署。基线发布 20260930.19；使用 `rungic_dev.py` 开发覆盖，不生成正式发布或提交 rootfs 快照。

首轮构建成功，安装前的直传检查失败：开发 G100 没有 buildhost SSH 密钥。已在手机生成密钥，Mac mini 只授权其公钥，限定来源地址和 `rungic-transfer` 强制命令。两条直连路径（10.77.0.20、192.168.5.45）读取同一构建机文件得到相同 SHA-256；私钥留在手机，产物从 Mac mini 直接到手机。

证据目录 `.work/verify/20261003-codex-desktop/`；失败部署记录 `.work/dev-deploy/20261003-135335-deploy/`，后续部署记录 `.work/dev-deploy/20261003-140208-deploy/`。


首轮六包覆盖 `20260930.19+dev20261003t060208` 安装和重启通过，apt Installed = Candidate。完整性摘要与部署前一致：changed_files=0、release_mismatch=0，已有 308 个缺失语言文件和 unowned_usr=5 / unowned_etc=11；未新增漂移。SSH socket 继续启用。

首个常驻 Agent 验收正确调用了启动和截图工具，任务计划/进展回到原对话，但截图连续返回 Cancelled；Agent 停止而未假称完成。调查 KWin 6.6.6 实际源码和 supportInformation：截图需要 EGL 后端，手机工作区实际为 QPainter。此次安装的新工作区脚本默认 virtual，而设备仍是旧 `kwin +rungic8`，缺少已有 `virtual-render-device.patch`。这不是 Codex 登录或模型问题。补齐当前 KWin 补丁队列的五个配套包，再验收；不改应用或添加另一条截图通道。原方案调查与此前验收见 [research/97 §10](research/97-headless-agent-work.md#10-方案-c-第一步无头工作区实机实验2026-10-02-13551410)。


补齐 KWin 开发覆盖 `4:6.6.6-0ubuntu0.1+rungic9+dev20261003t060922.b8d3251`，整体覆盖变为 `20260930.19+dev20261003t060922`。增量构建 29 秒，直接同步五个二进制包。主手机会话已经重启，独立工作区按当前设计不会跟它一起退出，所以另重启验收工作区 1 以加载新 KWin，截图随即恢复。

部署工具的 session-ready 步骤出现已知误报：它比较 `pidof kwin_wayland` 的全部 PID，其中独立工作区的旧 PID 持续存在，被判成“旧桌面尚未退出”。主手机 KWin/plasmashell 都是 active；同一问题已记在 [research/97 §20.1](research/97-headless-agent-work.md)。本轮记录该限制，不把工具最终 result=ok 当作完整 UI 验收。


Codex 的常驻 Agent 验收已通过：新对话 `01a10066-ad2e-73c3-b380-36ce35558741` 由当前模型 gpt-6-luna 通过桌面 MCP 启动 Kalk、读取截图、点按 137 × 29，并重复截图确认显示 3,973。原对话显示计划、逐步进展、结果和 token 事件增长；这是本机观察值，不是账单。截图 `.work/verify/20261003-codex-desktop/kalk-final.png` 已人工核对。进行中调用 SetDesktopMode 返回忙时错误，未改变模式。第二轮失败是工具实际路由到尚未加载新 KWin 的工作区 0；确认该区没有应用窗口后重启它，0/1 都报告 OpenGL ES + FD710，随后同一测试通过。保留两个失败日志，避免把一次 CLI 截图成功当作完整路由验收。

API 备选的首次实机只读验收发现本轮重构遗漏：模型工具常量 TOOLS 被移到共享 screen 模块，luna 循环没有引用。已把 API 工具定义放回 luna 模块，增加真实 ComputerUse 类的隔离请求/截图续接测试，并重新通过 106 项 Python 回归。随后仅重建和部署 rungic-cua。所有 API 实机验证结束都恢复 Codex，未改变现有登录或 key。


最终 API 备选验收通过：`SetDesktopMode api` 返回 luna，独立 Responses 循环 3.2 秒只读识别同一 Kalk 显示 3,973，并指出当前没有显示算式；与截图一致。`SetDesktopMode codex` 恢复成功，Setup 保持 account.type=apiKey。最终开发覆盖 `20260930.19+dev20261003t061714`，cua 版本 `0.358+dev20261003t061714.b8d3251.dirty`，其他覆盖沿用上述记录。最终 apt 核对通过，完整性摘要仍与部署前相同。证据 `api-mode-final.log`、`dev-final.json`、`final-state.log`；安装的 voice-agent、server、mode、luna、screen 与工作区 SHA 一致。

本轮实机范围是默认配置、常驻 Codex 看图/输入/结果验证、来源对话进展和用量事件、忙时切换拒绝、API 只读循环和恢复 Codex。设计系统 ChoiceRow/ListRow/RadioMark 在手机离屏出图通过；完整新设置页为本机四状态渲染。没有向真实联系人发语音或拨号，没有验证完整电话或按住录音；原生音频生命周期的假进程测试不能代替这些验收。G100 S 日常机未改，rootfs 快照未提交。代码在 `feat/codex-desktop-default` 分支，工作区改动未提交，部署可经开发覆盖 reset 撤销。


## 同步最新 main 后的继续开发（2026-10-03）

本机 mibook / x86_64 经 SwiftWire SOCKS5h 拉取 `origin/main`，将 `feat/codex-desktop-default` 快进到 `331bbdea`。同步前的 33 个改动文件保存在 `.work/verify/20261003-codex-desktop-continue/before-pull.tar.gz`，Git stash 也保留。恢复后合并文档索引、CUA 包依赖和工作区测试三处冲突；保留上游补充的 python3-pypinyin 依赖、独立桌面行为和测试。

本轮继续完成：

- 接入 main 新增的质量治理：声明 mode、screen、设置页、录音辅助程序和测试的功能归属，分类本文，更新默认 Codex / 显式 API 的体验，重新生成功能总览。严格检查无新增结构性警告，原有 44 条 device-only 欠账不变。
- 上游电脑操作测试改为显式选择 API 备选，截图检查使用共享 screen 模块；配置文件在 mode 模块内替换为测试私有文件，避免改写用户选择。拨号测试使用新的决策执行入口。
- 增加设置页真实 QML 点击检查：没有独立 API key 时不能选择 Luna，等待切换结果时不能连点，忙时拒绝保持原选择并显示错误，成功才更新选择。
- 修复电话模式空闲或启动中允许切换执行方式的问题。`restart_server` 会调用 BackendReset，故没有运行任务也会打断电话模式；现在 sessionId 存在或 phone_starting 时拒绝切换，保留原模式和连接。新回归检查覆盖这两种状态。
- CLI 的无效模式仍以清楚的错误退出，不输出 Python traceback。

验证证据在 `.work/verify/20261003-codex-desktop-continue/`：

- `targeted-final.log`：桌面执行方式、API 循环、共享截图、拨号入口和 Agent App 的 57 项测试、7 项子测试通过。
- `ui-interaction.log`：设置页交互和历史滚动两项单独检查通过。历史滚动测试此前没有计入 ListView 的 originY，估计高度使 originY=-2 时误判未到末尾；修正测试的内容坐标计算，未改动聊天页实现。
- `offline-final.log`：完整 runner 的 Python 部分为 864 passed、15 failed、6 skipped、506 subtests passed；补丁队列、Java 和 shell 检查通过。pytest 输出汇总后，在本机 Python 3.15 / GI / Qt 混合进程的退出阶段发生段错误，原因尚未定位，整套检查不算通过。Qt6Core 开发文件本机未安装，原生录音 helper 的三项测试本轮未重跑；其源码未变，不能将旧 ARM64 假进程测试称为本轮实机验收。
- `baseline.log`、`baseline-import-order.log`：在干净 `331bbdea` 工作树逐项对照，全部 15 个失败复现。其中缺少 dpkg-parsechangelog / apt-get、Debian 依赖检查、libx264；另有 director 替身请求、linux-vdso 符号化、输入探针，以及完整模块导入顺序下 ThreadPoolExecutor 为 lazy_import 的六个失败。本轮未扩大范围修复这些上游或宿主环境问题。

本轮只同步、整合和离线检查。没有重新部署手机、拨打电话或发送语音，没有更换账户和 API key。新的电话模式切换保护仍需后续开发部署验收；此前 G100 的计算器和 API 只读验收仍为上一节记录的版本。
