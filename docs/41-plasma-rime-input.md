# Plasma Mobile 的 Rime 中文输入

2026-09-23，Ubuntu 26.04 ARM64、Plasma Keyboard 6.6.6、Qt Virtual Keyboard 6.10.2、librime 1.16.1。

用户实际发现旧键盘输入一段后自动收起重开、候选消失、拼音排在中文前。本轮改用 **Plasma 官方屏幕键盘 + Rime 简体拼音**，保留英文切换；不改 Phosh 的输入法。

## 旧问题的证据

- 14:32:29 和 14:32:37，KWin 日志记录 `Input Method crashed "maliit-keyboard" ... 11 QProcess::CrashExit`。自动重启导致键盘收起又弹出，不是用户误触。尚未取得这两次崩溃的完整调用栈，因此不把所有崩溃归结为同一个源码缺陷。
- 核对 Maliit 2.3.1 及当前 master 的 `PinyinPlugin::finishedProcessing`：当已完成请求的 `word != m_nextWord` 时，又发出 `parsePredictionText(word)`，反复处理旧请求。本机也出现相同旧拼音持续生成候选的日志。旧结果竞争会影响快速输入；不能当成已完成适配。
- `PinyinAdapter::genCandidatesForCurrentSequence` 把原始/部分转换拼音先放到候选数组中。这是旧插件行为，与用户期望的中文优先不同。
- SVG 功能图标缺失是独立问题，已补齐 `libqt5svg5` 和 `qt5-image-formats-plugins`。更换后的 Qt6 键盘不再依赖这些 Qt5 图标补丁。

## 调研和选型

| 路线 | 核验结果与选择 |
|---|---|
| 修 Maliit + libpinyin | 可以修旧请求循环及候选排序，但仍需调试旧插件的选词/预编辑状态及崩溃。没有直接复用的 Rime 插件在本轮搜索中得到确认 |
| Fcitx5 + fcitx5-rime + fcitx5-osk | Fcitx5 在 KWin Wayland 下有正式入口，Rime 后端成熟；独立 OSK 使用 Rust/Iced，项目说明仍有修饰键转发问题，默认辅助程序涉及 evdev 权限。可作备选，未安装或启用 root 键盘辅助服务 |
| Plasma Keyboard + Qt 输入法扩展 + librime | 采用。复用已安装桌面键盘、布局、候选栏和语言选择器，用 Qt 公开的 `QVirtualKeyboardAbstractInputMethod` 接入发行版 Rime C API。不改 KWin，也不使用 Qt 私有 ABI |

来源：[Maliit 插件源码](https://github.com/maliit/keyboard/blob/2.3.1/plugins/pinyin/src/pinyinplugin.cpp)、[Maliit 候选生成](https://github.com/maliit/keyboard/blob/2.3.1/plugins/pinyin/src/pinyinadapter.cpp)、[Fcitx Wayland 配置](https://fcitx-im.org/wiki/Using_Fcitx_5_on_Wayland/en)、[fcitx5-osk](https://github.com/fortime/fcitx5-osk)、[Qt 输入法公开接口](https://doc.qt.io/qt-6/qvirtualkeyboardabstractinputmethod.html)、[Plasma Keyboard 6.6.6](https://invent.kde.org/plasma/plasma-keyboard/-/tree/v6.6.6)、[Rime 1.16.1 API](https://github.com/rime/librime/blob/1.16.1/src/rime_api.h)。实际源码副本在 `.work/refs/plasma-mobile-20260923/upstream/input/` 和 `upstream/maliit/`。

## 部署与数据

源码、CMake、安装脚本：[plasma/rime/](../plasma/rime)。适配代码使用 GPL-3.0-or-later；当前发行版 librime 包为 GPL-3.0-only，Qt 布局保留 GPL-3.0-only 许可，朙月拼音和 prelude 数据包为 LGPL-3，详细版权随系统包保留。

容器内依赖：

```sh
apt-get install --no-install-recommends qt6-virtualkeyboard-dev librime-dev \
    librime-bin rime-data-luna-pinyin rime-prelude rime-essay
sh /root/rime/install.sh
```

安装器只构建和安装，不自动改用户配置。此设备已设置：

```ini
# ~/.config/kwinrc
[Wayland]
InputMethod=/usr/local/share/applications/moto-plasma-rime.desktop

# ~/.config/plasmakeyboardrc
[General]
enabledLocales=zh_CN,en_US
```

包装入口仅为键盘进程设置 QML 搜索目录；其他桌面应用不受影响。布局在 `/usr/local/share/moto-rime/plasma/keyboard/layouts`，中文布局替换输入引擎，其余链接发行版布局。升级后重跑安装器；如果上游中文布局入口变化，安装器报错要求核对，避免静默用回旧引擎。`kwinrc.pre-rime` 是本轮切换前备份。会话重启后正式生效。

默认方案为 `luna_pinyin_simp`，用户词频和定制配置位于 `~/.local/share/plasma-rime/`，目录权限 0700，离线处理。`default.custom.yaml` 首次创建，此后不覆盖用户修改。隐藏密码字段不交给 Rime；敏感字段关闭词频学习。暂未预装雾凇等第三方词库，也未承诺任意方案免适配。

候选列表直接使用 Rime 顺序，不手动插入拼音候选；拼音显示在预编辑区。选词、空格、退格和标点经过同一个 Rime 会话处理，切换字段时按 Qt 的 reset/update 契约清理状态。当前候选读取上限 200 项。

## 已验收与边界

- 独立测试数据目录进行 300 次快速组合、首候选和提交测试通过（你好、中国、测试）。
- 实际触屏连续输入“你好、中国、测试、我不知道、中文、输入法”，首候选为中文，提交正确。
- 四次键盘收起再打开通过，测试期间同一个键盘 PID 持续存活。
- 切换 American English 并输入 hello，再切回简体中文通过。
- **日常 Firefox profile** 地址栏实际触屏拼音预编辑、点击“你好”提交通过；该测试没有启用 Marionette。
- 当时键盘进程 8079 连续运行，未出现新的 `Input Method crashed` 日志。这是本轮实测结果，不代表已完成长时间稳定性验证。

证据：`rime-engine-test.log`、`rime-nihao.png`、`rime-continuous.png`、`rime-language-menu.png`、`rime-english.png`、`firefox-rime-preedit.png`、`firefox-rime-committed.png`。材料位于 `.work/refs/plasma-mobile-20260923/`。

整套桌面、后端与后续验收继续记录在 [40 篇](40-plasma-mobile-integration.md)。

## 键盘前端的语言菜单与旋转修复

另发现 Plasma Keyboard 6.6.6 的 `LanguagePopup.show()` 把坐标设置为捕获旧按键对象的 `Qt.binding`。切换语言销毁旧按键后，旋转会不断访问已失效对象。核对当前主线仍有相同写法；本轮 `plasma/keyboard-popup.patch` 改为打开菜单时一次性计算坐标，在键盘尺寸变化时关闭该菜单。

使用 `plasma/build-desktop-fixes.sh` 构建独立 `/usr/local/libexec/moto-plasma-keyboard`，Rime包装入口执行此二进制。适配Rime仍只用Qt公开输入法接口；前端改动在Plasma Keyboard自己的源码中，按其GPL许可保留补丁。安装顺序需先准备这个前端，再运行 `rime/install.sh`，否则包装入口缺少可执行文件。

> 2026-09-26起由`moto-plasma-input`包安装（`/usr/lib/moto-rime`、`/usr/libexec/moto-plasma-rime`），Rime包装入口直接执行重建的`plasma-keyboard +moto1`，不再有私有的`/usr/local`副本（61篇）。

修复后再验切换语言、横竖屏、输入 `nihao`、首候选“你好”和提交，没有新的LanguagePopup失效对象日志或输入法崩溃。证据：`rime-final-nihao.png`、`rime-menu-fixed.png`。英语切换仍保留；默认中文方案仅为朙月简体拼音，未来可单独评估雾凇拼音，不在本轮未经验证替换词库。

整机重启后再次验收：点Plasma入口自动启动，默认简体中文；真实触屏`nihao`首候选“你好”，键盘PID266持续运行，无新的输入法CrashExit或LanguagePopup错误。截图`rime-after-reboot-nihao.png`。
