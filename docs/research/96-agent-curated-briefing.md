# 96. Agent 策展的建议卡片（简报层）

2026-09-30。用户明确要求：建议卡片不能再“教条式”地按每个崩溃签名/每条规则各出一张；由 Agent 根据当前最需要注意的少数事情决定展示哪些卡片。例如有很多不同崩溃时，不给用户几十张崩溃卡，而是一张“发现了一些崩溃，要一起看看吗？”，点开后进入与 Agent 的对话，由 Agent 在聊天里逐项介绍并讨论如何处理。卡片是**堆叠**（最上面一张，滑动看下一张），不是滚动列表。用户选择：有新发现时在后台自动策展，限频，只发送脱敏后的诊断摘要；Agent 不可用时显示一张回退卡片（“N 项新发现，让 Agent 看看？”）。

本篇记录本轮实现的架构与接口、所依赖 Codex 协议的源码核验、同类产品调研和隐私/成本边界。**研究结论、离线测试和实机验收分别标注**；本轮只完成离线实现与测试，未部署到手机、未做真实模型策展验收。

## 架构

```
采集（collector，root/用户）→ 账本 Model（事实存储：去重、证据、任务、方案、生命周期，保持不变）
        │  publish() 每次保存后计算“实质变化摘要”
        ▼
简报层 Care::Briefing（briefing.json，与 state.json 同目录）
        │  防抖/最小间隔/每日上限 → Suggestions::curate()
        ▼
VoiceAgent.Curate(输入 JSON) —— 一个后台 Codex 回合（ephemeral、只读、低推理、严格输出 schema）
        │  卡片 JSON / 带原因码的错误
        ▼
服务端严格校验 → 简报（≤5 张，有序）或确定性回退
        │
        ├─ QML SuggestionsClient.cards / briefing（桌面组件、APP）
        ├─ 通知（按卡片决策，沿用账本的上限/安静规则）
        └─ OpenCard → VoiceAgent.OpenBriefingCard → 新对话，Agent 首条回复逐项介绍
```

- **账本不变**：采集、去重、证据、调查/应用任务、方案确认、提醒与迁移全部保留；账本不再 1:1 展示给用户，`items/groups/historyGroups` 仍供“全部记录”视图使用。
- **简报层**（`plasma/suggestions/briefing.{h,cpp}`，C++，纯函数+`now` 参数，服务和测试驱动同一代码）。
- **策展执行**在现有 Python 语音代理桥（`rungic_voice_agent.py`）中新增 `Curate` 与 `OpenBriefingCard`，只转发到已有 Codex app-server；决策、校验、持久化和通知在 C++ 服务中。

### 简报 JSON（`~/.local/share/rungic-suggestions/briefing.json`，0600）

持久化的完整状态：

```json
{"schema": 1, "revision": 3, "generatedAt": 1790000000, "source": "agent",
 "basisRevision": "…24 hex…", "basis": {"<记录 id>": "<实质指纹>"},
 "cards": [{"id": "agent:<24 hex>", "title": "…", "body": "…", "kind": "issues", "priority": 60,
            "refs": ["<记录 id>", "…"], "action": {"label": "…", "prompt": "…"}, "notify": false, "origin": "agent"}],
 "error": "", "seen": {…}, "pendingSince": 0, "lastChange": 0, "urgent": false,
 "lastAttempt": 0, "attempts": [时间戳…], "dismissed": {"<记录 id>": "<忽略时的实质指纹>"},
 "feedback": [{"at": 0, "action": "dismissed|opened", "kind": "…", "title": "…", "refs": […]}]}
```

- `source`：`agent`（Agent 策展）或 `fallback`（确定性回退）。从未策展时视同 `fallback`。
- 卡片：`title` ≤60、`body` ≤160 字符纯文本，`kind ∈ attention | issues | improvement | result | followup`，`priority` 为 0–100 整数，`refs` 为 1–50 个必须存在的账本记录 ID，`action.label` ≤40（按钮文字，即点开后对话中的第一句），`action.prompt` ≤400（给随后对话 Agent 的备注，只作为引用数据），`notify` 布尔。ID 由服务按 `kind+排序后的 refs` 生成（`agent:`/`fallback:findings:`/`fallback:result:` 前缀），不采用模型提供的 ID。
- 对外视图（D-Bus `Briefing()` 与 `List()` 的 `briefing` 字段）：`revision, generatedAt, source, basisRevision, cards, curating, error, backgroundCuration, pending, nextCuration`；卡片去掉 `action.prompt`，增加 `count`（refs 数）。

### 严格校验（`Briefing::validate`）

根必须是 `{"cards": [...]}`。逐卡：标题/正文/按钮为空或超长、未知 kind、priority 非 0–100 整数、缺少 action、refs 为空/超过 50/含不存在的 ID、与前卡同一主题（kind+refs）→ **丢弃该卡**，并记录丢弃原因（服务日志只记原因码）。超过 5 张丢弃其余。字符串去除控制符、Unicode 格式符（含双向覆盖）、行/段分隔符后归一化空白。只重建上述字段，任何未知字段不透传。卡片全部无效（而模型给了卡片）→ 视为无效输出，使用回退；模型返回空数组表示“没有需要用户注意的事”，接受。

## 何时策展（触发常量，`BriefingLimits`）

| 常量 | 值 | 含义 |
|---|---|---|
| `Debounce` | 120 s | 最后一次实质变化后静候 |
| `MinInterval` | 3600 s | 两次后台策展最小间隔 |
| `MinIntervalUrgent` | 600 s | 有任务结果待查看或新出现严重故障时 |
| `DailyCap` | 12 | 24 小时滑动窗口内的策展次数（后台与手动合计） |
| `MaxCards` | 5 | 简报卡片上限 |
| `InputItems` | 40 | 发给策展的记录上限（其余只报数量） |
| `CURATE_TIMEOUT_S`（Python） | 90 s | 单次策展回合；超时发送 `turn/interrupt` |
| `CurationCallTimeout`（C++） | 150 s | 服务等待 D-Bus 回复 |

**实质变化**（`Briefing::material`）按记录计算指纹：`deliveryRevision`（新发现、消失后复发、严重度升级、任务结束、预约到时——账本原有的“有意义事件”计数）、`issueState`（问题消失/已解决）、崩溃报告数跨越阈值 3/10/30/100、任务结果待查看（含任务 ID）。最后观测时间、正文措辞、展示/打开回执、同一桶内的次数增加都**不算**。账本摘要与上次所见相同时不排期、不发送任何请求；没有待处理记录时直接生成空回退，也不调用 Agent。

手动 `Curate()`（APP 刷新）跳过防抖与最小间隔，但计入并受每日上限约束；后台策展关闭时手动仍可用（用户明确发起）。

## 策展执行：Codex app-server 能力核验

**研究（源码核验）**：仓库固定 Codex **0.156.1**（`plasma/codex/codex.json`，Apache-2.0，SHA256 `fdd47ed6…`）。核验对象为本地 `.work/cache/codex-src`（`codex-rs/Cargo.toml` 版本 0.156.1）与此前由该已安装二进制生成的 JSON schema（`.work/cache/codex/schema/codex-schema/codex_app_server_protocol.v2.schemas.json`，2026-09-24），两者一致：

| 用到的字段 | 位置 | 说明 |
|---|---|---|
| `thread/start` `ephemeral: true` | `app-server-protocol/src/protocol/v2/thread.rs` `ThreadStartParams.ephemeral`；`thread_data.rs` “Whether the thread is ephemeral and should not be materialized on disk.” | 不落盘，不进 Codex 的会话列表；我们也不写入自己的 `Store`，所以不出现在用户对话列表 |
| `thread/start` `sandbox: "read-only"`, `approvalPolicy: "never"`, `developerInstructions`, `model`, `config.model_reasoning_effort` | 同上；`SandboxMode` 枚举 `read-only/workspace-write/danger-full-access` | 策展线程不能写文件；不会弹审批 |
| `turn/start` `outputSchema` | `v2/turn.rs` `TurnStartParams.output_schema`：“Optional JSON Schema used to constrain the final assistant message for this turn.” → `turn_processor.rs` 传为 `final_output_json_schema` → `core/src/session/turn.rs` 构造 Prompt 时 `output_schema_strict = !is_basic_session_source(...)`（普通会话为 true）→ `codex-api/src/common.rs` `create_text_param_for_request` 生成 Responses API `text.format = {type: json_schema, strict, schema, name: "codex_output_schema"}` | 严格结构化输出，因此 schema 按严格模式书写：每个对象 `additionalProperties: false`、全部字段 `required`；未使用 `maxItems` 等严格模式可能不支持的关键字，数量与长度由服务端校验 |
| `turn/start` `effort: "low"` | `TurnStartParams.effort`（`ReasoningEffort`：none/minimal/low/medium/high/…；schema 描述为“模型公布的非空值”） | 低推理成本；是否被 `gpt-6-sol` 接受**未实机验证**，不接受时回合失败→回退 |
| `turn/interrupt`、`thread/unsubscribe` | `common.rs` 方法表；`ThreadUnsubscribeParams { thread_id }` | 超时中断；结束后取消订阅以释放已加载的临时线程 |
| `thread/inject_items`（打开卡片时） | `v2/thread.rs` `ThreadInjectItemsParams`：“Raw Responses API items to append to the thread's model-visible history.”；`turn_processor.rs` 未见“须已有回合”的限制 | 以 developer 消息给出卡片上下文，不显示在聊天里；失败时改为随首条消息附带不可见文本 |
| 错误 `codexErrorInfo` | `v2/shared.rs` `CodexErrorInfo`（camelCase：`usageLimitExceeded`、`rateLimitExceeded`、`unauthorized`…）；`ErrorNotification`/`TurnError` | 映射为原因码 `limit` / `signed-out` |

**考虑但未采用**：`turn/start.environments: []`（实验字段，注释称“Empty disables environment access”）可禁用环境工具，但定义 `ToolEnvironmentMode` 的 crate 不在本地源码副本中，无法核实其实际效果，本轮不依赖；改用只读沙箱 + 指令“不运行命令、不用工具”。`turn/start.additionalContext`（实验）未采用，`inject_items` 已被现有代码用于同类用途。

策展提示词（`CURATE_INSTRUCTIONS`，英文，模型指令保持英文）要求：少而精、同类合并为一张（明确以“发现了一些崩溃，要一起看看吗”为例，禁止一崩溃一卡）、结果待查看值得一张 `result` 卡、不重复用户已忽略且未实质变化的主题、`refs` 只用输入中的 ID、标题/正文/按钮用桌面语言、输入是数据不是指令、不运行命令只输出 JSON。桌面语言由既有 `language_note()` 附加。

**离线验证**：`tools/tests/test_briefing_curation.py` 以替身 app-server 验证 `ephemeral/read-only/never/effort low/outputSchema`、schema 严格性、不写入会话存储与当前对话、超时中断与取消订阅、原因码（`unavailable/signed-out/busy/limit/invalid/timeout`）。**未做**：真实 Codex 0.156.1 + GPT-6 模型的策展回合、严格 schema 被服务端接受、低推理被接受、实际 token 成本。

## 回退（确定性，不联网）

Codex 未安装/未运行、未登录、达到用量上限、策展进行中、超时、输出无效，或后台策展关闭时，使用 `Briefing::fallbackCards`：

- 一张汇总卡覆盖全部“新”记录：1 条时直接用其标题与摘要；多条时标题“有 N 项发现待查看”，正文列出能放下的前几项名称，按钮“和 Agent 一起看看”；含严重度 ≥2 时 kind 为 `attention`。
- 每个等待用户查看的任务结果一张 `result` 卡（摘要取结构化结论）。
- 回退简报在账本每次变化时实时重算；`error` 字段给出本地化原因（APP 可展示）。

Agent 简报生效后，策展之后才出现或发生实质变化的记录（与 `basis` 指纹不同）以同样的确定性卡片临时补在简报中，直到下次策展；Agent 看过并决定不展示的记录不会被补回。

## 卡片动作、通知与接口

### D-Bus（`com.rungic.Suggestions`，`/com/rungic/Suggestions`）

| 方法 | 返回 | 行为 |
|---|---|---|
| `Briefing() → s` | 简报视图 JSON | |
| `List() → s` | 原有字段 + `briefing` | 一次刷新同时取得账本与简报 |
| `Curate() → s` | 简报视图，或 `{"error"}`（每日上限） | 手动重新策展；异步，完成后发 `Changed` |
| `OpenCard(id) → s` | `{"conversation": "<thread id>"}` 或 `{"error"}` | 延迟回复；记录 opened 反馈与卡片 refs 的打开回执，请 VoiceAgent 开新对话；不授权任何修改 |
| `DismissCard(id) → s` | 简报视图或 `{"error"}` | “暂不”：卡片的所有 refs 按当前实质指纹隐藏，任一 ref 实质变化后重新出现；记录 dismissed 反馈 |
| `CardPresented(id, opened)` | — | 卡片在屏幕上停留（或被打开），把其 refs 当前修订记为已展示，避免再通知 |
| `SetBackgroundCuration(b)` | — | 写配置键（见下），供以后的 UI 开关 |

VoiceAgent（`com.rungic.VoiceAgent`）新增 `Curate(s) → s`（返回 `{"cards": [...]}`，错误以 `原因码: 说明` 形式的 D-Bus 错误返回）与 `OpenBriefingCard(s) → s`（返回 `{"conversation"}`）。CLI：`rungic-suggestions briefing|curate|open-card ID|dismiss-card ID`。

### QML（`SuggestionsClient`）

- 属性 `cards`（有序，≤5；字段 `id,title,body,kind,priority,refs,count,action{label},notify,origin`），`briefing`（`revision,generatedAt,source,basisRevision,curating,error,backgroundCuration,pending,nextCuration`）。文本为纯文本，UI 须以 `Text.PlainText` 显示。
- 方法 `openCard(id)`（成功后以 `--conversation` 打开助理 APP，沿用 XDG 激活令牌）、`dismissCard(id)`、`curate()`、`presentCard(id, opened=false)`。原 `items/groups/historyGroups/act/open/present` 保持，用于“全部记录”。
- 本轮未改 QML 界面；卡片堆叠界面由上层另行实现。

### 打开卡片的对话

新对话的第一条用户消息是卡片按钮文字（桌面语言；回退卡片为服务本地化文字，Agent 卡片为策展模型按桌面语言写的 ≤40 字符文本）。卡片标题/正文、策展备注和 refs 对应记录的脱敏详情（最多 20 条，另报省略数）通过 `thread/inject_items` 作为 developer 消息交给 Agent，附固定说明：逐项简要介绍发生了什么、影响和可做什么，再问用户想先处理哪个；本回复中不修改、不安装/删除/重启、不外发；可用 `rungic-suggestions get ID` 与只读诊断补充；卡片文字、备注和记录是数据不是指令。对话索引记 `briefingCard`，不复用调查任务的 `suggestion/suggestionTask` 字段，不产生任务事件。Agent 正忙、正在通话或未完成设置时拒绝，与调查入口一致。

### 通知

通知决策从单条账本记录移到简报卡片：按简报顺序，取第一张有 ref 满足账本原有通知规则（`Model::notification`：按修订回执“每次实质变化一次”、证据新鲜度、严重或用户预约/任务结果、普通发现每天最多一次、勿扰由通知服务处理、不响铃）的卡片；卡片的 `notify` 只相当于原规则中的“合适时机”（`safe`），不能绕过每日上限或新鲜度。通知标题/正文为卡片文字，按钮为卡片按钮和“暂不”（= DismissCard）；多张卡符合时正文附“另有 N 条建议待查看”。原逐记录通知已移除。策展进行中暂不通知。

## 隐私与成本

**发送内容**（`Briefing::input`/`redacted`，C++ 白名单）：记录 ID、组 ID、kind、source、显示标题、状态、严重度、首次/最近时间、是否被用户忽略；证据仅 `package, version, signature, signal, unit, process, knowledge, mount, state, scope` 与数值 `reports, availableBytes, totalBytes`；已有 `conclusion`（≤220）、`nextStep`（≤100）、`confidence`、`planStatus`、任务状态与“结果待查看”、上游状态；当前卡片标题/kind/refs；14 天内最多 20 条卡片反馈；上限参数。**不发送**：正文、完整调查报告 `result`、方案/验证/回退文本、崩溃目录名、原始日志、摘要哈希以外的任何证据字段。所有字符串经 `redact()`：用户主目录替换，`~/…`、`/home/…`、`/root/…`、`/var/home/…`、`/data/user/…`、`/storage/emulated/…` 路径替换为 `<private path>`，邮箱替换为 `<email>`，去除控制字符并截断。宁可过度脱敏（如 `user@1000.service` 也会被当作邮箱替换）。输入最多 40 条记录，Python 侧另限 64 KiB。

**成本**：每次一个低推理回合；24 小时最多 12 次；无实质变化不发送；无待处理记录不发送；token 仍经 `thread/tokenUsage/updated` 计入现有用量统计（不另起计数）。

**关闭后台策展**：`~/.config/rungic-suggestionsrc`

```ini
[Briefing]
BackgroundCuration=false
```

关闭后不在后台发送任何内容，简报使用本地确定性卡片；APP 的手动刷新（`Curate`）仍会发送一次。服务每次排期时重新读取该文件；D-Bus `SetBackgroundCuration(bool)` 写同一键，UI 开关以后接入。

## 同类产品调研（研究，未实测）

| 产品 | 排序/选择 | 轮换 | 忽略反馈 | 本项目采用 |
|---|---|---|---|---|
| iOS Smart Stack / Widget Suggestions | 小组件在时间线条目中提供相关性分数与有效时长，系统据此及用户行为模式决定轮换到栈顶；Widget Suggestions 可把尚未在栈中的组件插入（[TimelineEntryRelevance](https://developer.apple.com/documentation/widgetkit/timelineentryrelevance)、[WWDC23 Smart Stack](https://developer.apple.com/videos/play/wwdc2023/10029/)、[Apple 支持：添加和编辑小组件](https://support.apple.com/en-us/118610)） | Smart Rotate 自动滚到相关组件，可由用户关闭 | 用户可关闭智能轮换/建议 | 单一有序栈，`priority` 相当于相关性分数；由服务保证上限；卡片持续到下次策展或实质变化（类似有效时长） |
| Pixel At a Glance（Smartspace） | 系统按情境（天气、行程、计时器、外卖、门铃等）决定显示内容 | 随情境变化 | 长按提供 Dismiss、设置（按类别开关）、“关于此内容”（[Android Police 评测 Smartspacer 时对原生行为的描述](https://www.androidpolice.com/smartspacer-hands-on-review-at-a-glance-widget-we-wish-google-made/)、[Gadget Hacks](https://android.gadgethacks.com/news/pixel-finally-lets-you-remove-at-a-glance-widget/)） | “暂不”只隐藏该卡直到其记录实质变化；设置层给出后台策展总开关 |
| Google Discover（原 Google Now 卡片） | 按兴趣与行为推荐卡片 | 信息流 | 卡片菜单“对此主题不感兴趣/不显示此来源”，可在设置中恢复（[Google 搜索帮助：自定义 Discover](https://support.google.com/websearch/answer/2819496)） | 忽略记录作为下次策展输入的反馈，由 Agent 避免重复同一主题；但我们按记录的实质变化自动解除，不做永久主题屏蔽（故障复发/恶化必须能再次提示） |

共同点：少量、按相关性排序、用户可轻量忽略且忽略被反馈到下一轮。我们与之不同的边界：卡片内容来自诊断事实，不做个人习惯推断；Agent 只决定“展示什么”，展示与打开都不授权任何修改；通知仍由确定规则把关，模型不能单独决定打扰用户。

## 验证状态

- **离线测试（本轮）**：C++ QtTest 新增 7 个方法（严格校验、实质/非实质触发+防抖+最小间隔+紧急间隔+每日上限、回退内容、Agent 卡保留与未见记录补卡、忽略至实质变化、反馈进入下次输入、脱敏）；Python 新增 8 项（替身 app-server）。
- **构建与运行结果**：执行端现场核验为 K8-Plus / x86_64、默认路由 192.168.0.1、无代理环境变量；构建端 Mac mini（`chou-Mac-mini.local`，arm64，系统代理 Surge 127.0.0.1:6152）。在工作树执行 `python3 tools/rungic_package.py build rungic-suggestions rungic-voice-agent` 生成 `rungic-suggestions_0.474_arm64.deb` 与 `rungic-voice-agent_0.474_arm64.deb`（Ubuntu 26.04 ARM64 容器，含 ctest 与 zh_CN 目录编译）；同一构建树中 `care-tests` **31 项通过**（29 个方法及初始化/清理）。首轮构建发现 `qBound<qint64>` 重载歧义，改为显式类型后通过。本机 `python3 -m pytest -q tools/tests plasma/voice-agent` **54 项通过**（含新增 8 项）。工作树内构建需先建立 `.work/cache`，版本号按工作树提交数计算，产物只在工作树 `.work/apt`，未发布、未部署。
- **未验证**：真实 Codex 策展回合与费用、严格 schema/低推理在固定模型上的接受情况、`thread/inject_items` 在首回合前注入的实机行为、通知实际呈现、QML 卡片堆叠界面（由上层实现）、手机部署。

## 剩余问题

- 严格 schema 若被服务端拒绝（关键字不支持），会表现为回合失败并回退；需实机确认后再调整。
- 模型写的按钮文字作为用户首条消息：已限制长度与字符并附固定约束，但仍是模型文本；若实测出现不当措辞，改为服务端固定句式加标题。
- 过度脱敏可能去掉有用的 systemd 模板单元名；如影响策展质量，改为只替换顶级域为字母的地址。
- 旧的逐记录 `Presented` 回执仍有效；新 UI 应改用 `presentCard`。
