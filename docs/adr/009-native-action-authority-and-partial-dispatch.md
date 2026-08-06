# ADR-009: Native action authority is revalidated at each driver-controlled mutation boundary

Status: Accepted
Date: 2026-08-05

## Context

The MCP server is the sole desktop execution authority. Its action tools first
wait for human-idle readiness and then run a final, non-waiting e-stop,
applicable-foreground, and human-input recheck immediately before calling
`Session`. That check is necessary, but it is not sufficient once control enters
the Windows driver.

Optional interaction pacing can show feedback and sleep before a semantic UIA
call, animate a pointer through several `SetCursorPos` calls, delay focused
typing, or spread a drag across many mouse events. Key chords and window
activation are multi-event even without presentation pacing. Authority can
therefore change after the server's final guard and before a later native
desktop mutation.

The certainty depends on where authority is lost. Before the first native
mutation attempt, the action is known not dispatched. After any pointer, mouse,
keyboard, UIA, or activation mutation attempt, the Runtime cannot prove the
desktop's resulting state. Calling that outcome a normal driver error or a
pre-dispatch rejection would permit unsafe continuation or replay.

Three terms are used precisely in this record:

- A **native dispatch attempt** begins immediately before the driver calls a
  native API that may change desktop state. It counts even when the API later
  reports failure, because an effect may have occurred before the failure was
  observed.
- An **effect-intending mutation** is a pointer move, mouse or keyboard input,
  UIA `Invoke` / `SetValue` / `Select`, or window restore, attachment, bring-to-
  top, or foreground operation.
- A **safety unwind** is the smallest bounded cleanup needed to release native
  state acquired by this call: release a held mouse button or key, detach an
  attached input queue, and clear passive feedback. It is not rollback and does
  not continue the target action.

## Decision drivers

- ADR-004 keeps policy and desktop dispatch authority in the MCP server; the
  driver must not read the e-stop, Gate, model data, or human-input policy.
- ADR-001 requires an uncertain side effect to stop without automatic replay.
- Revalidation must be call-scoped. A module-global callback or mutable shared
  action context could leak confirmation or authority across concurrent calls.
- The successful pacing and feedback behavior is intentional presentation, but
  delay is never authority and cannot extend an earlier decision.
- Native APIs still contain irreducible time-of-check/time-of-use windows. The
  Runtime must state what it can prove rather than claim rollback or preemption.

## Considered options

### 1. Disable optional pacing

*Rejected.* Drag, key chords, and activation remain multi-event without pacing.
This hides one reproduction without closing the authority window.

### 2. Check only before and after the `Session` call

*Rejected.* A check before `Session` is the current gap. A check after the call
cannot revoke native effects that already occurred or distinguish zero dispatch
from partial dispatch.

### 3. Let the Driver read e-stop, foreground, and human-input state

*Rejected.* This would split policy authority across the server and platform
code, contrary to ADR-004. It would also expose policy facts and confirmation
state below the ports-and-adapters boundary.

### 4. Keep one opaque `SendKeys(text, interval=...)` call

*Rejected.* The library interprets braces as a key-command grammar and performs
its own multi-event loop. One boundary before that opaque call would let
authority age during the configured interval. The reviewed `type` tool promises
text entry, while key chords have their own reviewed `key` tool; implicit
`SendKeys` command grammar is not part of the Driver or tool contract.

### 5. Pass a required action context through every Driver primitive

*Rejected for this bounded slice.* It is explicit but changes every public
primitive signature and every driver implementation. Making the parameter
optional would not make an old override safe when the new core supplies it. A
future cross-platform contract migration must be versioned rather than hidden
inside this hardening change.

### 6. Use a module-global callback or split one action into several MCP calls

*Rejected.* Global mutable state can cross calls, while additional MCP calls
would widen model-facing authority and make one action's dispatch certainty
depend on untrusted orchestration.

### 7. Roll back a partial action

*Rejected.* Moving the pointer back, restoring a prior window, sending another
key, or reversing an application mutation is another side effect. It cannot
prove that the target application returned to its prior state.

## Decision

**Every current Windows Runtime action must use one server-owned, call-scoped
native action boundary, and the driver must revalidate through that boundary
immediately before each driver-controlled native dispatch attempt.** This
accepted decision is normative; implementation and acceptance evidence are the
active `GDA-CORE-017` work.

`build_server` owns one `NativeActionBoundary` instance and binds it exactly
once to the Windows driver. Each MCP action opens exactly one non-reusable call
scope around the existing `Session` call. The scope contains a server-owned,
non-waiting revalidator; the driver receives only allow or reject and never
receives model prose, tool arguments, e-stop state, Gate state, human-input
ticks, or confirmation content.

The controller uses instance-owned call-local storage plus a non-blocking
single-active-scope guard. Missing binding, a missing or closed scope, nesting,
concurrent action scope, or duplicate binding fails closed before the first
native dispatch attempt. A revalidator failure fails closed at its next
checkpoint: it is known not dispatched if no attempt precedes it and partial
unknown otherwise. There is no production bypass.

At each checkpoint the controller:

1. asks the server closure to recheck e-stop, applicable foreground authority,
   safe-local human authority, and applicable activation-target identity without
   waiting;
2. rejects immediately when that authority is absent; or
3. conservatively records a native dispatch attempt and returns immediately
   before the native API call, with no intervening feedback, sleep, or work.

The driver must checkpoint every UIA action and activation mutation, every
pointer step, every mouse or key down/up event, and every wheel or drag-path
event. For focused literal typing, the Windows implementation must send one
Unicode scalar per native `SendInput` batch and checkpoint between scalars. A
non-BMP scalar is encoded as two ordered UTF-16 surrogate down/up pairs inside
that one opaque batch, avoiding the old single-`WORD` truncation. Configured
inter-character pacing follows the scalar. The Runtime does not claim preemption
inside a batch. Character order is preserved. The old
library-specific brace/chord grammar is intentionally removed from `type`;
callers use the separately reviewed `key` tool for key chords. A single UIA
pattern call and other opaque native calls remain one checkpointed attempt: the
Runtime does not claim mid-call cancellation or rollback.

### Human-input attribution inside a call

Windows includes injected input in `GetLastInputInfo`. After a known-returning
pointer, mouse, keyboard, or focused-typing dispatch, the scope captures the
current exact input tick only for the next checkpoint in this same call. This
prevents the driver from yielding to its own preceding event. Missing capture
after an attempted native input fails as a partial unknown outcome. At the next
probe, a current tick that differs from that call-local capture rejects.

There is an irreducible attribution race: physical input can occur after the
native call returns but before the post-input capture, causing that physical tick
to be mistaken for the preceding agent input until another tick change. Without
source-tagged input or a global hook, this design cannot eliminate that window.
The capture remains exact, call-local, short-lived, and never becomes global
success attribution, which bounds but does not erase the limitation.

This call-local exception is never persisted and never updates the global
agent-input attribution. The existing `note_agent_action()` call remains
success-only and route-specific: only a completely successful coordinate click,
scroll, drag, focused type, or key action can record the final agent tick.
Semantic UIA actions, activation, validation failures, rejections, partial
actions, and failed results do not.

The dangerous-confirmation tick remains exact, call-local, and confined to its
confirmed click. After the first known-returning native input, the scope advances
only to its exact call-local input capture; a different tick is not excused.

### Modes and existing exceptions

- In `safe_local`, every checkpoint rechecks e-stop, applicable foreground, and
  human-input authority.
- `activate_window` retains its foreground-gate exception at every checkpoint,
  but it still checks e-stop, safe-local human authority, and the target's
  observed direct-owner identity.
- `full_control_local` retains its explicit foreground and human-yield bypass,
  but every checkpoint still checks e-stop and applicable activation-target
  identity.

### Activation target identity clarification

For `activate_window`, a successful MCP `list_windows` result atomically binds
each unambiguous window id to the exact direct-owner PID and executable name in
that same structured observation. An activation captures one binding at call
entry and cannot follow a concurrent replacement. The server checks that the
captured binding is still current and matches exactly one live target before
each native attempt, then checks again after the Driver returns so drift during
the last attempt cannot become success. A missing, invalid, duplicate,
disappeared, or owner-drifted target invalidates the still-current binding; only
a fresh successful model-visible `list_windows` can bind a replacement.

Within each activation mutation checkpoint, target enumeration runs first and
the existing non-waiting e-stop plus applicable human/foreground probe runs
last. A slower read-only enumeration therefore cannot age human authority before
the native attempt.

These probes also apply in `full_control_local` and do not add a foreground
allowlist requirement. Internal window lists used by screenshot, OCR, capture,
or redaction do not bind authority. The comparison is a bounded server-owned
TOCTOU check over the existing window id plus direct-owner `(pid, name)`, not an
atomic OS lease or process-creation identity; Driver contract `1.0.0` remains
unchanged.

### Partial dispatch and bounded unwind

Authority loss forbids every later effect-intending action-progress mutation.
On the normal path, planned key/button releases and input-queue detaches are
checkpointed like every other native mutation. Once authority is lost, the only
exception is a separate bounded unwind path: if this call already pressed a
mouse button or key, or attached an input queue, the driver must attempt the
matching release or detach directly in `finally`, without revalidation. Passive
feedback may be cleared without its presentation delay. This exception cannot
start a new press/attach, cannot downgrade certainty, cannot retry the action,
and cannot restore the pointer or application state.

The server centrally projects call-scoped boundary evidence into fixed outcomes
above the Driver `Result` boundary:

| Condition | Agent status | Dispatch | Code |
| --- | --- | --- | --- |
| Authority is lost before the first native dispatch attempt | `REJECTED` | `NOT_DISPATCHED` | Existing fixed `ABORTED`, `HUMAN_ACTIVE`, or `DENIED_BY_GATE`; boundary composition failures use fixed `NATIVE_AUTHORITY_LOST` |
| Authority is lost after any native dispatch attempt | `UNKNOWN_OUTCOME` | `DISPATCHED` | Fixed `NATIVE_AUTHORITY_LOST` |
| A Windows action returns failure or raises after any native dispatch attempt | `UNKNOWN_OUTCOME` | `DISPATCHED` | Fixed `NATIVE_OUTCOME_UNKNOWN` |
| A Windows action fails with zero recorded native dispatch attempts | Unchanged | Unchanged | Existing result code |

`NATIVE_AUTHORITY_LOST` records an authority failure. The distinct
`NATIVE_OUTCOME_UNKNOWN` records only that a native API reported failure after
dispatch had begun and the effect therefore cannot be proved or disproved. It
is a server-owned certainty projection, not a Driver error code. The server
replaces, rather than appends, the original Driver result or exception detail.
The fixed envelopes contain no native parameters, typed text, model content,
arbitrary exception message, or original Driver message.

The Agent bridge reviews both exact fixed codes and maps the two post-attempt
conditions to `UNKNOWN_OUTCOME / DISPATCHED`. The Runner persists the correlated
result, terminalizes as `UNKNOWN_OUTCOME`, invalidates the MCP generation under
the existing post-dispatch path, and never verifies, continues, or replays the
call.
Strict continuation v6 retains its existing deliberately conservative
`next_step=stop` recovery decision while preserving the ToolResult's exact
`dispatch=dispatched` in both the completed boundary and ledger. Existing v6
payloads whose completed unknown boundary used `dispatch=unknown` remain
readable and equally non-replayable.

The public Driver Contract remains `1.0.0`: primitive signatures, shared data
structures, `Result`, driver error vocabulary, and `capabilities()` are
unchanged. The boundary is an explicit current MCP/Windows Runtime composition
requirement. An injected driver that cannot bind and checkpoint its native
mutations is not permitted to execute actions in this Runtime. This ADR does not
claim equivalent coverage for an unimplemented platform driver.

## Consequences

- Pacing and driver-controlled multi-event actions can no longer continue on an
  authority decision made before their intervening sleep or native event.
- A partial pointer, key, drag, typing, UIA, or activation route stops with
  honest unknown/dispatched certainty and zero automatic replay.
- A native failure after dispatch is no longer exposed as an ordinary
  `DRIVER_ERROR`; its original failure detail is replaced by the fixed redacted
  `NATIVE_OUTCOME_UNKNOWN` envelope.
- Safety unwind avoids leaving input or thread attachment held while preserving
  the unknown outcome.
- Successful action order, presentation pacing, passive feedback, and final
  native-input attribution remain unchanged. Focused typing preserves literal
  character order and pacing while replacing the undocumented `SendKeys`
  command grammar with checkpointable literal code points.
- Each native step adds synchronous authority probes. Foreground or human-input
  drift can therefore stop a long action more often, by design.
- A very small TOCTOU window remains between a successful checkpoint and its
  immediately following native API call. A second attribution window remains
  between a returning native-input call and the exact input-tick capture. Opaque
  native APIs cannot be preempted, and Windows input ticks have their existing
  same-millisecond granularity. No stronger claim is made.
- Full Cycle Lane A schemas, frozen consumer evidence, and Driver Contract
  version remain unchanged. This decision does not resume Full Cycle or Lane B.

## Acceptance evidence

- Paced semantic actions lose authority after presentation delay with zero UIA
  mutation; unchanged authority preserves feedback, sleep, mutation, and clear
  order.
- Coordinate pointer movement rejects before its first step with zero mutation,
  or stops after an exact partial prefix without sending the later click.
- Drag and key tests stop after partial dispatch, perform only required release
  cleanup, and return unknown/dispatched.
- Focused typing checks between literal Unicode scalars without exposing typed
  text in feedback, audit, or error envelopes; non-BMP surrogate order,
  newline/control literals, and partial-loss stopping are covered.
- Activation retains its foreground exception and detaches every successfully
  attached input queue on partial loss. Its observed-owner binding rejects
  missing, replaced, and pre-attempt drifted targets with zero mutation; drift
  after an intermediate or final attempt remains unknown/dispatched, and only a
  fresh model-visible list binds a replacement.
- Dangerous-confirmation, full-control, e-stop, and successful agent-input
  attribution behaviors remain explicitly covered.
- Effect-then-raise and partial-return tests cover semantic UIA, coordinate,
  focused input, and activation paths; zero-attempt validation and ordinary
  Driver failures retain their existing certainty, and native exception text is
  absent from the fixed envelope.
- Agent conversion and Runner tests prove fixed `NATIVE_AUTHORITY_LOST` and
  `NATIVE_OUTCOME_UNKNOWN`, `UNKNOWN_OUTCOME / DISPATCHED`, terminal unknown
  state, exact one MCP dispatch, and zero replay, including a failed continuation
  completion write.

Related: [ADR-001](001-uncertain-dispatch-is-never-auto-replayed.md),
[ADR-003](003-custom-durability-vs-workflow-engine.md),
[ADR-004](004-mcp-server-is-sole-desktop-authority.md),
[ADR-005](005-model-output-is-untrusted-data-not-authority.md),
[ADR-007](007-one-active-lease-per-foreground-desktop.md),
[Driver Contract](../DRIVER_CONTRACT.md), [Design](../DESIGN.md).
