# computer-use-mcp

一个**与模型无关（model-agnostic）**的 computer-use MCP 服务器：让任意支持 MCP 的 agent 壳（Claude Code / Codex / Cline 等）都能截屏并控制 **Windows** 桌面。

核心是**双模式输出**：

- `screenshot` —— 给**视觉模型**（Claude / GPT-4o / Qwen-VL / UI-TARS）看，按坐标点击
- `ui_snapshot` —— UIA 无障碍树（纯文本），给**纯文本模型**（如 DeepSeek）按控件 `ref` 点击

> 一个 server，多个 agent 壳复用；将来换 DeepSeek / 通义千问 / UI-TARS 等模型驱动时，**不用改 server**。

## 状态

🚦 **v0.0 已落地** —— 只读冒烟通过：`capture_screen` + `get_tree` 在 Win11 上坐标 / DPI 完全对齐，A 路径（进程内 Python）实测拍板。
- 架构：通用核心 + 平台原生驱动（ports & adapters）
- 已实现：`src/computer_use_mcp/`（contract / dpi / Windows 驱动）+ `scripts/smoke_v0.py`
- 下一步：v0.1（UIA 写一行文字）。完整设计见 [docs/DESIGN.md](docs/DESIGN.md)；驱动契约见 [docs/DRIVER_CONTRACT.md](docs/DRIVER_CONTRACT.md)

## 计划的工具面（tool surface）

| 工具 | 作用 |
| --- | --- |
| `screenshot` | 截图，返回图片（视觉模型用） |
| `ui_snapshot` | 前台窗口的 UIA 无障碍树，扁平列表 + 稳定 `ref`（文本模型用） |
| `find(query)` | 按名字/角色找元素，只回匹配项，省 token |
| `click({x,y} 或 {ref})` | 坐标点击 或 UIA 模式调用（Invoke/SelectionItem） |
| `type(text)` | 输入文字（优先 ValuePattern.SetValue） |
| `key(combo)` | 按键组合 |

## 技术栈（已定）

Python + [`mcp`](https://github.com/modelcontextprotocol/python-sdk) SDK + `mss`(截图) + `uiautomation`(UIA) + `pyautogui`(鼠标键盘)。
平台抽象层预留，Windows 优先，将来可扩展 macOS(AX) / Linux(AT-SPI)。

## 安全（DIY 必须自己造）

前台进程闸门 + allowlist、敏感字段在 snapshot 脱敏、敏感窗口截图打码、危险动作二次确认、操作审计日志、全局急停热键。详见 DESIGN。

## License

暂不定 / 私有 —— 目前不放 LICENSE 文件，纯本地项目；将来如开源再议。
