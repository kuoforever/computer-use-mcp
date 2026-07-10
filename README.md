# computer-use-mcp

一个**与模型无关（model-agnostic）**的 computer-use MCP 服务器：让任意支持 MCP 的 agent 壳（Claude Code / Codex / Cline 等）都能截屏、理解并控制桌面应用。

A **model-agnostic** computer-use MCP server that lets any MCP-capable agent shell, such as Claude Code, Codex, or Cline, capture, understand, and control desktop applications.

本文按**目标实现版本**书写，描述项目预期完成后的能力边界。当前进度、开工顺序和历史验证记录分别见 [docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md) 与 [HANDOFF.md](HANDOFF.md)。

This document describes the **target implementation** and its intended capability boundary. For current progress, implementation order, and historical validation notes, see [docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md) and [HANDOFF.md](HANDOFF.md).

## 目标形态 / Target State

核心是**双模式感知 + 双路径动作**：

The core model is **dual-mode perception + dual-path actions**:

- `screenshot`：给视觉模型看屏幕，用坐标执行视觉 grounding。
- `screenshot`: provides screen images for vision models and coordinate-based grounding.
- `ui_snapshot`：给文本模型读无障碍树，用稳定 `ref` 操作控件。
- `ui_snapshot`: provides an accessibility tree for text-only models and stable `ref`-based control.
- `click({x,y})`：服务视觉模型和 UIA 抓不到的 canvas / 游戏类界面。
- `click({x,y})`: supports vision models and canvas / game-style surfaces that accessibility APIs cannot capture.
- `click({ref})` / `type(text, ref)`：直接调用 UIA / AX / AT-SPI 模式，不合成坐标点击。
- `click({ref})` / `type(text, ref)`: directly call UIA / AX / AT-SPI patterns instead of synthesizing coordinate clicks.

一个 server 可以被多个 MCP client 复用。换模型、换 agent 壳或换桌面平台时，核心 MCP 工具语义保持稳定。

One server can be reused by multiple MCP clients. When the model, agent shell, or desktop platform changes, the core MCP tool semantics stay stable.

## 架构 / Architecture

目标架构是 ports & adapters：

The target architecture follows ports and adapters:

```text
MCP client
  └─ stdio
      └─ server.py / MCP tools
          ├─ core.py / Session, refs, snapshot serialization
          ├─ gate.py / safety.py / audit.py
          └─ contract.py / Driver Contract
              └─ platform driver
                  ├─ Windows UIA + Win32
                  ├─ macOS AX
                  └─ Linux AT-SPI
```

核心约束：

Core constraints:

- 通用核心不 import 平台专属模块。
- The shared core does not import platform-specific modules.
- `contract.py` 是核心和平台驱动之间的唯一边界。
- `contract.py` is the only boundary between the core and platform drivers.
- 截图像素、控件 bbox 和坐标点击共享同一坐标空间。
- Screenshot pixels, control bounding boxes, and coordinate clicks share one coordinate space.
- 动作类工具默认先经过安全闸门、危险确认和审计。
- Action tools go through the safety gate, dangerous-action confirmation, and audit by default.

架构细节见 [docs/DESIGN.md](docs/DESIGN.md)，驱动边界见 [docs/DRIVER_CONTRACT.md](docs/DRIVER_CONTRACT.md)。

See [docs/DESIGN.md](docs/DESIGN.md) for architecture details and [docs/DRIVER_CONTRACT.md](docs/DRIVER_CONTRACT.md) for the driver boundary.

## 目标工具面 / Target Tool Surface

感知工具：

Perception tools:

| 工具 / Tool | 作用 / Purpose |
| --- | --- |
| `screenshot(region?)` | 返回屏幕或区域截图，供视觉模型使用 / Returns a full-screen or regional screenshot for vision models |
| `ui_snapshot(scope?)` | 返回可交互控件列表、稳定 `ref`、bbox、状态和值摘要 / Returns interactive controls, stable refs, bounding boxes, states, and value summaries |
| `find(query, scope?)` | 在 UI snapshot 中按名称 / 角色缩小结果，降低 token 成本 / Narrows UI snapshot results by name or role to reduce token cost |
| `list_windows()` | 枚举可见顶层窗口和 owned 对话框 / Lists visible top-level windows and owned dialogs |

动作工具：

Action tools:

| 工具 / Tool | 作用 / Purpose |
| --- | --- |
| `click({ref})` | 按控件 ref 调用 Invoke / SelectionItem 等无障碍模式 / Invokes accessibility patterns such as Invoke or SelectionItem by control ref |
| `click({x,y})` | 按共享像素坐标执行鼠标点击 / Performs a mouse click in the shared pixel coordinate space |
| `type(text, ref?)` | 有 ref 时写入目标控件；无 ref 时向当前焦点输入 / Writes to a target control when a ref is provided; otherwise types into current focus |
| `key(combo)` | 发送组合键 / Sends a key combination |
| `activate_window(id)` | 激活目标窗口，作为 foreground-required 动作 / Activates a target window as a foreground-required action |

## 安全模型 / Safety Model

安全默认拒绝：

Safety is deny-by-default:

- 动作类工具默认要求目标处在授权边界内。
- Action tools require the target to be inside an authorized boundary by default.
- allowlist 使用进程树归属链，而不是只看单个进程名。
- The allowlist uses process ownership chains, not only individual process names.
- password 控件不返回明文 value。
- Password controls never return plaintext values.
- 敏感窗口截图需要打码。
- Sensitive windows are redacted in screenshots.
- 危险动作需要二次确认。
- Dangerous actions require a second confirmation.
- 所有动作进入 JSONL 审计日志。
- All actions are written to a JSONL audit log.
- 急停热键触发后，所有动作锁死直到 server 重启。
- After the e-stop hotkey is triggered, all actions are locked until the server restarts.
- 同桌面后台 ref 动作不作为能力保证：受控 Notepad 探针确认 `SetValue` 会在输入 tick 未变化时切换前台。
- Same-desktop background ref actions are not a guaranteed capability: a controlled Notepad probe confirmed that `SetValue` changes foreground without an input-tick change.

运行模式 / Operating modes:

- `safe_local`：默认模式，保留 allowlist、人机让路、危险确认、审计和急停。
- `full_control_local`：显式授权 agent 接管本机桌面，可抢前台、使用鼠标和键盘；急停与审计始终保留。
- `isolated_worker`：agent 在独立 VM / Session 中完整操作，主桌面可继续游戏或工作。

质量属性和验收信号见 [docs/QUALITY_ATTRIBUTES.md](docs/QUALITY_ATTRIBUTES.md)。

See [docs/QUALITY_ATTRIBUTES.md](docs/QUALITY_ATTRIBUTES.md) for quality attributes and acceptance signals.

## 技术栈 / Tech Stack

目标主栈：

Target stack:

- Python 3.11-3.13
- MCP Python SDK + stdio transport
- Windows UI Automation / Win32 API / `ctypes`
- `mss` 截图、`psutil` 进程树、Pillow 图像处理
- `mss` for screenshots, `psutil` for process trees, and Pillow for image processing
- macOS AX / Linux AT-SPI 作为平台驱动扩展方向
- macOS AX and Linux AT-SPI as platform driver extension paths
- VM / 独立 Session / Xvfb 作为真后台 worker 的运行环境方向
- VM, independent sessions, and Xvfb as runtime options for true background workers

完整技术边界见 [docs/TECH_STACK.md](docs/TECH_STACK.md)。

See [docs/TECH_STACK.md](docs/TECH_STACK.md) for the full technology boundary.

## 目标运行方式 / Target Run Flow

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

# 默认安全模式；全权限与隔离 worker 模式由运行时配置选择。
$env:CUMCP_ALLOWLIST = "notepad.exe,weixin.exe"
.\.venv\Scripts\computer-use-mcp.exe

# 显式接管本机桌面；保留急停和审计。
$env:CUMCP_MODE = "full_control_local"
# 可选：全权限模式下仍要求危险动作确认。
$env:CUMCP_DANGEROUS_CONFIRM = "1"
.\.venv\Scripts\computer-use-mcp.exe
```

### VMware isolated worker prototype

For true background operation on Windows Home, the first isolated-worker route is
VMware Workstation Pro with an existing Windows guest VM. Create and prepare the
guest manually, then let the host helper start it and invoke the worker through
VMware Tools.

```powershell
# Host: point the helper at an existing VMware .vmx file.
$env:CUMCP_WORKER_VMX = "D:\VMs\cumcp-worker\cumcp-worker.vmx"
.\.venv\Scripts\python.exe scripts\vmware_worker.py doctor
.\.venv\Scripts\python.exe scripts\vmware_worker.py start --wait-tools

# Guest: the repo is already cloned at C:\work\computer-use-mcp and .venv exists.
# Prefer env vars for guest credentials so passwords do not land in shell history.
$env:CUMCP_VM_GUEST_USER = "worker"
$env:CUMCP_VM_GUEST_PASSWORD = "<guest password>"
.\.venv\Scripts\python.exe scripts\vmware_worker.py run-worker --no-wait
```

This prototype validates an independent desktop and worker process. Host-to-guest
MCP transport and multi-worker orchestration are later P9 work.

在支持 MCP 的 agent 壳里登记为 stdio server：
Register it as a stdio server in an MCP-capable agent shell:

```json
{
  "command": "computer-use-mcp"
}
```

## 文档地图 / Documentation Map

| 文档 / Document | 作用 / Purpose |
| --- | --- |
| [docs/DESIGN.md](docs/DESIGN.md) | 目标架构与关键设计约束 / Target architecture and key design constraints |
| [docs/DRIVER_CONTRACT.md](docs/DRIVER_CONTRACT.md) | 通用核心和平台驱动的契约 / Contract between shared core and platform drivers |
| [docs/TECH_STACK.md](docs/TECH_STACK.md) | 目标技术栈和平台边界 / Target technology stack and platform boundaries |
| [docs/QUALITY_ATTRIBUTES.md](docs/QUALITY_ATTRIBUTES.md) | 质量属性、设计约束和验收信号 / Quality attributes, design constraints, and acceptance signals |
| [docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md) | 从当前代码推进到目标版本的开工顺序 / Implementation path from current code to target version |
| [HANDOFF.md](HANDOFF.md) | 当前交接状态、历史验证记录和已知坑 / Current handoff state, historical validation notes, and known pitfalls |

## License

目标开源许可尚未确定；未定前按私有本地项目处理。

The target open-source license is not decided yet. Until then, treat the project as private and local.
