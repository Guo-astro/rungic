# Firefox 地址栏输入崩溃修复

2026-09-23，Alpine edge / Firefox 154.0-r0 / Phosh 0.57 / Stevia / 原生 Wayland。

本次反复崩溃的直接诱因是此前自动化验收把 `focusmanager.testmode=true` 留在日常 Firefox profile。它绕过正常窗口焦点处理，触发 Firefox 154 输入法路径中的空指针缺陷。清理后，真实屏幕键盘英文、中文候选提交和重新打开后的地址输入均通过。不是已证实的 musl、Mesa 或硬件编解码问题。

这是此前验收清理的遗漏。只验证网页脚本、视频或浏览器启动，不能代替真实屏幕键盘输入验收。前一轮桌面入口修复仍然必要，但没有覆盖本次输入崩溃。

## 证据与上游核验

- 原日常 profile 第一颗 ASCII 字母可重复触发 SIGSEGV；GDB 显示 libxul 调用 GTK `im-wayland.so` 提交回调，空指针偏移 `0xc0`，对应 `ldr x8,[x0,#192]` 且 x0=0。
- IME 日志中 `mLastFocusedWindow` 一直为空。Firefox 154 `nsFocusManager.cpp` 明确在测试模式跳过 widget focus。
- [Bug 2063818](https://bugzilla.mozilla.org/show_bug.cgi?id=2063818)及其[上游修复](https://github.com/mozilla-firefox/firefox/commit/f66ab2d39e45)针对 `IMContextWrapper::DispatchKeyEventsForCommittedCharacter` 增加焦点窗口空值保护，修复里程碑为156。新输入路径关联[Bug 2010538](https://bugzilla.mozilla.org/show_bug.cgi?id=2010538)。本机没有重编或回移此补丁；保存补丁只用于分析。
- 使用精确 `FIREFOX_154_0_RELEASE` 的 [RecommendedPreferences.sys.mjs](https://github.com/mozilla-firefox/firefox/blob/FIREFOX_154_0_RELEASE/remote/shared/RecommendedPreferences.sys.mjs)核验自动化配置写入和清理机制。退出时清理依赖本次会话记录；已被保存到 profile 的残留不会自动成为下一会话的待恢复项。
- 保持同一二进制、同一用户 profile，仅移除测试焦点开关后，屏幕键盘 `q` 即可输入；修复后日志出现有效焦点窗口。这是配置因果验证，不只是换了启动命令后偶然成功。

对应上游源码、URL、SHA256与日志在 .work/refs/firefox-input-fix-20260923（历史材料已移除）。Mozilla源码及补丁保留 MPL-2.0 许可；一次性修复脚本和验收保护脚本为本项目自写。

## 实施内容

1. 浏览器停止后备份 `~/.config/mozilla/firefox/r68efudv.default-release/prefs.js`，先去掉测试焦点设置，再复测同一输入操作。
2. 对照 Firefox 154 的115项 COMMON_PREFERENCES，清理另外94项名称和值都匹配的自动化覆盖。未匹配值、部署默认配置和策略保留；没有重建 profile 或删除书签、Cookie、密码数据库。算法不是逐字恢复某个更早的完整 profile 快照。
3. 三个当前 codec Marionette 脚本增加 `browser_automation_guard.py`：连接前检查浏览器必须显式使用 `--marionette --profile /home/linux/.cache/moto-codec-tests/firefox-profile`。普通日常浏览器运行时拒绝连接，负向验证已通过。
4. 正常浏览器不启用 Marionette/IME 调试日志；临时 GDB 虚拟包已卸载，恢复713包、APK报告1344.9MiB。全局 SELinux 保持 Enforcing。

备份仅留在设备用户私有目录 `~/.cache/moto-firefox-input/`：`prefs-before-focus-fix.js`、`prefs-before-automation-cleanup.js`。这些可能含用户设置，不加入共享产物。需要调查回退时先退出 Firefox 再检查备份差异，不应直接恢复含测试焦点开关的故障配置。

## 实机验收与边界

- ADB 注入实际触摸点击 Stevia 按键，英文 `hello` 正常显示。
- 切中文，输入 `nihao`、选择候选，地址栏提交 `你好`，删除操作也未崩溃。
- 确认 Firefox 退出对话框后，主进程消失；再由 GIO desktop 入口启动新主进程，屏幕键盘输入 `phosh.mobi`、回车，页面加载成功。
- profile 中 `focusmanager.testmode` 和 `remote.prefs.recommended.applied` 均已消失；最终进程没有 Marionette 或 MOZ_LOG 环境。

没有关闭中文输入、Wayland、GPU、浏览器沙箱或硬件编解码。此次未重新跑全部视频性能验收，也未做整机重启或长时间输入压力测试。Firefox 154 上游的空值防护补丁尚未合入本机，不能宣称已消除所有其他焦点竞态；后续发行版升级应跟踪并核验该补丁。

历史测试脚本不是日常启动器。旧归档内脚本不会自动获得此次保护，复现时应使用材料目录外层最新脚本，并始终指定独立测试 profile。
