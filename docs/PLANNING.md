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

The next Executor increment must preserve one recorder/continuation lifetime
across this lock-scoped session, reread the snapshot with
compare-and-swap expectations, and route each fresh requested call only through
that shared Runner boundary. Plan transitions may record outcomes,
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
