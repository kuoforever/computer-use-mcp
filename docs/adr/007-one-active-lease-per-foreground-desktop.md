# ADR-007: One active lease per foreground desktop

Status: Accepted
Date: 2026-07-21

## Context

A Windows foreground session has exactly one focused window, one mouse
position, one keyboard target. Two Agents running concurrently on the same
desktop cannot both send input without interleaving actions in ways neither
observed and neither can attribute.

The temptation to permit exceptions is real: two items that "clearly don't
interact", or "just concurrent reads (screenshots) while one writer runs".

## Decision drivers

- The failure mode of unauthorized concurrency is invisible: a second actor's
  focus change lands between the first actor's click and its verification
  screenshot; both actors succeed by their own accounting and both attribute
  the failure to something else
- Enforceability matters: the system has no way to prove that two GUI paths
  don't share focus, don't scroll the same window, don't trigger the same
  notification popup. Any exception is unverifiable
- True concurrency has a real answer — an independent display authority (VM,
  dedicated session, remote host) — that does not require a policy hole here

## Considered options

### 1. Allow concurrent items that appear non-interacting

*Rejected.* "Appear" is not enforceable at the code layer. Every exception
opens a class of bugs that only manifest under load.

### 2. Serialize writes, allow concurrent reads (screenshots, UIA queries)

*Rejected.* A screenshot is a state read, but the desktop it reads *is*
shared state being mutated. The read races the writer and returns a
half-updated frame. In practice this is more confusing than an outright
error, because both actors succeed and report different truths.

## Decision

**At most one item per campaign may be in a claim-active status
(`CLAIMED`, `OBSERVED`, or `EXTRACTED`) at a time.** The lease is not
released at intermediate transitions; it survives until `COMMITTED`,
`SKIPPED`, or an equivalent terminal state. Additional concurrency requires
an independent desktop, not a policy relaxation.

The claim-active predicate is centralized as `_CLAIM_ACTIVE_STATUSES` in
[batch_coordinator.py](../../src/computer_use_agent/batch_coordinator.py)
(introduced with the guard-unification refactor in PR [#174]).

## Consequences

- Planner, Verifier, offline analysis, and research agents that never touch
  the shared desktop can run concurrently — this ADR scopes to side-effecting
  execution, not reasoning
- Multi-item throughput requires either sequential batches or additional VM
  workers; there is no "just parallelize on the same box" path
- Cost: a demo of "two Agents on one desktop" is not something the platform
  supports. This is stated in the docs, not hidden as a race

Related: [ADR-001](001-uncertain-dispatch-is-never-auto-replayed.md),
[DESIGN.md](../DESIGN.md).

[#174]: https://github.com/kuoforever/guarded-desktop-agent/pull/174
