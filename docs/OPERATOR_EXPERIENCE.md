# Operator experience

> **Status: passive progress plus configurable ordinary-run/bounded-plan/read-only
> recovery/fixed-campaign progress and ordinary-run/bounded-plan/read-only
> recovery/fixed-campaign
> primary-display presence
> lifecycles are implemented; complete-product
> integration remains planned.** The presence
> surface has a pure Host-state projection, click-through/non-activating Win32
> halo, DPI geometry, reduced-motion/high-contrast modes, capture affinity, and
> E-stop/authority-release teardown. One fail-silent Host coordinator now drives
> it from durable phases in ordinary Agent `run`/`resume` and bounded
> observation-only `plan run` lifecycles when enabled. Newly generated installed
> product profiles enable every current UI/UX boolean; legacy or hand-written
> absent-key configuration retains the prior disabled behavior. Explicit
> read-only recovery now projects the same presence phases only after validated
> persistence and durable recovery CAS writes. The three fixed MCP-backed
> campaign execution commands also project their durable run phases through
> presence and start the same campaign-state progress poller; zero-port campaign
> control remains window-free.
> Multi-monitor support and abrupt-process teardown remain separate gates. The
> composed Windows surfaces now share the implemented
> [operator accessibility contract](OPERATOR_ACCESSIBILITY.md): safe keyboard
> traversal, native UIA semantics, bounded status announcements, Windows High
> Contrast/reduced-motion preferences, and 200%/400% text reflow are offline
> verified, with a bounded native UIA smoke. Human Narrator/NVDA review and live
> large-text visual acceptance remain separate gates.
> Decision Card compilation,
> choice validation, and a configurable four-choice focus-taking Win32 adapter are
> implemented through the existing `ApprovalPort`. The approved-action flow
> remains one exact action at a time; generated installed profiles enable the
> card, while legacy/manual absent-key configuration retains console
> confirmation. The standalone native surface has retained
> [on-device evidence](PRESENCE_WINDOW_EVIDENCE.md), and ordinary Host wiring
> has retained [lifecycle evidence](PRESENCE_LIFECYCLE_EVIDENCE.md). One fixed
> provider-free bounded plan has separate native
> [presence lifecycle evidence](PLAN_PRESENCE_LIFECYCLE_EVIDENCE.md). Decision
> Card models have retained [offline evidence](DECISION_CARD_MODEL_EVIDENCE.md),
> and the enabled approval path has bounded native
> [focus/timeout evidence](DECISION_CARD_WINDOW_EVIDENCE.md). The separate
> progress lifecycle has retained
> [background-thread evidence](PROGRESS_LIFECYCLE_EVIDENCE.md), a fixed
> provider-free bounded plan has separate
> [plan lifecycle evidence](PLAN_PROGRESS_LIFECYCLE_EVIDENCE.md), and the fixed
> synthetic campaign has
> [campaign lifecycle evidence](CAMPAIGN_PROGRESS_LIFECYCLE_EVIDENCE.md). One
> persisted observation-pending run has separate read-only
> [recovery lifecycle evidence](RECOVERY_PROGRESS_LIFECYCLE_EVIDENCE.md). A
> separate CLI-first [read-only Task Center](TASK_CENTER.md) now groups the same
> validated local run/campaign projection and renders fixed outcome receipts;
> it has offline evidence only and no control or notification port. The fixed
> side-effect product workflow also has a CLI-first Host-compiled
> [Pre-run Review](PRE_RUN_REVIEW.md) before all external startup; it is
> offline verified and is not an action approval.
> The fixed product Runner loops now also expose offline-verified
> [cooperative Pause/Takeover/Resume](COOPERATIVE_CONTROL.md): a request becomes
> effective only after a durable safe-boundary pause releases desktop authority,
> and explicit resume requires fresh observation. Native takeover timing remains
> unverified.
> One strict [Approval Inbox](APPROVAL_INBOX.md) now supplements a compiled
> Decision Card with a local expiring identity/digest record and optional
> fixed-content Windows notification. Both are offline verified, have no
> approval or dispatch authority, and retain no raw task/action content.

## Goal

Make desktop Agent activity continuously legible without making model output an
authority source. The operator experience has seven coordinated but
separately trusted surfaces:

1. a Pre-run Review Scope Sheet showing the fixed workflow boundary before any
   external startup;
2. a non-interactive desktop presence indicator showing when computer use is
   active and which execution state owns the shared desktop;
3. a passive progress window projecting validated run and campaign state;
4. an explicit Decision Card presenting bounded choices and trade-offs when a
   human decision is required;
5. a CLI-first read-only Task Center grouping validated tasks and rendering
   fixed Completion/Failure Receipts after the active desktop work ends;
6. a local cooperative control lane that requests safe pause, publishes explicit
   authority release, and requires explicit resume plus fresh observation;
7. a read-only Approval Inbox plus fixed-content local notification that makes
   one bound Decision Card discoverable without becoming a decision surface.

All seven surfaces observe or act only through their documented Host-owned
boundary. They do not infer success from model prose, create a second dispatch
path, replay uncertain work, or weaken Host/MCP policy.

## Surface separation

~~~text
fixed reviewed workflow contract + exact local request
  -> Pre-run Review             # local scope only; no action approval
      -> exact start acknowledgement
          -> ordinary Host workflow entry

validated checkpoint / campaign / approval request
  -> pure operator view-model projection
      -> presence indicator       # passive, click-through, never authority
      -> progress viewer          # passive by default, never execution
      -> Task Center              # explicit local read, fixed receipts only
      -> Approval Inbox           # pending record only; no liveness or decision
      -> Windows notification     # fixed attention text; no callback/action
      -> Decision Card            # explicit focus-taking human boundary
          -> bound policy decision
              -> ordinary Host policy / grounding / approval / MCP path

live Host Runner lease + strict local control record
  -> pause/takeover request       # request is not yet authority release
      -> durable PAUSED boundary
          -> authority=released   # human may now use the desktop
              -> explicit resume -> fresh observation -> ordinary Runner path
~~~

The passive surfaces must not become approval shortcuts. Opening a Decision
Card is a deliberate transition into operator interaction; it may take focus and
therefore triggers normal human-activity yielding until the decision is closed
and the desktop is explicitly returned to the Agent.

The implemented default composition reserves two corners of the foreground
application's monitor work area. Passive Progress occupies a top-right HUD rail
and keeps its right edge fixed while its checklist expands or collapses. An
explicit operator move opts out of automatic anchoring. Decision Card occupies
the bottom-right rail, takes focus only for the bound decision, and restores the
captured prior foreground window on every exit. Pure geometry covers 100%,
125%, and 150% DPI against the bounded Demo application rectangle; the current
accessibility slice separately reflows controls and text through 400% effective
scale. An isolated
Computer Use review at the current DPI confirmed the passive foreground,
focus-taking card, and `Esc` restoration sequence; this is not retained
Chrome/Word or multi-monitor evidence.

Closing a Decision Card does not create a separately sampled readiness lease.
The card first completes its exit path and restores the captured foreground.
The Runner then makes exactly one MCP action call. Inside that call, the MCP
guard waits for the configured consecutive healthy idle samples, verifies the
foreground allowlist, and only then invokes the driver at most once. An idle
timeout, unavailable idle observation, E-stop, foreground denial, or user
denial is a known pre-dispatch rejection. It is reported as `not_dispatched`
and must not be replayed. The bounded Demo configures three samples; the
generic server keeps the legacy one-sample default unless a reviewed Host
configuration raises it.

The current native card is a normal Windows overlapped window rather than a
modal Task Dialog. It can be dragged, minimized, covered by another
application, or resized by the operator, and never remains topmost. Decision
detail and digest-only evidence use independent read-only scroll areas. Buttons
use a responsive layout and stack when the window is narrow. Close and timeout
deny without dispatch.

`GDA-DEMO-003` targets a compact Operator HUD that adds the current approval
number, total approvals, fixed action label, target application, a genuine
compact/expanded details state, and safe `Esc` rejection. The first live review
did not meet that target: content overlapped, buttons stacked and clipped, and
the details affordance was not a true collapsed state. The classified issue
inventory and acceptance criteria are owned by `PROJECT_STATUS.md`; these
sentences describe the target, not promoted implementation evidence.

## Desktop presence indicator

The indicator provides ambient feedback comparable to a computer-use border or
halo. It appears only while the Agent owns or is waiting to regain the shared
desktop. State is conveyed by label/icon/motion as well as color so color is
never the only signal. A thicker border and solid phase tab are present as
unverified `GDA-DEMO-003` worktree changes; the first live review reported no
visible halo, so high-visibility behavior is not yet an evidence-backed claim.

| Host state | Suggested presentation | Meaning |
| --- | --- | --- |
| Observing | blue, steady, eye label | Reading the current application; no action is being dispatched. |
| Planning | violet, slow motion, plan label | The model or planner is deciding the next bounded step. |
| Executing | green, directional motion, action label | One authorized desktop action is in progress. |
| Verifying | cyan, short pulse, verify label | A fresh observation is checking the preceding action. |
| Recovering | orange, slow pulse, recovery label | The Agent is re-observing or preparing a bounded recovery path. |
| Needs input | amber, attention pulse, approval label | No further side effect may execute until a bound decision is returned. |
| Paused / human takeover | neutral white/gray, paused label | Agent desktop authority is released or yielding to local input. |
| Needs inspection | red, fixed warning, inspect label | Automatic replay is forbidden; evidence or human action is required. |

The implemented shared token contract is now the source of truth for these
labels, glyphs, and RGB roles. Presence phase projection and workflow progress
both consume it directly. Decision Card uses the same amber `Needs input`
token while retaining the separate `approval locked` boundary. The older
run/campaign diagnostic projection also uses `In progress`, `Needs input`,
`Paused`, `Ready`, `Failed`, `Cancelled`, and `Needs inspection` rather than a
second vocabulary. High Contrast uses the operator's selected Windows system
colors and never removes the fixed label or glyph.

Implementation requirements:

- render as a top-level, click-through, non-activating tool window;
- never intercept pointer, keyboard, drag, or accessibility hit testing;
- bind the indicator to the controlled display and optionally identify the
  currently verified target window without drawing over actionable content;
- disappear immediately after E-stop, terminal close, or authority release;
- remain visibly distinct from application focus, selection, validation, and
  Windows security indicators;
- support reduced motion, high contrast, color-blind-safe labels, and per-user
  disablement without disabling audit or safety controls;
- exclude Agent-owned surfaces from screenshots when supported and also make
  the observation pipeline identify/mask them by trusted window identity;
- treat capture exclusion as feedback-loop prevention, not a secrecy or DRM
  guarantee;
- define per-monitor bounds and DPI behavior before claiming multi-monitor
  support.

The implemented slice is deliberately primary-display-only. Its native window
uses `WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW |
WS_EX_TOPMOST | WS_EX_LAYERED`, returns `HTTRANSPARENT` and `MA_NOACTIVATE`, and
has no controls or focus/input API. `PresenceSnapshot` accepts only fixed phase,
desktop-authority, E-stop, terminal-close, and accessibility-preference values;
its rendered model contains only fixed label/glyph/color/motion fields. The
controller exposes its HWND solely as trusted masking identity and reports
whether Windows accepted `WDA_EXCLUDEFROMCAPTURE`; that affinity is feedback
prevention, not a secrecy guarantee. `RunRecorder` publishes a phase to the
coordinator only after its atomic checkpoint succeeds. `ABORTED`,
`HUMAN_ACTIVE`, terminal phases, and final Host cleanup latch the surface off;
later phase notifications cannot reopen it. Surface failure is swallowed and
permanently disables that run's passive projection. The UI has no execution or
approval method. Bounded `plan run` now uses the same durable phase projection
and fail-silent teardown. Explicit read-only recovery starts only after
validated persistence and publishes later phases after its existing CAS.
The three fixed MCP-backed campaign execution commands use the same recorder
observer and immediate MCP E-stop/human-yield teardown; zero-port campaign
control remains window-free. Native BOSS campaign evidence and multi-monitor
selection remain separate work.

The indicator must not claim that an action succeeded. It displays only the
current validated Host phase and ownership state.

## Progress window

The detailed projection, privacy constraints, multi-run grouping, and
non-activating behavior live in [Operator progress viewer](PROGRESS_VIEWER.md).
The complete window adds chapter and work-item progress for the universal GUI
campaign while retaining the existing passive default.

When explicitly enabled, Agent `run`, `resume`, bounded observation-only
`plan run`, and explicit read-only recovery now start a separate fail-silent
progress coordinator. Its dedicated UI thread reads validated local state,
pumps the native window, and wakes after durable phase publication. Recovery
wakes occur only after the existing checkpoint/continuation CAS. The surface
has no provider, MCP, desktop, approval, or replay port. Unlike presence, it
stays available during human activity and a focus-taking Decision Card; E-stop
and final cleanup close it and join the thread. Fixed MCP-backed campaign
execution starts the same poller directly over validated campaign state and
releases it at command cleanup; zero-port campaign control commands do not open
the window.

The diagnostic summary may show:

- campaign, chapter, batch, and committed-item counts;
- current application class and sanitized fixed phase;
- model/tool calls, provider tokens, observation escalation, and retry counts;
- waiting approval, human takeover, challenge, recovery, uncertain, and
  terminal states;
- last validated checkpoint time and whether liveness is known or unknown.

An unpromoted `GDA-DEMO-003` worktree change leads the first line with
`STEP current/total`, where the total is the Host tool-call budget and current
is derived only from the durable checkpoint. The issue inventory records that
this is not yet a truthful end-user workflow-step model and has not passed live
visual review.

The first `GDA-HUD-005` model slice now defines a separate, immutable linear
workflow checklist. Its labels and application names are reviewed Host data,
not task text or provider prose. A checklist row can be not started, in
progress, waiting for approval, completed, skipped, failed, or uncertain;
overall paused and verifying states do not falsely complete the current row.
Completed and skipped rows form an ordered prefix, only one current row may
exist, and future rows remain not started. Contradictory or unknown state fails
closed. The controlled Chrome-to-Word Demo has six fixed workflow chapters:
prepare the workspace, review the public source, open the brief, add the note,
save the brief, and verify the saved document.

These six workflow chapters are deliberately independent of the seven
side-effect approvals and the Host tool-call budget. The model is not yet wired
to durable Demo transitions. The passive native window can now render a
workflow-aware compact summary from an explicitly supplied checklist: overall
state, completed/skipped/not-started counts, total chapters, exact current
chapter, and application. In this mode run IDs, provider/tool counters, and the
seven-approval count are absent. Ordinary poller paths retain their existing
diagnostic rendering until a later slice supplies durable workflow state. The
native summary combines observed DPI with the Windows text-scale preference.
Containers grow through 200%; larger text reflows from requested font height,
including every summary/checklist row through 400% effective scale;
an isolated Computer Use review at the current desktop DPI confirmed that the
fixed title, counts, current chapter, action, and application fit without
overlap or clipping. This is visual review, not retained production lifecycle
evidence.

The workflow-aware window also has a bounded checklist projection. It retains
the summary and appends all six ordered rows, each with a fixed glyph, step
number, Host-owned label, application, and human status. The checklist is the
default first-open state so the operator can immediately see completed,
current, and not-started work. Collapsing restores the reviewed compact size;
subsequent workflow refreshes preserve that explicit operator choice. The
toggle exists on the controller and as a non-activating `SHOW STEPS` /
`HIDE STEPS` mouse affordance; it does not dispatch, approve, replay, or alter
workflow state. Isolated Computer Use review at 150% DPI confirmed the default
six-row checklist and explicit collapsed summary. The retained matrix is
[recorded separately](OPERATOR_HUD_VISUAL_EVIDENCE.md). Durable Demo-state
wiring and complete production lifecycle evidence remain separate work.

New run checkpoints now preserve creation time and separately count complete
provider-usage reports and successful `screenshot` results. The passive viewer
therefore labels token coverage, screenshots, and elapsed-at-checkpoint time as
known only when those fields are present; older checkpoints remain unavailable.

It must not show raw task text, model prose, screenshots, page or message
content, typed values, credentials, account names, arbitrary errors, or hidden
reasoning. Unknown values remain unavailable rather than becoming zero.

## Remote and mobile notification semantics

Mobile push is a host surface, not another operator authority surface. After a
future campaign worker exists, Codex or Claude may poll the bounded status
projection defined in [Long-running tasks](LONG_RUNNING_TASKS.md). ChatGPT
Remote or Claude Remote Control may then notify the operator when the host ends
on a validated terminal state or pauses for a validated attention state.

The notification title and category may be host-specific, but its meaning must
remain fixed: `COMPLETED` is success; `FAILED` and `CANCELLED` are terminal but
not success; `WAITING_APPROVAL`, `PAUSED`, and `CHALLENGE` need attention but
are not complete; `UNCERTAIN` requires inspection and forbids replay. Running,
stale, malformed, missing, or identity-mismatched state cannot produce a
completion notification. MCP log notifications are never used as terminal
evidence.

No iPhone push adapter is implemented in this repository. The local Task Center
displays the validated task projection, but it neither sends a mobile
notification nor changes task state. A separate local Windows notification is
implemented only for a compiled Decision Card; it carries fixed wording, has
no action, and is not a terminal-status or mobile-notification bridge. See
[Approval Inbox](APPROVAL_INBOX.md).

## Decision Cards

A Decision Card is created only from a Host-classified decision point. It
explains the business decision before exposing the underlying GUI operation.
Examples include choosing between a compliant recovery and human takeover,
approving an external message, resolving object-version drift, or declining a
high-risk transition.

Each card contains:

- decision ID, campaign/run identity, expiry, and state/version digest;
- fixed blocker or decision class;
- target application and stable object/conversation/document identity in a
  bounded, privacy-safe form;
- the intended business effect and recipient/tenant/scope where applicable;
- bounded evidence references and which facts remain unknown;
- two to four mutually exclusive options, including a safe cancel, defer, or
  handoff path;
- a clearly labeled Agent recommendation when one exists;
- an explicit statement that the recommendation is advisory and grants no
  authority.

The native card uses progressive disclosure. Its compact state shows only the
approval lock, approval count, current fixed action, application, safe-close
countdown, details affordance, and a two-by-two grid of short choices. Decision
trade-offs and evidence are absent from that state. Expanding intentionally
resizes the same pending card and reveals two read-only panes: human-readable
option outcomes/trade-offs and human-readable safety checks. Internal enum
values and complete digests are not operator prose; technical correlation is
shown only as labeled short fingerprints. Collapsing restores the saved compact
geometry and does not create a new decision or selection.

The card's native Text, Edit, and Button controls expose standard Windows UIA
semantics. The unique safe `Deny` choice receives initial focus. Native dialog
navigation owns `Tab`, `Shift+Tab`, arrows, and `Space`; `Enter` activates only a
known focused toggle or choice, while `Esc` remains safe denial. Countdown name
changes are limited to bounded milestones rather than every timer tick. The
full contract, deterministic evidence, and native UIA-smoke limit are recorded
in [Operator accessibility](OPERATOR_ACCESSIBILITY.md).

At the current desktop DPI, Computer Use inspected a visual-only card carrying
the same trusted labels used by the bounded Demo. Compact state visibly showed
`APPROVAL 4/7`, `Microsoft Word`, the exact source-note action,
`WORKFLOW 4/6`, the safe-close countdown, details affordance, and four short
choices without clipping. Expanded state visibly showed separate readable
decision-scope and safety-check panes above the same choices; `Esc` then
removed the window. These are session-visible screenshots, not retained
repository artifacts, multi-DPI evidence, or Chrome/Word acceptance.

The card may also show one Host-owned workflow breadcrumb derived from the
validated checklist's exact current row. Approval count and workflow position
remain different facts: for example, `APPROVAL 4/7` can appear with
`WORKFLOW 3/6 · Open the research brief`. The primary line remains the exact
action being approved. The card never copies the complete checklist, derives a
workflow location from provider prose, or treats the breadcrumb as authority.
An isolated Computer Use review at the current DPI confirmed the approval
count, exact action, application, workflow breadcrumb, countdown, details
affordance, and 2x2 choices fit in compact mode without clipping.

## Disposable Demo lifecycle

The bounded Chrome-to-Word Demo declares both its start and end state. Each run
creates a unique root, empty Chrome profile, pristine DOCX copy, initial-state
manifest, and run ID. The manifest also declares that cleanup is limited to
exact processes launched by that run.

Word starts as a separate `/x` instance and Chrome starts with the unique
profile. The launcher retains only those two exact process handles. One
`finally` block executes for normal completion, Runner failure, safe denial or
cancel, keyboard interruption, and partial startup. It delegates to the shared
disposable-process cleanup component, which posts `WM_CLOSE` only to visible
unowned top-level windows belonging to each retained PID, then waits for every
visible top-level window for that PID, including owned dialogs, to disappear. A
process may drain naturally after its operator-visible windows are gone. Force
termination is reserved for a bounded close timeout or a partial launch that
exposed no window. Unavailable window observation becomes
`handoff_required`; it never causes a process-name scan.

The per-run `final-state.json` contains only its schema version, run identity,
fixed outcome, sanitized failure class, document/profile identity, cleanup
scope, close-request count, per-process disposition, exit-code snapshot, and
process-running snapshot. `cleanup_complete` means every exact owned window was
closed or the exact process was already gone; it does not require killing an
otherwise windowless application process.

An initial live diagnostic proved why that distinction matters:
force-terminating Word after its windows closed caused prior disposable
documents to reappear as AutoRecover windows on the next launch. The shared
window-first fallback then closed those exact windows without touching the
pre-existing Chrome window. Two subsequent real fixture-cleanup runs each
started exactly one disposable Chrome and one disposable Word window, closed
both as `windows_closed`, preserved the pre-existing Chrome window, and did not
reproduce the recovery windows.

Each option uses a typed trade-off record:

~~~json
{
  "option_id": "option_reobserve",
  "title": "Re-observe and retry the documented path",
  "effect": "No external message is sent during recovery",
  "benefits": ["may complete automatically", "preserves campaign state"],
  "costs": ["additional observation and model calls"],
  "risks": ["application state may have changed again"],
  "reversible": true,
  "expected_time": {"kind": "range", "min_seconds": 15, "max_seconds": 45},
  "expected_tokens": {"kind": "unknown"},
  "confidence": {"kind": "uncalibrated", "label": "medium"},
  "required_authority": "read_only_recovery",
  "fallback": "handoff_to_operator"
}
~~~

Time, token, and success estimates must identify whether they are measured,
configured bounds, uncalibrated model estimates, or unknown. The UI must not
present invented precision. A recommended option is not automatically
selected, and no option may hide an externally visible or irreversible effect.

## Decision and approval semantics

Choosing an option does not directly execute it. Selection creates a fresh,
digest-bound Host decision and, when necessary, a separate approval request for
the exact side effect. Before dispatch the Host rechecks:

- decision/card identity, expiry, and selected option;
- current run, tool call, policy, task, and registry digests;
- application, tenant, object, recipient, and version identity;
- grounding freshness, budgets, required approver role, and side-effect scope;
- whether new observations invalidate the displayed evidence or trade-offs.

Any drift closes the card as stale and requires a new projection. Empty input,
window close, timeout, malformed response, or mismatched identity defaults to
deny/defer. The model provider cannot approve its own recommendation.

The card must always make these paths available when applicable:

- approve the exact recommended option;
- choose a bounded alternative;
- inspect sanitized evidence;
- defer and preserve a resumable handoff;
- deny/cancel the proposed effect;
- take over the desktop, which first releases Agent authority.

There is no global "always allow" control in the first interactive version.

## Cooperative desktop authority

`pause_requested` is a notification to the live Runner, not an interrupt and
not permission for concurrent input. The Runner acknowledges only before a
provider call, before a tool dispatch, or after an approval returns. It first
persists `PAUSED`, invalidates old grounding, yields the presence surface, and
only then publishes `authority=released`.

The operator explicitly requests resume and must stop desktop input while the
record passes through `resume_requested` and `resuming`. Prior approval and
grounding never return. The provider sees observation tools only until a fresh
successful observation is durable. If an action is in flight or its dispatch is
uncertain, `UNKNOWN_OUTCOME` remains terminal and the request cannot turn it
into resumable work. The complete state machine and CLI are in
[Cooperative Pause, Takeover, and Resume](COOPERATIVE_CONTROL.md).

This same-process lane is distinct from durable Defer and crash continuation.
Defer still stops the run; crash recovery still follows conservative new-run or
read-only reconstruction rules. There is no `BlockInput`, remote endpoint,
campaign-control mutation, or second desktop dispatcher.

## Example

~~~text
+ Decision required -----------------------------------------------+
| WeChat test conversation changed after restart                   |
| Intended effect: send one approved test summary                  |
| Known: draft digest matches   Unknown: active conversation       |
|                                                                  |
| A  Re-observe and verify conversation        Recommended          |
|    + may finish automatically   - 15-45 s; token cost unknown     |
|    Risk: stale identity may remain; sends nothing during recovery|
|                                                                  |
| B  Keep draft and hand control to operator                       |
|    + lowest automation risk      - requires manual completion     |
|                                                                  |
| C  Cancel send and finish partial campaign                       |
|    + no external side effect     - task remains incomplete        |
|                                                                  |
| [Choose A] [Choose B] [Choose C] [Evidence] [Cancel]             |
+------------------------------------------------------------------+
~~~

## Acceptance checks

1. Presence and progress surfaces never become the foreground window, intercept
   input, or enter Agent observations as actionable application content.
2. Indicator state follows validated Host phases and disappears on authority
   release, crash detection, terminal close, and E-stop.
3. A Decision Card may take focus only after the Agent has yielded; no desktop
   action executes while the decision is open. After it closes, foreground
   restoration, stable-idle sampling, the foreground gate, and at most one
   driver dispatch remain one ordered readiness boundary; a pre-dispatch
   rejection is not replayed.
4. Every option is schema bounded, mutually exclusive, and includes effect,
   risk, reversibility, authority, cost provenance, and fallback.
5. Selecting an option with stale evidence, identity, policy, or object version
   cannot produce an approval or dispatch.
6. Recommendations remain advisory; deny, defer, cancel, and human takeover are
   tested paths.
7. Screenshot and trace fixtures prove that operator surfaces and trade-off
   records do not leak sensitive desktop or typed content.
8. Reduced-motion, high-contrast, DPI, focus, multi-window, and abrupt-process-
   termination cases have deterministic UI tests before isolated desktop smoke.

## Delivery sequence

1. Define pure presence, progress, option, trade-off, and Decision Card view
   models with redaction and stale-state tests. **Implemented: card inputs accept
   only fixed Host classifications, safe IDs, bounded timestamps, and digests;
   all display prose and trade-offs come from fixed mappings.**
2. Implement the passive non-activating progress window from synthetic records.
   **Implemented, including explicitly enabled ordinary `run`/`resume`,
   bounded `plan run`, read-only recovery, and fixed MCP-backed campaign
   execution lifecycles on a dedicated UI thread; E-stop/final cleanup,
   fail-silent isolation, and phase-free campaign wake are tested.**
3. Implement the click-through presence indicator, capture filtering, reduced
   motion, DPI handling, and E-stop/authority-release teardown. **Implemented
   for one primary display over an injected controller and ctypes backend;
   opt-in ordinary `run`/`resume`, bounded `plan run`, and explicit read-only
   recovery lifecycle wiring is implemented, while campaign wiring and
   multi-monitor selection remain.**
4. Add a fake-only Decision Card compiler and deterministic choice tests.
   **Implemented: expiry plus state, policy, task, registry, object, and evidence
   drift all fail closed; recommendation never selects an option.**
5. Connect a focus-taking local Decision Card to the existing ApprovalPort
   without changing the ordinary Host/MCP dispatch boundary. **Implemented for
   exact one-action approval: the Runner yields first; close, timeout, error,
   expiry, malformed selection, and Host binding drift deny. The native
   focus/timeout and sole-dispatch path has retained on-device evidence.**
6. Add campaign/chapter progress, bounded alternatives, evidence inspection,
   and trade-off provenance. **Partially implemented for ordinary approved
   actions: exact-effect approval, re-observe, durable defer, and denial are
   native custom choices; the expandable section shows digest-only Host evidence
   and existing fixed trade-off provenance. Re-observe abandons the stale turn
   and requires fresh evidence. Defer persists a non-resumable paused checkpoint.
    Campaign/chapter facts remain.**
7. Add cooperative Pause/Takeover/Resume without changing the sole Runner/MCP
   boundary. **Implemented for the fixed public-web-word Runner loops with
   local CLI control, Decision Card takeover, durable authority release,
   explicit resume, fresh-observation gating, and unknown-outcome precedence;
   offline verified only.**
8. Add a strict read-only Approval Inbox and fixed-content local notification
   around the existing Decision Card lifecycle. **Implemented with exact
   identity/digest/expiry binding, bounded private records, no liveness claim,
   fail-silent native delivery, fixed payload, and no approval or dispatch
   action; native assistive-technology evidence remains open.**
9. Close keyboard, screen-reader, high-contrast, reduced-motion, and 200%/400%
   scaling gaps across the composed operator experience.
10. After the executable campaign worker exists, verify fake-host terminal and
   attention events from the same redacted status projection without adding a
   second execution path.
11. Run isolated Windows UX smoke, then the BOSS -> Google Docs -> WeChat
   cross-application scenario with one approval and one human takeover.

The final integrated presentation and evidence requirements live in the
[Universal GUI complete-product demo](UNIVERSAL_GUI_DEMO.md).
