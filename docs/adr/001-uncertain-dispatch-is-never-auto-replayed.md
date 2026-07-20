# ADR-001: An uncertain dispatch is never automatically replayed

Status: Accepted
Date: 2026-07-20

## Context

A desktop action crosses a process boundary. The Host writes a dispatch intent,
sends the call to the MCP server, and waits for a correlated completion. Three
things can interrupt that: the child process dies, the transport times out, or
the Host itself crashes.

After any of those, the durable record can show a dispatch intent with no
correlated completion. The system knows it *asked* for a click. It does not know
whether the click happened.

This is not a rare edge case. It is the normal consequence of a crash landing in
the window between send and acknowledge, and that window exists on every single
side-effecting call.

## Decision drivers

- **Correctness of side effects.** A GUI click can send a message, delete a
  record, or submit a payment. Doing it twice is not a degraded outcome; it is a
  different, wrong outcome.
- **Recoverability.** The system must make progress after a crash without a
  human reading logs for every item.
- **Testability.** Whatever rule we pick has to be assertable offline.
- **Operational cost.** Stopping too often makes the system useless.

## Considered options

### 1. Retry on missing completion

Treat "no completion recorded" as "did not happen" and re-dispatch.

*Rejected.* This is the option that reads as resilient and is actually the
dangerous one. Absence of a completion record says the *observer* does not know;
it says nothing about the *observed system*. The GUI may have processed the
click and died before answering. Under this rule, every crash in the send window
produces a duplicate side effect, and the failure is silent: the ledger looks
clean, and only the target application knows there are two of something.

### 2. Timeout-based heuristic retry

Re-dispatch only if the completion is missing *and* less than N seconds elapsed,
assuming a longer gap means the action truly landed.

*Rejected.* This converts a correctness property into a tuning parameter. There
is no value of N that is sound: a foreground application under load can exceed
any threshold, and a transport can fail instantly after the effect landed.
Worse, it fails probabilistically, so it passes tests and breaks in production.

### 3. Query the target application for its state

After a crash, re-observe the application and infer whether the effect landed.

*Rejected as a general rule, retained as a narrow one.* It works when the effect
has an exact, durable, observable signature. It does not generalize: many GUI
effects are not idempotently observable after the fact, the page may have moved
on, and an incorrect inference is worse than an admission of ignorance. Where an
exact receipt does exist, reconciliation from that receipt is allowed — but it
must be evidence, not inference.

## Decision

Classify every interrupted call into exactly one of three states, and let only
two of them proceed automatically:

| State | Evidence | Automatic action |
| --- | --- | --- |
| Known not dispatched | No intent, or an intent proven unsent | Retry is safe |
| Known completed | A correlated completion, or an exact durable receipt | Reconcile bookkeeping; **never re-dispatch** |
| **Uncertain** | Intent present, completion absent, no exact receipt | **Stop. Request human attention.** |

Explicitly forbidden:

- Re-dispatching a side effect in the uncertain state, under any timeout,
  retry budget, or backoff policy.
- Downgrading uncertain to "not dispatched" because a retry succeeded before.
- Treating an external workflow engine's activity retry as permission to redo a
  GUI action (see [ADR-003](003-custom-durability-vs-workflow-engine.md)).

Observation-only calls are exempt from the *side-effect* concern but still
follow the same classification, because a stale observation can mislead a later
decision.

## Consequences

**Positive.** Duplicate side effects are structurally impossible rather than
statistically unlikely. Failure is loud and located. The rule is a fixed
property, so it can be asserted rather than measured.

**Negative.** The system stops and waits for a human more often than a retrying
one. Throughput on a flaky desktop is worse. Someone must build and staff the
attention path — an item parked as uncertain is a real operational obligation,
not a resolved state. This project accepts that cost.

**Future migration point.** If a side effect ever gains a true
end-to-end idempotency key that the target application honors, that specific
effect may move from "uncertain" to "safely retryable". That is a per-effect
change with its own evidence, never a global policy switch.

## Evidence

Implemented:

- `DispatchCertainty` (`NOT_DISPATCHED` / `DISPATCHED` / `UNKNOWN`) and
  `ToolResultStatus.UNKNOWN_OUTCOME` in `src/computer_use_agent/types.py`.
- `OperationStage.DISPATCH_INTENT` and the intent/completion boundary in
  `src/computer_use_agent/continuation.py`.
- Recovery classification in `src/computer_use_agent/recovery.py`.

Tested offline:

- `tests/agent/test_approved_workflow.py::test_unknown_action_outcome_stops_without_replay_and_marks_terminal_state`
- `tests/agent/test_executor_reconciliation.py::test_unknown_outcome_is_never_reconciled_or_replayed`
- `tests/agent/test_executor_runtime.py::test_runtime_unknown_outcome_is_preserved_and_never_replayed`
- `tests/agent/test_desktop_mcp_lifecycle.py::test_post_dispatch_timeout_invalidates_generation_without_replay_and_can_restart`
- `tests/agent/test_campaign_host_status.py::test_uncertain_and_stale_durable_state_fail_closed`

Desktop evidence: [E4](../E4_EVIDENCE.md) records a fail-closed attempt ending
as `VERIFICATION_REQUIRED` with no action replayed.

Not verified: behavior under a real power loss or filesystem corruption, as
opposed to process termination. No claim is made there.
