# 工作空间：Agent 各自独立的 GUI 空间（方案，2026-09-29）

状态：方案与调研，未实现。所有“已核验”的内容都来自本机源码或实机，未验证的推断会单独标明。

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
