# Capability status and evidence dashboard

> **Status: current review dashboard, verified 2026-08-09.** This page is the
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
| Agent Host | `YES` | `PARTIAL` — installed `config init` / `config doctor`, dual-provider read-only loop, private signed/redacted Claude reasoning-block continuation, locally approved actions, provider request timeout, and fixed `workflow public-web-word` composition. Default `approved_actions` still requires every side effect to be approved; the generated fixed workflow now uses Host-owned low/high/unknown classification so only exact in-scope low-risk steps skip the prompt, high risk requires approval, and unknown is denied | `YES` — doctor fail-fast setup UX, exact thirteen-tool installed-MCP discovery, model-authored brief/save/reopen happy path, stable reviewed Provider contract plus observation-only Runner reacquisition, default/high/low/unknown authorization paths, and wheel resource contract are functional gates | `YES` — [OpenAI and Claude passed](E3_EVIDENCE.md) both bounded fake-MCP E3 cases with reviewed model IDs; Sonnet 5 compatibility is revalidated on the exact repair commit | `YES` — [both reviewed providers passed](E4_EVIDENCE.md) read-only and one approved action with post-action verification; the earlier same-wheel [Desktop Ask and public-web-to-Word](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md) runs also passed through the installed Host, but predate risk-tier code | `PARTIAL` — one OpenAI `gpt-5.6-terra` Notepad answer and one fixed OpenAI/Chrome/Word workflow passed through the installed product; no current-candidate application run or broader application claim exists for risk-tier code | Run only the remaining bounded non-E4 human/native checks; keep current-candidate application evidence, E4, and release separate |
| Planner / Executor | `YES` | `PARTIAL` — `ask` / `plan run` provide bounded observation planning, while `workflow public-web-word` wraps a real provider that chooses reviewed cross-app steps and authors a source-grounded brief under a fixed Host envelope | `YES` — the functional model writes a non-prewritten three-bullet brief and completes bounded primary and reopen-verifier calls; an action proposed during observation-only reacquisition cannot reach the Runner | `YES` — [OpenAI and Claude passed](E3_EVIDENCE.md) the bounded fake-MCP scope, and same-wheel OpenAI `gpt-5.6-terra` [Notepad and fixed Chrome-to-Word plans](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md) passed | `PARTIAL` — one Windows 11 foreground `document_text -> final_response` plan and one fixed model-driven Chrome-to-Word plan passed from one clean wheel | `PARTIAL` — one synthetic Notepad answer and one fixed public-browser-to-disposable-Word workflow are retained | Keep broader side-effect and application expansion separate; close only the remaining bounded non-E4 acceptance gates |
| Campaign | `YES` | `PARTIAL` — one manifest-routed runtime composes fifteen reviewed identity/observation/navigation/verification/approval capabilities into validated scenario specs; A1-A19 are built-in examples, while another spec can be registered without changing Runner or campaign control. Explicit stable-item preparation, one-item provider execution, strict semantic result validation, digest commit, handoff, fresh-run resume, exhausted-manifest completion, terminal handoff, and exact heartbeat retirement share the existing boundaries. Composable `link_url`/`control_name` discovery adapters bound to a campaign kind now derive stable item keys from one bounded foreground observation, and the campaigns they create enter the same start/run/resume path; only BOSS keeps a separate fixed discovery contract with retained on-device evidence, plus three fixed offline semantic CLIs that open one-item/five-call/zero-side-effect batches, accept only strict provider JSON under a fixed no-preference policy, and commit canonical result digests | `YES` — all built-in examples plus a custom composition route through shared control; capability/tool derivation, provider result substitution, claimed-but-unexecuted evidence, registry refusal, exact-plan commit/handoff, fresh transfer/resume, idempotent terminalization, and adapter extraction/bounds/pass-ledger invariants fail closed in tests | `NO` — the new generic provider worker has no retained live-provider result | `PARTIAL` — the earlier fixed [synthetic path](SYNTHETIC_CAMPAIGN_EVIDENCE.md), BOSS [two-pass discovery](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md), the historical [three-item diagnostic](BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md), and the clean [three-item restart sequence](BOSS_ITEM_RESTART_CLEAN_EVIDENCE.md) passed on-device; generic examples and adapters remain offline-only | `PARTIAL` — the clean gate retained twelve identities and three consecutive fresh-run identity-only commits with zero correction, provider calls, tokens, retryable items, or uncertain items; semantic extraction, provider rotation, and the 100-item gate remain open | Retain one on-device BOSS semantic item and one clean A1 semantic campaign, then promote scenarios individually; no universal capability claim before evidence |
| Observation | `YES` | `PARTIAL` — UIA, full primary-display screenshot, bounded region OCR, bounded region image capture, bounded UIA document text, bounded Agent image handling, and a pure BOSS per-item ladder reducer exist; delta observations do not | `YES` — OCR, capture, and document-text limits, schemas, redaction, timeout, and result projection are tested | `NO` | `PARTIAL` — [BOSS OCR evidence](BOSS_OCR_EVIDENCE.md) recovered a missing static tab and matched one job card to UIA; bounded [document text](DOCUMENT_TEXT_EVIDENCE.md) and a synthetic [region capture](CAPTURE_REGION_EVIDENCE.md) passed on-device | `PARTIAL` — one real page and card plus synthetic image/text slices, not application acceptance | Exercise the observation ladder across bounded multi-item and restart cases |
| Operator UI | `YES` | `PARTIAL` — console approval, a focus-taking four-choice Decision Card, non-activating Presence/Progress, CLI-first Task Center and receipts, Pre-run Review, cooperative control, Approval Inbox/local notifications, bounded Host risk-tier prompting, and Windows [accessibility](OPERATOR_ACCESSIBILITY.md), [English/Simplified-Chinese localization](OPERATOR_LOCALIZATION.md), [dark/light/system personalization](OPERATOR_PERSONALIZATION.md), and [native multi-display composition](OPERATOR_MULTI_DISPLAY.md) contracts exist. Safe keyboard traversal, native UIA Text/Document/Button semantics, a presentation-only Progress disclosure, bounded status announcements, system High Contrast/reduced motion, measured-glyph 200%/400% reflow, locale-neutral authority, strict theme fallback/precedence, foreground-monitor rectangle/work-area/DPI selection, and identity-backed modern notification with legacy fallback are implemented and offline verified. One bounded English Windows Narrator Decision Card path, the named one-monitor 200%/400% visual design, one fake-only cooperative takeover/resume timing path, and one Windows 11 notification banner/pending-history/withdrawal path are human-verified. Other CLI localization, general process resume, terminal/mobile notifications, native Inbox UI, custom/learned/per-application personalization, broader risk models, NVDA/JAWS/braille/other-locale AT, and physical-two-monitor review remain absent | `YES` — exact approval/re-observe/defer, generated defaults, low-risk no-prompt/high-risk prompt/unknown denial, progress/presence isolation, Task Center receipts, cooperative control including takeover after low-risk Host authorization, Approval Inbox boundaries, modern notification identity/activation/lifecycle/fallback, accessibility fallback, contrast, focus/order/action, announcements, UIA names, static-details Tab exclusion, on-demand content exposure, Progress Document/Invoke state, measured Presence extents, large-text layout, strict locale and theme resolution, two-locale copy, palette precedence, unknown-text preservation, stable IDs, negative monitor coordinates, offset work areas, mixed DPI, and primary fallback are covered by deterministic tests | `NO` | `YES` — native [Decision Card](DECISION_CARD_WINDOW_EVIDENCE.md), [progress](PROGRESS_LIFECYCLE_EVIDENCE.md), and [presence](PRESENCE_WINDOW_EVIDENCE.md) are retained. The post-risk-tier [PRODUCT-017 automated native rerun](PRODUCT017_AUTOMATED_NATIVE_EVIDENCE.md) and later [human Narrator/UX result](PRODUCT017_HUMAN_NATIVE_EVIDENCE.md) cover ten safe-denial presentation cases, current Progress/Presence human acceptance, one bounded English spoken-order/verbosity/scan-mode path, one fake-only released-input/resume/fresh-observation timing path without focus drift, and one watched Simplified-Chinese modern-notification banner, pending Notification Center item, and Host withdrawal on Windows 11. Physical-two-monitor evidence remains hardware-blocked | `PARTIAL` — the retained application run used five Decision Cards; offline tests now prove the fixed low-risk workflow needs zero prompts, but no new application evidence is claimed | Preserve the named results; keep other Windows versions, notification screen-reader behavior, other AT/locales, physical two-monitor, E4, and release separate |
| Quick Setup and Agent Controls | `YES` | `YES` — `config setup` creates one non-overwriting reviewed default through the strict initializer; setup/init accept one strict pause-chord override; `config settings` projects the same TOML as bounded human/JSON purpose, connection, safety, interface, effective shortcuts, paths, and exact doctor/shortcut-host commands. Credentials remain environment-only; the settings projection has no authority or registration ownership | `YES` — defaults/overrides, reserved/invalid pause rejection, non-overwrite, secret exclusion, strict loading, provider-presence booleans, human/JSON parity, and CLI routing are deterministic tests | `NO` | `NO` — the settings surface opens no provider, MCP, application, or desktop port | `NO` | Preserve the inert settings/liveness boundary |
| ShortcutBroker | `YES` | `YES` — explicit `shortcuts run` checks every currently loaded layout, then atomically registers fixed `Ctrl+Alt+G` presentation and the strict configured `ctrl+alt+<a-z>` cooperative-pause request with Win32 `RegisterHotKey + MOD_NOREPEAT`; G/Q are reserved, ACTIVE follows successful registration/timer startup, conflicts roll back, exit unregisters, and only exact `paused + authority=released` is safe. Q is not registered; global approve/resume do not exist | `YES` — default/configured/no-Q registration, invalid/reserved keys, pre-registration layout conflicts, registration rollback, cleanup, presentation failure, strict config refresh, request-versus-release state, unavailable/drift handling, and CLI/service composition are deterministic tests | `NO` | `PARTIAL` — the [Windows 11 non-input fixed-G/P run](SHORTCUT_BROKER_WINDOWS_EVIDENCE.md) passed real registration/message routing, cross-process conflict, atomic rollback, release/reacquisition, unchanged foreground, and loaded-layout AltGr checks. Later [supervised PRODUCT-021 physical runs](SHORTCUT_BROKER_PHYSICAL_EVIDENCE.md) on loaded `zh-CN`/`en-US` passed configured G foreground, no-run K fail-closed behavior, direct-console Ctrl+C cleanup wording, installed physical-Q E-stop latching, and physical K reaching `paused/authority=released` in an active production Runner control lifecycle before any provider call. Full-MCP post-Q action denial, real-provider/MCP/application pause or resume, and other layouts remain unverified | `NO` | Retain the bounded fake-only and loaded-layout claims; widen only through another exact physical scope |
| Pre-run Review | `YES` | `PARTIAL` — `review public-web-word` and the default workflow start gate compile a human/JSON Scope Sheet from Host-fixed contract fields and exact local paths before any provider, MCP, application, desktop, or fixture startup. Version 2 discloses seven possible side effects, low-risk Host authorization, zero expected high-risk approvals, and unknown denial. Exact `START` or `--acknowledge-scope` enters only the ordinary workflow and grants no action approval, retry, or replay authority; other commands and workflows do not yet have this surface | `YES` — complete fields, contract drift, risk policy, output preconditions, human/JSON parity, cancel/EOF zero-work behavior, exact acknowledgement, one config load, and bound config/request handoff are tested | `NO` | `NO` — no native window is claimed; the bounded CLI Scope Sheet preceded the retained live workflow | `PARTIAL` — the retained [fixed workflow](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md) started only after its Host-fixed review, but that evidence predates review version 2 and risk-tier code | Preserve the fixed contract; broaden it only through another Host-owned workflow scope |
| Cooperative desktop control | `YES` | `PARTIAL` — the installed public-web-word Runner loops expose strict local `control`, `pause`, `takeover`, and `resume` commands plus a Decision Card takeover choice. Pause is acknowledged only at a durable safe boundary, authority release is explicit, resume discards old approval/grounding and requires fresh observation, and uncertain work is never replayed. Other workflows, campaigns, crash recovery, remote control, and `BlockInput` are excluded | `YES` — live-lease and checkpoint binding, atomic lifecycle, CLI human/JSON routing, nested verifier state, stale-call rejection, observation-only resumption, Decision Card takeover, external takeover at `after_authorization`, continuation incompatibility, stable Provider tool contract, and unknown-outcome precedence are tested | `NO` | `PARTIAL` — one current fake-only human timing run used the production control record and OS-backed run lock: `pause_requested -> paused/released` took `65.2 ms`; input occurred only while released; resume required a fresh observation and reached `closed/success` in `1587.5 ms` without new input or focus drift. No provider, MCP, application, or desktop action was exercised | `NO` — no real-provider or application takeover timing is claimed | Preserve the passed bounded timing result; widen only with an exact provider/application scope, while keeping crash recovery, campaigns, remote control, and E4 separate |
| Approval Inbox and local notification | `YES` | `PARTIAL` — Decision Card compilation publishes one strict private expiring identity/digest record, `approval inbox` renders bounded human/JSON inspection without a liveness claim, and an optional Win32 notification carries fixed English or Simplified-Chinese content only. The notifier prefers a per-user identity-backed modern toast with exact tag/group withdrawal and falls back to the legacy Shell signal; whole-toast activation reaches only a local no-authority sink. Inbox and notification have no approval, task-control, provider, MCP, desktop, replay, retry, or dispatch port; console approval, mobile push, Inbox CLI localization, and a native Inbox window are excluded | `YES` — binding/expiry lifecycle, registry action coverage, content exclusion, corrupt isolation, strict bounds, two-locale fixed notification payload, modern registration, inert activation, replacement/withdrawal, legacy fallback, CLI parity, configuration, notification failure isolation, and Decision Card cleanup are tested | `NO` | `PARTIAL` — the earlier [PRODUCT-017 automated native rerun](PRODUCT017_AUTOMATED_NATIVE_EVIDENCE.md) passed legacy Shell acceptance without claiming visibility. The later [human result](PRODUCT017_HUMAN_NATIVE_EVIDENCE.md) retains the initially blocked `ToastEnabled=0` attempt, then records watched transient legacy banners and one repaired Simplified-Chinese modern banner, pending Notification Center record, foreground preservation, and Host withdrawal after the user enabled notifications on Windows 11 | `NO` — no application behavior is claimed | Preserve the one named Windows 11 result; separately test other Windows versions and bounded notification screen-reader behavior |
| Hierarchical control | `YES` — [the closed node set, fail-closed propagation, `H1`-`H8` order, and uncertainty boundary](HIERARCHICAL_TASK_AND_BEHAVIOR_TREES.md) are fixed | `PARTIAL` — H1-H6 add immutable versioned nodes, canonical tree/envelope/template-registry digests, structural/budget limits, pure total parent reduction, lossless linear-plan projection, private `RunLock`-bound exact-CAS snapshots, pure next-leaf compilation, an optional observation/final-response status projection over the existing Runtime Executor, typed content-free observation facts with exact run/epoch/generation/window/time binding and three-valued conditions, and one exact-version reviewed BOSS observation-ladder template. They add no second Runner/MCP dispatch, side effects, retry, replay, recovery, or learning authority | `YES` — topology, limits, digest binding, malformed contracts, linear compatibility, registry/restart/template drift, stale writes, persistence failures, frozen next-leaf traces, exact pre-boundary activation, correlated known results, uncertainty retention, zero-dispatch failures, local-only repair, final completion, typed value validation, raw-content exclusion, deterministic fact/snapshot/template digests, empty/missing/unknown facts, epoch/generation/window/type/time invalidation, unavailable-not-false conditions, exact ladder equivalence, fixed argument and safety-baseline bindings, terminal handoffs, ordering, active-state drift, and unresolved choices fail closed in deterministic tests | `N/A` | `N/A` — H4-H6 evidence uses injected data/fake ports only | `N/A` | Preserve the exact H6 pin and no-fallback boundary; H7 side effects remain separately gated |
| Continual Learning | `YES` | `PARTIAL` — L0 derives redacted outcomes/cost coverage; L1 quarantines only fresh successful-episode boolean/integer facts; L2 adds content-free versioned procedures, frozen replay, held-out gates, reviewed data lifecycle, and rollback; L3 compares one reviewed data-only `ACTIVE` baseline with equivalent reviewed data-only `SHADOW` candidates on exact frozen evidence and emits a visible deterministic offline recommendation. No L1 promotion, memory, runtime loader/selector, provider, Runner, MCP, desktop, persistence, training, or execution port exists | `YES` — L0/L1 gates; L2 schema/replay/lifecycle/rollback gates; and L3 strict policy decode, review/expiry, exact equivalence and suite binding, full verified-success hard gate, zero escape/regression, complete nine-cost vector, visible weights/contributions, order-independent digest, active-tie behavior, strict-lower-cost recommendation, and forged score/recommendation rejection fail closed in deterministic tests | `N/A` | `N/A` — L0-L3 evidence is offline/injected only | `N/A` | Preserve L3 as non-executing advice; H7 side effects are exact next, while L4 runtime routing remains separately gated |

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

1. **Hierarchical control and verified learning:** H1-H6 and L0-L3 now fix the node,
   digest, limit, reduction, linear-plan compatibility, private atomic
   persistence, pure next-leaf, normalized outcome, and explicit cost-coverage
   contracts plus observation-only Runtime Executor composition, typed
   freshness/window-bound facts, the exact pinned BOSS observation template,
   private fresh-fact quarantine lifecycle, content-free procedure fixture,
   replay, held-out gate, lifecycle, rollback, and visible offline shadow-score
   contracts. H7 bounded side-effect leaves are exact next. None of these phases
   adds runtime procedure routing or automatic memory-injection authority.
2. **Installed product verticals:** the installed-first-run configuration,
   public `ask` command, reviewed Planner scope, and semantic document-text
   flow have one exact-candidate Windows/OpenAI/Notepad
   [result](DESKTOP_ASK_EVIDENCE.md). The installed model-driven
   public-browser-to-disposable-Word workflow now also has one exact-candidate
   provider/Chrome/Word [result](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md). Neither
   result broadens beyond its recorded application and authority scope; the
   same-wheel [integration result](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md)
   now composes both paths. The remaining human/native-control gates, E4, and
   release remain separate.
3. **Bounded application evidence:** the repaired `activate_window` path, both
   reviewed providers, the [BOSS home observation](BOSS_EVIDENCE.md), and the
   separate [interested-jobs OCR result](BOSS_OCR_EVIDENCE.md) have retained
   evidence. This remains narrower than BOSS campaign acceptance and does not
   widen action authority.
4. **Observation vertical slice:** [the retained OCR result](BOSS_OCR_EVIDENCE.md)
   recovered a static BOSS tab omitted by UIA, used a fresh OCR target check,
   entered the interested-jobs page, and measured one UIA/OCR card comparison.
   Next reuse that ladder across bounded multi-item and restart cases.
5. **Runtime connection:** the fixed campaign seam now reuses the Agent
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
6. **Wave 1 evidence:** only after the prior gates, execute BOSS, Google Docs,
   and WeChat draft-only cases and retain success, token, retry, recovery, and
   takeover measurements.
7. **Operator and learning layers:** project real checkpoint/campaign facts into
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
