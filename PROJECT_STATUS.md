# Project status

> **Mode: Experimental Windows Agent MVP productization is explicitly active.**
> `GDA-PRODUCT-005` is the single active item, scoped to the user's explicit
> default-on UI/UX requirement before its separate exact-candidate release
> gates. `GDA-DEMO-006` is paused at checkpoint `d74201f` in draft PR #231 with
> its exact live-acceptance resume point retained below. The Full Cycle Runtime
> baseline remains frozen at
> `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`, and Full Cycle consumer work
> remains paused.
> Updated: 2026-08-07.
> This file is the single operational entry point for the next coding session.
> It does not replace capability evidence in `docs/CAPABILITY_STATUS.md`.

Every closed item keeps its commit, PR, merge hash, and gate result in the
[Closure backlog](#closure-backlog) below. The pre-closure gap analysis for each
`GDA-CORE-*` slice, the completed bounded-task records, and the per-item
decision chronology are retained in
[core Runtime slice history](docs/archive/CORE_RUNTIME_SLICE_HISTORY.md). Two
HUD defect narratives moved to [postmortems](docs/postmortems/).

## Active product objective

Ship an **Experimental Windows Agent MVP** for a single supervised foreground
desktop and primary display. The first releasable product boundary must let a
new Windows user:

1. install a wheel without a source checkout;
2. generate and validate a read-only configuration without manually discovering
   the MCP executable or state paths;
3. ask a natural-language question about the foreground desktop and receive one
   direct answer through the existing Planner, Runner, MCP, and final-response
   boundaries;
4. retain one current-candidate real read-only application result and one
   model-driven public-browser-to-disposable-document workflow; and
5. install a versioned GitHub release artifact with a recorded digest, exact
   limitations, and matching release evidence.

The MVP does not claim background execution, universal GUI coverage, a complete
campaign product, Google Docs or WeChat acceptance, multi-monitor or non-Windows
support, hierarchical control, continual learning, or Multi-Agent operation.
Those are post-MVP programs, not blockers for the first honest release.

## Productization delivery map

| Product batch | State | Product outcome | Acceptance |
| --- | --- | --- | --- |
| `GDA-PRODUCT-001` | Complete; merged | Installed-first-run Desktop Ask: `config init`, public `ask`, semantic `document_text` planning, EN/ZH quick start, and clean-wheel entry smoke | Commit `2b7198e`, merged through PR #266 as `3c7aa48`; generated config immediately validates, `ask` and `plan run` share one Runner path, Planner -> `document_text` -> final answer is functionally verified, all four GitHub checks passed, and both feature-branch copies were removed |
| `GDA-PRODUCT-002` | Complete; merged | Readiness and error UX: `config doctor`, actionable provider/setup failures, truthful Driver `scroll`/`drag` capability metadata, and a stronger clean-wheel first-run contract | Commit `f0e78cd`, merged through PR #267 as `d94d5f9` after all four GitHub checks passed; both branch copies were removed |
| `GDA-PRODUCT-003` | Complete; merged | One exact-candidate real Windows/provider document-aware Desktop Ask result, with functional hardening only for defects actually observed | Commit `8bf139f`, wheel `54ec7077...a7a3`, and run `2699db750c314b178e1f2fb400e233bf` passed from fresh state; PR #268 merged all four green checks as `5eb9182`, and both branch copies were removed |
| `GDA-PRODUCT-004` | Complete; merged | Installed `workflow public-web-word` product path with real-model step choice, packaged disposable DOCX template, installed sibling-MCP discovery, durable reopen/render verification, and exact fixture lifecycle; selectively port only required work from draft PR #231 | Clean candidate `74544d8`, wheel `b9eef298...e9ab22`, and run `public-web-word-e713ae032a3eb8ebf9923cc4eeeca02d` passed with a 518-character three-bullet brief, exact save/OOXML/reopen verification, real-Word visual QA, exact window cleanup, bounded output, and [retained evidence](docs/PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md); PR #269 merged as `0275f25` after all four checks passed and both branch copies were removed |
| `GDA-PRODUCT-005` | Active; UI/UX defaults | Exact-candidate integration and release: current-wheel E3/E4, every generated installed UI/UX boolean default-on, clean preflight, version/changelog/package metadata, GitHub release wheel and SHA-256 | Both generated product profiles explicitly write `CUMCP_ACTION_FEEDBACK=1` plus `[operator].presence_enabled`, `progress_enabled`, `reduced_motion`, `high_contrast`, and `decision_cards_enabled` as `true`; existing passive/read-only/approval/no-authority boundaries remain fixed. Release review, clean install, version check, and rollback/uninstall evidence remain separate gates |

During every live desktop test, the user may take the mouse, keyboard, or
foreground focus. Treat unexpected input/focus drift as possible operator
interference first: mark that attempt interrupted or invalid, re-establish a
fresh observation, and rerun. Diagnose a code defect only when trace, window,
and timing evidence exclude user intervention. This is evidence-interpretation
discipline, not an additional product feature or `GDA-PRODUCT-004` acceptance
item.

After `GDA-PRODUCT-005`, campaign `status`/single-step `advance`, bounded BOSS
semantic batches, broader Wave 1 applications, and richer operator surfaces are
prioritized by product evidence. They are not silently pulled into this MVP.

## Preserved Full Cycle integration objective

Freeze `guarded-desktop-agent` as the reliable Windows execution environment
for the Multimodal LLM Full Cycle project. Finish only the smallest stable
integration surface needed for:

1. runtime capability discovery;
2. safe reliability/evaluation data export;
3. an external, explicitly consented rich-training capture adapter; and
4. a reproducible frozen baseline.

The model factory, multimodal dataset pipeline, post-training, serving,
Agentic RL, and Multi-Agent work live outside this repository.


## Current baseline

| Fact | Current state |
| --- | --- |
| Product | Experimental Windows-only foreground desktop MCP runtime and Agent Host |
| Public tools | 13 reviewed tools |
| Driver contract | `1.0.0` |
| Agent contract | `0.1.0` |
| Trace/checkpoint | Redacted `trace_version=1`, `checkpoint_version=1` |
| Providers | OpenAI and Claude bounded paths |
| Safety | Sole Runner/MCP dispatch, grounding, policy, approval, budgets, audit, mandatory re-observation |
| Recovery | Conservative recovery; uncertain side effects are never replayed |
| Offline baseline | Run the current suite; CI publishes the live total. Last full gate: 2026-08-07, all green — pytest, Ruff, mypy over 127 source files, docs consistency, and `git diff --check` |
| Frozen commit | `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`, reachable from local `main` |

The test count is a dated working snapshot, not a permanent capability claim.
Run the current suite before relying on it.

## Closed temporary scope exception

The user explicitly approved `GDA-DEMO-001` on 2026-07-30. The bounded item
closed after retained run `cross-app-demo-20260730-034539` passed. The
temporary exception did not erase, silently supersede, or strand
`GDA-FC-002`. The user subsequently requested the bounded `GDA-DEMO-002`
realism enhancement and `GDA-DEMO-003` Operator HUD polish. The latter is
complete locally after separate issue-by-issue sessions. It did not displace
the Full Cycle resume point, and `GDA-FC-004` subsequently closed the Runtime
freeze. On 2026-08-03 the user explicitly reopened only `GDA-DEMO-004` for
operator-selectable action pacing and more visible mouse/keyboard activity.
The user then reopened `GDA-DEMO-006` for a model-driven bounded Demo. Its
offline implementation is preserved at checkpoint `d74201f` in draft PR #231,
but repository consolidation pauses live acceptance while core Runtime work is
active.

Continue to exclude:

- hierarchical task or behavior-tree runtime support;
- broad BOSS/application automation beyond the bounded Demo;
- a universal-GUI capability claim;
- additional desktop tools or platform drivers;
- Multi-Agent coordination;
- automatic continual learning;
- operator-UI work beyond the closed Demo surfaces and the paused
  `GDA-DEMO-006` live-acceptance checkpoint;
- broad refactors unrelated to the bridge.

Existing planned documents remain valid design records, but they are not active
delivery work.


## Closure backlog

| ID | Status | Deliverable | Completion evidence |
| --- | --- | --- | --- |
| `GDA-PRODUCT-001` | Complete; merged | Installed-first-run, document-aware Desktop Ask vertical slice | Commit `2b7198e`, merged through PR #266 as `3c7aa48`; `config init` creates one non-overwriting, immediately valid read-only profile with automatic sibling MCP discovery and no stored credential; `ask` shares the bounded Planner/Runner path with `plan run`, prints direct text by default, and adds semantic `document_text`. Complete gate: `1840 passed, 8 skipped`, Ruff, mypy over 122 source files, docs consistency, diff check, isolated Python 3.13 wheel install/init/validate/dry-run smoke, shared text/JSON routing tests, independent functional review, and all four GitHub checks on 2026-08-06; no live provider, desktop, application, or release claim is made |
| `GDA-PRODUCT-002` | Complete; merged | Runtime doctor, actionable setup errors, truthful capability metadata, and installed-wheel first-run contract | Commit `f0e78cd`, merged through PR #267 as `d94d5f9`; fixed JSON doctor checks config, SDK, documented key, executable, cwd, and exact names/schemas; six OpenAI/Claude provider/planner/final constructors share one-line actionable setup errors; Driver metadata exposes all 15 implemented primitives. Complete gate: `1853 passed, 8 skipped`, Ruff, mypy over 124 source files, docs consistency, diff check, clean Python 3.13 wheel installation with both provider extras, two real sibling-MCP `ready=true` / 13-tool handshakes, independent functional review, and all four GitHub checks on 2026-08-06; both feature-branch copies were removed and no provider request, MCP tool call, desktop content read/action, application, or release evidence is claimed |
| `GDA-PRODUCT-003` | Complete; merged | Current-candidate real document-aware Desktop Ask evidence | Attempt 1 retained the scope-paraphrase failure. Commit `8bf139f` repaired only that observed contract; its clean Python 3.13 wheel passed `config init` / `doctor` / `validate` and one installed OpenAI `gpt-5.6-terra` Windows/Notepad `ask --json` run with correct fixture-only facts, one successful semantic observation, one final response, zero side effects/retries/failures, and [retained bounded evidence](docs/DESKTOP_ASK_EVIDENCE.md). Complete gate: `1857 passed, 8 skipped`, Ruff, mypy over 124 source files, docs consistency, diff check, independent functional review, all four GitHub checks, and PR #268 merged as `5eb9182`; both branch copies were removed |
| `GDA-PRODUCT-004` | Complete; merged | Model-driven public-browser-to-disposable-Word product workflow | Candidate `74544d8` and clean wheel `b9eef298...e9ab22` passed one OpenAI/Chrome/Word run with fresh source observations, non-prewritten three-bullet brief, durable save/OOXML/reopen verification, real-Word visual QA, exact cleanup, and [retained bounded evidence](docs/PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md); PR #269 merged as `0275f25` with all four checks green and both branch copies removed |
| `GDA-PRODUCT-005` | Active; UI/UX defaults | Exact-candidate integration and first GitHub release | Generated desktop-ask and public-web-word profiles default action feedback, presence, progress, reduced motion, high contrast, and Decision Cards on without changing authority; current-wheel E3/E4, clean preflight, release review, tagged wheel/digest, clean install and rollback evidence remain |
| `GDA-FC-000` | Complete | Closure scope, integration contract, project status, Codex/Claude entrypoints | This documentation change |
| `GDA-FC-001` | Complete | Safe Full Cycle manifest and redacted run-export CLI | Exact schema/version tests, CLI tests, fail-closed record/output tests |
| `GDA-FC-002` | Complete | Consumer fixture in `reliable-agent-model-lifecycle` | That repository's `FC-BRIDGE-001`: `fixtures/bridge_v1` with one valid manifest, one valid run export, and eight invalid fixtures, pinned to producer commit `8ace897`. Re-verified on 2026-08-01 (below) |
| `GDA-FC-003` | Deferred to Full Cycle review | Explicit-consent rich episode capture contract owned by Full Cycle | Excluded from this freeze; remains disabled by default pending the separate `FC-BRIDGE-003` security/privacy review |
| `GDA-FC-004` | Complete locally | Freeze validation and handoff | Clean release preflight passed at branch-reachable commit `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`; the matching Full Cycle `FC-BRIDGE-004` record pins the same commit |
| `GDA-DEMO-001` | Complete | Real Chrome-to-Word interview Demo through existing Runtime authority | Retained run `cross-app-demo-20260730-034539`; [evidence](docs/CROSS_APP_DEMO_EVIDENCE.md) |
| `GDA-DEMO-002` | Complete; restart hardening offline-verified | Improve Demo realism without broadening authority | Retained run `cross-app-demo-20260730-042826`; deterministic fresh-start tests; [evidence](docs/PUBLIC_WEB_WORD_DEMO_EVIDENCE.md) |
| `GDA-DEMO-003` | Complete locally | Operator HUD visual hierarchy, step status, safe lock interaction, and live reliability | [Demo evidence](docs/OPERATOR_HUD_DEMO_EVIDENCE_2026-08-03.md); [100%/125% DPI evidence](docs/OPERATOR_HUD_DPI_EVIDENCE_2026-08-03.md); [physical Alt+Tab evidence](docs/OPERATOR_HUD_KEYBOARD_EVIDENCE_2026-08-03.md) |
| `GDA-DEMO-004` | Complete locally | Operator-selectable Demo action pacing plus visible mouse and content-free keyboard feedback | [Native probe and retained Demo evidence](docs/DEMO_ACTION_PRESENTATION_EVIDENCE_2026-08-03.md) |
| `GDA-DEMO-005` | Proposed; not active | Cooperative desktop authority handoff, explicit pause/re-observe/resume, and complete Decision Card consequences | Await a separate control-lifecycle contract; must never use `BlockInput` or make physical input unavailable |
| `GDA-DEMO-006` | Paused; implemented offline; live agentic acceptance pending | Model-driven bounded public-web-to-disposable-Word Demo | Checkpoint `d74201f` in draft PR #231; exact fresh live-run resume point is retained below |
| `GDA-CORE-001` | Complete; merged | Make a ref without a supported accessibility action fail with `NOT_INVOKABLE`, never a coordinate click | Commit `1727a26`, merged through PR #230; `tests/test_core.py` proves zero coordinate calls; complete gate: `1578 passed, 8 skipped`, Ruff, mypy, docs consistency, and diff check passed on 2026-08-04 |
| `GDA-CORE-002` | Complete; merged | Revalidate e-stop and foreground authority at the final MCP-to-driver action boundary | Commit `aa7d5a7`, merged through PR #230 as `d52ffb2`; six-action e-stop and five-action foreground-drift zero-dispatch tests plus confirmation/activation boundary tests; complete gate: `1592 passed, 8 skipped`, Ruff, mypy, docs consistency, and diff check passed on 2026-08-04 |
| `GDA-CORE-003` | Complete; merged | Preserve post-dispatch MCP cancellation certainty through the Runner | Commit `647a9ef`, merged through PR #232 as `5d19157`; result-aware cancellation persists the validated/privacy-protected unknown result and completed WAL boundary before re-propagation; task cancellation, generation invalidation, zero replay, persistence-failure chaining, and shared-caller terminal-state guards are regression tested; complete gate: `1597 passed, 8 skipped`, Ruff, mypy, docs consistency, and diff check passed on 2026-08-04 |
| `GDA-CORE-004` | Complete; merged | Enforce the actual per-turn advertised tool set at the Runner authority boundary | Commit `ba907bf`, merged through PR #233 as `5c9c379`; whole-turn Host validation uses the final caller/privacy/safety-baseline-filtered set; mixed observation/action turns, downstream baseline filtering, continuation ordering, valid restricted execution, prompt injection, and unknown tools are regression tested with zero leaked authority; complete gate: `1600 passed, 8 skipped`, Ruff, mypy, docs consistency, and diff check passed on 2026-08-04 |
| `GDA-CORE-005` | Complete; merged | Revalidate required MCP safety baselines before read-only recovery dispatch | Commit `969a56f`, merged through PR #234 as `ea2e063`; the executor checks the current reviewed requirement against the connected MCP generation before intent; missing OCR evidence has fixed `RECOVERY_SAFETY_BASELINE_UNSATISFIED`, byte-identical checkpoint/continuation files, zero phase transition, and zero MCP dispatch, while the baseline-satisfied path retains atomic intent/completion; complete gate: `1601 passed, 8 skipped`, Ruff, mypy, docs consistency, and diff check passed on 2026-08-04 |
| `GDA-CORE-006` | Complete; merged | Make returned-turn argument validation whole-turn atomic | Commit `12d1211`, merged through PR #235 as `33b0d73`; shared preflight runs after identity/advertised-name checks and before every downstream authority boundary; malformed observation and approved-action sibling tests prove fixed `SCHEMA_MISMATCH`, provider intent only, user-task-only trace, zero model/tool/side-effect budget, zero approval, and zero MCP dispatch; complete gate: `1603 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-04 |
| `GDA-CORE-007` | Complete; merged | Preserve the original Host-advertised tool scope across recovery | Commit `a53d6c1`, merged through PR #236 as `e726052`; strict continuation v6 binds the exact final Host-advertised names, recovery narrows them to currently evidenced observations, and the same ordered tuple governs every provider and returned-turn boundary. Old/corrupt evidence, unauthorized mandatory observation synthesis, mismatched completed ledgers, and out-of-scope calls fail closed; complete gate: `1619 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, independent authority review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-04 |
| `GDA-CORE-008` | Complete; merged | Prevent non-native or failed MCP actions from claiming a human input tick | Commit `0756861`, merged through PR #237 as `ab4bb3a`; structured results and explicit route provenance gate agent-tick attribution on known-successful native input. Semantic ref actions, activation, invalid/no-op calls, and all failures leave the tick unclaimed; five native-success routes, self-input suppression, concurrent-human blocking, audit compatibility, and typed-text redaction are regression tested; complete gate: `1631 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, independent safety review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-04 |
| `GDA-CORE-009` | Complete; merged | Reserve a mandatory post-action verification lane before side-effect authority | Commit `b771e5f`, merged through PR #238 as `5f9c9de`; before approval, the Runner preflights model, input-token, projected-context, and tool-call capacity in fixed priority. Four insufficiency paths retain an exact eight-event known-not-dispatched ledger and prior verified observation with zero approval/action continuation/side-effect/MCP authority; exact `4/4/9/3` completion and `3/3/9/3` verification-only capacity prevent over-reservation; complete gate: `1637 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, two independent authority reviews, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-04 |
| `GDA-CORE-010` | Complete; merged | Revalidate live MCP generation and required safety baselines after approval wait | Commit `8b49c36`, merged through PR #239 as `0b58044`; after a valid audited `ALLOW`, ref/window/screenshot generation drift and typed-text baseline loss now fail before side-effect budget, action continuation, or MCP. Each path retains an exact nine-event audited-ALLOW ledger, prior verified observation, and `ready` recovery state with a rejected/not-dispatched policy result and zero action calls; unchanged authority completes normally; complete gate: `1642 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, independent authority review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-04 |
| `GDA-CORE-011` | Complete; merged | Keep continuation-incompatible sensitive actions out of the advertised tool set | Commit `7be485f`, merged through PR #240 as `2c6b9bb`; when continuation is enabled, `type` is excluded from the final provider tuple and persisted scope. Attempted typed text fails whole-turn before budget or authority, while continuation-disabled baseline-satisfied typing is unchanged; complete gate: `1643 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, independent boundary review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-04 |
| `GDA-CORE-012` | Complete; merged | Make every side-effect-bearing provider turn exactly one call | Commit `d7ca143`, merged through PR #241 as `059734d`; action/action, observation/action, and action/observation returns fail before budget or authority, while pure observations and single-action verification are unchanged. The reviewed E2 fixture/manifest pins zero dispatch; complete gate: `1647 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, independent boundary review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-04 |
| `GDA-CORE-013` | Complete; merged | Revalidate human-input authority at the final MCP-to-driver boundary | Commit `eee77a6`, merged through PR #242 as `48ef716`; stable readiness plus final double-sampling rejects missing, changed, or newer human input before all six safe-local driver boundaries. The dangerous-confirmation exception is exact, call-local, non-persisted, and never attributed as agent input; activation/full-control exceptions remain bounded. Complete gate: `1660 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, independent safety review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-04 |
| `GDA-CORE-014` | Complete; merged | Preserve known-not-dispatched certainty when pre-dispatch tool continuation writes fail | Commit `fbd6758`, merged through PR #243 as `c451526`; `prepare_tool` and `dispatch_tool` failures append a correlated `REJECTED/not_dispatched/CONTINUATION_WRITE_FAILED` result before raising `RunFailure` with the latest state. Observation/action x prepared/intent tests freeze exact ledgers, budgets, checkpoint sequences, cleanup, and zero target MCP calls; complete gate: `1664 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, independent boundary review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-05 |
| `GDA-CORE-015` | Complete; merged | Bind stale-ref relocation to the ref's original observation scope and keep ref maps bijective | Commit `21650a7`, merged through PR #244 as `16ef9d6`; per-ref set-once scope, complete-Node relocation, and bijective cached-node/native/reverse rebinding preserve the original scope and fail reverse conflicts before candidate action. Complete gate: `1669 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, and independent ref-boundary review passed on 2026-08-05 |
| `GDA-CORE-016` | Complete; merged | Forbid stale relocation from dynamic `foreground` and `all` scope tokens | Commit `64bca1e`, merged through PR #245 as `6ea1b1f`; dynamic-scope stale refs return fixed `STALE_ELEMENT` with zero additional relocation query, candidate action, coordinate action, or ref-map mutation. Explicit numeric window-id success and collision controls preserve the CORE-015 path and Driver contract `1.0.0`. Complete gate: `1671 passed, 8 skipped`, Ruff, mypy over 120 source files, docs consistency, diff check, independent code/test/contract reviews, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-05 |
| `GDA-CORE-017` | Complete; merged | Close the driver-pacing native-authority and partial-dispatch certainty window | Commit `9d0b5d8`, merged through PR #247 as `212081a`; accepted ADR 009 and server-owned call scopes revalidate authority before every driver-controlled native mutation. Pre-mutation loss is rejected/not-dispatched; post-attempt loss is unknown/dispatched with bounded cleanup and zero replay. Literal Unicode input, pointer/mouse/key/UIA/activation paths, exact continuation certainty, pacing, feedback, confirmation, activation, and full-control exceptions are regression tested. Complete gate: `1719 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, three independent reviews, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-05; no real-desktop claim is made |
| `GDA-CORE-018` | Complete; merged | Invalidate prior observation and grounding when a side effect yields to `HUMAN_ACTIVE` | Commit `f613056`, merged through PR #249 as `1adce11`; the exact side-effect `REJECTED / NOT_DISPATCHED / HUMAN_ACTIVE` tuple now clears the verified observation, requires re-observation, and invalidates Host grounding before continuation completion. Old refs cannot revive through an unrelated observation, fresh snapshot grounding restores action authority, unknown/dispatched certainty remains terminal, and recovery plans only a new observation with zero action replay. Complete gate: `1725 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, independent code/certainty/scope reviews, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-05; no real-desktop claim is made |
| `GDA-CORE-019` | Complete; merged | Invalidate prior observation and grounding when a side-effect action is denied by the live gate | Commit `bf0cbec`, merged through PR #251 as `dfc5f9e`; the exact side-effect `REJECTED / NOT_DISPATCHED / DENIED_BY_GATE` tuple now clears the verified observation, requires re-observation, and invalidates Host grounding before continuation completion. Old refs and screenshot coordinates cannot revive through unrelated observations, fresh snapshot grounding restores action authority, observation-shaped gate denial and every other certainty tuple remain unchanged, and recovery plans only a new observation with zero action replay. Complete gate: `1733 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, independent code/certainty/contract reviews, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-05; no real-desktop claim is made |
| `GDA-CORE-020` | Complete; merged | Preserve terminal unknown certainty when a native mutation reports failure after a dispatch attempt | Commit `257c42d`, merged through PR #253 as `b53bbe2`; the server-owned call scope now promotes every failed Windows action or ordinary exception after one or more native attempts to fixed redacted `NATIVE_OUTCOME_UNKNOWN`. The Agent maps it to terminal `UNKNOWN_OUTCOME / DISPATCHED`, invalidates the MCP generation, and preserves exact continuation/no-replay certainty. Full action-family, actual Windows UIA/SendInput stitch, zero-attempt, bounded-unwind, redaction, lifecycle, Runner, continuation, and recovery regressions pass. Complete gate: `1763 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, independent code/test/contract review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-05; no real-desktop claim is made |
| `GDA-CORE-021` | Complete; merged | Bind continuation recovery actions to their actual budget dimensions before external dispatch | Commit `0e83c6e`, merged through PR #255 as `5d605e7`; full topology validation makes `next_step` non-authoritative, the final reconstructed action owns its model/input or tool budget, executor and locked persistence recheck before authority, and prepared singleton observations reuse their charged call. Digest-valid mismatches, exhausted dimensions, forged verification calls, and uncertain multi-observation boundaries have zero external work; valid recovery and side-effect no-replay remain intact. Complete gate: `1780 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, independent code/certainty/contract review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-05; no provider, real-desktop, application, or release claim is made |
| `GDA-CORE-022` | Complete; merged | Preserve mandatory verification and terminal certainty across completed-provider recovery finalization | Commit `dc59252`, merged through PR #257 as `5c0ab09`; complete-ledger folding, exact checkpoint binding, monotonic locked persistence, and a non-`ready` trace-finalization guard preserve verification, Host-only stricter state, terminal unknown, and synthetic stop. OpenAI/Anthropic crash windows, result variants, non-serial histories, abandoned calls, counter/status swaps, mandatory success/failure, Host-only unknown, byte-stable refusal, valid finalization, current-tail blocking, and pure-observation controls pass. Complete gate: `1813 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, two independent final reviews, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-06; both feature-branch copies were removed and no provider, real-desktop, application, or release claim is made |
| `GDA-CORE-023` | Complete; merged | Bind `activate_window` to the owner identity observed for its target window | Commit `9edc585`, merged through PR #259 as `1c5b2a0`; the MCP atomically binds unique valid ids to exact direct-owner `(pid, name)` evidence from successful `list_windows`, captures one generation before waits, rechecks owner before each mutation and after Driver return, and never lets internal enumeration or an old in-flight call bind/follow/delete a replacement. Stable, missing, invalid, duplicate, disappeared, PID-only/name-only drift, pre-first/intermediate/final-attempt drift, probe failure, full-control, foreground-exception, failed/empty/internal list, fresh rebind, concurrent rebind, guard-order, audit, and fixed-certainty cases pass. Complete gate: `1832 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, two independent final reviews, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-06; both feature-branch copies were removed, Driver Contract `1.0.0` and every public/schema/Full Cycle boundary remain unchanged, and no real-desktop claim is made |
| `GDA-CORE-024` | Complete; merged | Normalize configured comma-list entries before matching | Commit `9e59361`, merged through PR #261 as `b9a7fbe`; `_env_list` trims each non-empty item exactly once while preserving blank defaults and all other parsing/matching semantics. Shared compact/spaced/default parsing plus existing Gate controls and three real-`build_server` spaced-title paths prove screenshot, capture-region, and OCR blackout without a redundant safety matrix. Complete gate: `1833 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, independent review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-06; both feature-branch copies were removed and no public/runtime boundary changed |
| `GDA-CORE-025` | Complete; merged | Make Windows `find()` search the full bounded traversal before applying its result cap | Commit `d7ac3b8`, merged through PR #262 as `0b43442`; shared bounded traversal filters matches before visual de-duplication, the 200-result cap, exact matching-only truncation, and native-cache insertion. One 201-control deterministic Windows fake proves the ordinary snapshot remains `200 + truncated=1`, the unique position-201 target is found with cache only for that match, 201 matching controls remain capped, and cap-omitted named duplicates count once. Complete gate: `1834 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, independent final reviews, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-06; both feature-branch copies were removed and every public boundary remains unchanged |
| `GDA-CORE-026` | Complete; merged | Report partial Windows document-range clipping instead of claiming complete text | Commit `47532dd`, merged through PR #263 as `95bd16a`; one real-Windows-Driver fake distinguishes exact 20,000-character and 20,001-character ranges with a bounded 40,002-UTF-16-unit probe. Overflow retains only the first 20,000 Python characters and its digest but returns `complete=false`, `truncated=true`, `omitted_blocks=0`; exact-cap and legitimate-empty controls remain complete, while UIA exception/non-string reads are explicitly incomplete. Complete gate: `1835 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, independent final reviews, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-06; both feature-branch copies were removed and no public boundary changed |
| `GDA-CORE-027` | Complete; merged | Give Chromium `find()` the existing lazy-UIA warmup used by `ui_snapshot()` | Commit `25e0049`, merged through PR #264 as `ee4aebf`; one private Session helper gives both final reads the existing optional disposable `get_tree` plus bounded delay. A first-empty/second-ready functional regression proves warmup uses `get_tree`, the final result still comes from `find("Ready")`, and only that result is ingested; zero-delay retains one read. Complete gate: `1836 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, independent functional review, and the GitHub Python 3.11-3.13 plus wheel matrix passed on 2026-08-06; both feature-branch copies were removed and no public boundary changed |
| `GDA-CORE-028` | Complete; merged | Relocate a stale explicit-window ref through the full matching traversal instead of the ordinary snapshot cap | Commit `db5d537`, merged through PR #265 as `9a0ae0e`; `_relocate()` queries `driver.find()` in the original explicit scope with empty-name role fallback, `control_types=(role,)`, and the existing browser warmup before retaining exact role/name, nearest bbox, collision, rebind, and one semantic retry. One real WindowsDriver/Session test places an unnamed Button after 200 name-matching Edit decoys and proves old/fresh native ids are each invoked once. Complete gate: `1837 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency, diff check, independent functional review, and all four GitHub checks passed on 2026-08-06; both feature-branch copies were removed |
| `GDA-CORE-029` | Preserved; grouped into `GDA-PRODUCT-002` | Advertise implemented Windows `scroll` and `drag` features through Driver capability discovery | The existing deterministic probe and focused metadata scope remain valid, but this correction will ship with product readiness/doctor work rather than as a standalone micro-PR. No safety matrix, tool/schema change, or action implementation change is planned |

`GDA-CORE-009` is merged through PR #238 as `5f9c9de`.
`GDA-CORE-010` is merged through PR #239 as `0b58044`.
`GDA-CORE-011` is merged through PR #240 as `2c6b9bb`.
`GDA-CORE-012` is merged through PR #241 as `059734d`.
`GDA-CORE-013` is merged through PR #242 as `48ef716`.
`GDA-CORE-014` is merged through PR #243 as `c451526`.
`GDA-CORE-015` is merged through PR #244 as `16ef9d6`.
`GDA-CORE-016` is merged through PR #245 as `6ea1b1f`.
`GDA-CORE-017` is merged through PR #247 as `212081a`.
`GDA-CORE-018` is merged through PR #249 as `1adce11`.
`GDA-CORE-019` is merged through PR #251 as `dfc5f9e`.
`GDA-CORE-020` is merged through PR #253 as `b53bbe2`.
`GDA-CORE-021` is merged through PR #255 as `5d605e7`. `GDA-CORE-022` is
merged through PR #257 as `5c0ab09`. `GDA-CORE-023` is merged through PR #259
as `1c5b2a0`.
`GDA-CORE-024` is merged through PR #261 as `b9a7fbe`. `GDA-CORE-025` is
merged through PR #262 as `0b43442`. `GDA-CORE-026` is merged through PR #263
as `95bd16a`. `GDA-CORE-027` is merged through PR #264 as `ee4aebf`.
`GDA-CORE-028` is merged through PR #265 as `9a0ae0e`. `GDA-PRODUCT-001` is
merged through PR #266 as `3c7aa48`. `GDA-PRODUCT-002` is merged through PR
#267 as `d94d5f9`, including closure of `GDA-CORE-029`. `GDA-PRODUCT-003` is
complete locally and awaiting publication; `GDA-PRODUCT-004` is the exact
post-merge next item.
`GDA-DEMO-006` is paused at its exact resume point, and no `GDA-HUD-*` item is
active. The historical Full Cycle freeze remains the handoff baseline; it no
longer freezes the separately reopened core Runtime scope above.


## Paused resume point: `GDA-DEMO-006`

Checkpoint `d74201f` in draft PR #231 preserves the offline implementation.
Keep `CrossAppDemoProvider` as the deterministic E1 regression baseline. The
live path uses the real public Microsoft Support co-authoring page and a
disposable Word document; the configured provider chooses observations and
actions and authors a two-to-four-bullet source brief. Host constraints do not
substitute fixed prose. Nine 2026-08-03 live diagnostics failed and are not
evidence.

The exact resume action is one fresh `gpt-5.6-terra` run in default
`agentic_actions` mode using fresh public-page and Word observations. It must
author a non-prewritten brief, durably verify the complete saved brief, and
resolve exact fixture cleanup without reusing prior observations, approvals, or
generated content. Per-action cards remain skipped while MCP `safe_local`,
human-input yielding, E-stop, audit, grounding, budgets, mandatory
  post-observation, and unknown-outcome no-replay remain enforced. This Demo item
  must not displace `GDA-CORE-029` after the user explicitly resumes it.

The user proposed `GDA-DEMO-005` after observing a known pre-dispatch gate
rejection. If explicitly resumed, implement a cooperative lease rather than a
physical input lock: an operator interrupt requests pause at the next safe
boundary, releases authority, and requires explicit resume plus mandatory
re-observation. An interrupt during a possibly dispatched side effect remains
unknown outcome and cannot auto-continue. Wire the already-defined human
takeover option and ensure approve, re-observe, defer, deny, and takeover each
produce their documented distinct state transition. Keep this out of the
single-purpose `GDA-DEMO-004` presentation change.

Full Cycle remains paused after merged PRs #10 and #11. Three uncommitted BF16
merge-probe files in `C:\Users\Alienware\reliable-agent-model-lifecycle` are
preserved as work in progress; do not continue, delete, or publish them until
the user explicitly resumes Full Cycle. Lane B remains `FC-BRIDGE-003` pending
its separate consent, security, and privacy review.

The final Demo-closure gate passed on 2026-08-03: `1566 passed, 8 skipped`,
Ruff passed, mypy reported no issues in 118 source files, documentation
consistency reported 13 reviewed tools, and `git diff --check` passed.


## Definition of closed (Full Cycle handoff)

This scopes the Full Cycle handoff only; it does not describe the active
productization program above. The Full Cycle handoff is closed locally
because:

- `GDA-FC-001` and `GDA-FC-002` are complete;
- the rich-capture boundary is either accepted with a separate reviewed design
  or explicitly deferred;
- the complete offline validation gate passes;
- the root README, documentation index, this file, and `HANDOFF.md` agree;
- no planned feature is described as implemented;
- the Full Cycle repository records the pinned runtime version and consumer
  contract;
- a fresh Codex or Claude Code session can complete the next task using only
  repository files.


## Session protocol

At the beginning of every session:

1. Read `AGENTS.md` or `CLAUDE.md`.
2. Read this file.
3. Read only the owner documents linked by the active task.
4. Run `git status --short --branch`.
5. Confirm the active backlog item and avoid unrelated work.

At the end of every session:

1. Run the task's validation commands.
2. Update exactly one Closure backlog row and the active item named in the
   header.
3. Record new durable implementation facts in `HANDOFF.md` only when needed.
4. Do not promote capability evidence without the required retained run.
5. Leave a concise list of modified files, tests, limitations, and next task.

## Validation gate

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe scripts\check_docs_consistency.py
git diff --check
```

On-device smoke scripts are not part of the routine closure gate and must not
be run on an active or sensitive desktop without an explicit evidence plan.


## Decisions

Durable policy and active-scope decisions only. The per-item
chronology is in
[core Runtime slice history](docs/archive/CORE_RUNTIME_SLICE_HISTORY.md).

| Date | Decision |
| --- | --- |
| 2026-07-28 | The Runtime is a Full Cycle dependency, not the model-training repository. |
| 2026-07-28 | Existing redacted traces may feed reliability/evaluation work but are insufficient for multimodal model training. |
| 2026-07-28 | Rich episodes require an explicit-consent external capture adapter and a separate privacy/security review. |
| 2026-08-01 | Durable evidence must name a commit reachable from a branch. Pre-merge candidate `45bee82` was replaced by its squash merge `8ace897`; the earlier preflight result is retained, its unreachable identity is not. |
| 2026-08-02 | Lane B is explicitly deferred from the Runtime freeze to the Full Cycle project's separate `FC-BRIDGE-003` consent, security, and privacy review; it remains disabled by default. |
| 2026-08-03 | The user explicitly reopened core Runtime development without reopening Demo or Full Cycle consumer work. Core changes must preserve the frozen Full Cycle baseline, completed Lane A state, disabled/deferred Lane B boundary, and external `FC-BRIDGE-003` resume point. |
| 2026-08-05 | For this repository, completed and validated slices are automatically committed, pushed, opened as PRs, merged only when checks, review state, and conflicts are clear, and then cleaned up locally and remotely. Failing, blocked, conflicting, requested-changes, or unresolved work never merges. |
| 2026-08-05 | `HUMAN_ACTIVE` is fail-closed evidence that current human-idle authority is unavailable or the desktop may have changed since grounding; it is not proof that a particular physical input occurred after the last Host observation. Current contracts and the CORE-018 status narrative were corrected without promoting evidence. |
| 2026-08-06 | The user changed the governing objective from micro-audit CORE throughput to productization: prioritize user-visible functions, keep new safety-test work out of the current program, publish coherent product PRs, merge only when clear, and continue automatically. |
| 2026-08-06 | The first release boundary is an Experimental Windows Agent MVP, not a universal-GUI claim. Five product batches cover Desktop Ask first-run, readiness/error UX, one current-candidate real document-aware result, a model-driven public-browser-to-disposable-Word workflow, and exact-candidate GitHub release evidence. |
| 2026-08-06 | During any live desktop test, the user may take mouse, keyboard, or focus. Unexpected drift must first be classified as possible operator interference and the attempt rerun from a fresh observation; it becomes a code defect only when trace, window, and timing evidence exclude user intervention. This corrects an over-broad interpretation: it is test-evidence discipline, not a new `GDA-PRODUCT-004` acceptance item. |
| 2026-08-06 | The user kept action feedback and progress display opt-in for `GDA-PRODUCT-004` and selected `GDA-PRODUCT-005` as the point where the installed product profile defaults `CUMCP_ACTION_FEEDBACK=1` and `[operator].progress_enabled=true`; their existing passive, read-only, no-authority boundaries remain fixed. |
| 2026-08-07 | The user explicitly resumed the UI/UX-default portion of `GDA-PRODUCT-005` and broadened the requirement from action feedback plus progress to every existing boolean UI/UX preference. Newly generated installed desktop-ask and public-web-word profiles must set `CUMCP_ACTION_FEEDBACK=1` and all five `[operator]` booleans to `true`; legacy/manual absent-key behavior and every safety/authority boundary remain unchanged. Exact-candidate integration and release evidence are still separate gates and are not implied by this default change. |
