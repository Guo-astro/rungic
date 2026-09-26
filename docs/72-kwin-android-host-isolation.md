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

**B KWin侧（进行中）**：在pq分支末尾以临时提交实现，折叠进补丁队列前先构建与测试。
- 新目录`src/backends/android/`：`AndroidBackend : WaylandBackend`（为所有输出创建`AndroidOutput`；用户修改分辨率/刷新策略时请求Android；在自己的事件队列上绑定宿主的`zwp_idle_inhibit_manager_v1`，KWin的空闲抑制状态变化时在手机输出表面上创建或销毁抑制器）、`AndroidOutput : WaylandOutput`（手机输出的物理尺寸与internal、Android分辨率×刷新率模式表；在Android宿主上由KWin决定缩放）；`android-display-client.h`移入该目录。
- 上游文件中的钩子：H1 `main_wayland.cpp`的`--android-host`；H2 `WaylandBackend::createOutputObject`（protected virtual）；H4 `WaylandOutput::modesFor`、`applyExtraChanges`（protected virtual）与`setRefreshRate`；H8 `InputRedirection::idleInhibitedChanged`信号。`idle-android-power`补丁（D-Bus与5秒重发）整条删除，`idle_inhibition.cpp`回到上游原样。
- 构建与L1测试：为不占用手机，在主机上建立x86的KWin构建环境（`tools/pq/build.Dockerfile`，同一`ubuntu:26.04`镜像摘要加`apt-get build-dep kwin`），先在主机上编译检查并运行KWin集成测试（虚拟后端）。
