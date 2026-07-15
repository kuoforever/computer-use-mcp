# Task planning contract

> **Status: non-executable contract and private persistence implemented.**
> Strict provider-neutral `TaskPlan` and `PlanStep` values, a bounded JSON
> candidate compiler, pure ordered transitions, atomic private snapshots, and
> a one-shot provider-neutral PlannerPort contract are implemented. No live
> Planner adapter or runtime command asks a provider for or executes a plan.

## Boundary

A plan is untrusted declarative data, not an authorization capability:

~~~text
bounded task + exact host-scoped non-sensitive schemas
  -> one-shot PlannerPort with no retry/fallback or execution methods
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

The next milestone may introduce a separately reviewed concrete Planner
provider adapter that can only produce the already bounded candidate format. Executor
consumption remains a later, independent review and must reconstruct fresh call
identity and pass every existing policy, grounding, budget, approval, MCP,
write-ahead, and verification boundary.

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

The current implementation includes only the provider-neutral port and a
deterministic fake. It does not include OpenAI/Claude Planner adapters and does
not connect to CLI, Runner, PlanStore, policy, approval, MCP, or Executor. The
next milestone can add one concrete Planner adapter with its own complete
request byte/token gates; the bounded Executor remains a separate review.
