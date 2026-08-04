# Project status

> **Mode: core Runtime development is explicitly reopened by the user.
> `GDA-CORE-001` and `GDA-CORE-002` are merged through PR #230;
> `GDA-CORE-003` is merged through PR #232; `GDA-CORE-004` is merged through
> PR #233; `GDA-CORE-005` is merged through PR #234; `GDA-CORE-006` is merged
> through PR #235; `GDA-CORE-007` is complete locally; and `GDA-CORE-008` is
> the exact next item.
> `GDA-DEMO-006` is paused at checkpoint
> `d74201f` in draft PR #231 with its exact live-acceptance resume point retained
> below; the user reaffirmed that core Runtime development stays ahead of all
> Demo work. The Full Cycle Runtime baseline remains frozen at
> `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`, and Full Cycle consumer work
> remains paused.**
> Updated: 2026-08-04.
> This file is the single operational entry point for the next coding session.
> It does not replace capability evidence in `docs/CAPABILITY_STATUS.md`.

## Objective

Freeze `guarded-desktop-agent` as the reliable Windows execution environment
for the Multimodal LLM Full Cycle project. Finish only the smallest stable
integration surface needed for:

1. runtime capability discovery;
2. safe reliability/evaluation data export;
3. an external, explicitly consented rich-training capture adapter; and
4. a reproducible frozen baseline.

The model factory, multimodal dataset pipeline, post-training, serving,
Agentic RL, and Multi-Agent work live outside this repository.

## Reopened core Runtime scope

On 2026-08-03 the user explicitly reopened development of the project itself,
not the Demo and not the external Full Cycle consumer. The first audit is
restricted to real gaps in the existing Runner/MCP/authority/recovery boundary.
Demo, Operator HUD, Universal GUI, hierarchical control, Multi-Agent, training,
and BF16 work remain excluded.

`GDA-CORE-001` addressed the smallest highest-value gap found by that audit.
The accepted ADR and current design forbid a ref click from silently becoming a
coordinate click. `Session._press()` had still clicked the cached bounding-box
center when a control exposed neither `Invoke` nor `SelectionItem`; it now
returns fixed `NOT_INVOKABLE` with zero coordinate driver calls. Explicit
`click(x=..., y=...)` remains unchanged.

The audit also found that initial e-stop/foreground authority evidence could age
while the server waited for stable human-idle evidence or native dangerous-click
confirmation. `GDA-CORE-002` closed that gap with a final non-waiting authority
recheck before native dispatch. Both audit slices are merged through PR #230.

`GDA-CORE-003` closed the next Runner/MCP recovery gap. A result-carrying
post-dispatch cancellation now passes through normal result validation and
privacy protection, persists the correlated unknown result and completed
continuation boundary, terminalizes the safe checkpoint as `UNKNOWN_OUTCOME`,
then re-propagates task cancellation. Shared Runner callers cannot replace that
certainty with `CANCELLED`; a failed continuation completion write remains a
chained error while the redacted checkpoint stays unknown. The bridge generation
remains invalidated and no call is replayed.

`GDA-CORE-004` closed the next provider/Host authority gap. The Runner now
derives an immutable name set from the exact tools remaining after caller,
privacy, and current MCP safety-baseline filtering, then atomically rejects a
returned turn containing any other name before Host privacy validation, ledger
or budget consumption, continuation completion, policy, approval, or MCP
dispatch. A valid prefix cannot execute first, and the frozen E2 prompt-injection
and unknown-tool cases now pin the earlier zero-authority failure.

`GDA-CORE-005` closed the read-only recovery baseline gap. Immediately before
any recovered observation intent can be persisted, the executor now resolves
the current reviewed tool specification and requires its safety baselines from
the connected MCP generation. Missing evidence has one fixed failure before
operation identity construction, persistence, authorization, or dispatch; the
checkpoint and continuation remain byte-identical.

`GDA-CORE-006` closed the remaining same-turn prefix-authority gap in the
ordinary Runner. After identity and advertised-name validation, the Host now
preflights every returned call's reviewed schema and exact canonical arguments
before privacy processing, model-turn or tool budgets, continuation completion,
policy, approval, or MCP. One malformed sibling rejects the whole turn with
fixed `SCHEMA_MISMATCH`; neither an observation nor an approved action prefix
can execute first.

`GDA-CORE-007` closes the recovery tool-scope gap locally. Strict continuation
v6 now persists the immutable final Host-advertised names, rejects older or
malformed evidence, and permits recovery to derive only the currently evidenced
read-only subset. The Host passes one ordered tuple through provider restore,
stateless replay, and turn creation, then atomically rejects any returned call
outside that tuple before provider completion or future MCP dispatch.

The next bounded audit selected `GDA-CORE-008`. The MCP server currently calls
`HumanActivity.note_agent_action()` after every action-shaped result, including
semantic UIA actions, activation, validation failures, and driver failures that
did not inject native input. If real human input arrives during such a call, the
unconditional note can claim the human's tick as agent-generated and let a
following native action bypass the safe-local human-yield gate. The next slice
must record agent input only for known-successful native-input routes.

This scope change does not alter Full Cycle state. Lane A manifest/export v1,
the consumer fixture, and the Runtime freeze remain complete. Lane B remains
disabled by default and deferred to the external Full Cycle `FC-BRIDGE-003`
consent, security, and privacy review. If Full Cycle is explicitly resumed, the
exact resume point is that external review; no rich capture work starts here.

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
| Offline baseline | `1619 passed, 8 skipped` in the 2026-08-04 `GDA-CORE-007` closure revalidation |
| Worktree at start | Clean |
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
| `GDA-CORE-007` | Complete locally | Preserve the original Host-advertised tool scope across recovery | Strict continuation v6 binds the exact final Host-advertised names; recovery narrows them to currently evidenced observations and uses the same ordered tuple for provider restore, stateless replay, request creation, and returned-turn validation. Old/corrupt evidence, unauthorized mandatory observation synthesis, mismatched completed ledgers, and out-of-scope returned calls fail closed; complete gate: `1619 passed, 8 skipped`, Ruff, mypy, docs consistency, diff check, and independent authority review passed on 2026-08-04 |
| `GDA-CORE-008` | Next | Prevent non-native or failed MCP actions from claiming a human input tick | Record agent input only after a known-successful native-input route; semantic UIA actions, activation, invalid/no-op calls, and failed driver calls must leave concurrent human activity authoritative so the next safe-local action yields with zero dispatch |

`GDA-CORE-007` is complete locally on
`codex/core-runtime-recovery-tool-scope`; no new implementation starts until it
is merged and a fresh branch is created for `GDA-CORE-008`. `GDA-DEMO-006` is
paused at its exact resume point, and no `GDA-HUD-*` item is active. The
historical Full Cycle freeze remains the handoff baseline; it no longer freezes
the separately reopened core Runtime scope above.

## Defect found by composing the HUD surfaces (2026-08-01)

The workflow HUD would not have appeared in a real Demo run, and would not have
said so. `GDA-HUD-005` and `GDA-HUD-006` were verified with each surface driven
alone; opening both together for `GDA-HUD-009` is what exposed it.

`ctypes.windll.user32` returns one cached library object per process, and every
function on it carries a single mutable `argtypes`/`restype`. The Decision Card
and the Progress HUD each define their own `_MONITORINFO` and each pinned
`GetMonitorInfoW.argtypes` to a pointer to its own type. Constructing the card
adapter made the progress adapter's `byref` of a structurally identical type
raise `ArgumentError`, so the progress window failed to open.
`scripts/demo_cross_app.py` builds the card adapter before the Runner opens the
progress window, and `DemoWorkflowProgress` is fail-silent by design, so the
checklist would simply have been missing with `error_count` latched and nothing
on screen.

Every adapter now takes a private library handle through
`computer_use_agent.win32_dll.private_windll`; only the Python-side prototype
tables are private, the loaded DLLs are unchanged. Three offline tests pin it:
the adapters hold distinct handles, prototyping one handle cannot reach another
or the process-wide table, and the exact ordering the Demo uses no longer
breaks the progress adapter.

Isolating the handles then exposed a second latent dependency: the text
measurement helper had been inheriting `CreateFontW`, `SelectObject`, and
`DeleteObject` prototypes that an adapter happened to set on the shared table.
On a private handle nothing had declared them and a default `c_int` return
truncated a 64-bit handle. It now declares every prototype it uses.

## Presence halo: three causes, none of them the suspected one (2026-08-02)

`GDA-HUD-001` opened with an operator reporting no visible halo. Chasing it by
eye across three complete Demo runs found one cause at a time, and each fix
looked correct in isolation while the symptom persisted. Instrumenting the run
settled it in one pass. The lesson is recorded because it generalises: a
surface that is capture-excluded by design cannot be verified by asking an
operator what they saw.

`scripts/demo_cross_app.py` now writes a presence probe report into
`final-state.json` — the projection sequence the halo was asked to show, plus
sample counts for painted, unpainted, and window-absent. The sampled run
`cross-app-demo-20260802-144124-559107` reported `projection_count: 0` and
`samples_window_absent: 32`, which named the third cause immediately.

The three causes were: a DPI source that always reports 96; a coordinator that
never pumped a message loop, so the window never painted and a colour-keyed
layered window that never paints is fully transparent; and a transient approval
yield expressed with the latching `release()`. The second had made the halo
invisible in every Demo run this repository has ever recorded.

## Cross-repository correction (2026-08-01)

The consumer repository recorded three status conflicts that it deliberately
refused to fix on this repository's behalf. All three are corrected here.

1. `GDA-FC-002` was still marked `Next`, and the `Exact active task` section
   still sent a new session to implement a consumer that
   `reliable-agent-model-lifecycle` had already completed and gated as
   `FC-BRIDGE-001` on 2026-07-28. The row and that section are corrected.
2. `GDA-FC-004` recorded clean release-preflight evidence for producer
   candidate `45bee82`. That candidate was squash-merged into `main` as
   `8ace897` (PR #219) and is no longer reachable from any branch, so the
   recorded identity could not be resolved by a later session. The 2026-07-28
   preflight itself is not rewritten; only the durable identity is corrected.
   `git merge-base --is-ancestor 45bee82 main` and the same check against
   `HEAD` (`7001375`) both fail; the same check for `8ace897` passes.
3. `GDA-FC-004` claimed `Complete locally` while the consumer's matching
   `FC-BRIDGE-004` was `Pending`. Because the recorded preflight commit is
   unreachable and the freeze must cover a candidate that already contains the
   completed consumer contract, this row is demoted to `Next` rather than the
   consumer row being promoted.

Verification performed on 2026-08-01, offline only:

| Check | Command | Result |
| --- | --- | --- |
| Consumer offline gate | `python -I .\scripts\validate_offline.py` in `reliable-agent-model-lifecycle` | `Ran 50 tests ... OK`, report `"valid":true`, `"tests_run":50`, Python 3.13.7 |
| Pinned manifest digest | Consumer report and `fixtures/bridge_v1/fixture-metadata.json` | Both `sha256:6abe3431ea0e6b4065f21e9a6c6fe34de772f9c3c86a2437f8d14f95a5d6f522` |
| Producer contract drift | `fullcycle manifest` regenerated from this branch's `HEAD` | 7183 bytes, 13 tools, digest identical to the pinned consumer digest, so Lane A has not drifted since `8ace897` |
| Commit reachability | `git merge-base --is-ancestor 8ace897 main` | Passes; the consumer pin is valid |
| Runtime offline gate | `pytest -q`, `ruff check src tests scripts`, `mypy`, `check_docs_consistency.py`, `git diff --check` | `1529 passed, 8 skipped`; Ruff `All checks passed!`; mypy `no issues found in 116 source files`; docs `OK (13 reviewed tools)`; diff clean |

The Runtime gate above also re-establishes the post-rebase offline result that
`HANDOFF.md` flagged as outstanding for `codex/demo-hud-baseline`. It is an
offline result only and promotes no provider, desktop, application, or release
evidence.

## Completed bounded task: GDA-DEMO-001

1. Use a dedicated browser profile and controlled local webpage fixture.
2. Observe and interact with real Chrome through reviewed desktop tools.
3. Create a disposable Word document through the existing Runner/MCP dispatch
   authority.
4. Project lifecycle changes through the existing Presence Halo and passive
   Progress Window.
5. Yield desktop authority and show the existing Decision Card before one
   exact local save effect.
6. Re-observe and verify the saved artifact.
7. Use no personal browser state, account, message, or production data.
8. Do not promote application evidence until a retained real-environment run
   passes.
9. Keep the application for the current step visibly in the foreground:
   activate the exact listed window before entering each application stage,
   re-observe it after activation, and stop if foreground verification fails.

The retained real-environment run passed with thirteen tool calls and five
operator-approved side effects. Chrome and Word were activated and re-observed
at their application boundaries, the disposable Word artifact was saved, and
the fixed verification marker was present afterward. This is bounded
application evidence, not a universal-GUI capability claim.

## Completed bounded task: GDA-DEMO-002

1. Keep the dedicated Chrome fixture in a normal `1280x900` window.
2. Use the public Microsoft Support Word-collaboration page and a professionally
   formatted `.docx` research-note fixture.
3. Activate and re-observe each current application before acting.
4. Page through the public article once, then re-observe it without submitting
   a form, using an account, or changing remote state.
5. After every approval, require three consecutive healthy human-idle heartbeat
   samples before dispatch; defer without dispatch if stability is unavailable.
6. Move the real Word cursor to the end of the research notes.
7. Show one exact approval for the fixed source follow-up, then enter it with a
   bounded visible per-keystroke delay.
8. Save through Word and verify the semantic text and durable DOCX package.
9. Do not promote the enhanced evidence until a complete retained run passes.

Retained run `cross-app-demo-20260730-042826` passed with seventeen tool calls
and seven operator-approved effects. It opened a public Microsoft Support page
in windowed Chrome, performed one approved `PageDown`, re-observed the page,
activated real Word, moved the cursor to the document end, visibly typed a
fixed public-source summary, saved, and verified the durable DOCX. The
approval-to-dispatch heartbeat required three consecutive healthy idle samples
and never replayed a failed action. Subsequent restart hardening guarantees a
new empty browser profile, pristine DOCX copy, unique run identity, fixed
browser geometry, and foreground-only same-title browser binding. Those
fresh-start invariants are offline verified; the retained application run
predates that final hardening delta.

## Resumed bounded task: GDA-DEMO-003 issue inventory

This is the only status registry for the Operator HUD work. Each future session
must explicitly resume one issue ID, keep the other rows paused, and return to
`GDA-FC-002` afterward. The exploratory live run
`cross-app-demo-20260730-044009-247254` is failed evidence, not a retained pass:
it ended after five tool calls, two approved side effects, and one known
`DENIED_BY_GATE` failure on the approved Chrome `PageDown`. It did not reach
Word editing or save verification. No Demo process remains running.

| ID | Category | Current problem | Current implementation state | Acceptance before closure |
| --- | --- | --- | --- | --- |
| `GDA-HUD-001` | Presence visibility | The operator reported no visible full-screen halo during the earlier live run. Presence is capture-excluded, so retained evidence must come from its probe rather than a screenshot. | Three separate causes made the halo invisible and all are fixed. Post-fix retained run `cross-app-demo-20260803-024517-764321` completed all seven approval boundaries with 85 projections, 247 painted samples, zero unpainted samples, and all expected active and waiting states. [Evidence](docs/OPERATOR_HUD_DEMO_EVIDENCE_2026-08-03.md). Presence remains `WDA_EXCLUDEFROMCAPTURE`. |
| `GDA-HUD-002` | Decision Card layout | The original card clipped and lacked compact visual hierarchy. | The rebuilt card passed live compact and expanded review at 100% and 125% on 2026-08-03; the retained 150% matrix passed on 2026-08-01. Across all three scales, the fixed header, countdown, approval/workflow qualifiers, details affordance, detail pane, scrollbar, and 2x2 choices remain bounded and readable. [Multi-DPI evidence](docs/OPERATOR_HUD_DPI_EVIDENCE_2026-08-03.md). | Default view fits wholly in the work area and shows only lock state, `1/7`, current action, application, countdown, a details affordance, and a 2x2 set of short choices. No overlap, clipping, or scroll is present in compact mode at 100%, 125%, and 150% DPI. |
| `GDA-HUD-003` | Expandable details | “Expand technical details” currently toggles only the evidence pane inside the same crowded layout; it is not a genuine compact/expanded state. | The same synthetic card intentionally resizes between compact and expanded geometry. Compact hides both panes; expanded shows human-readable decision trade-offs and safety checks with abbreviated support fingerprints; collapse restores the saved compact rectangle without changing the pending decision. The sunken `WS_EX_CLIENTEDGE` bevel was replaced by hairline-bounded panes with legible scrollbars, and the toggle now matches the Progress HUD's `SHOW/HIDE DETAILS` chevron. [Live 150% DPI acceptance](docs/OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md) is retained for both states. | Compact mode hides both decision trade-offs and digest evidence. Expanding reveals bounded decision details and evidence; collapsing restores the exact compact geometry without losing the pending decision. |
| `GDA-HUD-004` | Approval lock and exit | “Locked” must never mean trapping the operator or allowing later dispatch while a decision remains pending. | Top-level and child-control message paths map `Esc` to a null selection; close and timeout deny. Dispatch pausing is structural: the Runner awaits `request_approval`, so no later action can be reached while the card is open. `scripts/smoke_decision_card_exits.py` drove `Esc`, `WM_CLOSE`, and countdown expiry against the real window twice consecutively on 2026-08-01; each returned no selection and restored the exact prior foreground window. A source-level test asserts the module never reaches for global hooks or input-blocking APIs. On 2026-08-03 the operator physically pressed Alt+Tab while the synthetic non-dispatching card was presented and confirmed that Windows switched windows. [Keyboard evidence](docs/OPERATOR_HUD_KEYBOARD_EVIDENCE_2026-08-03.md). | While open, no later action dispatches. `Esc`, close, and timeout all produce safe deny/defer and restore the previous foreground application. Alt+Tab and Windows security keys remain available. Positive approval still requires an explicit bounded choice. |
| `GDA-HUD-005` | Step semantics | The surfaces mix different totals: Progress uses the Host tool-call budget while the card shows seven approval actions. The progress view cannot yet name the exact current Demo chapter from durable Host state. | A bounded immutable checklist defines six fixed Demo chapters and drives compact/expanded Progress projections. The pure `project_demo_workflow` mapper fail-closed maps fixed provider boundaries `0..18` to the six Host-owned chapters and now also covers the cancelled boundary. `DemoWorkflowProgress` connects it: the provider reports only an integer boundary, the durable `RunPhase` owns overall status, and the Demo Decision Card derives its breadcrumb from `WorkflowBreadcrumb.from_checklist` while the approval `n/7` count stays separate. Approval wait projects `NEEDS_INPUT`, durable success projects `READY` only at the terminal boundary, and failure, uncertainty, or cancellation never complete the interrupted chapter. The complete offline gate passed on 2026-08-01. `scripts/smoke_demo_workflow_progress.py` then passed three consecutive times on the real non-activating Win32 surface: the foreground never moved from `0x204a0`, the first open showed every chapter, and a provider boundary, approval wait, held terminal chapter, and durable `SUCCESS` each reached worker-owned pixels. It asserts no tool-call diagnostics and no approval `n/7` count leak into the workflow HUD. This is isolated live evidence for the projection surface only; it opens no Runner, MCP, provider, or application, so it is not Demo, application, or release evidence. | The UI clearly labels “workflow step” versus “approval n/7”, names the current fixed action without trusting provider prose, and defines how skipped, failed, verification, and terminal steps affect counts. |
| `GDA-HUD-006` | Progress HUD visual design | The passive progress window has only received a dark fill and accent stripe; its hierarchy, compactness, typography, current-action emphasis, and expand behavior have not been seen or accepted live. | The DPI-scaled compact summary now has a non-activating `SHOW/HIDE STEPS` affordance. Expanded state appends all six Host-owned rows with fixed status glyphs and labels; collapse restores compact geometry. Computer Use completed an expanded-to-compact-to-expanded round trip at the current DPI with no clipping or state loss. The bounded Demo now drives this surface instead of the generic `state_dir` poller, so it no longer shows tool-call budgets: `DemoWorkflowProgress` owns one worker thread for every open, repaint, pump, and close, the first open shows all six chapters, and an operator collapse survives later refreshes. A dedicated live smoke confirms the real window stays non-activating across every projected transition (see `GDA-HUD-005`). Operator collapse preservation remains deterministic-offline only, because toggling the live affordance needs synthesized input. Retained production evidence remains. | A live passive window remains non-activating and foreground-safe while clearly showing overall progress, current action/phase, application, and expandable sanitized detail. |
| `GDA-HUD-007` | Cross-surface visual system | Presence, Progress, and Decision Card initially lacked one shared hierarchy and approval-state vocabulary. | One fixed token contract now owns operator labels, glyphs, RGB roles, chrome, shared type tiers, and phase/approval vocabulary. Both Win32 backends consume it, and a test asserts that the two interactive surfaces resolve one palette. The bounded Demo surfaces do not animate, so no reduced-motion override is needed. High-contrast mode was not promoted and remains outside this bounded evidence claim. | The standard-theme bounded Demo uses shared typography, spacing, phase colors, and status vocabulary; approval transition is visually obvious. No high-contrast capability claim is made. |
| `GDA-HUD-008` | Approval-to-dispatch heartbeat | The post-approval heartbeat raced the MCP human-activity gate in the exploratory run: the card approved `PageDown`, but dispatch returned known `DENIED_BY_GATE`. | The bounded Demo now restores the captured foreground before making exactly one MCP action call. That call owns one bounded readiness sequence: three consecutive healthy idle samples, foreground allowlist verification, then at most one driver dispatch. The duplicate Host-side heartbeat was removed. Idle timeout, unavailable observation, foreground denial, E-stop, and user denial are returned as `rejected` with known `not_dispatched`; none is replayed. Deterministic offline tests cover streak reset, timeout, fail-closed observation, one-call/one-dispatch behavior, and result conversion. Repeated real Chrome/Word evidence remains. | One Host-configured, MCP-enforced readiness protocol covers card close, foreground restoration, idle stabilization, the foreground gate, and at most one dispatch. A denied gate causes no replay, and repeated real runs cross the boundary reliably without guessing a fixed delay. |
| `GDA-HUD-009` | Foreground and window composition | The current application must remain foreground while passive HUD surfaces stay visible and non-interactive; the card must restore that application after any exit. | Progress anchors to the foreground monitor's top-right work-area rail; Decision Card uses the same monitor's bottom-right rail and restores the captured foreground on every exit. Pure geometry covers 100%, 125%, and 150% DPI. `scripts/smoke_hud_composition.py` opened all three real surfaces twice on 2026-08-01: passive surfaces did not activate, the card alone took focus, painted Presence pixels covered neither companion surface, the card and Progress did not overlap, and safe close restored foreground. The complete retained Chrome-to-Word run supplies bounded application composition, while the isolated live matrix supplies multi-DPI card composition. This does not claim a complete Chrome-to-Word run at every display scale. | Bounded live and deterministic evidence prove passive foreground safety, Decision Card focus and restoration, surface separation, application composition, and multi-DPI geometry without promoting a universal composition claim. |
| `GDA-HUD-010` | Restart and cleanup | Fresh browser/document state is offline verified, but a failed or cancelled HUD run can leave launched Chrome/Word fixtures open. The next session needs an explicit cleanup/restart contract. | Cleanup is now a reusable exact-process component rather than a Demo-only process kill. It posts `WM_CLOSE` only to visible unowned top-level windows for each retained launch PID, observes all visible windows for that PID including owned dialogs, and treats verified window disappearance as completion even while an application process drains naturally. It force-terminates only when exact owned windows remain after the bounded close wait or a partial launch exposes no window; unavailable observation becomes explicit `handoff_required`. It never scans or terminates by executable name. The Demo uses the component from one `finally` and records fixture identity, close count, disposition, exit snapshot, and process-running snapshot. A live diagnostic caught force-termination-induced Word AutoRecover; after the generalized fix, two consecutive real fixture-cleanup smokes (`...091139-912478`, `...091235-478306`) each observed exactly two disposable windows, closed both as `windows_closed`, preserved the pre-existing Chrome window, and produced no recovery window on restart. | Start and end state are both declared. A failed/escaped run closes or clearly hands off its disposable windows, and the next run starts from the same pristine state without touching unrelated user windows. |
| `GDA-HUD-011` | Evidence and promotion | Retain the proportional evidence needed to close the bounded Demo without promoting it into a universal claim. | [The 150% DPI image matrix](docs/OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md), [100%/125% DPI acceptance](docs/OPERATOR_HUD_DPI_EVIDENCE_2026-08-03.md), [physical Alt+Tab acceptance](docs/OPERATOR_HUD_KEYBOARD_EVIDENCE_2026-08-03.md), and [post-fix complete run](docs/OPERATOR_HUD_DEMO_EVIDENCE_2026-08-03.md) are retained. The run reached durable `SUCCESS` with 17 tool calls, seven approved effects, zero tool failures, 247 painted Presence samples, and exact-process cleanup. All handoff-listed operator-only evidence is complete. | Each issue has proportional offline tests, a dedicated live smoke where visual behavior matters, one complete retained Chrome-to-Word run, documented DPI/keyboard evidence, full validation gate, and explicit statement that the result remains bounded rather than universal GUI evidence. |

### Recommended separate-session order

1. `GDA-HUD-002` + `GDA-HUD-003`: compact/expanded Decision Card geometry.
2. `GDA-HUD-004`: safe lock state and keyboard/foreground behavior.
3. `GDA-HUD-001`: held-phase and waiting-approval halo visibility.
4. `GDA-HUD-005` + `GDA-HUD-006`: truthful step model and progress HUD.
5. `GDA-HUD-007` + `GDA-HUD-009`: unified composition and foreground rules.
6. `GDA-HUD-008`: authoritative heartbeat/readiness handshake.
7. `GDA-HUD-010` + `GDA-HUD-011`: restart cleanup, full Demo, and evidence.

The first session should begin from the user-provided failed-card screenshot and
must not restart the complete Demo until the compact card passes an isolated
visual smoke.

## Completed task: GDA-FC-002

The offline consumer lives in `C:\Users\Alienware\reliable-agent-model-lifecycle`
as `FC-BRIDGE-001`, not in this repository's Runtime. Every acceptance point is
implemented there:

1. an offline consumer for manifest v1 and redacted run-export v1
   (`src/fullcycle_bridge/consumer.py`);
2. validation of exact supported versions, the manifest digest, data class,
   training use, and every `automatic_export` false claim;
3. eight invalid fixtures covering unknown version, digest mismatch, malformed
   JSON, incomplete event, unexpected field, rich content, wrong data class,
   and wrong training use;
4. one valid manifest and one minimal valid run export generated from the
   canonical producer with no provider, MCP, desktop, network, approval,
   memory, or continuation access;
5. producer commit `8ace897`, PR #219, consumer schema `1.0.0`, and every
   contract version pinned in `fixtures/bridge_v1/fixture-metadata.json`.

Rich multimodal capture was correctly excluded. `GDA-FC-003` is explicitly
deferred to the Full Cycle project's separate `FC-BRIDGE-003` consent,
security, and privacy review and remains disabled by default.

## Completed task: GDA-FC-004

The 2026-08-02 freeze candidate is
`324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`. The presence branch was
fast-forwarded into local `main` without rewriting its three reviewed commits,
and `git merge-base --is-ancestor 324ff2fb main` passed before the preflight.
The clean [release preflight](docs/RELEASE.md) passed with the same start and
end commit and clean source at both endpoints:

- CPython `3.13.7`, report schema `5`;
- `1566 passed, 8 skipped`, Ruff passed, and the diff check passed;
- 13/13 frozen E1/E2 cases with zero safety escapes;
- 15 crash-reconstruction cases (`22` tests) and 9 stateless-replay cases
  (`11` tests), with zero failures or skips;
- wheel `guarded_desktop_agent-0.1.0-py3-none-any.whl` built and installed in
  the no-deps smoke environment;
- report SHA-256
  `dc78f08030b4d3c4fac255a91fb7badf2b06fdb0eb0c487073e1f825260c6d0e`.

A manifest regenerated from the candidate has SHA-256
`6abe3431ea0e6b4065f21e9a6c6fe34de772f9c3c86a2437f8d14f95a5d6f522`,
identical to the immutable `FC-BRIDGE-001` fixture produced at `8ace897`.
The consumer's `baseline/runtime-freeze-v1.json` separately pins the freeze
commit and contract versions without rewriting that fixture's provenance.

The local preflight records one Python runtime; supported-version evidence
still comes from the CI Python 3.11-3.13 matrix. This is an offline Runtime
freeze, not new provider, desktop, application, or release approval evidence.
After the coordinated records were written, the complete repository gate also
passed: `1566 passed, 8 skipped`, Ruff passed, mypy reported no issues in 118
source files, documentation consistency reported 13 reviewed tools, and
`git diff --check` passed.

## Completed slice: `GDA-CORE-007`

Continuation v6 persists a canonical, unique list of the exact final
caller/privacy/current-MCP-baseline-filtered Host-advertised names. Recovery
fails closed on v1-v5 or malformed scope evidence, derives only the persisted
read-only tools whose current safety baselines are evidenced, and gives the
same ordered tuple to provider restore, stateless replay, and turn creation.
The Host rejects out-of-scope returned calls before provider export/completion
or MCP eligibility and forbids mandatory `ui_snapshot` synthesis from widening
the original scope. Exact completed model/tool/result correlation is also
required. OpenAI request-contract drift fails before network access; Anthropic
remains governed by the same provider-neutral Host boundary.

## Exact next task: `GDA-CORE-008`

`build_server()` currently calls `HumanActivity.note_agent_action()` for every
action-shaped return, even when no native mouse or keyboard input was injected.
A deterministic safe-local reproduction performs a semantic ref click while a
real human-input tick advances; the unconditional note adopts that tick as the
agent's own, so a following coordinate click passes the human-yield check and
dispatches. Activation, validation/no-op errors, failed driver calls, semantic
`Invoke`/`SelectionItem`/`ValuePattern` routes, and any other non-native path
must not claim a tick.

Create `codex/core-runtime-human-yield-attribution` from the merged
`GDA-CORE-007` `origin/main`. Carry a structured success result plus an explicit
native-input fact to the server's action recorder and call
`note_agent_action()` only after a successful route known to inject bounded
native input. Freeze three boundaries: concurrent human input during a semantic
or activation action blocks the next safe-local native action with zero second
dispatch; successful native input still does not self-block; failed or no-op
input never claims a human tick. Preserve audit behavior, final authority
rechecks, ref semantics, and the sole MCP/Runner dispatch path. Update the
owning MCP safety/configuration contract and run the complete gate. Do not
resume Demo, Full Cycle consumer, training, BF16, Operator HUD, Universal GUI,
or Multi-Agent work.

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
must not displace `GDA-CORE-008`.

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

## Definition of closed

This repository is closed locally for the Full Cycle handoff because:

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
2. Update exactly one backlog row and the `Exact next task` section.
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

| Date | Decision |
| --- | --- |
| 2026-07-28 | The Runtime is a Full Cycle dependency, not the model-training repository. |
| 2026-07-28 | Existing redacted traces may feed reliability/evaluation work but are insufficient for multimodal model training. |
| 2026-07-28 | Rich episodes require an explicit-consent external capture adapter and a separate privacy/security review. |
| 2026-07-28 | New product features are frozen until the bridge and baseline handoff close. |
| 2026-07-28 | Lane A manifest/export v1 is implemented; the next code task is the external offline consumer, not more Runtime capability. |
| 2026-07-28 | Clean release preflight passed for the producer candidate later squash-merged as `8ace897` (recorded at the time as pre-merge candidate `45bee82`, which is now unreachable); Runtime remains feature-frozen while the external consumer is completed. |
| 2026-07-30 | Operator HUD polish was paused after a failed live review. Eleven issues are classified under `GDA-DEMO-003`; they may be resumed one bounded session at a time without displacing the Full Cycle resume point. |
| 2026-08-01 | `GDA-FC-002` is complete; the consumer contract is owned and gated by `reliable-agent-model-lifecycle`. `GDA-FC-004` becomes the single active item. |
| 2026-08-01 | Durable evidence must name a commit reachable from a branch. Pre-merge candidate `45bee82` was replaced by its squash merge `8ace897`; the earlier preflight result is retained, its unreachable identity is not. |
| 2026-08-02 | Lane B is explicitly deferred from the Runtime freeze to the Full Cycle project's separate `FC-BRIDGE-003` consent, security, and privacy review; it remains disabled by default. |
| 2026-08-02 | `GDA-FC-004` completed locally at branch-reachable Runtime commit `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`; clean release preflight and the matching consumer freeze record passed without changing Lane A contracts or fixture provenance. |
| 2026-08-03 | The user explicitly reopened core Runtime development without reopening Demo or Full Cycle consumer work. Core changes must preserve the frozen Full Cycle baseline, completed Lane A state, disabled/deferred Lane B boundary, and external `FC-BRIDGE-003` resume point. |
| 2026-08-04 | `GDA-CORE-001` removed the implementation's forbidden ref-to-coordinate fallback and restored alignment with accepted ADR-002; explicit coordinate clicks remain a separate caller-authorized path. |
| 2026-08-04 | `GDA-CORE-002` added a final non-waiting e-stop and foreground authority revalidation before every MCP native action dispatch while preserving the intentional `activate_window` foreground exception. |
| 2026-08-04 | Repository consolidation pauses `GDA-DEMO-006` at checkpoint `d74201f` in draft PR #231 and keeps `GDA-CORE-003` as the only active item; the Demo's exact fresh live-run resume point and both Full Cycle lane boundaries remain preserved here. |
| 2026-08-04 | `GDA-CORE-003` preserves result-carrying post-dispatch cancellation as durable `UNKNOWN_OUTCOME`, retains cancellation semantics and zero replay, and keeps persistence failures observable without loading the MCP SDK into the Agent foundation. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-004` next: the Host must enforce the exact final tool set advertised for each provider turn before continuation persistence, approval, or MCP dispatch. |
| 2026-08-04 | `GDA-CORE-004` makes the final caller/privacy/MCP-baseline-filtered advertised set a Host authority boundary and atomically rejects the whole returned turn before ledger, continuation completion, approval, or dispatch. |
| 2026-08-04 | `GDA-CORE-004` merged through PR #233 as `5c9c379`; `GDA-CORE-005` is now the sole active core Runtime item. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-005` next: read-only recovery must revalidate the current MCP generation's required safety baselines before persisting intent or dispatching an observation. |
| 2026-08-04 | `GDA-CORE-005` revalidates required tool safety baselines against the current MCP generation before any recovered observation intent, authorization, or dispatch; missing evidence leaves both durable files byte-identical. |
| 2026-08-04 | `GDA-CORE-005` merged through PR #234 as `ea2e063`; `GDA-CORE-006` is now the sole active core Runtime item. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-006` next: reviewed schema and canonical-argument validation must be whole-turn atomic so no valid prefix executes before a malformed sibling fails. |
| 2026-08-04 | The separate `GDA-CORE-007` recovery-scope gap remains queued: continuation must version and preserve the original Host-advertised tool scope rather than widening a restricted run after a crash. |
| 2026-08-04 | `GDA-CORE-006` makes reviewed schema and canonical-argument validation whole-turn atomic after advertised-name validation; malformed siblings cannot grant an observation or approved-action prefix any authority. |
| 2026-08-04 | A real Anthropic recovery reproduced `GDA-CORE-007`: a run restricted to `ui_snapshot` widened to six advertised observations and later dispatched `list_windows`; exact Host tool scope must become versioned continuation evidence. |
| 2026-08-04 | `GDA-CORE-006` merged through PR #235 as `33b0d73`; all four GitHub checks passed, and `GDA-CORE-007` is now the sole active core Runtime item on `codex/core-runtime-recovery-tool-scope`. |
| 2026-08-04 | `GDA-CORE-007` will bind continuation v6 to the exact final Host-advertised names and allow recovery only to narrow that authority to currently evidenced observations; one ordered scope must govern provider restore, stateless replay, request creation, returned-turn validation, and later MCP eligibility. |
| 2026-08-04 | The user reaffirmed that project-body core Runtime development takes priority now that Pro is available; `GDA-DEMO-006` remains paused at `d74201f` / draft PR #231 and resumes only after the core Runtime phase is deliberately closed or reprioritized. |
| 2026-08-04 | `GDA-CORE-007` is complete locally and independently reviewed: strict continuation v6 preserves and narrows original Host tool authority across recovery, with old/corrupt evidence and every tested widening path failing closed. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-008` ahead of verification-capacity work: only a known-successful native-input route may claim the current input tick as agent-generated; semantic, activation, invalid, no-op, and failed actions must preserve concurrent human authority. |
