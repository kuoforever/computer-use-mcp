# computer-use-mcp（中文快速开始）

[English README](README.md) | [文档索引（英文）](docs/README.md)

> **状态：实验性、本机 Windows 桌面控制。** 英文文档是唯一的规范来源；本页提供中文快速开始。

computer-use-mcp 是一个与模型无关的 MCP 服务器，用于查看并控制
Windows 桌面应用。它同时提供面向视觉模型的截图，以及基于 Windows UI
Automation（UIA）的控件快照和稳定引用。

当前实现仅面向本机、明确授权的自动化任务。它不是后台 worker、远程控制
服务或通用浏览器自动化框架。

## 当前支持

- Windows；Python 3.11 至 3.13。
- stdio MCP transport。
- 主显示器截图和 UIA 控件发现。
- 八个 MCP 工具：`ui_snapshot`、`find`、`list_windows`、`screenshot`、
  `activate_window`、`click`、`type`、`key`。
- 默认安全模式：进程白名单、检测到人类输入时让路、危险 ref 点击确认、审计
  日志和急停热键。

macOS、Linux、多显示器坐标以及隔离 worker 编排都仍在路线图中，尚未实现。

## 安全提示

桌面动作会移动鼠标、切换焦点、输入文字和调用控件。请从
`safe_local` 开始，将白名单限制在测试应用（例如 Notepad），并先阅读
[英文配置与安全说明](docs/CONFIGURATION.md)。

`full_control_local` 会明确绕过前台白名单和人类输入让路机制；虽然仍保留
审计和急停，但只应在操作员明确授权接管本机桌面时使用。

## 安装与启动

~~~powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

$env:CUMCP_ALLOWLIST = "notepad.exe"
.\.venv\Scripts\computer-use-mcp.exe
~~~

在 MCP 客户端的 stdio server 配置中，推荐填写虚拟环境内可执行文件的绝对
路径：

~~~json
{
  "command": "C:\\absolute\\path\\to\\computer-use-mcp\\.venv\\Scripts\\computer-use-mcp.exe",
  "env": {
    "CUMCP_ALLOWLIST": "notepad.exe"
  }
}
~~~

不同 MCP 客户端的外层配置格式不同；上面的 command 和 env 内容可通用。

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
[文档索引](docs/README.md)。
