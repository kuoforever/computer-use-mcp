# Isolated Operator HUD visual evidence after the Decision Card rebuild

Date: 2026-08-01

This record supersedes the presentation shown in
[the 2026-07-30 matrix](OPERATOR_HUD_VISUAL_EVIDENCE.md) for the Decision Card
only. That dated record is retained unchanged; it remains the evidence for the
surfaces as they were.

## Why the Decision Card was rebuilt

The operator compared the HUD against the Claude Code and Codex interfaces they
were targeting. The workflow Progress HUD already matched: an uppercase accent
micro-label, one large title, muted qualifying metadata, and a quiet
text-plus-chevron expand affordance. The Decision Card shared none of it,
because it was assembled from system dialog controls rather than painted.

Four concrete defects were found and fixed:

1. the frame was `WS_OVERLAPPEDWINDOW`, so a one-decision card was resizable,
   maximizable, and minimizable, and the operator could break the exact
   reviewed compact/expanded geometry;
2. both detail panes used `WS_EX_CLIENTEDGE`, the sunken 3D bevel;
3. the two surfaces had drifted onto different dark greys, because status
   colour came from one token contract but chrome did not;
4. `Show details` was a framed system push button rather than the Progress
   HUD's quiet affordance.

Three further defects were found by the operator during this live review and
fixed before the matrix below was retained:

5. every owner-drawn control painted an empty label. `GetWindowTextW` with a
   null buffer and `nMaxCount=0` copies nothing and returns 0, so the buffer
   was always sized 1. The choices rendered as unlabelled rectangles;
6. the expand affordance drew `SHOW DETAILS` and `HIDE DETAILS` on top of each
   other after one toggle, because an owner-drawn control owns its whole
   rectangle and the handler painted text without first filling the background;
7. the detail panes and the system scrollbars inside them had insufficient
   contrast once the sunken bevel was gone;
8. the expanded state nested two scroll contexts inside a fixed card. The
   reference interfaces never do this, and the fixed 55/45 split was also what
   truncated whichever section happened to be longer. It is now one region,
   which additionally surfaced trade-off lines the split had hidden.

## Retained matrix

Captured at 144 DPI (150%) through the existing fail-closed helper: exact
white-listed title, expected compact/expanded aspect, stable geometry, and a
compositor-settle interval before cropping only that window rectangle.

| Surface | State | Result | Artifact and SHA-256 |
| --- | --- | --- | --- |
| Decision Card | Default compact | Amber `NEEDS INPUT · APPROVAL LOCKED` micro-label, the full untruncated action as the title, muted `APPROVAL 4/7` and `WORKFLOW 4/6` qualifiers, a right-aligned countdown, `SHOW DETAILS ∨`, and a 2x2 of flat labelled choices. The caption offers close only. | [PNG](evidence/operator-hud/2026-08-01/decision-card-compact.png), `5BE23C21249406FF808DBC3A803D5EB3459E327EDBF14F0FD8789CEB4044C7D6` |
| Decision Card | Expanded details | `HIDE DETAILS ∧` renders cleanly with no overdraw. One hairline-bounded detail region with a single legible scrollbar and no sunken bevel; the 2x2 choices stay wholly visible. | [PNG](evidence/operator-hud/2026-08-01/decision-card-expanded.png), `ED2F79E74C1A03CD6FC7C595455FC3403AB2EC313B7CF337B239FA8DF92AD935` |
| Progress HUD | Default expanded | Unchanged by the shared-token refactor, as intended: the canonical values are the ones this surface already shipped. | [PNG](evidence/operator-hud/2026-08-01/progress-hud-expanded.png), `814C75D097F1D130374A049AAC83626FF65F8989CE97EA6BBD08835D19998A94` |
| Progress HUD | Operator-collapsed | Unchanged; summary counts, current step, action, application, and `SHOW STEPS ∨`. | [PNG](evidence/operator-hud/2026-08-01/progress-hud-compact.png), `AE9BE4BFC98439C779DE964DA681B300493D12347E0E9250A123E835DE311081` |

## Why the three windows were not merged

The reference interfaces own their whole viewport, so they can render an
approval inline in one document flow. This product cannot: the foreground
during a Demo is Chrome or Word. Presence, Progress, and the Decision Card must
remain separate top-level windows composited over a third-party application.

The separation is also load-bearing for safety. `ProgressWindowApi` defines no
`activate`, `focus`, `set_foreground`, or `bring_to_top` method at all, so a
controller written against it cannot steal foreground — the call does not
exist. The Decision Card must do the opposite and take focus, because it is an
approval gate. Merging them into one morphing surface would replace a
structurally provable property with a runtime condition. Alignment therefore
covers the design language — type scale, palette, density, quiet affordances —
and not the window architecture.

## What did not change

The approving option gained no visual promotion. `BS_*` type styles share one
4-bit field, so an owner-drawn button cannot also carry `BS_DEFPUSHBUTTON`;
that style was only ever a highlighted border here, because this window runs its
own message loop and never calls `IsDialogMessage`. The safe-default hint is now
painted explicitly and still sits on deny. On an approval surface the
consequential option must not be the visually loudest one.

The controls remain real `BUTTON` windows, so focus, tab order, and
accessibility are untouched; only their pixels are owner-drawn. `Esc`, close,
and timeout remain safe denials.

## Promotion boundary

This is one retained isolated visual cell at one observed DPI, reviewed live by
the operator. It does not verify Presence, 100% or 125% DPI, Chrome/Word
foreground composition, durable Demo transition wiring, a complete
Chrome-to-Word run, provider behaviour, application acceptance, universal GUI
behaviour, or release readiness. Presence remains capture-excluded by design.
