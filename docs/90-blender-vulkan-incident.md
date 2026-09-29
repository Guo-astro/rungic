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
- **512×512 的实测**（篮球场景，Cycles CPU，4 线程，64 采样加降噪）：
  - 渲染约 20 秒，连同启动 Blender 约 26 秒。
  - 平均占用 3.78 个核心。
  - Blender 常驻内存约 340 MB，可用内存最低 2.85 GB，显存只多约 30 MB（界面）。
  - 画质正常，看不出噪点。
- **技能**（`rungic-phone-desktop`）：
  - 用 Cycles CPU 渲染；默认分辨率 512×512（用户决定，2026-09-29），64 采样加降噪，用户要大图时才提高分辨率；不改用 EEVEE 或 GPU，不传 `--gpu-backend`，除非用户要求。
  - 在助理屏上可见地运行脚本，用状态文件判断进度。
  - Not Responding 期间不关闭、不结束 Blender。

## 遗留

- 窗口为什么落到手机屏：`desktop_launch` 只把这个应用的第一个窗口放到助理屏。应改为同一次启动的进程的所有窗口都放到助理屏；原因需要复现后确认。
- 16:18:12 同时启动了两个助理屏浮窗进程，是重复启动问题。
- 15:49 的 `blender -b` EEVEE 渲染在 Mesa EGL 初始化（`driCreateNewScreen3`）时崩溃，另行调查。现在默认用 Cycles CPU，一般不会走到这条路径。

## 渐进渲染：手机和助理屏同时看到画面变清晰（2026-09-29）

- **Blender 不对外开放渲染中的像素**（已验证）：
  - 渲染进行中调用 `Render Result` 的 `save_render` 会报 “could not be saved”；
  - 在绘制回调里读帧缓冲，图像区域是黑的；
  - `gpu.texture.from_image` 只返回 1×1 占位。
- **分批渲染**：用 Cycles 的 `use_sample_subset`、`sample_offset` 把采样分批（64 分为 4、8、16、36）。已完成批次的平均就是那么多采样的渲染结果。
  - 实测篮球 512×512：预览在 1.6、4.3、9.2、19.8 秒依次出现；总耗时比一次渲染（18.6 秒）多约 6%，最终图与一次渲染看不出差别。
- **`rungic_render` 模块**（`/usr/lib/blender/scripts/modules/`，随 `rungic-plasma-config` 安装）：
  - 在界面里调用时，先存一份场景副本，交给后台 Blender（`blender -b`）渲染，所以窗口一直可响应。
  - Blender 自己的渲染窗口（“Blender Render”）逐批换上预览，所以助理屏、浮窗和电视都能看到画面变清晰。
  - 每批预览都写进动态通道（`rungic_cua.activity` 新增 `image`、`progress`），也写进 `<输出>.status.json`。
- **降噪**：Blender 5.0 的合成器在后台对一张图做 Denoise，实测没有执行（换成反相节点，输出也不变），所以第一版不降噪。
- **启动模块**：不再显示启动画面。
- **实机验证**：
  - 界面调用后，第 6、8、13、22 秒分别出现 4、12、28、60 采样的预览，第 23 秒完成。
  - 助理屏截图里，渲染窗口显示的是 28 采样时的预览。
  - 端到端测试（新对话“用 Blender 做一个足球”）：助理按技能调用 `rungic_render`，等状态文件显示完成后才回答；自己检查结果、修了两轮，计划三步全部完成。
- **问题**：App 被开到了助理屏上；渲染窗口一度开到手机上。根本原因是 KWin 只有一个座席和一个活动屏，改为方案 A 的工作空间解决（docs/research/91）。

## 编辑窗口里的模型显示错乱（2026-09-29，用户报告）

- **现象**：小火箭用 CPU（Cycles）渲染出来是对的，但 Blender 编辑窗口里的模型“特别奇怪”：零件错位，火箭头缺失，只剩一片尾翼。
- **编辑窗口怎么画**：编辑窗口由 GPU 实时绘制，“实体”模式是 Workbench，“材质预览”是 EEVEE。Blender 5.0.1 默认后端是 OpenGL，本机为 freedreno FD710（Adreno 710），Mesa 26.3.0-devel，即硬件加速。Blender 提示 “Could not find a matching GPU name”，不认识这块 GPU。
- **复现**：同一文件、同一镜头，用 GPU 的 Workbench 和 EEVEE 出图，两者错得一样，而 Cycles CPU 正确。
- **最小对照**：三个立方体，大小、颜色、位置各不相同，其中一个带倒角。OpenGL 下，物体之间的大小、颜色、位置互相串位；Cycles 正确。所以与模型和修改器无关：每个物体取自己的数据时取错了。
- **排除**：
  - `--debug-gpu-force-workarounds` 无效。
  - Blender 5.0 硬性要求 `GL_ARB_shader_draw_parameters`，用 `MESA_EXTENSION_OVERRIDE` 去掉它后，Blender 直接拒绝启动，没有退路。
  - llvmpipe（Wayland 和 Xwayland 下都试过）与 zink 在本机无法建立上下文，或者崩溃，因此没能用软件渲染对照。
- **同一 GPU 的 Vulkan 后端**（`--gpu-backend vulkan`，Turnip Adreno 710）：三个立方体和小火箭的 Workbench、EEVEE 都正确。
- **结论**：freedreno 的 OpenGL 实现在 Blender 按物体取数据的这条路径上出错，同一硬件的 Turnip（Vulkan）正确。用户看到的显示错乱就是这个原因，不是模型本身的问题。
- **尚未查明**：freedreno 具体哪一处出错（gl_BaseInstance、gl_DrawID 和间接绘制的组合是首要怀疑），上游是否已有修复。
- 脚本：`.work/logs/gpu-views.py`、`gpu-cubes.py`；对照图在当次会话的 scratchpad 中。
- **默认改为 Vulkan（用户决定，2026-09-29）**：系统启动模块把用户的 GPU 后端偏好设为 Vulkan。
  - 第一版只设一次（留标记），随即失效：还在用 OpenGL 的旧 Blender 退出时自动保存偏好（`use_preferences_save`），把 OpenGL 写了回去；助理再次打开时仍是 OpenGL，编辑窗口仍然错乱（用户再次报告）。
  - 现在每次以图形界面启动时，都把偏好保持为 Vulkan，本次会话内存里的偏好也是 Vulkan，退出时自动保存的也就是 Vulkan。在 Blender 的 `config/rungic-gpu-backend` 里写 `OPENGL`，可以保留 OpenGL。
  - 实测：关闭旧实例、恢复偏好后重新打开小火箭，进程加载了 `libvulkan_freedreno`，编辑窗口显示正确。
  - 待查：Turnip 在 KGSL 上显示时会闪屏（56 篇）。这个问题可能也影响 Blender 窗口，尚未逐帧检测。
