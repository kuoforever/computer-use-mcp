# GDA-06 — Deterministic hierarchical control with bounded concurrency

> **Status: current candidate item; H1-H8 are merged and offline verified.**
> H7 is the only injected widened Runtime path; H8A-H8C are port-free.
> Personal ownership: `TBC`. Submission-ready only after `My scope` is filled.

## Quick select

| Field | Guidance |
| --- | --- |
| Primary roles | Agent planning, workflow/state-machine engineering, concurrency, backend |
| Position | Lead |
| Evidence ceiling | H1-H8 source/offline evidence plus one H7 injected isolated Runtime composition |
| Use when | The JD mentions task graphs, behavior trees, scheduling, deterministic concurrency, CAS, or orchestration |
| Skip when | The wording would imply distributed workers, live parallel actions, or general autonomy |
| Exact JD keywords | `behavior tree`, `DAG`, `state machine`, `deterministic scheduling`, `bounded concurrency`, `CAS`, `fail closed` |

## Resume copy

**Short ZH:** 离线实现并验证 H1-H8 deterministic task trees，以 canonical
digest、≤4 个 local condition workers、Host-order choice 与 atomic CAS 保持
可复现，且 H8 不新增外部端口。

**Evidence-rich ZH:** 完成 H1-H8 immutable hierarchical control：versioned node/
tree contracts、atomic store/CAS、next-leaf compiler、fresh fact model、最多
4-worker 的 local condition evaluation、bounded all-of DAG/join 与 Host-order
choice/fallback；H7 的唯一 side-effect sequence 仍复用既有 Runner，H8 不新增
provider/MCP/desktop port。

**Short EN:** Implemented and offline-verified deterministic H1-H8
task/behavior-tree contracts with canonical digests, bounded local concurrency,
dependency joins, Host-ordered choice, and atomic CAS, without new external
ports.

**Evidence-rich EN:** Built immutable H1-H8 hierarchical-control contracts and
offline gates spanning exact store/CAS, next-leaf compilation, four-worker
condition evaluation, bounded all-of graphs, deterministic safe choice, and
globally serialized external boundaries.

**My scope to confirm:** Identify the node/schema, compiler, store, concurrency,
choice/fallback, H7 composition, tests, or evidence you personally owned.

## Fact card

| Dimension | Evidence-backed fact |
| --- | --- |
| Problem | A linear plan cannot express reusable subtrees, dependencies, conditions, or safe fallback, but a second workflow engine could duplicate execution authority |
| Constraint | At most one external boundary, no concurrent foreground-desktop action, uncertainty remains in outer RunPhase, model candidates remain data |
| State foundation | Immutable nodes, canonical v1-v4 payload/digests, bounded topology/budgets, private atomic tree store, exact sequence/tree-digest CAS |
| Concurrency | H8A evaluates 2-16 direct typed conditions with at most four local workers over one immutable snapshot; one CAS records a complete known batch |
| Graph/choice | H8B adds bounded all-of dependencies and local joins; H8C evaluates gates concurrently but resolves selection in fixed Host order |
| Runtime ceiling | H7 owns one reviewed observation/action/verification-observation/final injected path; H8A-H8C have no external port |

## Proof map

| Claim | Owner/evidence |
| --- | --- |
| Complete H1-H8 design and current merged state | [Hierarchical control owner](../../HIERARCHICAL_TASK_AND_BEHAVIOR_TREES.md) |
| Actual local worker overlap and atomic batch | [H8A evidence](../../H8A_PARALLEL_CONDITION_EVIDENCE.md) |
| Dependency/join bounds | [H8B evidence](../../H8B_DEPENDENCY_JOIN_EVIDENCE.md) |
| Host-order choice and fallback stop matrix | [H8C evidence](../../H8C_SAFE_CHOICE_EVIDENCE.md) |
| PR/merge and complete gate | [Project status](../../../PROJECT_STATUS.md) |

## Interview card

- **S:** hierarchical planning was needed without creating a second authority or
  allowing parallel foreground actions.
- **T:** state the contract/store/compiler/runtime/evidence slice you owned.
- **A:** separate pure control compilation from durable state and from the sole
  Runner; bind every transition to immutable evidence and one CAS.
- **R:** H1-H8 pass deterministic compatibility, overlap, ordering, tamper,
  conflict, restart, and prohibited-fallback matrices at their named scopes.
- **Trade-off:** external effects stay serialized, so concurrency improves only
  local condition evaluation rather than total desktop throughput.
- **Debug story:** explain why `unavailable` cannot be treated as `false`, or why
  a CAS conflict must preserve exact prior bytes.

Deep-dive questions:

1. How can gate evaluation overlap while branch choice remains deterministic?
2. Which outcomes permit fallback, and why do denial or unknown dispatch stop the tree?
3. Why does the tree project over the existing Runner instead of owning dispatch?

## Claim limits

Do not claim Multi-Agent operation, distributed scheduling, concurrent desktop
actions, arbitrary scripts, general retry/fallback, live provider/MCP/Windows
parallelism, application acceptance, L5, E4, or release readiness. Phase names
belong in the deep dive; the short bullet should explain the engineering result.
