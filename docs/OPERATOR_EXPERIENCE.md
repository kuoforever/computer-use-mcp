# Operator experience

> **Status: passive progress plus opt-in ordinary-run progress and bounded
> primary-display presence lifecycles are implemented; complete-product
> integration remains planned.** The presence
> surface has a pure Host-state projection, click-through/non-activating Win32
> halo, DPI geometry, reduced-motion/high-contrast modes, capture affinity, and
> E-stop/authority-release teardown. One fail-silent Host coordinator now drives
> it from durable phases in ordinary Agent `run` and `resume` lifecycles when
> explicitly enabled. Planned/campaign/recovery runtimes, multi-monitor support,
> and abrupt-process teardown remain separate gates. Decision Card compilation,
> choice validation, and an opt-in four-choice focus-taking Win32 adapter are
> implemented through the existing `ApprovalPort`. The approved-action flow
> remains one exact action at a time; console confirmation is default and the
> card requires explicit opt-in. The standalone native surface has retained
> [on-device evidence](PRESENCE_WINDOW_EVIDENCE.md), and ordinary Host wiring
> has retained [lifecycle evidence](PRESENCE_LIFECYCLE_EVIDENCE.md). Decision
> Card models have retained [offline evidence](DECISION_CARD_MODEL_EVIDENCE.md),
> and the opt-in approval path has bounded native
> [focus/timeout evidence](DECISION_CARD_WINDOW_EVIDENCE.md). The separate
> progress lifecycle has retained
> [background-thread evidence](PROGRESS_LIFECYCLE_EVIDENCE.md).

## Goal

Make desktop Agent activity continuously legible without making model output an
authority source. The complete operator experience has three coordinated but
separately trusted surfaces:

1. a non-interactive desktop presence indicator showing when computer use is
   active and which execution state owns the shared desktop;
2. a passive progress window projecting validated run and campaign state;
3. an explicit Decision Card presenting bounded choices and trade-offs when a
   human decision is required.

The visual surfaces observe host-owned state. They do not infer success from
model prose, dispatch tools, replay uncertain work, or weaken Host/MCP policy.

## Surface separation

~~~text
validated checkpoint / campaign / approval request
  -> pure operator view-model projection
      -> presence indicator       # passive, click-through, never authority
      -> progress viewer          # passive by default, never execution
      -> Decision Card            # explicit focus-taking human boundary
          -> bound policy decision
              -> ordinary Host policy / grounding / approval / MCP path
~~~

The passive surfaces must not become approval shortcuts. Opening a Decision
Card is a deliberate transition into operator interaction; it may take focus and
therefore triggers normal human-activity yielding until the decision is closed
and the desktop is explicitly returned to the Agent.

The native card is a normal Windows overlapped window rather than a modal Task
Dialog. It starts compact in one configured work-area corner (bottom-right by
default), can be dragged, minimized, maximized, covered by another application,
or resized by the operator, and never remains topmost. Decision detail and
digest-only evidence use independent read-only scroll areas; resizing gives
those panes more space instead of expanding the initial window to fit all text.
Buttons use a responsive two-column layout and stack when the window is narrow.
Close and timeout still deny without dispatch.

## Desktop presence indicator

The indicator provides ambient feedback comparable to a computer-use border or
halo. It appears only while the Agent owns or is waiting to regain the shared
desktop. State is conveyed by label/icon/motion as well as color so color is
never the only signal.

| Host state | Suggested presentation | Meaning |
| --- | --- | --- |
| Observing | blue, steady, eye label | Reading the current application; no action is being dispatched. |
| Planning | violet, slow motion, plan label | The model or planner is deciding the next bounded step. |
| Executing | green, directional motion, action label | One authorized desktop action is in progress. |
| Verifying | cyan, short pulse, verify label | A fresh observation is checking the preceding action. |
| Recovering | orange, slow pulse, recovery label | The Agent is re-observing or preparing a bounded recovery path. |
| Waiting approval | amber, attention pulse, approval label | No further side effect may execute until a bound decision is returned. |
| Paused / human takeover | neutral white/gray, paused label | Agent desktop authority is released or yielding to local input. |
| Unknown outcome / blocked | red, fixed warning, inspect label | Automatic replay is forbidden; evidence or human action is required. |

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
approval method. Wiring beyond ordinary `run` and `resume`, plus multi-monitor
selection, remains separate work.

The indicator must not claim that an action succeeded. It displays only the
current validated Host phase and ownership state.

## Progress window

The detailed projection, privacy constraints, multi-run grouping, and
non-activating behavior live in [Operator progress viewer](PROGRESS_VIEWER.md).
The complete window adds chapter and work-item progress for the universal GUI
campaign while retaining the existing passive default.

When explicitly enabled, ordinary Agent `run` and `resume` now start a separate
fail-silent progress coordinator. Its dedicated UI thread reads validated local
state, pumps the native window, and wakes after durable phase publication. It
has no provider, MCP, desktop, approval, or replay port. Unlike presence, it
stays available during human activity and a focus-taking Decision Card; E-stop
and final cleanup close it and join the thread. Plan, campaign, and recovery
lifecycle wiring remains separate work.

The compact summary may show:

- campaign, chapter, batch, and committed-item counts;
- current application class and sanitized fixed phase;
- model/tool calls, provider tokens, observation escalation, and retry counts;
- waiting approval, human takeover, challenge, recovery, uncertain, and
  terminal states;
- last validated checkpoint time and whether liveness is known or unknown.

New run checkpoints now preserve creation time and separately count complete
provider-usage reports and successful `screenshot` results. The passive viewer
therefore labels token coverage, screenshots, and elapsed-at-checkpoint time as
known only when those fields are present; older checkpoints remain unavailable.

It must not show raw task text, model prose, screenshots, page or message
content, typed values, credentials, account names, arbitrary errors, or hidden
reasoning. Unknown values remain unavailable rather than becoming zero.

## Remote and mobile notification semantics

Mobile push is a host surface, not a fourth operator authority surface. After a
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

No iPhone push adapter is implemented in this repository. The planned local
operator UI may display the same validated projection, but it neither sends the
mobile notification nor changes the task state.

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
   action executes while the decision is open.
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
   **Implemented, including an explicitly enabled ordinary `run`/`resume`
   lifecycle on a dedicated UI thread; E-stop/final cleanup and fail-silent
   isolation are tested. Plan, campaign, and recovery wiring remain.**
3. Implement the click-through presence indicator, capture filtering, reduced
   motion, DPI handling, and E-stop/authority-release teardown. **Implemented
   for one primary display over an injected controller and ctypes backend;
   opt-in ordinary `run`/`resume` lifecycle wiring is implemented, while
   multi-monitor selection remains.**
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
7. After the executable campaign worker exists, verify fake-host terminal and
   attention events from the same redacted status projection without adding a
   second execution path.
8. Run isolated Windows UX smoke, then the BOSS -> Google Docs -> WeChat
   cross-application scenario with one approval and one human takeover.

The final integrated presentation and evidence requirements live in the
[Universal GUI complete-product demo](UNIVERSAL_GUI_DEMO.md).
