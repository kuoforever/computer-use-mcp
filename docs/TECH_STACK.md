# 技术栈 / Tech Stack — computer-use-mcp

> 本文按**预期实现版本**书写，记录目标系统使用的技术栈、平台边界和后续隔离 worker 的运行环境选择。
>
> This document describes the **target implementation** technology stack, platform boundaries, and runtime options for isolated workers.

## 1. 核心栈 / Core Stack

| 层 / Layer | 技术 / Technology | 用途 / Purpose |
| --- | --- | --- |
| 语言 / 运行时<br>Language / runtime | Python 3.11-3.13 | MCP server、通用核心、平台 driver<br>MCP server, shared core, and platform drivers |
| MCP | `mcp` Python SDK | 对外暴露 computer-use 工具<br>Expose computer-use tools |
| Transport | stdio | 供 Claude Code / Codex / Cline 等 MCP client 连接<br>Connect MCP clients such as Claude Code, Codex, and Cline |
| 打包 / Packaging | `pyproject.toml` / setuptools | 本地安装与命令行入口 `computer-use-mcp`<br>Local install and CLI entry point |
| 测试 / Testing | pytest | 核心逻辑、gate、安全、audit、fake driver<br>Core logic, gate, safety, audit, and fake driver tests |
| Lint / 格式<br>Lint / formatting | ruff | Python 代码质量检查<br>Python code quality checks |

## 2. Windows 桌面自动化栈 / Windows Desktop Automation Stack

| 技术 / Technology | 用途 / Purpose |
| --- | --- |
| Windows UI Automation / `uiautomation` | 读取无障碍树，执行 `Invoke` / `SetValue` / `SelectionItem`<br>Read accessibility trees and execute `Invoke`, `SetValue`, and `SelectionItem` |
| Win32 API / `ctypes` | 鼠标、键盘、前台窗口、DPI、窗口枚举、进程窗口关系<br>Mouse, keyboard, foreground windows, DPI, window enumeration, and process-window ownership |
| `mss` | 主屏帧缓冲截图<br>Main-screen framebuffer screenshots |
| `psutil` | 进程树、前台进程归属链、allowlist 判定辅助<br>Process trees, foreground owner chains, and allowlist support |
| Pillow | 截图标注、区域处理、截图脱敏辅助<br>Screenshot annotation, region processing, and redaction support |

鼠标键盘输入走 Win32 API / `ctypes`（例如 `SetCursorPos` / `mouse_event` / `keybd_event`）和必要的 `uiautomation.SendKeys` 兜底。项目不采用 `pyautogui`。

Mouse and keyboard input use Win32 API / `ctypes`, such as `SetCursorPos`, `mouse_event`, and `keybd_event`, with `uiautomation.SendKeys` only as a fallback. The project does not use `pyautogui`.

## 3. MCP 工具层 / MCP Tool Layer

目标工具分为感知和动作。

Target tools are split into perception and actions.

感知 / Perception:

- `screenshot`
- `ui_snapshot`
- `find`
- `list_windows`

动作 / Actions:

- `click`
- `type`
- `key`
- `activate_window`

工具层只处理 MCP schema、参数校验、内容返回和安全管线编排；具体桌面能力由 Driver Contract 提供。

The tool layer handles MCP schemas, parameter validation, returned content, and safety pipeline orchestration. Concrete desktop capabilities come from the Driver Contract.

## 4. 安全与控制层 / Safety and Control Layer

| 能力 / Capability | 技术 / 机制<br>Technology / Mechanism |
| --- | --- |
| allowlist gate | `safe_local` 的前台 owner-chain 授权<br>Foreground owner-chain authorization for `safe_local` |
| 进程树授权<br>Process-tree authorization | `psutil` + 平台进程归属链<br>`psutil` plus platform process ownership chains |
| 人机让路<br>Human coexistence | Windows `GetLastInputInfo` / 平台等价能力<br>Windows `GetLastInputInfo` or platform equivalents |
| 急停 / E-stop | 全局热键，触发后锁死动作直到重启 server<br>Global hotkey that locks actions until server restart |
| 危险动作确认<br>Dangerous-action confirmation | 原生系统确认对话框<br>Native system confirmation dialog |
| 审计 / Audit | JSONL action audit log |
| snapshot 脱敏<br>Snapshot redaction | password 控件不返回 value<br>Password controls do not return values |
| screenshot 脱敏<br>Screenshot redaction | 标题匹配敏感窗口后涂黑<br>Redact windows whose titles match sensitive patterns |

## 5. 浏览器与复杂应用栈 / Browser and Complex App Stack

浏览器、Electron、微信等复杂应用依赖：

Browsers, Electron apps, WeChat, and similar complex apps rely on:

- Chromium / Chrome UIA accessibility tree。
- Chromium / Chrome UIA accessibility trees.
- accessibility warmup 或稳定读取策略。
- Accessibility warmup or another stable-read strategy.
- 内容页 probe，用于判断截断、同名元素歧义、文本 run 合并和 parent ref 需求。
- Content-page probes to evaluate truncation, duplicate names, text-run merging, and parent-ref needs.
- 进程树 allowlist，覆盖渲染子进程和 owned 对话框。
- Process-tree allowlists that cover renderer subprocesses and owned dialogs.
- 对 canvas / 游戏类界面保留坐标路径。
- Coordinate paths for canvas or game-style surfaces.

## 6. 跨平台驱动候选 / Cross-Platform Driver Candidates

| 平台 / Platform | 技术 / Technology | 用途 / Purpose |
| --- | --- | --- |
| Windows | UIA + Win32 + `ctypes` | 主线 driver<br>Main driver |
| macOS | Accessibility API / AX、`pyobjc` 或 Swift helper | macOS driver |
| Linux | AT-SPI、X11 / Wayland 截图与输入能力 | Linux driver |

跨平台扩展通过实现 Driver Contract 接入。通用核心不直接依赖平台专属库。

Cross-platform extensions integrate by implementing the Driver Contract. The shared core does not directly depend on platform-specific libraries.

## 7. 真后台 worker / 隔离运行环境 / True Background Workers and Isolated Runtimes

完整后台操作者需要独立前台、鼠标、键盘和截图源，因此属于运行环境编排。

A full background operator needs its own foreground, mouse, keyboard, and screenshot source, so this is runtime orchestration rather than a normal driver branch.

优先路线 / Priority routes:

1. Windows VM；Windows Home 主机优先 VM，不把 RDP Host 作为默认路径。
   Windows VM; on Windows Home hosts, prefer a VM rather than RDP Host.
2. Windows 第二登录 Session（环境支持时）。
   Windows second login session when the environment supports it.
3. Linux Xvfb / 独立 DISPLAY。
   Linux Xvfb or independent DISPLAY.
4. macOS VM / 第二台机。
   macOS VM or a second machine.

相关候选 / Related candidates:

- VM 编排。
  VM orchestration.
- Linux Xvfb / Xephyr / 独立 X server。
  Linux Xvfb, Xephyr, or independent X server.
- Windows `PrintWindow` / DWM thumbnail / app-specific fallback，用于窗口级截图。
  Windows `PrintWindow`, DWM thumbnails, or app-specific fallbacks for window-level screenshots.
- Windows `CreateDesktop` / `SwitchDesktop` 只作为实验路线。
  Windows `CreateDesktop` / `SwitchDesktop` only as an experimental route.

隔离 worker 需要自己的 driver 实例、截图源、输入源、allowlist 和审计日志。

An isolated worker needs its own driver instance, screenshot source, input source, allowlist, and audit log.

## 8. 不采用或不默认采用 / Not Used or Not Enabled by Default

- `pyautogui`：鼠标键盘走 Win32 API / `ctypes`。
  `pyautogui`: mouse and keyboard use Win32 API / `ctypes`.
- 同桌面后台 ref 动作：受控 Notepad 探针确认 UIA `SetValue` 可在输入 tick 未变化时影响前台，不能作为承诺能力。
  Same-desktop background ref actions: a controlled Notepad probe confirmed UIA `SetValue` can affect foreground without an input-tick change and is not a promised capability.
- 同桌面完整后台操作者：共享鼠标、焦点和主屏截图，不能和用户稳定并行。
  Full same-desktop background operator: mouse, focus, and main-screen screenshots are shared and cannot run stably in parallel with the user.
- 大规模重写 contract：Driver Contract 变更必须由实现证据驱动。
  Large contract rewrites: Driver Contract changes must be driven by implementation evidence.
