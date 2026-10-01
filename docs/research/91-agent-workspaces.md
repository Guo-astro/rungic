# 工作空间：Agent 各自独立的 GUI 空间（方案，2026-09-29）

状态：方案 A 的原型已实现，并在实机上跑通一个 Agent 的完整流程（见文末“原型实施与实测”）；尚未打包发布。所有“已核验”的内容都来自本机源码或实机，未验证的推断会单独标明。

用户决定（2026-09-29）：每个空间一条独立的 D-Bus 总线；放弃过渡用的 KWin 放置补丁；直接做原型验证。

## 需求（用户，2026-09-29）

1. **与用户空间隔离**：Agent 在自己的空间里工作，不在用户手机上打开软件，不抢指针、键盘焦点和当前活动屏。
2. **任何一个工作空间都能单独投屏**，包括浮窗、全屏和电视。
3. **支持多个 Agent**：将来可能有多个 Agent，每个都有自己独立的 GUI 工作空间。
4. **无缝**：工作用的应用直接出现在它的工作空间里，不能先在手机上出现再挪过去。

## 现状（已核验）

- **单一 KWin**（6.6.6+rungic8），两块输出：
  - `WL-0`：手机；
  - `CAST-1`：宿主的第二输出，即助理屏或电视（docs/65）。
- **KWin 里没有能隔离输入的“工作区”**：
  - 只有一个座席：`wayland_server.cpp` 只创建一个 `SeatInterface`，即一个指针、一个键盘焦点、一个活动窗口。
  - 虚拟桌面和活动都是全局的，没有按屏分开的虚拟桌面。
  - 当前活动屏会随指针移动（`pointer_input.cpp`）、触摸（`touch_input.cpp`）和窗口激活（`activation.cpp`）改变。
  - 所以助理在 CAST-1 上点击、激活窗口时，会把活动屏和键盘焦点拉过去。实例：语音助手 App 被开到助理屏；Blender 的渲染窗口被开到手机。
- **新窗口的输出**：Wayland 新窗口在创建时取当前活动屏（`XdgToplevelWindow` 构造函数）。窗口规则的“屏幕”在 Wayland 窗口初始化时不生效。现在的 `desktop_launch` 是窗口出现后再挪，而且只挪第一个窗口。
- **宿主**（`native/plasma`，smithay）：
  - 给 KWin 额外提供一个 wl_output `cast-0`；KWin 在它上面建一个全屏 toplevel，这个窗口的缓冲零拷贝交给电视或全屏呈现端（`cast.rs`）。
  - 目前只支持一个：`cast: Option<CastOutput>`。
- **浮窗**：Linux 侧的 Qt 程序，用 KWin 的 `zkde_screencast` 录制 CAST-1，经 PipeWire 显示（docs/65）。
- **KWin 能以独立实例运行**：支持 `--socket`、`--no-lockscreen`、`--no-global-shortcuts`、`--no-kactivities`、`--exit-with-session`、`--xwayland`、`--virtual`、`--wayland-display`（嵌套窗口模式，`--width`、`--height`、`--output-count`），以及我们的 `--android-host`。
- **资源**：主 KWin 常驻内存约 87 MB，plasmashell 约 89 MB。

## 业界做法（按公开资料和常识，本轮未逐项查源码）

- OpenAI Operator、Anthropic computer-use 演示、E2B Desktop 这类沙箱：每个 Agent 一个独立的显示服务器（Xvfb 或 Xvnc 加一个窗口管理器），画面再串流出来。隔离靠“各自一台显示服务器”，不靠在同一个合成器里分区。
- Wayland 上的对应做法是嵌套或无头合成器：weston 或 cage 的 wayland 后端、gamescope、`kwin_wayland --virtual`。KDE 自己用嵌套 KWin 做开发和测试。
- 结论：要做到真正的输入隔离，业界一致是**每个空间一个合成器**。单一合成器多座席（MPX 式多指针）在 KWin 中没有支持，改动面极大。

## 方案比较

| | A：每个工作空间一个 KWin，直连宿主 | B：每个工作空间一个嵌套或虚拟 KWin，画面走 PipeWire | C：单一 KWin，多座席 |
|---|---|---|---|
| 隔离 | 完全隔离：各自的座席、焦点、剪贴板、Xwayland | 完全隔离，同 A | KWin 大量代码假定只有一个座席，需要大改 |
| 投电视 | 宿主把电视呈现端直接接到这个空间的输出，零拷贝 | 用户空间的 CAST-1 上跑一个播放器全屏显示 PipeWire 画面，多一次复制和合成 | 同现在 |
| 浮窗 | 宿主层浮窗零拷贝；或第一阶段仍用 Linux 浮窗录 PipeWire | Linux 浮窗录 PipeWire，与现在相同 | 同现在 |
| 多个 Agent | 宿主输出按工作空间编号，数量不受限 | 可以 | 难 |
| 宿主改动 | 中：单个投屏输出改成多个显示源，按连接区分空间 | 无 | 无 |
| 能耗和延迟 | 最好，与现在的助理屏相同 | 电视路径多一次 GPU 合成 | — |

**推荐 A**：它是现有“宿主第二输出”机制的推广。现在的助理屏就是 A 的特例，只是和用户共用一个 KWin。

## 推荐架构（A）

```
                      ┌──────── Android 宿主（smithay） ─────────┐
用户空间  KWin#0 ──── │ 显示源 user:phone (WL-0)  ─→ 手机主画面   │
          (现有)      │ 显示源 user:desk  (现 CAST)─┐             │
Agent 1  KWin#1 ──── │ 显示源 agent-1               ├→ 呈现端：   │
Agent 2  KWin#2 ──── │ 显示源 agent-2               │  电视 / 全屏 │
                      │                              │  / 浮窗     │
                      └──────────────────────────────┴────────────┘
```

- **工作空间 = 一个独立的最小会话**，用 systemd 用户模板单元 `rungic-workspace@<名字>` 启动：
  - `kwin_wayland --android-host --socket wayland-ws-<名字> --xwayland --no-lockscreen --no-global-shortcuts --no-kactivities`，一块输出，默认 1920×1080。
  - 需要时再加入门户（文件对话框在空间内打开）和通知转发，见“待定”。
  - 进入这个空间的环境变量：`WAYLAND_DISPLAY`、`DISPLAY`（空间自己的 Xwayland）、`RUNGIC_WORKSPACE=<名字>`。视 D-Bus 方案决定是否再带 `DBUS_SESSION_BUS_ADDRESS`。
  - 在这个环境里启动的一切（Codex 的命令、`desktop_launch`、Blender 及其子进程）天然只连这个空间的 KWin：窗口只可能出现在这里，第一帧就在，无需“挪”。
- **宿主：从“一个投屏输出”推广为“多个显示源 × 多个呈现端”**：
  - **显示源**：每个工作空间 KWin 的输出。宿主按连接区分空间，例如每个空间一个宿主 socket，或连接时带上空间编号。每个空间只看得到自己的 wl_output。
  - **呈现端**：手机主画面（固定给用户空间）、手机全屏（APK 现有 `AgentFullscreen`）、电视（现有 CastDesktop）、浮窗。
  - 平台桥新增请求，例如 `{"op":"workspace","name":"agent-1","present":"tv|fullscreen|float|none"}` 和 `{"op":"workspaces"}`（列表）。任何一个空间都能单独接到任何一个呈现端。用户说“把它投到电视上”，就是把这个空间接到电视。
  - 沿用 docs/65 的降速：没有呈现端的空间按低帧率渲染。
- **浮窗**：
  - **第一阶段**保留现有 Linux 浮窗，只把录制对象换成那个空间：由一个小助手连到该空间的 KWin，申请 `zkde_screencast`，拿到 PipeWire 节点号。PipeWire 是全局的，浮窗照常显示。
  - **第二阶段**可改为宿主层浮窗：APK 中的小 SurfaceView，零拷贝，交互从 QML 移植。多个空间可以各有一个浮窗。
- **Agent 的操作**：`rungic_cua`（桌面工具）按 `RUNGIC_WORKSPACE` 连对应空间的 KWin，截图、脚本、fake input 都在那个 KWin 上。它的点击和打字只影响那个空间的座席，碰不到用户的焦点。
  - Luna 现在经 RemoteDesktop 门户输入，门户属于用户会话，要改为直连该 KWin 的 `org_kde_kwin_fake_input`。浮窗已经在用这个协议。
- **多个 Agent**：每个 Agent 一个空间名，各自有语音服务里的 Codex 环境和自己的 `rungic_cua`。空间的创建和回收由一个“工作空间管理”服务（或语音服务）负责，空闲时可以停掉。
- **用户空间**：现在的 KWin 不变。现在的 CAST-1（桌面投电视）就是用户空间的第二个显示源，电视也可以换接到它。

## 待定（需要用户决定或原型验证）

1. **D-Bus 会话**：
   - 每个空间一条独立总线，隔离最彻底。KWin 的 `org.kde.KWin` 名称不会和主 KWin 冲突，`rungic_cua` 的脚本和截图也能按空间分开。代价是空间里的应用看不到用户会话的服务：通知、托盘（微信）、门户、输入法都要在空间里另起，或者单独转发。
   - 共用用户总线：必须给第二个 KWin 改服务名，而 KWin 和 Plasma 组件大量硬编码 `org.kde.KWin`，不推荐。
   - **倾向**独立总线，再按需加最小的服务：门户、通知转发到手机、托盘宿主。
2. **音频**：PipeWire 共用。空间里的应用建议输出到这个空间的虚拟 sink，声音跟着它的呈现端走（投电视时进电视，否则静音或送到手机）。需要调研。
3. **剪贴板**：各空间天然隔离；需要时由 Agent 显式搬运。
4. **放置补丁**：已放弃（用户决定）。写过的 `rungic-workspaces.patch` 已从 `packages/kwin` 撤回。它按进程环境决定窗口开在哪块屏，已在 Mac mini 编出 `+rungic9`，未安装。“语音助手 App 在手机上”在方案 A 里自然成立，因为用户空间只有手机和用户桌面。

## 原型验证清单（实施前）

1. 第二个 `kwin_wayland --android-host` 能否在容器里与主 KWin 同时运行：logind、GPU、宿主连接；看内存、GPU 和空闲功耗。
2. 宿主为第二个 KWin 客户端提供一个只属于它的输出，并把电视或全屏呈现端接过去，零拷贝，帧率与现在的助理屏一致。
3. 在空间里用独立总线启动 Dolphin、Blender、Firefox 和微信（Xwayland）：窗口只出现在空间里；文件对话框、托盘、输入法的表现。
4. `rungic_cua` 连到空间的 KWin，截图和 fake input 能用，用户手机上的焦点不受影响：在手机上打字的同时让 Agent 在空间里打字，两边互不干扰。
5. 浮窗录制空间画面：一个空间一个浮窗，两个空间同时存在。
6. 资源：一个空间闲置时的内存和功耗，两个空间同时工作时的情况。

## 分期建议

1. **原型**：验证清单第 1–4 项，只做一个 Agent 空间，浮窗沿用 Linux 路径。
2. **替换现有助理屏**：现在的 CAST-1 助理屏改为 agent-1 空间；电视和全屏可以接到用户桌面或 agent-1；技能和提示词改为“一律在自己的空间工作”。
3. **多个 Agent**：宿主层浮窗；工作空间管理；多个呈现端的切换界面（控制中心或浮窗工具栏）。

## 原型实施与实测（2026-09-29）

### 组成

- **宿主**（`native/plasma`，APK 2.15）：
  - `ws-1` … `ws-4` 四个监听口，连接时记下编号（`WaylandClientState.workspace`）。
  - 每个工作区一个 1920×1080 的输出，只让该工作区的 KWin 看见（smithay 的 `create_global_for` 加按客户端过滤）。
  - 呈现端（电视、全屏）显示“要求的显示源”，平台桥的 `agent-screen` 请求带上 `workspace`。
  - 选中工作区时，用户的 KWin 不再有第二个输出（`sync_user_cast`）。工作区还没连上时，等它连上再呈现。
  - APK 记住所选工作区，重启后在打开助理屏之前恢复。
- **KWin**：`--android-workspace` 选项（补丁 `android-workspace.patch`，+rungic9）：`--android-host` 模式下不建 WL-N 输出，只用宿主给的输出。
- **`plasma/workspace`**：
  - `rungic-workspace N`（用户单元 `rungic-workspace@N`）：独立 D-Bus 会话、独立 KWin 设置目录、自己的 Xwayland。GPU 环境取自 `/etc/plasma/gpu-env`，另需 `FD_KGSL_DMABUF_UBWC=1`，否则报 EGL_BAD_MATCH。启动器把总线地址和 X 显示号写入 `~/.local/state/rungic-workspaces/N/`。
  - `rungic-workspace-env N 命令`：在工作区里运行一条命令。
  - `rungic-user 命令`：在工作区里，把一条命令送回用户会话执行（例如通知）。
  - `rungic-workspace-input`：Agent 的指针和键盘，走 KWin fake input。
  - `rungic-workspace-stream`：给浮窗的画面，走 zkde_screencast，内嵌指针；同时转发浮窗里的触摸。
  - `rungic-workspace-desktop`：壁纸。
- **语音服务**：启动时拉起工作区 1。每个 Codex 线程的 `shell_environment_policy.set` 和 `mcp_servers.rungic-desktop.env` 都设为工作区环境：`WAYLAND_DISPLAY`、`DISPLAY`、`DBUS_SESSION_BUS_ADDRESS`、`RUNGIC_WORKSPACE`，外加用户会话的 `RUNGIC_USER_*`。
- **`rungic-agent-screen`**：`on` 或 `ensure` 时启动工作区并呈现它。浮窗始终在用户会话里打开，缺的环境变量从 systemd 用户管理器补齐，并加锁防止重复启动。
- **浮窗**：显示工作区时，由 `rungic-workspace-stream` 提供 PipeWire 节点号。
- **`rungic_cua`**：
  - 在工作区里，`desktop_launch` 一律开在工作区，并顺带让助理屏显示该工作区；
  - 会话环境改从用户总线读取；
  - 输入走 `WorkspaceInput`。
- **提示词和技能**：说明 Agent 在自己的工作区工作，碰不到用户手机上的应用。

### 实测（实机）

- 工作区 KWin 用 GPU 合成：OpenGL ES，FD710；常驻内存约 146 MB。
- 开在工作区里的应用只出现在工作区；fake input 点击不影响用户手机上的焦点。
- 全屏呈现工作区为零拷贝。
- APK 重启后：
  - 工作区 KWin 由 systemd 自动重启；
  - APK 恢复工作区 1 的呈现；
  - 用户 KWin 只有 WL-0；
  - 浮窗自动接回工作区画面。
- 端到端（新对话 01a0eced）：请求“用 Kalk 算 12×12”。
  - Agent 在工作区打开 Kalk，在屏幕上操作，回答 144；
  - 浮窗实时显示整个过程；
  - 用户会话里除浮窗外没有新窗口。

### 这一轮查到的问题与修正

- **环境泄漏到用户会话**：启动器里的 `dbus-update-activation-environment` 把 `WAYLAND_DISPLAY=wayland-ws-1` 和 `RUNGIC_WORKSPACE=1` 写进了用户 systemd 管理器的环境，之后由 systemd 启动的用户服务都会继承。已改为在启动私有总线前 export 这些变量；已清掉泄漏的值，并复核：工作区重启、Xwayland 启动之后，用户环境不变。
- **空工作区是透明的**：KWin 单独运行、没有 Plasma 外壳时，空白处 alpha 为 0。浮窗的图层随之整块透明，看上去像“浮窗消失”。已加壁纸程序，默认读取用户的 Plasma 壁纸设置；本机未指定图片，使用 Next 的 16:9 版本。
- **手机左上角的黑底光标**：宿主把 KWin 的光标表面画成了独立窗口。用户 KWin 没有第二输出后，指针落在 WL-0 上，这个问题才暴露出来。现在宿主不把以下表面当作独立窗口：无角色的、光标角色的、子表面，以及任何工作区客户端的表面。修复后 `unmanaged=0`，手机回到零拷贝路径。
- **`kstart` 在工作区里卡住**：Codex 启动 MCP 服务时只传少数环境变量，`rungic_cua` 再用 `busctl --user` 向 systemd 取会话环境；在工作区里这条请求发到了私有总线，没有 systemd，结果缺 `XDG_DATA_DIRS` 等变量，`kstart` 找不到应用。已改为向用户总线查询。
- **浮窗启动两次**：两个 `ensure` 同时执行。已加锁。
- **手机主屏幕错乱**（用户报告，约 19:07 起）：
  - 现象：壁纸放大，Dock 和时钟小部件不见，文件夹移位，应用抽屉的搜索栏超出屏幕。KWin 和 plasmashell 窗口的几何都正常（360×800），错在主屏幕 containment 本身：`desktops()` 里它的 `screen` 为 -1，也就是没有挂到任何屏幕上，于是按错误的尺寸布局。
  - 直接原因：用户会话的 kactivitymanagerd 当前活动为空（`CurrentActivity` 返回 ""），Plasma 按活动把 containment 挂到屏幕上。用 `SetCurrentActivity` 设回唯一的 Default 活动并重启 plasmashell 后恢复（已验证：containment 1 回到 screen 0，Dock 等恢复）。
  - 当前活动为何变空，尚未查明。时间上与 19:06 那次 APK 重启吻合；此前 18:53 做过一次 A/B 测试，第二输出增减一次，Plasma Mobile 的自动停靠写了 `plasmamobilerc` 和 `kde.org/plasmashell.conf`。工作区里没有第二个 kactivitymanagerd。`kactivitymanagerdrc` 里本来就没有 `currentActivity`。后续要继续观察是否复发。
- **应用数据库来回重建**（同时查出）：工作区 KWin 用自己的 `XDG_CONFIG_HOME`，却与用户共用缓存目录。ksycoca 记录它是为哪个配置目录建的，两边轮流判定“不对”并重建同一个文件，每秒数次；每次重建都让手机主屏幕重新加载应用列表（`Reloading folio app list`，一个 plasmashell 实例里出现上千次）。已给工作区单独的 `XDG_CACHE_HOME`，重建随即停止（已验证：数据库文件不再变化，主屏幕不再重载）。它不是布局错乱的原因：错乱之前的实例也在重载，布局却正常。

### 单实例应用的按需切换（2026-09-29，用户决定）

- **规则**：
  - 能多开的应用（Blender、Kalk、Dolphin 等）直接在工作区另开一个实例，不动用户那一份。
  - 每个用户只能跑一份的应用（微信、同一配置的浏览器、Telegram 等）按需切换：在用户会话里关闭，在工作区打开；Agent 最后一轮结束约两分钟后，自动还给用户会话，并发一条通知。
  - 关闭用户正在运行的实例之前，必须先征得用户同意（用户要求）。工具层强制执行：`desktop_launch` 或 `desktop_goal` 返回 `needs_confirmation` 和要问的话，只有带上 `"switch": true` 才会关闭；应用正在用麦克风（通话、会议）时一律不切换。
- **实现**：
  - `plasma/cua/rungic_cua/switch.py`：按程序名判断；按进程环境里的 `WAYLAND_DISPLAY` 区分会话；用 SIGTERM 正常结束；在 `$XDG_RUNTIME_DIR/rungic-workspace-switched.json` 里登记；`rungic-cua restore-apps N` 负责归还。
  - 语音服务：空闲检查时负责归还。
  - 微信代打电话的各个环节（查找窗口、拨号、接通检查、挂断）改为在微信当前所在的会话里执行。
- **验证**：
  - 单元测试 `tools/test_switch.py`（6 项）已通过。
  - 实机（2026-09-29 20:30，新对话 01a0ed24）：
    - 替身：一个名为 firefox、没有窗口的程序，在用户会话里扮演“用户的 Firefox”；归还时启动的也是它，因此用户手机上不会弹出窗口。
    - 请求“用 Firefox 打开 example.com”：Agent 调用 `desktop_launch`，得到 `needs_confirmation`，于是提问；替身未被关闭。
    - 回答“可以”：替身被关闭，Firefox 在工作区打开，页面加载完成，并登记为待归还。
    - Agent 结束约 2.5 分钟后，语音服务自动归还：工作区的 Firefox 被正常关闭，应用在用户会话里重新打开（替身出现在 `wayland-0`），记录清空，日志中有 `restored to the phone`。
  - 实测中修正：
    - Firefox 的可执行文件是 `firefox-bin`，原先按可执行文件名找不到它。现在同时比对去掉 `-bin` 的名字和命令行里的程序名，并且只处理主进程。
    - 从工作区内部调用时，缺少 `RUNGIC_USER_*`，浮窗被开进了工作区。现在 `rungic-workspace-env` 会带上这些变量，各处也默认回到用户会话。
    - 助理屏开着但浮窗不在时，会重新打开浮窗。
    - 之前的测试脚本“卡住”，原因是后台启动的进程继承了远程执行的输出管道，不是功能问题。
  - 语音转述问题：对“征求同意”的问题加了推荐（“建议你选择可以”），并在用户已经回答后又请用户再说一遍。已在 `realtime.md` 加规则：征求同意的问题原样、中立地转述，不给推荐。新规则从下一次实时会话开始生效。
  - 待测：微信重启后是否需要在主力手机上确认登录（需要用户在场）。

### D-Bus：私有还是共用（2026-09-29 的判断）

保持**每个工作区一条私有总线**，由我们补齐缺口；不共用用户总线。

- **共用的冲突是结构性的，没法逐个修补**：
  - 第二个 KWin 拿不到 `org.kde.KWin`；
  - 单实例应用（KDBusService Unique：Dolphin、Kate、Okular、Firefox 等）会把请求交给用户会话里已在运行的实例，窗口开在手机上；
  - 门户、输入法、快捷键都属于用户会话。
- **私有总线的缺口可以列举，都能在启动器或共享层补上**：
  - 会话环境：已补；
  - systemd 不在私有总线上：`systemctl --user` 走自己的私有套接字，不受影响；`busctl --user` 等要改走用户总线，或用 `rungic-user`；
  - 通知：目前没人接收，待做转发到手机并标明来源；
  - 托盘、kded：按需补。
  - 门户、ksecretd、at-spi、plasma-keyboard 会在工作区的总线上按需自动启动（已看到进程）。
- **边界**：用户在自己会话里登录的应用（例如微信）不在工作区里，Agent 碰不到。docs/63 的微信代打电话、代发语音需要另行设计：让微信常驻 Agent 的工作区，或做受控转发。这项待用户决定。

### 待办

- 打包：`plasma/workspace` 进入一个软件包；KWin +rungic9 发布；APK 2.15 发布。
- 工作区应用的通知转发到手机。
- 微信类流程的去向（见“边界”）。
- 空闲时停掉工作区以省内存（约 146 MB 加上其中的应用），以及多 Agent 的工作区分配和切换界面。

## 三块屏幕与 Agent 的工作位置（2026-09-29，用户定义）

### 概念

- **助理屏**：只指 Agent 自己的工作区屏幕。它在 Agent 需要时自己显示为浮窗，控制中心里没有它的开关（用户要求）。
- **桌面模式**：最早的功能（docs/65），即用户的桌面多一块输出，是完整的桌面，显示在手机的浮窗里。用户从控制中心的“桌面模式”打开。
- **投屏**：投出去之后就是桌面模式，电视显示用户的桌面。只有明确要求时（`rungic-agent-screen tv`），电视才改为显示助理屏。

### Agent 在哪工作

- 用户开着桌面模式，或电视在显示桌面时，默认在用户的桌面上工作。
- 否则在自己的工作区工作。
- 用户可以指定位置：`desktop_where`，取值 desktop、workspace 或 auto，在本次对话内有效。

### 实现

- **宿主**：用户 KWin 的第二输出，在桌面模式开着时按桌面模式的尺寸存在；或者在呈现端（电视、全屏）显示桌面时，按那个窗口的尺寸存在。它不再因为呈现工作区而消失（`sync_user_cast`）。
- **APK 2.16**：两套独立状态。
  - 平台桥：`desktop-mode` 对应桌面模式（开关、全屏、watched）；`agent-screen` 对应助理屏（开关、工作区、全屏、`tv`）。
  - 电视和全屏各自记住显示来源（`tvSource` / `fullscreenSource`），接管画面前先设好（`bindPresenter`）；电视断开后，下一台默认显示桌面。
  - 偏好 `desktop_mode` 和 `assistant_screen` 分开保存，旧的 `agent_screen` 迁移为后者。
- **浮窗**：同一个程序跑两份。`--desktop`（`com.rungic.DesktopMode`）显示桌面模式，`--workspace N`（`com.rungic.AgentScreen`）显示助理屏。两个浮窗可以同时存在，默认一上一下；工具栏出现时显示名称（“桌面”或“助理屏”）。
- **命令**：`rungic-desktop-mode`（符号链接）和 `rungic-agent-screen` 是同一个脚本，按调用时的名字区分；助理屏另有 `tv` / `notv`。
- **控制中心**：只有“桌面模式”（`com.rungic.quicksetting.desktopmode`），原来的“助理屏”开关已删除。
- **桌面工具**（`rungic_cua/router.py`）：
  - 语音服务启动的 MCP 进程作为路由，每次调用时决定目标，把调用交给对应会话里的 `rungic-cua mcp` 子进程，子进程在第一次用到时启动。
  - 目标变化时，结果里附一行 where/why。
  - 桌面一侧需要第二屏时打开的是桌面模式。
- **工作区应用的生命周期**：在工作区里，KIO 在会话总线上找不到 systemd，于是直接 fork，应用就留在语音服务的 cgroup 里，服务重启时被一起结束（实测：测试过程中工作区的 Kalk 消失）。现在工作区里的 `desktop_launch` 用 `systemd-run --user --scope` 给应用单独的 scope。
- **测试**：`tools/test_router.py`（6 项）。验收检查 `agent_screen_output` 改名为 `desktop_mode_output`，检查的仍是“第二输出按尺寸出现和消失”，也就是桌面模式。

### 实测（2026-09-29 20:53–21:05，APK 2.16）

- 桌面模式打开后，浮窗显示完整桌面（带任务栏）；再打开助理屏，两个浮窗同时存在，一上一下。
- 桌面模式开着时，请求“用 Kalk 算 3×7”：Kalk 开在用户的 CAST-1 上，结果里附 `where: desktop, why: desktop mode is on`，回答 21。
- 关闭桌面模式后，请求“算 6×8”：结果里附 `where: workspace`，Kalk 只开在工作区。
- 请求“在我的桌面上……算 9×9”：Agent 调用 `desktop_where desktop`，桌面模式随之打开，Kalk 开在用户的桌面上，回答 81。
- 工作区启动的 Kalk 进入 `app-rungic-ws1-org.kde.kalk-….scope`，显示仍是 `wayland-ws-1`。
- 测试后两块屏幕都已关闭，用户主屏幕正常。
- 未测：电视在显示桌面时的路由（需要电视在场）。实测中，关闭桌面模式时 KDED 会弹出“显示器已移除”通知，这是桌面模式开关原本就有的提示。

## 无障碍总线被工作区抢走（2026-09-30，已修复）

- **现象**：发布验收的 `input.text` 失败，报 `AT-SPI: Couldn't connect to accessibility bus`。手机上同时有两套 at-spi：一套是用户会话的（`at-spi-dbus-bus.service`），一套是工作区私有总线按需启动的。
- **原因**：两者都是用同一个 `XDG_RUNTIME_DIR` 启动的 `at-spi-bus-launcher`，socket 都在 `/run/user/1000/at-spi/bus`，后启动的会抢走这个路径。工作区一重启，用户会话里的程序就注册不到无障碍总线。助理读手机屏幕控件、验收脚本都依赖它。
- **修复**：
  - 工作区的 dbus-daemon 改用自己的配置 `/usr/share/rungic-workspace/dbus-1/session.conf`：在标准会话配置之前加一个服务目录。
  - 这个目录里的 `org.a11y.Bus` 由 `rungic-workspace-a11y` 启动 launcher，运行时目录改为 `$XDG_RUNTIME_DIR/rungic-workspace-N-a11y`。
  - 同时发现 `plasma/workspace` 原来不在任何包里（是手工部署的），现在并入 `rungic-agent-screen`（0.415，发布 20260930.3）。
- **实测**：
  - 两条总线分开：工作区为 `/run/user/1000/rungic-workspace-1-a11y/at-spi/bus`，用户会话为 `/run/user/1000/at-spi/bus`。
  - 已经连在失效总线上的 Qt 程序不会自己重连，切换 `IsEnabled` 也没用，需要重启：本次重启了 plasmashell。
  - 冒烟验收 9/9 通过。


## 工作区的环境照 Plasma 桌面会话配置（2026-10-01）

工作区是一块 1920×1080 的桌面，环境变量按 Plasma 桌面会话（`startplasma`）的样子设置，而不是手机会话（`startplasmamobile`）的。原因见 docs/103：Plasma Mobile 写死的 `QT_QPA_PLATFORMTHEME=KDE` 会进入程序启动时建的临时应用，让它的会话总线一直不派发消息；`PLASMA_INTEGRATION_USE_PORTAL=1` 又让文件对话框依赖门户的 D-Bus 信号，最终 Krita 整个卡死。

| 变量 | 工作区 | 用户会话（手机） |
|---|---|---|
| `QT_QPA_PLATFORMTHEME` | 不设（Codex 里是空字符串，Qt 当作未设置） | 不设（2026-10-01 起，`plasma-mobile` 补丁） |
| `PLASMA_INTEGRATION_USE_PORTAL` | `0`：进程内的 KDE 文件对话框 | `1`：门户的手机版选择器 |
| `KDE_FULL_SESSION`、`KDE_SESSION_VERSION` | `true`、`6`，不依赖调用者 | 由 `startplasma` 设置 |

- 三处保持一致：
  - `rungic-workspace`：工作区总线拉起的程序（门户等）继承它；
  - `rungic-workspace-env`；
  - 语音服务 `workspace_env()`：给 Codex 线程和桌面工具，也就是 Agent 启动的应用。
- 用户会话原来的值随 `RUNGIC_USER_<变量名>` 带进工作区，在 `rungic-user`、`router.user_session_env`、`switch.restore` 交还用户会话时恢复。原来没有的，交还时也不设。
- 测试：`tools/tests/test_workspace_env.py`、`tools/test_router.py`、`tools/test_switch.py`。


## 多 Agent 团队（调研，2026-10-01）

**用户设想**：做一款游戏时，由几个 Agent 组成团队，分别负责 Godot、Blender、音乐和绘画。每个 Agent 有自己相对独立的桌面，大家在同一个项目上协作。要回答的问题是：每个 Agent 一个桌面，还是所有 Agent 共用一个工作区？以及协作层怎么做。

本节结论来自三条调研线：Codex 源码、业界资料、实机只读查询。标注方式：
- **源码**：读过源码；
- **实机**：执行主机 K8-Plus，手机 ZY32MVJS25，只读查询；
- **资料**：官方文档、论文或博客；
- **推断**：未经验证。

本节不包含任何实施或验收。

### 1. 桌面隔离的粒度：每个 Agent 一个桌面

- **不能共用一个桌面**（源码，见上文“现状”一节）：KWin 只有一个座席，也就是一套指针、一个键盘焦点和一个活动窗口。两个 Agent 同时在一个桌面上操作 GUI，会互相抢焦点。要并行，就必须每个 Agent 一个合成器。
- **业界做法**（资料）：
  - 通常的隔离单位是“容器或 VM 加一个独立显示服务器”：Anthropic computer-use-demo、Bytebot、E2B Desktop、OpenHands、Devin 的子 Devin 都是这样。
  - 跨 Agent 共享靠挂载的工作目录或 Git 仓库；共享剪贴板的做法本轮没有找到。
  - 最接近我们的是 Microsoft UFO2 的 PiP 虚拟桌面（arXiv 2504.14603）：在同一台机器上另开一个会话，以画中画窗口显示。
- **现有工作区已满足这个粒度**（源码）：每个槽位有自己的 KWin、私有 D-Bus、Wayland、Xwayland 和剪贴板。
- **建议共享的**：同一个 Linux 用户、同一个家目录、同一个项目目录。分 Linux 用户会带来权限和配置复制的麻烦，收益很小。只有确实冲突的单实例应用，沿用上文的“按需切换”。

### 2. Agent 编排：每个成员一个 Codex 线程

- **Codex 0.159.2 自带多 Agent**（源码，`rust-v0.159.2` 浅克隆在 `.work/refs/codex-src-0.159.2`）：
  - `multi_agent`（V1，Stable，默认开启）提供 `spawn_agent`、`send_input`、`wait_agent`、`close_agent`，默认最多 6 个线程（`core/src/config/mod.rs:254`）。
  - `multi_agent_v2`（Stable，默认关闭）默认 4 个并发；子 Agent 结束后以消息形式交回父线程（`core/src/agent/control/completion.rs`）。
  - 实际用 V1 还是 V2，取决于服务端下发的模型目录，本轮没有核实。
- **原生子 Agent 做不到“一人一桌面”**（源码）：
  - 子 Agent 从父 Agent 克隆配置，强制继承工作目录、审批策略和沙箱（`core/src/agent/child_config.rs:131-190`）。
  - 角色（`[agents.<名>]`）只能改提示词、模型、推理强度等，改不了 `mcp_servers` 和环境变量（`core/src/agent/role.rs:36-48`）。
  - 结果是所有子 Agent 的桌面工具都指向同一个槽位。
- **可行做法**（源码 + 推断）：语音服务在同一个 app-server 里给每个成员开一个线程。
  - `thread/start` 的 `config` 是正式字段（`app-server-protocol/src/protocol/v2/thread.rs:100`），按 `-c key=value` 合并（`app-server/src/config_manager.rs:437-455`）。
  - 语音服务已经用它注入 `mcp_servers.rungic-desktop.env` 和 `shell_environment_policy.set`（`rungic_voice_agent.py` 的 `thread_settings()`）。只要按成员传入不同的 `RUNGIC_WORKSPACE`，就能把线程和槽位一一对应。
  - 工作目录、角色提示词和模型也可以按成员分别设置。
  - 成员线程内部仍可用原生子 Agent 做只读调研，因为它们共用同一个槽位，不冲突。
- **代码里的单 Agent 假设**（源码），改造时要逐项处理：
  - `rungic_voice_agent.py`：`WORKSPACE = 1`；只有一个 `thread_id`；不属于当前线程的通知直接丢弃；忙碌状态和进度播报都是单一的。
  - `rungic_cua`：`show_workspace` 会把助理屏切到自己的槽位，多个 Agent 会互相抢；`activity.json` 和 `switch.py` 的状态文件都是全局唯一；`restore-apps` 默认槽位 1。
  - 显示：`rungic-agent-screen` 一次只呈现一个槽位；APK 只记一个 `assistantWorkspace`。
  - 宿主：`WORKSPACE_SLOTS = 4`，写死在 `packages/android-host` 的补丁里；`rungic-workspace` 接受 1..9，但宿主只提供 ws-1..ws-4（实机：四个 socket 都在）。

### 3. 协作层：业界什么做法有效

- **资料中一致的结论**：
  - 一个协调者；
  - 按产物（文件或目录）划分负责范围；
  - 带依赖关系和锁的任务板；
  - 结构化的交接件；
  - 一个独立的验收 Agent。
- **Claude Code agent teams**（官方文档，实验特性）：
  - 组成：lead、若干 teammates、共享任务表（pending、in progress、completed，带依赖关系，认领时用文件锁），再加每人一个收件箱。
  - 文档明确：两个成员改同一个文件就会互相覆盖，所以要让每人负责不同的文件；建议 3–5 名成员。
  - 已知问题：任务状态滞后，lead 会提前宣布完成。
- **A2A v1.0**（官方规范）：任务状态机（SUBMITTED、WORKING、INPUT_REQUIRED、COMPLETED、FAILED 等）和 Artifact 可以直接借用为我们任务板的语义。它是跨框架的互通协议，不是编排器。
- **Anthropic 的经验**（官方博客）：
  - 多 Agent 一般比单 Agent 多耗 3–15 倍 token；
  - 应按“上下文能否隔离”来拆分任务，不按头衔；
  - 子 Agent 把产物直接写进文件，比层层转述更可靠；
  - 验证型子 Agent 效果最稳。
- **反面证据**：
  - Cognition 的 “Don't Build Multi-Agents”（博客）：决策分散在多个 Agent 里，会互相冲突。
  - MAST（arXiv 2503.13657）：多 Agent 的失败集中在系统设计、Agent 间错位、验证不足三类。

### 4. 游戏工具：能脚本化的用脚本，需要看和听时才开桌面

（资料）

- **Godot**：`--headless`、`--script`、`--import`、`--export-release`；推荐 glTF 导入，音乐用 Ogg。官方 4.7.2 提供 Linux ARM64 版本。社区有 godot-mcp（MIT），可以无界面地建场景、运行游戏、抓输出。
- **Blender**：`-b --python` 能完成建模、材质、渲染和 glTF 导出。blender-mcp 必须在 GUI 进程里运行，而且没有鉴权。
- **Krita**：Python 接口在 GUI 进程里。`kritarunner` 可以无界面运行，但维护不足。社区的 MCP 都需要开着 GUI。
- **音乐**：
  - LMMS：`lmms render`；
  - Ardour：`luasession`；
  - MuseScore：`-o` / `-j` 批处理；
  - SuperCollider：NRT 离线渲染。
  - 这些都能无界面导出。
- **判断**：生成、转换和导出几乎都能脚本化。必须用桌面的只有三类：
  - 看效果和听效果（比例、手感、混音）；
  - 笔刷、雕刻这类交互操作；
  - 插件驻留在 GUI 里的 MCP。

### 5. 手机上的约束

（实机，16:01–16:04）

- **内存**：
  - 手机 7.35 GiB，当时可用 2.68 GiB。
  - 整个容器只有一个 Android v1 memcg：`/dev/memcg/rungic-plasma`，上限 4 GiB，当时用量 2.68 GiB，`failcnt` 约 28 万，经常在上限处回收。
  - KGSL 显存峰值 2.08 GiB，很可能不计入这个 memcg（推断）。
- **一个工作区的开销**：
  - KWin 148–185 MB RSS，Xwayland 34 MB，desktop 75 MB，stream 59 MB；
  - 显示为浮窗时再加约 113 MB；
  - 私有总线上的门户、ksecretd 等，每个 36–62 MB。
  - 每个成员的 Codex 线程和 `rungic_cua` 约 0.2–0.35 GB。
- **重型应用实测**：当时另一条工作线正在 1 号工作区试装官方 Godot 4.7.2 arm64。启动 8 秒后 RSS 962 MB、显存 484 MiB；同一分钟 lmkd 以 “kswapd is busy” 为由连杀 6 个 Android 应用。
- **systemd 资源限制在容器里不生效**：容器 cgroup2 从根到 `user@1000.service` 的 `cgroup.controllers` 全为空，memory、cpu、cpuset、blkio 都在 Android 的 v1 层级上。`MemoryMax`、`CPUWeight` 会静默失效，`rungic-workspace@1` 显示 `MemoryMax=infinity`。要按工作区限额，只能从 Android root 在 `/dev/memcg/rungic-plasma/` 和 `/dev/cpuctl` 下建子组，再把进程迁进去，做法类似现有的 `adopt_container`（推断）。
- **声音**：
  - 容器的声音服务是 PulseAudio 17，默认 sink `android` 直通手机外放。
  - 工作区没有设 `PULSE_SINK`，所以工作区应用的声音会从手机外放出来。
  - 方案（推断）：每个工作区建一个 `module-null-sink ws-N`，并导出 `PULSE_SINK`；用户想听哪个，就用 `module-loopback` 把它接到手机或电视。
  - Sonic Pi、SuperCollider 需要 JACK，本机没有，需要另行验证。
- **观看**：电视、全屏、浮窗各只能显示一个来源；浮窗脚本只能开一个助理屏。同时看多个工作区，需要改脚本、浮窗程序和 APK。
- **应用**（Ubuntu 26.04 arm64）：
  - 已安装：Blender 5.0.1、Krita 6.0.1。
  - 只在软件源里：LMMS 1.2.2、Ardour 9.0.0、Audacity 3.7.7、SuperCollider 3.13.0、Sonic Pi 3.2.2。
  - 软件源没有 Godot 4（只有 godot3 3.6.2），也没有 MuseScore 4。
  - git 2.53 已装，git-lfs 3.7.1 可以装。
  - 磁盘可用 120 GB 以上，不是瓶颈。
- **估算**（推断）：
  - 4 个工作区全开、各跑一个重型应用，需要 5–7 GB，超过 4 GiB 的容器上限和当时的可用内存。
  - 默认档下比较现实的是：同时最多 1 个重型 GUI 应用、2 个工作区。

### 6. 建议架构

1. **成员 = Codex 线程 + 工作区槽位 + 角色**，由语音服务统一管理。
   - 协调者就是用户正在对话的助手，它通过我们提供的团队工具派活、查进度、验收。
   - 成员线程用线程级 `config` 绑定自己的槽位、工作目录和角色提示词。
2. **无界面优先，需要时才开桌面**：
   - 成员默认用脚本完成工作（`blender -b`、`godot --headless`、`lmms render`）。
   - 只有要看效果、听效果，或要用交互工具时，才启动或唤醒自己的工作区。
   - 工作区空闲就停掉。
   - 同时开着的重型 GUI 应用数量由管理服务限制，在手机上默认 1 个。
3. **协作层放在项目仓库里**：
   - `.team/` 下存任务板：状态参照 A2A，任务有依赖关系，认领时加锁。
   - 每个成员一个收件箱。
   - 按目录划分负责范围（`game/`、`models/`、`art/`、`audio/`），跨目录只通过导出产物交接（GLB、PNG 加帧表、OGG），交接规格由脚本检查。
   - 另设一个验收成员，在自己的工作区里运行游戏、截图、听声音。
4. **共享层要补的能力**：
   - 每个工作区的资源子组，从 Android root 侧建；
   - 每个工作区的 null sink 和“旁听”；
   - 全局状态文件（activity、switch）按槽位分开；
   - `show_workspace` 改为“用户当前关注的成员”；
   - 多个浮窗，或一个团队总览。
5. **以后可以把重活搬到别的机器**：工作区本质上是“一个 KWin 加一条显示输出”，Blender 渲染这类重任务可以放到 Mac mini 上跑，画面传回手机。现在不做，但架构上不要把它堵死。

### 7. 分期

| 阶段 | 内容 | 验收 |
|---|---|---|
| 0 | 每个工作区的资源子组和 null sink；全局状态文件按槽位分开；`show_workspace` 不再抢助理屏 | 两个工作区同时运行时互不干扰；一个工作区超出限额时只影响它自己；声音不再直接外放 |
| 1 | 线程与槽位一一对应；通知按线程分发；成员线程的启动和停止；工作区按需启动和回收 | 两个成员各在自己的槽位里打开应用、各自完成一个任务，用户手机上的焦点不受影响 |
| 2 | `.team/` 任务板和收件箱；协调者和成员的团队工具；目录负责范围；交接规格检查；验收成员 | 一个小游戏切片：Blender 导出 GLB → Godot 导入并运行 → 验收成员截图确认 |
| 3 | 团队总览、多个浮窗、旁听 | 用户能同时看到各成员的画面，并切换收听 |
| 4（可选） | 远程工作区 | — |

### 8. 需要用户决定

- **token 成本**：多 Agent 比单 Agent 多 3–15 倍。是先用 2–3 个成员试，还是一开始就 4 个？
- **容器内存档位**：默认 4 GiB 不够多个重型应用同时运行。调高档位会挤压 Android，增加 VPN 和宿主被杀的风险。
- **默认工作方式**：成员是否默认用脚本工作、只在需要时开桌面？这是让手机跑得动的关键。

调研时取用的 Codex 源码在 `.work/refs/codex-src-0.159.2` 和 `.work/refs/codex-0.156.1-features`（本机，不同步）。业界资料的出处见第 1、3、4 小节里的论文号和项目名。

### 9. 项目会话：KDE 的会话保存能否用来“按项目切换”（2026-10-01）

**用户设想**：Agent 会同时负责不同的项目。它应当知道自己在某个项目上用的是哪个桌面会话，以后能切回那个会话，打开的应用、文件和窗口都回到原样。

**KDE 现有机制**（源码，取自 KWin v6.6.6 和 plasma-workspace v6.6.6，存放在 `.work/refs/kde-session-20261001/`；Qt 一项取自 qtbase v6.10.2 的源码树）：

- **ksmserver**：
  - 基于 XSMP（ICE），会在环境里设置 `SESSION_MANAGER`。
  - D-Bus 接口已经支持按名字保存和恢复：`sessionList`、`saveCurrentSessionAs`、`restoreSession`。默认的两个会话叫 “saved at previous logout” 和 “saved by user”（`ksmserver/server.h:55-56`）。
  - 它只能保存和重启说 XSMP 的客户端，重启时用的是应用自己登记的重启命令。
- **Qt 6.10.2**：会话管理（`QSessionManager`）只在 X11 平台插件里实现（`qxcbsessionmanager.cpp`），Wayland 插件里没有。所以原生 Wayland 的 Qt 程序（Krita 6、KDE 应用）不参与 XSMP 会话，只有 Xwayland 程序才会被保存。
- **KWin 的 `xx-session-management-v1`**（Wayland 会话协议）：
  - 只有设置 `KWIN_WAYLAND_SUPPORT_XX_SESSION_MANAGER=1` 才打开（`wayland_server.cpp:383`），是实验特性。
  - 它只保存窗口状态，存在 `kwinsession` 里，并不负责重启应用；而且客户端也要支持这个协议，Qt 6.10.2 的 Wayland 插件里没看到对应实现。
  - KWin 自己的会话信息只保存 `X11Window`（`sm.cpp`）。
- **活动（Activities）**：KWin 6.6.6 启动时会删掉旧的 `SubSession: …` 配置组（`activities.cpp:50-57`）。也就是说，“停用活动时保存它的窗口、再启用时恢复”这个功能已经不在了，活动现在只用来给窗口分组。
- **应用这一侧**（推断，未逐一核对源码）：Blender 和 Godot 没有接入 XSMP。它们真正的状态在各自的项目文件里（`.blend`、`project.godot`、`.kra`、`.mmp`）。

**结论**：
- 方向对：“一个项目对应一个可保存、可切换的会话”。
- 但 KDE 的会话机制在 Wayland 上恢复不了我们要用的这些应用，不能拿来当底座。

**建议做法**（推断，未实施）：**项目会话由 Rungic 自己记录，工作区槽位只是用来显示它的地方。**

关系类似 tmux：会话可以挂到某一块“屏幕”上，也可以从屏幕上卸下来。

- **项目会话**是一份有名字的记录，存在项目仓库的 `.rungic/session.json` 里，或者在 `~/.local/share/rungic/sessions/<名字>/` 下登记一份索引。内容包括：
  - 项目目录，以及对应的 Codex 线程 ID（继续这个项目时 `thread/resume`）；
  - 打开过的应用：可执行文件、参数和它们打开的项目文件；
  - 窗口布局：从 KWin 读出的位置、大小和最大化状态；
  - 这个会话自己的工作区状态目录（KWin 配置、缓存），以及最后一次保存时的截图；
  - 未保存改动的处理记录。
- **挂上（attach）**：给会话分配一个空闲的槽位（宿主目前提供 1–4）；在这个槽位里启动 KWin，使用会话自己的状态目录；按记录用项目文件重新打开应用；再按记录放回窗口。
- **卸下（detach）**：
  1. 先让应用保存：Agent 用桌面工具或应用自己的脚本接口保存，存不了的要先问用户；
  2. 把窗口布局记下来；
  3. 关掉应用，释放槽位。
  - 手机内存紧，卸下的会话不保持运行；冻结进程会继续占内存，只在短时间切换时才考虑。
- **Agent 的视角**：项目和会话的对应关系写在项目里。Agent 进入一个项目时，就是“恢复这个 Codex 线程，再把这个项目的会话挂到一个槽位上”；切到别的项目，就先卸下当前会话。
- **与第 6 小节的关系**：团队里的每个成员，就是“一个线程，加上它在这个项目里的会话”。同一个成员参与不同项目时，会有不同的会话。
- **待核实**：
  - 各应用怎样可靠地保存和重新打开（Blender `-b` 脚本或 GUI 内保存、`godot --editor --path`、`krita <文件>`、`lmms <文件>`）；
  - 怎样从 KWin 读出和放回窗口布局（KWin 脚本，或启动后用窗口规则）；
  - 设置了实验开关后的 `xx-session-management` 能不能用来放回窗口（需要客户端支持，Qt 6.10 目前不支持）。

### 10. 工作区的生命周期：Linux 上的标准做法（调研，2026-10-01）

**起因**：用户关掉助理屏后，Ardour 还在运行。原因有两层：
- 浮窗上的 ✕（`AgentScreen::close`）只把助理屏标为关闭、退出浮窗，`rungic-workspace@1` 继续运行；
- `desktop_launch` 给应用建的 `app-rungic-ws1-…scope` 和工作区单元之间没有任何依赖，所以就算工作区停了，应用也不会跟着停。

**参照的做法**：
- **KDE 注销**（源码，plasma-workspace v6.6.6 `ksmserver/logout.cpp`，KWin v6.6.6 `sm.cpp`）分两段：
  1. 先让 KWin 记下状态，再给每个 XSMP 客户端发 `SaveYourself`（交互式）。应用可以弹出保存提示，也可以取消注销。
  2. 对 Wayland 窗口，KWin 的 `org.kde.KWin.Session.closeWaylandWindows` 逐个调用 `closeWindow()`：10 秒后还有没关的，发一条“取消注销 / 仍然注销”的通知；2 分钟后不再等待，强制继续。它只处理 `XdgToplevelWindow`，不管 Xwayland 程序。
- **systemd 的桌面约定**（`docs/DESKTOP_ENVIRONMENTS.md`，systemd v259）：
  - 会话必需的进程放在 `session.slice`，应用放在 `app.slice`，后台任务放在 `background.slice`；
  - 应用单元的命名是 `app-<启动器>-<应用ID>-<随机串>.scope`，推荐用 `.service`；
  - GNOME 用 drop-in 给自己启动的应用设置 `BindTo=graphical-session.target`、`CollectMode=inactive-or-failed`、`TimeoutSec=5s`，也就是“会话结束，应用跟着停止，最多等 5 秒”。
- **KWin 关闭 X11 窗口**（源码，`x11window.cpp:1348`）：程序支持 `WM_DELETE_WINDOW` 就发关闭请求，否则直接 `killWindow()`。所以对不支持这个协议的 X11 程序，“请它关闭”等于直接杀掉。
- **空闲检测**：KWin 实现了 `ext-idle-notify-v1` 和 `idle-inhibit-v1`（`src/wayland/idlenotify_v1.cpp`、`idleinhibit_v1.cpp`）。前者按输入判断空闲，用户和 Agent 的输入都算；后者是应用在播放等场景下声明“别当我空闲”的标准方式。
- **冻结**（实机只读，systemd 259）：容器的 cgroup v2 没有任何控制器，但冻结是 cgroup v2 的核心接口，不依赖控制器：`app.slice/cgroup.freeze` 和 `cgroup.events`（`frozen 0`）都在，`systemctl --user show -p FreezerState` 能读到 `running`。`systemctl --user freeze` 这次还没实测。
- **“有没有未保存内容”没有跨应用的标准查询方式**：Wayland 的 xdg-toplevel 没有“已修改”标志，Inhibit 门户的 logout 标志也很少有应用使用。所以“请窗口关闭、由应用自己决定要不要提示”是唯一通用的信号，KDE 和 GNOME 也都是这么做的。

**结论：建议的分层**（推断，按标准机制组合；第 1、2 条已在实现）：

1. **分组和生命周期交给 systemd**：
   - 工作区自己的 KWin 等进程是 `rungic-workspace@N.service`；
   - 应用按约定命名为 `app-rungicwsN-<应用ID>-<随机串>.scope`，放进工作区自己的 `app-rungicwsN.slice`（在 `app.slice` 之下）；
   - 用 `BindsTo=` 和 `After=` 绑定工作区（GNOME 有同样的先例），工作区一停，systemd 先停应用，再停 KWin。
2. **关闭分两段，和 KDE 注销一样**：
   - 第一段可以被否决：请每个窗口关闭（Wayland 和 X11 都处理），没关掉的报告出来，不自动强制。KWin 自带的 `closeWaylandWindows` 2 分钟后会强制继续，而且不管 X11 窗口，所以不直接用它。
   - 第二段不可否决：停止 systemd 单元，强制结束只作兜底。
   - 对不支持 `WM_DELETE_WINDOW` 的 X11 程序，第一段会被 KWin 直接杀掉，需要先识别、跳过，并报告出来。
3. **隐藏后冻结**（待实测）：
   - 工作区被隐藏、Agent 又空闲时，用 `systemctl --user freeze app-rungicwsN.slice` 冻结应用：不占 CPU，状态不丢，内存在压力下会被 ZRAM 压缩；重新显示或 Agent 要用时立即解冻。
   - KWin 本身不冻结，避免宿主等不到它的帧。
   - 冻结期间，发给这些应用的 D-Bus 调用会超时，音频流会中断，所以只在空闲时冻结。
4. **空闲判断用标准信号**：在工作区的 KWin 上用 `ext-idle-notify-v1`，没有任何输入一段时间才算空闲；应用用 `idle-inhibit-v1` 声明“别当我空闲”时不算空闲；再加上语音服务报告的“Agent 是否正在干活”。冻结一段时间后，再按第 2 条关闭。
5. **项目会话**（第 9 小节）的“卸下”就是第 2 条，再加上保存布局。
6. **资源上限**仍然只能从 Android 的 v1 memcg 来设（第 5 小节）。slice 只负责分组、冻结和停止。

**已实现**：
- `rungic_cua/workspace.py`：
  - 应用的 scope 命名为 `app-rungicwsN-<应用ID>-<随机串>.scope`，放进 `app-rungicwsN.slice`，带 `BindsTo=` 和 `After=rungic-workspace@N.service`；
  - `close-workspace` 分两段关闭：先把从用户会话切换过来的应用还回去，再请窗口逐个关闭，没关掉的报告出来，最后停止单元和 slice；
  - 对 X11 程序：不支持 `WM_DELETE_WINDOW` 的不请求关闭，按 PID 识别，没有 PID 的按 `WM_CLASS` 识别。
- Agent 的工具 `desktop_close_workspace`（router）。下一次调用桌面工具时，会自动重新启动工作区。
- 命令 `rungic-agent-screen close [--force]`，与只隐藏浮窗的 `off` 区分开。
- `rungic-workspace`：收到 TERM 停止时以 0 退出。原来退出码是 143，单元停止后显示 failed。
- 测试：`tools/test_workspace_lifecycle.py`。

**实机验证**（G100 S，开发覆盖，空闲的 4 号工作区，不显示，1 号工作区和其中的 Ardour 全程未受影响；记录在 `.work/verify/2026-10-01-workspace-lifecycle/`）：
- Kalk 的 scope 为 `app-rungicws4-org.kde.kalk-….scope`，`Slice=app-rungicws4.slice`，带 `BindsTo` 和 `After`。
- **冻结在容器里可用**：`systemctl --user freeze app-rungicws4.slice` 之后，`cgroup.events` 为 `frozen 1`，`FreezerState=frozen`；解冻后为 `frozen 0`。
- `rungic-cua close-workspace 4` 返回 `{"closed": true}`，Kalk 退出，工作区单元为 inactive。
- 兜底路径：只执行 `systemctl --user stop rungic-workspace@4`，Kalk 也随之停止，单元为 inactive、`Result=success`（修正 143 之前是 failed）。
- X11：`xmessage`（支持 `WM_DELETE_WINDOW`，但没有设置 `_NET_WM_PID`）收到关闭请求后正常退出。因为它没有 PID，促成了按 `WM_CLASS` 识别的补充。“不支持 `WM_DELETE_WINDOW` 的 X11 程序”这一情况只有单元测试，没有实机样本。
- 还没验证的：在真实对话里由 Agent 调用 `desktop_close_workspace`；有未保存内容的应用（例如 Ardour 的保存提示）走 `remaining` 的路径。

**用户操作对应的行为**（建议，待用户确认）：

| 操作 | 行为 |
|---|---|
| 浮窗 ✕，Agent 空闲 | 按第 2 条关闭；有应用没关的就保留工作区，并通知用户 |
| 浮窗 ✕，Agent 正在干活 | 只隐藏，这一轮任务中不再自动弹出 |
| 隐藏且空闲约 1 分钟 | 冻结应用 |
| 冻结后长时间空闲 | 解冻，再按第 2 条关闭 |

#### ✕、冻结和自动关闭（2026-10-01，按用户确认的表格实现）

- **浮窗的 ✕**（`agentscreen.cpp`）：助理屏的 ✕ 改为调用 `systemd-run --user rungic-agent-screen dismiss`，放在独立单元里运行，以免浮窗退出时连带被结束。`dismiss` 的行为：
  - Agent 正在这个工作区干活（语音服务的 `State` 里 `agentBusy` 为真，且 `workspace` 等于当前槽位）：只隐藏，并写入标记 `rungic-agent-screen-dismissed-N`。标记存在时 `show_workspace` 不会自动弹出浮窗；语音服务在 `turn/completed` 时删除标记。
  - 否则正常关闭工作区。有应用没关掉时，后台用 `notify-unsaved` 发一条通知，提供“查看”（重新打开助理屏）和“不保存，直接关闭”两个操作。
- **冻结和自动关闭**（`agent/workspace/keeper.cpp`）：`rungic-workspace-keeper N` 随工作区一起启动和结束。
  - **怎样算“安静”**：同时满足三条：
    - `ext-idle-notify-v1` 报告没有输入；
    - 平台桥显示这个工作区没在显示；
    - Agent 没在这个工作区干活。
  - **冻结**：安静时冻结 `app-rungicwsN.slice`。外部解冻后，只要仍然安静就会重新冻结。
  - **自动关闭**：安静持续足够久，就在工作区单元之外运行 `systemd-run --wait --pipe rungic-cua close-workspace N`。
  - **时间**：默认 60 秒冻结，1800 秒关闭；可以用 `RUNGIC_WORKSPACE_FREEZE_S` 和 `RUNGIC_WORKSPACE_CLOSE_S` 调整。
  - **日志**：判断的变化写到工作区状态目录的 `keeper.log`。
- **调用 systemd 时用用户会话总线**：工作区自己的总线上没有 systemd，`freeze` 会报 “Failed to add reference to unit”。所以 keeper、`workspace.py` 和 `rungic-agent-screen` 调用 systemctl 时，都显式使用用户会话总线。
- **关闭期间不冻结**：
  - `workspace.close` 会写一个“正在关闭”的标记 `rungic-workspace-N.closing`，keeper 看到它就不冻结；
  - 关闭开始时和停止单元之前，各解冻一次；
  - 工作区脚本收到 TERM 时也会先解冻；
  - 应用 scope 的 `TimeoutStopSec` 为 10 秒。
- **解冻的时机**：router 转发调用给工作区之前，以及 `rungic-agent-screen on`、`ensure` 显示浮窗之前，都先解冻。

**实机验证**（4 号工作区，不显示；测试 drop-in 设为 10 秒冻结、45 秒关闭；脚本和日志在 `.work/verify/2026-10-01-workspace-lifecycle/keeper-test*.log`；助理屏状态前后一致）：
- 没有输入 10 秒后冻结（`freeze: 0`，`FreezerState=frozen`）；
- `workspace.thaw` 之后立即恢复，几秒内又重新冻结；
- 安静 45 秒后自动关闭，Kalk 退出，工作区停止；
- 拒绝关闭的 GTK 测试程序被报告在 `remaining` 里，工作区保留；强制关闭后它和工作区都结束了。

**测试中发现并修正的问题**：
- keeper 的 `systemctl` 和 `systemd-run` 走了工作区自己的总线，冻结和自动关闭都失败；
- 关闭流程等待应用期间，keeper 又把应用冻住了，强制关闭后应用仍然存活，最长要等 90 秒才被结束。

**一次测试方法上的错误**：在测试工作区里用 `rungic-cua launch` 打开应用，会调用 `show_workspace()`，结果用户手机上的助理屏被切到了 4 号工作区并打开了浮窗。已经恢复，之后的测试改用 `systemd-run` 直接启动应用。

**没有实测**：
- 用户在真实界面里点 ✕ 的三种情况；
- 通知里的两个操作；
- 语音服务忙碌时只隐藏的路径；
- 默认的 60 秒和 1800 秒在真实使用中是否合适。
