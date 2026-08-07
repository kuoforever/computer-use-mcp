# Isolated Operator HUD visual evidence

> **Status: superseded for the Decision Card.** Its presentation was replaced
> by the rebuild recorded in
> [the 2026-08-01 matrix](OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md). The
> observations below are retained unedited as the 2026-07-30 record; do not
> cite them as the current Decision Card appearance.

Date: 2026-07-30

## Scope

This retained matrix covers only the synthetic Decision Card and workflow
Progress HUD renderers. The source baseline was `df35711` (pre-rebase
`19840a9`); the capture helper, default-expanded workflow behavior,
single-instance visual-review guard, tests, and this record are retained
together at `efc5062` (pre-rebase `d1507e3`). The branch was rebased onto
`main` at `9cb38c8` on 2026-07-31; these images were captured before that
rebase and were not re-collected.

No Runner, MCP server, provider, Chrome/Word action, approval dispatch, network
request, or complete Demo ran while collecting these images. All labels and
state are fixed reviewed fixture data.

The capture process entered Per-Monitor DPI Aware V2 before importing its pixel
backend. The observed system DPI was 144 (150%). It required one exact
white-listed synthetic title, the expected compact/expanded aspect, and stable
geometry before cropping only that window rectangle. Ambiguous, missing,
wrong-state, or already-owned output failed closed.

## Retained matrix

| Surface | State | Result | Artifact and SHA-256 |
| --- | --- | --- | --- |
| Decision Card | Default compact | Approval/workflow positions, application, fixed action, countdown, details affordance, and four short choices are readable without a scroll area. | [PNG](evidence/operator-hud/2026-07-30/decision-card-compact.png), `5A75E264C8699141663041978106DBBAB6C16962F0D0EBC052D450A4117040BD` |
| Decision Card | Expanded details | The same pending decision shows human-readable scope, choice trade-offs, safety checks, and bounded evidence; the 2x2 choices remain wholly visible. | [PNG](evidence/operator-hud/2026-07-30/decision-card-expanded.png), `CA3397D215DD52675FEEAEAD58BF030DA7ACDD2907C6A602DBB290C8A83BD82C` |
| Progress HUD | Default expanded | The six Host-owned steps are visible immediately, with completed, current, and not-started states plus the exact current application. | [PNG](evidence/operator-hud/2026-07-30/progress-hud-expanded.png), `A6E1C1665526BE927C23BCCBBB9A78DEE706FCE6154BE39BB2FB4986EE2350A4` |
| Progress HUD | Operator-collapsed | The summary retains overall counts, current step, current action, application, and a `SHOW STEPS` affordance. | [PNG](evidence/operator-hud/2026-07-30/progress-hud-compact.png), `24A070A7D34720DE453DEFEA606C73739CC008A90C8A87F9026A3A4A7CDA507F` |

Computer Use inspected the live synthetic windows at this DPI. It confirmed the
Decision Card compact hierarchy and the Progress HUD default checklist and
explicit collapsed state. The retained images were separately reviewed for
wrong-coordinate capture, compositor-transition transparency, clipping, and
unrelated foreground content; two invalid intermediate capture attempts were
replaced and are not retained.

## Reproduction

Run the capture watcher before opening a review surface. Each review kind owns
one named local mutex, so a duplicate instance exits instead of leaving
overlapping synthetic cards.

~~~powershell
.venv\Scripts\python.exe scripts\capture_operator_hud_evidence.py `
  decision-card-compact decision-card-expanded --wait-seconds 120
.venv\Scripts\python.exe scripts\show_decision_card_layout.py `
  --timeout-seconds 600

.venv\Scripts\python.exe scripts\capture_operator_hud_evidence.py `
  progress-expanded --wait-seconds 120
.venv\Scripts\python.exe scripts\show_progress_summary.py `
  --inspection-frame --timeout-seconds 600

.venv\Scripts\python.exe scripts\capture_operator_hud_evidence.py `
  progress-compact --wait-seconds 120
.venv\Scripts\python.exe scripts\show_progress_summary.py `
  --inspection-frame --collapsed --timeout-seconds 600
~~~

Decision details are expanded through the visual-only `--expanded` review
option or the live `Show details` control. Progress defaults to the full
checklist; `--collapsed` exists only to review the operator-collapsed state.

## Promotion boundary

This fills one retained isolated visual cell at one observed DPI. It does not
verify Presence, 100% or 125% DPI, Chrome/Word foreground composition, durable
Demo transition wiring, a complete Chrome-to-Word run, provider behavior,
application acceptance, universal GUI behavior, or release readiness. Presence
remains capture-excluded by design and must not be made capturable merely to
produce a screenshot.
