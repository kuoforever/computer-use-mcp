# Project status

> **Mode: Full Cycle closure; two bounded GUI Demo items are complete and the
> Operator HUD polish item is paused with a classified issue inventory.**
> Updated: 2026-07-30.
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
| Branch at start | `main` |

The test count is a dated working snapshot, not a permanent capability claim.
Run the current suite before relying on it.

## Closed temporary scope exception

The user explicitly approved `GDA-DEMO-001` on 2026-07-30. The bounded item
closed after retained run `cross-app-demo-20260730-034539` passed. The
temporary exception did not erase, silently supersede, or strand
`GDA-FC-002`. The user subsequently requested the bounded `GDA-DEMO-002`
realism enhancement and `GDA-DEMO-003` Operator HUD polish. The latter is
paused for separate issue-by-issue sessions; `GDA-FC-002` remains the sole
active item and explicit resume point.

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
| `GDA-FC-002` | Next | Consumer fixture in `reliable-agent-model-lifecycle` | Export bundle parsed and validated without desktop/provider access |
| `GDA-FC-003` | Pending review | Explicit-consent rich episode capture contract owned by Full Cycle | Separate security/privacy review; disabled by default |
| `GDA-FC-004` | Complete locally | Freeze validation and handoff | Clean release preflight passed for producer candidate `45bee82`; PR CI validates the final documentation commit |
| `GDA-DEMO-001` | Complete | Real Chrome-to-Word interview Demo through existing Runtime authority | Retained run `cross-app-demo-20260730-034539`; [evidence](docs/CROSS_APP_DEMO_EVIDENCE.md) |
| `GDA-DEMO-002` | Complete; restart hardening offline-verified | Improve Demo realism without broadening authority | Retained run `cross-app-demo-20260730-042826`; deterministic fresh-start tests; [evidence](docs/PUBLIC_WEB_WORD_DEMO_EVIDENCE.md) |
| `GDA-DEMO-003` | Paused; issues classified; no evidence promotion | Operator HUD visual hierarchy, step status, safe lock interaction, and live reliability | Issue inventory below; failed exploratory run `cross-app-demo-20260730-044009-247254` |

Only one item may be active.

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
| `GDA-HUD-001` | Presence visibility | The operator reported no visible full-screen halo during the live run. The effect may be too brief, may disappear during approval yield, and has no retained visual proof. | Border was increased from 6px to 10px at 96 DPI and a solid phase tab was added, but the change is offline-tested only and was not visibly confirmed. | A dedicated live smoke holds every phase long enough to inspect; the border and phase tab are unmistakable without covering actionable content; approval-wait visibility is explicitly specified and verified. |
| `GDA-HUD-002` | Decision Card layout | The first card is not a compact Codex/Claude-style HUD. The instruction wraps into the timeout, dense technical text is visible immediately, four long buttons stack vertically, the bottom is clipped, and typography/spacing look like a legacy form. | A visual-only synthetic card now renders a DPI-scaled dark compact state with Segoe UI, separate action/countdown hierarchy, a fixed 2x2 short-choice grid, and no decision/evidence panes. Pure geometry checks cover 100%, 125%, and 150% DPI; live operator acceptance at all three scales remains. | Default view fits wholly in the work area and shows only lock state, `1/7`, current action, application, countdown, a details affordance, and a 2x2 set of short choices. No overlap, clipping, or scroll is present in compact mode at 100%, 125%, and 150% DPI. |
| `GDA-HUD-003` | Expandable details | “Expand technical details” currently toggles only the evidence pane inside the same crowded layout; it is not a genuine compact/expanded state. | The same synthetic card now intentionally resizes between compact and expanded geometry. Compact hides both panes; expanded shows human-readable decision trade-offs and safety checks with abbreviated support fingerprints; collapse restores the saved compact rectangle without changing the pending decision. Isolated visual acceptance remains. | Compact mode hides both decision trade-offs and digest evidence. Expanding reveals bounded decision details and evidence; collapsing restores the exact compact geometry without losing the pending decision. |
| `GDA-HUD-004` | Approval lock and exit | Host dispatch is paused while the bound card is open, but the visual lock is weak and keyboard behavior lacks retained live evidence. “Locked” must never mean trapping the operator. | Top-level and child-control message paths now map `Esc` to a null selection; close and timeout already deny. This is unit/offline verified only. | While open, no later action dispatches. `Esc`, close, and timeout all produce safe deny/defer and restore the previous foreground application. Alt+Tab and Windows security keys remain available. Positive approval still requires an explicit bounded choice. |
| `GDA-HUD-005` | Step semantics | The surfaces mix different totals: Progress uses the Host tool-call budget while the card shows seven approval actions. The progress view cannot yet name the exact current Demo chapter from durable Host state. | A bounded immutable checklist defines six fixed Demo chapters and drives compact/expanded Progress projections. Decision Card can now derive one current breadcrumb from that validated checklist while keeping the exact approval action and `n/7` count separate; it never copies the checklist. Isolated Computer Use review passed at the current DPI. Durable Demo transition mapping remains. | The UI clearly labels “workflow step” versus “approval n/7”, names the current fixed action without trusting provider prose, and defines how skipped, failed, verification, and terminal steps affect counts. |
| `GDA-HUD-006` | Progress HUD visual design | The passive progress window has only received a dark fill and accent stripe; its hierarchy, compactness, typography, current-action emphasis, and expand behavior have not been seen or accepted live. | The DPI-scaled compact summary now has a non-activating `SHOW/HIDE STEPS` affordance. Expanded state appends all six Host-owned rows with fixed status glyphs and labels; collapse restores compact geometry. Computer Use completed an expanded-to-compact-to-expanded round trip at the current DPI with no clipping or state loss. Durable Demo wiring and retained production evidence remain. | A live passive window remains non-activating and foreground-safe while clearly showing overall progress, current action/phase, application, and expandable sanitized detail. |
| `GDA-HUD-007` | Cross-surface visual system | Presence, Progress, and Decision Card do not yet feel like states of one product. Approval has no strong amber relationship to the phase halo, and fixed colors/type/spacing are inconsistent. | Documentation describes a unified visual language, but the native controls do not implement it consistently. | Shared typography, spacing, phase colors, status vocabulary, and motion rules are implemented; approval transition is visually obvious; reduced-motion and high-contrast behavior remain valid. |
| `GDA-HUD-008` | Approval-to-dispatch heartbeat | The post-approval heartbeat still raced the MCP human-activity gate in the exploratory run: the card approved `PageDown`, but dispatch returned known `DENIED_BY_GATE`. | Three consecutive idle samples are required after approval, but the UI interaction and downstream gate do not share one authoritative readiness handshake. | One host-owned readiness protocol covers card close, idle stabilization, foreground restoration, and MCP dispatch. A denied gate causes no replay, and repeated real runs cross the boundary reliably without guessing a fixed delay. |
| `GDA-HUD-009` | Foreground and window composition | The current application must remain foreground while passive HUD surfaces stay visible and non-interactive; the card must restore that application after any exit. Overlap with Chrome/Word and screen-edge placement are not yet composition-tested across DPI. | Existing contracts prohibit activation by Presence/Progress and restore the prior foreground after Decision Card close. ABI composition has an offline test only. | Live tests prove Chrome/Word remain foreground during passive updates, Decision Card alone takes focus after yield, prior foreground is restored, and no surface obscures the task-critical region. |
| `GDA-HUD-010` | Restart and cleanup | Fresh browser/document state is offline verified, but a failed or cancelled HUD run can leave launched Chrome/Word fixtures open. The next session needs an explicit cleanup/restart contract. | Unique profile, pristine DOCX copy, initial-state manifest, fixed Chrome geometry, and unique run ID exist. Demo-process termination was verified for the failed run; application cleanup is not owned. | Start and end state are both declared. A failed/escaped run closes or clearly hands off its disposable windows, and the next run starts from the same pristine state without touching unrelated user windows. |
| `GDA-HUD-011` | Evidence and promotion | The visual changes have no retained screenshot/video matrix or successful end-to-end run. The latest run is a failure and must not replace prior passing evidence. | Targeted tests passed (`52 passed`), Ruff passed, and mypy passed before the rejected live UI review. No full gate was rerun after all HUD edits. | Each issue has proportional offline tests, a dedicated live smoke where visual behavior matters, one complete retained Chrome-to-Word run, documented DPI/keyboard evidence, full validation gate, and explicit statement that the result remains bounded rather than universal GUI evidence. |

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

## Exact active task: GDA-FC-002

Work in `C:\Users\Alienware\reliable-agent-model-lifecycle`, not in this
repository's Runtime:

1. Add an offline consumer for manifest v1 and redacted run-export v1.
2. Validate exact supported versions, the manifest digest, data class, training
   use, and every `automatic_export` false claim.
3. Reject unknown versions, digest mismatch, malformed JSON, unexpected rich
   content, and oversized inputs.
4. Add one fixture generated from the current canonical producer without
   provider, MCP, desktop, network, approval, memory, or continuation access.
5. Pin Runtime package/commit and schema versions in the consumer project.
6. Do not add rich multimodal capture under this item.

After the consumer passes, return here only for `GDA-FC-004`: commit the
reviewed bridge, rerun release preflight from a clean candidate, record the
exact commit, and freeze Runtime feature work.

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
| 2026-07-28 | Clean release preflight passed for producer candidate `45bee82`; Runtime remains feature-frozen while the external consumer is completed. |
| 2026-07-30 | Operator HUD polish was paused after a failed live review. Eleven issues are classified under `GDA-DEMO-003`; they may be resumed one bounded session at a time without displacing the `GDA-FC-002` Full Cycle resume point. |
