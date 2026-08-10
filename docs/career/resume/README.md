# Resume evidence index

> **Status: current derived job-application view, reviewed against source
> baseline `50dad3b` on 2026-08-10.** Content schema: `2`.
> These items are not capability owners, a final resume, or proof of personal
> authorship.

## Reusable project block

**Project name:** Guarded Desktop Agent — safety-governed Windows GUI Agent

**Resume project summary (ZH):** Windows-first GUI Agent 运行时，以 Host-owned
policy/approval/WAL 和单一 Runner/MCP dispatch 边界约束模型工具调用，并按
证据维度区分 offline、provider、desktop 与 application 结果。

**Resume project summary (EN):** A Windows-first GUI agent runtime that
constrains model tool calls behind Host-owned policy, approval, WAL, and one
Runner/MCP dispatch boundary, with claims separated by evidence surface.

**30-second summary (ZH):** 一个 Windows-first、MCP-based 的实验性 GUI Agent
运行时，把 observation、model reasoning、Host authority、desktop execution、
durable evidence 与 operator control 分层；通过单一 Runner/MCP dispatch、
fail-closed recovery 和分级证据避免把模型建议或离线测试当成执行权限与线上能力。

**30-second summary (EN):** An experimental Windows-first GUI agent runtime
that separates observation, model reasoning, Host authority, desktop execution,
durable evidence, and operator control behind one safety-governed Runner/MCP
dispatch boundary.

**Evidence-backed stack:** Python 3.11-3.13, MCP, Windows UI Automation, Win32,
OpenAI/Anthropic-compatible provider adapters, pytest, Ruff, mypy, SQLite,
canonical JSON, WAL, CAS, and GitHub Actions.

Use only the technologies you can personally explain. A repository dependency
is not automatically an individual skill claim.

## Five-minute picker

`Lead` means the item can carry a project narrative. `Support` means it usually
needs a stronger product or systems result beside it. `TBC` means personal
ownership is not yet confirmed in this repository.

| ID | Highlight | Primary fit | Position | Evidence ceiling | Claim complexity | Ownership |
| --- | --- | --- | --- | --- | --- | --- |
| `GDA-01` | [Safety-governed Agent Runtime](GDA-01-safety-runtime.md) | AI Agent, Agent safety, LLM application | Lead | Offline plus selected exact provider/desktop/application paths | Medium | `TBC` |
| `GDA-02` | [Conservative recovery and synthetic duplicate suppression](GDA-02-crash-recovery.md) | Backend reliability, distributed state, recovery | Lead | Synthetic campaign benchmark plus separate offline Agent recovery contracts | Medium | `TBC` |
| `GDA-03` | [Provider-neutral regional routing](GDA-03-provider-routing.md) | LLM platform, provider integration | Lead | Nine profiles offline; narrower historical live scope | Medium | `TBC` |
| `GDA-04` | [Installed Windows product integration](GDA-04-windows-product.md) | Windows/client engineering, end-to-end Agent product | Lead | Exact retained same-wheel Notepad and Chrome/Word result | Medium | `TBC` |
| `GDA-05` | [Native operator UX and accessibility](GDA-05-operator-ux.md) | Windows UI, accessibility, HITL UX | Lead or support | Named native and human evidence only | High | `TBC` |
| `GDA-06` | [Deterministic hierarchical control](GDA-06-hierarchical-control.md) | Agent planning, state machines, concurrency | Lead | H1-H8 source/offline; H7 injected Runtime only | High | `TBC` |
| `GDA-07` | [Evidence-driven engineering](GDA-07-evidence-engineering.md) | Evaluation, QA, release engineering | Support by default | Repository-wide process and deterministic gates | Medium | `TBC` |
| `GDA-08` | [Verified adaptive routing](GDA-08-verified-adaptive-routing.md) | ML systems, safe adaptation, online-serving controls | Lead or support | L0-L4 offline plus one injected Runtime composition | High | `TBC` |

`Claim complexity` estimates how much context is needed to defend a statement;
it is not a page-length estimate. Determine rendered page cost only after the
short copy is placed in the real resume template, and keep each selected bullet
within two lines.

## Role recipes

Choose the resume project summary and normally two or three bullets. Use four
only when this is the sole or dominant project and the rendered one-page layout
still fits.

| Target role | Lead | Supporting choices | Emphasize |
| --- | --- | --- | --- |
| AI Agent / LLM application | GDA-01 or GDA-04 | GDA-03, 05, or 06 | Authority boundary plus one verified product path |
| Backend / reliability | GDA-02 | GDA-01, 06, 07, or 08 | Failure windows, durable state, certainty, rollback |
| LLM platform / provider integration | GDA-03 | GDA-01 and 07 | Exact identity, wire differences, regional isolation, live limits |
| Windows / client platform | GDA-04 | GDA-05 and GDA-01 | Packaging, native UI, accessibility, cleanup |
| Safety / evaluation / quality | GDA-01 or GDA-07 | GDA-02, 05, or 08 | Evidence levels, fail-closed behavior, negative results |
| Planning / ML systems | GDA-06, GDA-08, or both | GDA-01 and GDA-02 | Determinism, bounded concurrency, canary and rollback |

## Overlap and replacement rules

- `GDA-01 + GDA-02` is valid only when the first explains execution authority
  and the second explains crash/recovery windows; do not repeat “no replay.”
- `GDA-01 + GDA-07` usually overlap. Prefer GDA-01 for Agent/safety roles and
  GDA-07 for evaluation, QA, or release roles.
- `GDA-04 + GDA-05` is strongest for Windows/client/UX JDs; for backend roles,
  normally keep only GDA-04.
- `GDA-06 + GDA-08` can coexist for planning/ML-systems roles only when one
  covers deterministic control flow and the other covers evidence-gated
  strategy routing.
- `GDA-07` is normally a supporting bullet; do not let process language replace
  an implemented system or verified outcome.

## Selection workflow

1. Extract five to eight exact `must-have` and `preferred` JD phrases.
2. Rank items by role fit, evidence ceiling, confirmed personal contribution,
   uniqueness, claim complexity, and expected density.
3. Select two or three non-overlapping items and start with the short copy.
   Treat the evidence-rich draft inside each file as interview/portfolio
   material, not the one-page default.
4. Fill the item's `My scope` field with the work you can defend: design,
   implementation, tests, debugging, evidence collection, or documentation.
5. Open every linked owner/evidence source before submission and retain the
   stated limit in the wording.
6. Render the real resume. Shorten any bullet over two lines without deleting
   its evidence ceiling or turning a bounded result into a general claim.

## Evidence vocabulary

| Class or dimension | What it supports | What it does not support |
| --- | --- | --- |
| Implemented | Code and contract exist | Correctness or live behavior |
| Offline verified | Deterministic tests/gates passed | Provider, desktop, application, or human behavior |
| Provider verified | A named provider/model request passed | Desktop or application behavior |
| Desktop verified | A bounded native Windows path passed | General application coverage |
| Application verified | One named end-to-end application scope passed | Universal GUI or production deployment |
| Human verified | One named operator/UX/AT observation passed | Other people, settings, devices, locales, or environments |
| Release verified | Exact candidate release gates passed | A wider environment than the release record |

## Personal-ownership gate

Before copying any candidate bullet into a submitted resume, record privately:

- **My scope:** what you personally decided, implemented, tested, debugged, or
  verified.
- **Collaboration:** what coding agents, libraries, or other contributors did.
- **Defense:** which code path, failure window, trade-off, and evidence record
  you can explain without the repository open.

Until that check is complete, the wording is a project-level candidate, not a
personal claim.
