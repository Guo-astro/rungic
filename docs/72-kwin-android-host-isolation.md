# KWin的Android宿主适配：协议化与独立后端

2026-09-26。docs/71的模拟升级显示，KWin的16条补丁散布在28个上游文件中（+847/−120行，11条改`src/backends/wayland/`），跟进6.7时大部分冲突都在这里。用户决定暂不向上游提交，直接试点两项结构调整：

- **协议化**：KWin与Android宿主（APK中的Wayland合成器）之间，用宿主通过Wayland协议通告的信息代替环境变量与旁路文件/套接字。
- **集中**：Android专用代码放进新的`src/backends/android/`，上游文件只保留少量钩子；上游改动时在钩子处编译失败，而不是在后端各处产生文本冲突。

调研报告：`.work/research/android-isolation/kwin-report.md`（KWin侧，逐项文件:行号）、`host-report.md`（宿主侧）。以下是结论摘要。

## 现状（调研结论）

**环境变量**（`plasma/kwin`、`plasma/gpu-env`设置）

| 变量 | 实际表达的信息 | 替换方向 |
|---|---|---|
| `MOTO_KWIN_RENDER_DEVICE=/dev/kgsl-3d0` | GPU是非DRM的KGSL；宿主dmabuf为v3（无feedback）；还被借用为“宿主是Android”（空闲抑制） | 宿主发dmabuf v4 default feedback；客户端按`st_rdev`找回路径；“是否Android”由后端类型表达 |
| `MOTO_GPU_ALLOCATOR` | 宿主提供AHB分配器及其套接字；无隐式同步；宿主会重启 | 分配仍走现有套接字（在渲染路径上，Wayland往返不划算）；路径由后端配置或宿主协议给出 |
| `MOTO_KWIN_FLAT_OUTPUT` | 一个开关五种含义：宿主按设备像素对待KWin表面、单表面零拷贝、手机主屏的模式与internal、手指滚动方向、借用于录屏 | 拆开：缩放用宿主preferred_scale的通用公式；单表面与主屏属性归Android后端；录屏两处单独核查 |
| `MOTO_KWIN_ANDROID_SHM` | 容器memfd过不了APK的SELinux标签 | 只注入Android后端的QPainter分配器 |
| `MOTO_KWIN_UBWC` | 宿主已在dmabuf格式表中列出QCOM UBWC modifier | 按modifier交集自动启用 |
| `MOTO_KWIN_EXPLICIT_SYNC`、`MOTO_KWIN_CAST_SCALE`、`MOTO_ANDROID_DISPLAY` | 未设置的调试开关与默认值；最后一个无人读取 | 删除 |

**旁路通道**：`android-display.json`（物理尺寸、可选分辨率与刷新率）与`platform.sock`的`display-set`（设置分辨率/刷新策略）属于输出状态，可由标准`wl_output`模式、`zwlr_output_manager_v1`（宿主已实现，但只报当前模式、apply不走Android）或小型项目协议承担；投屏输出靠`wl_output`的make/model字符串“Moto/Cast”识别；空闲抑制走D-Bus `dev.moto.Android.Power`并每5秒重发。宿主已通告`zwp_idle_inhibit_manager_v1`但只计数、没有效果。摄像头、编解码、音频与其他平台服务的通道与KWin无关，不动。

**KWin结构**：后端编译进`kwin_wayland`，`main_wayland.cpp`按启动参数选择；`WaylandBackend`的`createOutput`、`WaylandOutput`的模式构造与配置处理、`WaylandEglBackend::createOutputLayers`都不是virtual，`WaylandDisplay`的registry是写死的if/else链；`InputRedirection`在空闲抑制变化时不发信号。kwin-dev安装了core头文件（插件可在树外编译），但不含`backends/wayland/*`，所以后端子类必须在树内。

## 目标结构

- 新目录`src/backends/android/`：`AndroidBackend : WaylandBackend`、`AndroidOutput : WaylandOutput`、Android图层与分配器、宿主输出与宿主文本输入等；`kwin_wayland --android-host`选择它。
- 上游文件中的钩子约80–100行（H1启动参数、H2输出创建为protected virtual、H3 registry全局对象信号与断线回调、H4输出模式/缩放virtual、H5图层创建virtual、H6/H7分配器注入、H8空闲抑制信号、H9输入法提交接口）。
- 与宿主无关的通用改进（显式同步、滚动来源、dmabuf回退等，约230行）暂留为普通补丁。

## 试点范围（第一轮）

只切两片，各自完整走通并验收，再决定是否推广：

**A 协议化：空闲抑制**

- KWin：Android后端在KWin的空闲抑制状态变化时（H8：`InputRedirection`新增`idleInhibitedChanged`信号），在宿主输出表面上创建或销毁标准的`zwp_idle_inhibitor_v1`；删除`idle-android-power`补丁中的D-Bus调用、5秒重发与对`MOTO_KWIN_RENDER_DEVICE`的借用。
- 宿主：`idle_inhibit`处理器由计数改为对应表面可见时保持亮屏（沿用APK现有的keep-awake实现），并有Rust单元测试。
- 发布顺序：先装新APK（旧KWin仍走D-Bus，互不影响），再发KWin；回滚KWin时D-Bus路径仍在。
- 测试：新增探针客户端（创建带抑制器的表面）与验收场景`idle.inhibit`：抑制期间APK窗口带`FLAG_KEEP_SCREEN_ON`，释放后消失。补上docs/71所列“空闲抑制无测试”的缺口。

**B 集中：Android显示设置**

- 新建`src/backends/android/`与H1、H2、H4钩子；把`android-display-settings`补丁的内容（按Android信息构造模式列表、物理尺寸，用户修改时请求Android切换分辨率/刷新策略）移入`AndroidOutput`与`AndroidBackend::applyOutputChanges`。数据来源本轮仍是`android-display.json`与`platform.sock`，只改变代码位置；协议化放到下一轮（需要宿主列出全部模式并让`zwlr_output_manager_v1`的apply走Android）。
- `plasma/kwin`启动参数加`--android-host`；尚未迁移的代码继续读环境变量，迁移完毕后删除。
- 测试：`display.mode`、`display.geometry`验收，KScreen改分辨率与刷新策略，模拟升级时统计冲突变化。

**通过标准**：完整验收通过；`idle.inhibit`通过；`pq.py`统计的“触及上游文件的行数”下降；把试点后的补丁队列再次rebase到6.7.5，比较冲突数。

## 进度

**A 宿主侧（完成，APK 1.46）**：`native/plasma/src/android/idle_inhibit.rs`按表面记录抑制器（同一表面多个抑制器只算一次），状态变化时写eventfd；Java主looper监听该fd，把`FLAG_KEEP_SCREEN_ON`的第三个来源`AWAKE_WAYLAND`设为当前状态（原有两个来源：Linux会话的keep-awake与投屏）。实测：`plasma/diagnostics/wayland-probes/idle-probe`直接连宿主socket持有抑制器时，APK窗口出现`KEEP_SCREEN_ON`，释放后消失；APK 1.45下同一测试无效果。

**宿主单元测试首次运行**：宿主crate依赖oboe等Android库，不能在x86主机上编译测试，此前的25个`#[test]`从未运行过。新增`plasma/test-native-core.sh`：交叉编译测试程序，经adb在手机临时目录运行后删除。首次运行发现一个过期测试（发送18条命令却断言17条），已改为按列表长度断言；现27个全部通过（含`idle_inhibit`的2个）。

**KWin构建来源切到补丁队列（完成）**：`build_on_device.py`对`packages/kwin`用`pq.py source`，发布工具从`packages/kwin/debian/changelog`取版本；`+moto20`（内容与`+moto19`相同）已构建入库，随发布20260926.17部署。第一次部署的冒烟验收因一次plasmashell崩溃（签名`6c87dacae3ce`，Qt Wayland事件线程在`wl_display_read_events`中SIGSEGV）自动回滚：崩溃发生在部署重启会话时旧会话被关闭的那一刻，之前两次KWin重启也有同类报告。它是真实缺陷（KWin退出时Qt客户端崩溃，待查），但不是新发布的回归；部署工具改为从新会话就绪时统计新崩溃，并把余量从30秒改为2秒（统计窗口按相对时长计算，不受两端时钟影响）。

**B KWin侧（完成，KWin `+moto21`，发布20260926.18）**

- 新目录`src/backends/android/`：`AndroidBackend : WaylandBackend`（为所有输出创建`AndroidOutput`；用户修改手机输出的分辨率/刷新策略时请求Android，投屏输出不请求；在自己的事件队列上绑定宿主的`zwp_idle_inhibit_manager_v1`，KWin的空闲抑制状态变化时在手机输出表面上创建或销毁抑制器）、`AndroidOutput : WaylandOutput`（手机输出的物理尺寸与internal、Android分辨率×刷新率模式表；在Android宿主上由KWin决定缩放）；`android-display-client.h`移入该目录。
- 上游文件中的钩子：H1 `main_wayland.cpp`的`--android-host`；H2 `WaylandBackend::createOutputObject`（protected virtual）；H4 `WaylandOutput::modesFor`、`applyExtraChanges`（protected virtual）与`setRefreshRate`；H8 `InputRedirection::idleInhibitedChanged`信号。
- **折叠进补丁队列，而不是追加在末尾**：先在pq分支末尾开发并编译测试，再在新分支上重放原有补丁，删去`idle-android-power`与`android-display-settings`，冲突按“去掉Android显示设置部分”解决（`cast-output`、`cast-cursor-host-text-raw-outputs`两条），最后一条`android-backend`补丁把源码树补到试点结果。检验：从orig tarball用quilt应用导出的队列，结果与折叠后的源码树一致（仅上游`.gitattributes`标为export-ignore的`.clang-format`不在`git archive`中）。折叠时逐项比对搬移的代码，发现试点漏掉了`cast-output`补丁加入的`output->isCast()`判断（否则在KScreen里改电视输出会改手机分辨率），已补上。
- **主机上的构建与L1测试**：`tools/pq/build.Dockerfile`（x86，同一`ubuntu:26.04`摘要，`build-dep kwin`加测试需要而发行版构建不装的`libei-dev`）；源码只读挂载，`.git`用tmpfs遮住（KDE的CMake会写提交钩子）。结果：`testIdleInhibition` 9/9、`testInputMethod` 23/23、`testVirtualKeyboardDBus` 5/5、`testXdgShellWindow` 63通过7失败（含新增`testMinimumAboveMaximum`）。不含我们补丁的基线（上游＋Ubuntu补丁）在同一环境中同样是这7个失败（服务端装饰、desktop文件、kill辅助程序：环境缺少已安装的组件），记为已知环境失败。
- **量化**：我们的补丁在上游已有文件中的改动由29个文件+822/−68行变为31个文件+759/−69行（多出的是钩子所在的`input.*`、`main_wayland.cpp`、CMake），新文件由209行变为533行。再次把队列顺序合并到6.7.5：冲突由18条中15条变为17条中14条，**基本没有改善**——这种测法下第一条大补丁`android-host-graphics`在6.7上冲突后，后续依赖它的补丁连带冲突，新补丁也被牵连。试点证明了结构可行（钩子加新目录可编译、可测、可验证），但要在升级冲突上见效，必须把Wayland后端中的大补丁（图形、投屏、宿主输出）也迁入`src/backends/android/`。记录：`.work/research/patch-queue/pq-upgrade-report-pilot.txt`。
- **兼容性**：会话脚本`plasma/kwin`传`--android-host`，旧KWin不认识该参数会退出，所以`moto-plasma-session`依赖`kwin-wayland (>= +moto21~)`；新KWin需要APK 1.46（旧APK上抑制器只被计数，不保持亮屏）。
- **验收**：新增冒烟场景`idle.inhibit`（`moto-idle-probe`显示一个带抑制器的窗口6秒，APK窗口期间有`KEEP_SCREEN_ON`、结束后消失）。探针最初只在裸`wl_surface`上创建抑制器：直接连宿主有效，但KWin只对显示出的窗口计算空闲抑制，所以经KWin时无效——探针改为显示真实窗口，`--bare`保留给直接测试宿主。

**实机验收（20260926.18，KWin `+moto21`、会话包0.187、APK 1.46）**：部署的冒烟验收通过，其中新增的`idle.inhibit`通过——空闲抑制已经从KWin的Android后端经标准`zwp_idle_inhibitor_v1`到达宿主。完整验收16项中15项通过（含`display.mode`、`display.geometry`、录屏、合成器时序：paint p95 3.559 ms、呈现间隔p95 16.721 ms）；`camera.frames`（前置）首次只收到1帧，随后两次重跑都是20帧/28.5 fps——与.17相同，只在会话启动后第一次打开前置摄像头时出现，是docs/61记录的冷启动问题，不是本次引入。快照已提交。

**部署工具的一次事故与修复**：部署.18时手写的版本排序把旧的20260926.9选成了“最新”。工具把容器降级安装为.9后，在同步Android侧文件时发现源码已变，直接退出，没有回滚，留下降级的rootfs与仍在运行的.17会话。用`rollback --snapshot`回到部署前（快照由该次部署建立，Android侧文件未改动）。修复：Android侧源码在建快照之前检查；快照之后的任何异常都像验收失败一样保存证据并回滚；单元测试复现了这两种情况（修复前失败、修复后通过）。部署改为不带版本参数（默认最新）。

**另外发现的既有缺陷（未修复）**：快捷设置录屏在.17时连续两次失败——停止后只有`video0`接受了EOS，向PulseAudio监听源`pulsesrc`发送EOS的调用被阻塞，收尾线程一直等待，12秒后超时，只留下`.partial.mp4`。.18时同一场景通过，属于间歇性问题，但阻塞位置已经明确。

## 第二轮：全部迁入Android后端（2026-09-26，用户决定）

用户要求把KWin中剩余的Android宿主相关改动全部搬进`src/backends/android/`，按试点方法进行。不搬的只有不依赖Android、改的是KWin核心职责的补丁：`xdg-min-above-max`（窗口协议）、`virtualkeyboard-commit-text`（D-Bus接口）、`output-internal-to-scripts`（输出属性）、`ftrace-fd-markers`中的写入缺陷修正；它们保留为小补丁，但不再依赖任何环境变量。

**原则**：每个环境变量判断换成它实际表达的含义，写成钩子（基类是上游行为，Android后端覆盖），而不是把“是否Android”的判断搬个地方。

| 现在的判断 | 实际含义 | 改为 |
|---|---|---|
| `MOTO_KWIN_FLAT_OUTPUT`（输入坐标、视口、配置尺寸、缩放、主图层、层数、黑底） | 宿主按设备像素显示KWin表面；缩放由KWin决定；主图层直接画在输出表面上 | `WaylandOutput::hostScale()`（上游=scale，Android=1）、`ownsScale()`、`singleSurface()`；输入坐标经`mapFromHost()` |
| `MOTO_KWIN_RENDER_DEVICE`（打开设备、EGL渲染节点） | GPU节点不是DRM设备，宿主dmabuf没有main_device | `WaylandBackend::renderDevicePath()`（上游取dmabuf main_device，Android取`/dev/kgsl-3d0`）；Wayland后端把自己打开的设备路径交给`EglDisplay::create()` |
| 同上（宿主dmabuf只接受v4） | 宿主只提供v3 | 宿主dmabuf v3也可接受，缺main_device时由后端给设备 |
| 同上（给KWin的客户端只开放dmabuf v3） | 客户端无法解析非DRM的main_device | `OutputBackend::maxLinuxDmabufVersion()`（上游5，Android 3），`WaylandServer`据此创建全局对象 |
| `MOTO_GPU_ALLOCATOR`（GBM分配改走宿主租借） | 输出缓冲由宿主分配 | `DrmDevice`可注入分配器；Android后端注入宿主租借分配器（`androidgraphicsbuffer.h`移入后端目录），路径为后端配置 |
| 同上（glFinish/显式同步fence、禁止扫描输出客户端缓冲、光标层glFinish） | 这些缓冲没有隐式同步；宿主只能直接显示自己分配的缓冲 | `WaylandBackend::implicitSync()`、`hostImportsClientBuffers()`；有显式同步全局对象时用fence |
| `MOTO_KWIN_UBWC` | 宿主格式表含QCOM UBWC modifier | 按modifier交集自动启用 |
| `MOTO_KWIN_ANDROID_SHM` | 容器memfd过不了APK的SELinux标签 | Android后端的QPainter分配器用`/dev/shm`，不再影响全局SHM分配 |
| 宿主重启（`MOTO_GPU_ALLOCATOR`借作判断） | 宿主会重启，KWin应等它回来 | `WaylandBackendOptions`加宿主会重启的选项，断线处理交给后端 |
| `Moto`/`Cast`字符串、`MOTO_KWIN_CAST_SCALE` | 宿主通告的投屏输出 | 宿主输出跟踪与投屏输出移入Android后端（registry钩子）；投屏初始缩放按物理尺寸推算 |
| 录屏的两处`MOTO_KWIN_FLAT_OUTPUT` | 录制者是shell本身；GLES读回方向 | 前者改为按录制程序判断（通用）；后者先查根因 |

**分批与验收**：每批先在主机上编译并运行L1测试，再在手机上构建、部署、完整验收，最后统一折叠进补丁队列。
1. 图形与输出：渲染设备、分配器注入、UBWC、SHM、扁平输出、显式同步/隐式同步、宿主重启。
2. 投屏与宿主输入：宿主输出、投屏输出与光标、后台投屏、宿主文本输入、宿主滚动。助手屏在KWin看来也是投屏输出，可用它自动验收投屏代码路径；连接电视的部分需要人工验收。
3. 收尾：录屏两处；删除全部`MOTO_KWIN_*`、`MOTO_GPU_ALLOCATOR`环境变量；模拟升级到6.7.5并比较冲突。

### 第二轮进度

**实现（完成，KWin `+moto22`）**：三批都在主机的x86构建环境中编译，并运行KWin全部157个测试（`ctest -j8`），与不含我们补丁的基线（上游＋Ubuntu补丁）在同一环境、同一命令下比较：失败集合完全相同（57个，均为环境原因：没有X显示、并行冲突；`testMouseKeys`一次并行失败，单独运行两边都3/3通过）。环境问题使这57个测试目前没有实际意义，之后改为xvfb、串行运行。

**折叠（完成）**：不是把改动追加在队列末尾，而是按功能重写整个补丁队列（13条），每一步只取属于该功能的代码段，功能交织的段落手写中间状态（EGL帧结束：先只有钩子，再加显式同步fence，再加FTrace标记），每条补丁都能单独编译（在主机上检查了钩子这一步与最终状态）。从orig tarball用quilt应用后与测试过的源码树一致。顺序：xdg最小/最大尺寸、向脚本暴露internal、录屏×2、输入法接收宿主文字、虚拟键盘commitText、宿主dmabuf v3、`android-backend-hooks`、显式同步fence、FTrace、宿主滚动、跳过未变的配置、`android-backend`。

**结果（如实）**：

| | 第一轮前 | 第一轮后 | 第二轮后 |
|---|---|---|---|
| 我们的补丁在上游已有文件中的改动 | 29个文件 +822/−68 | 31个文件 +759/−69 | 39个文件 +620/−86 |
| 独立新文件 | 209行 | 533行 | 1056行 |
| 逐条单独合并到6.7.5时干净的补丁 | 18条中4条 | — | 15条中6条 |

- Android专用代码（1056行）全部在新文件中，`android-backend`补丁在6.7.5上干净应用；升级时它只会在钩子签名改变处编译失败，不会有文本冲突。
- 钩子比预估大：`android-backend-hooks`在23个上游文件中+342/−53行（方案估计80–100行）。钩子不只是新增虚函数，还要把原先分散的判断改为调用钩子并写明含义；分配器、SHM、EGL渲染节点、服务端dmabuf版本的钩子落在KWin核心文件里，所以涉及的上游文件从29个增加到39个。
- 冲突集中在：钩子补丁（9个文件）、依赖钩子上下文的三条小补丁（显式同步、FTrace、跳过配置）、以及核心小补丁（xdg、输入法、虚拟键盘）。这些冲突都对应明确的功能。
- 不再读取任何`MOTO_*`环境变量；会话脚本只传`--android-host`，Mesa的`FD_KGSL_DMABUF_UBWC`保留。

**新增验收**：完整级`cast.agent_screen`：打开助手屏后KWin出现`CAST-n`输出（1920×1080），关闭后移除；覆盖宿主输出跟踪与投屏输出的创建/删除（在旧KWin上先验证了场景本身）。
