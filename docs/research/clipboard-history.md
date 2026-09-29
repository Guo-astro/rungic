# Plasma 剪贴板历史入口核查（2026-09-29）

## 结论与当前证据

复用 KDE Klipper 作为唯一历史管理器，现有 Android ↔ Wayland 文本桥保持同步职责。无需新增历史数据库，也不需要逐个应用适配。本文前半为初始调查；用户随后授权实测并要求桌面右下角托盘入口，后续实现与部署见末尾。

- 源码：`shared/platform/clipboard.py` 只同步当前纯文本，不存历史；APK `PlatformBridge` 通过 `getPrimaryClip().getItemAt(0).getText()` 读取当前条目，要求 Activity 有焦点，跳过敏感标记及超长文本。
- X70 镜像基线：Plasma Mobile 6.6.5、plasma-workspace/libklipper6 6.6.6；包含 `org.kde.plasma.clipboard.so` 与 QML `KlipperPopup`、`ClipboardMenu`、`HistoryModel`。外屏默认布局包含 systemtray。镜像包含组件不等于当前用户已加载它。
- 当前 ADB 5037/5038 均没有 X70；未对其他手机执行写操作。在线 G100 S（mumba，5037 的明确 Wi-Fi serial）只读确认 `rungic-plasma-clipboard.service`、plasmashell active，`org.kde.klipper /klipper` 存在，历史接口返回 1 条。只输出数量，未输出或存储正文。此证据不能推广为 X70 运行验收。
- 用户指出应核验当前 USB G100 后，确认 ADB 5038 / `ZY32M9MRVP` 为 portov / XT2533-4，固件 `W1VT36H.1-51-8`，当前 APK 2.8/56。普通 ADB 正常，但 `su -c id` 与 root stdin 脚本均返回 `Permission denied`（退出 13），因此暂不能查询该机容器用户 D-Bus；不能把 G100 S 的运行结果当作此 G100 已验。连接正常与 Magisk Shell 授权是不同检查项，授权恢复后继续查服务及入口。
- 上游 Mobile 6.6.5 源码树中没有独立 clipboard/klipper 快捷设置；当前项目也未提供这种手机触屏入口。外屏托盘、手机桌面小部件的实际可见性仍需按用户布局实测。

## 已有入口与推荐改动

现有 Klipper 提供 D-Bus `org.kde.klipper.klipper.showKlipperPopupMenu()`；对应容器用户会话命令：

```sh
qdbus6 org.kde.klipper /klipper org.kde.klipper.klipper.showKlipperPopupMenu
```

上游默认 Meta+V 也打开此菜单；外接键盘实际映射与用户覆盖设置另验。桌面模式可从系统托盘剪贴板图标打开历史，隐藏项中是否可见取决于布局与托盘配置。

优先在手机下拉快捷设置增加“剪贴板”入口，调用现有 Klipper 弹窗，先检验触摸尺寸、焦点、关闭抽屉后的时序，以及手机/电视上正确的目标输出。Klipper 默认弹窗按鼠标位置出现，不能假定从手机点击必然出现在手机。如果原生弹窗不满足触屏需求，再复用同一 HistoryModel/ClipboardMenu 制作适合手机的页面。该 QML 模块位于 `private` 命名空间，不是稳定公共 API，需要随固定 Plasma 版本回归；直接 D-Bus 打开现有 UI 的维护成本更小。

如果某会话没有 org.kde.klipper，应先定位标准 applet/会话加载情况并确保单实例，不以另造历史守护进程掩盖问题。上游 6.6.6 默认 MaxClipItems=20、KeepClipboardContents=true、IgnoreImages=true；这些是上游默认，不代表每台设备的用户实际设置。入口应尊重已有配置。

选择历史项由 Klipper 更新当前 Wayland 剪贴板，现有桥在前台条件满足时负责同步 Android。它不会自动向当前应用输入文字，用户仍在目标应用执行粘贴。清空历史与清空当前条目是不同接口，需要分别验收，不承诺能清掉 Android 输入法自己的历史。

## 历史范围

Klipper 可以记录它实际收到的 Linux 复制内容，以及 Android 桥成功同步过来的内容。Android 连续复制 A/B/C 后才切回 Linux，现有桥只能得到 C，不能补回 A/B；输入法维护的历史也未接入。Android 公共 ClipboardManager 文档定义的是当前 primary clip，并限制无焦点且非默认输入法应用读取；不提供输入法历史列表导出接口。

因此第一阶段应准确称为“Linux 与已同步内容的剪贴板历史”。如果目标进一步要求 Android 后台每一次复制都保存，必须另行研究获授权的后台采集、生命周期与敏感内容过滤，不能把增加 Klipper 入口当作已经完成。保持当前敏感标记过滤，不在日志中记录正文。

## 后续验收

以连接的目标设备为准：先只读检查同步服务、org.kde.klipper、配置及历史数量；使用明确的测试文本验证两个独立 Linux 应用复制、Android 复制后切回 Linux、历史项选择后两边粘贴、去重与清空。再验证新账户、会话重启、锁屏/后台过滤，以及手机和投屏双屏的弹窗位置。已有用户历史不得被测试清空。当前未进行这些写入验收。

### G100 授权恢复后的实际核验

用户开启 Magisk Shell 后，5038 / ZY32M9MRVP 上 root 恢复。同步服务与 plasmashell 均 active，但 `org.kde.klipper` 不存在，说明不能只检查桥接服务就认定历史正在记录。已安装 workspace/libklipper6 6.6.6、Mobile 6.6.5+rungic2、clipboard applet 和 `plasmawindowed`，没有独立 `klipper` 可执行文件。

用临时用户单元 `rungic-clipboard-preview.service` 运行 `plasmawindowed org.kde.plasma.clipboard`，并将现有 Rungic Activity 切到前台后，Klipper D-Bus 出现，窗口管理器确认 Clipboard 窗口在 WL-0 激活；截图实际显示搜索栏与 “Clipboard is empty”，历史数量为 0。没有写入测试文本或清空历史。窗口暂留供用户查看，未配置开机自启；这只是现成组件显示验证，关闭此唯一承载进程后不能假定历史后台仍运行。证据 `g100-preview.txt`、`g100-clipboard.png` 在上述研究目录。

据此修正实施优先级：先补齐各 Mobile 会话中历史管理器的可靠加载与单实例生命周期，再做触屏入口。默认手机布局没有加载 Klipper 的实际缺口已经在 G100 证实；G100 S 的已运行状态不能替代这项首装检查。后续需比较常驻 clipboard applet 与独立 Klipper 包的会话集成，检查投屏新增托盘时不产生两个历史实例；本轮没有完成该选型或修改启动配置。

## 来源、版本与许可证

- [Plasma Mobile v6.6.5](https://github.com/KDE/plasma-mobile/tree/v6.6.5)，本地配方 `packages/plasma-mobile/recipe.json`；布局文件 SPDX GPL-2.0-or-later。
- [Klipper v6.6.6 实现](https://github.com/KDE/plasma-workspace/blob/v6.6.6/klipper/klipper.cpp)、[默认配置](https://github.com/KDE/plasma-workspace/blob/v6.6.6/klipper/klipper.kcfg)。已核对固定版本源码；镜像 QML ClipboardMenu/KlipperPopup 标记 GPL-2.0-or-later，本轮不复制上游实现。
- [KDE 使用手册](https://docs.kde.org/trunk_kf6/en/plasma-workspace/klipper/using-klipper.html)：托盘历史入口。手册为滚动版本，具体行为以固定源码为准。
- [Android ClipboardManager](https://developer.android.com/reference/android/content/ClipboardManager)、[复制粘贴文档](https://developer.android.com/develop/ui/views/touch-and-input/copy-paste)：当前条目及访问范围。
- 下载源码与只读设备结果：`.work/research/clipboard-history-20260929/`；X70 镜像核查路径：`.work/ci/runs/vantage-20260928-onboarding/rootfs/base/`。

## 实现与 G100 实测

用户要求先实测，并通过桌面右下角托盘直接打开历史。按传统外屏桌面完成入口，不在手机导航栏挤入第二套系统托盘。手机本地历史后台同样常驻；专用触屏入口尚未新增。

### 选型及补丁

- 核对 workspace v6.6.6 的 `klipper/declarative/klipperinterface.cpp`：KlipperInterface 持有 `Klipper::self()` 的 shared_ptr，后者是进程内弱引用单例。Mobile taskpanel 实例化同一 QML 接口，与外屏托盘共用 plasmashell 内的 Klipper，不启动第二个独立历史进程。关闭外屏后手机 taskpanel 仍保留该实例。
- 独立 `plasmawindowed` 适合初次演示，但它在另外的进程里创建 Klipper，不能作为与托盘并存的常驻方案。本轮已停止该临时进程。当前选择不需要修改 workspace，也不复制其历史存储逻辑；私有 QML 接口随 workspace 固定版本检查。
- `external-desktop.js` 为新旧桌面托盘启用 clipboard applet，加入 shownItems，从 hiddenItems 移除；按托盘记录一次迁移标记，用户后续更改显隐不应被每次接屏覆盖。保留原有其他托盘项及远端刚更新的通知去重逻辑。
- 通过 `tools/pq.py prepare/export` 维护补丁，plasma-mobile 升至 `6.6.5-0ubuntu0.1+rungic6`。补丁位于 `packages/plasma-mobile/debian/patches/rungic/0014-Keep-clipboard-history-alive-and-show-its-desktop-tr.patch`。

### 部署范围

G100 / portov / ADB 5038 / ZY32M9MRVP，APK 仍是 2.8/56。Mac mini 沿现有系统代理构建，使用 `tools/build_on_device.py` 增量构建并 collect 包；编译/打包成功。构建日志末尾 `dpkg-genchanges` 因缺 `.dsc` 失败，因此不称为完整 source changes 产物成功；实际 `.deb` 已生成、收集、安装，`apt-get check` 和 `dpkg --audit` 通过。

只更新 plasma-mobile 与 tweaks 至 rungic6。为保持原 release 的精确依赖一致，调用已有 `rungic_release.build_meta` 基于设备原始 `20260928.1` 清单生成 `20260928.1+clipboard1`；其他包版本保持一致。清单明确是此机增量实验，带补丁哈希及 dirty 标记，不是全镜像新发行/清数据验收。更新前设备与原清单无版本漂移，原 deb 在 `.work/apt/repo/` 保留，可连同旧 metapackage 回退。仅重启 plasmashell，未重启手机/容器，未刷写。

### 验证结果及边界

证据目录 `.work/experiments/g100-clipboard-20260929/`：

| 场景 | 实际结果 |
| --- | --- |
| 连续复制普通文字 | A（中文、emoji）、B（换行）通过 wl-copy 写入，均进入 Klipper，Android 当前文字与之匹配 |
| Android → Linux | 经现有 APK clipboard-set 接口设置 C，wl-paste 与 Klipper 历史均收到；这是接口实测，未冒充 Android 第三方应用 GUI 复制验收 |
| 重复项 | 再设置相同 C 未增加重复记录；A/B/C 同时保留 |
| 历史选择 | 初次历史 UI 点击 A 后，Wayland 与 Android 均读回 A（异步等待后）；新常驻实例通过 Klipper 接口选择 A 后，实际点击 GTK TextView 的粘贴按钮，编辑器内容匹配 A |
| 独立应用复制 | 实际点击 GTK 编辑器复制 E，Wayland、Klipper、Android 均匹配；与 wl-clipboard 和 Qt 历史 UI 交叉核验 |
| 常驻与持久化 | 没有历史窗口/外屏时复制 F 仍入历史；再次重启 plasmashell 后新 PID 17517 持有 org.kde.klipper，A/F 仍在，共 5 条；桥服务 active |
| 托盘 | 用此机现有助理屏建立 1920×1080 的 CAST-1，实际点击右下角图标显示完整历史、搜索框，弹窗在屏幕内；见 `tray-landscape.png`。两次运行布局脚本均 unchanged |
| 收尾 | 关闭 GTK 实验进程、临时 plasmawindowed，助理屏/fullscreen 恢复关闭；手机回到正常 Linux。保留 5 条明确标记的测试文字供查看，没有清空用户历史 |

早期 GTK 自动脚本的粘贴结果不匹配，程序性复制 D 也未成为历史；这些没有计为通过。换成真实按钮输入、明确选中 A 并等待同步后，实际 GTK 粘贴通过，见 `gtk-final-paste.txt`，不据此宣称已经确定所有旧脚本失败的唯一原因。

**仍存在的限制：**

1. 直接 D-Bus 调 Klipper 通用弹窗在手机竖屏时出现越界，未作为手机产品入口交付；桌面托盘使用自己的定位，实测不越界。
2. APK 2.8 的助理屏全屏模式中 `clipboard-get` 返回 available=false，因为当前桥要求 Activity 窗口焦点；其间选中的 Linux 条目不能据此承诺同步到 Android，退出全屏后也不能假设未同步选择优先于 Android 当前值。本轮没有修改 APK 的焦点策略。普通 Rungic 前台双向同步与此分别验收。
3. G100 无已部署的 root WFD helper，本次托盘测试是虚拟外屏桌面，未连接物理电视；没有给 X70 或 G100 S 部署。
4. 上游默认保留 20 项并持久化，本次尊重默认/用户配置；不是 Android 输入法旧历史的导入，也不新增后台读取 Android 的权限。
