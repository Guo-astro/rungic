# Blender 渲染事故与默认 CPU 渲染（2026-09-29）

## 用户报告

- 助理用 Blender 渲染篮球时，Blender 没有开在助理屏上，手机上出现黑屏窗口。
- 助理给出的结论是“Vulkan 后端退出，改用 OpenGL 成功”，用户据此判断 Vulkan 有问题，要求彻底修复。

## 当时发生了什么（对话 01a0ec30-6554 的记录和日志，手机时间）

| 时间 | 事件 |
|---|---|
| 16:16–16:18 | 助理读 `blender --help` 后，自己选了 `--gpu-backend vulkan`。Blender 默认是 OpenGL。 |
| 16:18:22 | `desktop_launch` 报告 Blender 窗口在助理屏 CAST-1。Vulkan 驱动为 Turnip（Mesa 26.3.0-devel，Adreno 710）。 |
| 16:18:20–16:18:56 | Android 连续以 LOW_MEMORY 为由结束进程（`dumpsys activity exit-info`：magisk、com.motorola.actions 等，importance 200 的进程也被结束）。 |
| 16:18:43 | Blender 窗口“Not Responding”，位于手机屏 WL-0，即用户看到的黑屏。 |
| 16:18:57 | 助理把窗口移回助理屏。 |
| 16:19:02 | KWin 启动了一个子进程，很可能是无响应处理程序 `kwin_killer_helper`。KWin 本身从 10:02 起一直在运行，没有重启。 |
| 16:19:15 | Blender 被 SIGKILL 结束（systemd：`code=killed, status=9/KILL`）。没有崩溃记录，也没有 core。 |
| 16:19:53–16:20:20 | 助理改用 `--gpu-backend opengl`（freedreno FD710，OpenGL 4.6），29 秒完成渲染。 |

- 当天 KGSL 显存峰值 `page_alloc_max` 为 2.23 GB，常态约 0.6 GB。
- 之后 VPN 断线两次，其间 adb 和容器都无法访问。

## 隔离复现（带内存看门狗：显存超过 1.8 GB 或可用内存低于 1.2 GB 时立即结束 Blender）

| 场景 | 显存峰值 | 最低可用内存 | 结果 |
|---|---|---|---|
| Vulkan，只开窗口 | 0.98 GB | 2.45 GB | 正常，窗口在助理屏 |
| Vulkan，400×400 球体，EEVEE | 1.62 GB | 1.88 GB | 6.7 秒完成 |
| OpenGL，同上 | 1.56 GB | 1.99 GB | 4.2 秒完成 |
| Vulkan，原篮球脚本 900×900，EEVEE | 1.68 GB | 1.92 GB | 约 20 秒完成；渲染时约 10 秒 Not Responding，属正常 |
| Cycles CPU，同一篮球场景，64 采样，降噪 | 0.76 GB（只有界面） | 2.80 GB | 约 75 秒完成 |

- 脚本：`.work/vk/repro.sh`、`bb.sh`、`cpu.sh`。
- **结论**：
  - 单独运行时，Vulkan 三次测试都正常，窗口也都在助理屏上。
  - “Vulkan 出故障、OpenGL 正常”只是事发时机的巧合，不是后端的差别。
  - 事发时的共同条件是内存吃紧。EEVEE 无论用哪个后端，都要多占约 0.9–1 GB 共享内存（手机没有独立显存，GPU 与 CPU 共用 7.3 GB）。
  - 那次运行比隔离复现多出约 0.55 GB，来源已无法事后查清。
- **Not Responding**：脚本在 Blender 主线程上渲染，渲染期间界面一定无响应。如果这时关窗，KWin 会强制结束 Blender。
- **分析中的更正**：
  - 起初以为 KWin 重启了，实际是 KWin 的子进程。
  - 又以为同时进行的打包在手机上编译、占满了内存。但 `rungic_package.py` 默认在 Mac mini 上构建（`RUNGIC_BUILD_HOST` 未设置），输出里的“(device)”指包的构建类型，不是手机，所以这一判断也不成立。
- **没有复现的**：窗口在 16:18:43 出现在手机屏上，原因不明。

## 决定与实现（用户决定，2026-09-29）

- **构建**：不在后台编译，除非用户明确要求；构建通常在 Mac mini 上进行。
- **Blender 默认用 CPU 渲染，只用一半核心**，把算力留给其他程序。
  - **系统级实现**（不靠助理记住）：`rungic-plasma-config` 安装 `/usr/lib/blender/scripts/startup/rungic_render_defaults.py`。Blender 每次启动都会载入它，图形界面、`-b` 后台和 `--factory-startup` 都一样。
  - 新场景（启动文件、新建文件）用 Cycles，设备为 CPU。打开的文件和脚本明确指定的引擎保持不变：这只是默认值。
  - 每次渲染开始时（`render_init`）和每次载入文件时，线程数上限为核心数的一半（本机 8 核，即 4）。脚本设成自动或 8 线程，也会被改回 4。
  - 实测：
    - `blender -b` 和 `--factory-startup` 下，默认值都是 `CYCLES CPU FIXED 4`。
    - 脚本分别设成自动和固定 8 线程，渲染时按 /proc 统计，实际都只占用 4.0 个核心。
- **技能**（`rungic-phone-desktop`）：
  - 用 Cycles CPU 渲染，64–128 采样加降噪；不改用 EEVEE 或 GPU，不传 `--gpu-backend`，除非用户要求。
  - 在助理屏上可见地运行脚本，用状态文件判断进度。
  - Not Responding 期间不关闭、不结束 Blender。

## 遗留

- 窗口为什么落到手机屏：`desktop_launch` 只把这个应用的第一个窗口放到助理屏。应改为同一次启动的进程的所有窗口都放到助理屏；原因需要复现后确认。
- 16:18:12 同时启动了两个助理屏浮窗进程，是重复启动问题。
- 15:49 的 `blender -b` EEVEE 渲染在 Mesa EGL 初始化（`driCreateNewScreen3`）时崩溃，另行调查。现在默认用 Cycles CPU，一般不会走到这条路径。
