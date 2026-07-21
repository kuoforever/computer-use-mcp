# ADR-006: Durable state is the source of truth

Status: Accepted
Date: 2026-07-21

## Context

At runtime the system holds several views of the same fact: an item's status
in the ledger, the same item's status in an in-process projection, a claim in
the current provider conversation that "the model just said it committed", a
value a Worker computed and hasn't fsynced yet. When they disagree, one has
to win.

## Decision drivers

- Every long-running operation eventually crosses a process boundary or a
  crash. In-memory facts and conversation histories survive neither
- A Worker that trusts its own memory can wake up after a crash and act on a
  view of the world that no longer exists
- Provider conversation history is compressed, truncated, and rotated. It is
  not a record of what happened; it is a working set for the next turn

## Considered options

### 1. Treat in-memory projection as authoritative during a run

*Rejected.* Faster, but the projection is derived state. The moment it drifts
from the ledger (a peer wrote, a crash mid-transaction, a stale read), the
run is operating on a fiction. The bugs this produces are unreproducible.

### 2. Treat the model's conversation history as a record of decisions

*Rejected.* Compression and rotation are invisible to the model but real. A
model that "remembers" it committed an item may be reading a summary of a run
that was aborted before commit.

### 3. Reconstruct from the ledger only at handoff and recovery, cache in between

*Rejected.* The cache is now a second source of truth that must be reconciled
with the ledger. The reconciliation code becomes the new place bugs live.
Cheaper to read from the ledger every time and let atomicity do its job.

## Decision

**A fact is durable if and only if it is fsynced to the campaign store, WAL,
or evidence record.** Everything else — in-memory projections, provider
context, Worker scratch state, the model's beliefs — is a working view
rebuilt from durable state on demand and never authoritative when they
disagree.

Recovery reads only durable state. Handoff writes only durable state. Task
completion is measured only from durable state.

## Consequences

- Every state transition has an atomic-write boundary; PR [#173] hardens that
  boundary against transient Windows scanner interference
- A Worker can be killed, resumed, or replaced without a handshake; the new
  owner reads the ledger, not the last message
- Cost: no "just cache it in memory" optimizations for state that must
  survive a crash. Speed wins that require in-memory truth are refused
- Cost: reasoning about a bug means reading the ledger, not scrolling the log

Related: [ADR-001](001-uncertain-dispatch-is-never-auto-replayed.md),
[ADR-003](003-custom-durability-vs-workflow-engine.md).

[#173]: https://github.com/kuoforever/computer-use-mcp/pull/173
