# GDA-03 — Provider-neutral and region-bound LLM routing

> **Status: current candidate resume item; added-provider live gates are deferred.**

- **JD tags:** LLM platform, provider abstraction, OpenAI, Anthropic, Qwen,
  Doubao, Kimi, DeepSeek, GLM, MiniMax, schema validation, regional routing.
- **Candidate bullet (ZH):** 实现覆盖 8 个精确 provider profile、3 类 wire
  protocol 与 allowlisted service region 的统一 Host 路由，隔离区域凭据、端点、
  capability 和 continuation identity，并以严格迁移与无跨区 fallback 保持恢复
  身份一致。
- **Candidate bullet (EN):** Implemented unified Host routing for eight exact
  provider profiles across three wire protocols and allowlisted service
  regions, isolating credentials, endpoints, capabilities, and continuation
  identity with no cross-region fallback.
- **Evidence level:** implementation and offline gate complete as of 2026-08-10;
  live evidence remains limited to earlier OpenAI/Claude scopes.
- **Sources:** [provider contract](../../PROVIDERS.md),
  [capability dashboard](../../CAPABILITY_STATUS.md), and
  [project status](../../../PROJECT_STATUS.md).
- **Do not claim:** that all eight providers/regions made live API requests, or
  that offline compatibility equals production compatibility.
- **Interview expansion:** discuss structured-output differences, credential
  isolation, continuation migration, and why silent regional fallback is unsafe.
