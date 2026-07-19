# Capability status and evidence dashboard

> **Status: current review dashboard, verified 2026-07-18.** This page is the
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
| MCP Server | `YES` | `YES` — nine-tool Windows stdio server, including bounded OCR | `YES` | `N/A` | `YES` — [the five-case Windows activation regression passed](E4_EVIDENCE.md) in the isolated VM | `PARTIAL` — bounded BOSS [home](BOSS_EVIDENCE.md) and [interested-jobs OCR](BOSS_OCR_EVIDENCE.md) observations passed, not application acceptance | Add a bounded multi-item read-only BOSS campaign with restart evidence |
| Agent Host | `YES` | `PARTIAL` — dual-provider read-only loop, private signed/redacted Claude reasoning-block continuation, and locally approved actions | `YES` | `YES` — [OpenAI and Claude passed](E3_EVIDENCE.md) both bounded fake-MCP E3 cases with reviewed model IDs; Sonnet 5 compatibility is revalidated on the exact repair commit | `YES` — [both reviewed providers passed](E4_EVIDENCE.md) read-only and one approved action with post-action verification | `NO` | Proceed to bounded application evidence without widening action authority |
| Planner / Executor | `YES` | `PARTIAL` — `plan run` composes one provider plan, 1-4 observations through the sole Runner boundary, and one tool-free final response; side effects remain unavailable | `YES` | `YES` — [OpenAI and Claude passed](E3_EVIDENCE.md) the exact bounded CLI path with reviewed model IDs | `NO` | `NO` | Retain isolated E4 evidence; any side-effect expansion remains a separate review |
| Campaign | `YES` | `PARTIAL` — the synthetic seam and host-status projection remain bounded; an internal BOSS discovery module now creates the fixed manifest and idempotently records stable public job keys from complete reviewed UIA link values | `YES` | `NO` | `YES` — [the exact on-device synthetic path passed](SYNTHETIC_CAMPAIGN_EVIDENCE.md); BOSS discovery is offline only | `NO` | Connect fixed BOSS discovery to the project MCP path, then run the multi-item restart gate; no general worker |
| Observation | `YES` | `PARTIAL` — UIA, full primary-display screenshot, bounded region OCR, and bounded Agent image handling exist; document text, standalone crop, and delta sources do not | `YES` — OCR limits, schema, redaction, timeout, and result projection are tested | `NO` | `YES` — [BOSS OCR evidence](BOSS_OCR_EVIDENCE.md) recovered a missing static tab and matched one job card to UIA | `PARTIAL` — one real page and card, not application acceptance | Exercise the same source ladder across bounded multi-item and restart cases |
| Operator UI | `YES` | `PARTIAL` — console yes/deny approval and internal fake-host status decisions exist; presence indicator, passive progress window, Decision Cards, public status tool, and notification bridge do not | `PARTIAL` — approval and status-decision paths have fake evidence | `NO` | `NO` | `NO` | Implement the checkpoint-to-view-model reducer and isolated viewer smoke; keep mobile delivery host-owned |
| Continual Learning | `YES` | `NO` — current explicit memory is not automatic learning | `NO` | `NO` | `NO` | `NO` | Deliver L0 normalized episode outcomes and complete cost vectors before candidate extraction or strategy routing |

## Verification snapshot

The following read-only checks were run against this checkout on 2026-07-19:

~~~text
python -m pytest -q              903 passed, 5 skipped
ruff check .                     PASS
relative Markdown targets       PASS
~~~

These results support offline claims only. The separately retained E3 and E4
records fill only their explicitly scoped provider and desktop cells; neither
fills real-application, release, or complete-demo evidence cells.

Separately, the retained [provider E3 record](E3_EVIDENCE.md) supports the two
dual-provider `YES` cells above. It is model-scoped and records the historical
Sonnet 5 compatibility failure; the implemented reasoning-block repair has an
exact-commit retained rerun. Neither record alters the offline snapshot
or fills application or release gates. The separate
[E4 record](E4_EVIDENCE.md) is likewise VM-, model-, and repair-tree-scoped.

## Active priorities

1. **Bounded application evidence:** the repaired `activate_window` path, both
   reviewed providers, the [BOSS home observation](BOSS_EVIDENCE.md), and the
   separate [interested-jobs OCR result](BOSS_OCR_EVIDENCE.md) have retained
   evidence. This remains narrower than BOSS campaign acceptance and does not
   widen action authority.
2. **Observation vertical slice:** [the retained OCR result](BOSS_OCR_EVIDENCE.md)
   recovered a static BOSS tab omitted by UIA, used a fresh OCR target check,
   entered the interested-jobs page, and measured one UIA/OCR card comparison.
   Next reuse that ladder across bounded multi-item and restart cases.
3. **Runtime connection:** the fixed campaign seam now reuses the Agent
   authority boundary through correlated `OBSERVED`, extracts only a bounded
   non-sensitive window count, commits its verified canonical digest, closes the
   batch with measured usage, writes deterministic handoff, and transfers a
   fresh Runner run using only those durable records. A third fixed CLI command
   now prepares the sole manifest, item, heartbeat, batch, and claim without a
   provider, MCP port, or selector. The complete sequence now has
   [retained on-device state, trace, and cost evidence](SYNTHETIC_CAMPAIGN_EVIDENCE.md).
   The bounded internal terminal-status projection and fake-host polling
   contract are now offline verified. No public status tool or general worker is
   connected; proceed to the bounded multi-item BOSS restart gate.
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
