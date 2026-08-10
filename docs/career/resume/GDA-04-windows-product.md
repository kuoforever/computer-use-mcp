# GDA-04 — Installed Windows product integration

> **Status: current candidate item; exact retained same-wheel application evidence.**
> Personal ownership: `TBC`. Submission-ready only after `My scope` is filled.

## Quick select

| Field | Guidance |
| --- | --- |
| Primary roles | Windows/client engineering, AI Agent product, end-to-end integration |
| Position | Lead |
| Evidence ceiling | One exact OpenAI/Windows/Notepad read-only path and one fixed Chrome-to-disposable-Word workflow |
| Use when | The JD mentions Windows, packaging, UI Automation, native integration, document workflows, or E2E verification |
| Skip when | The role is model-training-only or the bullet would be rewritten as general Office/browser automation |
| Exact JD keywords | `Windows`, `UI Automation`, `Win32`, `Python wheel`, `end-to-end`, `artifact verification`, `cleanup` |

## Resume copy

**Short ZH:** 将 Host/Runner/MCP 组装为 clean Windows wheel；同一构建版本
完成 Notepad 只读问答及固定 Chrome-to-Word 的
save/reopen/digest/cleanup 验证。

**Evidence-rich ZH:** 构建并验证可安装 Windows Agent wheel：同一 clean-wheel
构建版本先以 `document_text -> final_response` 完成 0-side-effect Notepad
问答，再通过单一 Runner/MCP 路径执行固定 Chrome-to-Word 工作流；主流程
15 tool calls / 5 side effects / 0 retries，保存、OOXML digest、独立 reopen/readback、
Completion Receipt 与精确窗口清理均通过。

**Short EN:** Built and validated a clean installable Windows agent wheel with
exact same-build evidence for a read-only Notepad query plus a fixed
Chrome-to-disposable-Word workflow.

**Evidence-rich EN:** Integrated the Agent Host, Runner, and installed sibling MCP
into one clean wheel, retaining exact Notepad read-only evidence and a fixed
Chrome-to-Word run with save, OOXML digest, independent reopen/readback,
completion receipt, and fixture cleanup.

**My scope to confirm:** Identify the packaging, workflow composition, observed
bug fix, native run, artifact verifier, cleanup, or evidence review you
personally performed.

## Fact card

| Dimension | Evidence-backed fact |
| --- | --- |
| Problem | Source tests do not prove an installed package can compose provider, Host, MCP, Windows, and application postconditions |
| Constraint | One supervised foreground desktop, exact launched-process identities, fixed source and disposable fixtures, no unrelated-window cleanup |
| Decision | Build once, run both paths from the same wheel, verify semantic state and durable artifacts rather than trust model prose |
| Read-only result | One `document_text` observation plus final response; 0 side effects, retries, and tool failures; exact Notepad cleanup |
| Side-effect result | Main Runner: 16 model turns, 15 tool calls, 5 side effects, 0 retries/failures; 17 total tool calls including reopen verifier |
| Durable proof | Pre/post-save semantic checks, DOCX digest/OOXML verification, independent reopen/readback, receipt, Task Center projection, exact fixture-window cleanup |

## Proof map

| Claim | Owner/evidence |
| --- | --- |
| Same-wheel environment and both results | [Current-candidate integration](../../CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md) |
| Earlier exact Desktop Ask record | [Desktop Ask evidence](../../DESKTOP_ASK_EVIDENCE.md) |
| Fixed workflow and Word evidence | [Public Web to Word evidence](../../PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) |

## Interview card

- **S:** unit tests could not establish installed entrypoints, real Windows
  focus, application postconditions, or durable document output.
- **T:** state the packaging, integration, debugging, or evidence scope you owned.
- **A:** use a clean wheel, exact fixtures/process identities, fresh observations,
  artifact digests, independent reopen, and cleanup verification.
- **R:** one same-wheel Notepad path and one fixed Chrome/Word path passed with
  zero retries/tool failures in their named runs.
- **Trade-off:** exact fixed fixtures make the result defensible but deliberately
  do not prove universal GUI or arbitrary Office automation.
- **Debug story:** a fast Chrome observation initially saw a loading URL rather
  than the reviewed title; the Host requested a fresh observation instead of
  relaxing title matching.

Deep-dive questions:

1. Why are save success and file existence insufficient without reopen/readback?
2. How did the workflow avoid closing a pre-existing Chrome or shared Word process?
3. Which parts are application evidence and which remain offline policy behavior?

## Claim limits

Do not claim arbitrary websites, general Notepad/Office automation, unattended
operation, background execution, universal GUI support, other providers/models,
E4 current-candidate coverage, or release readiness.
