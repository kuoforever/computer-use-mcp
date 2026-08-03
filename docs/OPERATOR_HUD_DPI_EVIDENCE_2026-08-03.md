# Decision Card live DPI acceptance — 2026-08-03

> **Result: PASS at 100% and 125% Windows display scaling.**

## Scope

The operator changed Windows display scaling manually. At each scale, the
existing visual-only Decision Card review opened synthetic, non-dispatching
data. The fail-closed capture helper selected exactly one visible window with
the fixed `Needs input · approval locked` title, required stable geometry, and
captured only that exact rectangle.

No Runner, MCP, provider, application action, or system-setting automation was
opened by the review.

## Evidence

| Scale | System DPI | State | Result | Artifact |
| ---: | ---: | --- | --- | --- |
| 100% | 96 | Compact | Full title, countdown, approval/workflow qualifiers, details affordance, and 2x2 choices are visible without clipping, overlap, or scroll. | [PNG](evidence/operator-hud/2026-08-03/decision-card-compact-100pct.png), `08BD0BEACB4CA813BE65D364BAE7D50C86F31F6336CDB4A582BFC4541F6AD177` |
| 100% | 96 | Expanded | Detail pane, scrollbar, and 2x2 choices remain inside the work area with no clipped controls. | [PNG](evidence/operator-hud/2026-08-03/decision-card-expanded-100pct.png), `DC2F8B5AC873D6BEB86B5E72BBDD88A46EA5355A99A86C8CC49498AE445CD60A` |
| 125% | 120 | Compact | The scaled hierarchy and all controls remain fully readable with no clipping, overlap, or unexpected scroll. | [PNG](evidence/operator-hud/2026-08-03/decision-card-compact-125pct.png), `431DD1B2E79A1964F197B82B2CA1C3B98185F42567F44427B21C43EA2DDDDD64` |
| 125% | 120 | Expanded | The scaled detail pane, scrollbar, and action grid remain bounded and readable. | [PNG](evidence/operator-hud/2026-08-03/decision-card-expanded-125pct.png), `DDBEE536E70BDDABA3AAB191843F0DD6770E28DCD6B82170B6D2A5951060C6D4` |

The dated fixed capture slots contain the final 125% captures. The four
scale-suffixed artifacts are byte-identical retained copies of the exact
fail-closed captures made at their named scale.

## Boundary

This closes the live 100% and 125% clauses of `GDA-HUD-002`. The existing
150% evidence remains in `OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md`.
Physical Alt+Tab availability is owned separately by `GDA-HUD-004` and is not
inferred from these screenshots.
