# Design

> **Status: implemented Windows architecture with planned extension points.**
> This document explains boundaries and decisions. For the current user-facing
> API, use [the tool reference](TOOLS.md), not this design document.

For the end-to-end feature, implementation, quality, evidence, and ownership
map, start with [Project overview](PROJECT_OVERVIEW.md).

## Architecture

The project follows a small ports-and-adapters design. The shared core owns
model-facing state and policy; a platform driver owns native desktop APIs.

~~~text
MCP client
  -> stdio
      -> server.py: FastMCP schemas and action orchestration
          -> core.py: Session, refs, snapshot serialization
          -> gate.py / human_activity.py / safety.py / audit.py
          -> contract.py: platform-neutral Driver interface
              -> drivers/windows.py: UIA, Win32, capture, process ownership
~~~

The core does not import a platform driver. The Windows driver is loaded at the
server boundary when no driver is explicitly supplied.

## Current component responsibilities

| Component | Responsibility |
| --- | --- |
| `server.py` | Exposes thirteen MCP tools and applies runtime guard behavior. |
| `core.py` | Maintains session-scoped `ref_N` handles, serializes snapshots, and retries one stale ref relocation. |
| `contract.py` | Defines the typed Driver boundary and shared data structures. |
| `drivers/windows.py` | Uses UIA/Win32, screen capture, and process inspection to implement the contract. |
| `gate.py` | Matches the foreground window's process ancestry against the safe-mode allowlist. |
| `human_activity.py` | Yields safe-mode actions after recent local input without installing an input listener. |
| `safety.py` | Provides dangerous ref-click detection, native confirmation, e-stop, and screenshot blackout helpers. |
| `audit.py` | Writes bounded JSONL action records. |

## Design invariants

### Model and client independence

The server exposes MCP tools rather than model-specific prompts or browser
automation APIs. A client can use screenshot-based visual grounding or
UIA-based refs without changing the core tool semantics.

### Two observation paths

- `screenshot()` gives vision-capable clients a primary-display PNG.
- `ui_snapshot()` provides a flat UIA control list for text-first clients.
- `find(query)` narrows a snapshot to reduce context cost.

The current MCP screenshot surface is deliberately narrower than the internal
driver contract: it has no region argument and captures only the primary
display.

### Two action paths

- `click(ref=...)` uses the target's accessibility pattern where available:
  invoke, selection, or value-setting.
- `click(x=..., y=...)` uses a physical coordinate click in the current
  primary-display pixel space.

Ref actions must not be silently converted to center-of-bounding-box clicks.
If a native control is stale, the session makes at most one role-and-name
relocation attempt, then returns an explainable error.

### One coordinate model, with a current boundary

Within the supported primary display, screenshot pixels, UIA bounding boxes, and
coordinate clicks use the same DPI-aware pixel grid. The current implementation
does **not** offer a validated virtual-desktop or multi-monitor coordinate
model. Do not extrapolate this invariant beyond the primary display.

## Action safety flow

In `safe_local`, `click`, `type`, and `key` follow this effective flow:

~~~text
request
  -> e-stop check
  -> recent-human-input check
  -> foreground process-ancestry allowlist check
  -> dangerous ref-click confirmation, when applicable
  -> final e-stop check
  -> final single-observation foreground allowlist check
  -> native driver action
  -> audit record
  -> result
~~~

The final checks do not wait for human-idle evidence or retry foreground
flicker; they reject when authority changed during either earlier wait.
`activate_window` is e-stop/human-activity guarded and audited, but
intentionally skips both foreground allowlist checks because it is the
operation that makes a listed window foreground. `full_control_local` bypasses
the human and allowlist checks while retaining both e-stop checks and audit. See
[Configuration and safety](CONFIGURATION.md) for exact runtime behavior.

## Human coexistence and background work

A Windows desktop has one foreground window, pointer, and keyboard focus. A
controlled UIA action can still affect foreground state, so direct UIA patterns
must not be advertised as generally background-safe.

The current design therefore yields when a human recently interacted with the
desktop in safe mode. True isolation requires an independent desktop runtime
such as a VM, separate session, or independent display server. That is
architecture direction, not a currently exposed `CUMCP_MODE`.

## Browser and complex-application behavior

Chromium-family browsers may build their accessibility tree lazily. The Windows
driver performs a best-effort warm-up for Chrome, Chromium, and Edge snapshots,
and reports an explicit incomplete-content hint when the tree still resembles
browser chrome only.

The long-term product boundary is universal GUI interaction, not a UIA-only
automation server. Browser windows are one application class within that
boundary. Pixel interaction remains the universal fallback; UIA, bounded OCR,
document-text extraction, and optional browser-native adapters may improve
grounding when available. The current runtime does not yet implement a generic
browser adapter and does not claim to bypass site challenges or automation
controls.

Validate each complex application with a read-only probe before relying on
snapshot shape, duplicate names, truncation behavior, process ancestry, or the
availability of static document text. See [Observation contract](OBSERVATION_CONTRACT.md)
for the planned multi-source observation model.

## Long-running orchestration

Day-scale work must not depend on one provider context or one Codex session.
The Agent Host should execute bounded work units, persist a cursor and item
ledger, and resume from durable checkpoints without replaying uncertain side
effects. Conversation context is an operator interface, not the source of truth
for task progress. See [Long-running tasks](LONG_RUNNING_TASKS.md) and
[Token efficiency](TOKEN_EFFICIENCY.md).

## Planned extension points

The Driver Contract is intentionally broad enough for native macOS AX and Linux
AT-SPI drivers, but neither exists today. Isolated-worker orchestration would
give each worker its own driver instance, screenshot source, input source,
allowlist, and audit log. It must not be implemented by stealing foreground on
the user's desktop.

See [Tech stack](TECH_STACK.md) for planned runtime options and
[Roadmap](EXECUTION_PLAN.md) for sequencing.
