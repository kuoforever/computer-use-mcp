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

项目级自主行动应在 Host 配置中设置 `mode = "agentic_actions"` 和
`require_approval_for_actions = false`，同时让 MCP 保持 `safe_local`。这样只会
取消逐动作审批，不会取消白名单、人类输入让路、预算、急停、审计和未知结果
禁止重放。

`full_control_local` 会明确绕过前台白名单和人类输入让路机制；虽然仍保留
审计和急停，但只应在操作员明确授权接管本机桌面时使用。

## 安装与启动

~~~powershell
py -3 -m venv .venv
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
