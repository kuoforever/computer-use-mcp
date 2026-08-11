# GDA-03 — Provider-neutral and region-bound LLM routing

> **Status: current candidate item; nine exact profiles are offline verified.**
> Added cloud routes/regions and local E3 remain deferred.
> Personal ownership: `TBC`. Submission-ready only after `My scope` is filled.

## Quick select

| Field | Guidance |
| --- | --- |
| Primary roles | LLM platform, AI infrastructure, provider integration, backend |
| Position | Lead |
| Evidence ceiling | Eight cloud profiles plus one loopback-only local profile offline; live evidence remains narrower |
| Use when | The JD mentions multi-provider routing, SDK adapters, structured output, credentials, regions, or local inference |
| Skip when | The wording cannot retain the offline/live distinction |
| Exact JD keywords | `provider abstraction`, `Responses API`, `Chat Completions`, `Messages`, `structured output`, `regional routing`, `credential isolation` |

## Resume copy

**Short ZH:** 离线实现并验证 9 个 LLM profiles（8 cloud + 1 loopback
local）的统一 routing，隔离 region/credential/capability/continuation
identity，禁止 silent fallback。

**Evidence-rich ZH:** 构建 catalog-backed provider factory，覆盖 OpenAI、Anthropic、
Qwen、Doubao、Kimi、DeepSeek、GLM、MiniMax 与严格 loopback-only
`local_openai`；通过 15 个 allowlisted route entries、provider-specific
structured output、credential isolation 和 continuation v8 保持跨区域/协议恢复
身份一致，未验证的 local native tool calling 在 client construction 前 fail closed。

**Short EN:** Implemented and offline-verified Host routing for nine exact LLM
profiles across three wire families, with explicit region, credential,
endpoint, capability, and continuation identity.

**Evidence-rich EN:** Built a catalog-backed provider factory for eight cloud
profiles and one strict loopback-only local profile, isolating regional routes,
credentials, structured-output modes, modalities, and continuation v8 identity
without cross-region or endpoint fallback.

**My scope to confirm:** Identify the catalog/factory, adapter, migration,
configuration, tests, or provider evidence you personally owned. Do not infer
live-provider work from offline adapters.

## Fact card

| Dimension | Evidence-backed fact |
| --- | --- |
| Problem | Wire compatibility can hide different vendor identity, credentials, modalities, schema modes, and continuation semantics |
| Constraint | Regional accounts and model availability differ; local servers expose dynamic endpoints but must not become arbitrary proxies |
| Decision | Keep exact profile identity; use typed allowlisted regions; bind provider/model/protocol/region/effective endpoint into continuation |
| Implementation | Responses, Chat Completions, and Messages adapters; strict Host validation; provider-specific credentials; 15 route entries; literal-loopback local URL parser |
| Verified result | Nine profiles pass offline construction, routing, migration, capability, request-bound, secret-isolation, and recovery-binding gates |
| Live ceiling | Retained credentialed evidence covers exact Kimi, MiniMax, and GLM China, DeepSeek global, and Doubao plus Qwen Beijing candidates in addition to earlier OpenAI/Claude; sibling routes/models, other candidates, E4, applications, and local E3 remain unverified |

## Proof map

| Claim | Owner/evidence |
| --- | --- |
| Current matrix and 15 route entries | [Provider support](../../PROVIDERS.md#support-matrix) |
| Exact implemented/live boundary | [Capability dashboard](../../CAPABILITY_STATUS.md) |
| Merge chronology and current exact-next state | [Archived closure snapshot](../../archive/PROJECT_STATUS_SNAPSHOT_2026-08-11.md#closure-backlog); [current project status](../../../PROJECT_STATUS.md) |

## Interview card

- **S:** compatible wire formats tempt a platform to alias identity and silently
  route across vendors or regions.
- **T:** state the provider/catalog/adapter/config/test scope you owned.
- **A:** bind identity and capabilities explicitly, compile structured output
  locally, isolate credentials, and reject unsupported modality/tool routes.
- **R:** nine exact profiles and 15 reviewed routes pass offline gates; six
  exact added-provider candidates now have bounded retained live E3 evidence.
- **Trade-off:** no automatic fallback reduces availability but prevents
  credential, residency, billing, and recovery identity drift.
- **Debug story:** explain why local ordinary tool calling returns
  `PROVIDER_TOOL_CALLING_UNVERIFIED` before SDK construction rather than hoping
  an OpenAI-compatible server behaves identically.

Deep-dive questions:

1. Which behaviors belong to wire-family adapters and which belong to exact provider profiles?
2. How does continuation v8 prevent cross-region recovery?
3. Why does prompt-only JSON still require strict Host compilation?

## Claim limits

Do not claim nine live integrations, all vendor regions, named local
server/model compatibility, arbitrary proxy support, or production readiness.
Passing one provider/model/region does not promote a sibling route.
