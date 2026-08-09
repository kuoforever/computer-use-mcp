# ADR-010: Tree uncertainty remains outside node state

- **Status:** Accepted
- **Date:** 2026-08-09

## Context

Hierarchical control needs durable node state, parent reduction, selectors, and
bounded retry without creating a second representation of execution certainty.
The existing Runner already owns `UNKNOWN_OUTCOME`: after a possibly dispatched
boundary, it retains the continuation WAL, closes live authority, and forbids
automatic replay. Adding `unknown` to the node vocabulary would let tree logic
reinterpret that boundary as a selectable failure, retry input, or completed
transition.

The existing linear `TaskPlan` also persists a closed six-state step vocabulary.
A hierarchical contract should read those plans without rewriting their status
history or inventing a second lifecycle authority.

## Decision

Hierarchical nodes reuse exactly the existing `PlanStepStatus` values:
`pending`, `in_progress`, `completed`, `failed`, `blocked`, and `cancelled`.
There is no tree-level uncertainty state.

Parent status is a pure deterministic projection with this precedence:
`failed`, `blocked`, `cancelled`, all `completed`, any progress, then `pending`.
Every tree snapshot binds its contract version, stable node/parent identities,
ordered child identities, task/registry/policy digests, structural limits,
budgets, and node state into one canonical SHA-256 tree digest.

When a future Runner boundary is uncertain, it performs no node transition. The
leaf remains `in_progress`; `RunPhase.UNKNOWN_OUTCOME` remains the sole durable
certainty fact; the complete tree stops; and neither a selector nor retry rule
may consume that event.

H1 is deliberately inert. It adds no tree store, next-leaf compiler, provider,
Runner, MCP, desktop, approval, retry, replay, or campaign-item authority.

## Rejected alternatives

### Add `unknown_outcome` as a seventh node status

Rejected because the same uncertainty would exist in two state machines and
tree code could accidentally reduce, retry, or overwrite it.

### Convert uncertainty to `failed` or `blocked`

Rejected because those statuses describe known outcomes. A selector may react
to a known eligible failure; it must never react to lost execution knowledge.

### Mark the leaf failed and retain uncertainty only in an event log

Rejected because the canonical node state would then falsely claim a known
transition and could permit a fallback after a possibly committed side effect.

### Give behavior templates their own richer status vocabulary

Rejected because templates propose control flow; they are not a second durable
execution ledger or authority surface.

## Consequences

- Existing linear plans project losslessly as one `sequence` tree.
- Pure reduction is total over the existing status vocabulary and independently
  testable before persistence or execution exists.
- Tree snapshots cannot represent uncertainty in isolation; readers must retain
  and reconcile the outer run record and continuation WAL.
- Future selectors and retries need an explicit known-result contract and must
  stop before interpreting approval denial, authority loss, policy conflict, or
  uncertain dispatch as strategy failure.
- Full Cycle Lane A and Lane B schemas, the sole Runner/MCP boundary, and the
  Driver Contract remain unchanged.

Related: [ADR-001](001-uncertain-dispatch-is-never-auto-replayed.md),
[ADR-003](003-custom-durability-vs-workflow-engine.md),
[ADR-004](004-mcp-server-is-sole-desktop-authority.md),
[ADR-005](005-model-output-is-untrusted-data-not-authority.md),
[ADR-006](006-durable-state-is-the-source-of-truth.md), and
[Hierarchical task and behavior trees](../HIERARCHICAL_TASK_AND_BEHAVIOR_TREES.md).
