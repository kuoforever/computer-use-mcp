# ADR-003: A project-owned ledger and WAL, not a workflow engine

Status: Accepted
Date: 2026-07-20

## Context

The project needs day-scale work to survive process death: a campaign of many
items, each observed and possibly acted on, resumable after a crash without
repeating anything.

That is the problem statement durable workflow engines exist for. Temporal,
Cadence, and Step Functions all provide durable execution history, timers,
retries, and worker lifecycle — and are far more mature than anything this
project will write.

So this ADR has to justify not using one, and be honest that "we built our own"
is the suspicious answer.

## Decision drivers

- **Semantic fit.** The hard part here is classifying GUI outcomes, not
  scheduling.
- **Evidence integrity.** Recovery decisions must be reconstructible from
  retained records.
- **Operational surface.** A local Windows desktop tool that requires a server
  cluster to start is a different product.
- **Migration cost.** Whatever is built should not have to be demolished later.

## Considered options

### 1. Adopt Temporal as the primary state machine now

Model the campaign as a workflow, items as activities, and delete the local
ledger.

*Rejected for now, not forever.* Two problems.

First, **activity retry is not side-effect safety**. Temporal will happily
re-run an activity whose result it never received. For an HTTP call with an
idempotency key that is correct. For a GUI click it is exactly the behavior
[ADR-001](001-uncertain-dispatch-is-never-auto-replayed.md) forbids. The
project would still have to own the uncertain-outcome classification, so the
engine would replace the scheduling half of the problem while the hard half
stayed. The risk is worse than "no benefit": a mature retry mechanism sitting
directly on top of non-idempotent desktop effects is an invitation to trust it.

Second, workflow history is not desktop evidence. Temporal records what the
workflow *decided*; the project needs what the desktop *did*, with exact digests
and a redacted trace. Those are different artifacts, and conflating them means
the recovery authority moves to a system that never observed the desktop.

Adopting it now would also mean rewriting a large tested state machine before
the project has demonstrated its own semantics — spending the effort where the
risk is not.

### 2. Use a general durable-execution library in-process

*Rejected.* It carries most of the retry-semantics mismatch from option 1 while
adding a dependency whose failure modes are as unfamiliar as our own code's, and
without the operational maturity that made option 1 attractive in the first
place.

### 3. Keep everything in memory and restart from scratch after a crash

*Rejected.* This is only viable if every item is cheap and repeatable. Neither
holds: items involve side effects, and re-running them is the duplicate problem.

## Decision

Own the durability layer, and keep it deliberately small and domain-specific:

- An append-only item ledger with an explicit status transition table
  (`DISCOVERED` → `CLAIMED` → `OBSERVED` → `EXTRACTED` → `COMMITTED`, plus
  `RETRYABLE`, `SKIPPED`, `CHALLENGE`, `UNCERTAIN`), reduced to a projection.
- A write-ahead intent/completion boundary per external call.
- Lease and heartbeat ownership, so a dead owner's work cannot be continued by
  two processes at once.
- Content digests, so a completion can be verified rather than assumed.

What this layer does **not** try to be: a general scheduler, a timer service, a
distributed queue, or a cross-machine worker pool. Those are exactly what a
workflow engine does well, and the absence is intentional.

Explicitly forbidden: letting any external scheduler dispatch to the desktop
without passing through the Agent Runner and MCP boundary.

## Consequences

**Positive.** Recovery semantics are expressed in the vocabulary of the actual
problem — uncertain dispatch, stale lease, exact digest — instead of being
encoded into a general engine's retry policy. The project runs as a local tool
with no server dependency. Every recovery decision is reconstructible from files
in the state directory.

**Negative.** This is real state-machine code the project must maintain and test
itself, and it is the code most likely to contain a subtle bug. It provides no
timers, no cross-machine scheduling, and no worker pool. It has been exercised
by offline tests and bounded on-device runs — not by production traffic, which
is the strongest argument for a mature engine and is not answerable by design.

**Future migration point.** The intended end state is *both*, split by
responsibility:

| Temporal would own | This project keeps owning |
| --- | --- |
| Scheduling, timers, retry policy, worker lifecycle, task queues | Desktop authority, policy, grounding, approval, result validation |
| Durable workflow history across processes | Whether a GUI action is safe to retry at all |
| Assigning work to an isolated Windows worker | Exact evidence, redacted trace, item ledger |

The boundary that makes this safe: an activity may be re-run **only** when the
project's own classification says the item was never dispatched. A workflow
task must never turn a re-scheduled activity into a repeated click. Until a
proof-of-concept demonstrates that boundary holds, this remains a plan and not a
capability.

## Evidence

Implemented:

- `src/computer_use_agent/campaign.py`: manifest, append-only item ledger,
  transition table, projection reducer, heartbeat and lease records, digests.
- `src/computer_use_agent/continuation.py`: per-call intent/completion boundary.
- `src/computer_use_agent/recovery.py`: bounded read-only recovery planning.
- `src/computer_use_agent/run_lock.py`: single-owner local run lock.

Tested offline: the campaign, continuation, recovery, lease, and heartbeat test
modules under `tests/agent/`.

On-device: [synthetic campaign evidence](../SYNTHETIC_CAMPAIGN_EVIDENCE.md) and
[BOSS discovery evidence](../BOSS_CAMPAIGN_DISCOVERY_EVIDENCE.md), each scoped
to its own recorded run.

Unknown: no Temporal integration exists in this repository. The comparison above
is a design position, not a measured result, and the table describing a future
split is **planned**, not implemented.
