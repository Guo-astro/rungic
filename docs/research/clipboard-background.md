# 剪贴板后台桥重构（2026-09-29）

## 选型与接口核验（实现前）

- AOSP `android16-release` 的 ClipboardService 与 IClipboard：后台读取按包的 READ_CLIPBOARD_IN_BACKGROUND 权限、UID/包归属与 AppOps 校验；写入本来不要求焦点。默认设备的剪贴板和显示输出不是同一个概念。来源：https://android.googlesource.com/platform/frameworks/base/+/refs/heads/android16-release/services/core/java/com/android/server/clipboard/ClipboardService.java （Apache-2.0）。原始核查副本在 `.work/research/clipboard-backend/`，不进入仓库。
- scrcpy v3.3.4（Apache-2.0）：ClipboardManager wrapper 已从手写 IClipboard 反射签名迁移到 Android framework ClipboardManager；FakeContext 提供 Shell 包/归因身份，包含 Samsung service context 修正。v2.7 手写签名分支较多，维护成本更高。来源：https://github.com/Genymobile/scrcpy/tree/v3.3.4/server/src/main/java/com/genymobile/scrcpy 。仅复用架构方法，本次不复制该源码。
- 选用独立 app_process + Shell UID + framework ClipboardManager。不用普通 APK 后台 Service（不能获得后台读取权限），不用输入法占位，不引入 scrcpy 显示/控制协议。复用本项目 Magisk 控制器启动机制；业务桥仅提供有限的纯文本协议，不提供命令执行。
- G100 / portov_cn / Android 16，5038 / ZY32M9MRVP：独立 Shell 身份探针成功读取并注册 ClipboardManager 监听。仅 createPackageContext 不够：系统 Context 的 opPackage 仍为 android，触发包/UID 不匹配；需显式 ContextWrapper 与 framework 构造器。root 身份返回空不能视为权限成功；正式服务使用 UID 2000。探针失败仅在独立进程，不改系统服务。
- 桌面侧通过 Unix socket 直接连接后台服务，Klipper 保持历史职责；APK 旧接口仅转发。生命周期跟随 Linux 容器，不跟随 Activity/显示窗口。抽象 Unix socket 可达性依赖当前共享 Android 网络命名空间的 LXC 架构；客户端仍须 peer UID 验证。

## 验收计划

Android 第三方/独立测试应用在前台复制 → Linux/Klipper；Linux 历史选择 → Android 应用实际粘贴；自己应用的全屏面板；APK 后台/重建；后端进程异常退出恢复；敏感标记、非文本、清空、超长与重复；记录锁屏与用户隔离边界。研究与探针结果不代表完整验收，实测结果另记。

## 实现与设备增量部署

- `plasma/native-apk/src/com/rungic/clipboard/ClipboardDaemon.java`：通过 framework 构造器取得 Shell Context 的 ClipboardManager；系统自身处理其 Binder 签名。变化监听、解锁/切换用户事件与带 epoch 的长轮询；最多 8 个并发请求，正文上限 65536 UTF-16 单元 / 262144 UTF-8 字节；仅 user 0 且设备未锁定时交换文本。缺后台权限则服务启动失败，不降级到普通 APK 焦点访问。
- `plasma/android-clipboard`：宿主启动/停止、单实例锁、进程退出恢复；APK 路径变化后重启后端。只杀经 PID/完整主类命令核验的后端。`rungic-plasma` 挂接 start/stop，`tools/ci/build_host_seed.py` 包含脚本，代码随 APK 发布，不引入第二份 Java 构建产物。
- `shared/platform/clipboard.py`：Linux 直连抽象 Unix socket，无 APK Watch 依赖；修正初次 wl-copy 失败时过早记下 last 导致不再重试的问题。桥只交换当前值；断线重连以 Android 当前值恢复，不承诺补回断线期间每一次复制。
- `AndroidClipboardBridge`：兼容转发原 platform.sock 的读写与 HostEvents（包括混合主题），不在 UI 线程执行剪贴板操作。
- Android 2.14 / versionCode 62；本机复用 G100 原 APK 的三个 JNI 库，SHA 在实验目录 `native/SHA256SUMS`；沿用该机原先无 OCR runtime 的构建模式。未刷机、清数据或更新整套 Linux 软件包。
- 增量工具 `tools/deploy_clipboard.py --serial ... --port ... --apk ... --output .work/...` 明确指定设备，保留 APK/控制器/Linux 脚本/已有后端备份；仅给该机控制器基线插入两处生命周期 hook。**不能直接覆盖旧 G100 的完整控制器**：本轮曾用最新控制器调用旧容器 account-setup 的 `--status`，报“无效的账户信息”；恢复设备基线并只加剪贴板 hook 后正常。没有账户数据变更。
- 后台 `pm path` 的 stderr 若继承 root 日志文件，会触发已知 `Failed transaction (2147483646)`，导致发现 APK 路径失败。stdout/stderr 合并进管道后再解析；不把该错误误判为 APK 未安装。
- APK 升级会断开旧 Wayland 宿主连接。本轮重建会话时旧 kactivitymanagerd 激活失败，重启对应用户单元与 plasmashell 恢复；这是桌面重启验收的实际边界，不能只看进程 active。

## 验收证据

实验目录 `.work/experiments/g100-clipboard-background/`。只记录已知测试文字或布尔值，用户剪贴板正文不进入日志。`tools/tests/android_clipboard/` 是单独构建/临时安装的测试应用，不进入发行包。

- `android-copy.json`：独立 Android 测试 Activity 处于前台，实际点击复制中文/emoji/换行；Android、Wayland 和 Klipper 均匹配。
- `linux-copy.json`、`android-paste.json`：Linux 通过 Klipper 写入测试文本；独立 Android Activity 实际点击粘贴，内容匹配。
- `filter-tests.json`：Android sensitive / 非文本保持 Linux 原内容；敏感测试值不进 Klipper；超长、缺字段、错误类型被拒绝。
- 清空：Klipper 默认 `General/NoEmptyClipboard=true` 会主动恢复上一条，桥随后同步该值。临时关闭并调用 Klipper.reloadConfig 后 Android 清空 → Linux 清空通过；随后恢复原配置。没有清空用户历史，也没有改变该默认设置。
- `fullscreen.json`：自己的 AgentFullscreen 开启时，旧平台 status.foreground=false，但 clipboard-get 可用且匹配 Linux 选择；已退出全屏并关闭虚拟输出。
- `recovery.json`：验证主类后 kill -9 后端；宿主监控自动重启，epoch 改变，Android 当前文本恢复至 Wayland/Klipper。

G100 本次 `getenforce` 为 Enforcing，后端通过 Magisk 启动的 Shell 身份运行；其他厂商及不同域策略需分别验证。锁屏/多用户采用拒绝交换的实现，未在本轮锁屏或创建用户实测。当前协议只读 Android 系统的当前纯文本，不导入输入法私有旧历史，不同步图片/文件。手机专用历史面板的布局问题属于另一个入口任务。

## 回退

停止宿主 `android-clipboard`，恢复保存的 `controller.before` 与 `clipboard.before.py`。原始 2.8 APK 保存在实验目录顶层 `before.apk`；若 Android 不接受降级 versionCode，用原源码构建同功能更高 versionCode 的 APK，不卸载应用清除用户数据。随后启动 Rungic 并重启用户 `rungic-plasma-clipboard.service`，核验旧前台桥和桌面；保留 Klipper 数据。`final-deployment/` 另保留最终增量前的候选版本和精确部署 SHA，不能混同最初 2.8 备份。

最终复测补充：`final-core-tests.json` / `final-sync.json` 验证最终 APK 的双向同步、实际粘贴、参数边界和 UID 1001 拒绝访问；`compat-watch.json` 验证 APK 后台时旧平台接口的混合 clipboard/network Watch 能收到通知；`fullscreen-final.json` 从已有 Klipper 历史取测试条目再选择，主窗口无焦点仍同步。`sensitive-restart.json` 验证 Android 敏感内容存在时重启 Linux 桥，不会把 wl-paste 初次订阅送来的旧 Linux 文本写回 Android。后续普通复制同步仍正常。临时测试 APK 已卸载；已关闭虚拟外屏，保留用户历史与带明确标记的测试条目。

部署脚本使用完整文件加 rename 原子替换控制器/宿主脚本/Linux 桥，避免覆盖正在解释执行的 shell 文件。本轮早期直接 cp 覆盖运行中的 watcher 时出现过 `ck: inaccessible or not found` 的残缺命令日志；最终部署应采用工具内的原子替换路径。
