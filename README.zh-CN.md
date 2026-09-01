# Guarded Desktop Agent（中文快速开始）

**面向 Windows 的、可恢复且受安全策略约束的 computer-use 运行时。**

本项目原名 `computer-use-mcp`。新名称用于明确区分项目自带的 MCP 服务与平台
提供的 Computer Use 插件；旧 Python 导入路径、状态目录、环境变量及命令在兼容
期内继续可用。

[English README](README.md) | [完整项目总览（英文）](docs/PROJECT_OVERVIEW.md) | [文档索引（英文）](docs/README.md)

> **状态：实验性。** 仅 Windows、前台桌面、主显示器。英文文档是唯一的规范
> 来源；本页只提供中文快速开始。所有能力主张都以英文
> [能力状态看板](docs/CAPABILITY_STATUS.md)中的留存证据为准。

让模型在桌面上乱点并不难；难的是知道它**被允许做什么**、**实际做了什么**，
以及进程崩溃后**什么才可以安全重试**。本项目把这几层分开：UIA 与受限 OCR
负责观察，策略与审批构成显式边界，桌面执行权限收敛到唯一入口，证据持久化
到崩溃之后仍然可用。

## 现在（Now）

项目当前是一个实验性的 Windows 前台桌面 Runtime 与 Agent Host，而不是一个
已经统一完成的桌面 Agent 产品。用户入口仍然是几组**彼此分开的 CLI 命令**：
只读提问、一个固定 Chrome-to-Word 工作流、配置检查、Pre-run Review、Task
Center 和协作式控制各有自己的命令。

当前**没有**可以理解并执行任意自然语言任务的统一 Agent Console，也没有通用的
`recipe list -> review -> start -> status` 产品入口。现在已有一个独立的
Offline Scope Review Windows Console；它只接收一段进程内草稿，展示用户原样选择的 model、
静态审核过的 provider route/profile 与本地 disclosure，并在 exact `COMPILE` 后由固定
Host 本地 compiler 一次性消费 permit、显示完整内置 Scope。内部也已有离线-only 的
`TaskIntent`、scenario、role profile、通用 Scope Sheet，以及敏感本地 disclosure /
exact `COMPILE` 的进程内 permit 合同。这个 Console 不读 Agent 配置、API key 或
provider 环境变量，不调用 provider；自由文本只绑定 digest，不改变固定 Scope，
预期运行的 provider call 与 retry 都是 0。它只选择了 inert 的 Outlook Desktop
测试账户草稿设计 profile，并让原生 `Start` 永久禁用。它没有 Runner、MCP、桌面自动化、应用、持久化
或 durable run 路径；这里显示的 model 也不代表 readiness 或 compatibility，不能从该入口推断完整产品能力。当前授权工作和安全恢复点只看
[Project status](PROJECT_STATUS.md)，能力及证据只看
[Capability status](docs/CAPABILITY_STATUS.md)。

## 现在能做什么（Can do）

| 需求 | 当前入口 | 真实边界 |
| --- | --- | --- |
| 本地审阅 Formal Demo Scope | `guarded-desktop-agent-console --provider <provider> --model <model>` | exact `COMPILE` 一次性消费本地 permit，以固定 Host mapping 显示完整内置 Scope；`Start` 禁用，不读 key、不发 provider 请求，不解释自由文本 |
| 询问前台文档内容 | `guarded-desktop-agent ask` | 一到四次已审核的只读观察；不能规划桌面副作用 |
| 运行现有产品工作流 | `guarded-desktop-agent review public-web-word`，再执行 `guarded-desktop-agent workflow public-web-word` | 只覆盖固定公开网页到全新 Word 文档；不是任意网页或任意办公任务 |
| 检查安装和配置 | `guarded-desktop-agent config setup/settings/doctor` | 配置与 readiness；不等于开始任务或授予桌面权限 |
| 查看本地任务结果 | `guarded-desktop-agent task center` | 只读状态与 Receipt；不能 approve、resume、retry 或 dispatch |
| 协作式暂停、接管和恢复 | `guarded-desktop-agent task pause/takeover/resume` | 目前只覆盖固定工作流的同进程 Runner；恢复前必须重新观察 |
| 直接接入 MCP Runtime | `guarded-desktop-mcp` | 13 个核心工具加可选只读浏览器观察；桌面仍只有一个执行路径 |

### 当前 Runtime 与 provider 支持

- Windows；Python 3.11 至 3.13。
- stdio MCP transport。
- 主显示器截图和 UIA 控件发现。
- 13 个核心 MCP 工具：`ui_snapshot`、`find`、`list_windows`、`screenshot`、
  `capture_region`、`ocr`、`document_text`、`activate_window`、`click`、
  `scroll`、`drag`、`type`、`key`。
- 用户显式配置后，可增加第 14 个只读 `browser_snapshot`：通过本机
  Chromium CDP 读取有界的已渲染 ARIA/文字，但不能导航、点击、执行脚本、
  读取 cookie/storage，也不会产生浏览器 action ref。
- 默认安全模式：进程白名单、检测到人类输入时让路、危险 ref 点击确认、审计
  日志和急停热键。
- Agent Host 已离线实现 9 个精确 provider profile：8 个云端 identity
  （OpenAI、Anthropic、Qwen、Doubao、Kimi、DeepSeek、GLM 和 MiniMax）以及
  一个仅 loopback 的 `local_openai`。云端路由和本地 Planner/final 边界已离线
  验证；本地 native tool-calling 在 E3 前固定不可用。留存的真实 API 证据覆盖
  此前 OpenAI/Claude 范围、Kimi `cn` + `kimi-k2.6`、MiniMax `cn` +
  `MiniMax-M2.7`、DeepSeek `global` + `deepseek-v4-pro`，以及 Doubao
  `cn-beijing` + `doubao-seed-2-0-lite-260215`、Qwen `cn-beijing` +
  `qwen3.7-plus`、GLM `cn` + `glm-5.2` 精确范围；其他路由和模型仍须分别
  验证。详见
  [provider 支持矩阵（英文）](docs/PROVIDERS.md)。

macOS、Linux、多显示器坐标以及隔离 worker 编排都仍在路线图中，尚未实现。

## 已验证的结果

| 结果 | 证据 |
| --- | --- |
| 强制崩溃的 campaign：中途杀掉、新进程恢复，每个故障点都是 **0 重复副作用** | [可靠性 demo](docs/demo/README.md) |
| 可靠性基准：**30 次运行 × 100 item**，在每个命名故障点注入崩溃，**0 重复副作用**，每个 item 要么提交要么停下等人 | [基准证据](docs/benchmark/README.md) |
| 一页真实 BOSS 页面：7 个稳定公开 job key、0 重复、0 重试、0 token —— **该测量所依据的契约已被 discovery-pass ledger 取代** | [发现证据](docs/BOSS_CAMPAIGN_DISCOVERY_EVIDENCE.md) |
| 当前 BOSS 发现契约：2 次不同的 on-device pass、12 个稳定公开 job key、0 重复、0 provider 调用、0 副作用 | [多 pass 发现证据](docs/BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md) |
| BOSS item/restart 部分诊断：3 条身份提交、修复后 stale-owner 恢复成功、0 provider 调用，且明确保留两项现场缺陷 | [item/restart 诊断证据](docs/BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md) |

每条记录**只支持它自己的范围**：这些都不是 application acceptance，也不表示
本项目是通用 worker。旧的一页结果保留作历史记录；当前契约的两次 pass 只证明
外部控制翻页后的身份累积，不证明 item 处理、provider 执行或重启恢复。

## 计划中（Planned）

下列内容已经分清 owner；其中标明的内部离线合同不是当前可执行命令、产品入口或
真实应用证据：

1. **统一 Host 前门：**Offline Scope Review Console 已实现到本地 disclosure、
   process-local `COMPILE` permit、固定 Host intent 与完整 Scope；完整的 `Agent Console -> TaskIntent -> Host validation
   -> Scope Sheet -> review/start/status` 只负责收集意图和展示 Host 验证后的范围；
   它不会获得桌面权限，后续仍必须进入现有 Runner、唯一 MCP server 和 Windows
   Driver。自然语言如果要发送给 provider 生成 `TaskIntent`，发送前还必须本地展示
   exact text、provider/model、用途与 data-use 警告，并用单独的 `COMPILE` 确认；
   这不等于后续 Scope Sheet 的 `START`，也不授予动作权限。详见
   [项目总览中的 current/planned architecture](docs/PROJECT_OVERVIEW.md)。
2. **Formal Demo v1：**选定的产品故事是 GitHub Issues fixture -> PDF ->
   disposable Excel -> disposable Word -> test-account email draft（绝不发送）。
   `GDA-DEMO-007A` 到 `GDA-DEMO-007F` 均已实现并完成 offline verification：
   包括四个 inert v1 数据合同、typed 敏感本地 disclosure、reviewed warning pin、
   单 gate 实例 exact `COMPILE` permit、provider-neutral one-attempt coordinator、
   固定 no-key local Scope compiler、独立 Offline Scope Review Console，以及一个
   精确 `openai` / `global` / `gpt-5.6-terra` live-capable intent adapter 和内部
   Provider Scope path。该 adapter 未连接 Console；当前账号/data-controls preflight
   与 process-local credential 均未提供，因此 credentialed live gate 未运行：
   `Provider evidence: NO`；native `Start: disabled`。email role 只选择了 inert Outlook Desktop
   test-draft 设计绑定，不代表可执行 adapter 或应用可用。原始任务只保留在本地
   内存 disclosure 与显示中，permit/receipt 只绑定其 digest；没有 serialized
   gate loader，也不提供跨进程 exactly-once。`START`、可执行应用 adapter、
   durable composition 和正式 Formal Demo evidence 仍未实现。详见
   [Formal Demo v1](docs/FORMAL_DEMO_V1.md)。
3. **Application Coverage Set A：**BOSS、Google Docs、WeChat 继续作为独立的
   真实应用覆盖与证据用例，不再定义 Formal Demo，也不是自动获得优先级的
   “Wave 1”。详见[应用评估矩阵](docs/APPLICATION_EVALUATION_MATRIX.md)。
4. **Universal GUI final showcase：**未来在多个独立机制和应用通过证据门后，
   再组装完整的多章节最终展示；它不是 Formal Demo v1，也不是当前下一步。
   详见[Universal GUI final showcase](docs/UNIVERSAL_GUI_DEMO.md)。

## 怎么下指令（How to ask）

今天仍没有一个统一 Console 可以理解并执行任意指令；Offline Scope Review
Console 不解释自由文本，也不会执行。请先说明你是在**使用当前
能力**，还是在**要求修改项目**。

使用当前只读能力时，把问题写成明确且可验证的结果，例如：

> 总结当前前台测试文档的三个要点；只读，不点击、不输入、不切换应用。

使用固定工作流时，不要用泛化描述替代它的契约；先运行
`review public-web-word`，核对来源、应用、输出路径、停止条件和残留风险，再显式
输入 `START`。

让 Codex 或 Claude Code 修改项目时，建议一次给出五项：

1. **Outcome：**这一小步完成后应新增或纠正什么；
2. **Scope：**允许修改的模块、应用和文件；
3. **Side effects：**允许读、写、发送或发布什么，哪些明确禁止；
4. **Evidence：**用哪些测试、真实环境或保留产物证明完成；
5. **Stop：**缺账号、权限、选择、真实证据或出现不确定副作用时在哪里停下。

可以直接复制下面的边界化表达：

> 只审查当前架构和文档，不改 Runtime。列出 implemented、partial、planned，
> 并指出每一项的 owner、证据和准确下一步。

> 在另行激活 Formal Demo 后续切片前，先重读 `PROJECT_STATUS.md`；保留当前
> Offline Scope Review 的固定本地 mapping、永久禁用的 `Start`、Full Cycle 与
> provider E3 恢复点，不把 Outlook 设计 profile 当成可执行 adapter，也不启动
> provider、Runner、MCP、desktop、application 或 durable run。

> 设计 OpenClaw-like 的产品入口时，只做 Host-owned front-door contract；复用
> 现有 Runner/MCP，不增加 daemon、scheduler、plugin gateway、Multi-Agent 或
> 第二条桌面执行路径，并把未实现部分明确标成 Planned。

如果指令会改变项目优先级，应同时要求将唯一 active item、停止条件和原有恢复点
写回 [Project status](PROJECT_STATUS.md)，不能只在对话里改变方向。

### 如果以后要改 Runner 或 tools

这类改动通常不是“只改一个文件”：新增或修改 tool 要同步 Host `ToolSpec`、MCP
schema、策略/grounding、安全元数据、结果转换、registry digest 及相关测试；新增原生
动作还要同步 Driver Contract 与 Windows Driver。修改 Runner 的 dispatch、恢复或
结果确定性，则要同步 continuation/WAL/recovery 与 unknown-outcome no-replay 测试。
只有纯 Host 前门、recipe 或 scenario contract 通常可以复用现有 Runner/tools 而不改
核心工具面。完整影响表见[项目架构](docs/PROJECT_OVERVIEW.md#runner-and-tool-change-impact-map)。

## 安全提示

桌面动作会移动鼠标、切换焦点、输入文字和调用控件。请从
`safe_local` 开始，将白名单限制在测试应用（例如 Notepad），并先阅读
[英文配置与安全说明](docs/CONFIGURATION.md)。

`full_control_local` 会明确绕过前台白名单和人类输入让路机制；虽然仍保留
审计和急停，但只应在操作员明确授权接管本机桌面时使用。

## Desktop Ask 首次使用

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[agent-openai]"

.\.venv\Scripts\guarded-desktop-agent.exe config setup

$env:OPENAI_API_KEY = "<provider credential>"

.\.venv\Scripts\guarded-desktop-agent.exe config settings
~~~

`config setup` 会为用户本地配置打印准确的 `config doctor --config ...`
命令；首次提问前请执行该命令。安全暂停默认是 `ctrl+alt+p`；可用例如
`config setup --pause-shortcut ctrl+alt+k` 选择另一个字母，G/Q 保持保留。
若要启用已有浏览器的只读辅助，请安装 `.[agent-openai,browser]`，并按英文
配置文档在 `[mcp].environment` 中设置 loopback CDP endpoint；默认仍关闭。

打开一个不敏感的 Notepad、Word 或浏览器测试文档并保持在前台，然后执行：

~~~powershell
.\.venv\Scripts\guarded-desktop-agent.exe ask `
  --config "$env:LOCALAPPDATA\computer-use-agent\agent.toml" `
  --task "把前台文档总结成三个要点"
~~~

`ask` 默认直接输出答案；加 `--json` 会同时输出 run ID、plan ID、观察次数和
usage。它只允许一到四次已审核的只读观察，包括有界的 UIA
`document_text`，不能规划桌面副作用。生成的配置不写入凭据，使用用户本地状态
目录，并启用这条观察/最终回答路径所需的短期 continuation WAL。新生成的产品
配置还会默认开启当前全部 UI/UX 布尔设置：动作反馈、presence、progress、
reduced motion、high contrast 和 Decision Cards。这些设置只增加可见性和本地
交互，不授予模型或桌面执行权限，并且每一项仍可在配置中显式关闭。

`config settings` 是 CLI-first 的 Agent Controls 视图。它从同一份严格
TOML 展示用途、provider/model、安全、界面偏好和准确的下一步命令；只报告
provider SDK 与凭据环境变量是否存在，不打开外部端口、不注册快捷键，也不授予
approval、control、retry/replay 或 dispatch 权限。加 `--json` 可取得同一组
有界信息。

如需全局 Agent Controls 与安全暂停快捷键，可另开一个终端并保持运行：

~~~powershell
.\.venv\Scripts\guarded-desktop-agent.exe shortcuts run `
  --config "$env:LOCALAPPDATA\computer-use-agent\agent.toml"
~~~

`Ctrl+Alt+G` 只恢复该 host 自己的 Agent Controls 控制台；配置的暂停组合键（默认
`Ctrl+Alt+P`）只提交 cooperative pause 请求，必须等到明确显示
`PAUSED · DESKTOP AUTHORITY RELEASED` 才可本地接管；`Ctrl+Alt+Q` 仍是独立
MCP 急停。没有全局 approve/resume，关闭 host 即释放两个注册。详见
[Quick Setup and Agent Controls](docs/AGENT_CONTROLS.md)。

`config doctor` 是安装后 readiness 检查：它依次验证配置、provider extra、
必需或可选的凭据合同、MCP 可执行文件和工作目录，然后短暂启动已安装的 MCP
子进程，通过 `initialize` / `list_tools` 核对完整的已配置契约：默认 13 个
核心工具，启用 CDP 时为核心工具加 `browser_snapshot`。它输出固定
JSON；全部通过时退出码为 `0`，遇到一个可操作故障时为 `2`。它不会请求
provider、调用 MCP tool、读取桌面内容或执行桌面动作；但 MCP 启动期间仍可能
创建配置的 audit 目录并启动急停按键轮询，随后子进程会被关闭。

`config setup --provider NAME [--model ID]` 支持 `openai`、`anthropic`、
`qwen`、`doubao`、`kimi`、`deepseek`、`glm`、`minimax` 和 `local_openai`。
Anthropic 与 MiniMax 使用 `agent-anthropic`，其余 profile 使用 `agent-openai`；若两类
都需要则安装 `agent`。可用 `--region` 显式选择受审核服务区；Qwen 还必须
提供 `--workspace-id`，由 Host 构造对应区域 endpoint。云端 `--base-url` 仅保留给
旧 Qwen 配置迁移，固定 endpoint 的 provider 会拒绝该覆盖。`local_openai` 必须
显式给出 model 和 `http://127.0.0.1:<port>/v1`（或 `::1`）地址；Host 不启动或
下载模型服务，`LOCAL_OPENAI_API_KEY` 可选，native tool-calling/E3 暂不开放。
当前 Desktop Ask 已有一次 OpenAI/Windows/Notepad exact-candidate 结果；它不
证明其他 provider、application、desktop action 或 release artifact。各家的
凭据变量、图片能力和真实测试状态见
[provider 支持矩阵（英文）](docs/PROVIDERS.md)。

## 只读 Task Center

无需连接 provider、MCP 或桌面，即可查看经过验证的本地 run/campaign 状态：

~~~powershell
guarded-desktop-agent task center --config C:\absolute\path\agent.toml
guarded-desktop-agent task center --config C:\absolute\path\agent.toml --json
~~~

默认界面按 Attention、In progress 和 History 分组，并输出固定的
Completion/Failure Receipt；它不能 approve、resume、retry、cancel 或 advance。
`UNKNOWN_OUTCOME` 会明确提示不得自动重试。`public-web-word` 只有在保存、摘要、
重新打开和清理全部验证通过并写入严格的本地不可变 receipt 后，Task Center 才会
声称 DOCX 已保存并验证。完整边界见
[Task Center 与 receipt 契约](docs/TASK_CENTER.md)。

## Public Web to Word 工作流

先生成专用的受监督配置并检查 readiness，再从固定的 Microsoft Support
公开页面生成一个全新的 DOCX：

~~~powershell
guarded-desktop-agent config init `
  --profile public-web-word `
  --provider openai `
  --model <已审核的模型 ID> `
  --output C:\absolute\path\public-web-word.toml

guarded-desktop-agent config doctor `
  --config C:\absolute\path\public-web-word.toml

guarded-desktop-agent review public-web-word `
  --config C:\absolute\path\public-web-word.toml `
  --output C:\absolute\path\collaboration-brief.docx

guarded-desktop-agent workflow public-web-word `
  --config C:\absolute\path\public-web-word.toml `
  --output C:\absolute\path\collaboration-brief.docx
~~~

只读 review 会展示 Host 固定的目标、应用、读取/修改边界、精确输出位置、最多
7 次逐 effect 批准、停止条件和可能残留的部分文件；它不会连接 provider、启动
MCP、打开应用或创建 workflow state。正式 workflow 会再次显示同一 Scope Sheet，
只有精确输入 `START` 才会启动。明确的非交互调用方必须增加
`--acknowledge-scope`；该 flag 只允许进入原 workflow，不会预先批准任何桌面动作。
完整边界见 [Pre-run Review 契约](docs/PRE_RUN_REVIEW.md)。

模型根据新的 Chrome 观察自行选择已审核步骤并撰写 2–4 个要点；task 和模板
都不预写结论。工作流继续使用现有本地 approval 边界，不覆盖已有输出；保存后
会关闭精确 fixture、重新打开同一 DOCX，并通过 Runner/MCP 读回验证，最后只
输出有界元数据。完整边界见
[Public Web to Word 工作流契约](docs/PUBLIC_WEB_WORD_WORKFLOW.md)。

当其中一个 Runner loop 正在运行时，可在第二个本地终端请求协作式控制：

~~~powershell
guarded-desktop-agent task takeover --config C:\absolute\path\public-web-word.toml
guarded-desktop-agent task control --config C:\absolute\path\public-web-word.toml
# 只有 status=paused 且 authority=released 后，人才可操作桌面。
guarded-desktop-agent task resume --config C:\absolute\path\public-web-word.toml
~~~

`pause_requested` 只表示请求已记录，不表示暂停完成。显式 resume 会丢弃旧 approval
和 grounding，并要求先持久化一次 fresh observation，之后才允许新的 side effect。
已在执行或可能已执行的动作仍以 `UNKNOWN_OUTCOME` 终止，绝不自动重放。完整边界见
[协作式 Pause、Takeover 与 Resume](docs/COOPERATIVE_CONTROL.md)。

## 原始 MCP server 启动

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

$env:CUMCP_ALLOWLIST = "notepad.exe"
.\.venv\Scripts\guarded-desktop-mcp.exe
~~~

在 MCP 客户端的 stdio server 配置中，推荐填写虚拟环境内可执行文件的绝对
路径：

~~~json
{
  "command": "C:\\absolute\\path\\to\\guarded-desktop-agent\\.venv\\Scripts\\guarded-desktop-mcp.exe",
  "env": {
    "CUMCP_ALLOWLIST": "notepad.exe"
  }
}
~~~

不同 MCP 客户端的外层配置格式不同；上面的 command 和 env 内容可通用。
旧的 `computer-use-mcp` 与 `computer-use-agent` 命令仍作为兼容别名保留；
新配置应使用 `guarded-desktop-mcp` 与 `guarded-desktop-agent`。

## 推荐操作流程

审批卡正在等待时，可在另一个本地终端读取严格受限的只读 Inbox：

~~~powershell
guarded-desktop-agent approval inbox --config C:\absolute\path\agent.toml
guarded-desktop-agent approval inbox --config C:\absolute\path\agent.toml --json
~~~

它只显示 Host 验证过的 identity、固定动作分类、digest 和 expiry，不能批准、
拒绝、延期、接管、恢复、重试或 dispatch；`pending_at_last_record` 也不代表
Runner 一定仍然存活。生成的产品配置还会启用只有固定文案、没有操作按钮和
私密任务内容的 Windows 通知；真正的决定仍必须回到绑定的 Decision Card。
完整边界见 [Approval Inbox 与通知契约](docs/APPROVAL_INBOX.md)。

1. 使用 `ui_snapshot()` 获取控件及 `ref_N`，用 `screenshot()`/OCR 观察
   界面；如用户已配置，也可让模型按场景选择 `browser_snapshot()` 辅助读取
   JavaScript 渲染后的页面。
2. 默认 `click(ref=...)`、坐标点击、focused `type(text)` 和 `key(combo)`
   都走可见的 Windows OS 鼠标/键盘输入；这是 Win32 生成的 input，不是字面
   意义上的硬件信号。
3. 只有用户显式设置 `CUMCP_UIA_ACTIONS=1` 时，ref 点击/输入才走 UIA
   Invoke/ValuePattern；UIA 失败后绝不自动降级成坐标点击。
4. 每次动作后查看返回结果和审计日志。

## 已知限制

- `screenshot()` 只截取主显示器，目前没有 MCP 区域截图参数。
- 同一桌面共享前台窗口、鼠标和键盘，不能承诺安全的并行后台控制。
- Chromium 浏览器的 UIA 内容可能不完整；可选 Playwright CDP 只读观察没有
  真实浏览器/应用验收证据，也不会绕过登录、CAPTCHA 或反自动化挑战，遇到时
  应暂停并交还用户。
- VMware 辅助脚本只能启动已有虚拟机，不会创建系统、启动 guest MCP server
  或提供 host-to-guest 传输。

详细工具签名、配置和技术文档请以英文为准：
[完整项目总览](docs/PROJECT_OVERVIEW.md)和[文档索引](docs/README.md)。
