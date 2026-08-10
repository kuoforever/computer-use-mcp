# GDA-01 — Safety-governed Agent Runtime

> **Status: current candidate item; source baseline `50dad3b`.**
> Personal ownership: `TBC`. Submission-ready only after `My scope` is filled.

## Quick select

| Field | Guidance |
| --- | --- |
| Primary roles | AI Agent, LLM application, Agent platform, safety engineering |
| Position | Lead |
| Evidence ceiling | Implemented/offline verified; selected exact provider, desktop, and application paths are retained separately |
| Use when | The JD mentions tool calling, MCP, policy, grounding, HITL, safety, audit, or reliable execution |
| Skip when | The role is primarily model training or pure frontend and only one project bullet is available |
| Exact JD keywords | `tool calling`, `MCP`, `policy enforcement`, `grounding`, `human-in-the-loop`, `WAL`, `fail closed` |

## Resume copy

**Short ZH:** 为 Windows GUI Agent 构建 Host-owned 安全边界，将模型调用
视为不可信数据，经 schema、grounding、budget 与 approval 后仅由单一
Runner/MCP 路径执行。

**Evidence-rich ZH:** 构建 Windows GUI Agent 的 Host-owned 执行边界，以 13-core
reviewed tool registry 约束模型请求，并组合 schema validation、fresh
grounding、预算、审批、WAL 与 post-action observation；对可能已 dispatch 的
未知副作用进入 `UNKNOWN_OUTCOME`，禁止自动重放。

**Short EN:** Built a Host-owned safety boundary that compiles untrusted model
tool calls through reviewed schemas, policy, grounding, budgets, and approval
before one Runner/MCP dispatch path.

**Evidence-rich EN:** Built a safety-governed Windows GUI agent runtime around a
13-core reviewed tool registry, fresh grounding, budgets, approvals, WAL, and
post-action observation, with terminal no-replay handling for uncertain effects.

**My scope to confirm:** Which invariants, Runner/registry/policy/recovery code,
tests, or retained runs did you personally own? Use `designed` or `led` only for
the part you can defend.

## Fact card

| Dimension | Evidence-backed fact |
| --- | --- |
| Problem | Model output and visible UI content can request unsafe, stale, malformed, or out-of-scope work |
| Constraint | One shared foreground desktop, changing human input/focus, mutable MCP generation, and uncertain post-dispatch outcomes |
| Decision | Keep authority in the Host; separate semantic result from dispatch certainty; permit only one Runner/MCP dispatch site |
| Implementation | Reviewed schemas/effects, whole-turn validation, policy, fresh observation grounding, risk/approval, budget reservation, continuation WAL, post-action verification |
| Verified result | Deterministic E0-E2 gates cover denial, drift, human activity, e-stop, malformed calls, missing verification, and unknown outcomes; live evidence remains exact-scope only |

## Proof map

| Claim | Owner/evidence |
| --- | --- |
| Sole dispatch and untrusted model boundary | [Agent Host contract](../../AGENT.md#trust-boundaries-and-non-negotiable-rules) |
| Authorization sequence and mandatory verification | [Approved actions](../../APPROVALS.md#authorization-sequence) |
| Current evidence ceiling | [Capability dashboard](../../CAPABILITY_STATUS.md) |
| Earlier bounded isolated desktop cells | [E4 evidence](../../E4_EVIDENCE.md) |

## Interview card

- **S / Problem + constraint:** a model can emit a plausible call while desktop
  identity, approval evidence, or human-input state has already changed.
- **T / Objective + ownership:** identify the exact boundary you owned and the
  invariant it had to preserve.
- **A / Decision + implementation:** explain why schemas, policy, grounding,
  approval, WAL, and verification are separate gates rather than one boolean.
- **R / Verification + limit:** name one deterministic denial/uncertainty test
  and one exact live record; then state what remains unverified.
- **Trade-off:** fail-closed behavior reduces autonomous completion, but avoids
  inventing authority or duplicating an uncertain side effect.
- **Debug story:** contrast a failure before dispatch with a timeout or malformed
  result after dispatch; only the latter loses outcome certainty.

Deep-dive questions:

1. Why is an approval record an audit fact rather than permanent dispatch authority?
2. Why can a stale ref not silently degrade to coordinates?
3. Which invariants would break if Planner or recovery code added another MCP call site?

## Claim limits

Do not claim production deployment, universal GUI safety, zero incidents,
exactly-once effects, or provider/application coverage beyond named records.
The optional read-only browser observer does not widen the 13-core registry or
add browser action authority.
