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
| I am inspecting the frozen Full Cycle Runtime baseline or intentionally reopening work | [Project status](../PROJECT_STATUS.md) |
| I am integrating this Runtime with the Multimodal LLM Full Cycle project | [Full Cycle integration](FULLCYCLE_INTEGRATION.md) |
| I need the complete project map: features, implementation, quality attributes, status, evidence, and next gates | [Project overview](PROJECT_OVERVIEW.md) |
| I need the current product names and compatibility aliases | [Naming migration](BRAND_MIGRATION.md) |
| I want to install and run the server | [Root README](../README.md) |
| I need the shortest implemented/evidence/next-gate view | [Capability status](CAPABILITY_STATUS.md) |
| I need environment variables or safety behavior | [Configuration and safety](CONFIGURATION.md) |
| I need exact MCP tool parameters and behavior | [Tool reference](TOOLS.md) |
| I need the architecture and design decisions | [Design](DESIGN.md) |
| I want to know why a specific safety rule exists, and what was rejected | [Architecture decision records](adr/) |
| I want a worked failure analysis with root cause and detection gap | [Postmortems](postmortems/) |
| I want to know how coding agents are used here and who is responsible | [AI-assisted development](AI_ASSISTED_DEVELOPMENT.md) |
| I am implementing a driver | [Driver Contract](DRIVER_CONTRACT.md) |
| I need the current stack and platform boundary | [Tech stack](TECH_STACK.md) |
| I am reviewing non-functional requirements | [Quality attributes](QUALITY_ATTRIBUTES.md) |
| I want to test or contribute | [Development](DEVELOPMENT.md) |
| I need completed work and remaining priorities | [Roadmap](EXECUTION_PLAN.md) |
| I need the planned full Agent Host scope and delivery gates | [Agent implementation plan](AGENT_IMPLEMENTATION_PLAN.md) |
| I am implementing or reviewing the Agent Host Phase 0-3 foundation and MCP bridge | [Agent Host contract](AGENT.md) and [evaluation contract](EVALUATION.md) |
| I am reviewing declarative TaskPlan, Planner, Executor, WAL, or reconciliation contracts | [Task planning](PLANNING.md) |
| I am designing hierarchical task state, conditional branches, or reusable behavior trees | [Hierarchical task and behavior trees](HIERARCHICAL_TASK_AND_BEHAVIOR_TREES.md) |
| I need Agent checkpoint, trace redaction, or recovery rules | [Agent traces](TRACE.md) |
| I am adding telemetry, or need the observation-vs-authority boundary | [Telemetry contract](TELEMETRY.md) |
| I am designing broader crash resume without replay | [Persisted continuation](CONTINUATION.md) |
| I am evaluating an external workflow engine for scheduling | [Temporal proof of concept](TEMPORAL_POC.md) |
| I need context-budget or explicit-memory rules | [Agent context and memory](CONTEXT_MEMORY.md) |
| I need local text or screenshot pseudonymization before provider dispatch | [Local privacy boundary](LOCAL_PRIVACY.md) |
| I am designing long-term learning from outcomes, corrections, and cost | [Continual learning](CONTINUAL_LEARNING.md) |
| I am reviewing explicit OpenAI stateless replay | [Stateless replay](STATELESS_REPLAY.md) |
| I need day-scale batches, resumability, or cross-session handoff | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| I need accurate Codex/Claude completion polling before a host sends a mobile notification | [Long-running tasks](LONG_RUNNING_TASKS.md#host-visible-completion-and-mobile-notification) and [Operator experience](OPERATOR_EXPERIENCE.md#remote-and-mobile-notification-semantics) |
| I need real-application and enterprise workflow cases from BOSS/Docs/WeChat and Douyin through Office, ERP, CRM, ticketing, communication, identity, remote desktop, and legacy UI | [Application evaluation matrix](APPLICATION_EVALUATION_MATRIX.md) |
| I need the clean fixed-code BOSS multi-item restart result | [BOSS clean item/restart evidence](BOSS_ITEM_RESTART_CLEAN_EVIDENCE.md) |
| I am implementing the bounded BOSS semantic result or per-item observation ladder | [BOSS semantic extraction contract](BOSS_SEMANTIC_EXTRACTION_CONTRACT.md) |
| I need the latest partial BOSS item/restart diagnostic | [BOSS item/restart diagnostic evidence](BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md) |
| I need the one-campaign complete-product showcase and evidence plan | [Universal GUI demo](UNIVERSAL_GUI_DEMO.md) |
| I need the retained bounded Chrome-to-Word GUI Demo result | [Cross-application Demo evidence](CROSS_APP_DEMO_EVIDENCE.md) |
| I am running or reviewing the model-driven bounded Demo | [Model-driven Demo contract](MODEL_DRIVEN_DEMO.md) |
| I need the retained public-web-to-Word Demo with approval heartbeat | [Public-web Word Demo evidence](PUBLIC_WEB_WORD_DEMO_EVIDENCE.md) |
| I need model-token and observation-cost optimization | [Token efficiency](TOKEN_EFFICIENCY.md) |
| I am adding OCR, document text, image, or delta observations | [Observation contract](OBSERVATION_CONTRACT.md) |
| I am designing computer-use presence, progress, Decision Cards, or operator trade-offs | [Operator experience](OPERATOR_EXPERIENCE.md) |
| I am implementing the non-activating multi-run UI | [Operator progress viewer](PROGRESS_VIEWER.md) |
| I need the retained isolated Decision Card and workflow Progress HUD images | [Operator HUD visual evidence, 2026-08-01](OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md); the superseded presentation is retained in [the 2026-07-30 record](OPERATOR_HUD_VISUAL_EVIDENCE.md) |
| I need the post-fix complete Operator HUD Demo result | [Post-fix Operator HUD Demo evidence, 2026-08-03](OPERATOR_HUD_DEMO_EVIDENCE_2026-08-03.md) |
| I need Decision Card evidence at 100%, 125%, and 150% scaling | [100%/125% live DPI acceptance, 2026-08-03](OPERATOR_HUD_DPI_EVIDENCE_2026-08-03.md); [150% visual evidence, 2026-08-01](OPERATOR_HUD_VISUAL_EVIDENCE_2026-08-01.md) |
| I need the physical Alt+Tab acceptance result | [Decision Card keyboard evidence, 2026-08-03](OPERATOR_HUD_KEYBOARD_EVIDENCE_2026-08-03.md) |
| I need sanitized findings from live desktop sessions | [Operator session notes](OPERATOR_SESSION_NOTES.md) |
| I need the retained bounded BOSS MCP observation | [BOSS observation evidence](BOSS_EVIDENCE.md) |
| I need the retained BOSS static-content OCR result | [BOSS OCR evidence](BOSS_OCR_EVIDENCE.md) |
| I need the retained on-device UIA semantic-text result | [Document-text evidence](DOCUMENT_TEXT_EVIDENCE.md) |
| I need the retained on-device bounded region-capture result | [Region-capture evidence](CAPTURE_REGION_EVIDENCE.md) |
| I need the retained one-page BOSS campaign discovery result | [BOSS campaign discovery evidence](BOSS_CAMPAIGN_DISCOVERY_EVIDENCE.md) |
| I need the retained current-contract multi-pass BOSS discovery result | [BOSS multi-pass discovery evidence](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md) |
| I need the retained on-device synthetic campaign result | [Synthetic campaign evidence](SYNTHETIC_CAMPAIGN_EVIDENCE.md) |
| I need the native synthetic campaign progress-window result | [Campaign progress lifecycle evidence](CAMPAIGN_PROGRESS_LIFECYCLE_EVIDENCE.md) |
| I need the native bounded-plan progress-window result | [Bounded plan progress lifecycle evidence](PLAN_PROGRESS_LIFECYCLE_EVIDENCE.md) |
| I need the native bounded-plan presence-halo result | [Bounded plan presence lifecycle evidence](PLAN_PRESENCE_LIFECYCLE_EVIDENCE.md) |
| I need the native read-only recovery progress-window result | [Recovery progress lifecycle evidence](RECOVERY_PROGRESS_LIFECYCLE_EVIDENCE.md) |
| I need the 100-item forced-restart reliability result | [Reliability benchmark evidence](benchmark/README.md) |
| I need Host permission modes, approval, and action-grounding rules | [Action authorization](APPROVALS.md) |
| I need to execute or review isolated Agent desktop smokes | [E4 smoke runbook](E4_SMOKE.md) |
| I need the retained sanitized isolated desktop outcomes | [E4 evidence](E4_EVIDENCE.md) |
| I need the retained sanitized provider integration outcomes | [Provider E3 evidence](E3_EVIDENCE.md) |
| I need CI gates or the release checklist | [Release and operator checklist](RELEASE.md) |
| I need to report a vulnerability or read the threat-model boundary | [Security policy](../SECURITY.md) |
| I need what changed in a packaged version | [Changelog](../CHANGELOG.md) |
| I need to record a release review or explicit waiver | [Release evidence record](RELEASE_EVIDENCE.md) |
| I am taking over maintenance | [Maintainer handoff](../HANDOFF.md) |

## Documentation ownership

| Document | Owns |
| --- | --- |
| Project status | Frozen closure backlog, reactivation rule, session protocol, and freeze scope |
| Full Cycle integration | Runtime/model-factory ownership boundary, safe export schema, rich-capture boundary, and closure gates |
| Project overview | Cross-system project shape, exhaustive feature-family inventory, implementation map, quality-attribute mapping, and role-based reading paths |
| Root README | Current product scope, safe quick start, and high-level limitations |
| Capability status | Cross-surface implementation state, retained evidence level, and next executable gate |
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
| Local privacy boundary | One disabled-by-default package for run-scoped PII tokens, local screenshot redaction, non-restorable secrets, local resolution sinks, and deferred non-text visual backends |
| Continual learning | Planned four-layer memory, verified workflow promotion, cost-aware strategy selection, rollback, and deferred model-learning boundary |
| Stateless replay | Provider continuation strategies, explicit OpenAI replay contract, and mandatory activation invariants |
| Task planning | Strict TaskPlan/Planner contracts, local WAL/reconciliation, and the bounded observation-only `plan run` composition |
| Hierarchical task and behavior trees | Planned post-linear task hierarchy, reviewed behavior templates, typed conditions, fail-closed propagation, persistence, and delivery order |
| Long-running tasks | Campaigns, item ledgers, batches, resumability, liveness, deterministic cross-session handoff, and the planned host-terminal polling contract |
| Application evaluation matrix | Staged real-application workloads, failure-mechanism coverage scoring, cross-application cases, and promotion gates |
| Universal GUI demo | One-campaign chapter plan spanning all mechanism families, fault injection, operator UX, token evidence, and presentation cuts |
| Token efficiency | Observation escalation, image/delta policy, item-local context, batching, and cost measurement |
| Observation contract | Planned UIA, document-text, OCR, image, and delta observation envelope and grounding rules |
| Operator experience | Implemented passive progress with opt-in ordinary-run, bounded-plan, read-only recovery, and fixed MCP-backed campaign execution lifecycle wiring; zero-port campaign control remains window-free. Ordinary-run, one provider-free bounded plan, one persisted read-only recovery observation, and the fixed synthetic campaign have native progress lifecycle evidence. Opt-in durable ordinary-run/bounded-plan/read-only-recovery/fixed-campaign presence and a focus-taking four-choice Win32 Decision Card with expandable digest evidence also exist; bounded-plan presence has native evidence, while recovery and BOSS campaign presence plus same-run re-observe/durable defer remain offline verified and host-owned mobile notification remains planned |
| Operator progress viewer | Checkpoint projection, non-activating window behavior, multi-run grouping, and acceptance checks |
| Operator session notes | Sanitized cross-session evidence and live desktop regressions |
| Action authorization | Project-wide read-only, per-action approval, or agentic reviewed-action modes; grounding, budgets, re-observation, and current validation boundary |
| E4 smoke runbook | Isolated environment prerequisites, dual-provider acceptance matrix, fail-closed execution, and sanitized evidence |
| E4 evidence | Reviewed VM/model scope, activation regression, four provider cells, approvals, and sanitized trace hashes |
| Provider E3 evidence | Per-provider bounded live-API outcomes and the remaining dual-provider promotion boundary |
| Release checklist | Automated CI, human E3/E4 gates, operator checks, disablement, and release boundary |
| Release evidence record | Per-candidate automated evidence, E3/E4 results, waivers, classification, and human decision |
| Development / handoff | Test practice and maintainer-only operational knowledge |

## Archive policy

Files under [the archive](archive/README.md) preserve superseded plans and
implementation chronology.
They are non-normative, are not part of the start-here path, and must link back
to the current owner document. Do not update an archived snapshot to describe
new behavior and do not cite it as current capability evidence.

Do not use the roadmap or design documents to infer that a capability is
available. The root README, configuration page, and tool reference describe the
current runtime surface.
