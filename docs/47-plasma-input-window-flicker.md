# Plasma Mobile 输入时窗口上下闪动

2026-09-23，独立 Ubuntu Plasma 容器；Phosh 不改。用户报告点击正在输入的文本框时，包含文本框的窗口快速上下跳动。

## 实机定位与上游核验

Marknote 的“新建笔记”空白输入框可复现。KWin 窗口信号记录显示：每次触摸后，应用高度由486恢复为726，再于约60–90ms后回到486；y始终38。输入法进程未崩溃。在单字段复现期间，VirtualKeyboard的active/visible信号没有对应切换，不能归因于Rime崩溃或候选排序。

GDB短暂附加KWin，触摸触发`XdgToplevelWindow::maximize`，调用链来自Qt QML。继续核对Plasma Mobile 6.6.5的`convergentwindows`脚本：每次运行均直接把`frameGeometry`设置为MaximizeArea。它响应窗口激活、屏幕变化和最大化状态；本机触摸伴随输出更新时也可反复触发。MaximizeArea不包含虚拟键盘的临时避让，随后KWin的输入法代码再次缩小窗口，形成抖动。

对照当日[Plasma Mobile主线脚本](https://github.com/KDE/plasma-mobile/blob/master/kwin/scripts/convergentwindows/contents/ui/main.qml)，仍有相同直接赋值，以及在反复激活时累加匿名信号连接的写法。该直接赋值原为消除取消窗口边框时的尺寸竞争，相关[上游问题256](https://invent.kde.org/teams/plasma-mobile/issues/-/issues/256)本轮网页访问失败，仅核验了源码中保留的说明，不宣称已查清其所有历史。

另对比[Plasma Keyboard主线输入监听](https://github.com/KDE/plasma-keyboard/blob/master/src/inputlisteneritem.cpp)、KWin6.6.6的`InputMethod`/`Window::setVirtualKeyboardGeometry`，以及[Qt6.10.2 Wayland text-input-v3](https://github.com/qt/qtbase/blob/v6.10.2/src/plugins/platforms/wayland/qwaylandtextinputv3.cpp)。GTK两个字段切换时有第二条独立路径：键盘前端立即响应旧上下文失活，把窗口隐藏并销毁Wayland surface，随后新上下文又显示窗口。需分别验收，不能用单字段测试代替。

源码摘取/主线副本、日志、录屏均在`.work/refs/plasma-input-flicker-20260923/`。上游代码保留原许可：convergentwindows为LGPL-2.1-or-later；键盘输入监听为GPL-2.0-only OR GPL-3.0-only OR LicenseRef-KDE-Accepted-GPL；Qt源码副本保留文件头许可。

## 修复

1. `plasma/convergent-keyboard.patch`只在窗口边框实际需要取消时保留原直接尺寸设置；已经无边框的窗口由KWin继续管理最大化、屏幕工作区和键盘避让。将反复累加的匿名回调改成绑定当前活动窗口的`Connections`，并处理空窗口。
2. `plasma/install-convergent-fix.sh`使用dpkg-divert保存发行版原件到`main.qml.distrib`。升级Plasma Mobile后重新核对并应用补丁。现场热加载用了新路径，因为同一QQmlEngine重载同一路径仍可能命中旧组件缓存；不能把`loadDeclarativeScript`成功等同于新代码已生效。
3. `plasma/keyboard-focus.patch`将上下文可见性同步放到Qt事件队列末尾，合并同一批Wayland中的失活/激活。旧组合文本仍立即reset；真正失焦仍隐藏键盘；用户主动收起不经过延时合并。已构建部署并重启键盘，实机结果如下。

## 验收记录

- Marknote原问题：`before.log`、`before.mp4`；首次同路径热重载仍使用旧脚本，失败材料保留为`cached-old-script.*`。
- 换路径加载修复后，Marknote12次同字段点击无几何变化：`verified-taps.log`。
- 独立GTK4输入窗口20次同字段点击没有应用几何变化；实际触屏nihao首候选“你好”，点击候选提交正确：`gtk-acceptance.log`、`gtk-nihao.png`。
- keyboard-focus补丁部署后，GTK两个字段交替12次，仅出现GTK光标手柄自身的22个几何事件，应用窗口与OSK没有高度往返变化。
- 主动收起/再显示3轮通过；横屏切换后回到竖屏，应用恢复y=38、height=726。18时已重开完整会话，持久脚本与键盘补丁的再次输入验收仍待补齐。
