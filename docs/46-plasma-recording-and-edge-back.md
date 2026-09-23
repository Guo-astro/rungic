# Plasma 录屏与 Android 边缘返回

2026-09-23。

## 右下角按钮：保留上游设计

核对Plasma Mobile6.6.5 [NavigationPanelComponent.qml](https://github.com/KDE/plasma-mobile/blob/v6.6.5/containments/taskpanel/qml/NavigationPanelComponent.qml)：右侧按钮在键盘可见时关闭键盘，否则调用tasksModel.requestClose关闭活动应用。没有逐层页面返回逻辑。按用户要求不改。

## 左右边缘区分

Android16的公开[BackEvent.getSwipeEdge](https://developer.android.com/reference/android/window/BackEvent#getSwipeEdge())可区分左右；使用API34起的OnBackAnimationCallback，在手势完成时执行，取消不产生操作。Activity显式启用OnBackInvokedCallback。

`MainActivity.java`新增：

- 右侧边缘滑入：若键盘显示先收起，否则向当前Linux窗口发送标准Alt+Left返回快捷键。KDE StandardKey.Back、GTK常见导航与Firefox历史导航可使用这一组合；应用是否有可返回页面仍由应用决定，不自动关闭应用。
- 左侧边缘滑入：打开Android容器菜单。
- 单独的物理返回键、旧Android无边缘信息时，保留原有兼容入口；Android系统IME自身也可能优先消费返回。

复用了已有NativeBridge与Wayland按键队列，避免另造触摸边缘拦截区抢占Linux应用内部侧栏。现有native keymap未映射Android KEYCODE_BACK，因此没有直接发送该值冒充返回；Alt/Left现有映射已具备。APK1.6/versionCode7已部署，左侧菜单与右侧收键盘已实测；Dolphin子目录返回测试材料见verified-child.png、verified-right-back.png。沉浸状态第一次边缘手势可能仅显示Android系统栏，下一次才向容器分派返回。

## 录屏黑屏调查及候选修复

用户文件`Shared/Videos/screen-recording.webm`为VP8、720×1600、10.308秒、110252字节，抽取第2秒确为黑画面。副本与帧在`.work/refs/plasma-recording-20260923/`。播放器在16:24:02才打开文件；录制发生在16:23:40–50，问题不是只在播放环节出现。

调查实际源代码：

- Plasma Mobile的录屏quicksetting使用TaskManager.ScreencastingRequest和KPipeWireRecord。
- KWin6.6.6的`ScreencastManager::getPid`默认把请求进程PID作为`pidToHide`，只有xdg-desktop-portal-kde例外。
- `FilteredSceneView`排除这个PID的所有窗口。Plasma Mobile的桌面、面板与录屏按钮都在plasmashell进程，因而整个桌面可被一起排除。
- 当日master仍把请求PID传入OutputScreenCastSource，不能直接升级master就当作修复。
- 同时阅读KPipeWire6.6.6 DMA-BUF导入/下载路径；本机实际KPipeWire库是Ubuntu6.6.4，未替换该库。不能仅凭收到20个PipeWire buffer的旧验收就证明录屏像素正确。

`plasma/kwin-screencast.patch`：仅在本机MOTO_KWIN_FLAT_OUTPUT适配环境、请求可执行路径为`/usr/bin/plasmashell`时不排除整个请求进程；窗口显式`excludeFromCapture`规则照常保留。沿用原LGPL-2.0-or-later上下文，未关闭所有窗口录制保护。

定制KWin升级到`4:6.6.6-0ubuntu0.1+moto3`，先显式cmake构建后打deb并安装五包，重新hold。日志`kwin-moto3-build.log`、`kwin-moto3-install.log`。`plasma/build-kwin.sh`纳入补丁以支持干净源码重建。

moto3实机录像已恢复桌面和应用像素，材料moto3-frame.png、moto3-app-frame.png。用户随后反馈画质差，录屏转向H.264和声音源配置；后续的SHM方向、长录屏音轨时序/停止问题与moto4验收见48篇，不能把画面恢复等同于完整录屏功能已验收。
