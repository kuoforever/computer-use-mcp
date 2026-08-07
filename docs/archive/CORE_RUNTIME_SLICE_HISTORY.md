# Core Runtime and bounded-task slice history

> **Status: historical, non-normative.** Moved out of `PROJECT_STATUS.md` on
> 2026-08-07 so the operational entry point carries only the active item.
> These records are not capability evidence and must not override an active
> owner document. Current status is owned by
> [`PROJECT_STATUS.md`](../../PROJECT_STATUS.md); capability claims by
> [capability status](../CAPABILITY_STATUS.md).

Every closure fact below also has a row in the `PROJECT_STATUS.md` Closure
backlog table. What survives only here is the *pre-closure gap analysis* for
each slice: why the audit selected it and what the defect actually was.

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

`GDA-CORE-007` closed the recovery tool-scope gap. Strict continuation
v6 now persists the immutable final Host-advertised names, rejects older or
malformed evidence, and permits recovery to derive only the currently evidenced
read-only subset. The Host passes one ordered tuple through provider restore,
stateless replay, and turn creation, then atomically rejects any returned call
outside that tuple before provider completion or future MCP dispatch. It is
merged through PR #236.

`GDA-CORE-008` closed the human-yield attribution gap. The MCP server
now retains each structured `Result` plus an explicit route fact and records an
agent tick only after a known-successful native-input route. Semantic UIA
actions, activation, validation/no-op failures, and every failed driver result
leave concurrent human input authoritative, while successful coordinate click,
scroll, drag, focused typing, and key routes still avoid yielding to themselves.
It is merged through PR #237.

`GDA-CORE-009` closed the post-action verification-capacity gap. Before
approval exists, the Runner now requires one next model turn, input-token
headroom, a reducible projected `ALLOW` plus dispatched-result context, and one
remaining observation call. Fixed model/input/context/tool insufficiency records
a known-not-dispatched budget result while preserving the verified observation
and granting zero approval, action continuation, side-effect budget, or MCP
authority. It is merged through PR #238.

`GDA-CORE-010` closed the approval-wait authority gap. After recording a
valid `ALLOW`, the Runner now revalidates grounding against the live MCP
generation and required baselines against live child evidence before side-effect
budget, action continuation, or MCP dispatch. Generation or baseline drift keeps
the decision as an audit fact but appends a rejected/not-dispatched policy result
with zero action authority. It is merged through PR #239.

`GDA-CORE-011` closes the continuation tool-compatibility gap. With sensitive
continuation enabled, the Host now omits `type` from the final provider tool
tuple and persisted advertised scope. A provider that nevertheless returns a
typed-text call is rejected with fixed `PROVIDER_TOOL_NOT_ADVERTISED` before
model/tool budget, provider completion, approval, side-effect, or MCP; strict
continuation v6 still rejects raw typed text, while continuation-disabled,
baseline-satisfied typing remains unchanged.

The next bounded audit selected `GDA-CORE-012`. A provider turn containing more
than one call can currently dispatch its first side effect before a later
sibling triggers mandatory re-observation and terminates the run. The sibling
does not gain action authority, but it can consume the only flow that
`GDA-CORE-009` reserved to verify the already-dispatched action. The next slice
must make every side-effect-bearing provider turn exactly one call and reject
the whole non-serial turn before model/tool budget, provider completion,
approval, side-effect budget, continuation action records, or MCP dispatch.

`GDA-CORE-012` closes that provider-turn atomicity gap. After advertised-name
and reviewed-schema validation, the Host now rejects every multi-call turn that
contains a reviewed side effect with fixed
`PROVIDER_SIDE_EFFECT_TURN_NOT_SERIAL`. The returned turn consumes no model/tool
budget or continuation completion and creates no policy, approval, action, or
MCP authority. Pure observation multi-call turns remain sequential, and a
single action still reaches its reserved fresh observation.

The next bounded audit selected `GDA-CORE-013`. The MCP's initial stable
human-idle evidence can age while the foreground gate retries or a dangerous
confirmation is open, while the final authority guard currently rechecks only
e-stop and foreground. The next slice must perform one final non-waiting human
activity check before driver dispatch. An affirmative dangerous confirmation
may carry only its exact current input tick as a one-call, non-persisted
exception; any newer or unavailable tick fails closed without dispatch.

`GDA-CORE-013` closed that final human-authority gap. Safe-local calls now bind
one stable readiness tick, then double-sample fresh input around the final
non-waiting idle observation after the final e-stop and applicable foreground
checks. Missing, changed, or newer evidence returns fixed `HUMAN_ACTIVE` with
redacted audit and zero driver calls. An affirmative dangerous confirmation can
excuse only its exact call-local tick; it is never persisted, attributed to the
agent, or reused. Activation retains its foreground exception but not the final
human check, and full-control-local retains its intentional human-yield bypass.
It is merged through PR #242.

The next bounded audit selected `GDA-CORE-014`. A continuation `prepare_tool`
or `dispatch_tool` write failure occurs before the sole MCP dispatch site, so
the tool is certainly not dispatched. The shared Runner currently lets that
exception escape with an older state; terminal recording then detects a ledger
rewind, masks the original failure, and can leave an `EXECUTING` checkpoint with
no correlated result. The next slice must turn only those two pre-dispatch WAL
failures into fixed `CONTINUATION_WRITE_FAILED` plus a rejected/not-dispatched
result and a terminal `FAILED` checkpoint. It must not catch post-dispatch
completion failures, infer unknown outcome, retry, or move the dispatch site.

`GDA-CORE-014` closes that persistence/certainty gap. The shared Runner catches
`ContinuationError` only around `prepare_tool` and `dispatch_tool`, appends a
same-identity/name `REJECTED/not_dispatched` result with reviewed fixed code
`CONTINUATION_WRITE_FAILED`, then raises `RunFailure` with the updated state.
The terminal recorder therefore advances from the latest ledger without a
rewind. Observation and approved-action failures at both WAL stages preserve
their exact budgets and audit facts while making zero target MCP calls;
post-dispatch completion, unknown-outcome, and cancellation paths are unchanged.
It is merged through PR #243.

The next bounded audit selected `GDA-CORE-015`. A ref currently relocates stale
native handles using one mutable session-wide observation scope. Observing scope
B after minting a ref in scope A can therefore retarget that ref to a same-name
control in B; a successful relocation also updates only the forward native map,
allowing duplicate refs and stale reverse entries. The next slice must bind each
ref to its first observation scope token, relocate only in that scope, and
atomically maintain the node/native/reverse maps. A candidate already owned by
another ref must fail closed with no candidate action and no coordinate fallback.

`GDA-CORE-015` closes that explicit-scope and binding gap. Each ref now retains
the scope token from its first observation, later snapshot/find calls cannot
replace it, and stale relocation queries only that token. A successful candidate
uses its complete fresh Node and rebinds cached node, forward native id, and
reverse ownership together; collision fails `STALE_ELEMENT` before candidate
action. Cross-scope, rebinding, collision, same-native, unknown-ref, and
semantic-only controls are regression tested. Driver APIs remain unchanged.

The next bounded audit selected `GDA-CORE-016`. The default `foreground` and
broad `all` scopes are dynamic selectors rather than stable window identities.
Even with `GDA-CORE-015`'s set-once token, a stale foreground ref can re-resolve
after focus moves to another allowlisted window and invoke a same-role/name
control there. The next slice must fail closed without a relocation query for
refs minted from `foreground` or `all`; only an explicit window-id scope may use
the bounded stale relocation path. A fresh observation is required after a
dynamic-scope ref becomes stale.

`GDA-CORE-016` closes that dynamic-selector relocation gap. After the original
native handle reports `STALE_ELEMENT`, a ref first minted through `foreground`
or `all` now fails with the same fixed code before another tree query, candidate
semantic action, coordinate action, or ref-map mutation. Explicit numeric
window-id scopes retain the single bounded complete-Node relocation and
bijective rebind path, including reverse-conflict failure. Driver contract
`1.0.0` remains unchanged.

`GDA-CORE-017` closes the driver-pacing authority window under accepted ADR 009.
A server-owned call scope now revalidates e-stop, applicable foreground, and
safe-local human authority before each driver-controlled native mutation.
Authority loss before the first mutation remains rejected/not-dispatched;
authority loss after any attempted native mutation becomes unknown/dispatched,
stops later mutation, and is never replayed. Cleanup releases only state held by
the call; it does not claim rollback of opaque native effects. Driver contract
`1.0.0` remains unchanged.

`GDA-CORE-018` closes the human-yield grounding gap. A side-effect result with
the exact `REJECTED / NOT_DISPATCHED / HUMAN_ACTIVE` tuple now clears the prior
verified observation, requires re-observation, and invalidates Host grounding
before continuation completion. A fresh successful observation restores action
authority; unrelated rejected results and unknown/dispatched certainty remain
unchanged.

`GDA-CORE-019` closes the live-gate grounding gap. A side-effect result with the
exact `REJECTED / NOT_DISPATCHED / DENIED_BY_GATE` tuple now clears the prior
verified observation, requires re-observation, and invalidates Host grounding
before continuation completion. Old refs and screenshot bounds cannot revive
through an unrelated observation or later allowlisted foreground; a fresh
successful observation restores action authority. Every other result tuple
retains its prior behavior.

`GDA-CORE-020` closes the post-attempt native-failure certainty gap under
accepted ADR 009. The server-owned call scope retains its native dispatch-attempt
count through action completion. A failed Windows action or ordinary exception
after any attempt is replaced by fixed redacted `NATIVE_OUTCOME_UNKNOWN`; the
Agent maps it to `UNKNOWN_OUTCOME / DISPATCHED`, invalidates the MCP generation,
terminalizes, and never verifies, continues, recovers, or replays that action.
Authority loss keeps its distinct fixed code, while zero-attempt stale,
missing-pattern, validation, bad-argument, and ordinary Driver failures retain
their existing semantics. Driver contract `1.0.0` remains unchanged.

`GDA-CORE-021` closes that recovery authority gap. Strict continuation v6 now
reconstructs and validates the complete boundary/ledger topology before treating
`boundary.next_step` as an equality constraint. The final
`ReconstructionAction`, not the persisted hint, selects model/input or tool-call
budget authority. The executor rechecks before external I/O, and locked
persistence rereads and replans before intent; an already-accounted singleton
prepared observation reuses its call without double charging. Contradictory or
forged topology fails before intent or external work, while uncertain
multi-observation state remains human-reviewed with zero replay. The v6 shape is
unchanged.

`GDA-CORE-022` closes that recovery-certainty gap. Recovery now folds the
complete canonical ledger before trusting the tail boundary, binds exact budgets
and observation counters to that fold, and permits the checkpoint only to retain
or tighten certainty. Provider completion, persistence intent, and failed
observation cannot erase verification debt; unknown and synthetic-stop outcomes
remain terminal; only a correlated successful ordinary observation restores
`ready`. Historical non-serial side-effect turns, abandoned provider calls, and
later events after terminal evidence fail before persistence or external work.
The locked writer preserves Host-only stricter state, and the trace finalizer
independently refuses every non-`ready` checkpoint.

`GDA-CORE-023` closes that activation-target gap. A successful model-visible
`list_windows` atomically replaces an MCP-instance-local map from each unique,
valid window id to its exact direct-owner PID and executable name. Activation
captures one binding before any wait, rejects concurrent replacement, and
revalidates exactly one live owner before every native mutation and after the
Driver returns. Target enumeration precedes the final e-stop/human probe at each
mutation checkpoint. Missing, invalid, duplicate, disappeared, or drifted
targets fail fixed and redacted; only a fresh successful list binds a
replacement.

`GDA-CORE-024` closes that configuration gap. `_env_list` now returns each
trimmed non-empty item while retaining the prior blank-environment default,
case, order, duplicate, and comma-only behavior. The shared parser therefore
normalizes both `CUMCP_REDACT_TITLES` and `CUMCP_ALLOWLIST` once. Real-server
tests drive a spaced second title through screenshot, OCR, and cropped capture;
one shared compact/spaced/default control plus the existing Gate tests retain
the allowlist semantics without duplicating a safety matrix.

`GDA-CORE-025` closes that find-order gap. Windows `get_tree()` and `find()` now
share one bounded traversal; an optional case-insensitive name/role query is
applied after Node construction but before visual de-duplication, the 200-result
cap, truncation accounting, and native-cache insertion. Nonmatches consume no
result capacity and receive no ref authority. Named UIA duplicates omitted
after the cap count once, while nameless controls retain their prior per-node
semantics. Ordinary snapshot node selection, cap, cache, and all public
contracts remain fixed.

`GDA-CORE-026` closes that document-range completeness gap. Windows
`document_text` now makes one bounded 40,002-UTF-16-unit probe, retains at most
20,000 Python characters, and marks a partially clipped range incomplete. The
envelope therefore reports `complete=false`, `truncated=true`, and
`omitted_blocks=0` while preserving the exact retained-prefix digest. A unique
read-failure sentinel also prevents a UIA exception or non-string result from
being misreported as a complete empty document; a legitimate empty string
remains complete.

`GDA-CORE-027` closes that Chromium query warmup gap. `Session.ui_snapshot()`
and `Session.find()` now share one private optional warmup that performs a
disposable `get_tree()` walk and bounded delay before the final read. The final
find still uses the original query and `driver.find()`, so only its matching
nodes enter the ref table and Driver cache. Missing-hook and zero-delay Drivers
retain one final read with no sleep.

`GDA-CORE-028` closes that deep-target relocation gap. Explicit-window stale-ref
relocation now uses the original scope, an empty-name fallback to the control's
role, a role-only control-type bound, the existing Chromium warmup, and the
Driver's full matching traversal. Exact role/name selection, nearest-bbox
tie-break, reverse-owner collision refusal, bijective rebind, and one semantic
retry remain unchanged. A single WindowsDriver/Session regression proves an
unnamed Button after 200 name-matching Edit decoys binds and invokes its fresh
native id.

The next bounded functional audit selected `GDA-CORE-029`. Windows implements
both `scroll()` and `drag()` and exposes them through the reviewed MCP tools, but
`WindowsDriver.capabilities()["features"]` omits both names. Capability
discovery therefore understates the real Driver surface. The future slice must
add only those two implemented features and one focused metadata regression.
Per the user's instruction, do not begin that slice automatically after the
`GDA-CORE-028` PR; this section is only its safe resume point.

This scope change does not alter Full Cycle state. Lane A manifest/export v1,
the consumer fixture, and the Runtime freeze remain complete. Lane B remains
disabled by default and deferred to the external Full Cycle `FC-BRIDGE-003`
consent, security, and privacy review. If Full Cycle is explicitly resumed, the
exact resume point is that external review; no rich capture work starts here.

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
| `GDA-HUD-001` | Presence visibility | The operator reported no visible full-screen halo during the earlier live run. Presence is capture-excluded, so retained evidence must come from its probe rather than a screenshot. | Three separate causes made the halo invisible and all are fixed. Post-fix retained run `cross-app-demo-20260803-024517-764321` completed all seven approval boundaries with 85 projections, 247 painted samples, zero unpainted samples, and all expected active and waiting states. [Evidence](../OPERATOR_HUD_DEMO_EVIDENCE_2026-08-03.md). Presence remains `WDA_EXCLUDEFROMCAPTURE`. |
| `GDA-HUD-002` | Decision Card layout | The original card clipped and lacked compact visual hierarchy. | The rebuilt card passed live compact and expanded review at 100% and 125% on 2026-08-03; the retained 150% matrix passed on 2026-08-01. Across all three scales, the fixed header, countdown, approval/workflow qualifiers, details affordance, detail pane, scrollbar, and 2x2 choices remain bounded and readable. [Multi-DPI evidence](../OPERATOR_HUD_DPI_EVIDENCE_2026-08-03.md). | Default view fits wholly in the work area and shows only lock state, `1/7`, current action, application, countdown, a details affordance, and a 2x2 set of short choices. No overlap, clipping, or scroll is present in compact mode at 100%, 125%, and 150% DPI. |
| `GDA-HUD-003` | Expandable details | “Expand technical details” currently toggles only the evidence pane inside the same crowded layout; it is not a genuine compact/expanded state. | The same synthetic card intentionally resizes between compact and expanded geometry. Compact hides both panes; expanded shows human-readable decision trade-offs and safety checks with abbreviated support fingerprints; collapse restores the saved compact rectangle without changing the pending decision. The sunken `WS_EX_CLIENTEDGE` bevel was replaced by hairline-bounded panes with legible scrollbars, and the toggle now matches the Progress HUD's `SHOW/HIDE DETAILS` chevron. [Live 150% DPI acceptance](../OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md) is retained for both states. | Compact mode hides both decision trade-offs and digest evidence. Expanding reveals bounded decision details and evidence; collapsing restores the exact compact geometry without losing the pending decision. |
| `GDA-HUD-004` | Approval lock and exit | “Locked” must never mean trapping the operator or allowing later dispatch while a decision remains pending. | Top-level and child-control message paths map `Esc` to a null selection; close and timeout deny. Dispatch pausing is structural: the Runner awaits `request_approval`, so no later action can be reached while the card is open. `scripts/smoke_decision_card_exits.py` drove `Esc`, `WM_CLOSE`, and countdown expiry against the real window twice consecutively on 2026-08-01; each returned no selection and restored the exact prior foreground window. A source-level test asserts the module never reaches for global hooks or input-blocking APIs. On 2026-08-03 the operator physically pressed Alt+Tab while the synthetic non-dispatching card was presented and confirmed that Windows switched windows. [Keyboard evidence](../OPERATOR_HUD_KEYBOARD_EVIDENCE_2026-08-03.md). | While open, no later action dispatches. `Esc`, close, and timeout all produce safe deny/defer and restore the previous foreground application. Alt+Tab and Windows security keys remain available. Positive approval still requires an explicit bounded choice. |
| `GDA-HUD-005` | Step semantics | The surfaces mix different totals: Progress uses the Host tool-call budget while the card shows seven approval actions. The progress view cannot yet name the exact current Demo chapter from durable Host state. | A bounded immutable checklist defines six fixed Demo chapters and drives compact/expanded Progress projections. The pure `project_demo_workflow` mapper fail-closed maps fixed provider boundaries `0..18` to the six Host-owned chapters and now also covers the cancelled boundary. `DemoWorkflowProgress` connects it: the provider reports only an integer boundary, the durable `RunPhase` owns overall status, and the Demo Decision Card derives its breadcrumb from `WorkflowBreadcrumb.from_checklist` while the approval `n/7` count stays separate. Approval wait projects `NEEDS_INPUT`, durable success projects `READY` only at the terminal boundary, and failure, uncertainty, or cancellation never complete the interrupted chapter. The complete offline gate passed on 2026-08-01. `scripts/smoke_demo_workflow_progress.py` then passed three consecutive times on the real non-activating Win32 surface: the foreground never moved from `0x204a0`, the first open showed every chapter, and a provider boundary, approval wait, held terminal chapter, and durable `SUCCESS` each reached worker-owned pixels. It asserts no tool-call diagnostics and no approval `n/7` count leak into the workflow HUD. This is isolated live evidence for the projection surface only; it opens no Runner, MCP, provider, or application, so it is not Demo, application, or release evidence. | The UI clearly labels “workflow step” versus “approval n/7”, names the current fixed action without trusting provider prose, and defines how skipped, failed, verification, and terminal steps affect counts. |
| `GDA-HUD-006` | Progress HUD visual design | The passive progress window has only received a dark fill and accent stripe; its hierarchy, compactness, typography, current-action emphasis, and expand behavior have not been seen or accepted live. | The DPI-scaled compact summary now has a non-activating `SHOW/HIDE STEPS` affordance. Expanded state appends all six Host-owned rows with fixed status glyphs and labels; collapse restores compact geometry. Computer Use completed an expanded-to-compact-to-expanded round trip at the current DPI with no clipping or state loss. The bounded Demo now drives this surface instead of the generic `state_dir` poller, so it no longer shows tool-call budgets: `DemoWorkflowProgress` owns one worker thread for every open, repaint, pump, and close, the first open shows all six chapters, and an operator collapse survives later refreshes. A dedicated live smoke confirms the real window stays non-activating across every projected transition (see `GDA-HUD-005`). Operator collapse preservation remains deterministic-offline only, because toggling the live affordance needs synthesized input. Retained production evidence remains. | A live passive window remains non-activating and foreground-safe while clearly showing overall progress, current action/phase, application, and expandable sanitized detail. |
| `GDA-HUD-007` | Cross-surface visual system | Presence, Progress, and Decision Card initially lacked one shared hierarchy and approval-state vocabulary. | One fixed token contract now owns operator labels, glyphs, RGB roles, chrome, shared type tiers, and phase/approval vocabulary. Both Win32 backends consume it, and a test asserts that the two interactive surfaces resolve one palette. The bounded Demo surfaces do not animate, so no reduced-motion override is needed. High-contrast mode was not promoted and remains outside this bounded evidence claim. | The standard-theme bounded Demo uses shared typography, spacing, phase colors, and status vocabulary; approval transition is visually obvious. No high-contrast capability claim is made. |
| `GDA-HUD-008` | Approval-to-dispatch heartbeat | The post-approval heartbeat raced the MCP human-activity gate in the exploratory run: the card approved `PageDown`, but dispatch returned known `DENIED_BY_GATE`. | The bounded Demo now restores the captured foreground before making exactly one MCP action call. That call owns one bounded readiness sequence: three consecutive healthy idle samples, foreground allowlist verification, then at most one driver dispatch. The duplicate Host-side heartbeat was removed. Idle timeout, unavailable observation, foreground denial, E-stop, and user denial are returned as `rejected` with known `not_dispatched`; none is replayed. Deterministic offline tests cover streak reset, timeout, fail-closed observation, one-call/one-dispatch behavior, and result conversion. Repeated real Chrome/Word evidence remains. | One Host-configured, MCP-enforced readiness protocol covers card close, foreground restoration, idle stabilization, the foreground gate, and at most one dispatch. A denied gate causes no replay, and repeated real runs cross the boundary reliably without guessing a fixed delay. |
| `GDA-HUD-009` | Foreground and window composition | The current application must remain foreground while passive HUD surfaces stay visible and non-interactive; the card must restore that application after any exit. | Progress anchors to the foreground monitor's top-right work-area rail; Decision Card uses the same monitor's bottom-right rail and restores the captured foreground on every exit. Pure geometry covers 100%, 125%, and 150% DPI. `scripts/smoke_hud_composition.py` opened all three real surfaces twice on 2026-08-01: passive surfaces did not activate, the card alone took focus, painted Presence pixels covered neither companion surface, the card and Progress did not overlap, and safe close restored foreground. The complete retained Chrome-to-Word run supplies bounded application composition, while the isolated live matrix supplies multi-DPI card composition. This does not claim a complete Chrome-to-Word run at every display scale. | Bounded live and deterministic evidence prove passive foreground safety, Decision Card focus and restoration, surface separation, application composition, and multi-DPI geometry without promoting a universal composition claim. |
| `GDA-HUD-010` | Restart and cleanup | Fresh browser/document state is offline verified, but a failed or cancelled HUD run can leave launched Chrome/Word fixtures open. The next session needs an explicit cleanup/restart contract. | Cleanup is now a reusable exact-process component rather than a Demo-only process kill. It posts `WM_CLOSE` only to visible unowned top-level windows for each retained launch PID, observes all visible windows for that PID including owned dialogs, and treats verified window disappearance as completion even while an application process drains naturally. It force-terminates only when exact owned windows remain after the bounded close wait or a partial launch exposes no window; unavailable observation becomes explicit `handoff_required`. It never scans or terminates by executable name. The Demo uses the component from one `finally` and records fixture identity, close count, disposition, exit snapshot, and process-running snapshot. A live diagnostic caught force-termination-induced Word AutoRecover; after the generalized fix, two consecutive real fixture-cleanup smokes (`...091139-912478`, `...091235-478306`) each observed exactly two disposable windows, closed both as `windows_closed`, preserved the pre-existing Chrome window, and produced no recovery window on restart. | Start and end state are both declared. A failed/escaped run closes or clearly hands off its disposable windows, and the next run starts from the same pristine state without touching unrelated user windows. |
| `GDA-HUD-011` | Evidence and promotion | Retain the proportional evidence needed to close the bounded Demo without promoting it into a universal claim. | [The 150% DPI image matrix](../OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md), [100%/125% DPI acceptance](../OPERATOR_HUD_DPI_EVIDENCE_2026-08-03.md), [physical Alt+Tab acceptance](../OPERATOR_HUD_KEYBOARD_EVIDENCE_2026-08-03.md), and [post-fix complete run](../OPERATOR_HUD_DEMO_EVIDENCE_2026-08-03.md) are retained. The run reached durable `SUCCESS` with 17 tool calls, seven approved effects, zero tool failures, 247 painted Presence samples, and exact-process cleanup. All handoff-listed operator-only evidence is complete. | Each issue has proportional offline tests, a dedicated live smoke where visual behavior matters, one complete retained Chrome-to-Word run, documented DPI/keyboard evidence, full validation gate, and explicit statement that the result remains bounded rather than universal GUI evidence. |

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
The clean [release preflight](../RELEASE.md) passed with the same start and
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

## Completed slice: `GDA-CORE-008`

The MCP action recorder now accepts the structured `Result` and one explicit
route-provenance fact. It calls `HumanActivity.note_agent_action()` only when a
known native mouse/keyboard route succeeds. A semantic ref click that observes
concurrent human input therefore leaves the new tick authoritative and the next
coordinate click returns `HUMAN_ACTIVE` without a second driver call. Five
native-success routes retain self-input suppression; activation, semantic ref
typing, invalid/no-op motion, and driver failure record no tick. Audit shape,
typed-text redaction, final authority rechecks, and output strings are unchanged.
The platform's latest-input tick still cannot identify input interleaved during
one successful native call; that larger provenance limit is explicit and is not
silently claimed as solved.

## Completed slice: `GDA-CORE-009`

The ordinary Runner now preflights one mandatory verification lane after an
action request passes ordinary authority checks but before creating approval.
It checks remaining model and input-token capacity, runs the canonical reducer
against an immutable same-identity `ALLOW` plus dispatched-result projection,
then checks the remaining observation-call slot. Fixed-priority insufficiency
appends only a rejected/not-dispatched `BUDGET_EXHAUSTED` result to the real
ledger; the projection grants no authority and never mutates or persists.
Regression coverage freezes the exact eight-event failure state, absence of
action approval/continuation/MCP authority, the `4/4/9/3` complete boundary,
and the `3/3/9/3` observation-only lane so final-response capacity is not
silently over-reserved.

## Completed slice: `GDA-CORE-010`

The approval wait no longer grants a stale lease over MCP facts. A valid
correlated `ALLOW` remains in the canonical ledger, but after the
DENY/REOBSERVE/DEFER branches the Runner first validates the original grounding
against `desktop.generation`, then checks required baselines against live child
evidence. Drift records fixed `MCP_GENERATION_CHANGED` or
`SAFETY_BASELINE_UNSATISFIED` plus a rejected/not-dispatched `POLICY_DENIED`
result. The prior verified observation and `ready` state remain intact;
side-effect budget, action continuation, and MCP authority remain zero.
Regression coverage freezes ref/window/screenshot generation drift, typed-text
baseline loss, the exact nine-event audited-ALLOW shape, terminal recovery, and
an unchanged-authority successful action/re-observation path.

## Completed slice: `GDA-CORE-011`

The final provider tool set now adds continuation compatibility after caller,
privacy, and live MCP safety-baseline filtering. Sensitive continuation omits
`type`, so the same persistence contract governs request construction and the
versioned advertised scope. The existing whole-turn membership boundary rejects
a returned typed-text call before model/tool budget, provider completion,
approval, side-effect, or MCP, and raw typed text never enters the run record or
continuation artifact. Regression coverage freezes the provider-visible and
persisted scope, provider-neutral atomic rejection, and unchanged successful
typing when continuation is disabled and the required baseline is live.

## Completed slice: `GDA-CORE-012`

The ordinary Runner now derives the reviewed ToolSpecs for the complete returned
turn after advertised-name and canonical-schema checks. If more than one call is
present and any reviewed effect is a side effect, fixed
`PROVIDER_SIDE_EFFECT_TURN_NOT_SERIAL` rejects the turn before privacy,
model/tool budget, provider completion, policy, approval, action continuation,
or MCP. Continuation evidence stops at provider `prepared` and
`dispatch_intent`; no returned-turn ledger event is accepted. Regression tests
freeze action/action, observation/action, and action/observation ordering, prior
verified-observation preservation, sequential pure observations, and the exact
single-action verification path. The reviewed E2 case and regenerated canonical
manifest pin a user-task-only trace, zero dispatch, and zero safety escapes.

## Completed slice: `GDA-CORE-013`

The MCP server now captures one stable human-input readiness tick before the
initial foreground gate. Immediately before every safe-local native action it
rechecks e-stop, rechecks foreground where required, and double-samples the
current tick around a non-waiting idle-age observation. Missing evidence,
in-check drift, or any tick newer than readiness returns fixed `HUMAN_ACTIVE`
through the redacted audit path with zero native action calls. The six action
boundaries, activation's intentional foreground exception, and full-control's
intentional human-yield bypass are regression tested.

An affirmative dangerous-click confirmation may capture its exact current tick
and pass it only into that click's final decision. The capture is not stored,
never calls or changes `note_agent_action`, cannot be reused by a later call,
and cannot excuse unavailable idle evidence or any newer tick. The documented
Windows tick-granularity limit remains explicit; same-millisecond physical
events that do not change the platform tick cannot be distinguished.

## Completed slice: `GDA-CORE-014`

The shared Runner now catches continuation failures only around the two tool-WAL
writes that precede its sole MCP call. Either failure appends a same-identity and
same-name `REJECTED/not_dispatched` result with reviewed fixed code
`CONTINUATION_WRITE_FAILED`, then raises `RunFailure` with that updated canonical
state. The outer recorder can therefore write a terminal `FAILED` checkpoint
without event-log rewind. There is no retry, replay, unknown-outcome inference,
or new dispatch path.

The observation/action x prepared/intent matrix freezes four and nine ledger
events, checkpoint sequences `5/6` and `11/12`, budgets `1/1/1/0` and
`2/2/2/1`, continuation cleanup, and zero target MCP calls. Approved actions
retain their correlated `ALLOW` and consumed side-effect budget as audit facts,
not authority. Normal WAL completion, provider-intent failure, post-dispatch
unknown outcome, result-carrying cancellation, and continuation completion
failure remain unchanged and independently tested.

## Completed slice: `GDA-CORE-015`

The ref table now binds each newly minted ref to its first observation scope
token. Later snapshot/find calls can refresh the same native Node but cannot
change that relocation domain. A stale semantic action queries that original
scope at most once, selects a same-role/name candidate by nearest-center
tie-break, and retries using the complete fresh Node rather than stale patterns.
No ref path can degrade to a coordinate action.

One `_rebind` path owns every accepted native change. It rejects a candidate
already owned by another ref without candidate action or mutation, removes the
old reverse entry only when it still points to this ref, and updates cached Node,
forward native id, and reverse ownership together. Tests freeze explicit A/B
scope separation with and without a candidate, fresh-Node semantics, stable ref
reuse after old-to-new relocation, new ref assignment when the old handle
reappears, collision failure, same-native cross-scope scope preservation,
unknown-ref zero I/O, and `NOT_INVOKABLE` zero coordinate fallback.

## Completed slice: `GDA-CORE-016`

The ref action boundary now distinguishes stable explicit window-id scopes from
dynamic selectors. Once the cached native handle reports `STALE_ELEMENT`, a ref
whose first scope token is exactly `foreground` or `all` returns a fixed stale
result before `_relocate`, so it performs zero additional `get_tree` calls,
candidate semantic actions, coordinate actions, or node/native/reverse/scope-map
mutations. A fresh observation is required.

Explicit numeric window-id refs retain the CORE-015 control path: one bounded
role/name plus nearest-center query, complete fresh-Node retry, atomic bijective
rebind, and reverse-owner conflict failure before candidate action. Two new
dynamic-scope regressions plus the existing explicit-window success and
collision controls pass. Driver interfaces and contract `1.0.0` are unchanged.

## Completed slice: `GDA-CORE-017`

Accepted ADR 009 defines one non-nested, server-owned native-action call scope.
The Windows driver checkpoints e-stop, applicable foreground, and safe-local
human authority before every driver-controlled native mutation. The scope marks
the dispatch attempt before entering an opaque native API, so loss before any
attempt remains rejected/not-dispatched while loss after an attempt is reported
as unknown/dispatched. Later mutations stop, the Agent terminalizes the run, and
continuation recovery never replays the action.

Pointer, mouse, key, literal Unicode typing, UIA, and activation paths are
covered. Cleanup can release a key or mouse button held by the call and detach
only a thread-input pair attached by the call; it never claims to roll back a
native effect. Successful paths preserve optional pacing and feedback, exact
call-local dangerous-confirmation input attribution, the activation foreground
exception, and the full-control local foreground/human bypass without bypassing
e-stop. Driver contract `1.0.0` and the 13-tool surface are unchanged.

The complete offline gate passed with `1719 passed, 8 skipped`, Ruff, mypy over
121 source files, docs consistency for all 13 reviewed tools, and diff check.
Three independent code, certainty, and documentation reviews found no remaining
P1/P2/P3 issue. This is deterministic offline/fake-native evidence only; it does
not promote provider, desktop, application, or release evidence.

## Completed slice: `GDA-CORE-018`

The Runner now treats the exact side-effect
`REJECTED / NOT_DISPATCHED / HUMAN_ACTIVE` tuple as evidence that current
human-idle authority is unavailable or that local input may have changed the
desktop since Host grounding was established. Immediately after recording that
result and before lifecycle, checkpoint, or continuation completion, it clears
`verified_observation_epoch`, sets
`REQUIRES_REOBSERVATION`, and invalidates `GroundingState`. The existing presence
release remains unchanged.

The next side effect therefore fails with fixed `REOBSERVATION_REQUIRED` before
approval, side-effect budget, action continuation, or MCP dispatch. An unrelated
observation cannot revive refs minted before the human yield; a fresh successful
snapshot mints current grounding and restores normal action plus mandatory
verification. Recovery from the completed continuation plans only a new
`ui_snapshot` and never replays the original action. The exact-tuple guard leaves
unrelated rejected results unchanged and cannot downgrade an
`UNKNOWN_OUTCOME / DISPATCHED` result carrying the same code.

The complete offline gate passed with `1725 passed, 8 skipped`, Ruff, mypy over
121 source files, docs consistency for all 13 reviewed tools, and diff check.
Independent code, certainty, and scope reviews found no remaining P1/P2/P3
issue. This is deterministic offline/fake-native evidence only; it does not
promote provider, desktop, application, or release evidence.

Commit `f613056` merged through PR #249 as `1adce11` after the GitHub Python
3.11-3.13 and wheel matrix passed. Both feature-branch copies were removed.

## Completed slice: `GDA-CORE-019`

The Runner now treats the exact side-effect
`REJECTED / NOT_DISPATCHED / DENIED_BY_GATE` tuple as proof that the live
foreground gate no longer grants the authority checked for the attempted
action. Immediately after recording that result and before lifecycle,
checkpoint, or continuation completion, it clears
`verified_observation_epoch`, sets `REQUIRES_REOBSERVATION`, and invalidates
`GroundingState`. No presence lifecycle behavior is added for gate denial.

The next ref-based or screenshot-coordinate side effect therefore fails with
fixed `REOBSERVATION_REQUIRED` before a second approval, side-effect budget,
action continuation, or MCP dispatch. A successful unrelated observation cannot
revive the old ref set or screenshot bounds, while a fresh successful snapshot
mints current grounding and restores normal action plus mandatory verification.
Recovery from the completed continuation plans only a new `ui_snapshot` and
never replays the denied action. Exact `HUMAN_ACTIVE` behavior remains intact;
`DENIED_BY_USER`, observation-shaped gate denial, and
`UNKNOWN_OUTCOME / DISPATCHED` controls retain their prior behavior.

The complete offline gate passed with `1733 passed, 8 skipped`, Ruff, mypy over
121 source files, docs consistency for all 13 reviewed tools, and diff check.
Independent code, certainty, and contract reviews found one overstrong
`HUMAN_ACTIVE` documentation claim, which was corrected and independently
rechecked; no P1/P2/P3 issue remains. This is deterministic offline/fake-native
evidence only; it does not promote provider, desktop, application, or release
evidence.

Commit `bf0cbec` merged through PR #251 as `dfc5f9e` after the GitHub Python
3.11-3.13 and wheel matrix passed. Both feature-branch copies were removed.

## Completed slice: `GDA-CORE-020`

The server-owned `NativeActionBoundary` now retains monotonic attempt evidence
for the whole native action call. `complete_action` promotes an unsuccessful
Driver `Result` after any attempt, while the call scope replaces an ordinary
post-attempt exception, with one fixed `NativeOutcomeUnknown` control-flow
exception. The server exposes only
`ERROR NATIVE_OUTCOME_UNKNOWN: native action outcome unknown after dispatch`;
the original Driver message, exception, typed text, and native details do not
enter the MCP result or audit record.

The Agent reviews the distinct new code as `UNKNOWN_OUTCOME / DISPATCHED` and
uses its existing unknown path to invalidate the MCP generation, terminalize the
Runner, persist exact continuation v6 `dispatch=dispatched,next_step=stop`, and
prevent verification, continuation, recovery dispatch, or replay. Authority
loss remains `NATIVE_AUTHORITY_LOST`. Zero-attempt validation, stale refs,
missing patterns, bad arguments, ordinary Driver failures, and the synthetic E2
`DRIVER_ERROR` control retain their prior certainty.

Deterministic regressions cover all current Windows action families, actual
WindowsDriver UIA effect-then-raise and positive-partial `SendInput` through the
production server boundary, exact pointer/key/button/thread-detach unwind,
fixed audit redaction, generation invalidation, Runner terminal state, and
continuation/recovery no-replay. The complete offline gate passed with
`1763 passed, 8 skipped`, Ruff, mypy over 121 source files, docs consistency for
all 13 reviewed tools, and diff check. Independent code, certainty, test, and
contract reviews found no P1/P2/P3 issue. This is offline fake-native evidence
only; it does not promote provider, real-desktop, application, or release
evidence.

Commit `257c42d` merged through PR #253 as `b53bbe2` after the GitHub Python
3.11-3.13 and wheel matrix passed. Both feature-branch copies were removed.

## Completed slice: `GDA-CORE-021`

Recovery now derives one ledger-proven semantic topology before classifying an
operation. The persisted `boundary.next_step` is checked only against that
topology; it no longer selects a budget dimension. The final reconstructed
action owns its actual model/input or tool-call budget, including the distinction
between a newly synthesized observation and a singleton prepared observation
whose call is already charged.

The executor repeats the topology and action-budget gate before provider restore
or desktop dispatch. `LockedRecoveryPersistence` rereads the durable checkpoint
and continuation under the run lock, replans the exact action, compares it with
the reviewed plan, and rechecks its budget before writing intent. A prepared
observation is reused without a duplicate ledger event or budget charge;
mandatory recovery observation still uses the fixed Host-generated identity.

Formal regressions cover digest-valid next-step swaps across completed provider,
observation, and side-effect boundaries; exhausted model-turn, input-token, and
tool-call dimensions; prepared-call reuse at the exact tool limit; forged
post-side-effect observation lineage; and pure multi-observation dispatch-intent
and unknown-result crash states. Invalid artifacts leave checkpoint and
continuation bytes unchanged and grant zero provider, desktop, or persistence
authority. The complete offline gate passed with `1780 passed, 8 skipped`, Ruff,
mypy over 121 source files, docs consistency for all 13 reviewed tools, and diff
check. Independent review found no remaining P1/P2/P3 issue. This does not
promote provider, real-desktop, application, or release evidence.

Continuation remains v6: no fields, enums, serialization shape, public tools,
Runner/MCP/Driver dispatch ownership, Driver Contract `1.0.0`, retry semantics,
Demo, Full Cycle, HUD, platform, hierarchical-control, or Multi-Agent scope
changed.

Commit `0e83c6e` merged through PR #255 as `5d605e7` after the GitHub Python
3.11-3.13 and wheel matrix passed. Both feature-branch copies were removed.

## Completed slice: `GDA-CORE-022`

Recovery now validates every canonical model turn, issued call, correlated
result, and terminal transition across the complete continuation ledger. The
fold reconstructs exact budgets, observation epoch, verified epoch, and recovery
status; the checkpoint must match those counters and may only retain or tighten
the folded certainty. A completed final provider response therefore succeeds
locally only when both sources are `ready`. Outstanding debt returns fixed
`START_NEW_RUN/VERIFICATION_REQUIRED`, terminal unknown returns
`HUMAN_REOBSERVE/UNKNOWN_OUTCOME`, and synthetic recovery completion retains its
existing stopped/new-run boundary.

The fold also replays the Runner's provider-turn invariants. Advertised calls
cannot be abandoned before a later turn, and a historical multi-call turn that
contains a side effect is invalid before a sibling observation can clear debt.
The exact current completed-provider tail remains an untrusted input record and
still terminalizes one or more action requests together with zero dispatch;
complete pure-observation histories remain valid. A Host-synthesized mandatory
intent immediately establishes debt, while checkpoint-backed Host-only
verified-epoch clears remain conservative through later unknown or stopped
outcomes.

`LockedRecoveryPersistence` preserves the current status and observation facts
through intent and completion, changing them only for the reviewed ordinary
success, mandatory, unknown, and stopped transitions. The trace success
finalizer independently requires `recovery_status=ready` before writing
`SUCCESS` or deleting continuation state. Continuation remains v6 and no public
field, enum, serialization shape, provider adapter, dispatch path, tool, Driver
Contract `1.0.0`, frozen E2 fixture, Demo/HUD, or Full Cycle lane changed.

The final offline gate passed with `1813 passed, 8 skipped`, Ruff, mypy over 121
source files, docs consistency for all 13 reviewed tools, and diff check. Two
independent final reviews found no remaining P1/P2/P3. This is offline
state-machine and persistence evidence only; it does not promote provider,
real-desktop, application, or release evidence.

Commit `dc59252` merged through PR #257 as `5c0ab09` after the GitHub Python
3.11-3.13 and wheel matrix passed. Both feature-branch copies were removed.

## Completed slice: `GDA-CORE-023`

The MCP now retains activation authority only from its own successful
model-visible `list_windows` tool. One complete structured result produces both
the unchanged text rows and a locked all-or-nothing binding table. Each unique,
non-empty id binds only when its direct owner has a positive integer PID and
non-empty exact executable name; malformed or duplicate ids remain visible but
cannot authorize activation. Empty successful lists clear the table, while
failed and internal screenshot/OCR/capture enumerations cannot change it.

`activate_window` captures the exact binding object before its potentially
waiting guard, so a concurrent fresh list cannot silently retarget an in-flight
call. A live probe requires that captured generation plus exactly one matching
window and owner. It runs before the final non-waiting e-stop/human check at
every native mutation, preserving ADR-009's volatile-authority ordering, and it
runs once after the Driver returns so drift during the final native attempt
cannot become success. Compare-and-delete invalidation cannot erase a newer
binding.

Pre-attempt owner loss returns fixed redacted `NATIVE_AUTHORITY_LOST` and maps
to `REJECTED / NOT_DISPATCHED`; any prior native attempt retains fixed
`UNKNOWN_OUTCOME / DISPATCHED`, later target mutation stops, and the Runner never
replays. A fresh model-visible list is the only replacement-binding path. The
intentional activation foreground exception remains, and full-control mode does
not bypass target identity.

The deterministic matrix covers stable identity; no observation; empty, failed,
and internal lists; invalid and duplicate owners; disappeared targets;
PID-only/name-only drift; pre-first, intermediate, and final-attempt drift;
probe failure; exact fixed audit/results; e-stop ordering; and concurrent old/new
binding behavior. The final offline gate passed with `1832 passed, 8 skipped`,
Ruff, mypy over 121 source files, docs consistency for all 13 reviewed tools,
and diff check. Two independent final reviews found no remaining P1/P2/P3. This
does not establish an atomic Windows identity lease or distinguish extreme
same-id/PID/name reuse, and it adds no real-desktop, provider, application, or
release evidence.

Commit `9edc585` merged through PR #259 as `1c5b2a0` after the GitHub Python
3.11-3.13 and wheel matrix passed. Both feature-branch copies were removed.

## Per-item decision chronology

| Date | Decision |
| --- | --- |
| 2026-08-04 | A bounded audit selected `GDA-CORE-004` next: the Host must enforce the exact final tool set advertised for each provider turn before continuation persistence, approval, or MCP dispatch. |
| 2026-08-04 | `GDA-CORE-004` merged through PR #233 as `5c9c379`; `GDA-CORE-005` is now the sole active core Runtime item. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-005` next: read-only recovery must revalidate the current MCP generation's required safety baselines before persisting intent or dispatching an observation. |
| 2026-08-04 | `GDA-CORE-005` merged through PR #234 as `ea2e063`; `GDA-CORE-006` is now the sole active core Runtime item. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-006` next: reviewed schema and canonical-argument validation must be whole-turn atomic so no valid prefix executes before a malformed sibling fails. |
| 2026-08-04 | `GDA-CORE-006` merged through PR #235 as `33b0d73`; all four GitHub checks passed, and `GDA-CORE-007` is now the sole active core Runtime item on `codex/core-runtime-recovery-tool-scope`. |
| 2026-08-04 | `GDA-CORE-007` is complete locally and independently reviewed: strict continuation v6 preserves and narrows original Host tool authority across recovery, with old/corrupt evidence and every tested widening path failing closed. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-008` ahead of verification-capacity work: only a known-successful native-input route may claim the current input tick as agent-generated; semantic, activation, invalid, no-op, and failed actions must preserve concurrent human authority. |
| 2026-08-04 | `GDA-CORE-007` merged through PR #236 as `e726052`; all four GitHub checks passed, and `GDA-CORE-008` is now the sole active core Runtime item on `codex/core-runtime-human-yield-attribution`. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-009` next: the Runner must reserve model, input-token, context, and tool-call capacity for mandatory post-action verification before approval or side-effect dispatch. |
| 2026-08-04 | `GDA-CORE-008` merged through PR #237 as `ab4bb3a`; all four GitHub checks passed, and `GDA-CORE-009` is now the sole active core Runtime item on `codex/core-runtime-verification-capacity`. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-010` next: after recording a valid `ALLOW`, the Runner must revalidate live MCP generation and required safety baselines before side-effect budget, action continuation, or MCP dispatch. |
| 2026-08-04 | `GDA-CORE-009` merged through PR #238 as `5f9c9de`; all four GitHub checks passed, and `GDA-CORE-010` is now the sole active core Runtime item on `codex/core-runtime-post-approval-authority`. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-011` next: when continuation is enabled, the Host must not advertise `type`, whose raw argument cannot satisfy strict continuation v6; continuation-disabled baseline-satisfied behavior remains unchanged. |
| 2026-08-04 | `GDA-CORE-010` merged through PR #239 as `0b58044`; all four GitHub checks passed, and `GDA-CORE-011` is now the sole active core Runtime item on `codex/core-runtime-continuation-tool-compatibility`. |
| 2026-08-04 | `GDA-CORE-011` is complete locally: sensitive continuation now removes `type` from the provider-visible and persisted Host scope, attempted typed-text returns fail before budget or authority, and the strict raw-text prohibition remains unchanged. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-012` next: every side-effect-bearing provider turn must contain exactly one call so an untrusted sibling cannot strand a known-dispatched action without the mandatory post-action observation reserved by `GDA-CORE-009`. |
| 2026-08-04 | `GDA-CORE-011` merged through PR #240 as `2c6b9bb`; all four GitHub checks passed, and `GDA-CORE-012` is now the sole active core Runtime item on `codex/core-runtime-side-effect-turn-atomicity`. |
| 2026-08-04 | `GDA-CORE-012` is complete locally: reviewed side-effect turns are single-call before any returned-turn consumption or authority; pure observations and exact single-action verification remain intact, and the reviewed E2 fixture/manifest pins zero dispatch. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-013` next: safe-local MCP actions must recheck fresh human input at the final driver boundary, with only a call-scoped exact confirmation tick permitted for the dangerous click that captured it. |
| 2026-08-04 | `GDA-CORE-012` merged through PR #241 as `059734d`; all four GitHub checks passed, and `GDA-CORE-013` is now the sole active core Runtime item on `codex/core-runtime-final-human-authority`. |
| 2026-08-04 | `GDA-CORE-013` is complete locally and independently reviewed: stable readiness plus a final double-sampled human-input decision guards all safe-local native actions; the dangerous-confirmation tick is exact, call-local, non-persisted, and cannot excuse drift or unavailable evidence. |
| 2026-08-04 | A bounded audit selected `GDA-CORE-014` next: pre-dispatch tool continuation write failures must retain certain not-dispatched evidence and terminalize from the latest ledger, without catching post-dispatch completion failures or changing the sole MCP dispatch path. |
| 2026-08-04 | `GDA-CORE-013` merged through PR #242 as `48ef716`; all four GitHub checks passed. `GDA-CORE-014` is now the sole active item on `codex/core-runtime-pre-dispatch-continuation-failure`. |
| 2026-08-05 | `GDA-CORE-014` is complete locally and independently reviewed: observation and approved-action tool-WAL failures at both pre-dispatch stages retain exact known-not-dispatched results and terminalize from the latest ledger without changing post-dispatch semantics. |
| 2026-08-05 | A bounded audit selected `GDA-CORE-015` next: each ref must retain its first observation scope for stale relocation, and successful relocation must update node/native/reverse bindings together while reverse-map conflicts fail closed. |
| 2026-08-05 | `GDA-CORE-014` merged through PR #243 as `c451526`; all four GitHub checks passed. `GDA-CORE-015` is now the sole active item on `codex/core-runtime-ref-scope-binding`. |
| 2026-08-05 | `GDA-CORE-015` is complete locally and independently reviewed: explicit-scope relocation is set-once per ref, full-Node semantic retry and bijective rebinding are enforced, and foreign/conflicting candidates receive zero authority with no coordinate fallback. |
| 2026-08-05 | A bounded audit selected `GDA-CORE-016` next: stale refs minted from dynamic `foreground` or `all` must fail without relocation; explicit window-id refs retain one bounded retry. The separately reproduced driver-pacing authority window remains queued for its own ADR and slice. |
| 2026-08-05 | `GDA-CORE-015` merged through PR #244 as `16ef9d6`; `GDA-CORE-016` became the sole active item on `codex/core-runtime-dynamic-ref-relocation`. |
| 2026-08-05 | `GDA-CORE-016` is complete locally and independently reviewed: stale dynamic-scope refs fail before any relocation query, candidate action, coordinate fallback, or map mutation, while explicit numeric window-id relocation and Driver contract `1.0.0` remain intact. |
| 2026-08-05 | A bounded audit selected ADR-first `GDA-CORE-017` next: driver-controlled pacing must not outlive native-action authority, and any authority loss after partial native mutation must retain unknown/dispatched certainty with zero replay. |
| 2026-08-05 | `GDA-CORE-016` merged through PR #245 as `6ea1b1f`; all four GitHub checks passed, and ADR-first `GDA-CORE-017` is the exact next core Runtime item. |
| 2026-08-05 | A bounded audit selected `GDA-CORE-018` next: side-effect `HUMAN_ACTIVE` must invalidate the prior verified observation and Host grounding before continuation persistence, forcing fresh observation before later side-effect authority. |
| 2026-08-05 | `GDA-CORE-017` merged through PR #247 as `212081a`; all four GitHub checks passed, both feature-branch copies were cleaned up, and `GDA-CORE-018` is the exact next core Runtime item. |
| 2026-08-05 | `GDA-CORE-018` is complete locally and independently reviewed: the exact side-effect `REJECTED / NOT_DISPATCHED / HUMAN_ACTIVE` tuple invalidates verified observation and Host grounding before continuation completion, while unknown certainty and unrelated rejections remain unchanged. |
| 2026-08-05 | A bounded audit selected `GDA-CORE-019` next: a side-effect `REJECTED / NOT_DISPATCHED / DENIED_BY_GATE` result must invalidate prior verified observation and Host grounding so restored foreground eligibility cannot revive stale action authority. |
| 2026-08-05 | `GDA-CORE-018` merged through PR #249 as `1adce11`; all four GitHub checks passed, both feature-branch copies were cleaned up, and `GDA-CORE-019` is the exact next core Runtime item. |
| 2026-08-05 | `GDA-CORE-019` is complete locally and independently reviewed: the exact side-effect `REJECTED / NOT_DISPATCHED / DENIED_BY_GATE` tuple invalidates verified observation and all Host grounding before continuation completion, while every other result tuple retains its prior behavior. |
| 2026-08-05 | A bounded full-server audit selected `GDA-CORE-020` next under accepted ADR 009: any Windows action failure after one or more recorded native dispatch attempts must retain fixed redacted `UNKNOWN_OUTCOME / DISPATCHED` certainty; zero-attempt failures remain unchanged. |
| 2026-08-05 | `GDA-CORE-019` merged through PR #251 as `dfc5f9e`; all four GitHub checks passed, both feature-branch copies were cleaned up, and `GDA-CORE-020` is the exact next core Runtime item. |
| 2026-08-05 | `GDA-CORE-020` is complete locally and independently reviewed: post-attempt Windows action failure or ordinary exception becomes fixed redacted `NATIVE_OUTCOME_UNKNOWN / UNKNOWN_OUTCOME / DISPATCHED`, while authority loss, zero-attempt failures, Driver Contract `1.0.0`, and side-effect no-replay remain unchanged. |
| 2026-08-05 | A bounded formal-persistence audit selected `GDA-CORE-021` next: recovery must semantically bind continuation next steps to reconstructed actions and enforce that action's model/input or tool budget before any intent persistence or external call. |
| 2026-08-05 | `GDA-CORE-020` merged through PR #253 as `b53bbe2`; all four GitHub checks passed, both feature-branch copies were cleaned up, and `GDA-CORE-021` is the exact next core Runtime item. |
| 2026-08-05 | `GDA-CORE-021` is complete locally and independently reviewed: full topology validation makes `next_step` non-authoritative, the final reconstructed action owns its budget, and executor plus locked persistence recheck before intent or external work while valid prepared observations are not double charged. |
| 2026-08-05 | A bounded formal-persistence audit selected `GDA-CORE-022` next: completed-provider recovery finalization must preserve a prior mandatory-verification obligation and terminal unknown certainty by folding the complete ledger and binding it to the checkpoint. |
| 2026-08-05 | `GDA-CORE-021` merged through PR #255 as `5d605e7`; all four GitHub checks passed, both feature-branch copies were cleaned up, and `GDA-CORE-022` is the exact next core Runtime item. |
| 2026-08-06 | `GDA-CORE-022` is complete locally and independently reviewed: complete-ledger folding plus checkpoint, locked-persistence, and trace-finalizer gates preserve verification debt, Host-only stricter state, unknown certainty, and stopped recovery without changing continuation v6 or any public contract. |
| 2026-08-06 | `GDA-CORE-022` merged through PR #257 as `5c0ab09`; all four GitHub checks passed, both feature-branch copies were cleaned up, and `GDA-CORE-023` is the exact next core Runtime item. |
| 2026-08-06 | `GDA-CORE-023` is complete locally and independently reviewed: MCP-owned list/owner binding plus per-mutation and post-return probes reject missing, invalid, duplicate, disappeared, drifted, and concurrently replaced activation targets with exact pre/post dispatch certainty while retaining the foreground exception and Driver contract `1.0.0`. |
| 2026-08-06 | A bounded configuration/redaction audit selected `GDA-CORE-024` next: comma-list parsing must trim each configured title and allowlist item so ordinary spaced syntax cannot silently bypass sensitive-window blackout or change process authorization semantics. |
| 2026-08-06 | `GDA-CORE-023` merged through PR #259 as `1c5b2a0`; all four GitHub checks passed, both feature-branch copies were cleaned up, and `GDA-CORE-024` is the exact next core Runtime item. |
| 2026-08-06 | `GDA-CORE-024` is complete locally and independently reviewed: one shared parser trim fixes ordinary spaced comma-list syntax across screenshot, cropped capture, OCR, and allowlist configuration while preserving defaults and every public/runtime boundary. |
| 2026-08-06 | A bounded functional audit selected `GDA-CORE-025` next: Windows `find()` must filter during the full bounded UIA traversal so targets after the ordinary 200-node snapshot cap remain discoverable, while matching results retain their own cap and truncation count. |
| 2026-08-06 | `GDA-CORE-024` merged through PR #261 as `b9a7fbe`; all four GitHub checks passed, both feature-branch copies were removed, and work continued directly into `GDA-CORE-025`. |
| 2026-08-06 | `GDA-CORE-025` is complete locally and independently reviewed: Windows `find()` now filters the full bounded UIA traversal before matching-only de-duplication, cap, truncation, and cache insertion, so a position-201 target is discoverable without widening any public contract. |
| 2026-08-06 | A bounded functional audit selected `GDA-CORE-026` next: Windows `document_text` must use bounded UTF-16-aware lookahead and mark a partially clipped TextPattern range incomplete and truncated without falsely counting a whole omitted block. |
| 2026-08-06 | `GDA-CORE-025` merged through PR #262 as `0b43442`; all four GitHub checks passed, both feature-branch copies were removed, and work continued directly into `GDA-CORE-026`. |
| 2026-08-06 | `GDA-CORE-026` is complete locally and independently reviewed: bounded UTF-16 lookahead now distinguishes exact-cap from partial clipping, preserves the retained Python-character prefix and digest, and reports overflow or UIA read failure as incomplete without counting a wholly omitted block. |
| 2026-08-06 | A bounded functional audit selected `GDA-CORE-027` next: Chromium `find()` must reuse the existing optional lazy-UIA warmup so a first frame-only traversal does not become a false empty query result. |
| 2026-08-06 | `GDA-CORE-026` merged through PR #263 as `95bd16a`; all four GitHub checks passed, both feature-branch copies were removed, and work continued directly into `GDA-CORE-027`. |
| 2026-08-06 | `GDA-CORE-027` is complete locally and independently reviewed: Chromium snapshot and find now share the existing optional disposable UIA warmup while the final query, matching-only cache, refs, and zero-delay one-read behavior remain unchanged. |
| 2026-08-06 | A bounded functional audit selected `GDA-CORE-028` next: explicit-window stale-ref relocation must use the full bounded matching traversal so a target originally found after the ordinary 200-node snapshot cap can bind its fresh native id. |
| 2026-08-06 | `GDA-CORE-027` merged through PR #264 as `ee4aebf`; all four GitHub checks passed, both feature-branch copies were removed, and work continued directly into `GDA-CORE-028`. |
| 2026-08-06 | `GDA-CORE-028` is complete locally: explicit-window relocation now uses a role-bounded full matching traversal and existing browser warmup, so an unnamed position-201 target can bind and invoke its fresh native id while every existing exact-match/rebind rule remains fixed. |
| 2026-08-06 | A bounded functional audit selected `GDA-CORE-029` as the future resume point: Windows capability discovery must advertise the already implemented `scroll` and `drag` primitives with one metadata regression and no safety matrix. |
| 2026-08-06 | `GDA-PRODUCT-001` is complete locally: a clean wheel now reaches generated valid configuration and dry-run through the canonical CLI, while public `ask` adds a direct-answer document-aware path through existing Planner/Runner/MCP boundaries. `GDA-PRODUCT-002` is the exact post-merge next batch. |
| 2026-08-06 | `GDA-PRODUCT-001` merged through PR #266 as `3c7aa48` after all four GitHub checks passed; both branch copies were removed and work continued directly into the single coherent `GDA-PRODUCT-002` readiness/error-UX batch. |
| 2026-08-06 | `GDA-PRODUCT-002` is complete locally: installed Runtime doctor, actionable dual-provider setup failures, truthful 15-primitive Windows Driver metadata, and a clean-wheel two-provider exact 13-tool handshake passed without a provider request or MCP tool call. `GDA-PRODUCT-003` is the exact post-merge next batch. |
| 2026-08-06 | `GDA-PRODUCT-002` merged through PR #267 as `d94d5f9` after all four GitHub checks passed; both branch copies were removed and work continued directly into `GDA-PRODUCT-003` under an explicit `NOT RUN` exact-candidate Desktop Ask evidence plan. |
| 2026-08-06 | `GDA-PRODUCT-003` merged through PR #268 as `5eb9182` after all four GitHub checks passed; comments, reviews, unresolved threads, and conflicts were clear, both feature-branch copies were removed, and work continued directly into `GDA-PRODUCT-004`. |
| 2026-08-07 | `GDA-PRODUCT-004` merged through PR #269 as `0275f25` after all four GitHub checks passed; reviews, comments, unresolved threads, and conflicts were clear, both feature-branch copies were removed, and user-owned `AGENTS.md` / `CLAUDE.md` changes remained byte-identical. Work stopped before `GDA-PRODUCT-005` as requested. |
| 2026-07-28 | New product features are frozen until the bridge and baseline handoff close. |
| 2026-07-28 | Lane A manifest/export v1 is implemented; the next code task is the external offline consumer, not more Runtime capability. |
| 2026-07-28 | Clean release preflight passed for the producer candidate later squash-merged as `8ace897` (recorded at the time as pre-merge candidate `45bee82`, which is now unreachable); Runtime remains feature-frozen while the external consumer is completed. |
| 2026-07-30 | Operator HUD polish was paused after a failed live review. Eleven issues are classified under `GDA-DEMO-003`; they may be resumed one bounded session at a time without displacing the Full Cycle resume point. |
| 2026-08-01 | `GDA-FC-002` is complete; the consumer contract is owned and gated by `reliable-agent-model-lifecycle`. `GDA-FC-004` becomes the single active item. |
| 2026-08-02 | `GDA-FC-004` completed locally at branch-reachable Runtime commit `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`; clean release preflight and the matching consumer freeze record passed without changing Lane A contracts or fixture provenance. |
| 2026-08-04 | `GDA-CORE-001` removed the implementation's forbidden ref-to-coordinate fallback and restored alignment with accepted ADR-002; explicit coordinate clicks remain a separate caller-authorized path. |
| 2026-08-04 | `GDA-CORE-002` added a final non-waiting e-stop and foreground authority revalidation before every MCP native action dispatch while preserving the intentional `activate_window` foreground exception. |
| 2026-08-04 | Repository consolidation pauses `GDA-DEMO-006` at checkpoint `d74201f` in draft PR #231 and keeps `GDA-CORE-003` as the only active item; the Demo's exact fresh live-run resume point and both Full Cycle lane boundaries remain preserved here. |
| 2026-08-04 | `GDA-CORE-003` preserves result-carrying post-dispatch cancellation as durable `UNKNOWN_OUTCOME`, retains cancellation semantics and zero replay, and keeps persistence failures observable without loading the MCP SDK into the Agent foundation. |
| 2026-08-04 | `GDA-CORE-004` makes the final caller/privacy/MCP-baseline-filtered advertised set a Host authority boundary and atomically rejects the whole returned turn before ledger, continuation completion, approval, or dispatch. |
| 2026-08-04 | `GDA-CORE-005` revalidates required tool safety baselines against the current MCP generation before any recovered observation intent, authorization, or dispatch; missing evidence leaves both durable files byte-identical. |
| 2026-08-04 | The separate `GDA-CORE-007` recovery-scope gap remains queued: continuation must version and preserve the original Host-advertised tool scope rather than widening a restricted run after a crash. |
| 2026-08-04 | `GDA-CORE-006` makes reviewed schema and canonical-argument validation whole-turn atomic after advertised-name validation; malformed siblings cannot grant an observation or approved-action prefix any authority. |
| 2026-08-04 | A real Anthropic recovery reproduced `GDA-CORE-007`: a run restricted to `ui_snapshot` widened to six advertised observations and later dispatched `list_windows`; exact Host tool scope must become versioned continuation evidence. |
| 2026-08-04 | `GDA-CORE-007` will bind continuation v6 to the exact final Host-advertised names and allow recovery only to narrow that authority to currently evidenced observations; one ordered scope must govern provider restore, stateless replay, request creation, returned-turn validation, and later MCP eligibility. |
| 2026-08-04 | The user reaffirmed that project-body core Runtime development takes priority now that Pro is available; `GDA-DEMO-006` remains paused at `d74201f` / draft PR #231 and resumes only after the core Runtime phase is deliberately closed or reprioritized. |
| 2026-08-04 | `GDA-CORE-008` makes agent-input attribution depend on both structured success and known native route provenance; semantic, activation, rejected, no-op, and failed actions cannot claim a concurrent human tick. |
| 2026-08-04 | `GDA-CORE-009` reserves exactly one mandatory verification lane before approval using a non-authorizing context projection; fixed insufficiency retains the prior verified observation and grants zero side-effect authority. |
| 2026-08-04 | `GDA-CORE-010` revalidates live MCP generation, grounding, and required baselines after an audited `ALLOW` but before any side-effect authority; drift remains known not dispatched with the prior verified observation intact. |
| 2026-08-05 | `GDA-CORE-017` is complete locally and independently reviewed under accepted ADR 009: per-mutation native authority revalidation preserves rejected/not-dispatched before the first attempt and unknown/dispatched after any attempted native mutation, with bounded cleanup and zero replay. |
| 2026-08-06 | A bounded MCP/native authority audit selected `GDA-CORE-023` next: `activate_window` must bind its reusable native id to the owner identity from a successful model-visible `list_windows`, fail known-not-dispatched on pre-attempt drift, and retain unknown/dispatched certainty after any native attempt. |
| 2026-08-06 | The user requested a stop after the `GDA-CORE-028` PR. Publish, merge, and clean that final slice, then do not start `GDA-CORE-029` without a new explicit resume request. |
| 2026-08-06 | `GDA-PRODUCT-001` is the single active item. `GDA-CORE-029` remains preserved inside `GDA-PRODUCT-002` so truthful `scroll`/`drag` capability discovery ships with product readiness rather than as a standalone micro-PR. |
| 2026-08-06 | `GDA-PRODUCT-003` Attempt 1 is retained as a real failure, not evidence: the Planner chose `list_windows` then `document_text` but paraphrased the scope as `foreground document`; the Host's non-empty-string schema allowed dispatch and Windows returned `DRIVER_ERROR` / `EXECUTOR_TOOL_FAILED`. The next candidate narrows only this observed functional contract before a fresh rerun. |
| 2026-08-06 | `GDA-PRODUCT-003` is complete locally on commit `8bf139f`: fresh wheel `54ec7077...a7a3` and fresh-state run `2699db750c314b178e1f2fb400e233bf` completed `document_text(scope=foreground) -> final_response`, returned the fixture-only codename, `37 + 58 = 95`, and `GO`, and retained `SUCCESS` evidence with zero side effects, retries, or tool failures. `GDA-PRODUCT-004` is the exact post-merge next batch. |
| 2026-08-06 | `GDA-PRODUCT-004` is one installed-product PR, not another CORE sequence and not draft PR #231 wholesale: add `workflow public-web-word`, package its disposable DOCX template, reuse installed sibling-MCP discovery, keep real-model content generation as the user path, verify saved/reopened/rendered DOCX output, and retain only bounded result metadata. |
| 2026-08-06 | The user requested a stop immediately after `GDA-PRODUCT-004` is validated, published, merged, and branch-cleaned. Keep `GDA-PRODUCT-005` queued with the recorded action-feedback and progress-display defaults, but do not start it in this session. |
| 2026-08-07 | `GDA-PRODUCT-004` clean-wheel candidate `74544d8` / `b9eef298...e9ab22` completed real run `public-web-word-e713ae032a3eb8ebf9923cc4eeeca02d`: the model authored a 518-character three-bullet brief from fresh Chrome evidence, the exact artifact hash `db01a12a...d01b76` matched disk, post-save and independent reopen verification passed, proposal corrections were zero, usage was `17` tool calls / `5` side effects, and both fixture phases reported verified window cleanup with no residual Word process. The complete offline gate passed (`1877 passed, 8 skipped`, Ruff, mypy over 127 source files, docs consistency, diff check). Visual QA is the single exact next action: packaged `render_docx.py` cannot run without LibreOffice, and the real-Word screenshot QA activation was denied/not dispatched before capture; do not mark the item complete or publish until that visual check passes. |
| 2026-08-07 | `GDA-PRODUCT-004` visual QA subsequently passed on the exact artifact in real Word under run `public-web-word-render-742da18da3974167b16085e6dfe1f9e1`: user-approved top/end inspection used `9` tool calls / `3` side effects, Word reported page 1 of 1 at 100% zoom, and no clipping, overlap, missing glyph, footer collision, or page overflow was visible. Exact Word cleanup and the run lock were clean. Static `render_docx.py` output remains unavailable on this machine because LibreOffice is absent, so it is not claimed as evidence. The exact transition is to publish this closure change, merge only with clear checks/reviews/conflicts, remove both branch copies, then stop; once this record is on `main`, no active delivery item is authorized and `GDA-PRODUCT-005` remains queued until an explicit later start. |
