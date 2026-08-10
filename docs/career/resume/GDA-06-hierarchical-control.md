# GDA-06 — Hierarchical control with bounded concurrency

> **Status: current candidate resume item; H1-H8 are offline verified.**

- **JD tags:** planning, behavior tree, DAG, concurrency, deterministic state,
  scheduling, CAS.
- **Candidate bullet (ZH):** 实现 H1-H8 immutable task/behavior-tree contracts，
  通过 canonical digest、typed fresh facts、bounded parallel condition
  evaluation、dependency join、Host-ordered safe choice 与单次 CAS 保持确定性和
  fail-closed 状态归约。
- **Candidate bullet (EN):** Implemented H1-H8 immutable task/behavior-tree
  contracts with canonical digests, freshness-bound facts, bounded parallel
  condition evaluation, dependency joins, Host-ordered choice, and atomic CAS.
- **Evidence level:** implemented and offline verified; widened external Runtime
  scope remains deliberately narrow.
- **Sources:** [hierarchical control](../../HIERARCHICAL_TASK_AND_BEHAVIOR_TREES.md),
  [H8A](../../H8A_PARALLEL_CONDITION_EVIDENCE.md),
  [H8B](../../H8B_DEPENDENCY_JOIN_EVIDENCE.md), and
  [H8C](../../H8C_SAFE_CHOICE_EVIDENCE.md).
- **Do not claim:** Multi-Agent operation, distributed workers, general autonomy,
  or live application acceptance for H8.
- **Interview expansion:** explain deterministic selection under concurrent fact
  evaluation, unavailable-vs-false semantics, and serialized external effects.
