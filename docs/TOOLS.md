# MCP tool reference

> **Status: implemented on Windows.** These are the eight tools currently
> exposed by the stdio MCP server.

## Read tools

| Tool | Parameters | Behavior |
| --- | --- | --- |
| `ui_snapshot` | `scope="foreground"` | Returns a flat list of interactive UIA controls with refs, bounding boxes, states, and safe value summaries. Scope is `"foreground"`, a window id from `list_windows()`, or `"all"`. |
| `find` | `query, scope="foreground"` | Returns a matching subset using the same snapshot/ref model. Use this to reduce context for large windows. |
| `list_windows` | none | Lists visible top-level windows, including owned dialogs. Each row includes a window id, owner executable, title, and foreground marker. |
| `screenshot` | none | Returns a PNG of the primary display. It does not accept a region parameter and does not provide a virtual-desktop capture. |

Snapshots are capped at 200 qualifying controls. If controls were omitted, the
text result explicitly reports a truncation count. Chromium-family windows get
a best-effort UIA warm-up; the result can still report that browser content is
incomplete.

## Action tools

| Tool | Parameters | Behavior |
| --- | --- | --- |
| `activate_window` | `window_id` | Brings a listed window to the foreground. In safe mode it is e-stop/human-activity guarded and audited, but not foreground-allowlist gated. |
| `click` | `ref` **or** `x, y` | Invokes an accessible control by ref, or clicks a primary-display coordinate. Supply one form only. |
| `type` | `text, ref=None` | With a ref, prefers UIA ValuePattern; without one, types into the current focus. |
| `key` | `combo` | Sends a key chord such as `Ctrl+S` to the foreground window. |

In `safe_local`, `click`, `type`, and `key` require an allowlisted
foreground process ancestry. See [Configuration and safety](CONFIGURATION.md)
for the complete guard behavior.

## Refs and stale elements

`ui_snapshot` and `find` return session-scoped names such as `ref_7`.
Refs are kept across later snapshots when the driver still recognizes the same
native UIA element. If the native element becomes stale, the server makes one
best-effort relocation attempt based on role and name. If that fails, it returns
`STALE_ELEMENT`; take a new snapshot before acting again.

Prefer refs whenever possible:

~~~text
ui_snapshot() -> choose ref_12 -> click(ref="ref_12")
~~~

A coordinate click is necessary for canvas/game-style surfaces that UIA cannot
expose, but it moves the physical pointer and has all normal foreground risks.

## Result and error behavior

Action tools return `ok` on success. Failures are returned as text with a
specific reason where available, for example:

| Result prefix or code | Meaning |
| --- | --- |
| `DENIED by gate` | The safe-mode foreground allowlist did not match. |
| `HUMAN_ACTIVE` | Recent local input caused safe mode to yield. |
| `ABORTED` | The e-stop is engaged; restart the server to clear it. |
| `STALE_ELEMENT` | The requested ref no longer resolves after one relocation attempt. |
| `OUT_OF_BOUNDS` | A coordinate lies outside the current supported capture space. |
| `DRIVER_ERROR` | The platform driver could not perform the operation. |

The driver may also report `NOT_INVOKABLE` or `PERMISSION_DENIED`. Treat
errors as information for the next observation step, not as a reason to repeat
a destructive action blindly.
