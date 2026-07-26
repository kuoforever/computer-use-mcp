# Capability status and evidence dashboard

> **Status: current review dashboard, verified 2026-07-22.** This page is the
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
| MCP Server | `YES` | `YES` — thirteen-tool Windows stdio server, including bounded OCR, region capture, UIA document text, scroll, and drag | `YES` | `N/A` | `PARTIAL` — [the five-case Windows activation regression](E4_EVIDENCE.md) and bounded [document-text result](DOCUMENT_TEXT_EVIDENCE.md) passed on-device; scroll and drag are offline-verified only | `PARTIAL` — bounded BOSS [home](BOSS_EVIDENCE.md) and [interested-jobs OCR](BOSS_OCR_EVIDENCE.md) observations plus a real UIA [document-text](DOCUMENT_TEXT_EVIDENCE.md) channel passed; no multi-item application workflow has passed | Retain on-device scroll and drag evidence, then a bounded multi-item read-only BOSS campaign with restart evidence |
| Agent Host | `YES` | `PARTIAL` — dual-provider read-only loop, private signed/redacted Claude reasoning-block continuation, and locally approved actions | `YES` | `YES` — [OpenAI and Claude passed](E3_EVIDENCE.md) both bounded fake-MCP E3 cases with reviewed model IDs; Sonnet 5 compatibility is revalidated on the exact repair commit | `YES` — [both reviewed providers passed](E4_EVIDENCE.md) read-only and one approved action with post-action verification | `NO` | Proceed to bounded application evidence without widening action authority |
| Planner / Executor | `YES` | `PARTIAL` — `plan run` composes one provider plan, 1-4 observations through the sole Runner boundary, and one tool-free final response; side effects remain unavailable | `YES` | `YES` — [OpenAI and Claude passed](E3_EVIDENCE.md) the exact bounded CLI path with reviewed model IDs | `NO` | `NO` | Retain isolated E4 evidence; any side-effect expansion remains a separate review |
| Campaign | `YES` | `PARTIAL` — one manifest-routed runtime composes fifteen reviewed identity/observation/navigation/verification/approval capabilities into validated scenario specs; A1-A19 are built-in examples, while another spec can be registered without changing Runner or campaign control. Explicit stable-item preparation, one-item provider execution, strict semantic result validation, digest commit, handoff, fresh-run resume, exhausted-manifest completion, terminal handoff, and exact heartbeat retirement share the existing boundaries. Composable `link_url`/`control_name` discovery adapters bound to a campaign kind now derive stable item keys from one bounded foreground observation, and the campaigns they create enter the same start/run/resume path; only BOSS keeps a separate fixed discovery contract with retained on-device evidence | `YES` — all built-in examples plus a custom composition route through shared control; capability/tool derivation, provider result substitution, claimed-but-unexecuted evidence, registry refusal, exact-plan commit/handoff, fresh transfer/resume, idempotent terminalization, and adapter extraction/bounds/pass-ledger invariants fail closed in tests | `NO` — the new generic provider worker has no retained live-provider result | `PARTIAL` — the earlier fixed [synthetic path](SYNTHETIC_CAMPAIGN_EVIDENCE.md), BOSS [two-pass discovery](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md), and partial [three-item diagnostic](BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md) passed on-device; generic examples remain offline-only | `PARTIAL` — earlier BOSS identity-only commits, not clean semantic A1 acceptance or broader application acceptance | Retain one clean A1 semantic campaign, then promote scenarios individually; no universal capability claim before evidence |
| Observation | `YES` | `PARTIAL` — UIA, full primary-display screenshot, bounded region OCR, bounded region image capture, bounded UIA document text, and bounded Agent image handling exist; delta observations do not | `YES` — OCR, capture, and document-text limits, schemas, redaction, timeout, and result projection are tested | `NO` | `PARTIAL` — [BOSS OCR evidence](BOSS_OCR_EVIDENCE.md) recovered a missing static tab and matched one job card to UIA; bounded [document text](DOCUMENT_TEXT_EVIDENCE.md) and a synthetic [region capture](CAPTURE_REGION_EVIDENCE.md) passed on-device | `PARTIAL` — one real page and card plus synthetic image/text slices, not application acceptance | Exercise the observation ladder across bounded multi-item and restart cases |
| Operator UI | `YES` | `PARTIAL` — console approval, an opt-in four-choice focus-taking Decision Card with configurable corner placement, normal drag/resize/minimize/maximize behavior, non-topmost stacking, responsive buttons, scrollable digest evidence, same-run re-observe, durable non-resumable defer, passive progress with explicit token-coverage, screenshot, and checkpoint-elapsed facts, and opt-in fail-silent ordinary-run, bounded-plan, read-only recovery, and fixed MCP-backed campaign execution progress/presence lifecycles exist; zero-port campaign control remains window-free, while public status, notifications, and general process resume do not | `YES` — [re-observe/defer evidence](DECISION_CARD_RECOVERY_EVIDENCE.md) covers zero-dispatch decisions, stale-turn abandonment, fresh-observation gating, `PAUSED` persistence/recovery projection, and the sole Runner dispatch boundary; progress/presence tests cover redaction, legacy unknowns, metric integrity, lifecycle isolation, durable bounded-plan/recovery/campaign projection, phase-free campaign progress wake, authority-loss teardown, and final cleanup | `NO` | `YES` — native [four-option Decision Card focus/resize/scroll/timeout evidence](DECISION_CARD_WINDOW_EVIDENCE.md), ordinary progress [lifecycle evidence](PROGRESS_LIFECYCLE_EVIDENCE.md), provider-free bounded-plan [progress](PLAN_PROGRESS_LIFECYCLE_EVIDENCE.md) and [presence](PLAN_PRESENCE_LIFECYCLE_EVIDENCE.md) evidence, persisted read-only [recovery progress evidence](RECOVERY_PROGRESS_LIFECYCLE_EVIDENCE.md), fixed synthetic [campaign progress evidence](CAMPAIGN_PROGRESS_LIFECYCLE_EVIDENCE.md), and ordinary-run native presence evidence are retained; recovery and BOSS campaign presence plus BOSS campaign progress remain offline-only | `NO` | Retain a human-operated four-choice cross-application UX result without widening action authority |
| Continual Learning | `YES` | `NO` — current explicit memory is not automatic learning | `NO` | `NO` | `NO` | `NO` | Deliver L0 normalized episode outcomes and complete cost vectors before candidate extraction or strategy routing |

## Verification snapshot

The following read-only checks are the offline gate for this repository. Every
pull request and every push to `main` runs them on Windows across Python 3.11,
3.12, and 3.13; see the [CI workflow](../.github/workflows/ci.yml) and the
[latest runs](https://github.com/kuoforever/computer-use-mcp/actions/workflows/ci.yml)
for the exact per-run totals.

~~~text
python -m pytest -q                          offline suite
python -m ruff check src tests scripts       lint
python -m mypy                               types
python scripts/check_docs_consistency.py     current-state tool surface
~~~

This page deliberately does not restate a running test total. That number moves
on nearly every commit, and a hand-maintained copy of it drifts silently. Dated
evidence records keep the exact totals observed by their own runs; this
dashboard states the gate, not a snapshot of it.

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
   contract are now offline verified. BOSS discovery now accumulates across a
   durable, append-only discovery-pass ledger that refuses an unchanged source,
   bounds the pass count, fails closed on a torn ledger, and is reconstructed by
   a fresh run from durable records alone; this advanced the BOSS policy and
   schema digests. The current contract now has a
   [retained two-pass on-device result](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md)
   with twelve stable identities and distinct source digests. No public status
   tool or general worker is connected. Fixed BOSS worker boundaries now open
   the exact coordinator-selected batch, verify and digest-commit one exact
   claimed identity through one project-MCP snapshot, write handoff, transfer
   heartbeat ownership to a fresh zero-port run, and claim the exact next item.
   A partial [on-device diagnostic](BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md)
   retained three commits and a clean post-fix stale recovery while explicitly
   preserving two defects found during the sequence. Run a fresh uncorrected
   sequence before semantic extraction or the 100-item gate.
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
