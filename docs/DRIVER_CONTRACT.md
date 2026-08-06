# Driver Contract v1.0

> **Status: version 1.0.0 interface; Windows is the only implementation.**
> This is the normative boundary between the shared core and a native desktop
> driver. It is not a promise that every contract feature is exposed by the
> current MCP server.

## Purpose and invariants

The contract keeps platform-native code out of the core. It defines:

1. Native desktop primitives and shared data structures.
2. A common pixel-space representation for a capture and its UI bounding boxes.
3. Driver-provided window/process ownership chains for the safe-mode gate.
4. Driver-side pruning so the core does not receive a raw, unbounded
   accessibility tree.

The shared core owns `ref_N` handles. Drivers only receive and return their
own `native_id` values. For each ref, the core retains the first `PruneOpts.scope`
token. It uses that token for one stale-handle relocation query only when the
token is an explicit window id. A stale ref minted through the dynamic
`foreground` or `all` selector fails before another `get_tree` call. The core
also owns a bijective native/ref binding: a relocated candidate already owned
by another ref fails closed, while an accepted candidate updates the cached
Node plus both binding directions before one semantic retry. Drivers neither
mint refs nor turn a ref into coordinates.

This ref lifecycle does not change Driver contract `1.0.0` or add a method.
`scope="foreground"` and `scope="all"` remain dynamic selectors resolved by
`get_tree`; the current `TreeResult` carries no atomic resolved-window identity.
The core therefore requires a fresh observation instead of attempting stale
relocation for either token. A future physical-window binding would require a
separately reviewed contract revision.

## Shared data model

~~~text
Rect {
  x, y, w, h
}

Display {
  id, bounds: Rect, scale, primary
}

Image {
  png: bytes, width, height, scale, displays: [Display]
}

ProcRef {
  pid, name
}

Window {
  id, title, bounds: Rect,
  owner: ProcRef,
  owner_chain: [ProcRef],  # self -> ancestors
  is_foreground
}

Node {
  native_id, role, name, value,
  bbox: Rect,
  states: [enabled, focused, selected, ...],
  patterns: [invoke, value, selectionitem, ...]
}

PruneOpts {
  scope: "foreground" | window_id | "all",
  control_types: "default" | [...],
  include_offscreen: false,
  max_nodes: 200,
  name_max_len: 100,
  redact_password: true
}

TreeResult {
  nodes: [Node],
  truncated: integer
}

Result {
  ok, code, message
}
~~~

Passwords and unavailable values are represented as `null`; they are not
returned as plaintext.

## Primitives

| Primitive | Responsibility |
| --- | --- |
| `capabilities()` | Declares contract version, platform, and available features. |
| `capture_screen(region=None)` | Captures an image in a driver-defined supported region. |
| `list_windows()` | Enumerates visible top-level windows, including owned dialogs. |
| `foreground_owner_chain()` | Returns the foreground process and its ancestors. |
| `get_tree(opts)` | Returns a pruned accessibility-control list. |
| `find(opts, query)` | Returns a pruned matching control list. |
| `get_document_text(opts)` | Returns bounded semantic document text when the backend has a real channel. |
| `invoke(native_id)` | Invokes an accessible control. |
| `set_value(native_id, text)` | Sets an accessible value. |
| `select(native_id)` | Selects an accessible item. |
| `click(x, y, button="left", modifiers=None)` | Performs a coordinate click. |
| `scroll(x, y, delta_x, delta_y)` | Injects bounded horizontal and vertical wheel movement at one point. |
| `drag(x, y, to_x, to_y, duration_ms=250)` | Performs one bounded left-button drag between two points. |
| `key(combo)` | Sends a key chord. |
| `type(text)` | Types literal Unicode text into the focused native control. |
| `activate_window(window_id)` | Attempts to restore and activate a window. Success means the driver verified that the target is the foreground window before returning. |

`activate_window` is idempotent when the target is already foreground. Native
input-thread attachments must be released in `finally`, including partial-
failure paths. A stale window, platform denial, or failed foreground
postcondition is a failure, not best-effort success. More specific activation
codes are planned for the next backward-compatible contract revision; the
current implementation may still collapse them into `DRIVER_ERROR`.

## Current Runtime native-action composition

Driver contract `1.0.0` does not make one method call equivalent to one native
mutation. The Windows implementation can pace an action or issue several native
events inside `click`, `scroll`, `drag`, `key`, `type`, and
`activate_window`. The current MCP/Windows Runtime therefore composes the driver
with one server-owned `NativeActionBoundary`; see
[ADR-009](adr/009-native-action-authority-and-partial-dispatch.md).

Immediately before every driver-controlled pointer, mouse, keyboard, UIA, or
activation mutation, the bound controller calls a non-waiting server-owned
authority probe. The driver receives only allow/reject. It does not receive or
interpret e-stop, Gate, human-input, confirmation, tool-argument, or model data.
An injected driver that cannot bind and checkpoint its native mutations is not
permitted to execute actions in the current Runtime.

Authority loss before the first native attempt retains the server's fixed
rejected/not-dispatched result. Authority loss after any attempt escapes the
ordinary `Result` path and becomes fixed `NATIVE_AUTHORITY_LOST` with
unknown-outcome/dispatched certainty at the Agent bridge.

Separately, if a Windows action returns an unsuccessful `Result` or raises after
the boundary has recorded at least one native dispatch attempt, the server
replaces the original failure detail with fixed, redacted
`NATIVE_OUTCOME_UNKNOWN`. This is a server-owned certainty projection, not a
Driver error code. A zero-attempt failure retains its existing Driver result and
Agent certainty semantics. No later target mutation, verification, action
continuation, recovery dispatch, or replay is permitted after either
post-attempt unknown outcome. A driver may directly perform only the smallest
bounded unwind needed to release a key/button or detach an input queue already
acquired by that call; this cannot downgrade certainty or roll back target state.

Focused `type(text)` is literal text, not the `uiautomation.SendKeys` brace/chord
grammar. The current Windows implementation checkpoints between Unicode
scalars and emits each scalar as one ordered UTF-16 `SendInput` batch. Key chords
remain the responsibility of `key(combo)`.

This composition adds no `Driver` ABC primitive or action parameter, changes no
shared data structure, and does not add a Driver error code. `Result {ok, code,
message}`, `capabilities()`, and `CONTRACT_VERSION = "1.0.0"` therefore remain
unchanged. A future cross-platform boundary API belongs in a separately
versioned contract change; this Windows Runtime hardening is not evidence for an
unimplemented platform driver.

The current Windows driver implements these primitives. The public MCP layer
uses full-primary-display capture for `screenshot()` and passes an explicit,
validated primary-display rectangle to `capture_screen(region)` for `ocr()`.

## Coordinate semantics and current limits

A driver should keep an image's pixels, control bounding boxes, and coordinate
clicks in one DPI-aware coordinate space for the same capture. The Windows
implementation currently establishes that behavior on the primary display.

The `Image` type includes display metadata for future work. OCR results expose
their requested crop origin and map recognized boxes back into primary-display
coordinates. Multi-monitor and virtual-desktop semantics are not validated
product behavior yet.

## Error codes

| Code | Meaning |
| --- | --- |
| `STALE_ELEMENT` | The native id no longer resolves or the target is stale. |
| `NOT_INVOKABLE` | The requested accessibility action is unsupported by the target. |
| `OUT_OF_BOUNDS` | A coordinate is outside the driver's valid capture space. |
| `PERMISSION_DENIED` | The platform or native API denied the operation. |
| `DRIVER_ERROR` | An unclassified driver failure occurred. |

Server-level guard results such as `DENIED by gate`, `HUMAN_ACTIVE`, and
`ABORTED`, and the certainty projections `NATIVE_AUTHORITY_LOST` and
`NATIVE_OUTCOME_UNKNOWN`, are produced above this driver boundary. They are not
Driver error codes and do not change Driver Contract `1.0.0`.

## Platform mapping

| Primitive family | Current Windows implementation | Planned macOS direction | Planned Linux direction |
| --- | --- | --- | --- |
| Capture | `mss` / Win32 desktop capture | ScreenCaptureKit or CGWindowList | X11 capture or Wayland portal |
| Accessibility tree | UIA through `uiautomation` | AXUIElement | AT-SPI |
| Accessible actions | Invoke, Value, SelectionItem patterns | AXPress / AXValue / AXSelect | AT-SPI Action / EditableText |
| Input | Win32 / `ctypes` | CGEvent | XTest or uinput |
| Ownership chain | HWND, PID, and process ancestry | AX PID and process ancestry | active-window APIs and `/proc` |

The macOS and Linux columns are design directions, not supported integrations.

### Android device direction (planned)

A phone or emulator is a fourth planned driver behind this same contract, not a
separate tool surface; see
[ADR-008](adr/008-android-device-driver-behind-driver-contract.md). Its
primitive mapping differs in kind from the desktop platforms:

| Primitive family | Planned Android direction |
| --- | --- |
| Capture | `adb exec-out screencap`, or the scrcpy video frame |
| Accessibility tree | `uiautomator dump` XML mapped into `Node` |
| Accessible actions | UIAutomator node actions, coordinate fallback otherwise |
| Input | `adb shell input tap` / `swipe` / `text` / `keyevent` |
| Ownership chain | foreground package / activity from `dumpsys` |

Two consequences are specific to a device target and are gated behind a
**contract v1.1** minor bump, not assumed here:

- **A touch `swipe` / `long_press` primitive does not exist in v1.0.** The
  existing `scroll` contract is desktop wheel movement and `drag` is a
  left-button pointer action; neither silently defines ADB touch semantics.
  Adding explicit device gestures is an additive, backward-compatible v1.1
  change that every driver then declares through `capabilities()`.
- **A device is a second coordinate domain.** The section below states that the
  supported space is the primary display; a phone's own resolution is a distinct
  domain. Extending the coordinate model to cover it must be a deliberate,
  versioned decision, not a silent widening.

Text injection on Android also does not go through `SendKeys`-style paths:
non-ASCII (e.g. Chinese) requires an IME such as ADBKeyboard or a
clipboard-paste path, decided at driver-build time.

## Versioning and change policy

`CONTRACT_VERSION` is currently `1.0.0`. Change a major version when a
primitive signature or shared data structure becomes incompatible; keep minor
versions backward compatible and add a changelog entry.

Drivers declare a version through `capabilities()`. Automatic compatibility
rejection by the core is a desired enforcement step, not current runtime
behavior; driver authors should not rely on the core to negotiate versions yet.

## Changelog

- **1.1.0 (planned)** — Adds an additive `swipe` / `long_press` primitive and a
  deliberate second-coordinate-domain model, prerequisites for the planned
  Android driver ([ADR-008](adr/008-android-device-driver-behind-driver-contract.md)).
  No v1.0 signature changes; drivers declare support through `capabilities()`.
- **1.0.0** — Defines the shared data model, the fifteen desktop primitives,
  `capabilities()`, and the `activate_window(window_id)` action. The Windows
  implementation later reproduced an unresolved Windows foreground-activation
  defect; see [operator session notes](OPERATOR_SESSION_NOTES.md).
