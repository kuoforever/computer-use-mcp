# Native operator multi-display composition

> **Status: implemented and offline verified on Windows; bounded current-monitor
> native UIA/no-activation smoke passed on 2026-08-07.** The Host now places
> Decision Card, Progress, and Presence on the monitor associated with the
> current foreground window. This is a presentation contract only. It does not
> widen the primary-display action, screenshot, OCR, capture, or MVP boundary,
> and it is not retained physical two-monitor usability evidence.

## Selection contract

The model does not name, index, or choose a monitor. At a defined native
surface transition, the Host snapshots the current foreground HWND and calls
`MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY)`. A missing foreground HWND
therefore selects the Windows primary monitor; an invalid monitor query fails
the optional surface closed instead of guessing virtual-screen geometry.

One immutable `OperatorMonitor` contains all facts consumed by that layout:

- the complete monitor rectangle in virtual-screen coordinates;
- its work area after taskbars and app bars;
- the selected monitor's effective DPI from `GetDpiForMonitor`, with bounded
  window-DPI, system-DPI, and 96-DPI fallbacks when that monitor query is
  unavailable or invalid.

All rectangle edges and DPI are validated together. Negative `left` and `top`
values are valid for displays arranged left of or above the primary display.
The work area must be non-empty and contained by the complete monitor bounds.
One layout never mixes a rectangle from one query with DPI from another.

## Surface placement

| Surface | Selection point | Rectangle | Follow behavior |
| --- | --- | --- | --- |
| Presence | Every visible Host phase sync | Complete selected monitor bounds | Repositions without activation when a later phase sync observes a different foreground monitor |
| Progress | Native window creation | Selected monitor work area, top-right | Keeps the created window on that monitor; expansion uses the window's current monitor, and an explicit operator move still opts out of automatic anchoring |
| Decision Card | Immediately before one card opens | Selected monitor work area, configured corner | Uses the same captured monitor and DPI for compact and expanded layouts until the bound decision exits |

Presence uses full bounds because it is a click-through border around the
controlled display. Progress and Decision Card use the work area so taskbars
and app bars remain unobstructed. Progress remains passive and non-activating;
Presence retains `WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`; Decision Card remains
the sole focus-taking surface and restores the foreground window captured for
that decision.

## Authority boundary

Monitor facts flow only into native window geometry and rendering scale. They
never enter a plan, provider request, persisted run/checkpoint, approval
binding, MCP argument, Driver coordinate conversion, observation region, or
automatic Full Cycle export. The existing primary-display coordinate and
capture contracts remain unchanged. Moving an operator surface to another
monitor creates no permission to observe or act there.

Native selection/configuration failure remains presentation-only. Presence and
Progress use their existing fail-silent lifecycle isolation. Decision Card
native failure keeps the existing safe denial behavior. None can retry or
replay a possibly dispatched effect.

## Evidence and limits

Deterministic tests cover negative virtual-screen coordinates, offset work
areas, mixed DPI, missing-foreground primary fallback, invalid monitor/DPI
facts, full-bounds Presence geometry, corner placement, and unchanged
no-activation/ABI behavior. A native smoke may confirm the current machine's
enumerated monitor layout and window placement, but only a valid run on a real
two-monitor setup can promote physical multi-display evidence.

The bounded native smoke ran on the available one-monitor Windows desktop at
`2560 x 1600`, 144 DPI, with work area `(0, 0)-(2560, 1528)`. In both English
and Simplified Chinese, Presence matched the complete monitor bounds, Progress
stayed in the top-right work-area rail without changing foreground, and
Decision Card stayed in the bottom-right work-area rail and returned the safe
`option_deny`. Capture exclusion was accepted. The machine enumerated only one
monitor, so this is native wiring evidence, not physical cross-monitor evidence.

The separately implemented
[operator personalization](OPERATOR_PERSONALIZATION.md) contract does not
change this geometry. Human Narrator/NVDA review, live large-text review, E4,
and exact release-candidate evidence remain separate later gates.
