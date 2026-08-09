# ADR-011: OS input is the default; browser-native access is read-only assistance

Status: Accepted
Date: 2026-08-09

## Context

Browser accessibility or plugin automation can expose a visible control yet
fail to activate it, especially on JavaScript-rendered pages or sites that
treat script-driven interaction differently from ordinary user input. Repeating
the same browser action is neither useful nor a safe recovery policy.

The project already has one audited Windows desktop dispatch path. Adding a
second browser-action authority would split policy, approval, grounding,
certainty, and recovery behavior.

## Decision

- Desktop side effects use OS pointer and keyboard input by default. These are
  Win32-generated input events visible through the normal desktop path; they
  are not literal hardware signals.
- `click(ref=...)` selects its backend before dispatch. The default backend
  moves/clicks the OS pointer at the center of the currently bound observed
  box. When the user explicitly sets `CUMCP_UIA_ACTIONS=1`, ref clicks instead
  use the existing UIA Invoke/SelectionItem path. A failed UIA action never
  falls back to coordinates.
- Focused `type(text)` and `key(combo)` keep the OS keyboard path. Ref-addressed
  `type(text, ref=...)` is unavailable by default and requires the same explicit
  UIA opt-in because ValuePattern is not OS keyboard input.
- Playwright CDP is an optional, read-only observation adapter enabled only by
  trusted user configuration. It may return bounded rendered text and ARIA
  structure from an existing loopback Chromium debugging endpoint. It exposes
  no navigation, click, fill, evaluate, cookie, storage, download, or browser
  ref action.
- Browser refs and viewport coordinates never become desktop refs or screen
  coordinates. Browser content remains untrusted data; only the existing
  Runner/MCP/Driver path can create a desktop effect.
- After one failed `browser_snapshot` result in a run, the Host removes that
  tool from later provider turns so the model must use UIA, screenshot, OCR,
  document text, or cooperative human takeover. There is no automatic action
  replay and no anti-automation or login-challenge bypass.

The configured browser endpoint must be `http` or `ws`, loopback-only, include
an explicit port, and contain no credentials, query, or fragment. The adapter
does not launch a browser or attach to an ordinary profile that was not already
started with an explicit debugging endpoint.

## Consequences

The visible default action now resembles ordinary mouse/keyboard use and works
with surfaces whose script-facing action mechanism is unreliable. Observation
can benefit from a rendered DOM without granting that DOM a second action path.

The trade-off is explicit: a ref-backed OS click relies on observed geometry,
so layout or occlusion can change between observation and input. Fresh Host
grounding, the foreground gate, human-activity yield, dangerous-action
confirmation, and mandatory post-action observation reduce but do not remove
that timing risk. Users who prefer semantic focus-independent ref actions can
opt in to UIA; the Runtime never switches between the two after a failed
attempt.

## Relationship to ADR-002

[ADR-002](002-ref-actions-never-silently-fall-back-to-coordinates.md) still
governs UIA ref execution: stale relocation is bounded and a failed semantic
action never becomes a coordinate click. This ADR changes the default backend
chosen before dispatch; it does not authorize runtime fallback after failure.

## Evidence boundary

Offline tests cover configuration validation, optional exact tool discovery,
bounded/redacted browser results, OS-default ref dispatch, explicit UIA opt-in,
failure withdrawal, continuation compatibility, and unchanged core registry
digest. No retained real-browser, provider, Windows desktop, anti-automation,
or application acceptance evidence is created by this decision.
