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
| MCP Server | `YES` | `YES` — eight-tool Windows stdio server | `YES` | `N/A` | `YES` — [the five-case Windows activation regression passed](E4_EVIDENCE.md) in the isolated VM | `PARTIAL` — [a bounded read-only BOSS home observation passed](BOSS_EVIDENCE.md), not an application acceptance pass | Add one bounded static-content source, then retain a separate interested-jobs result |
| Agent Host | `YES` | `PARTIAL` — dual-provider read-only loop, private signed/redacted Claude reasoning-block continuation, and locally approved actions | `YES` | `YES` — [OpenAI and Claude passed](E3_EVIDENCE.md) both bounded fake-MCP E3 cases with reviewed model IDs; Sonnet 5 compatibility is revalidated on the exact repair commit | `YES` — [both reviewed providers passed](E4_EVIDENCE.md) read-only and one approved action with post-action verification | `NO` | Proceed to bounded application evidence without widening action authority |
| Planner / Executor | `YES` | `PARTIAL` — `plan run` composes one provider plan, 1-4 observations through the sole Runner boundary, and one tool-free final response; side effects remain unavailable | `YES` | `YES` — [OpenAI and Claude passed](E3_EVIDENCE.md) the exact bounded CLI path with reviewed model IDs | `NO` | `NO` | Retain isolated E4 evidence; any side-effect expansion remains a separate review |
| Campaign | `YES` | `PARTIAL` — three fixed CLI commands prepare one exact synthetic claim, execute it through Runner handoff, and enter durable fresh-run resume | `YES` | `NO` | `YES` — [the exact on-device three-command synthetic path passed](SYNTHETIC_CAMPAIGN_EVIDENCE.md) | `NO` | Add the bounded read-only terminal-status projection and fake-host polling contract; no general worker |
| Observation | `YES` | `PARTIAL` — UIA, full primary-display screenshot, and bounded Agent image handling exist; document text, OCR, region, and delta sources do not | `PARTIAL` | `NO` | `PARTIAL` — BOSS probe proved useful UIA controls and missing static content | `NO` | Implement one bounded OCR or document-text vertical slice with source/cost evidence and no challenge bypass |
| Operator UI | `YES` | `PARTIAL` — console yes/deny approval exists; presence indicator, passive progress window, Decision Cards, and host completion notification bridge do not | `PARTIAL` — approval path has fake-port evidence; notification semantics are documentation only | `NO` | `NO` | `NO` | Implement the checkpoint-to-view-model reducer and isolated viewer smoke; the retained synthetic gate now permits fake-host terminal polling work |
| Continual Learning | `YES` | `NO` — current explicit memory is not automatic learning | `NO` | `NO` | `NO` | `NO` | Deliver L0 normalized episode outcomes and complete cost vectors before candidate extraction or strategy routing |

## Verification snapshot

The following read-only checks were run against this checkout on 2026-07-18:

~~~text
python -m pytest -q              890 passed, 5 skipped
ruff check src tests scripts    PASS
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
   reviewed providers, and [one bounded on-device BOSS home observation](BOSS_EVIDENCE.md)
   have retained evidence. This closes the narrow post-repair P0 without
   implying BOSS workflow acceptance or widening action authority.
2. **Observation vertical slice:** the retained BOSS probes showed that static
   browser content can be absent from the interactive UIA tree. Add one bounded
   fallback and measure its total cost per verified result.
3. **Runtime connection:** the fixed campaign seam now reuses the Agent
   authority boundary through correlated `OBSERVED`, extracts only a bounded
   non-sensitive window count, commits its verified canonical digest, closes the
   batch with measured usage, writes deterministic handoff, and transfers a
   fresh Runner run using only those durable records. A third fixed CLI command
   now prepares the sole manifest, item, heartbeat, batch, and claim without a
   provider, MCP port, or selector. The complete sequence now has
   [retained on-device state, trace, and cost evidence](SYNTHETIC_CAMPAIGN_EVIDENCE.md).
   Next add only the bounded terminal-status projection and fake-host polling
   contract. No general worker is connected.
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
