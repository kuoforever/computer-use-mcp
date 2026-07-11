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
own `native_id` values.

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
| `invoke(native_id)` | Invokes an accessible control. |
| `set_value(native_id, text)` | Sets an accessible value. |
| `select(native_id)` | Selects an accessible item. |
| `click(x, y, button="left", modifiers=None)` | Performs a coordinate click. |
| `key(combo)` | Sends a key chord. |
| `type(text)` | Types into the focused native control. |
| `activate_window(window_id)` | Activates a window. |

The current Windows driver implements these primitives. The public MCP layer
currently exposes only a full primary-display `screenshot()`; it does not pass
a region through to `capture_screen(region)`.

## Coordinate semantics and current limits

A driver should keep an image's pixels, control bounding boxes, and coordinate
clicks in one DPI-aware coordinate space for the same capture. The Windows
implementation currently establishes that behavior on the primary display.

The `Image` type includes display metadata for future work, but the current
MCP server does not expose it. Multi-monitor, virtual-desktop, and region-offset
semantics are not validated product behavior yet.

## Error codes

| Code | Meaning |
| --- | --- |
| `STALE_ELEMENT` | The native id no longer resolves or the target is stale. |
| `NOT_INVOKABLE` | The requested accessibility action is unsupported by the target. |
| `OUT_OF_BOUNDS` | A coordinate is outside the driver's valid capture space. |
| `PERMISSION_DENIED` | The platform or native API denied the operation. |
| `DRIVER_ERROR` | An unclassified driver failure occurred. |

Server-level guard results such as `DENIED by gate`, `HUMAN_ACTIVE`, and
`ABORTED` are produced above this driver boundary.

## Platform mapping

| Primitive family | Current Windows implementation | Planned macOS direction | Planned Linux direction |
| --- | --- | --- | --- |
| Capture | `mss` / Win32 desktop capture | ScreenCaptureKit or CGWindowList | X11 capture or Wayland portal |
| Accessibility tree | UIA through `uiautomation` | AXUIElement | AT-SPI |
| Accessible actions | Invoke, Value, SelectionItem patterns | AXPress / AXValue / AXSelect | AT-SPI Action / EditableText |
| Input | Win32 / `ctypes` | CGEvent | XTest or uinput |
| Ownership chain | HWND, PID, and process ancestry | AX PID and process ancestry | active-window APIs and `/proc` |

The macOS and Linux columns are design directions, not supported integrations.

## Versioning and change policy

`CONTRACT_VERSION` is currently `1.0.0`. Change a major version when a
primitive signature or shared data structure becomes incompatible; keep minor
versions backward compatible and add a changelog entry.

Drivers declare a version through `capabilities()`. Automatic compatibility
rejection by the core is a desired enforcement step, not current runtime
behavior; driver authors should not rely on the core to negotiate versions yet.

## Changelog

- **1.0.0** — Defines the shared data model, the twelve desktop primitives,
  `capabilities()`, and the `activate_window(window_id)` action. The Windows
  implementation was validated against the project's on-device smoke paths.
