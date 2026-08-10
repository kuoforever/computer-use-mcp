# GDA-01 — Safety-governed Agent Runtime

> **Status: current candidate resume item; evidence must be rechecked before use.**

- **JD tags:** AI Agent, LLM application, tool calling, safety, policy,
  human-in-the-loop, MCP.
- **Candidate bullet (ZH):** 为 Windows GUI Agent 设计 Host-owned 执行边界，
  将模型输出按不可信数据处理，并通过 typed tool registry、grounding、预算、
  审批与 `UNKNOWN_OUTCOME` 禁止自动重放约束所有副作用进入唯一 Runner/MCP
  dispatch path。
- **Candidate bullet (EN):** Designed a Host-owned execution boundary for a
  Windows GUI agent, compiling untrusted model output through typed tools,
  grounding, budgets, approvals, and no-replay handling for uncertain effects.
- **Evidence level:** implemented and offline verified; selected exact provider,
  desktop, and application paths are separately retained.
- **Sources:** [Agent Host](../../AGENT.md), [approved actions](../../APPROVALS.md),
  [capability dashboard](../../CAPABILITY_STATUS.md), and
  [E4 evidence](../../E4_EVIDENCE.md).
- **Do not claim:** production deployment, universal GUI safety, zero incidents,
  or provider/application coverage beyond the named records.
- **Interview expansion:** explain why model output is data rather than
  authority, why stale refs cannot degrade to coordinates, and why an unknown
  side-effect outcome differs from a normal failure.
