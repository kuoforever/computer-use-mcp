# ADR-005: Model output is untrusted data, not authority

Status: Accepted
Date: 2026-07-21

## Context

Provider models return proposals for tool calls, plan structures, approval
statements, budget requests, retry hints, and completion claims. Each one
looks like something the runtime *could* act on directly:

- A tool call could be dispatched
- A plan could be executed step by step
- A model saying "the user approved this" could be treated as approval
- A completion claim could be recorded as a successful side effect

The temptation is worst with structured output: a schema-conformant
`send_message` call feels like a validated request rather than a proposal.

## Decision drivers

- Prompt injection arrives through any observed content (screenshots,
  documents, tool results). The provider itself can be honest and still relay
  a poisoned instruction
- Authority is a property of the *tool*, not of what the model asks for:
  effect class, approval requirement, budget slice, and schema live in a fixed
  registry
- A model that hallucinates a completion is a small failure. A host that
  records the unverified completion as durable state is a large one

## Considered options

### 1. Trust structured output (function-calling, JSON mode) as authority

*Rejected.* Structure is not authenticity. A schema-conformant call can carry
prompt-injected intent through cleanly. The schema catches malformed input,
not misdirected intent.

### 2. Let the model raise its own budget or self-approve

*Rejected.* This is exactly the axis a confused or hijacked model would
exploit. Requirements are derived by the Host from the registry, never from
the request.

## Decision

**All model output — tool calls, plans, supervisor decisions, completion
claims, approval statements, budget requests — is untrusted proposal data.**
Authority is derived by the Host from static registries. The model influences
*what* the Host considers, never *what the Host is permitted*.

## Consequences

- Every tool call is re-validated at the runner boundary, even after the
  provider adapter has parsed it
- Planner output is a plan *artifact*, not an executable script; execution
  routes back through the runner as if the plan came from a human
- A model claiming completion of a side effect does not commit anything;
  evidence must come from tool return plus post-action verification
- Cost: some provider affordances (self-raise budget, self-approve workflows)
  cannot be adopted. This is by design.

Related: [ADR-001](001-uncertain-dispatch-is-never-auto-replayed.md),
[AI_ASSISTED_DEVELOPMENT.md](../AI_ASSISTED_DEVELOPMENT.md).
