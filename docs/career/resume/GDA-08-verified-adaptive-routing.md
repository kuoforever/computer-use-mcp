# GDA-08 — Verified adaptive routing with bounded canary rollback

> **Status: current candidate item; L0-L4 are offline/injected verified.**
> No model training, automatic promotion, or live application improvement is
> claimed. Personal ownership: `TBC`.
> Submission-ready only after `My scope` is filled.

## Quick select

| Field | Guidance |
| --- | --- |
| Primary roles | ML systems, safe adaptation, Agent infrastructure, backend reliability |
| Position | Lead or support |
| Evidence ceiling | L0-L3 offline data/evaluation plus L4 deterministic state and one injected isolated Runtime composition |
| Use when | The JD mentions online serving, shadow evaluation, canary, rollback, policy routing, or safe continual improvement |
| Skip when | The role expects actual fine-tuning/RL results or live production lift |
| Exact JD keywords | `shadow evaluation`, `canary rollout`, `rollback`, `policy routing`, `drift detection`, `verified outcome`, `ML systems` |

## Resume copy

**Short ZH:** 离线实现并验证 adaptive routing：exact shadow、LOW-only
canary、crash blocking，首个 hard-gate regression 永久 rollback；Runtime
仅有 injected evidence。

**Evidence-rich ZH:** 实现 verified improvement control plane：从 Host-validated
episode/cost evidence 提取隔离候选，经 content-free procedure lifecycle、
held-out replay 与 exact-equivalence shadow scoring 后，仅在 task/application/
policy/registry/precondition/action-risk digests 全匹配时进入 persistent
prefix-safe canary；crash-pending 阻止新选择，首个 hard-gate regression 回退到
exact ACTIVE pin。

**Short EN:** Built and offline-verified evidence-gated adaptive routing with
exact shadow equivalence, LOW-only canaries, crash blocking, and permanent
rollback; runtime composition evidence remains injected-only.

**Evidence-rich EN:** Implemented L0-L4 verified adaptation from redacted outcomes
through quarantined evidence, reviewed procedures, deterministic shadow
comparison, and exact-context canary routing, without automatic promotion,
retry, replay, or model training.

**My scope to confirm:** Identify the outcome normalization, quarantine,
procedure lifecycle, shadow scoring, canary store/policy, H7 binding, tests, or
evidence you personally owned.

## Fact card

| Phase | Evidence-backed fact |
| --- | --- |
| L0 | Normalize only validated redacted outcomes and explicit cost coverage; no export or learning authority |
| L1 | Quarantine fresh boolean/integer candidate facts in a separate private lifecycle; no memory injection |
| L2 | Use content-free procedures, disjoint held-out fixtures, reviewed lifecycle, and exact rollback pins |
| L3 | Compare only exact-equivalent ACTIVE/SHADOW evidence with visible reward vectors and deterministic strict-improvement recommendation |
| L4 policy | At least one baseline warmup; at most one candidate per ten eligible LOW decisions; cap 32; one pending decision; completion does not activate |
| Permanent rollback | Non-success, unknown outcome, missing verification, safety/authority regression, or approval/authority-gate change selects the exact ACTIVE pin permanently |
| Fallback and close | Candidate evidence, expiry, equivalence, suite, or rollback-pin drift permits one exact ACTIVE fallback decision and closes the rollout |
| No selection or transition | ACTIVE/context drift makes no selection; a forged outcome/procedure/context digest is rejected without a state transition |
| Runtime ceiling | One injected production-Runner composition routed selection ten to a reviewed `find -> click -> ui_snapshot` candidate; no real provider/MCP/desktop/application |

## Proof map

| Claim | Owner/evidence |
| --- | --- |
| L0-L4 architecture, lifecycle, and limits | [Continual learning owner](../../CONTINUAL_LEARNING.md) |
| Canary policy, persistence, rollback matrix, and injected composition | [L4 adaptive-routing evidence](../../L4_BOUNDED_ADAPTIVE_ROUTING_EVIDENCE.md) |
| Current evidence ceiling and L5 state | [Capability dashboard](../../CAPABILITY_STATUS.md) |
| Merge/gate chronology | [Archived closure snapshot](../../archive/PROJECT_STATUS_SNAPSHOT_2026-08-11.md#closure-backlog) |

## Interview card

- **S:** repeated success should improve routing without turning historical data
  or a score into execution authority.
- **T:** state the evidence, evaluation, routing, persistence, or test slice you owned.
- **A:** require exact equivalence and context/action-risk binding, route only a
  small LOW-risk prefix, persist one pending decision, and fail back to ACTIVE.
- **R:** deterministic gates cover canary bounds, crash-pending stop, tamper,
  drift, every rollback condition, and one injected Runner composition.
- **Trade-off:** conservative equivalence and LOW-only routing sharply limit
  learning coverage but preserve the existing policy/approval/verification path.
- **Debug story:** if a process crashes after route persistence but before
  outcome reconciliation, the next decision returns `ADAPTIVE_OUTCOME_REQUIRED`
  instead of resetting counters or choosing again.

Deep-dive questions:

1. Why is an L3 recommendation data rather than a routing decision?
2. Why does canary completion not promote the SHADOW procedure to ACTIVE?
3. Which context digests prevent a cheap strategy from leaking into a different task or action?

## Claim limits

Do not call this model fine-tuning, reinforcement learning, online learning,
automatic memory, general procedure synthesis, or production A/B testing. No
real provider, MCP process, Windows desktop, external application, E4, release,
or measured user-impact improvement is retained. L5 remains separately
consented and inactive.
