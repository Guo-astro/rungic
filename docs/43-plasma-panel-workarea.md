# Plasma 状态栏高度与应用避让

2026-09-23，Plasma Mobile 6.6.5 / Workspace 6.6.6 / LayerShellQt 6.6.6。

## 问题与调查

Android 挖孔中心线适配让顶部面板实际厚度变成38个逻辑像素（配置38.5，由PanelView转成整数），但KWin工作区仍从y=22开始。普通应用上方16个逻辑像素被覆盖。旧截图仅说明应用启动，不能作为应用避让通过的证据。

核对上游：

- [Plasma Mobile面板](https://github.com/KDE/plasma-mobile/blob/v6.6.5/containments/panel/qml/main.qml)：动态修改PanelView.thickness，甚至有连续设置两次的上游补救；master当日仍采用相同厚度设置路径。
- [Workspace PanelView](https://github.com/KDE/plasma-workspace/blob/v6.6.6/shell/panelview.cpp)：setThickness与更新LayerShell exclusive zone不是同一个动作；后者依赖窗口事件/计时器或visibilityMode变化。
- [LayerShellQt Window](https://github.com/KDE/layer-shell-qt/blob/v6.6.6/src/interfaces/window.h)：公开QML附加属性名是`exclusionZone`，可绑定到真实QWindow。
- [KConfigWatcher](https://github.com/KDE/kconfig/blob/v6.24.0/src/core/kconfigwatcher.cpp)：`/plasmamobilerc`的`org.kde.kconfig.notify.ConfigChanged`，组名用0x1d分隔，参数`a{saay}`。

实机短暂切换面板可见策略后，工作区立即恢复y=38，确认是面板预留区没有同步，而不是每个App缺少适配。

## 实现

`plasma/panel-exclusive-zone.patch`在移动外壳的Panel.qml中，使用公开LayerShellQt接口，在初始化、厚度及显示策略变化后同步非浮动顶部普通面板的预留空间，值直接取PanelView实际整数厚度。保留原有挖孔中心线，不再叠加一层safe area。自动隐藏策略仍交给上游；应用真正全屏仍可占整个屏幕。

`plasma/install-panel-fix.sh`应用补丁；使用dpkg-divert把发行版文件保存在`Panel.qml.distrib`，升级时原包更新该副本。升级Plasma Mobile后应重新核对并运行此脚本；不应永远沿用旧版完整QML文件。补丁上下文沿用原GPL-2.0-or-later许可；LayerShellQt是公开接口复用，无复制其实现。

> 2026-09-26起Panel.qml随`plasma-mobile +moto2`打包，本地divert由该包的preinst移除（61篇）。

`plasma/display.py`在四项面板参数写完后发一次KConfig通知并flush。此前实测个别短命kwriteconfig --notify进程退出后，文件值已更新而运行中面板仍读旧值；异步通知退出竞争是推断，非完整Qt内部追踪结论。改为同一长驻连接批量通知后完成下列验收。

## 验收

实机日志`.work/refs/plasma-mobile-20260923/panel-acceptance.log`；最终独立GTK窗口测试从16:18:08开始。早期日志包含测试脚本选错多个Dolphin窗口和配置未及时通知的失败，不应混作最终结果。

| 操作 | 实测 |
|---|---|
| 高度52 | 应用y52、height712，与工作区一致 |
| 恢复38.5 | 面板整数38，应用y38、height726 |
| 全屏 | 应用y0、height800 |
| 退出全屏 | 恢复y38、height726 |
| 自动隐藏 | 工作区y0、height800 |
| 退出自动隐藏 | 恢复y38、height726 |
| 横屏 | 工作区y22、762×302，应用一致；侧面挖孔继续由APK边距处理 |
| 竖屏后重启plasmashell | 工作区y38、360×726，应用一致 |

Dolphin与Discover实际顶部工具栏完整显示，截图在refs/plasma-mobile-20260923与refs/plasma-store-20260923中。该修复面向常规遵守Wayland窗口尺寸的应用；不保证所有第三方App本身的最小尺寸/响应式布局都适合手机。
