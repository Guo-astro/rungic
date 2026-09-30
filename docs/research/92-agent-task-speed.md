# Agent 做 Blender 这类任务为什么慢，业界怎么提速（调研，2026-09-30）

状态：调研，尚未实施。标注说明：“本机实测”来自手机上的记录；“文档/源码”是调研子任务读到的官方文档、论文或代码；“二手”指只见于 README、检索摘要或无法打开的页面，未复核。

## 本机实测：小火箭一轮 128 秒（对话 01a0ed64，2026-09-29）

| 阶段 | 用时 | 内容 |
|---|---|---|
| 了解环境 | 约 23 s | 读技能，查 Blender 版本和图片目录，读 `rungic_render` 源码 170 行 |
| 写建模脚本 | 约 47 s | 一次模型调用输出 2484 token（推理只有 292），约 53 token/s |
| 检查、启动 | 约 9 s | 编译检查脚本，启动 Blender |
| 建模和渲染 | 约 25 s | Blender 实际计算：CPU 渲染，512×512，64 采样，4 线程 |
| 看图、回答 | 约 18 s | |

- 一轮大约 13 次模型调用。即使输出很短，每次也要 5–8 秒（上下文 2.5–2.9 万 token，大部分命中缓存）。
- 模型 `gpt-6-sol`，推理强度 medium。
- 结论：约 100 秒花在模型往返和逐字输出代码上，Blender 本身只占约 25 秒。

## 业界做法（按对本机的预期收益排序）

1. **给模型一套高层积木库，并在技能里写明接口**（收益大）。
   - 模型调用 `part.cylinder()`、`mat.metal()`、`light.three_point()`、`cam.frame_all()`、`render.preview()` 这类函数，而不是手写原始 bpy。
   - 依据：
     - OpenAI 延迟指南（文档）：输出长度是延迟的主因，减少一半输出约可减少一半延迟，减少一半输入只改善 1–5%。https://developers.openai.com/api/docs/guides/latency-optimization
     - Anthropic Agent Skills（文档）：固定、可重复的步骤应做成现成脚本，而不是让模型逐字生成。https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
     - Anthropic “Code execution with MCP”（文档）：把可用代码存成高层函数工具箱。https://www.anthropic.com/engineering/code-execution-with-mcp
     - Blender 研究：3D-GPT（调 Infinigen 的程序化函数）、ShapeCraft（`cube()`、`cylinder()`、`Modifiers.bevel()` 等原语）、SceneCraft（把常用函数沉淀成可复用库），都限定模型只写高层调用（论文）。
   - 估算（未实测）：脚本从约 2500 token 降到 600–900 token，写代码从约 47 秒降到 12–18 秒。
2. **把稳定的事实写进技能，不让模型每次重新探索**（收益大）：Blender 版本和路径、输出目录、渲染模块的命令行用法、渲染预设、一个完整示例。Codex 只在用到技能时才加载全文，名称和简介常驻（文档：https://learn.chatgpt.com/docs/build-skills.md ）。预计少 3–5 次模型往返。
3. **一个工具调用完成一整步，并返回下一步需要的全部信息**（收益中高）：运行脚本、渲染预览，在一次结果里返回图片、物体数量、包围盒、警告，以及截到出错行的报错。依据 Anthropic《Writing effective tools for agents》（文档）https://www.anthropic.com/engineering/writing-tools-for-agents ，以及 OpenAI 延迟指南的“少发请求”。
4. **降低每次调用的固定开销**（收益中）：
   - 推理强度：本轮 medium 只推理了 292 token。Codex 文档说 low 适合“范围明确的快速任务”（https://learn.chatgpt.com/docs/models ）。没有找到官方的 low 与 medium 在智能体编程上的对照，需要自己做 A/B。
   - Fast 模式：`service_tier = "fast"` 加 `[features].fast_mode`。文档称对 GPT-5.x 快约 1.5 倍，没有说明 GPT-6 Sol 快多少；ChatGPT 额度按 2.5 倍计，用 API key 时按 Priority 计费（文档：https://learn.chatgpt.com/docs/agent-configuration/speed ）。
     - 本机核对：Codex 0.156.1 的二进制里有 `service_tier`、`fast_mode`、`priority` 等字符串。
   - 提示缓存：已经在命中；保持提示开头稳定即可。
5. **独立的命令并行或合并执行**（收益中，主要在探索阶段）：
   - Codex PR #10505 把 shell 工具标为可并行（源码）；PR #38499 默认开启 `parallel_tool_calls`（源码）。
   - app-server 客户端注册的动态工具仍然串行执行（issue #46685，未合并）。MCP 服务可以声明 `supports_parallel_tool_calls`（PR #17667）。
   - 本机核对：二进制里有 `parallel_tool_calls`、`supports_parallel_tool_calls`。
   - 最简单的办法：在技能里要求把几项检查合成一条命令。
6. **Blender 常驻，渲染预设放进积木库**（收益中）：blender-mcp 让 Blender 保持运行，只把代码发进去执行（二手，README）。
7. **后续修改用补丁，不整段重写**：“再高一点”这类请求改现有脚本（`apply_patch`）。Codex 的系统提示本来就倾向这样做（源码）。
8. **例行的小任务用更快的小模型，建模本身不用**（收益小到中）：Codex 子代理可以单独设置模型和推理强度；gpt-6-luna 适合范围窄、调用量大的任务（文档，键名来自检索摘要）。EZBlender 的测试里，轻量模型在复杂任务上明显变差，所以建模仍用 Sol。
9. **让等待显得短**：分阶段播报进度（本项目 89 篇已经在做）。

**不适用**：Predicted Outputs 只支持 gpt-4o 和 gpt-4.1 系列，而且不能和函数调用同时使用（文档：https://developers.openai.com/api/docs/guides/predicted-outputs ）。

## 同类 Blender Agent

| 项目 | 做法 | 积木库 | 备注 |
|---|---|---|---|
| blender-mcp | MCP 工具连着常驻的 Blender，执行任意代码 | 无（原始 bpy），另有素材工具 | 无延迟数据（README） |
| BlenderGPT | 一次提示生成 bpy 代码 | 无 | EZBlender 对照：23.85 s，但任务完成率只有 30.4% |
| LL3M（2025） | 6 个代理，检索 Blender 文档 | 无（检索式） | 创建约 4 分钟，加自动修改约 6 分钟（论文） |
| 3D-GPT | 由 LLM 填 Infinigen 程序化函数的参数 | **有** | 论文 |
| ShapeCraft（2025） | 形体分解成部件图，多代理 | **有** | 每个形体约 11.7 分钟（论文） |
| SceneCraft（2024） | 场景图 → 布局代码 → 视觉修正 | **有**（自动沉淀） | 论文 |
| EZBlender（2026） | 规划器按几何、材质、灯光、相机、背景分工 | 任务规格而非函数库 | GPT-4o：37.35 s，完成率 72%（论文） |

- 规律：又快又稳的系统，都把模型要写的东西限制在高层积木或参数上。
- 纯 bpy 的系统，要么快但不可靠（BlenderGPT），要么可靠但耗时数分钟（LL3M）。
- 3DCodeBench（2026）指出，失败主要来自 API 调用写错，和部件悬空。

## 未知与风险

- **需要本机 A/B 实测**：
  - Fast 模式对 GPT-6 Sol 快多少；
  - 推理强度 low 对质量的影响；
  - 积木库实际能省多少时间。
- 积木库可能限制造型的多样性：保留原始 bpy 作为兜底（LL3M、blender-mcp 都是这样）。
- 部分 openai.com 博客无法打开，相关结论只来自检索摘要。

## 建议的实施顺序（待用户决定）

1. 积木库和技能里的固定事实、示例：收益最大，只改我们自己的代码。
2. 一步完成“建模 + 渲染 + 返回结果”的工具：并入 `rungic_render`。
3. 固定一组题目（火箭、椅子、汽车），A/B 实测推理强度 low 对 medium，以及 Fast 模式（涉及费用）。
