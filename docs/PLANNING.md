# Task planning contract

> **Status: non-executable contract, private persistence, and pure Executor
> preflight implemented.**
> Strict provider-neutral `TaskPlan` and `PlanStep` values, a bounded JSON
> candidate compiler, pure ordered transitions, atomic private snapshots, and
> a one-shot provider-neutral PlannerPort contract, and isolated OpenAI and
> Claude adapters are implemented. No runtime command asks a provider for or
> executes a plan.

## Boundary

A plan is untrusted declarative data, not an authorization capability:

~~~text
bounded task + exact host-scoped non-sensitive schemas
  -> one-shot PlannerPort with no retry/fallback or execution methods
  -> optional OpenAI/Claude Structured Outputs request with no tools or continuation
  -> untrusted planner candidate
  -> exact JSON shape and byte/count bounds
  -> explicit host-scoped reviewed tools
  -> reviewed argument schemas
  -> host-derived effect and approval metadata
  -> immutable digest-bound TaskPlan
  -> private strict snapshot under the existing application RunLock
  -> sequence + plan-digest compare-and-swap transition
  -> no provider, policy, approval, MCP, or desktop call
~~~

Compiling or transitioning a plan cannot create a `ToolCall`, enter host
policy, request approval, or dispatch MCP. A later Executor must reconstruct a
fresh call identity and pass every existing policy, grounding, budget,
approval, MCP, write-ahead, and verification boundary independently.

## Candidate format

The compiler accepts UTF-8 JSON text up to 64 KiB with exactly these fields:

~~~json
{
  "version": 1,
  "steps": [
    {"action": "tool", "tool": "ui_snapshot", "arguments": {}},
    {"action": "final_response"}
  ]
}
~~~

Rules are fail-closed:

- one to 16 steps;
- exactly one `final_response`, always last;
- no provider-supplied IDs, statuses, effects, approval flags, digests, or
  execution fields;
- every tool must appear in an explicit host-supplied scope and in the reviewed
  registry;
- arguments must pass the existing exact tool schema;
- tools with sensitive arguments, currently `type`, cannot enter a plan at all;
- unknown fields, versions, actions, tools, malformed arguments, excessive
  bytes/steps, and reordered final steps fail without echoing candidate data.

The host assigns `step_1 ... step_N`, derives effect and approval requirements
from the reviewed registry, binds the exact task by SHA-256 without retaining
task text, and binds the current registry digest. The plan digest changes with
any step or status change.

## Local state transitions

Steps begin `pending`. Only the first non-completed step may transition:

| Current | Allowed next state |
| --- | --- |
| `pending` | `in_progress`, `blocked`, `cancelled` |
| `in_progress` | `completed`, `failed`, `blocked`, `cancelled` |
| terminal | none |

Completed steps must form an ordered prefix. At most one step may be active or
terminal, and untouched later steps remain pending. `TaskPlan.status` is
derived from step state; it is not accepted from a provider.

These transitions are pure immutable replacements. They grant no execution
authority by themselves.

## Private atomic persistence

`TaskPlanStore` persists one `task-plan.json` beneath the private run directory.
The canonical envelope is capped at 128 KiB and contains only the plan contract,
its current status, a monotonic sequence, and plan/envelope SHA-256 digests. It
retains the task digest but never raw task text. Unknown fields, malformed
types, unsupported versions, identity drift, registry drift, digest corruption,
unsafe paths, oversized data, and illegal transitions fail closed.

Every create, read, or transition requires the caller to hold the existing
OS-backed application `RunLock`. Creation never replaces an existing plan.
A transition rereads the validated snapshot and requires both the exact current
sequence and plan digest before applying the pure ordered transition and
atomically replacing the file. A stale or failed write leaves the previous
snapshot unchanged. The store imports no provider, policy, approval, MCP, or
desktop port.

The isolated provider adapters can only produce the already bounded candidate
format. The first Executor increment is a pure preflight compiler; runtime
consumption remains a later, independent review and must pass every existing
policy, grounding, budget, approval, MCP, write-ahead, and verification boundary.

## Pure Executor step preflight

`executor.py` accepts one already validated `PersistedTaskPlan`, the current
in-memory `RunState`, the caller's exact expected snapshot sequence and plan
digest, and new host-scoped turn/call identifiers. It then fails closed unless:

- run ID, exact task digest, and current reviewed registry digest match;
- sequence and plan digest match the caller's snapshot expectation;
- the first non-completed step is still `pending` and is a tool step;
- the registry still validates the tool arguments and host-derived metadata;
- the reconstructed `CallIdentity` does not already occur in the run ledger.

Success returns `PreparedPlanToolCall` containing only a newly reconstructed
`ToolCall` in `requested` state plus its source plan/step/snapshot binding. The
preflight has no external ports. It does not transition the plan, consume a
budget, authorize the call, write an intent, request approval, dispatch MCP, or
verify an outcome. Exhausted budgets can therefore still compile a requested
call: the ordinary host budget boundary remains mandatory and authoritative.
Started steps are rejected rather than replayed, and `final_response` remains
non-executable because the plan contains no trusted response text.

The ordinary Runner now exposes one internal requested-call boundary used by
its provider workflow. It contains the existing policy, grounding, budget,
approval, write-ahead, MCP, result-validation, observation, and verification
logic; Runner has no second MCP dispatch site. This extraction does not connect
plans or make the preflight result executable.

## Bounded non-executing session contract

`BoundedExecutorSession` coordinates the pure preflight with one
`TaskPlanStore` whose existing application `RunLock` must remain held. It still
has no provider, policy, approval, recovery, trace, MCP, or desktop port.

The session prepares observation tools only and enforces:

- at most four prepared steps, without changing the independent recovery cap;
- host-generated turn/call identities and exactly one outstanding request;
- the same run, task, policy, budget limits, and a lossless prior-ledger prefix;
- monotonic budget and observation counters;
- exactly one correlated tool-call and tool-result ledger event;
- exact plan ID, step/tool/argument binding and transition sequence;
- `completed` after success, `failed` after a known failure, and retained
  `in_progress` plus a closed session after an unknown outcome.

The session only checks evidence produced elsewhere. It neither invokes the
shared Runner boundary nor performs a plan transition, so forged plan status or
ledger data cannot create dispatch authority. A repeated prepare while a call
is outstanding, a released lock, history loss, drift, side effect, transition
mismatch, or fifth step fails closed.

## Observation-only runtime session

`executor_runtime.py` is the first execution-capable plan consumer. It is an
internal API with no CLI and accepts a host-compiled `TaskPlan` plus its exact
task. Opening a new session requires configured continuation WAL, acquires one
application RunLock, creates the private plan snapshot and safe run record,
verifies exact MCP discovery, and retains one recorder, continuation, grounding
state, MCP generation, and `BoundedExecutorSession` across steps.

For each observation step, ordering is fixed:

1. The bounded contract rereads the locked snapshot and creates a host-identified
   fresh `requested` call.
2. PlanStore CAS-transitions that exact step from `pending` to `in_progress`.
3. The sole Runner call boundary applies policy and budgets, writes prepared and
   dispatch-intent continuation state, authorizes, dispatches MCP, validates the
   result, and updates observation/grounding state.
4. A successful result CAS-transitions the step to `completed`; a known failure
   transitions it to `failed`. The session contract verifies exact ledger and
   transition evidence.
5. An unknown result performs no terminal plan transition: `in_progress` and
   the continuation artifact are retained, resources close, and the call is
   never replayed.

If the tool result is durably completed but the terminal plan CAS fails, the
runtime likewise closes with the step still `in_progress` and preserves the
completed continuation evidence. It never infers completion from the plan and
never repeats the call to repair bookkeeping.

The runtime module contains no direct `desktop.call_tool` site and cannot bypass
the Runner boundary. It rejects side effects before a plan transition, requires
an explicit cancellation for a remaining untouched step, never calls a model,
never treats `final_response` as trusted text, and never resumes implicitly.

## Completed-observation reconciliation

`executor_reconciliation.py` implements one explicit, local-only repair path;
it is not a general resume mechanism. It accepts an exact locked plan snapshot,
the exact task, and a strictly revalidated continuation envelope only when the
first unfinished step is the matching `in_progress` observation and the WAL's
last correlated tool call/result proves a known `completed` outcome. Run, task,
registry, plan sequence/digest, step/tool/arguments, fresh call digest,
operation identity, effect, dispatch certainty, and ledger order must all
match. It then performs only the CAS transition to `completed` or `failed` and
retains the WAL.

`prepared`, `dispatch_intent`, unknown outcomes, side effects, stale snapshots,
identity or argument drift, and malformed evidence fail without mutating the
plan. The module has no provider, policy, approval, recovery-executor, MCP, or
desktop port and never reconstructs a historical call for dispatch. It cannot
continue the plan, restore Runner state, execute `final_response`, delete the
continuation, or expose a CLI resume command.

## Tool-free final-response request contract

`executor_final.py` adds a pure local compiler for the next boundary; it does
not call either existing provider adapter. The current adapters' first request
contains only the task, so connecting them directly after plan observations
would omit the observation results. The new `FinalResponsePort` therefore has
one separate tool-free method whose implementation remains future work.

Compilation requires an exact snapshot with one to four successfully completed
observation steps followed by the still-pending `final_response`. Run, task,
registry, sequence/digest, recovery status, verified observation epoch, and
model/input budgets are rechecked. The in-memory ledger must be exactly one
`USER_TASK` followed by one correlated `TOOL_CALL`, successful `TOOL_RESULT`,
and `OBSERVATION` group per plan step, with exact tool/argument/order binding.
Provider turns, policy/recovery events, side effects, failures, unknown results,
missing observations, redacted arguments, and drift fail closed.

Success produces a digest-bound, 48 MiB-capped `FinalResponseRequest` containing
the task and lossless text/image observation data. Historical calls exist only
as compiler evidence and are not included as `ToolCall` values, tool schemas,
approval records, or dispatch authority. Sensitive task/output values are
excluded from object representations. The compiler does not consume budgets,
transition the final step, write WAL, call a model, validate returned text, or
terminalize a run. A future dual-provider adapter must still apply its exact
configured byte/token gates and one-shot no-tool/no-retry contract before I/O.

`final_response_wire.py` and the isolated `providers/openai_final.py` and
`providers/anthropic_final.py` adapters now implement that tool-free provider
boundary. The shared compiler emits canonical JSON containing the task,
observation text, exact plan/request bindings, and ordered SHA-256/dimension
descriptors for each PNG; image bytes are then sent as provider-native ordered
image blocks. Object representations expose only sizes/counts.

Each adapter makes exactly one stateless request with no tools, tool choice,
continuation ID/history, retry, fallback, approval, MCP, or execution port.
OpenAI uses one Responses request with `store=false`; Claude uses one Messages
request. Both apply the configured canonical request-byte limit and conservative
token-window gate before I/O, propagate cancellation, convert provider failures
to fixed codes, and accept only one bounded non-empty final text. Incomplete,
refused, truncated, tool/function-call, missing, or multi-content responses
fail closed after that one call. Returned text remains untrusted and neither
adapter writes WAL, consumes host budget, transitions the plan, or terminalizes
the run.

## Dedicated final-response WAL

The adapters now return `FinalResponseResult` rather than bare text. It binds
the exact run/turn, provider response ID, bounded untrusted text, and normalized
provider-reported usage while keeping text out of object representations. This
metadata is necessary for later host budget, trace, and crash correlation; it
still grants no terminal authority.

`executor_final_store.py` provides a separate private `final-response.json`
under the existing application RunLock. It is intentionally not encoded as a
normal continuation provider operation, so the existing recovery executor
cannot mistake a plan final response for a resumable provider/tool turn. The
strict digest-bound state machine is only `prepared -> dispatch_intent ->
completed`; every change uses sequence plus envelope-digest CAS and atomic
owner-only replacement. The request/plan/step/turn bindings are retained in
all stages, while sensitive final text and usage exist only after a correlated
completion. `PreparedRun.final_response_store()` exposes the store only while
the run lock remains live.

The WAL imports no adapter, policy, approval, MCP, trace, plan transition, or
recovery executor. Reading `completed` does not complete the plan, consume a
budget, publish text, or authorize retry. Dispatch intent remains uncertain and
non-replayable. Corruption, unsafe paths, stale CAS, illegal transitions,
identity drift, oversized text/envelopes, and replacement of existing WAL fail
closed without changing valid state.

The next Executor increment must separately review the orchestration ordering
across plan `in_progress`, WAL intent/completion, provider call, host budget,
final-step CAS, trace terminalization, and cleanup before connecting these
adapters to `RuntimeExecutorSession`, or add broader
explicit resume state before CLI wiring. Any side-effect
expansion must route fresh calls only through the shared Runner boundary and
retain the same approval, grounding, budget, WAL, and verification rules. Plan transitions may record outcomes,
but neither `pending`, `in_progress`, nor any persisted plan field may bypass or
replace policy, grounding, budget, approval, write-ahead, MCP, or mandatory
post-action observation.

## One-shot Planner port

`PlannerRequest` is immutable, canonical-JSON bounded to 128 KiB, versioned,
and digest-bound. It contains host-selected run/plan IDs, task text, the current
registry digest, and only the exact names, descriptions, and input schemas of
the explicit non-sensitive tool scope. It contains no ledger, memory,
observation, approval/effect metadata, provider continuation, or execution
state. The task is excluded from request `repr`.

`PlannerPort.create_candidate()` is called exactly once. The result is only
untrusted text: invalid JSON, unknown or authority-bearing fields, tools outside
the request scope, malformed arguments, excessive bytes, and invalid UTF-8
text fail through a fixed error after that one call. Provider failure is also
fixed and never retried or routed to another provider. Successful output goes
through `compile_task_plan`, where IDs and effect/approval metadata are still
host-derived.

The current implementation includes the provider-neutral port, a deterministic
fake, and isolated `OpenAIPlanner` and `AnthropicPlanner` adapters. OpenAI makes
exactly one Responses API request using strict `text.format` Structured Outputs. It sends no
function tools, `previous_response_id`, replay history, or reasoning include;
sets `store=false`; has complete canonical request-byte and conservative token
preflight gates; and never retries or falls back. Incomplete responses,
refusals, unexpected or ambiguous output/content items, malformed envelopes,
excessive bytes, and tools outside the request scope fail through fixed errors.
At most 64 output items are accepted; known `reasoning` items may accompany the
single assistant message but are ignored and never retained or compiled.

Claude makes exactly one Messages request using GA
[`output_config.format`](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
It
sends no tools, tool choice, history, thinking, continuation, or metadata and
never retries or falls back. Only one `end_turn` text block is accepted;
`refusal`, `max_tokens`, tool use, missing/extra content, malformed envelopes,
excessive bytes, and tools outside scope fail through fixed errors. The
`agent-anthropic` extra requires SDK 0.77 or newer for this GA request shape.

The shared strict provider wire schema carries tool arguments as JSON text because
the host schemas contain optional and mutually exclusive fields. The adapter
losslessly decodes that text into the ordinary candidate shape, then the
existing compiler alone enforces the exact reviewed tool-argument schema.
Historical function/tool calls never exist on these adapter paths. Neither is
connected to CLI, Runner, PlanStore, policy, approval, MCP, or Executor. The
bounded Executor remains a separate review.
