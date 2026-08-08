# PRODUCT-017 human native evidence

> **Status: the bounded English Windows Narrator Decision Card review passed
> on 2026-08-08 after one observed verbosity defect was repaired.** The same
> supervised design review accepted the repaired Decision Card at 200%/400%,
> then found and repaired real Progress and Presence large-text defects. Their
> new native/UIA evidence passed; final human confirmation of those two revised
> passive surfaces remains open. Visible-notification presentation, real
> cooperative takeover timing, other assistive technologies/locales, and
> physical two-monitor usability remain open or hardware-blocked. This is not
> E4, release approval, or a waiver.

## Environment and authority boundary

| Field | Result |
| --- | --- |
| Product candidate | branch `codex/gda-product-017-narrator-verbosity` on PRODUCT-017 merged baseline `930ba3a` |
| Platform | Windows, built-in Narrator, CPython 3.13.7 |
| Audio | Windows default output through recognized `LULIAN 108B` USB audio; a bounded SAPI phrase and Narrator startup were heard |
| Display | one `2560x1600` monitor, `2560x1528` work area, 144 DPI |
| External ports | fake provider and fake desktop only; no provider, MCP child, application, or desktop-action port opened |
| Action decision | every manual card ended through safe denial/close/timeout; no approval was selected |
| E4 / release / waiver | `NOT RUN` / not approved / none |

The first no-speech attempt was invalid because the Narrator process had
exited. The Windows default audio path was checked independently, Narrator was
restarted, and only subsequent audible attempts were considered.

## Observed failure

The pre-fix card exposed the expected native UIA names and button traversal.
`Show details` expanded successfully and a synchronized focus trace reached
the labelled `Decision details` read-only Document. Narrator then automatically
read more than 500 characters, from `Decision scope` through later authority
text, before the operator could continue the four-choice decision path. Button
names themselves were announced correctly.

This was a human usability failure, not missing content or a Tab-navigation
failure. A focus-triggered full-value dump made the ordinary decision path too
verbose.

## Bounded repair and retest

The read-only, multiline, scrollable details value remains exposed as a
labelled UIA Document/TextPattern, but it is static context and no longer has
`WS_TABSTOP`.
Interactive Tab order is now:

~~~text
Stop task -> Show details -> Approve once -> Check screen again
-> Pause and inspect -> Stop task
~~~

The current native probe passed all ten English/Simplified-Chinese
dark/light/High-Contrast/200%/400% safe-denial cases with that path. During the
supervised English Narrator rerun:

- initial safe denial and `Show details` were announced;
- expanding details did not automatically read the long value;
- the next `Tab` announced `Approve once`;
- Narrator scan mode (`Narrator+Space`) plus arrow navigation could enter and
  read the full details on demand; and
- `Esc` remained a safe denial with no external dispatch.

This follows the Windows convention that Tab order covers interactive
controls while screen-reader reading/scan navigation handles static text. It
does not claim that every Narrator verbosity setting, another screen reader,
braille display, locale, or application workflow passed.

## UX heuristic evaluation and cognitive walkthrough

The broader review used the professional lenses of **UX heuristic evaluation**
(consistency, feedback, error prevention, recovery, recognition over recall),
**cognitive walkthrough** (whether a new operator can infer the next action),
**interaction-state audit** (default, focus, hover, pressed, disabled, loading,
empty, error, timeout, and terminal states), **information architecture**, and
the operator's **mental model**. “Interaction model” is one part of this wider
review, not the umbrella term.

| User-visible surface | Walkthrough result | Remaining limitation or next evidence |
| --- | --- | --- |
| First-run config, doctor, and setup errors | The command order and actionable failure fields are coherent | `config doctor` is JSON-only and the broader CLI remains English-first; both are deferred product UX debt, not a PRODUCT-017 native-acceptance claim |
| Pre-run Review Scope Sheet | Pass: clearly says nothing has started, separates reads/changes/output/risk/stop conditions, and requires exact `START`; every other input cancels before startup | Only the fixed public-web-word workflow owns this surface |
| Presence halo | State and authority are glanceable, passive, click-through, and removed on release/terminal/disabled states | The old character-count width estimate clipped English and Chinese at 200%/400%; the repair now uses actual GDI glyph width/height and passed native screenshots, pending final human confirmation |
| Progress HUD | Summary-first hierarchy and compact/expanded states are appropriate | The old fixed-coordinate text clipped and its painted `Show steps` text had no UIA control state. The repair separates a wrapping/scrolling read-only Document from a real presentation-only Button with Invoke and visible compact/expanded labels; ten native cases passed, pending final human confirmation |
| Decision Card | Bounded pass: information and choices are separated; safe default, focus, hover, pressed, disabled, expanded, timeout, close, and keyboard states are explicit; English Narrator default/on-demand reading passed | Other screen readers, braille, and other-locale auditory review remain unclaimed |
| Approval Inbox and fixed notification | Pass at the authority boundary: Inbox is explicitly read-only and distinguishes pending/expired; notification directs the operator back to the existing Decision Card and has no approval port | Actual visible notification/retrieval under the current Windows settings remains `NOT RUN` |
| Cooperative pause/takeover/resume | The lifecycle exposes requested, acknowledged, released, resuming, and closed states with safe next instructions | Native timing remains `NOT RUN`; `task resume` versus top-level crash-safe `resume` is a terminology collision retained as deferred UX debt |
| Task Center and completion/failure receipts | Pass: Attention, In Progress, and History follow operator priority; terminal receipts state outcome and next action without adding authority | Some recovery copy says to use an “existing reviewed path” instead of naming an exact command; improve only in a later scoped CLI UX item |

The deferred findings are recorded here so they are not mistaken for completed
work, but they do not displace the single active PRODUCT-017 native gate.

## Large-text defects repaired during the walkthrough

At 200%/400%, the old Progress HUD used `TextOutW` against fixed rows. Workflow
title, counts, current-step text, and checklist labels could clip, while the
painted `Show steps` hit target exposed only a top-level UIA Pane with no
Button, Invoke, hover, pressed, focus, or disabled semantics. The replacement
uses one read-only wrapping RichEdit Document for information and one real
bottom disclosure Button for interaction. The compact document keeps all six
summary fields visible at 400%; expanded content is bounded and scrollable.

The old Presence tab estimated width from `len(text)`. Actual GDI measurements
exceeded that estimate in English and Simplified Chinese, most severely for
400% Chinese. The repaired tab measures the selected Segoe UI glyphs with
`GetTextExtentPoint32W`, includes both insets in its rectangle, and caps only at
the selected monitor boundary.

The ten-case native smoke now verifies Progress `Document/TextPattern`, one
localized disclosure `Button/Invoke`, exact `compact -> expanded -> compact`
state, foreground preservation, measured Presence containment, and safe
Decision Card denial. Focus did not drift during this rerun. The complete
current-branch source gate then passed `2066 passed, 8 skipped`, full Ruff,
mypy over 138 source files, documentation consistency, and `git diff --check`.

## Remaining human and hardware gates

| Gate | State | Exact next evidence |
| --- | --- | --- |
| Human 200%/400% and visual design | `PARTIAL` | Decision Card accepted; confirm the newly repaired Progress and Presence screenshots before promoting the whole gate |
| Visible notification presentation | `NOT RUN` | confirm one fixed local notification is actually seen and can be dismissed/retrieved under reviewed Windows settings |
| Native cooperative takeover timing | `NOT RUN` | take the desktop only after `paused/released`, stop input before resume, and judge timing/focus |
| NVDA/JAWS/braille/other locales | `NOT RUN` | separate tool- and locale-specific human evidence |
| Physical two-monitor usability | `BLOCKED BY AVAILABLE HARDWARE` | two physical displays; synthetic coordinates are insufficient |
| E4 four-cell matrix | `NOT RUN` | explicitly deferred; no waiver exists |
| Release/tag/artifact publication | `NOT RUN` | separate final-candidate review and explicit release authority |
