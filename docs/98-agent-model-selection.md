# Agent 的模型与推理强度可选（2026-10-01）

用户要求语音助手的 Agent（Codex）支持选择模型：

- 默认跟随账户默认；
- 推理强度也开放给用户选；
- 接口上为以后的其他 provider 留好位置。

标注：“实测”指在 G100 S 上用 Codex 0.156.1 和用户账户（ChatGPT Team）实际调用过；“离线”指本仓库的测试或本机渲染。

## 改之前

- **Codex 执行任务**：`gpt-6-sol`，推理强度 `medium`，都写死在代码里。环境变量 `RUNGIC_AGENT_MODEL` 可以覆盖模型。
- **实时语音**：`gpt-realtime-2.1-mini`。
- **系统建议整理**：跟随任务模型，强度 `low`。
- **通话画面判断**：`gpt-6-luna`，直接调 Responses API。
- 设置里没有模型选项。

## Codex 的接口（实测）

- **`model/list`**：返回账户可用的模型，每个模型带这些字段：
  - `id`、`displayName`、`description`；
  - `isDefault`、`hidden`；
  - `supportedReasoningEfforts` 和 `defaultReasoningEffort`；
  - `inputModalities`、`serviceTiers`；
  - `upgrade` 和 `upgradeInfo`（替代型号和退役时间）。

  用户账户有 7 个可见模型，加上隐藏的一共 9 个。默认是 GPT-6-Astra，默认强度 low；原来写死的 `gpt-6-sol`，目录里的说明是“Previous generation workhorse”。GPT-5.5 标了 `upgrade: gpt-5.6-sol`。强度按型号不同：Luna 最高到 max，Sol 和 Astra 到 ultra。

- **`thread/start` 不带 `model`**：得到账户默认的 gpt-6-astra，强度为空（取型号默认）。所以“跟随账户默认”可以直接交给 Codex。
- **`turn/start`**：可以带 `model` 和 `effort`，按接口说明，作用于这一轮及之后的轮次。
- **已加载的会话再 `thread/resume`，模型不会变**：
  - 做法：用 Luna/low 建会话，跑一轮；会话还加载着时，用 Astra/medium resume。
  - 结果：返回的仍是 Luna/low，下一轮的 `turn_context` 也是 Luna/low。
  - 先 `thread/unsubscribe`（卸载）再 resume，返回 Astra/medium，下一轮用的也是 Astra/medium。
  - 还没有过任何一轮的会话没有 rollout，无法 resume。
- **语音触发的任务**：由实时模型通过 Codex 内部的 `background_agent` 发起，沿用会话当前的模型，不经过我们的 `turn/start`。
- **`model/rerouted` 通知**：服务端可能把一轮改派给另一个模型；带 `fromModel`、`toModel`、`reason`。
- **`modelProvider/capabilities/read`**：网页搜索、图像生成、namespace 工具都可用。

- **模型目录按 Codex 客户端版本下发**（实测，2026-10-01）：同一账户，0.156.1 拿到 7 个模型，0.159.2 拿到 8 个，多出的 GPT-6.1-Sol 还是账户默认。所以 Codex 要跟随最新的 stable 版本，见 docs/99。

## 实现

- **`agent/assistant/model_catalog.py`**：与 provider 无关的一层。
  - 统一的模型结构：`id`、`name`、`description`、`default`、`efforts[{id, description}]`、`defaultEffort`、`upgrade`、`retiresAt`、`inputs`。
  - 用户的选择：`{model, effort}`，空字符串表示“默认”。
  - `resolve()`：把选择换算成实际使用的模型和强度。选的型号不再提供时，退回账户默认，并标 `fallback`；该型号不支持所选强度时，退回型号默认，并标 `effortFallback`。模型目录还没读到时返回 None，交给 provider 自己决定。
  - `valid_choice()`：校验选择是否合法。
  - `Catalog`：按需读取，缓存 10 分钟，`forget()` 使缓存失效。
  - `CodexCatalog`：调用 `model/list`，支持分页，去掉隐藏的模型。
  - 以后加新的 provider：写一个 `Catalog` 子类，再在服务的 `catalogs` 里登记。D-Bus 接口和 App 都不用改。
- **语音服务 `rungic_voice_agent.py`**：
  - 选择保存在 `preferences.json` 的 `models.<provider>` 下。原来的布尔偏好照旧，写入时两部分都保留。
  - **D-Bus**：
    - `Models({"provider", "refresh"})` 返回模型目录、用户的选择、换算结果（`effective`）和 provider 列表；
    - `SetAgentModel({"provider", "model", "effort"})` 先对照目录校验，再保存，并发出 `agent-model` 事件。
  - **新会话**：用选择对应的模型和强度；跟随默认、目录又未知时，不带 `model`。
  - **打字发的每一轮**：`turn/start` 都带 `model` 和 `effort`。
  - **resume**（`resume_with_settings`）：比对 resume 返回的模型和强度，不一致就 unsubscribe 再 resume。切换到之前加载过的会话时也会走这一步。
  - **改设置时**（`apply_agent_model`）：打开的会话空闲时，先停实时语音，再重载会话，之后恢复语音。有任务在跑、正在按住说话，或会话还没有过任何一轮时，记为 `model_pending`，等下一轮结束（`turn/completed`）后再重载。
  - **账户变化**（`account/updated`、重新登录）：模型目录失效，重新读取；选择不再成立时发出 `agent-model` 事件。
  - **`model/rerouted`**：在任务卡上加一条说明，内容为“改由 X 继续（原为 Y）”。
  - **用量面板**：`model` 字段改为报告实际使用模型的显示名。
  - **系统建议整理**：用自己的 `CURATE_MODEL`（`gpt-6-sol`），目录里没有它时改用账户默认。不跟用户的选择走。
  - **实时语音和通话画面判断**：不变，仍写死。
- **App**：
  - 设置的 Codex 组新增“模型”行，显示“模型名 · 强度”；选择退回默认时，行首显示红点。
  - 点进去是 `ModelPage.qml`，有加载中、就绪、不可用三个状态，写在 `states` 里：
    - 模型列表：第一项是“跟随账户默认（现在是 X）”，其后每个模型带描述，有替代型号的会标出；
    - 推理强度：第一项是“模型默认（X）”，其后是该型号支持的强度；
    - 提示：回退、开发覆盖变量、保存失败。
  - 强度的中文名称和说明放在 `efforts.js`，翻译在 `app/po/zh_CN`。

## 离线核对

- `tools/tests/test_model_catalog.py`：规整、换算、回退、校验、分页、缓存、失效。
- `tools/tests/test_agent_model.py`：已加载的会话在别的模型上时会重载；已经是目标模型或目录未知时不重载；会话空闲时立即切换，并恢复语音；忙碌或还没有过任何一轮时延后。
- `test_agent_usage.py` 和 `test_briefing_curation.py` 更新了替身。
- 本机用 PySide6 离线渲染了 ModelPage，用的是上面实测拿到的模型目录，浅色、深色都看过：就绪（跟随默认、选了 Luna 加高）、回退、加载中、不可用。
- 翻译文件由 Mac mini 上构建时的 ki18n（msgfmt）校验通过。

## 实机（G100 S，2026-10-01）

- **部署**：用开发覆盖装上（docs/97）：`rungic-voice-agent 0.514+dev20260930t151415.e11474f.dirty`，基线是发布 20260930.10。apt 核对通过，只重启了 rungic-voice-agent。构建在 Mac mini 上完成，其中 ki18n 的 msgfmt 校验翻译文件通过。
- **D-Bus**（以桌面用户身份在命令行调用，不开窗口）：
  - `Models`：选择为空，`effective` 为 gpt-6-astra/low，目录读到 7 个模型；
  - `SetAgentModel`：`gpt-4` 被拒（unknown model）；`gpt-6-luna` 加 `ultra` 被拒（no reasoning effort ultra）；
  - 改成 `gpt-6-luna` 加 `low` 后，`preferences.json` 的三个布尔开关保留，另外多了 `models.codex`；
  - 用量面板的 `model` 变为 GPT-6-Luna。
- **打开着的会话**（服务日志）：
  - 改成 Luna/low：日志显示会话原本在 gpt-6-astra/low，服务重载后，Codex 回报 gpt-6-luna/low，用时约 3 秒；
  - 恢复为默认：会话从 gpt-6-luna/low 重载回 gpt-6-astra/low；
  - 用户的设置已经恢复成跟随账户默认。
- **没有验证到的**：
  - 设置页和 ModelPage 在手机上的实际显示：要在你的屏幕上打开 App，所以只做了离线渲染；
  - 真实语音任务跑在新模型上：离线探针证明了“卸载再 resume 后，下一轮用新模型”，实机上只看到了 Codex 回报的会话模型；
  - `model/rerouted` 的显示：这次没有发生改派。
