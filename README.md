# computer-use-mcp

一个**与模型无关（model-agnostic）**的 computer-use MCP 服务器：让任意支持 MCP 的 agent 壳（Claude Code / Codex / Cline 等）都能截屏并控制 **Windows** 桌面。

核心是**双模式输出**：

- `screenshot` —— 给**视觉模型**（Claude / GPT-4o / Qwen-VL / UI-TARS）看，按坐标点击
- `ui_snapshot` —— UIA 无障碍树（纯文本），给**纯文本模型**（如 DeepSeek）按控件 `ref` 点击

> 一个 server，多个 agent 壳复用；将来换 DeepSeek / 通义千问 / UI-TARS 等模型驱动时，**不用改 server**。

## 状态

✅ **MCP server + 完整安全层（可连接使用）** —— 记事本三步阶梯 + Contract v1.0 冻结 + 核心 ref 表 + MCP server 8 工具 + 安全层（闸门 / 确认 / 审计 / 急停 / 打码），全部实测通过。
- 架构：MCP server → 核心 `Session`（ref 表）→ 平台驱动（ports & adapters）；契约见 [docs/DRIVER_CONTRACT.md](docs/DRIVER_CONTRACT.md)
- 已实现：`src/computer_use_mcp/`（contract / dpi / core / gate / safety / audit / server + Windows 驱动）；冒烟 `scripts/smoke_*.py` 全过
- 后续可选：真 app 实测（微信/浏览器）、快照层级、多屏坐标、macOS/Linux 驱动。进度见 [docs/DESIGN.md](docs/DESIGN.md)

## 工具面（已实现 8 个）

感知（不闸门；password 字段在 snapshot 脱敏）：

| 工具 | 作用 |
| --- | --- |
| `screenshot` | 截图，返回图片（视觉模型用） |
| `ui_snapshot(scope)` | 窗口的 UIA 无障碍树，扁平列表 + 稳定 `ref`（文本模型用） |
| `find(query, scope)` | 按名字/角色找元素，只回匹配项，省 token |
| `list_windows` | 可见顶层窗口（含 owned 对话框） |

动作（先过**前台进程闸门**才执行）：

| 工具 | 作用 |
| --- | --- |
| `click({ref} 或 {x,y})` | 按 ref 调 UIA 模式（Invoke/SelectionItem，不受焦点遮挡）或坐标点击 |
| `type(text, ref?)` | 按 ref 写值（ValuePattern.SetValue）或向焦点发键 |
| `key(combo)` | 按键组合（如 `Ctrl+S`） |
| `activate_window(id)` | 置某窗口前台 |

## 技术栈（已定）

Python + [`mcp`](https://github.com/modelcontextprotocol/python-sdk) SDK + `mss`(截图) + `uiautomation`(UIA) + `psutil`(进程树) + `pillow`(标注)。鼠标键盘走 ctypes（`SetCursorPos`/`mouse_event`/`keybd_event`）+ `uiautomation.SendKeys`。
平台抽象层预留，Windows 优先，将来可扩展 macOS(AX) / Linux(AT-SPI)。

## 运行 / 连接

```bash
pip install -e .                         # 建议 venv，Python 3.11–3.13
# 配置 allowlist（逗号分隔进程名；默认 notepad.exe）
$env:CUMCP_ALLOWLIST = "notepad.exe,weixin.exe"   # PowerShell
computer-use-mcp                         # 启动（stdio transport）
```

在 MCP 壳（Claude Code / Cline 等）里把它登记为一个 stdio server（command = `computer-use-mcp`）即可。动作类工具只在 allowlist 内的 app 处于前台时执行，否则返回 `DENIED by gate`。

## 安全（DIY 必须自己造）

- ✅ **前台进程闸门 + allowlist**（进程树判定 + 瞬时重试）—— `gate.py`，动作类工具先过闸门
- ✅ **snapshot 脱敏**：password 控件不回 value
- ✅ **危险动作二次确认**（原生 Yes/No）、**操作审计日志**（JSONL）、**急停热键**（默认 Ctrl+Alt+Q）、**敏感窗口截图打码**（`CUMCP_REDACT_TITLES`）

## License

暂不定 / 私有 —— 目前不放 LICENSE 文件，纯本地项目；将来如开源再议。
