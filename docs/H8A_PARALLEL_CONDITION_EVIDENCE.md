# H8A parallel-condition evidence

> **Status: implemented and offline verified on 2026-08-09; publication active.**

## Scope

H8A adds one content-free, port-free local computation boundary:

- tree contract v2 accepts a `parallel` node only with 2-16 direct typed H5
  condition leaves;
- at most four fixed workers evaluate the same immutable world-state snapshot
  and context;
- known results are sorted by node ID and bound to the source sequence/tree,
  snapshot/context, condition, fact, and observation-evidence digests; and
- exactly one existing tree-store CAS records a complete known batch and its
  leaf statuses. Unavailable evidence records no batch and changes no byte.

The persisted tree-store envelope remains version 1. Existing contract-v1
linear snapshots keep their exact payload and digest and require no rewrite.

## Deterministic evidence

The focused H8A matrix proves:

- a synchronization barrier is reached by distinct worker threads, with a
  five-condition case proving the fixed four-worker ceiling;
- input mapping order cannot change result ordering, payload, or digest;
- all true completes the condition leaves atomically;
- a fresh false produces known local failure, while unavailable without a
  false returns blocked and leaves the exact store bytes unchanged;
- malformed v1/v2 fields, topology, result bindings, and re-signed structural
  tampering fail closed;
- evaluator exceptions and an injected stale CAS leave the exact prior store
  bytes unchanged; and
- a complete batch and status projection survive a fresh store instance and
  strict restart decode.

The complete repository gate passed `2407 passed, 8 skipped`, Ruff, mypy over
158 source files, docs consistency, and `git diff --check`. The implementation
commit and GitHub matrix are recorded in `PROJECT_STATUS.md` and the pull
request after publication.

## Claim boundary

This is source/offline evidence only. H8A contains no task text, raw fact value,
observation text, image bytes, provider request, Runner call, MCP call, desktop
action, application operation, approval, side effect, retry, replay, script, or
arbitrary callable. It does not claim real provider/MCP/desktop/application
parallelism, H8B dependency graphs, H8C fallback, L5, E4, or release readiness.
