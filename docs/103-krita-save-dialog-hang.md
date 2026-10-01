# Krita 菜单、工具栏都点不动：门户“另存为”的结果没送到（2026-10-01）

用户反馈：Agent 在工作区里用 Krita 画画时，用户和 Agent 都点不了菜单栏（“文件”“另存为”等）。

标注：“源码”指核对过的上游源码；“离线”指本机测试；“实机”指 G100 S。

## 现象与定位（实机）

- **Krita 只是看起来没反应，进程本身是活的**：
  - Krita 6.0.1（Ubuntu 包，Qt 6.10.2，原生 Wayland），运行在工作区 1（`wayland-ws-1`），主线程停在 ppoll；
  - 用 fake input 点 File 菜单、点工具栏的矩形工具、切 docker 标签、按 Alt+F，都没有反应；
  - 无障碍树里自由画笔仍是选中状态，说明点击确实没送到 Krita。
- **被一个看不见的模态对话框挡住了**：
  - Krita 的无障碍树里有一个对话框 `Saving As — Krita`，状态是 showing、visible，里面只有 Krita 自己加的预览标签和开关，这是门户原生对话框的空壳；
  - 工作区 KWin 里只有桌面和 Krita 主窗口，没有这个对话框；门户 `xdg-desktop-portal-kde` 的 `Saving As` 窗口是不可见的。
- **主线程停在“另存为”里**：`eu-stack` 显示 `QDialog::exec ← KoFileDialog::filename ← KisMainWindow::saveDocument ← slotFileSaveAs ← 快捷键`。
- **经过**（Codex 会话记录，加上门户日志）：
  - 09:19:07，Agent 按 Ctrl+Shift+S，门户弹出手机版文件选择器（MobileFileDialog）；
  - 09:19:28，Agent 在文件名框里输入完整路径 `/home/kevinzhow/Pictures/像素小伙伴_20261001.kra`，再点 ✓，选择器随即消失；
  - 之后 Krita 再也没有响应，`krita.log` 里也没有这次保存的记录；
  - Agent 后来从自动保存文件复制出了原稿和 PNG。
- **请求在两边的状态**：
  - Krita 内存里只有一个门户请求 `/org/freedesktop/portal/desktop/request/1_16/qt4200004915`；
  - 前端门户的对象树里已经没有任何请求对象，说明门户那一侧早已结束。

## 根因：Krita 会话总线一直处于“暂停派发”

- **会话总线上的调用都不回应**（实机）：
  - 对 Krita 在会话总线上的连接做 `Peer.Ping`，立即返回（这由 libdbus 自己应答）；
  - 对任意路径做 `Introspect`，连不存在的路径也算，都超时；
  - 同一时刻，Krita 在无障碍总线上照常应答，门户等其他 Qt 程序在会话总线上也照常应答。
- **Qt 的机制**（源码：qtbase 6.10.2 `qdbusconnectionmanager.cpp`、`qdbusintegrator.cpp`）：
  - 主线程第一次用到默认会话总线时，连接以“暂停派发”状态创建；
  - Qt 往 `qApp` 投递一条排队调用，等主事件循环处理到它，再恢复派发；
  - 暂停期间收到的消息只进队列：方法调用的回复走 pending call，照常能收到；信号和别人发来的方法调用都会被扣住。
- **结果**：
  - `SaveFile` 的回复（请求句柄）到了，所以门户对话框能弹出；
  - 门户发来的 `Response` 信号被扣在队列里，`QXdgDesktopPortalFileDialog::gotResponse` 永远不会执行；
  - 模态的空壳对话框一直不关，Krita 的所有输入都被它挡住。
- **干净启动的 Krita 也一样**（实机）：
  - 临时 HOME、工作区 1、`QDBUS_DEBUG=1`；
  - 会话总线连接（Wayland 插件加载之后建立）在第一条消息就记 `delivery is suspended`，运行到最后对我的探测仍是 suspended，从未恢复；
  - 另一条连接（无障碍总线）正常。
- **普通流程不会卡**（实机对照）：
  - 用 PyQt6 写了一个“另存为”测试，条件尽量和 Krita 一致：`PLASMA_INTEGRATION_USE_PORTAL=1`、名称过滤、窗口级模态；
  - 分别放进同名的 `app-rungic-ws1-…` scope、用 Ctrl+Shift+S 快捷键触发、在路径里带中文；
  - 每一种情况都能收到 `Response` 并正常返回。所以这是 Krita 进程自己的状态，不是门户或工作区的问题。
- **是谁让派发一直暂停**（Mac mini 上的容器复现 + gdb，Qt 的调试符号来自 Ubuntu ddebs）：
  - 复现环境：Ubuntu 26.04 ARM64，Krita 6.0.1、Qt 6.10.2、plasma-integration 6.6.5，和手机相同；无头 Weston 加一条独立的会话总线；
  - 会话总线是在 `KisOpenGLModeProber::probeFormat` 里第一次连上的。Krita 在建立 `KisApplication` 之前，先建一个**临时的 `QGuiApplication`** 探测 OpenGL 格式；
  - 调用链：`QGuiApplication` → `QPlatformThemeFactory::create`（KDE 主题）→ `KIconLoader::global()` → `QDBusConnection::sessionBus()` → `enableDispatchDelayed(context = 这个临时应用)`；
  - 探测结束后临时应用被销毁，投给它的“恢复派发”随之删掉；默认会话总线连接是全局的，此后一直暂停。`setDispatchEnabled(true)` 从未执行。
- **为什么偏偏是我们**（源码）：
  - Krita 在 KDE 会话里探测时会调用 `setDesktopSettingsAware(false)`（判断依据是有没有 `KDE_FULL_SESSION`）。这时 Qt 只会选通用主题，而通用主题只在建菜单栏或托盘图标时才用会话总线；
  - 但环境变量 `QT_QPA_PLATFORMTHEME` 的优先级高于这个设置。Plasma Mobile 的 `startplasmamobile` 写死了 `QT_QPA_PLATFORMTHEME=KDE`，于是 KDE 主题照样被加载进临时应用；
  - 普通 Plasma 桌面的 `startplasma` 不设这个变量，只设 `XDG_CURRENT_DESKTOP=KDE`、`KDE_FULL_SESSION=true`、`KDE_SESSION_VERSION=6`，Qt 据此自动选 KDE 主题（插件的键是 `kde`）。Krita 的探测因此拿到通用主题，不会出问题；
  - `startplasmamobile` 这一行来自 2019 年的 `kwinwrapper`（上游提交 f0f01e82）。那时会话是手工拼起来的，这些变量都要自己设；如今它最后调用 `startplasma-wayland`，这一行已经多余；
  - `PLASMA_INTEGRATION_USE_PORTAL=1`（上游提交 ccdfd348，2020 年）让 KDE 程序的文件对话框全部走门户。门户靠 D-Bus 信号返回结果，暂停派发因此从“几乎察觉不到”放大成了卡死。
- **缺陷本身在 Qt**：“恢复派发”挂在连接时的 `qApp` 上，临时应用销毁后就再也不会恢复。上游 qtbase dev 分支这段代码仍未改。修 Qt 能覆盖所有用系统 Qt 的程序，但自带 Qt 的程序（如微信）管不到。这些程序也加载不了系统的 KDE 主题插件，不会被我们的环境触发。

## 同一次还发现的门户问题（源码 + 实机）

- **手机版文件选择器把输入当成文件名**：
  - 保存路径的拼法是 `dirModel.folder + "/" + 输入的文字`（`kirigami-filepicker/declarative/FilePicker.qml`）；
  - 输入完整路径，就得到 `file:///home/kevinzhow/Pictures//home/kevinzhow/Pictures/….kra`，一个不存在的目录。实机测试中门户确实这样返回了。
- **默认文件名没有填进去**：`current_name` 在手机版路径里没有实现（`filechooser.cpp` 中注明 not implemented），所以 Qt 传过去的 `untitled.kra` 不会出现在文件名框里，用户和 Agent 只能自己输入。
- **Qt 的一个隐患**（源码：`QFileDialog::accept()`）：原生对话框收到“成功”但文件列表为空时，函数直接返回，不关闭也不报错，同样会留下一个挡住输入的空壳。这次不是这个原因，但门户丢弃路径时同样会触发它。

## 证据位置

- 截图：`.work/verify/20261001-krita-menu/`；
- 下载的上游源码：`.work/research/qt-portal/`；
- 测试脚本当时放在手机的 `/tmp`。

## 处理（用户决定：改环境，不改应用；先工作区，再手机）

- **工作区**（已部署为开发覆盖：`rungic-agent-screen`、`rungic-cua`、`rungic-voice-agent`）：
  - 照 Plasma 桌面会话配置：不设 `QT_QPA_PLATFORMTHEME`；显式设置 `KDE_FULL_SESSION=true`、`KDE_SESSION_VERSION=6`；`PLASMA_INTEGRATION_USE_PORTAL=0`，文件对话框在进程内打开，不用手机版门户选择器；
  - 三处都改了：`rungic-workspace`（总线拉起的程序继承它）、`rungic-workspace-env`、语音服务给 Codex 和桌面工具设的变量表。Codex 只能设值，所以在那里写成空字符串，Qt 把空值当作未设置；
  - 用户会话原来的值存进 `RUNGIC_USER_<变量名>`，交还用户会话时恢复：涉及 `rungic-user`、`router.user_session_env` 和 `switch.restore`，测试覆盖了有值和原本没有这两种情况。
- **离线**（容器）：不设 `QT_QPA_PLATFORMTHEME` 时，Krita 的会话总线正常回应，真正的应用照样加载 KDE 主题；设成 `KDE` 时无回应。加上 `QT_ACCESSIBILITY=1`（来自 Ubuntu 的 at-spi2-core）结果不变。
- **实机**（工作区 1，临时 HOME 的测试 Krita）：
  - 探测阶段用的是 `generic` 主题，会话总线在探测之后才连上；
  - 对不存在的路径立即回复 `No such object path`；
  - Ctrl+O 弹出进程内的 KDE 文件对话框，KWin 里能看到这个窗口；Esc 关掉后，Alt+F 能弹出菜单。
  - 第一次实测仍然卡住，原因是我从 adb shell 启动，环境里没有 `KDE_FULL_SESSION`，Krita 的探测于是仍按桌面感知选了 KDE 主题；Agent 启动的应用本来就带这个变量。所以工作区现在显式设置它，不再依赖调用者的环境。
- **手机端**（已部署为开发覆盖：`plasma-mobile` 6.6.5-0ubuntu0.1+rungic9+dev…，`rungic-plasma-session`；会话已重启，用户同意）：
  - `packages/plasma-mobile` 新增补丁 `startplasmamobile-no-forced-platform-theme.patch`，删掉 `startplasmamobile` 里的 `export QT_QPA_PLATFORMTHEME=KDE`，changelog 升到 `+rungic9`；
  - `desktop/session` 在 `exec startplasmamobile` 之前 `unset QT_QPA_PLATFORMTHEME`，并从用户管理器里删掉它：`startplasma` 只写入当前有的变量，旧会话写进去的值会一直留着；
  - 这是开发覆盖第一次部署上游组件（docs/97）。
- **手机端实测**（G100 S，会话重启后）：
  - 用户管理器、plasmashell 的环境里都没有 `QT_QPA_PLATFORMTHEME`；plasmashell 仍加载 KDE 主题插件；
  - 用手机会话的环境（用户总线，`PLASMA_INTEGRATION_USE_PORTAL=1`）启动测试 Krita，窗口放在工作区以免弹到用户屏幕：用户总线上对不存在的路径立即回复 `No such object path`，KDE 主题照样加载；
  - 没测：门户手机版文件选择器在用户屏幕上的完整“另存为”流程，因为它会弹到用户屏幕上。
  - 会话重启把工作区和其中卡住的 Krita 一起停掉了。工作区随后自动恢复，但 Agent 屏幕的浮窗没有回来（`window_running: false`），执行一次 `rungic-agent-screen ensure` 后恢复。快捷设置原本也会定期执行它。
- **门户手机版文件选择器**（开发覆盖 `xdg-desktop-portal-kde` 6.6.6-0ubuntu0.1+rungic2+dev…；上游 master 里这两处仍未改）：
  - 补丁 `mobile-dialog-suggested-name.patch`：没有 `current_file` 时，把 `current_name` 放在 `current_folder` 下（没有就放主目录）作为当前文件，文件名框里就有建议的名字；
  - 补丁 `mobile-dialog-full-path.patch`：以 `/` 开头的完整路径或 `file:` 地址原样使用，只输入名字时仍放进当前目录；路径每段做百分号编码，`#`、`?` 不再截断文件名；文件名为空时不能保存；在文件名框里按回车也能保存；
  - 部署时用 `--restart never`，只重启了用户会话和工作区的两个门户进程，没有重启会话。
- **门户实测**（实机，在工作区总线上直接调用门户的 SaveFile，对话框只出现在 Agent 屏幕上）：
  - `current_name="测试图.kra"`、`current_folder=~/Pictures`：文件名框已预填，直接确认返回 `file:///home/kevinzhow/Pictures/%E6%B5%8B%E8%AF%95%E5%9B%BE.kra`；
  - 清空后输入 `/home/kevinzhow/Pictures/full path #1.kra`，按回车：返回 `file:///home/kevinzhow/Pictures/full%20path%20%231.kra`；
  - 只输入 `草稿 #2.kra`：返回 `file:///home/kevinzhow/Pictures/%E8%8D%89%E7%A8%BF%20%232.kra`；
  - 没测：用户屏幕上由 Qt 应用发起的完整“另存为”，因为对话框会弹到用户屏幕上。
- **端到端实测**（实机，工作区 1，临时 HOME 的测试 Krita，新建 64×64 文档后另存为）：
  - 门户路径（`PLASMA_INTEGRATION_USE_PORTAL=1`，与手机会话相同）：弹出门户的手机版选择器，输入 `/tmp/krita-e2e/portal 测试 #1.kra` 后回车，文件写出（30 KB），Krita 日志为 “Saving Completed”，之后菜单照常弹出。这正是当初卡死的路径；
  - 工作区默认（进程内 KDE 对话框）：输入 `/tmp/krita-e2e/inproc 测试 #2.kra` 后回车，文件写出，菜单照常；
  - 选择器里预填的“Pictures”是 Krita 自己给的建议名：临时 HOME 里没有 `~/Pictures`，Krita 把默认目录名当成了文件名。进程内对话框里显示的也是它；
  - 旧配置（`QT_QPA_PLATFORMTHEME=KDE` 加门户）在新系统上照样能重现卡死：门户里确认后，文件没有写出，Krita 一直等在那里。
- **Agent 的真实路径**：以正在运行的 `rungic-cua mcp` 的环境执行 `rungic-cua launch org.kde.krita`。Krita 落在 `app-rungic-ws1-org.kde.krita-….scope` 里，`PLASMA_INTEGRATION_USE_PORTAL=0`、`QT_QPA_PLATFORMTHEME` 为空、`KDE_FULL_SESSION=true`，会话总线正常回应，KDE 主题照样加载。
  - `rungic-cua` 在运行时用 `setdefault` 从用户管理器补全变量，`KDE_FULL_SESSION` 本来就会补上；但语音服务的变量表现在也显式给出 `KDE_FULL_SESSION` 和 `KDE_SESSION_VERSION`，与两个工作区脚本一致，不再依赖这个隐含行为。
- **全系统扫描**：对用户会话总线和工作区总线上的全部连接，向一个不存在的路径调用 `Introspect`。46 个连接里 40 个正常回应；没有回应的 6 个是 `pipewire`、`at-spi2-registryd`、`xdg-desktop-portal-gtk` 的第二条连接（同一进程的另一条都正常回应），以及我们只发信号的 Python 脚本 `rungic-plasma-display`。没有别的 Qt 程序处在派发暂停的状态。
- **Agent 工具识别“被看不见的对话框挡住”**（`rungic_cua/blocked.py`，开发覆盖 `rungic-cua`）：
  - 每次 `desktop_screenshot` 和 `desktop_act` 截图后，检查活动窗口所属的程序：无障碍树里有“显示中、可见”的对话框，KWin 里却没有该进程同名的窗口，就是原生对话框的空壳；
  - 有门户进程的同名窗口时，提示“它在等那个单独的窗口”；没有时，提示“被看不见的对话框挡住了，不要再点，告诉用户，关掉程序是唯一出路”；
  - KWin 的窗口列表新增 `dialogs`（对话框类型的窗口），否则进程内对话框会被误判；
  - 实机：用旧配置重现卡死后，`desktop_act` 的结果里立即出现提示：“Krita is held by a dialog that is not on the screen ('Saving As — Krita') …”。进程内对话框打开时不出提示；
  - 测试：`tools/test_blocked.py`。
- **新增的测试**：
  - `tools/tests/test_workspace_env.py`：工作区脚本的输出、用户值的带出与恢复、语音服务变量表与脚本一致。把 `unset QT_QPA_PLATFORMTHEME` 去掉时，测试会失败；
  - `tools/test_rungic_dev.py`：上游组件的开发覆盖；
  - `tools/test_router.py`、`tools/test_switch.py`：交还用户会话时恢复两个变量。
- **还没做**：
  - Qt 补丁：降为可选的加固，暂不做（用户决定）。
  - 用户屏幕上由 Qt 应用发起的门户“另存为”：工作区里已经端到端测过同一个门户进程和同一套补丁，没有在用户屏幕上弹窗。
  - 主屏上那张 “Krita quit unexpectedly … crashed twice recently” 建议卡片，是测试期间结束 Krita 进程（会话重启时那个卡住的 Krita，以及测试实例）后，崩溃检测记录下来的，不是真正的崩溃。
