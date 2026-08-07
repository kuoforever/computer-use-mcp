# Capability status and evidence dashboard

> **Status: current review dashboard, verified 2026-08-07.** This page is the
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
| MCP Server | `YES` | `YES` — thirteen-tool Windows stdio server, including bounded OCR, region capture, UIA document text, scroll, and drag | `YES` | `N/A` | `PARTIAL` — [the five-case Windows activation regression](E4_EVIDENCE.md), bounded [document-text result](DOCUMENT_TEXT_EVIDENCE.md), exact-candidate [Desktop Ask result](DESKTOP_ASK_EVIDENCE.md), and fixed [public-web-to-Word result](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) passed on-device; scroll and drag are offline-verified only | `PARTIAL` — bounded BOSS [home](BOSS_EVIDENCE.md) and [interested-jobs OCR](BOSS_OCR_EVIDENCE.md) observations plus real UIA [document text](DOCUMENT_TEXT_EVIDENCE.md), one Notepad [Desktop Ask](DESKTOP_ASK_EVIDENCE.md), and one fixed Chrome-to-Word [workflow](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) passed | Preserve these exact scopes; broaden applications only through retained evidence |
| Agent Host | `YES` | `PARTIAL` — installed `config init` / `config doctor`, dual-provider read-only loop, private signed/redacted Claude reasoning-block continuation, locally approved actions, provider request timeout, and fixed `workflow public-web-word` composition | `YES` — doctor fail-fast setup UX, exact thirteen-tool installed-MCP discovery, model-authored brief/save/reopen happy path, and wheel resource contract are functional gates | `YES` — [OpenAI and Claude passed](E3_EVIDENCE.md) both bounded fake-MCP E3 cases with reviewed model IDs; Sonnet 5 compatibility is revalidated on the exact repair commit | `YES` — [both reviewed providers passed](E4_EVIDENCE.md) read-only and one approved action with post-action verification; exact-candidate [Desktop Ask](DESKTOP_ASK_EVIDENCE.md) and fixed [public-web-to-Word](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) runs also passed through the installed Host | `PARTIAL` — one OpenAI `gpt-5.6-terra` Notepad answer and one fixed OpenAI/Chrome/Word workflow passed through the installed product; no broader application claim | Run exact-candidate integration and release gates without widening the retained application scope |
| Planner / Executor | `YES` | `PARTIAL` — `ask` / `plan run` provide bounded observation planning, while `workflow public-web-word` wraps a real provider that chooses reviewed cross-app steps and authors a source-grounded brief under a fixed Host envelope | `YES` — the functional model chooses 19 primary tool calls, writes a non-prewritten three-bullet brief, saves, closes, reopens, and completes 21 total calls across two Runner/MCP loops | `YES` — [OpenAI and Claude passed](E3_EVIDENCE.md) the earlier bounded scope, and one exact-candidate OpenAI `gpt-5.6-terra` [document-aware plan](DESKTOP_ASK_EVIDENCE.md) passed | `PARTIAL` — one Windows 11 foreground `document_text -> final_response` plan and one fixed model-driven [Chrome-to-Word plan](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) passed from clean wheels | `PARTIAL` — one synthetic Notepad answer and one fixed public-browser-to-disposable-Word workflow are retained | Keep broader side-effect and application expansion separate; next run only the release-candidate integration gate |
| Campaign | `YES` | `PARTIAL` — one manifest-routed runtime composes fifteen reviewed identity/observation/navigation/verification/approval capabilities into validated scenario specs; A1-A19 are built-in examples, while another spec can be registered without changing Runner or campaign control. Explicit stable-item preparation, one-item provider execution, strict semantic result validation, digest commit, handoff, fresh-run resume, exhausted-manifest completion, terminal handoff, and exact heartbeat retirement share the existing boundaries. Composable `link_url`/`control_name` discovery adapters bound to a campaign kind now derive stable item keys from one bounded foreground observation, and the campaigns they create enter the same start/run/resume path; only BOSS keeps a separate fixed discovery contract with retained on-device evidence, plus three fixed offline semantic CLIs that open one-item/five-call/zero-side-effect batches, accept only strict provider JSON under a fixed no-preference policy, and commit canonical result digests | `YES` — all built-in examples plus a custom composition route through shared control; capability/tool derivation, provider result substitution, claimed-but-unexecuted evidence, registry refusal, exact-plan commit/handoff, fresh transfer/resume, idempotent terminalization, and adapter extraction/bounds/pass-ledger invariants fail closed in tests | `NO` — the new generic provider worker has no retained live-provider result | `PARTIAL` — the earlier fixed [synthetic path](SYNTHETIC_CAMPAIGN_EVIDENCE.md), BOSS [two-pass discovery](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md), the historical [three-item diagnostic](BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md), and the clean [three-item restart sequence](BOSS_ITEM_RESTART_CLEAN_EVIDENCE.md) passed on-device; generic examples and adapters remain offline-only | `PARTIAL` — the clean gate retained twelve identities and three consecutive fresh-run identity-only commits with zero correction, provider calls, tokens, retryable items, or uncertain items; semantic extraction, provider rotation, and the 100-item gate remain open | Retain one on-device BOSS semantic item and one clean A1 semantic campaign, then promote scenarios individually; no universal capability claim before evidence |
| Observation | `YES` | `PARTIAL` — UIA, full primary-display screenshot, bounded region OCR, bounded region image capture, bounded UIA document text, bounded Agent image handling, and a pure BOSS per-item ladder reducer exist; delta observations do not | `YES` — OCR, capture, and document-text limits, schemas, redaction, timeout, and result projection are tested | `NO` | `PARTIAL` — [BOSS OCR evidence](BOSS_OCR_EVIDENCE.md) recovered a missing static tab and matched one job card to UIA; bounded [document text](DOCUMENT_TEXT_EVIDENCE.md) and a synthetic [region capture](CAPTURE_REGION_EVIDENCE.md) passed on-device | `PARTIAL` — one real page and card plus synthetic image/text slices, not application acceptance | Exercise the observation ladder across bounded multi-item and restart cases |
| Operator UI | `YES` | `PARTIAL` — console approval, a focus-taking four-choice Decision Card, passive presence/progress, CLI-first Task Center and receipts, Pre-run Review, cooperative control, Approval Inbox/local notifications, and bounded Windows [accessibility](OPERATOR_ACCESSIBILITY.md), [English/Simplified-Chinese localization](OPERATOR_LOCALIZATION.md), [dark/light/system personalization](OPERATOR_PERSONALIZATION.md), and [native multi-display composition](OPERATOR_MULTI_DISPLAY.md) contracts exist. Safe keyboard traversal, native UIA Text/Edit/Button semantics, bounded status announcements, system High Contrast/reduced motion, 200%/400% text reflow, locale-neutral authority, strict theme fallback/precedence, and foreground-monitor rectangle/work-area/DPI selection are implemented and offline verified. Other CLI localization, general process resume, terminal/mobile notifications, native Inbox UI, custom/learned/per-application personalization, and human Narrator/NVDA/visual-design/physical-two-monitor review remain absent | `YES` — exact approval/re-observe/defer, generated defaults, progress/presence isolation, Task Center receipts, cooperative control, Approval Inbox boundaries, accessibility fallback, contrast, focus/order/action, announcements, UIA names, large-text layout, strict locale and theme resolution, two-locale copy, palette precedence, unknown-text preservation, stable IDs, negative monitor coordinates, offset work areas, mixed DPI, and primary fallback are covered by deterministic tests | `NO` | `YES` — native [Decision Card](DECISION_CARD_WINDOW_EVIDENCE.md), [progress](PROGRESS_LIFECYCLE_EVIDENCE.md), [presence](PRESENCE_WINDOW_EVIDENCE.md), and current [feature-freeze non-E4 evidence](FEATURE_FREEZE_NON_E4_EVIDENCE.md) cover five dark/light/High-Contrast/200%/400% presentation cases in both locales, fixed notification lifecycle, current-card approved/timeout fake-port behavior, and one earlier human-approved fixed [Chrome-to-Word workflow](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md); physical two-monitor and human assistive-technology/visual review remain unverified | `PARTIAL` — Decision Cards authorized the exact fixed cross-application result; accessibility/localization/personalization/multi-display presentation and passive/read-only/attention surfaces do not widen authority or create application evidence | Run exact-current installed Notepad Desktop Ask and fixed Chrome-to-Word integration without E4; retain physical two-monitor, human Narrator/NVDA, and human 200%/400% visual review as explicit open gates |
| Pre-run Review | `YES` | `PARTIAL` — `review public-web-word` and the default workflow start gate compile a human/JSON Scope Sheet from Host-fixed contract fields and exact local paths before any provider, MCP, application, desktop, or fixture startup. Exact `START` or `--acknowledge-scope` enters only the ordinary workflow and grants no action approval, retry, or replay authority; other commands and workflows do not yet have this surface | `YES` — complete fields, contract drift, output preconditions, human/JSON parity, cancel/EOF zero-work behavior, exact acknowledgement, one config load, and bound config/request handoff are tested | `NO` | `NO` — no native window or live-desktop result | `NO` — the retained public-web-word result predates this surface | Retain the Scope Sheet in the final feature-freeze candidate; broaden it only through another fixed Host workflow contract |
| Cooperative desktop control | `YES` | `PARTIAL` — the installed public-web-word Runner loops expose strict local `control`, `pause`, `takeover`, and `resume` commands plus a Decision Card takeover choice. Pause is acknowledged only at a durable safe boundary, authority release is explicit, resume discards old approval/grounding and requires fresh observation, and uncertain work is never replayed. Other workflows, campaigns, crash recovery, remote control, and `BlockInput` are excluded | `YES` — live-lease and checkpoint binding, atomic lifecycle, CLI human/JSON routing, nested verifier state, stale-call rejection, observation-only resumption, Decision Card takeover, continuation incompatibility, and unknown-outcome precedence are tested | `NO` | `NO` — no native takeover timing or focus result | `NO` — retained public-web-word evidence predates this control lane | Run a disposable native takeover/resume smoke after feature freeze, then retain it only on the exact release candidate |
| Approval Inbox and local notification | `YES` | `PARTIAL` — Decision Card compilation publishes one strict private expiring identity/digest record, `approval inbox` renders bounded human/JSON inspection without a liveness claim, and an optional Win32 notification carries fixed English or Simplified-Chinese content only. Inbox and notification have no approval, task-control, provider, MCP, desktop, replay, retry, or dispatch port; console approval, mobile push, Inbox CLI localization, and a native Inbox window are excluded | `YES` — binding/expiry lifecycle, registry action coverage, content exclusion, corrupt isolation, strict bounds, two-locale fixed notification payload, CLI parity, configuration, notification failure isolation, and Decision Card cleanup are tested | `NO` | `PARTIAL` — native show/withdraw passed from an installed no-console executable before localization; current two-locale delivery is not assistive-technology evidence | `NO` — no application behavior is claimed | Retain human screen-reader review and final notification presentation on the exact feature-freeze candidate |
| Hierarchical control | `PARTIAL` — [the direction, closed node set, fail-closed propagation, and `H1`-`H8` order](HIERARCHICAL_TASK_AND_BEHAVIOR_TREES.md) are recorded; no node schema, digest, or store contract is fixed | `NO` — the current `TaskPlan` is flat and strictly ordered | `NO` | `N/A` | `N/A` | `N/A` | Fix the `H1` node schema, tree digest, structural limits, and pure state-reduction rules before any store or runtime work |
| Continual Learning | `YES` | `NO` — current explicit memory is not automatic learning | `NO` | `NO` | `NO` | `NO` | Deliver L0 normalized episode outcomes and complete cost vectors before candidate extraction or strategy routing |

## Verification snapshot

The following read-only checks are the offline gate for this repository. Every
pull request and every push to `main` runs them on Windows across Python 3.11,
3.12, and 3.13; see the [CI workflow](../.github/workflows/ci.yml) and the
[latest runs](https://github.com/kuoforever/guarded-desktop-agent/actions/workflows/ci.yml)
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
The [Desktop Ask record](DESKTOP_ASK_EVIDENCE.md) adds one exact-candidate
OpenAI/Windows/Notepad read-only application result. It does not fill another
provider, application, side-effect, multi-monitor, or release gate.
The [Public Web to Word record](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) adds one
fixed OpenAI/Windows/Chrome/Word side-effect workflow with human approvals,
durable save/reopen verification, real-Word visual QA, and exact fixture
cleanup. It does not establish arbitrary sites, applications, providers,
unattended operation, or release readiness.

## Active priorities

1. **Installed product verticals:** the installed-first-run configuration,
   public `ask` command, reviewed Planner scope, and semantic document-text
   flow have one exact-candidate Windows/OpenAI/Notepad
   [result](DESKTOP_ASK_EVIDENCE.md). The installed model-driven
   public-browser-to-disposable-Word workflow now also has one exact-candidate
   provider/Chrome/Word [result](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md). Neither
   result broadens beyond its recorded application and authority scope; the
   release-candidate integration gate remains separate.
2. **Bounded application evidence:** the repaired `activate_window` path, both
   reviewed providers, the [BOSS home observation](BOSS_EVIDENCE.md), and the
   separate [interested-jobs OCR result](BOSS_OCR_EVIDENCE.md) have retained
   evidence. This remains narrower than BOSS campaign acceptance and does not
   widen action authority.
3. **Observation vertical slice:** [the retained OCR result](BOSS_OCR_EVIDENCE.md)
   recovered a static BOSS tab omitted by UIA, used a fresh OCR target check,
   entered the interested-jobs page, and measured one UIA/OCR card comparison.
   Next reuse that ladder across bounded multi-item and restart cases.
4. **Runtime connection:** the fixed campaign seam now reuses the Agent
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
   preserves the two defects found during the earlier sequence. The later
   [clean on-device sequence](BOSS_ITEM_RESTART_CLEAN_EVIDENCE.md) retained
   twelve identities and three consecutive fresh-run commits without local
   correction. The strict semantic runtime and fresh-run transfer are now
   offline verified; next retain one on-device UIA/document-text semantic item
   before the 100-item gate.
5. **Wave 1 evidence:** only after the prior gates, execute BOSS, Google Docs,
   and WeChat draft-only cases and retain success, token, retry, recovery, and
   takeover measurements.
6. **Operator and learning layers:** project real checkpoint/campaign facts into
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
| `H` | [Hierarchical task and behavior trees](HIERARCHICAL_TASK_AND_BEHAVIOR_TREES.md) | Post-linear control-layer delivery phase |
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
