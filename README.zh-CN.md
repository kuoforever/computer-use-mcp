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

## 当前支持

- Windows；Python 3.11 至 3.13。
- stdio MCP transport。
- 主显示器截图和 UIA 控件发现。
- 13 个 MCP 工具：`ui_snapshot`、`find`、`list_windows`、`screenshot`、
  `capture_region`、`ocr`、`document_text`、`activate_window`、`click`、
  `scroll`、`drag`、`type`、`key`。
- 默认安全模式：进程白名单、检测到人类输入时让路、危险 ref 点击确认、审计
  日志和急停热键。

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
文档约定的凭据环境变量、MCP 可执行文件和工作目录，然后短暂启动已安装的 MCP
子进程，通过 `initialize` / `list_tools` 核对完整的 13-tool 契约。它输出固定
JSON；全部通过时退出码为 `0`，遇到一个可操作故障时为 `2`。它不会请求
provider、调用 MCP tool、读取桌面内容或执行桌面动作；但 MCP 启动期间仍可能
创建配置的 audit 目录并启动急停按键轮询，随后子进程会被关闭。

如使用 Claude，将安装 extra、provider 名和环境变量分别替换为
`agent-anthropic`、`anthropic` 和 `ANTHROPIC_API_KEY`。当前 Desktop Ask
已有一次 OpenAI/Windows/Notepad exact-candidate 结果；它不证明其他
provider、application、desktop action 或 release artifact。

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

1. 使用 `ui_snapshot()` 获取控件及 `ref_N` 引用，或用 `screenshot()`
   观察界面。
2. UIA 可识别控件时，优先使用 `click(ref="ref_N")` 和
   `type(text, ref="ref_N")`。
3. 仅在 canvas 或其他 UIA 无法访问的目标上使用坐标点击
   `click(x=..., y=...)`。
4. 每次动作后查看返回结果和审计日志。

## 已知限制

- `screenshot()` 只截取主显示器，目前没有 MCP 区域截图参数。
- 同一桌面共享前台窗口、鼠标和键盘，不能承诺安全的并行后台控制。
- Chromium 浏览器的 UIA 内容可能不完整，需要按实际应用验证。
- VMware 辅助脚本只能启动已有虚拟机，不会创建系统、启动 guest MCP server
  或提供 host-to-guest 传输。

详细工具签名、配置和技术文档请以英文为准：
[完整项目总览](docs/PROJECT_OVERVIEW.md)和[文档索引](docs/README.md)。
