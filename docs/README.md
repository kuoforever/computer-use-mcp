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
| I need context-budget or explicit-memory rules | [Agent context and memory](CONTEXT_MEMORY.md) |
| I need Host approval and action-grounding rules | [Approved actions](APPROVALS.md) |
| I need CI gates or the release checklist | [Release and operator checklist](RELEASE.md) |
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
| Agent context and memory | Provider-view reduction, explicit SQLite memory, expiry, deletion, and rejection rules |
| Approved actions | Opt-in local approval, grounding, budgets, re-observation, and current validation boundary |
| Release checklist | Automated CI, human E3/E4 gates, operator checks, disablement, and release boundary |
| Development / handoff | Test practice and maintainer-only operational knowledge |

Do not use the roadmap or design documents to infer that a capability is
available. The root README, configuration page, and tool reference describe the
current runtime surface.
