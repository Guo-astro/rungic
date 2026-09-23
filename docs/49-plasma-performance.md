# Plasma 动画、列表帧率与 Android 调度

2026-09-23，用户报告应用开启动画和滚动列表明显掉帧，并要求核查 Moto 的性能白名单。已部署APK1.7并完成第一轮同机对照，开启动画和滑动的长帧减少。本文区分已验证显示修正、调度实验和仍待定位的瓶颈；媒体任务的待办另见48篇。

## 已确认事实

- MotoPerfManagerService 把 `dev.moto.plasma`（UID10352）识别为 `TOP100 adj0 active bkt_active hasUI`；APK的CPU/cpuset组均为top-app，不能宣称APK被当作后台应用。
- LXC中KWin、plasmashell属于 `lxc.payload.plasma/user.slice/...`，在Android v1 CPU/cpuset控制器中仍为根组。允许使用CPU0–7，未发现只准用小核的限制。
- 本机CPU top-app竞争权重5120，根组1024；这是资源竞争时的相对权重，不代表速度或频率相差5倍。
- 采样时Android热状态为0，尚无证据把卡顿归因于温控。
- 旧版宿主DisplayPacer触摸请求最高120Hz，触摸后2秒降至活动60Hz，静止时释放请求，系统可能降到30Hz。1.7默认改为前台流畅优先；静止30Hz本身不是掉帧证据。
- 现有KWin→Android AHardwareBuffer协议还用glFinish保证GPU完成，没有跨进程显式fence；这也是候选瓶颈，不得直接删除同步造成画面竞争。

## 调研与复用入口

- [AOSP task profiles](https://source.android.com/docs/core/perf/cgroups)：平台用任务配置管理CPU组、cpuset等。设备已有 `/system/bin/settaskprofile`，可复用本机定义，而非为每个Linux应用编造厂商白名单。
- 本机 `/system/etc/task_profiles.json` 定义MaxPerformance→CPU top-app、ProcessCapacityMax→cpuset top-app；`/vendor/etc/task_profiles.json`另有Moto MDPF规则。配置副本及MotoPerf只读转储在 `.work/refs/plasma-performance-20260923/`。
- `/vendor/etc/perf/perfboostsconfig.xml`有应用启动、滚动、触摸加速配置。尚未证明这些配置存在适用于我们宿主的必要包名白名单，也未修改厂商配置。

## 对照方法与调度边界

同一手势/应用、无编译/录屏负载下采集SurfaceFlinger实际呈现时间，分别比较原配置、前台调度继承、稳定刷新率请求。临时调度实验只涉及KWin/plasmashell对应任务，随后恢复原组。没有把容器服务、编译、Docker等后台任务提升到top-app。若以后接入前台调度，应随Android前后台切换，保留温控与后台节能，且只作用于独立Plasma桌面进程，保留原cgroup以便退出恢复。


## 显示修正与第一轮对照

[Android帧率接口官方说明](https://developer.android.com/media/optimize/performance/frame-rate)明确提示频繁改变帧率请求可能在切换期间掉帧，且请求不保证被系统满足。通常优先Surface.setFrameRate；本机因Surface单独请求仍与90Hz类别竞争，额外匹配同物理分辨率的Window mode。没有更改显示分辨率。

`DisplayPacer.java`先前对每个Android display changed事件（包括刷新率没变的事件）都发送NativeBridge.setRefreshRate；原生层也无条件重新发布Wayland output mode。新Java层按实际刷新率去重，原生层另加相同mode不重复发布的保护。`plasma/adapt-native-presentation.py`保留了原生修复的可重建入口。

APK1.7/versionCode8新增菜单“显示流畅度”：默认流畅优先，在前台同时给SurfaceView和Activity请求同分辨率下的最高刷新率；自动模式保留原节能策略，离开/销毁Surface时释放请求。使用Android公开Window/Surface接口，未修改全局刷新率、温控或厂商白名单。

`tools/profile_plasma_frames.py`采集SurfaceFlinger呈现时间；固定8次滑动，或4次计算器启动/关闭。暂停也计入原始数据，不能用平均FPS掩盖长帧。新版本第一轮在桌面尚未准备好时的样本`display17-scroll.json`不作为有效对照，使用带实际抽屉界面确认的`display17-scroll-valid.json`。

| 场景 | 普通调度/旧显示策略 | 只把KWin/桌面临时移到top-app | 普通调度/新显示策略 |
|---|---:|---:|---:|
| 滑动P95帧间隔 | 11.19ms | 11.14ms | 8.78ms |
| 启动/关闭P95帧间隔 | 33.42ms | 22.39ms | 16.82ms |

这是一轮同机、无录屏/编译负载的对照，存在缓存/测试次序影响，不是全面性能基准。新显示策略下Android持续报告120Hz。所有数字只代表宿主Surface的实际呈现，不证明每个Linux客户端每帧都绘制了新内容。临时top-app配置已恢复，后续重开会话也恢复默认调度；尚未部署常驻调度代理。剩余大帧与复杂应用仍需跟踪CPU/GPU渲染、显式fence和冷启动路径。

## 最终版本生命周期复核

最终APK包含Java与原生两级刷新率去重，并在Activity.onStop清除Surface/View/Window请求；即使Surface已经销毁也会清除Window mode。onStart/Surface重建恢复请求。1.7最后一次构建哈希见 `.work/refs/plasma-performance-20260923/APK-SHA256SUMS`。

实际菜单切换“自动”后requested-hz=0；切回“流畅优先”，退到Android再返回后requested/actual均恢复120Hz，KScreen亦报告720×1600@120。后台Window不可见、无Surface、无preferred mode，帧计数采样停止。后台的android-refresh.ini保留最后一次前台样本，读取时需看sampled-uptime-ms，不能把旧的120Hz当作后台持续申请。证据：adaptive-idle.txt、lifecycle.json、background-window.txt、kscreen-final.txt、smoothness-menu.xml。

帧率请求仍服从Android显示调度；例如相机启动期间观察到短时实际60Hz、请求120Hz。流畅优先增加显示功耗，不绕过温控；可在左侧边缘菜单→显示流畅度切换自动。

后续APK1.8已改为原生1080×2400输出。本篇APK1.7的720×1600结果不能直接用于原生分辨率的性能判断；新的多轮GLES/Zink和原生Vulkan对照见[51篇](51-plasma-vulkan-benchmark.md)。
