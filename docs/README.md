# Documentation

The English documents in this directory are the canonical project
documentation. [README.zh-CN.md](../README.zh-CN.md) is a Chinese quick-start,
not a line-by-line mirror of every reference page.

## Status labels

- **Implemented** — present in the current codebase.
- **Experimental** — implemented but validated only in limited environments or
  applications.
- **Planned** — design direction or future work; do not rely on it at runtime.

## Start here

| Audience or question | Document |
| --- | --- |
| I want to install and run the server | [Root README](../README.md) |
| I need environment variables or safety behavior | [Configuration and safety](CONFIGURATION.md) |
| I need exact MCP tool parameters and behavior | [Tool reference](TOOLS.md) |
| I need the architecture and design decisions | [Design](DESIGN.md) |
| I am implementing a driver | [Driver Contract](DRIVER_CONTRACT.md) |
| I need the current stack and platform boundary | [Tech stack](TECH_STACK.md) |
| I am reviewing non-functional requirements | [Quality attributes](QUALITY_ATTRIBUTES.md) |
| I want to test or contribute | [Development](DEVELOPMENT.md) |
| I need completed work and remaining priorities | [Roadmap](EXECUTION_PLAN.md) |
| I need the planned full Agent Host scope and delivery gates | [Agent implementation plan](AGENT_IMPLEMENTATION_PLAN.md) |
| I am implementing or reviewing the Agent Host Phase 0-3 foundation and MCP bridge | [Agent Host contract](AGENT.md) and [evaluation contract](EVALUATION.md) |
| I need Agent checkpoint, trace redaction, or recovery rules | [Agent traces](TRACE.md) |
| I am designing broader crash resume without replay | [Persisted continuation](CONTINUATION.md) |
| I need context-budget or explicit-memory rules | [Agent context and memory](CONTEXT_MEMORY.md) |
| I am reviewing explicit OpenAI stateless replay | [Stateless replay](STATELESS_REPLAY.md) |
| I need day-scale batches, resumability, or cross-session handoff | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| I need real-application and enterprise workflow cases from BOSS/Docs/WeChat and Douyin through Office, ERP, CRM, ticketing, communication, identity, remote desktop, and legacy UI | [Application evaluation matrix](APPLICATION_EVALUATION_MATRIX.md) |
| I need model-token and observation-cost optimization | [Token efficiency](TOKEN_EFFICIENCY.md) |
| I am adding OCR, document text, image, or delta observations | [Observation contract](OBSERVATION_CONTRACT.md) |
| I am designing computer-use presence, progress, Decision Cards, or operator trade-offs | [Operator experience](OPERATOR_EXPERIENCE.md) |
| I am implementing the non-activating multi-run UI | [Operator progress viewer](PROGRESS_VIEWER.md) |
| I need sanitized findings from live desktop sessions | [Operator session notes](OPERATOR_SESSION_NOTES.md) |
| I need Host approval and action-grounding rules | [Approved actions](APPROVALS.md) |
| I need to execute or review isolated Agent desktop smokes | [E4 smoke runbook](E4_SMOKE.md) |
| I need CI gates or the release checklist | [Release and operator checklist](RELEASE.md) |
| I need to record a release review or explicit waiver | [Release evidence record](RELEASE_EVIDENCE.md) |
| I am taking over maintenance | [Maintainer handoff](../HANDOFF.md) |

## Documentation ownership

| Document | Owns |
| --- | --- |
| Root README | Current product scope, safe quick start, and high-level limitations |
| Configuration and safety | Runtime modes, environment variables, and guard behavior |
| Tool reference | Public MCP tool surface and result semantics |
| Design | Component boundaries and long-lived technical decisions |
| Driver Contract | The normative shared-core/driver interface |
| Tech stack | Current dependencies and planned platform/runtime choices |
| Quality attributes | Review and acceptance criteria |
| Roadmap | Completed milestones and future priorities |
| Agent implementation plan | Planned dual-provider Agent Host, safety boundaries, and release gates |
| Agent Host contract / evaluation | Implemented provider-neutral foundation, desktop bridge, trust boundaries, and evaluation gates |
| Agent traces | Atomic safe checkpoints, JSONL redaction, phase transitions, inspection, and conservative recovery |
| Persisted continuation | Private v2 storage with correlated OpenAI recovery token state, opt-in write-ahead boundaries, conservative classification, and a locked 1-4 step read-only CLI gate including completed-side-effect mandatory observation |
| Agent context and memory | Provider-view reduction, explicit SQLite memory, expiry, deletion, and rejection rules |
| Stateless replay | Provider continuation strategies, explicit OpenAI replay contract, and mandatory activation invariants |
| Task planning | Non-executable TaskPlan contract, strict candidate compiler, and ordered local transitions |
| Long-running tasks | Campaigns, item ledgers, batches, resumability, liveness, and deterministic cross-session handoff |
| Application evaluation matrix | Staged real-application workloads, failure-mechanism coverage scoring, cross-application cases, and promotion gates |
| Token efficiency | Observation escalation, image/delta policy, item-local context, batching, and cost measurement |
| Observation contract | Planned UIA, document-text, OCR, image, and delta observation envelope and grounding rules |
| Operator experience | Planned desktop presence indicator, passive progress, Decision Cards, trade-off provenance, and operator-interaction boundaries |
| Operator progress viewer | Checkpoint projection, non-activating window behavior, multi-run grouping, and acceptance checks |
| Operator session notes | Sanitized cross-session evidence and live desktop regressions |
| Approved actions | Opt-in local approval, grounding, budgets, re-observation, and current validation boundary |
| E4 smoke runbook | Isolated environment prerequisites, dual-provider acceptance matrix, fail-closed execution, and sanitized evidence |
| Release checklist | Automated CI, human E3/E4 gates, operator checks, disablement, and release boundary |
| Release evidence record | Per-candidate automated evidence, E3/E4 results, waivers, classification, and human decision |
| Development / handoff | Test practice and maintainer-only operational knowledge |

Do not use the roadmap or design documents to infer that a capability is
available. The root README, configuration page, and tool reference describe the
current runtime surface.
