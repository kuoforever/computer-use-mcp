# Project status

> **Mode: Full Cycle closure; the external consumer (`GDA-FC-002`) is complete,
> so `GDA-FC-004` freeze validation is the single active item. Two bounded GUI
> Demo items are complete and the Operator HUD polish item is paused with a
> classified issue inventory.**
> Updated: 2026-08-02.
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
| Offline baseline | `1440 passed, 8 skipped` on 2026-07-30 during `GDA-DEMO-002` |
| Worktree at start | Clean |
| Branch at start | `main`; the HUD branch merged as `4d12bd2` |

The test count is a dated working snapshot, not a permanent capability claim.
Run the current suite before relying on it.

## Closed temporary scope exception

The user explicitly approved `GDA-DEMO-001` on 2026-07-30. The bounded item
closed after retained run `cross-app-demo-20260730-034539` passed. The
temporary exception did not erase, silently supersede, or strand
`GDA-FC-002`. The user subsequently requested the bounded `GDA-DEMO-002`
realism enhancement and `GDA-DEMO-003` Operator HUD polish. The latter is
paused for separate issue-by-issue sessions; `GDA-FC-004` is now the sole
active item and explicit resume point, because `GDA-FC-002` closed in the
consumer repository.

Continue to exclude:

- hierarchical task or behavior-tree runtime support;
- broad BOSS/application automation beyond the bounded Demo;
- a universal-GUI capability claim;
- additional desktop tools or platform drivers;
- Multi-Agent coordination;
- automatic continual learning;
- operator-UI work beyond the individually resumed `GDA-DEMO-003` issues that
  compose the existing Presence, Progress, and Decision Card surfaces;
- broad refactors unrelated to the bridge.

Existing planned documents remain valid design records, but they are not active
delivery work.

## Closure backlog

| ID | Status | Deliverable | Completion evidence |
| --- | --- | --- | --- |
| `GDA-FC-000` | Complete | Closure scope, integration contract, project status, Codex/Claude entrypoints | This documentation change |
| `GDA-FC-001` | Complete | Safe Full Cycle manifest and redacted run-export CLI | Exact schema/version tests, CLI tests, fail-closed record/output tests |
| `GDA-FC-002` | Complete | Consumer fixture in `reliable-agent-model-lifecycle` | That repository's `FC-BRIDGE-001`: `fixtures/bridge_v1` with one valid manifest, one valid run export, and eight invalid fixtures, pinned to producer commit `8ace897`. Re-verified on 2026-08-01 (below) |
| `GDA-FC-003` | Pending review | Explicit-consent rich episode capture contract owned by Full Cycle | Separate security/privacy review; disabled by default |
| `GDA-FC-004` | Next | Freeze validation and handoff | Not yet established for a reachable candidate. See the commit-identity correction below |
| `GDA-DEMO-001` | Complete | Real Chrome-to-Word interview Demo through existing Runtime authority | Retained run `cross-app-demo-20260730-034539`; [evidence](docs/CROSS_APP_DEMO_EVIDENCE.md) |
| `GDA-DEMO-002` | Complete; restart hardening offline-verified | Improve Demo realism without broadening authority | Retained run `cross-app-demo-20260730-042826`; deterministic fresh-start tests; [evidence](docs/PUBLIC_WEB_WORD_DEMO_EVIDENCE.md) |
| `GDA-DEMO-003` | Paused; issues classified; no evidence promotion | Operator HUD visual hierarchy, step status, safe lock interaction, and live reliability | Issue inventory below; failed exploratory run `cross-app-demo-20260730-044009-247254` |

Only one item may be active.

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

## Paused bounded task: GDA-DEMO-003 issue inventory

This is the only status registry for the Operator HUD work. Each future session
must explicitly resume one issue ID, keep the other rows paused, and return to
`GDA-FC-002` afterward. The exploratory live run
`cross-app-demo-20260730-044009-247254` is failed evidence, not a retained pass:
it ended after five tool calls, two approved side effects, and one known
`DENIED_BY_GATE` failure on the approved Chrome `PageDown`. It did not reach
Word editing or save verification. No Demo process remains running.

| ID | Category | Current problem | Current implementation state | Acceptance before closure |
| --- | --- | --- | --- | --- |
| `GDA-HUD-001` | Presence visibility | The operator reported no visible full-screen halo during the live run. The effect may be too brief, may disappear during approval yield, and has no retained visual proof. | Three separate causes made the halo invisible; all are fixed and none was the one originally suspected. (1) `display_bounds()` read `GetDpiForWindow(GetDesktopWindow())`, which always reports 96, so the halo scaled by 1.0 on a 150% display and drew a 10px border where the contract asks for 15px. (2) `RunPresenceCoordinator` never pumped a message loop, so the window received no `WM_PAINT` and a colour-keyed layered window that never paints is fully transparent -- the dominant cause, and the reason the halo had never been visible in any real Demo run. (3) The Runner expressed a transient approval yield with `release()`, which latches, so even a painted halo would have vanished at the first approval. `yield_authority()` now expresses that yield reversibly while keeping the pinned yield-then-card-then-dispatch ordering. Verified programmatically against the real window across the Demo's exact phase order: `CREATED` shows nothing, every active phase and both approval yields are painted, `SUCCESS` destroys it, zero errors. `scripts/demo_cross_app.py` now writes a presence probe report into `final-state.json` (projection sequence plus painted/unpainted/absent sample counts), so this evidence never depends on an operator saying they saw a halo -- which matters because Presence is capture-excluded by design and can never be screenshotted. **A complete Demo run has not been performed since these fixes.** |
| `GDA-HUD-002` | Decision Card layout | The first card is not a compact Codex/Claude-style HUD. The instruction wraps into the timeout, dense technical text is visible immediately, four long buttons stack vertically, the bottom is clipped, and typography/spacing look like a legacy form. | Rebuilt on 2026-08-01 against the Claude Code/Codex reference the operator was targeting. The frame dropped `WS_THICKFRAME` and the min/max boxes, so the reviewed geometry can no longer be broken; the header is painted from the shared type scale instead of system STATIC controls; choices and the expand affordance are owner-drawn flat; and both surfaces now consume one `OPERATOR_SURFACE` chrome contract. Three defects the operator caught during the live review were fixed in the same session: empty owner-drawn labels, an overdrawn expand affordance, and unreadable pane/scrollbar contrast. [Live 150% DPI evidence](docs/OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md) is retained. Clipping is now checked by measuring real Segoe UI glyph extents against the exact painted rectangles at 100%, 125%, and 150% DPI, on a memory device context that touches no desktop; a further test proves that check trips on the layout that produced the observed clipping. Pure geometry alone did not catch it, because the boxes fitted while their text did not. Live operator acceptance at 100% and 125% still remains, since changing display scaling is an operator action. | Default view fits wholly in the work area and shows only lock state, `1/7`, current action, application, countdown, a details affordance, and a 2x2 set of short choices. No overlap, clipping, or scroll is present in compact mode at 100%, 125%, and 150% DPI. |
| `GDA-HUD-003` | Expandable details | “Expand technical details” currently toggles only the evidence pane inside the same crowded layout; it is not a genuine compact/expanded state. | The same synthetic card intentionally resizes between compact and expanded geometry. Compact hides both panes; expanded shows human-readable decision trade-offs and safety checks with abbreviated support fingerprints; collapse restores the saved compact rectangle without changing the pending decision. The sunken `WS_EX_CLIENTEDGE` bevel was replaced by hairline-bounded panes with legible scrollbars, and the toggle now matches the Progress HUD's `SHOW/HIDE DETAILS` chevron. [Live 150% DPI acceptance](docs/OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md) is retained for both states. | Compact mode hides both decision trade-offs and digest evidence. Expanding reveals bounded decision details and evidence; collapsing restores the exact compact geometry without losing the pending decision. |
| `GDA-HUD-004` | Approval lock and exit | Host dispatch is paused while the bound card is open, but the visual lock is weak and keyboard behavior lacks retained live evidence. “Locked” must never mean trapping the operator. | Top-level and child-control message paths map `Esc` to a null selection; close and timeout already deny. Dispatch pausing is structural rather than enforced: the Runner awaits `request_approval`, so no later action can be reached while the card is open. `scripts/smoke_decision_card_exits.py` drives all three non-choice exits against the real window and passed twice consecutively on 2026-08-01: `Esc`, `WM_CLOSE`, and countdown expiry each returned no selection and each restored the exact prior foreground window. A source-level test asserts the module never reaches for `SetWindowsHookEx`, `RegisterHotKey`, `BlockInput`, `ClipCursor`, `SetCapture`, or `LockWorkStation`, so Alt+Tab and the Windows security keys cannot have been taken away. Live keyboard evidence for Alt+Tab itself still requires an operator, since synthesizing it would prove nothing about a real key press. | While open, no later action dispatches. `Esc`, close, and timeout all produce safe deny/defer and restore the previous foreground application. Alt+Tab and Windows security keys remain available. Positive approval still requires an explicit bounded choice. |
| `GDA-HUD-005` | Step semantics | The surfaces mix different totals: Progress uses the Host tool-call budget while the card shows seven approval actions. The progress view cannot yet name the exact current Demo chapter from durable Host state. | A bounded immutable checklist defines six fixed Demo chapters and drives compact/expanded Progress projections. The pure `project_demo_workflow` mapper fail-closed maps fixed provider boundaries `0..18` to the six Host-owned chapters and now also covers the cancelled boundary. `DemoWorkflowProgress` connects it: the provider reports only an integer boundary, the durable `RunPhase` owns overall status, and the Demo Decision Card derives its breadcrumb from `WorkflowBreadcrumb.from_checklist` while the approval `n/7` count stays separate. Approval wait projects `NEEDS_INPUT`, durable success projects `READY` only at the terminal boundary, and failure, uncertainty, or cancellation never complete the interrupted chapter. The complete offline gate passed on 2026-08-01. `scripts/smoke_demo_workflow_progress.py` then passed three consecutive times on the real non-activating Win32 surface: the foreground never moved from `0x204a0`, the first open showed every chapter, and a provider boundary, approval wait, held terminal chapter, and durable `SUCCESS` each reached worker-owned pixels. It asserts no tool-call diagnostics and no approval `n/7` count leak into the workflow HUD. This is isolated live evidence for the projection surface only; it opens no Runner, MCP, provider, or application, so it is not Demo, application, or release evidence. | The UI clearly labels “workflow step” versus “approval n/7”, names the current fixed action without trusting provider prose, and defines how skipped, failed, verification, and terminal steps affect counts. |
| `GDA-HUD-006` | Progress HUD visual design | The passive progress window has only received a dark fill and accent stripe; its hierarchy, compactness, typography, current-action emphasis, and expand behavior have not been seen or accepted live. | The DPI-scaled compact summary now has a non-activating `SHOW/HIDE STEPS` affordance. Expanded state appends all six Host-owned rows with fixed status glyphs and labels; collapse restores compact geometry. Computer Use completed an expanded-to-compact-to-expanded round trip at the current DPI with no clipping or state loss. The bounded Demo now drives this surface instead of the generic `state_dir` poller, so it no longer shows tool-call budgets: `DemoWorkflowProgress` owns one worker thread for every open, repaint, pump, and close, the first open shows all six chapters, and an operator collapse survives later refreshes. A dedicated live smoke confirms the real window stays non-activating across every projected transition (see `GDA-HUD-005`). Operator collapse preservation remains deterministic-offline only, because toggling the live affordance needs synthesized input. Retained production evidence remains. | A live passive window remains non-activating and foreground-safe while clearly showing overall progress, current action/phase, application, and expandable sanitized detail. |
| `GDA-HUD-007` | Cross-surface visual system | Presence, Progress, and Decision Card do not yet feel like states of one product. Approval has no strong amber relationship to the phase halo, and fixed colors/type/spacing are inconsistent. | One fixed token contract owns operator labels, glyphs, and RGB roles. It now also owns chrome: `OPERATOR_SURFACE` supplies background, elevated surface, text, muted text, and hairline, and `OPERATOR_TYPE_*` supplies the shared micro-label/title/meta tiers. Both Win32 backends consume them, and a test asserts the two surfaces resolve one palette. The canonical values are the ones the Progress HUD already shipped, so its pixels are unchanged and the Decision Card moved onto it. Motion rules and high-contrast behaviour remain unaddressed. | Shared typography, spacing, phase colors, status vocabulary, and motion rules are implemented; approval transition is visually obvious; reduced-motion and high-contrast behavior remain valid. |
| `GDA-HUD-008` | Approval-to-dispatch heartbeat | The post-approval heartbeat raced the MCP human-activity gate in the exploratory run: the card approved `PageDown`, but dispatch returned known `DENIED_BY_GATE`. | The bounded Demo now restores the captured foreground before making exactly one MCP action call. That call owns one bounded readiness sequence: three consecutive healthy idle samples, foreground allowlist verification, then at most one driver dispatch. The duplicate Host-side heartbeat was removed. Idle timeout, unavailable observation, foreground denial, E-stop, and user denial are returned as `rejected` with known `not_dispatched`; none is replayed. Deterministic offline tests cover streak reset, timeout, fail-closed observation, one-call/one-dispatch behavior, and result conversion. Repeated real Chrome/Word evidence remains. | One Host-configured, MCP-enforced readiness protocol covers card close, foreground restoration, idle stabilization, the foreground gate, and at most one dispatch. A denied gate causes no replay, and repeated real runs cross the boundary reliably without guessing a fixed delay. |
| `GDA-HUD-009` | Foreground and window composition | The current application must remain foreground while passive HUD surfaces stay visible and non-interactive; the card must restore that application after any exit. Overlap with Chrome/Word and screen-edge placement are not yet composition-tested across DPI. | Progress now defaults to the current foreground monitor's top-right work-area rail and preserves that right edge while its checklist expands or collapses; an explicit operator move disables automatic anchoring. Decision Card remains on the same monitor's bottom-right rail and restores the captured prior foreground on every exit. Pure geometry covers 100%, 125%, and 150% DPI against the bounded Demo application rectangle. `scripts/smoke_hud_composition.py` opens all three surfaces the Demo actually runs, which no probe had done before, and passed twice on 2026-08-01. The full-screen halo stayed click-through and non-activating, so it cannot swallow the clicks meant for the card's buttons; neither passive surface took foreground across three Progress repaints; the Decision Card alone took focus under a topmost full-screen halo; no painted halo region — border ring or phase tab — covered either other surface; Progress and the card did not overlap and both stayed inside the work area; and closing denied and restored the prior foreground. Measured clearance from painted halo pixels was 5px for the card and 15px for Progress, printed each run so a widened border or card cannot silently close the gap. Driving two surfaces together first found a defect that made the workflow HUD silently absent from a real Demo (see the entry below). Chrome/Word composition and multi-DPI live composition remain. | Live tests prove Chrome/Word remain foreground during passive updates, Decision Card alone takes focus after yield, prior foreground is restored, and no surface obscures the task-critical region. |
| `GDA-HUD-010` | Restart and cleanup | Fresh browser/document state is offline verified, but a failed or cancelled HUD run can leave launched Chrome/Word fixtures open. The next session needs an explicit cleanup/restart contract. | Cleanup is now a reusable exact-process component rather than a Demo-only process kill. It posts `WM_CLOSE` only to visible unowned top-level windows for each retained launch PID, observes all visible windows for that PID including owned dialogs, and treats verified window disappearance as completion even while an application process drains naturally. It force-terminates only when exact owned windows remain after the bounded close wait or a partial launch exposes no window; unavailable observation becomes explicit `handoff_required`. It never scans or terminates by executable name. The Demo uses the component from one `finally` and records fixture identity, close count, disposition, exit snapshot, and process-running snapshot. A live diagnostic caught force-termination-induced Word AutoRecover; after the generalized fix, two consecutive real fixture-cleanup smokes (`...091139-912478`, `...091235-478306`) each observed exactly two disposable windows, closed both as `windows_closed`, preserved the pre-existing Chrome window, and produced no recovery window on restart. | Start and end state are both declared. A failed/escaped run closes or clearly hands off its disposable windows, and the next run starts from the same pristine state without touching unrelated user windows. |
| `GDA-HUD-011` | Evidence and promotion | The visual changes have no retained screenshot/video matrix or successful end-to-end run. The latest run is a failure and must not replace prior passing evidence. | [A four-image isolated matrix](docs/OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md) retains Decision compact/expanded and Progress default-checklist/operator-collapsed states at 144 DPI (150%); [the superseded 2026-07-30 matrix](docs/OPERATOR_HUD_VISUAL_EVIDENCE.md) is kept unedited. The fail-closed capture helper uses the project DPI contract, exact white-listed titles, state geometry, a compositor-settle interval, and fixed dated outputs; duplicate visual-review instances are rejected. Six dedicated live smokes now cover the surfaces where visual behaviour matters: presence window, presence phase holds, workflow projection, decision-card exits, three-surface composition, and disposable fixture cleanup. The complete offline gate passes; exact dated counts are recorded per issue row rather than restated here. Durable Demo workflow wiring is done and offline-verified. What remains for this row is one complete retained Chrome-to-Word run, plus the two items only an operator can produce: 100%/125% DPI acceptance and a real Alt+Tab press. | Each issue has proportional offline tests, a dedicated live smoke where visual behavior matters, one complete retained Chrome-to-Word run, documented DPI/keyboard evidence, full validation gate, and explicit statement that the result remains bounded rather than universal GUI evidence. |

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

Rich multimodal capture was correctly excluded and remains `GDA-FC-003`.

## Exact active task: GDA-FC-004

Freeze validation and handoff, in this repository:

1. Decide the disposition of the unmerged `codex/demo-hud-baseline` branch
   before freezing. `GDA-DEMO-003` is paused with eleven open issues, so the
   freeze candidate must be either `main` or an explicitly reviewed branch;
   do not freeze an in-progress HUD state by accident.
2. Rerun `release preflight` from a clean candidate checkout per
   [docs/RELEASE.md](docs/RELEASE.md), and record the resulting commit as a
   commit that is reachable from a branch, not a pre-merge candidate.
3. Confirm the consumer's `FC-BRIDGE-004` pin against that exact commit, and
   update both repositories in the same change.
4. Resolve `GDA-FC-003` as accepted-with-review or explicitly deferred.
5. Freeze Runtime feature work and check every clause in
   `Definition of closed` below.

The local preflight records one Python runtime; supported-version evidence
still comes from the CI Python 3.11-3.13 matrix.

## Definition of closed

This repository is considered closed for the Full Cycle handoff when:

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
