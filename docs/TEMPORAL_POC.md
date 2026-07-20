# Temporal proof of concept

> **Status: proof of concept, offline.** It runs against a real Temporal test
> server in the test suite. **No Temporal server is deployed, no real desktop
> work is scheduled through it, and the main package does not import
> `temporalio`.** This is not an architecture the project has adopted.

## The question it answers

Temporal will re-run an activity whose result it never received. For an HTTP
call with an idempotency key that is correct behavior. For a GUI side effect it
is precisely what [ADR-001](adr/001-uncertain-dispatch-is-never-auto-replayed.md)
forbids.

So: if you put a mature retry engine on top of non-idempotent desktop effects,
what stops it from duplicating one?

**The answer implemented here:** the activity asks the project's own durable
state before doing anything, and Temporal's retry decides only *when* the
activity runs again — never whether the effect may happen again.

## Division of responsibility

| Temporal owns | This project keeps owning |
| --- | --- |
| When an activity runs | Whether the effect may happen at all |
| Retry policy and backoff | The uncertain / committed / not-dispatched call |
| Worker lifecycle and task queues | The ledger, the lease, the exact receipt |
| Durable workflow history | Desktop authority and retained evidence |

The workflow holds no desktop authority. Every safety decision comes from
`classify_item`, which reads the ledger and the sink receipt and takes no
Temporal-shaped input at all — a test asserts its implementation never
references a workflow, an activity, or a retry.

## What is tested

Both cases run against a real Temporal test server, with a retry policy
deliberately set to be eager. The safety property must not depend on Temporal
being configured cautiously.

| Case | Crash point | Temporal does | The project decides | Result |
| --- | --- | --- | --- | --- |
| Safe redispatch | after an item commits | reschedules the activity | ledger says `COMMITTED` | continues, no repeat |
| **Uncertain stop** | between durable intent and result | **retries** | sink holds an intent with no receipt | **attention, never replayed** |

In the second case the sink still holds exactly one record for that key after
the workflow finishes: an intent with no result. A replay would have produced a
second attempt.

The workflow also exposes an `attention_items` query, so an operator can see
what stopped without reading state files.

## Running it

```powershell
pip install "computer-use-mcp[temporal]"
.\.venv\Scripts\python.exe -m pytest tests\agent\test_temporal_poc.py -q
```

The tests use `WorkflowEnvironment.start_time_skipping()`, which runs a real
Temporal test server locally. **No Docker and no external service are
required.** Without the extra installed the module is skipped.

## Deliberate boundaries

- Synthetic items and the fake durable side-effect sink. No desktop, no
  provider, no credentials.
- The activities are thin: they call the existing campaign functions. No item
  lifecycle, lease rule, or reconciliation logic is reimplemented, because a
  PoC that grew its own state machine would be demonstrating the wrong thing.
- `temporal_poc_workflow` exists as a separate module only because Temporal
  rejects a workflow class defined inside a function. Keeping it separate also
  preserves the optional dependency: nothing imports it unless the extra is
  installed.
- Not covered: a deployed Temporal cluster, worker fleets, signals for human
  approval, an isolated Windows worker, or scheduling a real desktop action.
  Those remain planned in [ADR-003](adr/003-custom-durability-vs-workflow-engine.md).
