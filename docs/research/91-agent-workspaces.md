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
  - 单元测试 `tools/test_switch.py`（4 项）已通过。
  - 实机：工具层的确认流程尚未在实机跑通（测试脚本卡住，待查）。
  - 归还一步会在用户手机上打开窗口，不在实机上测试。
  - 微信重启后是否需要在主力手机上确认登录，待测。

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
