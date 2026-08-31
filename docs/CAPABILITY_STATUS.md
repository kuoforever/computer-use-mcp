# Capability status and evidence dashboard

> **Status: current review dashboard, verified 2026-08-31.** This page is the
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

The complete [Formal Demo v1](FORMAL_DEMO_V1.md) does not exist as an executable
product surface. `GDA-DEMO-007A` implements and offline-verifies the internal
inert v1 `TaskIntent`, `DemoScenarioSpec`, `ApplicationRoleProfile`, and
`GenericScopeSheet` contracts, exact reviewed pins, canonical binding digest,
and fail-closed structural compilation. `GDA-DEMO-007B` adds an internal typed
local disclosure, exact route and conservative warning pins, exact `COMPILE`,
and one opaque issue/consume transition per process-local gate instance.
`GDA-DEMO-007C` adds a provider-neutral, no-network one-attempt coordinator that
resolves an exact reviewed scenario, consumes before entering one injected fake,
strictly loads the untrusted candidate, rejects scenario expansion, and never
retries a terminal gate. It ships no concrete port implementation, provider
factory/client, credential/config/environment read, network path, serialized
loader, command, persistence, or execution port. `GDA-DEMO-007F` converts that
seam to async and adds one exact `openai/global/gpt-5.6-terra` live-capable
Responses adapter plus internal Provider Scope composition. It resolves the
SDK/key only inside the pre-consumed port call, sends no tools, continuation,
or retry, uses strict structured output, and retains Provider output as
untrusted data. The current environment has no credential, so no live request
or Formal-Demo-specific Provider evidence exists. Executable adapters, durable run,
GitHub/PDF/Excel/Word/email-draft composition, Formal Demo Receipt, and formal
evidence remain absent.
`GDA-DEMO-007D` added one independently launchable Review-only Windows Console
through disclosure and inert permit issue. `GDA-DEMO-007E` adds the explicit
Host-owned no-key local compiler, selects the inert Outlook Desktop test-draft
design profile, consumes one process-local permit, compiles the complete
reviewed built-in Scope with zero provider calls and retries, and projects
Review ready. Free-form text binds identity only. The Console reads no Agent
config, credential or provider environment, makes no provider request, exposes
no start/dispatch transition, and keeps native `Start` disabled. In the
Operator UI row, "console" includes only this bounded Offline Scope Review surface and the existing
terminal/CLI approval surface, not a complete executing Agent Console. The
implemented `public-web-word` Pre-run Review remains a
different narrow fixed workflow; it is not the generic Demo product entry.

| Capability line | Designed | Implemented | Offline verified | Provider verified | Desktop verified | Application verified | Next gate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Formal Demo v1 | `YES` — the selected role-based product story and safety boundary are specified in [Formal Demo v1](FORMAL_DEMO_V1.md) | `PARTIAL` — internal inert v1 intent/scenario/profile/Scope contracts, exact registry pins, fail-closed compilation, a typed local disclosure/exact-`COMPILE` permit gate, an async provider-neutral one-attempt coordinator, the exact OpenAI Responses live-capable intent adapter and internal Provider Scope composition, an explicit Host-owned fixed local compiler, five selected inert role pins, and an independent no-key Offline Scope Review Windows Console/launcher exist. The Provider adapter is internal and not Console-connected; the Console reaches only its local reviewed Scope and stops with native `Start` disabled. No executable application adapter, durable composition, or Receipt exists | `PARTIAL` — the `GDA-DEMO-007A`/`007B`/`007C` gates cover contract binding, disclosure, permit, async consume-before-await, and injected-fake one-attempt behavior. `007F` adds exact OpenAI route/account-review/task/profile/scenario/draft binding, lazy client construction, strict tool-free structured-output wire shape, one-call/replay/concurrency, refusal/truncation/error/oversize handling, candidate Host validation, Provider Scope binding, explicit prior-external-work facts, and an opt-in live gate that skips without its exact credential/account inputs. The `007D`/`007E` gates cover exact local text, fixed local mapping, complete local Scope rendering, zero-provider/zero-retry budgets, native disabled/inert `Start`, and base-wheel startup without provider extras. This is deterministic offline/native-component evidence only; it is not process-wide or crash-safe exactly-once and proves no Provider, Desktop E4, Application, or human-accessibility result | `NO` | `NO` | `NO` | Run the exact opt-in `openai/global/gpt-5.6-terra` one-call gate only after current account/data-controls review and credential injection. Then separately activate Console live-mode/`START` or the first application vertical; no existing fixed-workflow, application-coverage, or Universal-showcase evidence transfers |
| MCP Server | `YES` | `YES` — thirteen-core-tool Windows stdio server, including bounded OCR, region capture, UIA document text, scroll, and drag; user-configured Playwright CDP adds one read-only rendered-browser observation | `YES` — optional-tool negotiation, bounded/redacted rendered output, unchanged core digest, OS-default input, and UIA opt-in are deterministic tests | `N/A` | `PARTIAL` — [the five-case Windows activation regression](E4_EVIDENCE.md), bounded [document-text result](DOCUMENT_TEXT_EVIDENCE.md), exact-candidate [Desktop Ask result](DESKTOP_ASK_EVIDENCE.md), and fixed [public-web-to-Word result](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) passed on-device; optional Playwright observation, OS-default ref dispatch, scroll, and drag have no retained live evidence | `PARTIAL` — bounded BOSS [home](BOSS_EVIDENCE.md) and [interested-jobs OCR](BOSS_OCR_EVIDENCE.md) observations plus real UIA [document text](DOCUMENT_TEXT_EVIDENCE.md), one Notepad [Desktop Ask](DESKTOP_ASK_EVIDENCE.md), and one fixed Chrome-to-Word [workflow](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) passed; none exercised the new optional browser observer | Preserve these exact scopes; retain one bounded CDP/OS-input result before any browser or application promotion |
| Agent Host | `YES` | `PARTIAL` — installed setup/doctor and ordinary/Planner/final routing cover eight exact cloud profiles; Kimi now has isolated `global` and `cn` gateways, while a ninth loopback-only `local_openai` profile reaches text-only Planner/final and fails closed on ordinary native tool calling pending E3. Cloud region and local endpoint, credential contract, protocol, capabilities, continuation v8 identity, and image/tool surfaces remain separate. Locally approved actions and fixed `workflow public-web-word` still use the sole Runner/MCP authority and exclude the local profile | `YES` — cloud catalog routing plus literal-loopback URL validation, optional local-key semantics, exact `cn` + `kimi-k2.6` one-shot thinking disablement, strict Messages reasoning-before-text normalization, exact Qwen Beijing/model Planner-fence normalization after the original byte gate, exact GLM China/model short Planner wire before unchanged Host compilation, Planner/final prompt mode, pre-client ordinary denial, local endpoint/port recovery binding, regional credential isolation, strict v7/v6 reads, image withdrawal, doctor/setup, and existing Runner authorization paths are deterministic gates | `PARTIAL` — earlier OpenAI/Claude scopes plus exact model-pinned Kimi `kimi-k2.6`, MiniMax `MiniMax-M2.7`, and GLM `glm-5.2` `cn`, DeepSeek `deepseek-v4-pro` `global`, and Doubao `doubao-seed-2-0-lite-260215` plus Qwen `qwen3.7-plus` `cn-beijing` matrices passed the retained [E3 evidence](E3_EVIDENCE.md); other added cloud routes and every local endpoint remain live-unverified | `PARTIAL` — only the two earlier reviewed providers have [retained E4 evidence](E4_EVIDENCE.md), predating the added profiles and current routing | `PARTIAL` — one OpenAI Notepad answer and one fixed OpenAI/Chrome/Word workflow are retained; no added provider has application evidence | Run another exact cloud provider/model/region E3 only after its account exists; local server/model E3 is separately deferred, and no sibling route, desktop, application, or release inherits Kimi, MiniMax, DeepSeek, Doubao, Qwen, or GLM evidence |
| Planner / Executor | `YES` | `PARTIAL` — `ask` / `plan run` route all nine exact profiles through one tool-free Planner/final factory; `workflow public-web-word` remains limited to the eight cloud profiles with reviewed ordinary tool calling. Native JSON Schema, JSON object, and exact-schema prompt modes remain explicit; only `cn` + `kimi-k2.6` one-shot calls disable thinking, Messages-compatible one-shot calls strictly validate and discard reasoning before one text block, only `qwen` + `cn-beijing` + `qwen3.7-plus` Planner output may shed one exact JSON fence, and only `glm` + `cn` + `glm-5.2` uses the reviewed short Planner argument wire before unchanged Host compilation | `YES` — cloud routes plus loopback local Planner/final construction, provider-specific fields, tool-free one-call behavior, byte/token limits, strict schema compilation, exact Kimi route/model-scoped one-shot thinking control, strict Messages reasoning normalization/discard, exact Qwen route/model fence scope and raw-response byte gate, exact GLM route/model short-wire scope and wrong/old/dual/object/sibling fail-closed forms, text-only local image failure, pre-client ordinary denial, and no cross-region/endpoint fallback are covered with fake clients | `PARTIAL` — [OpenAI, Claude, Kimi China, MiniMax China, DeepSeek global, Doubao China, Qwen Beijing, and GLM China passed](E3_EVIDENCE.md) their bounded fake-MCP scopes; Kimi, Doubao, and Qwen each cover one synthetic-image final cycle, while MiniMax, DeepSeek, and GLM prove exact text-only image-tool withdrawal. All six added-provider matrices cover ordinary continuation, structured Planner/final, and timeout. DeepSeek's live ordinary cell proves two-turn continuation, not that `reasoning_content` appeared or was replayed; the Doubao and Qwen 16x16 fixtures do not prove arbitrary image inputs, and GLM's small workload does not prove maximum context/output. Same-wheel OpenAI `gpt-5.6-terra` [Notepad and fixed Chrome-to-Word plans](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md) passed; other added cloud routes and local server/model candidates remain live-unverified | `PARTIAL` — one Windows 11 foreground `document_text -> final_response` plan and one fixed model-driven Chrome-to-Word plan passed from one clean wheel, both under earlier OpenAI scope | `PARTIAL` — one synthetic Notepad answer and one fixed public-browser-to-disposable-Word workflow are retained | Preserve the exact Kimi, MiniMax, and GLM `cn`, DeepSeek `global`, and Doubao plus Qwen `cn-beijing` model-scoped results; run another route only with matching authorization and never inherit evidence across gateways or models |
| Campaign | `YES` | `PARTIAL` — one manifest-routed runtime composes seventeen reviewed declarative capabilities—eight observation/verification, six navigation/recovery, one draft, one external-commit, and one critical-commit—into validated scenario specs; A1-A19 are built-in examples, while another spec can be registered without changing Runner or campaign control. Explicit stable-item preparation, one-item provider execution, strict semantic result validation, digest commit, handoff, fresh-run resume, exhausted-manifest completion, terminal handoff, and exact heartbeat retirement share the existing boundaries. Composable `link_url`/`control_name` discovery adapters bound to a campaign kind now derive stable item keys from one bounded foreground observation, and the campaigns they create enter the same start/run/resume path; only BOSS keeps a separate fixed discovery contract with retained on-device evidence, plus three fixed offline semantic CLIs that open one-item/five-call/zero-side-effect batches, accept only strict provider JSON under a fixed no-preference policy, and commit canonical result digests | `YES` — all built-in examples plus a custom composition route through shared control; capability/tool derivation, provider result substitution, claimed-but-unexecuted evidence, registry refusal, exact-plan commit/handoff, fresh transfer/resume, idempotent terminalization, and adapter extraction/bounds/pass-ledger invariants fail closed in tests | `NO` — the generic provider worker has no retained live-provider result | `PARTIAL` — the earlier fixed [synthetic path](SYNTHETIC_CAMPAIGN_EVIDENCE.md), BOSS [two-pass discovery](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md), the historical [three-item diagnostic](BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md), and the clean [three-item restart sequence](BOSS_ITEM_RESTART_CLEAN_EVIDENCE.md) passed on-device; generic examples and adapters remain offline-only | `PARTIAL` — the clean gate retained twelve identities and three consecutive fresh-run identity-only commits with zero correction, provider calls, tokens, retryable items, or uncertain items; semantic extraction, provider rotation, and the 100-item gate remain open | Retain one on-device BOSS semantic item and one clean A1 semantic campaign, then promote scenarios individually; no universal capability claim before evidence |
| Observation | `YES` | `PARTIAL` — UIA, full primary-display screenshot, bounded region OCR/image capture, bounded UIA document text, optional rendered-browser ARIA/text, bounded Agent image handling, and a pure BOSS per-item ladder reducer exist; delta observations do not | `YES` — OCR/capture/document-text limits plus browser endpoint, page/frame/depth/text/result bounds, URL stripping, no-action surface, and one-failure withdrawal are tested | `NO` — no provider has exercised the optional browser tool | `PARTIAL` — prior OCR, document text, and region capture evidence did not use Playwright CDP | `PARTIAL` — one real page/card plus synthetic image/text slices; no rendered-browser application acceptance | Retain one bounded JavaScript-rendered CDP observation and one OS-input action result, with challenges handed to the operator |
| Operator UI | `YES` | `PARTIAL` — console approval, a focus-taking four-choice Decision Card, non-activating Presence/Progress, CLI-first Task Center and receipts, Pre-run Review, cooperative control, Approval Inbox/local notifications, bounded Host risk-tier prompting, and Windows [accessibility](OPERATOR_ACCESSIBILITY.md), [English/Simplified-Chinese localization](OPERATOR_LOCALIZATION.md), [dark/light/system personalization](OPERATOR_PERSONALIZATION.md), and [native multi-display composition](OPERATOR_MULTI_DISPLAY.md) contracts exist. Safe keyboard traversal, native UIA Text/Document/Button semantics, a presentation-only Progress disclosure, bounded status announcements, system High Contrast/reduced motion, measured-glyph 200%/400% reflow, locale-neutral authority, strict theme fallback/precedence, foreground-monitor rectangle/work-area/DPI selection, and identity-backed modern notification with legacy fallback are implemented and offline verified. One bounded English Windows Narrator Decision Card path, the named one-monitor 200%/400% visual design, one fake-only cooperative takeover/resume timing path, and one Windows 11 notification banner/pending-history/withdrawal path are human-verified. Other CLI localization, general process resume, terminal/mobile notifications, native Inbox UI, custom/learned/per-application personalization, broader risk models, NVDA/JAWS/braille/other-locale AT, and physical-two-monitor review remain absent | `YES` — exact approval/re-observe/defer, generated defaults, low-risk no-prompt/high-risk prompt/unknown denial, progress/presence isolation, Task Center receipts, cooperative control including takeover after low-risk Host authorization, Approval Inbox boundaries, modern notification identity/activation/lifecycle/fallback, accessibility fallback, contrast, focus/order/action, announcements, UIA names, static-details Tab exclusion, on-demand content exposure, Progress Document/Invoke state, measured Presence extents, large-text layout, strict locale and theme resolution, two-locale copy, palette precedence, unknown-text preservation, stable IDs, negative monitor coordinates, offset work areas, mixed DPI, and primary fallback are covered by deterministic tests | `NO` | `YES` — native [Decision Card](DECISION_CARD_WINDOW_EVIDENCE.md), [progress](PROGRESS_LIFECYCLE_EVIDENCE.md), and [presence](PRESENCE_WINDOW_EVIDENCE.md) are retained. The post-risk-tier [PRODUCT-017 automated native rerun](PRODUCT017_AUTOMATED_NATIVE_EVIDENCE.md) and later [human Narrator/UX result](PRODUCT017_HUMAN_NATIVE_EVIDENCE.md) cover ten safe-denial presentation cases, current Progress/Presence human acceptance, one bounded English spoken-order/verbosity/scan-mode path, one fake-only released-input/resume/fresh-observation timing path without focus drift, and one watched Simplified-Chinese modern-notification banner, pending Notification Center item, and Host withdrawal on Windows 11. Physical-two-monitor evidence remains hardware-blocked | `PARTIAL` — the retained application run used five Decision Cards; offline tests now prove the fixed low-risk workflow needs zero prompts, but no new application evidence is claimed | Preserve the named results; keep other Windows versions, notification screen-reader behavior, other AT/locales, physical two-monitor, E4, and release separate |
| Quick Setup and Agent Controls | `YES` | `YES` — `config setup` / `config init` accept eight cloud names plus `local_openai`, typed cloud regions, Qwen workspace IDs, and one strict literal-loopback local URL with explicit model; `config settings` v2 projects required/present credential booleans without reading values. Fixed cloud endpoints and non-loopback local routes are rejected; the settings projection has no authority or registration ownership | `YES` — cloud defaults, local explicit-model requirement, loopback URL rejection matrix, optional-key truthfulness, regional overrides, Qwen construction/migration, action-profile denial, non-overwrite, secret exclusion, strict loading, human/JSON parity, and CLI routing are deterministic tests | `NO` — setup and settings make no provider request or local endpoint probe | `NO` — the settings surface opens no provider, MCP, application, or desktop port | `NO` | Preserve the inert settings/liveness boundary; live readiness starts only at an explicitly authorized provider/model/region or local endpoint gate |
| ShortcutBroker | `YES` | `YES` — explicit `shortcuts run` checks every currently loaded layout, then atomically registers fixed `Ctrl+Alt+G` presentation and the strict configured `ctrl+alt+<a-z>` cooperative-pause request with Win32 `RegisterHotKey + MOD_NOREPEAT`; G/Q are reserved, ACTIVE follows successful registration/timer startup, conflicts roll back, exit unregisters, and only exact `paused + authority=released` is safe. Q is not registered; global approve/resume do not exist | `YES` — default/configured/no-Q registration, invalid/reserved keys, pre-registration layout conflicts, registration rollback, cleanup, presentation failure, strict config refresh, request-versus-release state, unavailable/drift handling, and CLI/service composition are deterministic tests | `NO` | `PARTIAL` — the [Windows 11 non-input fixed-G/P run](SHORTCUT_BROKER_WINDOWS_EVIDENCE.md) passed real registration/message routing, cross-process conflict, atomic rollback, release/reacquisition, unchanged foreground, and loaded-layout AltGr checks. Later [supervised PRODUCT-021 physical runs](SHORTCUT_BROKER_PHYSICAL_EVIDENCE.md) on loaded `zh-CN`/`en-US` passed configured G foreground, no-run K fail-closed behavior, direct-console Ctrl+C cleanup wording, installed physical-Q E-stop latching, and physical K reaching `paused/authority=released` in an active production Runner control lifecycle before any provider call. Full-MCP post-Q action denial, real-provider/MCP/application pause or resume, and other layouts remain unverified | `NO` | Retain the bounded fake-only and loaded-layout claims; widen only through another exact physical scope |
| Pre-run Review | `YES` | `PARTIAL` — `review public-web-word` and the default workflow start gate compile a human/JSON Scope Sheet from Host-fixed contract fields and exact local paths before any provider, MCP, application, desktop, or fixture startup. Version 2 discloses seven possible side effects, low-risk Host authorization, zero expected high-risk approvals, and unknown denial. Exact `START` or `--acknowledge-scope` enters only the ordinary workflow and grants no action approval, retry, or replay authority; other commands and workflows do not yet have this surface | `YES` — complete fields, contract drift, risk policy, output preconditions, human/JSON parity, cancel/EOF zero-work behavior, exact acknowledgement, one config load, and bound config/request handoff are tested | `NO` | `NO` — no native window is claimed; the bounded CLI Scope Sheet preceded the retained live workflow | `PARTIAL` — the retained [fixed workflow](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md) started only after its Host-fixed review, but that evidence predates review version 2 and risk-tier code | Preserve the fixed contract; broaden it only through another Host-owned workflow scope |
| Cooperative desktop control | `YES` | `PARTIAL` — the installed public-web-word Runner loops expose strict local `control`, `pause`, `takeover`, and `resume` commands plus a Decision Card takeover choice. Pause is acknowledged only at a durable safe boundary, authority release is explicit, resume discards old approval/grounding and requires fresh observation, and uncertain work is never replayed. Other workflows, campaigns, crash recovery, remote control, and `BlockInput` are excluded | `YES` — live-lease and checkpoint binding, atomic lifecycle, CLI human/JSON routing, nested verifier state, stale-call rejection, observation-only resumption, Decision Card takeover, external takeover at `after_authorization`, continuation incompatibility, stable Provider tool contract, and unknown-outcome precedence are tested | `NO` | `PARTIAL` — one current fake-only human timing run used the production control record and OS-backed run lock: `pause_requested -> paused/released` took `65.2 ms`; input occurred only while released; resume required a fresh observation and reached `closed/success` in `1587.5 ms` without new input or focus drift. No provider, MCP, application, or desktop action was exercised | `NO` — no real-provider or application takeover timing is claimed | Preserve the passed bounded timing result; widen only with an exact provider/application scope, while keeping crash recovery, campaigns, remote control, and E4 separate |
| Approval Inbox and local notification | `YES` | `PARTIAL` — Decision Card compilation publishes one strict private expiring identity/digest record, `approval inbox` renders bounded human/JSON inspection without a liveness claim, and an optional Win32 notification carries fixed English or Simplified-Chinese content only. The notifier prefers a per-user identity-backed modern toast with exact tag/group withdrawal and falls back to the legacy Shell signal; whole-toast activation reaches only a local no-authority sink. Inbox and notification have no approval, task-control, provider, MCP, desktop, replay, retry, or dispatch port; console approval, mobile push, Inbox CLI localization, and a native Inbox window are excluded | `YES` — binding/expiry lifecycle, registry action coverage, content exclusion, corrupt isolation, strict bounds, two-locale fixed notification payload, modern registration, inert activation, replacement/withdrawal, legacy fallback, CLI parity, configuration, notification failure isolation, and Decision Card cleanup are tested | `NO` | `PARTIAL` — the earlier [PRODUCT-017 automated native rerun](PRODUCT017_AUTOMATED_NATIVE_EVIDENCE.md) passed legacy Shell acceptance without claiming visibility. The later [human result](PRODUCT017_HUMAN_NATIVE_EVIDENCE.md) retains the initially blocked `ToastEnabled=0` attempt, then records watched transient legacy banners and one repaired Simplified-Chinese modern banner, pending Notification Center record, foreground preservation, and Host withdrawal after the user enabled notifications on Windows 11 | `NO` — no application behavior is claimed | Preserve the one named Windows 11 result; separately test other Windows versions and bounded notification screen-reader behavior |
| Hierarchical control | `YES` — [the closed node set, fail-closed propagation, `H1`-`H8` order, and uncertainty boundary](HIERARCHICAL_TASK_AND_BEHAVIOR_TREES.md) are fixed | `PARTIAL` — H1-H7 add immutable nodes, exact digests/CAS, pure next-leaf compilation, typed fresh facts, one exact BOSS observation template, and one separately reviewed observation/action/verification-observation/final sequence. H8A adds contract-v2 bounded H5 batches, H8B adds contract-v3 all-of DAG/local joins, and H8C adds contract-v4 Host-order fixed choice with only fresh pre-boundary-false or exact verified zero-side-effect read-only-miss fallback. H7 still owns the only widened runtime path; H8A-H8C add no external port, and H4/public Planner/Executor remain observation-only | `YES` — prior H1-H8B gates plus H8C true/false/unavailable/multiple-true ordering, actual worker overlap, immutable selection, exact eligible fallback, denial/authority/grounding/policy/budget/cancel/error/missing-verification/unknown/side-effect stop matrix, context drift, CAS/exception zero-write, v1-v4 digest/decode, tamper, and restart semantics pass deterministically | `N/A` | `PARTIAL` — [H7 isolated-application evidence](H7_BOUNDED_SIDE_EFFECT_EVIDENCE.md) uses production stores/compiler/Runner/ledger with injected desktop and approval ports. [H8A](H8A_PARALLEL_CONDITION_EVIDENCE.md), [H8B](H8B_DEPENDENCY_JOIN_EVIDENCE.md), and [H8C evidence](H8C_SAFE_CHOICE_EVIDENCE.md) are port-free source/offline evidence only; no real MCP, Windows desktop, provider, external application, or external parallelism is claimed | `N/A` | Preserve the merged H1-H8 boundary and exact evidence limits; L5 requires separate consent |
| Continual Learning | `YES` | `PARTIAL` — L0 derives redacted outcomes/cost coverage; L1 quarantines fresh successful-episode boolean/integer facts; L2 supplies content-free reviewed procedures/replay/rollback; L3 emits one deterministic offline recommendation; L4 can now select that exact equivalent reviewed SHADOW only through an action-argument-bound LOW context, persistent prefix-safe canary, one pending decision, and first-regression rollback to ACTIVE. It binds a separately compiled H7 plan but carries no arguments, approval, dispatch, retry, replay, or promotion authority. General procedure compilation, L1/memory promotion, broader runtime selection, provider/real MCP/desktop/application evidence, online training, E4, and release remain absent | `YES` — L0/L1 gates; L2 lifecycle/replay/rollback; L3 equivalence/suite/hard-gate/reward validation; and L4 policy bounds, exact context and action-risk digests, atomic OS-lock/CAS persistence, crash-pending stop, prefix/absolute canary caps, LOW/non-LOW choice, evidence/context drift, first hard-gate regression rollback, forged outcome/tamper/write-failure rejection, H7 substitution rejection, and one isolated production-Runner composition are deterministic tests | `N/A` | `N/A` — L0-L3 are offline/injected; L4 adds one injected isolated Runner composition only, not real provider/MCP/desktop/application evidence | `N/A` | Preserve the bounded L4 route and exact limitations; L5 remains separately consented and inactive |

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

Separately, the retained [provider E3 record](E3_EVIDENCE.md) supports the
historical OpenAI/Claude portions and exact Kimi `kimi-k2.6` plus MiniMax
`MiniMax-M2.7` China, DeepSeek `deepseek-v4-pro` global, and Doubao
`doubao-seed-2-0-lite-260215` plus Qwen `qwen3.7-plus` Beijing and GLM
`glm-5.2` China portions of the `PARTIAL` cells above. It remains
model/route-scoped and records the historical
Sonnet 5 compatibility failure; ordinary reasoning preservation and one-shot
reasoning normalization each have exact-commit retained reruns. DeepSeek
required no production adapter repair and proves ordinary two-turn
continuation without claiming live `reasoning_content`. Doubao also required
no production adapter repair; its exact-marker 16x16 fake image proves only
one bounded synthetic-image cycle. Qwen required an exact
provider/region/model-scoped Planner-only JSON-fence normalization; the raw
byte gate and unchanged Host compiler remain authoritative, and its 16x16
fixture proves only one bounded synthetic-image cycle. GLM required an exact
provider/region/model Planner-wire field while retaining strict Host tool and
argument compilation; its text-only cell proves schema withdrawal rather than
image input. These records do not
alter the offline snapshot or fill another provider route, application, or
release gate. The separate
[E4 record](E4_EVIDENCE.md) is likewise VM-, model-, and repair-tree-scoped.
The [Desktop Ask record](DESKTOP_ASK_EVIDENCE.md) adds one exact-candidate
OpenAI/Windows/Notepad read-only application result. It does not fill another
provider, application, side-effect, multi-monitor, or release gate.
The [Public Web to Word record](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) adds one
fixed OpenAI/Windows/Chrome/Word side-effect workflow with human approvals,
durable save/reopen verification, real-Word visual QA, and exact fixture
cleanup. It does not establish arbitrary sites, applications, providers,
unattended operation, or release readiness.

## Retained capability and evidence gates

This section orders capability-specific evidence dependencies only;
[Project status](../PROJECT_STATUS.md) alone owns the active item and exact next
action.

1. **Hierarchical control and verified learning:** H1-H8 and L0-L4 now fix the node,
   digest, limit, reduction, linear-plan compatibility, private atomic
   persistence, pure next-leaf, normalized outcome, and explicit cost-coverage
   contracts plus observation-only Runtime Executor composition, typed
   freshness/window-bound facts, the exact pinned BOSS observation template,
   private fresh-fact quarantine lifecycle, content-free procedure fixture,
   replay, held-out gate, lifecycle, rollback, visible offline shadow-score,
   separately gated bounded side-effect sequence, persistent LOW-only canary
   route binding, bounded local parallel H5 condition batches, all-of graphs,
   local joins, deterministic one-ready-leaf selection, and safe Host-order
   choice/read-only verified-miss fallback. H8 is closed at its bounded
   offline scope; L5 still requires separate consent and remains inactive. None of these phases
   adds automatic memory injection, procedure promotion, or model training.
2. **Installed product verticals:** the installed-first-run configuration,
   public `ask` command, reviewed Planner scope, and semantic document-text
   flow have one exact-candidate Windows/OpenAI/Notepad
   [result](DESKTOP_ASK_EVIDENCE.md). The installed model-driven
   public-browser-to-disposable-Word workflow now also has one exact-candidate
   provider/Chrome/Word [result](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md). Neither
   result broadens beyond its recorded application and authority scope; the
   same-wheel [integration result](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md)
   now composes both paths. Other assistive technologies and locales, physical
   two-monitor evidence, E4, and release remain separate.
3. **Bounded application evidence:** the repaired `activate_window` path, both
   reviewed providers, the [BOSS home observation](BOSS_EVIDENCE.md), and the
   separate [interested-jobs OCR result](BOSS_OCR_EVIDENCE.md) have retained
   evidence. This remains narrower than BOSS campaign acceptance and does not
   widen action authority.
4. **Observation vertical slice:** [the retained OCR result](BOSS_OCR_EVIDENCE.md)
   recovered a static BOSS tab omitted by UIA, used a fresh OCR target check,
   entered the interested-jobs page, and measured one UIA/OCR card comparison.
   Retain one on-device UIA/document-text semantic item; review the OCR fallback
   baseline separately.
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
   tool is connected. The separate manifest-routed general worker is implemented
   and offline verified, but has no retained provider/application result. Fixed
   BOSS worker boundaries now open
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
6. **Application Coverage Set A evidence:** the BOSS semantic and 100-item
   gates above apply only to the BOSS case. Activate BOSS, Google Docs, and
   WeChat draft-only independently; each must pass its own source, identity,
   recovery, and application gates before retaining success, token, retry, and
   takeover measurements. These cases are not Formal Demo v1 and do not set
   product priority.
7. **Operator and learning layers:** project real checkpoint/campaign facts into
   the operator UI. Retain L0-L4 only at their bounded offline or
   injected-runtime scopes; L5 remains inactive pending separate consent, and
   none of these layers grants automatic promotion or model-training authority.

## Taxonomy map

The repository uses several independent numbering systems. They are not a
single sequence:

| Prefix | Owner | Meaning |
| --- | --- | --- |
| `P` | [Roadmap](EXECUTION_PLAN.md) | Product priority or historical milestone |
| `Phase` | [Agent implementation plan](AGENT_IMPLEMENTATION_PLAN.md) | Agent Host delivery decomposition |
| `E` | [Evaluation](EVALUATION.md) | Evidence level, from offline contracts through isolated release regression |
| `A` / `Coverage Set` | [Application matrix](APPLICATION_EVALUATION_MATRIX.md) | Independent application case and staged evidence group |
| `GDA-DEMO-007*` | [Formal Demo v1](FORMAL_DEMO_V1.md) | Proposed staged product-demo delivery; not active by naming alone |
| `Act` | [Universal GUI final showcase](UNIVERSAL_GUI_DEMO.md) | Future complete-product presentation chapter |
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
