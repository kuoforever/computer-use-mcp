# MCP tool reference

> **Status: implemented on Windows.** These are the thirteen tools currently
> exposed by the stdio MCP server.

## Read tools

| Tool | Parameters | Behavior |
| --- | --- | --- |
| `ui_snapshot` | `scope="foreground"` | Returns a flat list of interactive UIA controls with refs, bounding boxes, states, and safe value summaries. Scope is exactly `"foreground"`, a positive decimal window id from `list_windows()`, or `"all"`. |
| `find` | `query, scope="foreground"` | Returns a matching subset using the same snapshot/ref model. Use this to reduce context for large windows. |
| `list_windows` | none | Lists visible top-level windows, including owned dialogs. Each row includes a window id, owner executable, title, and foreground marker. A successful call atomically replaces this MCP instance's window-id/direct-owner activation bindings. |
| `screenshot` | none | Returns a PNG of the primary display. It does not accept a region parameter and does not provide a virtual-desktop capture. |
| `capture_region` | `x, y, w, h` | Captures exactly one primary-display region and returns a grounding envelope followed by the cropped PNG. The region is limited to 4,000,000 pixels and the encoding to 4 MiB. |
| `ocr` | `x, y, w, h` | Captures exactly one primary-display region and returns bounded Windows OCR text runs with crop-local and screen-relative boxes. The region is limited to 4,000,000 pixels. |
| `document_text` | `scope="foreground"` | Returns bounded ordered text blocks read through a real UIA text channel for the scope, with a content digest and truncation metadata. Password fields are skipped; a backend without a semantic text channel fails closed. |

`capture_region` is the cropped rung between `ocr` and `screenshot`: the caller
pays for the pixels it names. Its envelope reports the source, scope, crop
origin, dimensions, scale, encoded byte count, and a digest of exactly the bytes
returned, so a redacted crop never carries the digest of the original capture. A
refused region returns the reason as text alone and no pixels. Its coordinates
are evidence in the primary-display pixel space, not invokable refs.

`ocr` is a static-content fallback after UIA. It returns at most 100 runs and
8,000 recognized characters, with a five-second whole-call timeout and explicit
truncation metadata. Its boxes are evidence, not invokable refs. Configured
sensitive-window title matches are blacked out before recognition. Unsupported
or out-of-bounds regions fail instead of widening to a full-display capture.

`document_text` is the ladder rung between the interactive `ui_snapshot` and
`ocr`: it reads text an application or browser exposes through a real UIA
TextPattern channel, not a dump of the accessibility tree or hidden state. A
control's text range already covers its subtree, so page text comes back as a
small number of ordered blocks, each with an optional bounding box. It returns
at most 200 blocks and 20,000 characters with explicit truncation metadata, and
its offsets do not imply clickable coordinates.

The Agent Host advertises and validates that exact scope grammar for
`ui_snapshot`, `find`, and `document_text`. A Planner candidate such as
`"foreground document"` is invalid and stops before plan persistence or MCP
dispatch; scope labels are identifiers, not natural-language descriptions.

Snapshots are capped at 200 qualifying controls. If controls were omitted, the
text result explicitly reports a truncation count. `ui_snapshot` and `find`
both give Chromium-family window scopes a best-effort disposable UIA warm-up
before their final read; a snapshot can still report that browser content is
incomplete.

`find` searches the full bounded Windows UIA traversal before applying the same
200-result cap. Its truncation count therefore reports additional matching
controls, not unrelated controls omitted from a broad snapshot.

## Action tools

| Tool | Parameters | Behavior |
| --- | --- | --- |
| `activate_window` | `window_id` | Attempts to restore and activate a window whose id and direct-owner PID/executable were bound by a successful `list_windows`. The owner is rechecked before each native mutation and after the Driver returns; a missing, disappeared, ambiguous, or changed target requires a fresh list. Success also requires the Driver to verify the target is foreground. In safe mode activation is e-stop/human-activity guarded and audited, but not foreground-allowlist gated. |
| `click` | `ref` **or** `x, y` | Invokes an accessible control by ref, or clicks a primary-display coordinate. Supply one form only. |
| `scroll` | `x, y, delta_x=0, delta_y=0` | Sends bounded horizontal or vertical wheel movement at a screenshot-grounded primary-display coordinate. At least one delta must be non-zero. |
| `drag` | `x, y, to_x, to_y, duration_ms=250` | Holds the left mouse button along one bounded path between two screenshot-grounded primary-display coordinates. Both endpoints must differ and remain in the current screenshot. |
| `type` | `text, ref=None` | With a ref, uses one UIA ValuePattern mutation; without one, types literal Unicode scalars into the current focus. Braces are text, not a key-command grammar. |
| `key` | `combo` | Sends a key chord such as `Ctrl+S` to the foreground window. |

In `safe_local`, `click`, `scroll`, `drag`, `type`, and `key` require an allowlisted
foreground process ancestry. See [Configuration and safety](CONFIGURATION.md)
for the complete guard behavior.

## Refs and stale elements

`ui_snapshot` and `find` return session-scoped names such as `ref_7`.
Refs are kept across later snapshots when the driver still recognizes the same
native UIA element. Each ref also retains the exact scope token from the
snapshot or find call that first minted it; later observations in another scope
do not change its relocation domain. If that token is an explicit window id and
the native element becomes stale, the server makes one best-effort role-bounded
name query across the full Windows traversal before applying the 200 matching-
result cap, only in that window scope. It then requires the original exact role
and name. A candidate already owned by another ref is a conflict and fails
closed without acting on the candidate. Successful relocation updates the ref's
node and both native/ref bindings together.

The tokens `foreground` and `all` remain dynamic driver selectors, not frozen
physical-window identities. A stale ref first observed through either selector
returns `STALE_ELEMENT` without another tree query or candidate action; take a
fresh snapshot before acting again. Only an explicit window-id scope is eligible
for relocation. This fail-closed distinction requires no new resolved-window
identity evidence and does not change Driver contract `1.0.0`.

Prefer refs whenever possible:

~~~text
ui_snapshot() -> choose ref_12 -> click(ref="ref_12")
~~~

Coordinate click, scroll, and drag are necessary for canvas/game-style surfaces
that UIA cannot expose, but they move the physical pointer and have all normal
foreground risks.

Newly generated installed product profiles enable action feedback; legacy or
hand-written MCP configuration can still disable it. When enabled, coordinate motion gets a
high-contrast halo and fixed action label. Ref actions retain their semantic
UIA dispatch: the overlay pulses at the last observed element bounds without
converting the ref into a coordinate click. Keyboard feedback says only
`AGENT TYPING` or `AGENT KEY`; it receives neither typed content nor the key
combination. The overlay is passive, click-through, non-activating, and excluded
from capture. Visible typing animates a caret, cycling dots, and an estimated
progress bar using only bounded text length and the Host-selected interval. The
badge follows the foreground editor's native caret without reading document
content; a surface that exposes no native caret uses a stable fallback instead.

Presentation pacing never extends action authority. One call-scoped boundary
rechecks e-stop, applicable foreground, and safe-local human input immediately
before each driver-controlled native mutation. Focused typing checkpoints
between Unicode scalars; `key(combo)` remains the only reviewed chord path.

## Result and error behavior

Action tools return `ok` on success. Failures are returned as text with a
specific reason where available, for example:

| Result prefix or code | Meaning |
| --- | --- |
| `DENIED by gate` | The safe-mode foreground allowlist did not match. |
| `HUMAN_ACTIVE` | Recent local input caused safe mode to yield. |
| `ABORTED` | The e-stop is engaged; restart the server to clear it. |
| `STALE_ELEMENT` | The requested ref no longer resolves; dynamic-scope refs require a fresh snapshot, while explicit-window refs permit one bounded relocation attempt. |
| `OUT_OF_BOUNDS` | A coordinate lies outside the current supported capture space. |
| `DRIVER_ERROR` | The platform driver could not perform the operation. |
| `NATIVE_AUTHORITY_LOST` | Authority changed or the native boundary was unavailable. Before any native attempt this is rejected/not-dispatched; after a partial attempt it is unknown-outcome/dispatched, stops the Runner, and is never replayed. |
| `NATIVE_OUTCOME_UNKNOWN` | A Windows native action reported failure after at least one native dispatch attempt, so its effect may already have occurred. The server replaces the failure detail with this fixed redacted code; the Agent treats it as unknown-outcome/dispatched, stops, and never replays it. |

An activation id that was not successfully listed, disappeared, or changed
direct owner returns fixed `NATIVE_AUTHORITY_LOST`; a fresh `list_windows` is
required before activating a replacement. A zero-attempt platform failure can
still appear as `DRIVER_ERROR`, while failure after a native attempt becomes
`NATIVE_OUTCOME_UNKNOWN`. Do not retry an activation indefinitely.

The driver may also report `NOT_INVOKABLE` or `PERMISSION_DENIED`. Treat
errors as information for the next observation step, not as a reason to repeat
a destructive action blindly. `NATIVE_OUTCOME_UNKNOWN` is a server-owned
certainty projection rather than a Driver code; a failure with zero recorded
native attempts keeps its existing result and certainty semantics.

After partial native dispatch, the driver may only release a key/button or
detach an input queue acquired by that call. This bounded unwind is not rollback;
it does not restore pointer, window, or application state and cannot make the
outcome safe to retry.
