# L4 bounded adaptive-routing evidence

> **Result: passed for deterministic offline state and one injected isolated
> Runtime composition.** No real provider, MCP process, Windows desktop,
> external application, automatic promotion, E4, or release evidence is
> claimed.

## Reviewed boundary

L4 consumes only the exact strict-improvement recommendation already produced
by L3 from one reviewed data-only `ACTIVE` procedure and its equivalent reviewed
data-only `SHADOW` candidate. The candidate must retain an exact rollback pin to
the active procedure. The route never decodes an executable procedure, invents
arguments, imports memory, approves work, or calls a desktop port.

The reviewed canary policy requires at least one successful baseline warmup,
allows no more than one candidate selection per ten eligible LOW-risk
decisions, caps candidate selections at 32, and stops after the configured
successful canary count. Completion does not change either L2 lifecycle.

Each selection is bound to content-free exact context:

- task class plus exact task digest;
- application and version;
- current reviewed registry and Host policy digests;
- sorted boolean/integer preconditions;
- one Host risk tier per action; and
- one digest over each concrete action tool name and argument object.

Only all-LOW context can select the candidate. High or unknown risk selects the
active baseline and still requires the ordinary Runtime policy/approval path.

## Persistence and crash behavior

Each rollout has a private canonical JSON envelope beneath its own digest-named
directory. An independent OS lock serializes cross-run selection updates. The
store validates version, complete shape, rollout/state/envelope digests, exact
revision and digest CAS, safe non-symlink paths, a 512-KiB bound, and restrictive
file permissions before accepting state.

Only one decision may be pending. If a process stops after persisting a route
but before recording its outcome, the next selection returns
`ADAPTIVE_OUTCOME_REQUIRED`. It cannot reset the counters, choose another
candidate, retry, or replay the prior action. An injected atomic replacement
failure preserves the last durable state byte-for-byte.

## Rollback matrix

| Evidence | Result |
| --- | --- |
| Candidate result is not verified success | Permanent rollback to the exact active pin |
| Side-effect outcome is unknown | Permanent rollback; no candidate retry |
| Safety escape or authority regression is non-zero | Permanent rollback |
| Approval gate or authority gate changed | Permanent rollback |
| Verified postcondition missing | Permanent rollback |
| Candidate evidence, expiry, equivalence, suite, or rollback pin drifted | One exact active fallback decision and closed rollout |
| Active evidence or exact task/application/policy/registry/precondition context drifted | No selection from the stale rollout |
| Outcome decision/procedure/context digest is forged | Rejected without transition |

## Runtime composition

The selected procedure is still content-free. Before execution, L4 binds its
exact observation/action/verification tool sequence to one separately compiled
H7 plan and rechecks the digest of the concrete action arguments used for the
LOW classification. Substituting a tool, action ref, task, registry, or Host
policy fails before Runtime state or external ports open.

One deterministic isolated-dialog run used the production `AgentRunner`, Host
policy, approval request, plan/tree stores, write-ahead boundaries, grounding,
mandatory post-action observation, final compiler, and the single existing
Runner dispatch method. After nine persisted successful baseline selections,
selection ten routed the reviewed `find -> click -> ui_snapshot` candidate.
Every Runtime outcome retained the same procedure pin and route-binding digest;
the final provider input contained only the two observations. Reconciliation
then closed the one-run canary as complete without promoting the procedure.

## Verification

The focused L2/L3/H7/L4 gate currently passes 69 tests. The complete repository
suite, Ruff, mypy, documentation consistency, and diff checks remain the owning
implementation PR's publication gate and are recorded in `PROJECT_STATUS.md`.
