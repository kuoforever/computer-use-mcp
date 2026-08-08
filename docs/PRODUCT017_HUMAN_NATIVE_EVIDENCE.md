# PRODUCT-017 human native evidence

> **Status: the bounded English Windows Narrator Decision Card review, the
> complete 200%/400% human visual review, and one fake-only native cooperative
> takeover/resume timing run passed on 2026-08-08.** One earlier Narrator
> attempt and one earlier takeover harness attempt were invalid and are retained
> below. A 30-second fixed local notification was not seen and left no
> notification-center history while this machine reported global
> `ToastEnabled=0`; that gate is blocked by the current Windows setting, not
> promoted as product visibility. Other assistive technologies/locales and
> physical two-monitor usability remain open or hardware-blocked. This is not
> E4, release approval, or a waiver.

## Environment and authority boundary

| Field | Result |
| --- | --- |
| Product candidate | branch `codex/gda-product-017-human-gates` on merged PR #286 baseline `5b2790ca3dcd3dfdd0932304351937979cc1ac5a` |
| Platform | Windows, built-in Narrator, CPython 3.13.7 |
| Audio | Windows default output through recognized `LULIAN 108B` USB audio; a bounded SAPI phrase and Narrator startup were heard |
| Display | one `2560x1600` monitor, `2560x1528` work area, 144 DPI |
| Windows notification setting | `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\PushNotifications\\ToastEnabled=0`; no matching user- or machine-level Explorer policy was present |
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
| Presence halo | Pass: state and authority are glanceable, passive, click-through, removed on release/terminal/disabled states, and the repaired measured-glyph English/Chinese 200%/400% presentation was human-accepted | Physical two-monitor review remains hardware-blocked |
| Progress HUD | Pass: summary-first hierarchy, compact/expanded states, wrapping/scrolling read-only Document, and real presentation-only Button/Invoke were human-accepted after the clipping and semantic-control repair | No approval, control, retry, resume, or dispatch authority is exposed |
| Decision Card | Bounded pass: information and choices are separated; safe default, focus, hover, pressed, disabled, expanded, timeout, close, and keyboard states are explicit; English Narrator default/on-demand reading passed | Other screen readers, braille, and other-locale auditory review remain unclaimed |
| Approval Inbox and fixed notification | Pass at the authority boundary: Inbox is explicitly read-only and distinguishes pending/expired; notification directs the operator back to the existing Decision Card and has no approval port | Human visibility is `BLOCKED BY CURRENT WINDOWS SETTING`: Shell accepted and withdrew the notice, but no banner or notification-center item appeared while global `ToastEnabled=0` |
| Cooperative pause/takeover/resume | Pass for one fake-only human timing path: the operator waited for `paused/released`, used the desktop only while released, stopped before resume, and the lifecycle reacquired authority without new input or focus drift | `task resume` versus top-level crash-safe `resume` is a terminology collision retained as deferred UX debt; no provider, MCP, application, or desktop-action timing is claimed |
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

The operator then replied `继续` to the explicit revised Progress/Presence
confirmation request after reviewing the final 200%/400% screenshots. This is
the human acceptance signal for the repaired passive surfaces; it does not
extend the evidence to another display, text scale, locale, or assistive
technology.

## Visible-notification attempt

One Simplified-Chinese fixed-content approval notice was kept alive for 30
seconds. The notice contained only `受保护的桌面智能体` and
`需要审批。请返回已打开的决策窗口。`; it had no action, approval, task-control,
provider, MCP, desktop, retry, replay, or dispatch port. The Win32 host and
Shell lifecycle completed normally and withdrew cleanly without changing the
foreground.

The operator did not observe a banner, and the supplied screenshot showed an
empty Windows notification center. A concurrent read-only settings check found
global `ToastEnabled=0` and no matching user- or machine-level Explorer policy.
This is sufficient to classify the current environment as blocking the human
visibility/retrieval gate. It does not prove that Shell acceptance means
visibility, does not change the user's global setting, and does not claim the
notification passed.

## Native cooperative takeover timing

The bounded harness used the production `LocalCooperativeControl`, OS-backed
run lock, strict control record, and durable Runner checkpoint with fake-only
state. It opened no provider, MCP, application, or desktop-action port. The
operator was instructed not to touch the shared desktop until the observed
state was exactly `paused` with `authority=released`, then to use the desktop,
reply when finished, and stop input before resume.

The first attempt is invalid: after a correct pause and observed operator input,
the evidence harness wrote an impossible synthetic verified-observation epoch,
raised `ValueError`, and closed `stopped`. The traceback was confined to the
harness after `resuming`; it is neither product evidence nor operator error.

The corrected complete rerun passed:

| Observation | Result |
| --- | --- |
| Request to acknowledged pause | `65.2 ms` |
| Paused state | `paused`, `authority=released`, `boundary=before_provider` |
| Operator input during released interval | observed |
| Resume path | `resume_requested -> resuming -> active -> closed` |
| Resume request to closed | `1587.5 ms` |
| Fresh observation | durable epoch `1` before control returned `active` |
| Input after resume | none observed |
| Foreground during reacquisition | unchanged |
| Terminal state | `closed`, `authority=none`, `outcome=success` |

This proves the named same-machine, fake-only human hand-timing and focus path.
It does not prove real provider latency, an in-flight MCP call, application
correctness, remote control, crash recovery, multi-display usability, or E4.

## Remaining human and hardware gates

| Gate | State | Exact next evidence |
| --- | --- | --- |
| Human 200%/400% and visual design | `PASS` | Decision Card plus repaired Progress and Presence accepted on the named one-monitor environment |
| Visible notification presentation | `BLOCKED BY CURRENT WINDOWS SETTING` | global `ToastEnabled=0`; enable Windows notifications intentionally, then rerun banner and notification-center retrieval without changing product authority |
| Native cooperative takeover timing | `PASS` | one corrected fake-only run passed released-interval input, explicit resume, fresh observation, no post-resume input, and unchanged focus |
| NVDA/JAWS/braille/other locales | `NOT RUN` | separate tool- and locale-specific human evidence |
| Physical two-monitor usability | `BLOCKED BY AVAILABLE HARDWARE` | two physical displays; synthetic coordinates are insufficient |
| E4 four-cell matrix | `NOT RUN` | explicitly deferred; no waiver exists |
| Release/tag/artifact publication | `NOT RUN` | separate final-candidate review and explicit release authority |
