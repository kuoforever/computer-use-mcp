# Task planning contract

> **Status: non-executable contract implemented.** The current milestone adds
> strict provider-neutral `TaskPlan` and `PlanStep` values, a bounded JSON
> candidate compiler, and pure ordered status transitions. No runtime command
> asks a provider for a plan or executes a plan yet.

## Boundary

A plan is untrusted declarative data, not an authorization capability:

~~~text
untrusted planner candidate
  -> exact JSON shape and byte/count bounds
  -> explicit host-scoped reviewed tools
  -> reviewed argument schemas
  -> host-derived effect and approval metadata
  -> immutable digest-bound TaskPlan
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

These transitions are pure immutable replacements. They are not durable state
machine commits. The next milestone must define private plan persistence and
atomic sequence/digest validation before introducing a Planner provider port or
Executor loop.
