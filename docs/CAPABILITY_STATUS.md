# Capability status and evidence dashboard

> **Status: current review dashboard, verified 2026-07-17.** This page is the
> shortest path to the project's actual boundary. It separates design,
> implementation, offline evidence, provider evidence, desktop evidence, and
> application evidence. A design or offline test is never promoted to a live
> capability merely because its contract is detailed.

## Evidence states

| State | Meaning |
| --- | --- |
| `YES` | The capability exists at that layer and has retained repository evidence. |
| `PARTIAL` | A bounded slice exists, but the complete row-level claim is not supported. |
| `NO` | The layer has not passed or no retained evidence exists. |
| `N/A` | The evidence layer does not apply directly to this capability. |

Provider, desktop, and application columns require retained executable evidence;
documentation, mocks, and unit tests are insufficient. `NO` does not mean a
test was attempted and failed unless a linked evidence record says so.

## Current dashboard

| Capability line | Designed | Implemented | Offline verified | Provider verified | Desktop verified | Application verified | Next gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MCP Server | `YES` | `YES` — eight-tool Windows stdio server | `YES` | `N/A` | `PARTIAL` — prior desktop probes exist; repaired activation path has no retained isolated rerun | `PARTIAL` — one read-only BOSS/Chrome probe, not an application acceptance pass | Run the E4 Windows activation regression, then retain a bounded BOSS observation result |
| Agent Host | `YES` | `PARTIAL` — dual-provider read-only loop and fake-verified approved actions | `YES` | `NO` — E3 is opt-in and no credentialed result is retained | `NO` — E4 has no retained result | `NO` | Pass both providers through harmless E3, then the four-cell isolated E4 matrix |
| Planner / Executor | `YES` | `PARTIAL` — declarative planning, observation runtime, final runtime, and reconciliation preflights are internal only | `YES` | `NO` | `NO` | `NO` | Apply completed-final reconciliation through reviewed local CAS/cleanup, then expose one observation-only CLI path without adding a second dispatch boundary |
| Campaign | `YES` | `PARTIAL` — three fixed CLI commands prepare one exact synthetic claim, execute it through Runner handoff, and enter durable fresh-run resume | `YES` | `NO` | `NO` | `NO` | Retain one on-device three-command synthetic state, trace, and cost evidence run before connecting BOSS |
| Observation | `YES` | `PARTIAL` — UIA, full primary-display screenshot, and bounded Agent image handling exist; document text, OCR, region, and delta sources do not | `PARTIAL` | `NO` | `PARTIAL` — BOSS probe proved useful UIA controls and missing static content | `NO` | Implement one bounded OCR or document-text vertical slice with source/cost evidence and no challenge bypass |
| Operator UI | `YES` | `PARTIAL` — console yes/deny approval exists; presence indicator, passive progress window, Decision Cards, and host completion notification bridge do not | `PARTIAL` — approval path has fake-port evidence; notification semantics are documentation only | `NO` | `NO` | `NO` | Implement the checkpoint-to-view-model reducer and isolated viewer smoke; add fake-host terminal polling only after retained on-device synthetic campaign evidence |
| Continual Learning | `YES` | `NO` — current explicit memory is not automatic learning | `NO` | `NO` | `NO` | `NO` | Deliver L0 normalized episode outcomes and complete cost vectors before candidate extraction or strategy routing |

## Verification snapshot

The following read-only checks were run against this checkout on 2026-07-17:

~~~text
python -m pytest -q              863 passed, 3 skipped
ruff check src tests scripts    PASS
relative Markdown targets       PASS
~~~

These results support offline claims only. They do not fill E3, E4, real-app,
release, or complete-demo evidence cells.

## Active priorities

1. **Evidence correction:** the `activate_window` implementation and unit tests
   now cover input-thread attachment, reverse cleanup, minimized-window restore,
   and foreground postcondition. The remaining P0 is isolated Windows
   validation, not another speculative implementation rewrite.
2. **Observation vertical slice:** the recorded BOSS probe showed that static
   browser content can be absent from the interactive UIA tree. Add one bounded
   fallback and measure its total cost per verified result.
3. **Runtime connection:** the fixed campaign seam now reuses the Agent
   authority boundary through correlated `OBSERVED`, extracts only a bounded
   non-sensitive window count, commits its verified canonical digest, closes the
   batch with measured usage, writes deterministic handoff, and transfers a
   fresh Runner run using only those durable records. A third fixed CLI command
   now prepares the sole manifest, item, heartbeat, batch, and claim without a
   provider, MCP port, or selector. The complete three-command sequence is
   offline verified; next retain one on-device synthetic evidence run. No
   general worker is connected.
4. **Wave 1 evidence:** only after the prior gates, execute BOSS, Google Docs,
   and WeChat draft-only cases and retain success, token, retry, recovery, and
   takeover measurements.
5. **Operator and learning layers:** project real checkpoint/campaign facts into
   the operator UI; begin continual learning with L0 evidence, not automatic
   promotion or model training.

## Taxonomy map

The repository uses several independent numbering systems. They are not a
single sequence:

| Prefix | Owner | Meaning |
| --- | --- | --- |
| `P` | [Roadmap](EXECUTION_PLAN.md) | Product priority or historical milestone |
| `Phase` | [Agent implementation plan](AGENT_IMPLEMENTATION_PLAN.md) | Agent Host delivery decomposition |
| `E` | [Evaluation](EVALUATION.md) | Evidence level, from offline contracts through isolated release regression |
| `A` / `Wave` | [Application matrix](APPLICATION_EVALUATION_MATRIX.md) | Application case and staged coverage group |
| `Act` | [Universal GUI demo](UNIVERSAL_GUI_DEMO.md) | Complete-demo presentation chapter |
| `L` | [Continual learning](CONTINUAL_LEARNING.md) | Learning delivery phase |
| `vN` | Owning contract document | Schema or persisted-artifact version; never a product phase |

## Update rules

- Update this page in the same change that moves a capability between evidence
  states.
- Link the retained report, fixture, trace class, or operator record supporting
  every promotion. Do not rely on chat history.
- Keep exact runtime behavior in the root README, configuration, tools, and
  Agent contract. This dashboard summarizes; it does not override them.
- Keep historical implementation chronology in
  [the archive](archive/CAMPAIGN_CONTROL_STATE_HISTORY.md), not in the active
  roadmap or normative contracts.
- Treat missing metrics as unknown, never zero, and do not collapse a
  `PARTIAL` row into a complete product claim.
