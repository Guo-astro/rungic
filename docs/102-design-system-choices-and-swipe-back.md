# 设计系统查缺补漏：选项反馈、底部选择面板、页面横滑返回（2026-10-01）

用户指出设计系统的三处系统性不足：

1. **选项类组件没有交互反馈**：在模型页切换选项时，手指按下、抬起都没有反馈，会觉得没点上。“这一点非常重要，一定要修复。”
2. **主题的选择方式奇怪**：主题（System 等）是在列表里就地展开来选的，不如弹出一个 bottom sheet。
3. **Agent App 不能横滑返回**：用户澄清，指的是 App 自己的页面手势，不是 Android 的边缘返回。Kirigami 支持横滑返回，并且不要求从屏幕边缘开始。

标注：“源码”指核对过的上游源码；“离线”指本机渲染或测试；“实机”指 G100 S。

## 1. 选项没有反馈：`ListRow` 靠 accessory 猜能不能点

- **原因**：`ListRow` 只有设了 `accessory`（箭头或外链图标）时，才算“可交互”，才有按下状态。
  - 统计：App 的 30 个 `ListRow` 里，有 11 个可点击却没有 accessory，按下时都没有反馈：模型页和登录页的 7 个单选行、设置页的 3 个开关行，还有 1 个单独设了 `interactive: true`。
- **另一半原因**：快速点一下只有几十毫秒，即使有按下状态，也几乎看不到底色变化。
- **修复**（在设计系统里改，不在各页面打补丁）：
  - **`ChoiceRow`**：多选一的一行，自带 RadioMark，有按下状态，无障碍角色是单选按钮。`checked` 用 AbstractButton 自带的属性：`ListRow` 本身就是 AbstractButton，它的 `checked` 是 FINAL，不能重新声明。
  - **`ToggleRow`**：开关设置的一行，`checkable`，点整行就切换，发出 `switched(checked)` 信号；按下这一行时，开关的圆钮也会跟着变宽。
  - **`ListRow` 和 `NavItem`**：点击生效后，按下的底色再保持 `Theme.tapShown`（150 ms），让快速的一点也能看见。这段逻辑用 `Connections` 写，不会被使用处自己的 `onClicked` 覆盖。
  - **App**：模型页（4 处）和登录页（2 处）的单选行改用 `ChoiceRow`；设置页的 3 个开关改用 `ToggleRow`。
  - **状态总览**（Gallery）：新增 ChoiceRow、ToggleRow 两节，展示关、开、按下、禁用等状态，还有打开 ChoiceSheet 的入口。

## 2. 底部选择面板 `ChoiceSheet`

- 基于 Qt 的 `QQC2.Drawer`（`edge: Qt.BottomEdge`）：模态，有遮罩；`dragMargin: 0`，只能由 App 打开，可以往下拖来关闭。
- 外观沿用设计系统：background 底色、上角 `radiusSheet`、把手 36×4、标题用 titleSize 半粗，下面是一组 `ChoiceRow`。
- 点一项后立刻显示为选中（`pending`），过 `Theme.normal + Theme.quick` 毫秒再收起，让人看到选择已经生效；点遮罩、往下拖或按返回键，关闭时不做选择。
- 设置页的主题改用它：原来就地展开的单选列表删掉了。

## 3. 页面横滑返回 `PageStack`

- **上游核对**（源码：Kirigami 6.24.0，也就是手机上装的版本）：
  - `ColumnView::childMouseEventFilter` 拦截页面上子控件的触摸：纵向先移动超过 3 倍 `startDragDistance`，就让给页面自己滚动；横向先超过这个距离，才接管拖动；
  - 子控件设了 `keepTouchGrab` 或 `preventStealing` 时，不去抢；
  - 松手时按最后一次移动的方向吸附：往右就回到上一页（`snapToItem`）；
  - `PageRow` 在手机单列模式下，`popHiddenPages` 默认为 false，滑回去之后前一页仍保留。
- **为什么不直接用 `PageRow`**：它带着 Kirigami 的页面背景、分隔线、全局工具栏和多列导航模型，和我们设计系统的 `SettingsFrame`、`StackView` 不合。所以照它的交互规则，在设计系统里做一个。
- **`PageSwipe`**（C++，`desktop/design/pageswipe.cpp`）：
  - `setFiltersChildMouseEvents`，照 Kirigami 的规则判断：单指、横向超过 3 倍拖动距离、方向向右，并且纵向没有先超过这个距离，才开始横滑；
  - 开始后用 `grabTouchPoints` 接管触摸点，手指下的控件会收到取消，不会被当成一次点击，也不会一直停在按下状态；
  - 用信号告诉 QML 拖了多远，松手时是否仍在往右（`started`、`moved`、`released`、`cancelled`）；
  - 先重置状态再 `ungrabTouchPoints()`，避免 `touchUngrabEvent` 误发一次取消。
- **`PageStack.qml`**：
  - 用 `PageSwipe` 包住 `QQC2.StackView`：上面的页面跟着手指移动，下面的页面从左侧以 0.3 的视差回来；
  - 松手时仍在往右，就动画移出并 `pop`（Immediate）；否则弹回原位；
  - 页面切换的动画从 `Main.qml` 挪进这里作为默认值；
  - 同时响应 `StandardKey.Back` 和 Back 键。Android 右边缘的返回手势发的就是 Alt+Left（docs/46），所以它也能用了；
  - 页面仍然通过 `QQC2.StackView.view` 来 push 和 pop。
- **App**：
  - `Main.qml` 改用 `PageStack`；
  - 对话页的侧边栏只在对话页位于最上层时才能拖出，否则到了设置页往右滑，会被侧边栏抢走。

## 离线核对

- 全套离线测试通过。
- `tools/design_gallery.py local` 渲染了 ChoiceRow、ToggleRow 和 ListRow 三节，浅色、深色都有，关、开、按下、禁用都正确。
- 本机离线渲染了设置页和模型页：开关行、主题行（带箭头，点开是底部面板）、单选行都正常。
- 没有验证到的：
  - `PageSwipe` 是 C++ 组件，离线渲染时没有加载它（Gallery 不用 `PageStack`）；
  - 横滑手势、ChoiceSheet 的弹出和拖动关闭，都要在手机上实际操作。

## 实机（G100 S，2026-10-01）

- **部署**：用开发覆盖装上 `rungic-design` 和 `rungic-voice-agent` `0.514+dev20260930t173719.ae93be3.dirty`，基线是发布 20260930.10。apt 核对通过；plasmashell、语音浮层和语音服务都在 01:42（手机时区）重启过，处于 active。Mac mini 上的构建通过了 qmlcachegen 对新 QML 的编译。
- **状态总览**（`tools/design_gallery.py phone`，offscreen）：ChoiceRow、ToggleRow 两节在浅色、深色下，关、开、按下、禁用都正确（`.work/verify/20261001-choice-rows/`）。
- **用户实测**（2026-10-01）：选项的按下反馈、主题的底部面板、设置页的横滑返回、侧边栏，用户试过都没有问题。以下是当时列出请用户确认的项目：
  - 在模型页和登录页点选项时的按下反馈；
  - 设置里点“主题”弹出底部面板：选中后稍停再收起；往下拖和点遮罩都能关闭；
  - 在设置的各个页面任意位置往右横滑返回：跟手、松手判断，纵向滚动不受影响；
  - 右边缘的返回手势（Alt+Left）能返回上一页；
  - 对话页的侧边栏仍能拖出，到了设置页则不会被拖出来。

## 设计稿（2026-10-01）

- 设计稿「Agent · App 设计」v15 的「基础」页已补上新组件，浅色、深色两块组件画板都有：
  - 选择一节：ChoiceRow、ToggleRow 各 6 种状态（关、开、按下时关、按下时开、禁用时关、禁用时开）；列表组示例换成模型页的一组 ChoiceRow 和设置页的一组 ToggleRow；
  - 新增「页面与面板」一节：PageStack 横滑返回（停在第二页、滑到 40%、滑到 80%）和 ChoiceSheet（刚打开、刚选中）；
  - ListRow 和 NavItem 的说明写上了 `tapShown`；「尺寸与动效」画板的动效一栏加了 `tapShown` 150 ms。
- 数值和文案取自 `desktop/design/qml` 和 zh_CN 翻译；本机渲染截图核对过（离线）。横滑示意中的手指圆点和箭头只是标注。

## 2026-10-03：底部选择面板打开时，手机的返回手势不起作用（已修，离线验证）

- **发现**：离线测试 `tools/tests/test_design_system.py`（PySide6，非实机）对打开的 ChoiceSheet 发 Alt+Left（安卓右边缘返回手势在 Linux 里就是它，docs/46），面板不关。
- **原因**：QQC2 Drawer 只在 Escape 时关闭（Back 键只在 Android 构建的 Qt 里处理）；面板是模态的，页面 PageStack 的 Back 快捷键在它打开时也不触发。上文“按返回键关闭”实际上只对 Escape 成立。
- **修复**：ChoiceSheet 自带一个 `StandardKey.Back` 的 Shortcut，只在打开时启用，触发时关闭面板且不做选择。修复前该测试失败，修复后通过；实机尚未复核。
- **另记**：这一版 Qt 的 `StandardKey.Back` 已包含 Back 键（还有 Alt+Left、Backspace），PageStack 的 `sequences: [StandardKey.Back, "Back"]` 把 Back 注册了两次，Back 键因歧义不起作用；手机不会发 Back 键，暂未改。页面外的 Backspace 也会返回上一页。
