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
          -> native_authority.py: call-scoped native-mutation checkpoints
          -> contract.py: platform-neutral Driver interface
              -> drivers/windows.py: UIA, Win32, capture, process ownership
~~~

The core does not import a platform driver. The Windows driver is loaded at the
server boundary when no driver is explicitly supplied.

## Current component responsibilities

| Component | Responsibility |
| --- | --- |
| `server.py` | Exposes thirteen MCP tools and applies runtime guard behavior. |
| `core.py` | Maintains session-scoped `ref_N` handles, serializes snapshots, and retries one eligible explicit-window stale ref relocation. |
| `contract.py` | Defines the typed Driver boundary and shared data structures. |
| `drivers/windows.py` | Uses UIA/Win32, screen capture, and process inspection to implement the contract. |
| `gate.py` | Matches the foreground window's process ancestry against the safe-mode allowlist. |
| `human_activity.py` | Yields safe-mode actions after recent local input without installing an input listener. |
| `native_authority.py` | Carries one server-owned non-waiting authority probe through a single driver action call and tracks whether native dispatch has started. |
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
- `list_windows()` reports top-level window ids and direct owners. A completely
  successful call atomically replaces the MCP instance's activation bindings.

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
relocation attempt inside the explicit window-id scope token that first minted
that ref, then returns an explainable error. Later snapshot/find calls do not
replace this per-ref relocation scope. A successful relocation updates the
cached Node and both directions of the native/ref binding together; a candidate
already owned by another ref fails closed without a second semantic action. The
ref path never falls back to coordinates.

`foreground` and `all` are dynamic selectors, not resolved physical-window
identities. A ref minted through either token fails `STALE_ELEMENT` immediately
after its original native handle reports stale, without a relocation tree query,
candidate action, or binding mutation. The caller must observe again. Only an
explicit window-id token can use the bounded relocation path, so this rule needs
no new Driver/TreeResult identity evidence and keeps contract `1.0.0` unchanged.

### One coordinate model, with a current boundary

Within the supported primary display, screenshot pixels, UIA bounding boxes, and
coordinate clicks use the same DPI-aware pixel grid. The current implementation
does **not** offer a validated virtual-desktop or multi-monitor coordinate
model. Do not extrapolate this invariant beyond the primary display.

## Action safety flow

In `safe_local`, all six action tools follow this effective flow (activation
keeps the foreground exceptions described below):

~~~text
request
  -> e-stop check
  -> bounded stable human-idle check and call-scoped input capture
  -> foreground process-ancestry allowlist check
  -> dangerous ref-click confirmation and exact input capture, when applicable
  -> final e-stop check
  -> final single-observation foreground allowlist check
  -> final non-waiting human-idle and input-capture comparison
  -> for activation, recheck the listed target's direct owner identity
  -> open one call-scoped native-action boundary
  -> Session and native driver action
       -> before each driver-controlled native mutation:
            recheck e-stop, applicable foreground, safe-local human input,
            and the activation target identity when applicable
  -> after activation returns, recheck its target identity before success
  -> audit record
  -> result
~~~

The final checks do not wait for human-idle evidence or retry foreground
flicker. The human check samples the platform input tick before and after its
idle-age observation and rejects unavailable evidence, an internally changing
tick, or any tick newer than the call's readiness capture. An affirmative
dangerous confirmation may supply its exact post-dialog tick only to that
click's final check; this one-call exception is not stored, is not agent-input
attribution, and cannot authorize the next action. Windows input events sharing
one `GetLastInputInfo` millisecond tick remain indistinguishable at the platform
boundary.

The final server check is not a lease. Driver pacing, pointer steps, key/mouse
events, UIA calls, and activation mutations each use the same call-scoped
controller immediately before the next native API. After a known-returning
native-input event, one exact input tick is permitted only inside that call so
the next checkpoint does not yield to the driver's own event. Physical input in
the small window between native return and that capture can still be
misattributed; no source-tagging or global input hook is claimed.

`activate_window` captures an instance-local binding at call entry and never
follows a later concurrent binding. Only the MCP `list_windows` tool can replace
that table, using the same complete structured window list that produced its
successful text result; screenshot, OCR, and region-redaction enumerations do
not. The identity is the exact direct-owner `(pid, executable name)` paired with
the window id. Title, geometry, foreground state, and process ancestry are not
identity. Missing, invalid, duplicate, disappeared, or owner-drifted targets
fail closed and invalidate only the still-current captured binding, so a fresh
successful `list_windows` is required before a replacement can be activated.

The target probe runs outside the foreground/human mode exception, immediately
before every activation mutation, and once after the Driver returns. Inside a
mutation checkpoint, target enumeration runs first; the non-waiting e-stop and
applicable human/foreground checks follow, keeping volatile human authority
closest to the native attempt. This is a bounded TOCTOU check, not an atomic
Windows identity lease: the current Driver contract has no process-creation
token and cannot distinguish an extreme reuse of the same window id, PID, and
executable name. Stronger native identity evidence remains outside contract
`1.0.0`.

Authority loss before the first native attempt stays rejected/not-dispatched.
Loss after an attempt stops target progress and becomes fixed
`NATIVE_AUTHORITY_LOST` with `UNKNOWN_OUTCOME / DISPATCHED`. Independently, if a
Windows action returns failure or raises after the call-scoped boundary has
recorded at least one native dispatch attempt, the server replaces that cause
with the fixed redacted `NATIVE_OUTCOME_UNKNOWN` envelope. This is a server-owned
certainty code, not a Driver error code; failures with zero recorded native
attempts retain their existing result and certainty semantics.

The Runner terminalizes either post-attempt unknown outcome, invalidates the MCP
generation, and never verifies, continues, recovers, or replays the action. Only
a bounded safety unwind may release a key/button or detach an input queue already
acquired by the call. It may clear passive feedback without presentation delay,
but it does not restore the pointer, window, or application state.

A side-effect result with the exact `REJECTED / NOT_DISPATCHED / HUMAN_ACTIVE`
or `REJECTED / NOT_DISPATCHED / DENIED_BY_GATE` tuple is known not dispatched,
but also proves that the authority behind the Host's last observation yielded.
The first code records loss of current human-idle authority; the second records
loss of the live foreground gate. The Runner therefore clears its verified
observation and `GroundingState` before the next checkpoint and continuation
completion. Only a fresh successful observation can restore the corresponding
side-effect authority; observation-shaped results, other certainty tuples, and
unrelated rejections retain their existing grounding behavior.

Focused `type` sends literal Unicode scalars as ordered UTF-16 `SendInput`
batches with a checkpoint between scalars. The old library-specific brace/chord
grammar is intentionally excluded; reviewed chords use `key`.
`activate_window` is e-stop/human-activity guarded and audited, but
intentionally skips both foreground allowlist checks because it is the
operation that makes a listed window foreground. Its observed-owner binding and
target probes apply in both control modes. `full_control_local` bypasses the
human and allowlist checks while retaining e-stop, activation identity, and
audit. See [Configuration and safety](CONFIGURATION.md) for exact runtime
behavior.

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
