# computer-use-mcp

[中文快速开始](README.zh-CN.md) | [Documentation](docs/README.md)

> **Status: experimental, local Windows desktop control.** The English documentation is canonical.

computer-use-mcp is a model-agnostic MCP server for inspecting and controlling
Windows desktop applications. It combines screenshots for vision-capable agents
with UI Automation (UIA) snapshots and stable element references for text-first
agents.

It is intended for local, explicitly authorized desktop automation. The long-
term direction is a universal GUI agent: pixel input remains the fallback while
UIA, OCR, document text, and optional browser adapters provide progressively
more structured observations. The current runtime is still a foreground Windows
MCP server, not a background worker or a complete browser automation framework.

## Supported today

- Windows only; Python 3.11 through 3.13.
- Stdio MCP transport.
- Primary-display screenshots and UIA-based control discovery.
- Eight MCP tools: `ui_snapshot`, `find`, `list_windows`, `screenshot`,
  `activate_window`, `click`, `type`, and `key`.
- A safe default mode with an allowlist, human-activity yielding, dangerous
  ref-click confirmation, audit logging, and an emergency-stop hotkey.

macOS, Linux, multi-monitor grounding, and isolated-worker orchestration are
roadmap items, not current product capabilities.

## Safety first

Desktop actions can move the pointer, change focus, type text, and invoke UI
controls. Start with `safe_local`, keep the allowlist narrow, and use a
non-sensitive test application such as Notepad.

`full_control_local` deliberately bypasses the foreground allowlist and
human-activity yielding checks. It still has audit logging and an emergency
stop, but it should be used only when an operator explicitly intends to hand
over the local desktop.

Read [Configuration and safety](docs/CONFIGURATION.md) before enabling action
tools.

## Quick start

Create a virtual environment and install the package:

~~~powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
~~~

Run the server in its default safe mode. The example limits foreground actions
to Notepad:

~~~powershell
$env:CUMCP_ALLOWLIST = "notepad.exe"
.\.venv\Scripts\computer-use-mcp.exe
~~~

Register the executable with an MCP client using that client's stdio-server
configuration. Prefer an absolute executable path so the client does not depend
on an activated virtual environment:

~~~json
{
  "command": "C:\\absolute\\path\\to\\computer-use-mcp\\.venv\\Scripts\\computer-use-mcp.exe",
  "env": {
    "CUMCP_ALLOWLIST": "notepad.exe"
  }
}
~~~

The exact configuration wrapper varies by MCP client; the command and
environment values above are the portable part.

## Typical workflow

1. Call `ui_snapshot()` to obtain a flat list of interactive controls and
   their `ref_N` handles, or call `screenshot()` for visual inspection.
2. Prefer `click(ref="ref_N")` and `type(text, ref="ref_N")` when UIA
   exposes the target. These use accessibility patterns rather than synthetic
   coordinate clicks.
3. Use `click(x=..., y=...)` only for visual/canvas-style targets that UIA
   cannot expose. Coordinates share the primary-display pixel space shown by
   `screenshot()`.
4. Inspect the returned result and audit log before proceeding with another
   action.

## Tool surface

| Tool | Current behavior |
| --- | --- |
| `ui_snapshot(scope="foreground")` | Returns a flat, capped UIA control list with session-scoped refs. |
| `find(query, scope="foreground")` | Returns a smaller matching subset of a UIA snapshot. |
| `list_windows()` | Lists visible top-level windows, including owned dialogs. |
| `screenshot()` | Returns a PNG of the primary display; it has no MCP region parameter. |
| `activate_window(window_id)` | Attempts to restore and activate a listed window; success requires the driver to verify that it became foreground. |
| `click(ref=...)` / `click(x=..., y=...)` | Invokes an accessible control or performs a coordinate click. |
| `type(text, ref=None)` | Sets an accessible value when a ref is supplied, otherwise types into focus. |
| `key(combo)` | Sends a key chord to the foreground window. |

See the exact parameters, ref lifecycle, safeguards, and errors in
[Tool reference](docs/TOOLS.md).

## Limitations

- `screenshot()` captures the primary display only. Multi-monitor coordinate
  support is not yet implemented.
- A shared desktop has one foreground window, pointer, and keyboard focus.
  This project does not promise safe, parallel background control on that
  desktop.
- Chromium-family UIA trees may be incomplete until accessibility content is
  exposed. Browser support is limited and should be verified per application.
- The VMware helper can start an existing VM, but it does not create the guest,
  start its MCP server, or provide host-to-guest MCP transport.
- Screenshot redaction is title-substring based; it is not comprehensive secret
  detection.

## Documentation

| Need | Read |
| --- | --- |
| Understand the complete project, every feature family, implementation path, quality attribute, status, and next gate | [Project overview](docs/PROJECT_OVERVIEW.md) |
| Find the right document | [Documentation index](docs/README.md) |
| See what is implemented, verified, or still planned | [Capability status](docs/CAPABILITY_STATUS.md) |
| Configure modes, safeguards, and environment variables | [Configuration and safety](docs/CONFIGURATION.md) |
| Use the MCP API exactly | [Tool reference](docs/TOOLS.md) |
| Understand the implementation architecture | [Design](docs/DESIGN.md) |
| Implement a platform driver | [Driver Contract](docs/DRIVER_CONTRACT.md) |
| Test or maintain the project | [Development](docs/DEVELOPMENT.md) and [Maintainer handoff](HANDOFF.md) |
| See completed and future work | [Roadmap](docs/EXECUTION_PLAN.md) |
| Review the planned full Agent Host | [Agent implementation plan](docs/AGENT_IMPLEMENTATION_PLAN.md) |
| Design day-scale resumable work | [Long-running tasks](docs/LONG_RUNNING_TASKS.md) |
| Run staged real-application campaigns and coverage benchmarks | [Application evaluation matrix](docs/APPLICATION_EVALUATION_MATRIX.md) |
| Review the planned one-campaign complete-product showcase | [Universal GUI demo](docs/UNIVERSAL_GUI_DEMO.md) |
| Reduce model context and observation cost | [Token efficiency](docs/TOKEN_EFFICIENCY.md) |
| Review the planned computer-use indicator, progress UI, and decision experience | [Operator experience](docs/OPERATOR_EXPERIENCE.md) |

## License

Licensed under the [Apache License 2.0](LICENSE). You may use, modify, and
distribute this project, including commercially, subject to the license terms.
