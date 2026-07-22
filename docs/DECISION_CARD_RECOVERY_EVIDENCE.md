# Decision Card re-observe and defer offline evidence

> **Status: offline verified 2026-07-22.** This record covers Host semantics,
> not a human-operated desktop, provider, MCP-child, or application result.

The production Decision Card approval adapter now exposes four bounded choices:
exact-effect approval, re-observe, defer, and deny. Only exact-effect approval
can enter the existing action dispatch path.

For re-observe, the Runner records `APPROVAL_REOBSERVE_REQUIRED` as rejected and
not dispatched, consumes no side-effect budget, invalidates grounding, abandons
all remaining calls from the provider turn that proposed the action, and returns
to planning. A successful reviewed observation is required before another action
or final answer can proceed.

For defer, the Runner records `APPROVAL_DEFERRED` as rejected and not dispatched,
sets recovery to `stopped`, persists phase `PAUSED`, releases desktop presence,
and exits with the fixed `APPROVAL_DEFERRED` signal. A paused checkpoint is
operator attention with known non-running liveness. It is deliberately not
same-run resumable: recovery classifies it as `OPERATOR_DEFERRED` and requires
trace inspection followed by a fresh run.

Offline tests retain these invariants:

- all four card selections remain request-, identity-, digest-, and Host-binding
  correlated;
- re-observe dispatches no proposed action and ignores later calls from the stale
  turn;
- an action or final answer before successful observation fails closed;
- defer dispatches no action, consumes zero side-effect budget, and writes a
  non-resumable `PAUSED` checkpoint;
- pause is shown in the attention group and closes the passive presence surface;
- close, timeout, invalid selection, and denial retain fail-closed denial.

The earlier retained on-device Task Dialog result covers three choices. The
production surface and smoke script now expect four, but desktop evidence must
be rerun before claiming that expanded native presentation verified.
