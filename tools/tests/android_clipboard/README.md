# 独立 Android 剪贴板验收应用

此测试应用只调用普通 ClipboardManager，运行在独立 UID；不依赖 Rungic 的剪贴板协议。
设置 `RUNGIC_ANDROID_BUILD_TOOLS`、`RUNGIC_ANDROID_JAR` 与 PATH 中的 javac，执行 `build.sh`。
产物在 `.work/tests/android-clipboard/clipboard-test.apk`，使用项目开发签名。

明确指定 ADB 端口/序列号安装，启动 `com.rungic.clipboardtest/.MainActivity`，在界面实际点击：

- Copy Android test：检查 Wayland 当前文本与 Klipper 历史均出现中文/emoji/换行。
- 在 Linux 选择文本 `Rungic 后台 Linux 📋\n历史选择`（`\n` 为真实换行），再点击 Paste and check Linux test；结果在界面和应用私有 `files/result.json`，仅保存匹配布尔值。
- Copy sensitive test / Copy non-text test：Linux 当前文本应保持不变，敏感文本不能进入 Klipper。
- Android 存在敏感条目时重启 rungic-plasma-clipboard，敏感条目不应被旧 Linux 文本覆盖。
- Clear Android：区分后端清空与 Klipper 的 NoEmptyClipboard 设置；临时关闭该设置验证后恢复，不清除用户历史。

APK 放到后台/助理屏全屏、验证服务异常恢复另见 `docs/research/clipboard-background.md`。
完成后卸载 `com.rungic.clipboardtest`。该测试应用不参与任何产品构建或 host seed。
