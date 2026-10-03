# 功能清单与质量治理

Rungic 的功能、它们必须做到的体验，以及背后的代码、文档和测试，都记在这里。生成的总览是 [docs/feature-inventory.md](../docs/feature-inventory.md)，不要手改它；改这里的数据，再运行 `python3 tools/feature_inventory.py render --write`。

## 为什么这样做

- **找得到**：每个功能的代码、测试、文档和已知问题都在一处。改动前先查 `feature_inventory.py feature ID`，查一个文件归谁用 `feature_inventory.py owner PATH`。
- **测得全**：每条体验都要有检查。测试自己声明它检查哪一条，测试改名或删除时清单会发现。
- **清得掉**：每个被跟踪的文件都要有功能认领，每篇文档都要分类。没人认领的、已退役功能留下的、已被取代的文档，都会出现在 `report` 里，作为删除或重构的依据。

做法参照 Android CDD/CTS（要求有编号，测试声明自己验证哪一条）、Linux `MAINTAINERS`（路径归属），以及按用户场景组织功能的故事地图。

## 数据

| 文件 | 内容 |
|---|---|
| `features/<领域>.yaml` | 一个领域的用户场景和功能 |
| `interfaces.yaml` | 系统功能用到安卓的接口（契约） |
| `docs.yaml` | 每篇文档的类别 |

### 功能

```yaml
- id: desktop-mode.fullscreen        # 领域.名字，英文、稳定
  title: 桌面模式全屏                 # 用户说得出的名字
  scenario: desktop-mode.use         # 属于哪个用户场景
  status: live                       # live 在用 | experimental 实验 | retired 已退役
  platform: linux                    # linux 系统功能，与安卓无关 | android 离不开安卓
  interfaces: [platform-bridge]      # 经由哪些安卓接口（interfaces.yaml）
  summary: 一句话：用户得到什么。
  experience:                        # 必须做到的体验，一条一个可检查的要求
    - id: E1
      text: 进出全屏没有空白帧，退出后浮窗回到原位。
      evidence:                      # 人工验证：文档位置和日期（超过 90 天算过期）
        - {doc: docs/research/97-headless-agent-work.md, date: 2026-10-03, note: §21.6}
      gap: 只能人眼判断，等录屏比对工具       # 暂时无法检查的原因（可选，写明就不算“未检查”）
      device: 帧率取决于手机的 GPU 与 Android 的刷新   # 只有手机能说明这条体验的原因（可选，见“分层”）
  pitfalls:                          # 需要注意的问题：踩过的坑、限制、容易误判的地方
    - text: 手机上全屏窗口第一帧要晚约 0.6 秒。
      docs: [docs/research/97-headless-agent-work.md]
  code: [agent/screen/qml/Main.qml, agent/screen/]   # 认领的文件；以 / 结尾表示整个目录，支持 ** 通配
  docs: [docs/research/97-headless-agent-work.md]    # 讲它的文档
```

写法：

- **一条功能是用户能感知的一件事**，例如“桌面模式全屏”“授权框出现在桌面里”；不是一个模块、一个服务或一次重构。
- **体验写用户看到的结果**，要能判断对错：“退出后浮窗回到原来的位置和大小”，而不是“全屏逻辑正确”。性能、恢复、失败时的表现都算体验。
- 支撑性的工程能力（打包、发布、诊断、补丁队列）放在“交付与运维”领域，用户是开发者和 Agent。
- 已退役的功能保留记录，`status: retired`；它的代码和文档应当删除，`report` 会列出还没删的。确实要留的（例如 AGENTS.md 要求保留给历史/恢复工作的整包工具），写 `keep: 保留的理由`，就不再算作待清理。

### 测试声明

测试在被检查的地方写一行注释，任何语言都行（补丁里的测试也一样）：

```python
# covers: desktop-mode.fullscreen/E1            离线单元测试（默认）
# covers[system]: desktop-mode.fullscreen/E2    无头 Linux 系统测试（KWin --virtual 等，不需要安卓）
# covers[consumer]: iface:platform-bridge       接口契约：Linux 一侧对着替身
# covers[provider]: iface:platform-bridge       接口契约：安卓一侧，在手机上
// covers[device]: desktop-mode.tv/E2           在手机上跑的测试（不在 acceptance.json 里的）
```

实机验收（`release/acceptance.json`）在场景里写 `"covers": ["display.size/E1", "iface:kwin-android-host"]`。只在测试真的检查了那条体验时才声明。

### 分层

多数功能是 Linux 系统的功能（`platform: linux`），底下是安卓还是 PC 都一样，应当不靠安卓就能测：

| 层 | 在哪里跑 | 检查什么 |
|---|---|---|
| 单元 | 本机离线（`tools/run-tests.sh`） | 逻辑、协议、解析 |
| 系统 | 无头 Linux：Mac mini 的 arm64 容器里 `kwin_wayland --virtual`（`tools/system_test.py`） | 窗口、层级、D-Bus、多个程序协作 |
| 契约 | 使用方离线对着替身，提供方在手机上 | 系统功能和安卓之间的每个接口 |
| 实机 | 手机（`tools/rungic_acceptance.py`、人工） | 接上之后整体可用；性能、时序、功耗 |

`report` 会指出只在手机上检查的 Linux 功能（`device-only`，应当补系统测试）和只测了一头的接口（`one-sided-contract`）。

Linux 功能里也有只能在手机上看的体验：性能、帧率、时序、功耗、画质、音质，或者结果取决于 Android 和硬件本身（例如摄像头出画、120 Hz）。这类体验写 `device: 原因`，仍然要有实机验收或人工验证，但不算 `device-only` 欠账。原因要具体到为什么系统测试替代不了；能拆出 Linux 一侧逻辑的，那部分照样写单元或系统测试。

### 文档类别

| kind | 含义 | 处理 |
|---|---|---|
| reference | 现在的样子，维护到最新 | 必须有功能引用 |
| journal | 过程记录：调研、实现、实测的经过 | 必须有功能引用；结论应进入功能的体验和注意事项 |
| research | 可复用的调研 | 必须有功能引用 |
| history | 已结束的历史（旧设备、旧路线），保留作证据 | 不要求引用，不再更新 |
| index | 索引、总览 | — |
| superseded | 内容已被别的文档取代（`superseded_by`） | 确认独有的事实已迁移后删除 |

## 检查与清理

```sh
python3 tools/feature_inventory.py check          # 引用断裂是错误；其余是警告
python3 tools/feature_inventory.py check --strict # 警告也算错误（tools/test_feature_inventory.py 用它）
python3 tools/feature_inventory.py report         # 警告全文：要补的测试、要清理的文件、要决定的事
```

- `--strict`（`tools/test_feature_inventory.py`、`tools/run-tests.sh`）对两类警告的处理不同：
  - **结构性问题必须清零**：无主文件、未分类或无人引用的文档、已被取代还没删的文档、留着代码的退役功能（没有 `keep`）、没有功能用的接口。新增文件就要有功能认领，新功能就要写体验。
  - **测试欠账只许减少**：没有检查的体验（`untested`）、只在手机上检查的 Linux 功能（`device-only`）、只测了一头的接口（`one-sided-contract`）、过期的人工验证（`stale-evidence`）。现有的记在 `quality/baseline.json`，出现新的就失败。补上测试后运行 `check --update-baseline` 收紧基线；基线变大会出现在 diff 里，需要说明理由。
- 人工验证超过 90 天（`stale-evidence`）只在 `report` 里提示，测试不因日历而失败；重新验证后更新 `evidence` 的日期。
- `tools/run-tests.sh` 跑上述检查，另外核对 `release/acceptance.json` 的每个场景都有对应的检查函数（`tools/tests/test_acceptance_scenarios.py`），以及补丁头 `X-Rungic-Tests` 里写的 L3 场景存在（`tools/pq.py lint`；还没写的标 `(to write)`）。
- 删除代码或文档前，先用 `owner` 确认归属，用 `git grep` 确认没有引用，再看构建（`packaging/*/package.json` 的 `paths`、配方的 `overlay`）。一项清理一个提交，写明依据。

## 在手机上验证提供方：只读

契约的提供方检查和其他实机检查都在用户的日常机上跑。2026-10-03 `desktop-mode.workspace` 的第一版检查为验证开关而先关后开桌面模式，又把状态读成了空（输出格式与预期不同），于是关掉了用户正在用的桌面（工作区 0 被关、应用被要求退出）；当即用 `rungic-desktop-mode on` 恢复，浮窗进程没有受影响。现在的规则：

- 检查以实际运行的部件判断状态，读不懂状态就报失败，不做任何切换。
- 桌面模式正在使用时只做只读核对；开关的往返只在它本来就关着时做，结束时恢复原状。往返会在手机上短暂打开桌面模式的浮窗，所以它属于 `full` 级验收，不在部署后的冒烟验收里。
- 新的实机检查先在只读模式下跑一遍，看清它读到的是什么，再加会改变状态的步骤。
