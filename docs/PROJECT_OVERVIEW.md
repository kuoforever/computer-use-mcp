# Project overview

> **Status: canonical orientation map, verified against the repository on
> 2026-08-27.** This page explains the complete project shape without promoting
> planned work to runtime capability. Exact behavior remains owned by the
> linked contract documents; current evidence remains owned by
> [Capability status](CAPABILITY_STATUS.md).

## One-minute summary

Guarded Desktop Agent (formerly `computer-use-mcp`) is evolving from a
model-agnostic Windows desktop MCP server
into a locally governed universal GUI Agent system. The project currently has
four distinct maturity layers:

1. **Windows desktop MCP runtime — implemented:** thirteen core stdio tools combine
   UI Automation, primary-display screenshots, native input/window control,
   safety gates, audit logging, and an emergency stop. User-configured
   Playwright CDP can add one read-only rendered-browser observation tool.
2. **Agent Host — experimental and partially integrated:** a CLI can run bounded
   workflows through eight exact cloud profiles plus one loopback-only local
   Planner/final profile and the same MCP server. It adds
   policy, grounding, budgets, explicit approval, redacted trace/reporting,
   explicit memory, and conservative crash recovery.
3. **Planner/Executor and Campaign control plane — substantial internal/offline
   implementation:** strict planning, WAL-backed observation/final-response
   boundaries, campaign ledgers, leases, heartbeat, handoff, and reconciliation
   exist. Fixed synthetic and discovery paths plus a manifest-routed general
   campaign worker are implemented internally; the general worker remains
   offline-only, with no generic real-application acceptance or complete
   application product claim.
4. **Complete-product layers — bounded programs implemented, broader acceptance
   incomplete:** hierarchical H1-H8 and continual-learning L0-L4 are
   implemented at their documented offline or injected-runtime scopes.
   Multi-source observation, operator UI, mobile-completion projection, and
   broad application campaigns remain partial; isolated workers, additional
   platforms, the complete Formal Demo v1 front door and application adapters,
   complete real-application acceptance, the Universal GUI final
   showcase, and L5 remain planned or inactive at their documented evidence
   levels. One independent Review-only Formal Demo Console now exists, but it
   stops at an inert permit with Scope unavailable and `Start` disabled.

The central engineering idea is not “let a model click anywhere.” It is to
separate observation, reasoning, authority, execution, durable evidence, and
operator control so each layer can be bounded and verified independently.

## Product boundary

The selected future [Formal Demo v1](FORMAL_DEMO_V1.md) product story is an
independently launched GitHub Issues, PDF, Excel, Word, and unsent test-email
workflow. Its internal inert v1 `TaskIntent`, scenario/profile, generic Scope,
exact-pin/digest, pure-local typed intent-disclosure/permit contracts, and
provider-neutral one-attempt intent coordinator are implemented offline only.
The coordinator is exercised through injected deterministic fakes and has no
concrete provider, credential, configuration, environment, or network wiring.
An independent Review-only Windows Console/launcher now collects one in-memory
draft, shows the exact operator-selected model plus reviewed route/profile
disclosure without implying readiness, and issues one inert permit;
it reads no Agent config, credential, or provider environment, reports Scope
unavailable, and keeps `Start` disabled. The live provider intent adapter/call,
permit consumption, positive built-in Scope, executable application adapters,
durable composition, and formal evidence do not exist yet. BOSS,
Google Docs, and WeChat instead belong to independent
[Application Coverage Set A](APPLICATION_EVALUATION_MATRIX.md); coverage cases
do not define the product Demo or operational priority. The still broader
[Universal GUI program](UNIVERSAL_GUI_DEMO.md) is a future final integration
showcase, not either of those two programs.

The long-term intended product is a universal GUI execution system where
pixels remain the universal fallback and structured sources improve reliability
when available. That intent is not a current universal-GUI capability claim.

The project is currently:

- local and Windows-first;
- model-agnostic at the MCP boundary;
- nine-profile and three-wire-family at the experimental Agent Host boundary;
- explicit about foreground ownership and human takeover;
- conservative about replay, recovery, and capability claims; and
- evaluated through contracts and evidence gates before promotion.

It is not currently:

- a safe parallel background controller for the operator's active desktop;
- a production browser automation framework;
- a supported or application-verified day-scale campaign product;
- a multi-monitor, macOS, or Linux runtime;
- a production operator dashboard or iPhone notification adapter; or
- an automatically learning or self-modifying agent.

## Status and evidence vocabulary

Feature state and evidence state answer different questions:

| Term | Meaning |
| --- | --- |
| Implemented | Code exists in the current repository. |
| Experimental / partial | A bounded slice exists, but integration or real-environment proof is incomplete. |
| Internal only | Code is callable by tests/internal APIs but not a supported CLI/product path. |
| Planned | A documented contract or direction exists; no runtime claim is made. |
| Offline verified | Deterministic tests or fakes cover the stated boundary. |
| Provider verified | A retained credentialed result exists for that exact provider/model/scope; the earlier OpenAI/Claude cells, exact Kimi `cn` + `kimi-k2.6`, exact MiniMax `cn` + `MiniMax-M2.7`, exact DeepSeek `global` + `deepseek-v4-pro`, exact Doubao `cn-beijing` + `doubao-seed-2-0-lite-260215`, exact Qwen `cn-beijing` + `qwen3.7-plus`, and exact GLM `cn` + `glm-5.2` E3 currently qualify. |
| Desktop verified | A retained isolated Windows E4 result exists. |
| Application verified | A staged real-application acceptance case has passed with retained evidence. |

Always check the status header of an owner document and the
[evidence dashboard](CAPABILITY_STATUS.md). Detailed design is not executable
evidence.

## System map

~~~text
operator / Codex / Claude Code / another MCP client
  |
  +-- direct MCP path ---------------------------------------------+
  |    stdio -> guarded-desktop-mcp server                         |
  |             -> session refs / snapshot serialization           |
  |             -> e-stop / human activity / allowlist / approval  |
  |             -> Windows UIA + Win32 + capture                    |
  |                                                                |
  +-- Agent Host path ---------------------------------------------+
       guarded-desktop-agent CLI                                   |
         -> Responses / Chat Completions / Messages adapter         |
         -> policy / grounding / budgets / approval                 |
         -> redacted trace / explicit memory / recovery             |
         -> bounded stdio bridge -> the same MCP server ------------+

internal, not complete product paths
  -> Planner / Executor: plan, observe, reconcile, final response
  -> Campaign control plane: items, batches, leases, heartbeat, handoff,
     reviewed discovery adapters, and one manifest-routed offline worker
  -> H1-H8 control plus L0-L4 evidence/selection at bounded offline or
     injected-runtime scopes

implemented or partial projections and adapters
  -> OCR / document text / cropped image / optional browser observation
  -> passive progress / presence / Decision Cards
  -> local host terminal polling and read-only Task Center projection
  -> Review-only Formal Demo Console through inert COMPILE permit issue

planned or unverified expansion
  -> complete Host-owned TaskIntent / generic Scope Sheet / START front door
  -> Formal Demo v1 provider and application-role adapters
  -> delta observation and remote/mobile delivery
  -> isolated workers / macOS / Linux / Android device driver
  -> complete cross-application and release acceptance
~~~

The MCP server remains the only desktop execution authority. Planner,
campaign, recovery, UI, and learning layers may request or project work, but
must not create a second native-action path.

The user-facing entry is not unified today. The Review-only Console, `ask`, the fixed
`review` / `workflow public-web-word` pair, configuration, Task Center, and
cooperative control are separate CLI surfaces with different authority. The
Review-only Console must not be inferred to provide the planned intent call,
Scope, `Start`, or execution layers.

## Executable surfaces today

| Surface | Entry point | Current purpose | Boundary |
| --- | --- | --- | --- |
| Desktop MCP server | `guarded-desktop-mcp` | Expose thirteen core Windows GUI tools plus one optional read-only browser observation over stdio | Implemented Windows runtime |
| Agent Host | `guarded-desktop-agent` | Run bounded provider/MCP workflows and management commands | Experimental; scoped [E3](E3_EVIDENCE.md) and [E4](E4_EVIDENCE.md) evidence retained |
| Formal Demo Review-only Console | `guarded-desktop-agent-console --provider <provider> --model <model>` | Collect one local in-memory draft, show the exact operator-selected model plus reviewed route/profile disclosure without implying readiness, and issue one inert permit after exact `COMPILE` | Implemented/offline verified; reads no Agent config/key/provider environment, makes no provider request, shows Scope unavailable, and has disabled native `Start` with no consume/dispatch path |
| Quick Setup | `config setup` | Create one non-overwriting recommended strict configuration | Implemented; no credential write or process start |
| Agent Controls | `config settings` / `config settings --json` | Explain purpose, connection, safety, interface, and exact readiness command | Implemented and inert; no authority or shortcut registration |
| ShortcutBroker | `shortcuts run` | Explicitly own fixed open-controls and a strict configurable cooperative-pause-request shortcut | Implemented/offline verified; loaded-layout guard and foreground host only, no approve/resume/provider/MCP/desktop dispatch |
| Agent config creation | `config init` | Create a non-overwriting Desktop Ask or public-web-word installed profile | Implemented; no credential read or process start |
| Installed readiness | `config doctor` | Check provider setup and verify the configured MCP child's exact core-plus-configured-optional discovery contract | Implemented; real child handshake, no provider request or MCP tool call |
| Agent config validation | `config validate` | Parse strict TOML without starting external ports | Implemented and inert |
| Agent run | `run` / `run --dry-run` | Execute bounded workflow or validate preparation only | Observations implemented; actions opt-in and fake-verified |
| Desktop Ask | `ask` / `ask --json` | Plan one to four read-only observations, including semantic document text, and return one tool-free answer | Implemented/offline verified; the same-wheel current-candidate OpenAI/Windows/Notepad [result](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md) is retained |
| Public Web to Word | `workflow public-web-word` | Let a real model inspect the fixed public source, author a bounded brief, save a new DOCX, then close/reopen/read it back | Implemented/functionally verified; the same-wheel current-candidate provider/Chrome/Word [result](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md) is retained |
| Pre-run Review | `review public-web-word` / default workflow start gate | Show Host-fixed goal, applications, read/change boundary, exact output, approval bound, stops, and possible residue before external startup | Implemented/offline verified for public-web-word only; exact `START` or `--acknowledge-scope` starts no more than the ordinary workflow and approves no action |
| Read-only Task Center | `task center` / `task center --json` | Group validated local run/campaign state and render fixed Completion/Failure Receipts | Implemented/offline verified; CLI-first, local-only, and no execution, approval, replay, or notification authority |
| Cooperative desktop control | `task control`, `task pause`, `task takeover`, `task resume` | Coordinate one live fixed-workflow Runner at safe boundaries | Implemented/offline verified; same-process only, explicit authority release/resume, mandatory fresh observation, no uncertain replay |
| Approval Inbox | `approval inbox` / `approval inbox --json` | Inspect strict local pending/expired Decision Card attention records | Implemented/offline verified; local-only, no liveness claim, approval, control, retry, replay, or dispatch authority |
| Evaluation | `eval` | Run deterministic frozen E1/E2 cases | Implemented offline |
| Release preflight | `release preflight` | Run clean-candidate offline gates and build smoke | Implemented; not release approval |
| Inspection | `trace`, `report`, `recovery` | Read validated redacted state and classify recovery | Implemented, no implicit execution |
| Controlled recovery | `recover`, `resume`, `cancel` | Execute reviewed read-only boundaries, resume initial state, or close a run | Strictly bounded; no uncertain/action replay |
| Explicit memory | `remember add/list/delete` | Manage confirmed local preferences/procedures | Implemented opt-in baseline |
| Fixed synthetic campaign | `campaign prepare-synthetic`, `run-claimed-synthetic`, `resume-synthetic` | Prepare one exact claimed item, execute `list_windows` through Runner handoff, and enter durable fresh-run resume | Implemented/offline verified; no general selector, provider turn, side effect, or application worker |

Planner/Executor is exposed through product-facing `ask` and metadata-oriented
`plan run`. Campaign commands remain deliberately bounded control/evidence
surfaces rather than one automatic general-product loop.
There is no unified executing Agent Console or `TaskIntent` candidate entry in
this table; the Review-only command stops before both.

## Feature inventory

### Windows MCP runtime

| Feature | State | Implementation | Primary owner |
| --- | --- | --- | --- |
| Model-agnostic stdio MCP | Implemented | FastMCP schemas call a platform-neutral session/driver boundary | [Tools](TOOLS.md), [Design](DESIGN.md) |
| UIA snapshots | Implemented | Flat, 200-control-capped serialization with roles, names, bounds, states, and safe value summaries | [Tools](TOOLS.md) |
| Session refs | Implemented | `ref_N` binds model-visible controls and observed boxes to native UIA elements; user-enabled UIA actions allow one role/name relocation after staleness | [Tools](TOOLS.md), [Driver Contract](DRIVER_CONTRACT.md) |
| Scoped find | Implemented | Filters the same snapshot/ref model to reduce returned context | [Tools](TOOLS.md) |
| Window enumeration | Implemented | Win32 top-level enumeration includes owned dialogs and foreground identity | [Design](DESIGN.md) |
| Screenshot observation | Implemented / limited | `mss` returns a PNG for the primary display; configured title matches can be blacked out | [Tools](TOOLS.md), [Configuration](CONFIGURATION.md) |
| Bounded OCR observation | Implemented / Windows primary display | `Windows.Media.Ocr` recognizes one explicit region with run/character/pixel/time limits, pre-OCR title-based blackouts, image digest, and local/screen boxes | [Tools](TOOLS.md), [Observation contract](OBSERVATION_CONTRACT.md) |
| Rendered-browser observation | Implemented / optional, offline only | Playwright attaches read-only to one user-configured loopback Chromium CDP session and returns bounded untrusted ARIA/text; it exposes no browser actions or refs and is removed after one failed observation in a run | [Tools](TOOLS.md), [ADR-011](adr/011-os-input-default-with-read-only-browser-assist.md) |
| Window activation | Implemented; isolated rerun pending | Win32 input-thread attachment, restore, foreground request, reverse cleanup, and postcondition verification | [Capability status](CAPABILITY_STATUS.md) |
| Ref action | Implemented | OS pointer input to observed geometry is default; user-enabled UIA uses Invoke/Select and never silently falls back after failure | [Design](DESIGN.md) |
| Coordinate action | Implemented / primary display only | Win32 pointer input uses the same supported DPI-aware pixel space as capture | [Driver Contract](DRIVER_CONTRACT.md) |
| Text and key input | Implemented | Win32/native key events are default for focused input and chords; ref-addressed UIA ValuePattern requires user opt-in | [Tools](TOOLS.md) |
| Chromium UIA warm-up | Experimental | Best-effort accessibility traversal without foreground theft; incomplete content remains visible | [Design](DESIGN.md) |
| Driver abstraction | Implemented contract, one driver | Platform-free typed contract with a Windows UIA/Win32 implementation | [Driver Contract](DRIVER_CONTRACT.md), [Tech stack](TECH_STACK.md) |

### Desktop safety and coexistence

| Feature | State | Implementation | Primary owner |
| --- | --- | --- | --- |
| Safe local mode | Implemented/default | Foreground process-ancestry allowlist, recent-human-input yield, e-stop, dangerous-ref confirmation, audit | [Configuration](CONFIGURATION.md) |
| Full-control local mode | Implemented/explicit takeover | Bypasses allowlist and human-yield only; retains e-stop and audit | [Configuration](CONFIGURATION.md) |
| Foreground gate | Implemented | `psutil` ancestry match prevents action based on a misleading leaf process alone | [Design](DESIGN.md) |
| Human-activity yield | Implemented | Synchronous `GetLastInputInfo` check before safe-mode actions; no listener or hook | [Quality attributes](QUALITY_ATTRIBUTES.md) |
| Dangerous ref confirmation | Implemented/limited | Keyword-classified ref clicks request native confirmation; it is not general action classification | [Approvals](APPROVALS.md), [Configuration](CONFIGURATION.md) |
| Emergency stop | Implemented | Global hotkey latches future actions off until server restart | [Configuration](CONFIGURATION.md) |
| Audit logging | Implemented | Bounded JSONL records summarize action arguments and results; typed text content is omitted | [Configuration](CONFIGURATION.md) |
| Password/screenshot protection | Implemented/limited | Password values omitted from snapshots; title-substring screenshot blackout is defense in depth, not DLP | [Configuration](CONFIGURATION.md) |
| True isolated background work | Planned | Requires a VM, separate session/display, or second machine with independent input/capture authority | [Tech stack](TECH_STACK.md) |

### Agent Host

| Feature | State | Implementation | Primary owner |
| --- | --- | --- | --- |
| Provider-neutral host contract | Implemented | Canonical immutable types and ports isolate provider, desktop, approval, policy, and state | [Agent Host](AGENT.md) |
| Responses profiles | Implemented/offline verified; Doubao and Qwen `cn-beijing` E3 retained | Exact OpenAI/Qwen/Doubao identity, response-ID continuation, strict tool/result correlation, byte/token gates, bounded capability flags; the exact Doubao and Qwen candidates passed ordinary continuation plus prompt-only Planner/Host compilation/final and one 16x16 synthetic-image cycle each. Qwen Planner strips only one exact route/model-scoped JSON fence before unchanged Host compilation | [Provider support](PROVIDERS.md), [Agent Host](AGENT.md), [E3 evidence](E3_EVIDENCE.md) |
| Chat Completions profiles | Implemented/offline verified; Kimi `cn`, DeepSeek `global`, and GLM `cn` E3 retained | Exact Kimi/DeepSeek/GLM identity, isolated service-region routes, bounded local history, sequential tool calls, opaque compatible reasoning, exact Kimi one-shot thinking disablement, exact GLM short Planner wire with unchanged Host compilation, image withdrawal | [Provider support](PROVIDERS.md), [Agent Host](AGENT.md), [E3 evidence](E3_EVIDENCE.md) |
| Messages profiles | Implemented/offline verified; MiniMax `cn` E3 retained | Exact Anthropic/MiniMax identity, adjacent tool-use/results, atomic history packing, strict reasoning preservation for ordinary continuation, strict one-shot reasoning-before-text normalization, byte/token gates, exact MiniMax route/model-scoped image-tool withdrawal | [Provider support](PROVIDERS.md), [Agent Host](AGENT.md), [E3 evidence](E3_EVIDENCE.md) |
| Bounded runner | Implemented | One canonical loop owns budgets, ledger, provider turns, policy, dispatch, verification, and cleanup | [Agent Host](AGENT.md) |
| Sole desktop dispatch site | Implemented/frozen | All Agent desktop execution routes through the Runner boundary and then the stdio MCP child | [Agent Host](AGENT.md) |
| Reviewed tool registry | Implemented | Host derives effect/schema/approval facts; provider output cannot grant authority | [Agent Host](AGENT.md) |
| Policy modes | Implemented | Read-only default; approved actions are opt-in, budgeted, grounded, and confirmed by default. The fixed public-web-word profile uses Host-owned low/high/unknown classification: low proceeds without a prompt, high requires exact approval, and unknown is denied | [Approvals](APPROVALS.md) |
| Grounding and verification | Implemented/fake verified | Actions require fresh observation binding and mandatory post-action observation | [Approvals](APPROVALS.md) |
| Bounded stdio bridge | Implemented | Absolute child command, reviewed environment, exact core-plus-configured-optional discovery, bounded frames/results, generation invalidation | [Agent Host](AGENT.md) |
| Run budgets | Implemented | Model turns, tool calls, side effects, cumulative input, request bytes, context window, and image/result bounds | [Context and memory](CONTEXT_MEMORY.md) |
| Checkpoint and redacted trace | Implemented | Atomic safe checkpoint plus bounded append-only semantic JSONL; sensitive content excluded | [Trace](TRACE.md) |
| Reports | Implemented | Bounded checkpoint-only aggregation of phase, failure, token, call, and latency metrics | [Trace](TRACE.md) |
| Explicit memory | Implemented/opt-in | Confirmed, scoped, expiring SQLite preferences/procedures; never auto-extracted or auto-injected | [Context and memory](CONTEXT_MEMORY.md) |
| Local privacy boundary | Implemented/disabled by default | One opt-in privacy package owns run-scoped deterministic PII tokens, non-restorable secret tokens, fail-closed model token validation, local-only display/query restoration, and local OCR solid overlays; its non-text visual-detector port has no enabled backend, and continuation remains denied | [Local privacy boundary](LOCAL_PRIVACY.md) |
| Live provider and desktop proof | Retained for reviewed models and VM | E3 and E4 remain explicit human gates, not CI claims; retained results do not imply application or release readiness | [E3 evidence](E3_EVIDENCE.md), [E4 evidence](E4_EVIDENCE.md) |

### Recovery, planning, and execution

| Feature | State | Implementation | Primary owner |
| --- | --- | --- | --- |
| Redacted recovery classification | Implemented | Checkpoint phase/evidence maps to fixed safe next actions; no automatic replay | [Trace](TRACE.md) |
| Sensitive continuation WAL | Implemented/opt-in | Private atomic `prepared -> dispatch_intent -> completed` evidence with exact identity/digest binding | [Continuation](CONTINUATION.md) |
| Bounded read-only recovery | Implemented | One step by default, at most four reviewed boundaries under one lock; completed actions only re-observe | [Continuation](CONTINUATION.md) |
| OpenAI stateless replay | Implemented/explicit | Rebuilds only a complete digest-bound read-only transcript; never automatic fallback | [Stateless replay](STATELESS_REPLAY.md) |
| Declarative task plan | Implemented/internal | Strict JSON compiler derives host IDs/effects/approval metadata and rejects sensitive or out-of-scope arguments | [Planning](PLANNING.md) |
| Atomic plan store | Implemented/internal | Private `task-plan.json`, RunLock ownership, sequence/digest compare-and-swap, legal ordered transitions | [Planning](PLANNING.md) |
| One-shot nine-profile Planner | Implemented/internal | Isolated no-tool request with explicit native-schema, JSON-object, or prompt-schema mode; fixed one-call failure, no fallback | [Provider support](PROVIDERS.md), [Planning](PLANNING.md) |
| Observation Executor | Implemented/internal | At most four observation steps; WAL before dispatch; shared Runner authority; known completion or fail-closed uncertainty | [Planning](PLANNING.md) |
| Observation reconciliation | Implemented/internal | Repairs only the exact missed plan CAS after a known completed result; never redispatches | [Planning](PLANNING.md) |
| Tool-free final response | Implemented/internal | Lossless observation compiler, isolated provider adapters, dedicated WAL, ordered budget/plan/trace terminalization | [Planning](PLANNING.md) |
| Final-response reconciliation | Preflight implemented/internal | Pure reconstruction of exact completed evidence; applying CAS/cleanup and CLI exposure remain next | [Planning](PLANNING.md) |
| Bounded Planner/Executor CLI | Implemented/read-only | `ask` and `plan run` compose one Planner call, one to four reviewed observations through Runner, and one tool-free final answer; side effects remain unavailable | [Capability status](CAPABILITY_STATUS.md) |
| Hierarchical task and behavior trees | H1-H8 implemented/offline and merged | Immutable versioned nodes, canonical tree/envelope digests, structural/budget/graph limits, pure state and join reduction, private `RunLock`-bound exact CAS, next-leaf compilation, typed fresh facts, one exact BOSS observation template, one separately gated observation/action/verification-observation sequence, contract-v2 bounded H5 batches, contract-v3 all-of joins, and contract-v4 Host-ordered immutable choice plus exact verified read-only-miss fallback preserve the existing Runtime Executor and sole Runner boundary | [Hierarchical task and behavior trees](HIERARCHICAL_TASK_AND_BEHAVIOR_TREES.md), [H7 evidence](H7_BOUNDED_SIDE_EFFECT_EVIDENCE.md), [H8A evidence](H8A_PARALLEL_CONDITION_EVIDENCE.md), [H8B evidence](H8B_DEPENDENCY_JOIN_EVIDENCE.md), [H8C evidence](H8C_SAFE_CHOICE_EVIDENCE.md) |

### Long-running campaigns

| Feature | State | Implementation | Primary owner |
| --- | --- | --- | --- |
| Campaign manifest and item ledger | Implemented/internal | Strict manifest plus append-only item transitions with stable identities and fixed states | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| Bounded batches | Implemented/internal control plane | Hard limits for items, time, turns, tools, tokens, images, and failures | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| Lease and heartbeat | Implemented/internal | Injected-time bounded lease, heartbeat freshness, stale inspection, and locked recovery | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| Pause, resume, and run transfer | Implemented/internal | Deterministic preflight and owner transfer without granting item/action authority | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| Item progression | Implemented/internal/read-only | `CLAIMED -> OBSERVED -> EXTRACTED -> COMMITTED` with digest evidence and fail-closed drift checks | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| Deterministic handoff/completion | Implemented/internal | Fixed-schema handoff and terminal campaign projection derived from durable state | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| Fixed synthetic execution seam | Implemented/internal product boundary | Three CLI commands prepare one fixed claim, execute one `list_windows` observation through Runner handoff, and reconstruct fresh-run resume | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| BOSS identity discovery | Implemented/internal fixed runtime | Two fixed CLI commands create the reviewed manifest and dispatch one foreground `ui_snapshot` through Runner/project MCP; bounded complete link values produce idempotent public job keys with query data discarded. A [current-contract two-pass result](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md) retained twelve identities with externally controlled progression; no automatic navigation, worker, restart, or application acceptance | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| BOSS bounded item/restart seam | Implemented/internal fixed runtime | Three fixed CLIs start the first coordinator-selected batch, verify one exact claimed public identity through one Runner/project-MCP snapshot and digest-backed commit/handoff, then transfer a fresh or proven-stale finished owner to a zero-port run and claim the exact next item. A [clean on-device sequence](BOSS_ITEM_RESTART_CLEAN_EVIDENCE.md) retained twelve identities and three consecutive fresh-run commits without local state correction, and the earlier [diagnostic](BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md) preserves two corrected defects; no item selector, provider execution, automatic navigation, semantic job extraction, or clean application acceptance | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| BOSS semantic extraction seam | Implemented/offline-only runtime | Three fixed no-selector CLIs open a one-item/five-call/zero-side-effect batch, re-establish the exact claim through Runner UIA, permit strict escalation to document text, commit only a schema/policy/source-digest-bound provider result, hand off without OCR dispatch when its Host safety baseline remains denied, and transfer a successful batch to a fresh run. The pure contract retains the full OCR/crop/screenshot ladder; there is no on-device semantic result or automatic navigation | [Semantic contract](BOSS_SEMANTIC_EXTRACTION_CONTRACT.md) |
| General campaign worker | Implemented/internal, offline only | Manifest-routed capability-composed scenario registry with A1-A19 as built-in examples rather than a closed list; validated new specs register without Runner changes. Includes explicit stable-item preparation, provider execution through the sole Runner boundary, strict semantic result schema, digest commit, one-item handoff, fresh-run resume, and automatic exhausted-manifest completion with exact terminal heartbeat retirement. No generic real-application acceptance claim | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| Composable discovery adapters | Implemented/internal, offline only | Declarative `link_url`/`control_name` adapters bound to a campaign kind derive stable public item keys from one bounded foreground `ui_snapshot`; two CLI commands create the reviewed campaign and record one operator-driven pass with the provider forbidden and no page, URL, scope, or item selector. The campaign carries the ordinary worker digests, so discovery enters `campaign start` unchanged. Only BOSS has retained on-device discovery evidence, under its own separate fixed contract | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| Host completion polling | Implemented/internal contract | Bounded read-only projection and deduplicated fake-host terminal/attention decisions; the local Task Center consumes the projection, while no mobile bridge exists | [Long-running tasks](LONG_RUNNING_TASKS.md#host-visible-completion-and-mobile-notification) |

### Observation, operator, application, and learning layers

| Feature family | State | Intended implementation | Primary owner |
| --- | --- | --- | --- |
| Multi-source observation | Partial | UIA, full-screen PNG, bounded region OCR, standalone cropped images, bounded document text, and optional rendered-browser ARIA/text exist; complete cross-source envelopes and delta observations remain | [Observation contract](OBSERVATION_CONTRACT.md), [BOSS OCR evidence](BOSS_OCR_EVIDENCE.md) |
| Token-efficient observation | Contract/planned experiments | Escalate from structured/cheap sources to pixels; retain item-local context and measured cost | [Token efficiency](TOKEN_EFFICIENCY.md) |
| Presence and progress UI | Partial | Passive progress is implemented and follows durable ordinary `run`/`resume`, bounded `ask` / `plan run`, explicit read-only recovery phases, and validated state during fixed MCP-backed campaign execution; zero-port campaign control remains window-free. System High Contrast, reduced motion, bounded UIA status names, native automated 200%/400% text reflow, bounded English/Simplified-Chinese presentation, strict dark/light/system theme resolution, and Host-owned foreground-monitor composition are implemented and verified through the stated offline/native boundary; human assistive-technology, human large-text/visual-design, and physical two-monitor review remain open. The fixed synthetic campaign lifecycle is [desktop verified](CAMPAIGN_PROGRESS_LIFECYCLE_EVIDENCE.md); one persisted read-only observation has separate [recovery progress evidence](RECOVERY_PROGRESS_LIFECYCLE_EVIDENCE.md); and one fixed provider-free plan has separate [plan progress](PLAN_PROGRESS_LIFECYCLE_EVIDENCE.md) and [presence](PLAN_PRESENCE_LIFECYCLE_EVIDENCE.md) lifecycle evidence. The current [feature-freeze non-E4 audit](FEATURE_FREEZE_NON_E4_EVIDENCE.md) covers ten theme/locale/large-text safe-denial cases and fixed notification lifecycle. The earlier bounded primary-display halo is also [desktop verified](PRESENCE_WINDOW_EVIDENCE.md); the newer [multi-display contract](OPERATOR_MULTI_DISPLAY.md) still lacks physical two-monitor evidence. Integrated BOSS-campaign progress/presence evidence and recovery presence desktop evidence remain planned | [Operator experience](OPERATOR_EXPERIENCE.md), [Operator accessibility](OPERATOR_ACCESSIBILITY.md), [Operator localization](OPERATOR_LOCALIZATION.md), [Operator personalization](OPERATOR_PERSONALIZATION.md), [Native operator multi-display composition](OPERATOR_MULTI_DISPLAY.md), [Progress viewer](PROGRESS_VIEWER.md) |
| Decision Cards | Partial / configurable Windows | Pure cards compile 2-4 bounded options; generated installed profiles enable the focus-taking four-choice Win32 adapter, which yields authority and returns exact-effect approval, re-observe, durable defer, or denial through the existing ApprovalPort. Native Text/Edit/Button semantics, safe initial focus, standard keyboard traversal, bounded countdown announcements, system High Contrast/reduced motion, native automated 200%/400% reflow, English/Simplified-Chinese presentation, and strict dark/light/system theme resolution are implemented and verified through the stated offline/native boundary. Internal option IDs and authority stay locale-neutral. Human Narrator/NVDA, human large-text, and visual-design review remain open; broader current-candidate cross-application evidence remains planned | [Operator experience](OPERATOR_EXPERIENCE.md), [Operator accessibility](OPERATOR_ACCESSIBILITY.md), [Operator localization](OPERATOR_LOCALIZATION.md), [Operator personalization](OPERATOR_PERSONALIZATION.md), [Feature-freeze non-E4 evidence](FEATURE_FREEZE_NON_E4_EVIDENCE.md), [Approved actions](APPROVALS.md) |
| Task Center and outcome receipts | Implemented / CLI-first, offline verified | Read-only Attention/In progress/History grouping over validated redacted run/campaign state, fixed human receipt wording, and strict immutable public-web-word completion receipts; no provider, MCP, desktop, approval, resume, retry, cancel, campaign-advance, or notification port | [Task Center](TASK_CENTER.md) |
| Pre-run Review | Implemented / CLI-first, offline verified | Host-fixed public-web-word objective, applications, data use, output, seven-side-effect bound, low-risk Host authorization, zero expected high-risk approvals, stop conditions, residue, and exact acknowledgement before every external startup; no model prose or blanket approval | [Pre-run Review](PRE_RUN_REVIEW.md) |
| Cooperative Pause/Takeover/Resume | Implemented / CLI-first, offline verified | One strict local control lifecycle for the public-web-word Runner loops; pause waits for a durable safe boundary, releases Agent desktop authority, and resumes only after explicit operator return plus fresh observation. No `BlockInput`, crash reconstruction, campaign mutation, or uncertain replay | [Cooperative control](COOPERATIVE_CONTROL.md) |
| Approval Inbox and local notification | Implemented / CLI-first, offline verified | Strict expiring identity/digest records supplement the bound Decision Card; optional Windows notification carries fixed wording only. Neither surface can decide, control, retry, replay, or dispatch, and native accessibility evidence remains open | [Approval Inbox](APPROVAL_INBOX.md) |
| Public web to Word workflow | Implemented / exact scoped evidence | One installed fixed workflow lets a reviewed OpenAI model observe a fresh public Microsoft Support page, author a bounded brief, and write, save, reopen, visually verify, and clean up one disposable Word fixture through the existing Runner/MCP and Decision Card boundaries. The [retained result](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) does not establish arbitrary websites or applications | [Workflow contract](PUBLIC_WEB_WORD_WORKFLOW.md) |
| Mobile notifications | Host capability; internal repository projection implemented | Local fixed-content approval attention exists, but mobile terminal/attention delivery remains absent; no MCP-log completion inference or repository mobile bridge | [Operator experience](OPERATOR_EXPERIENCE.md#remote-and-mobile-notification-semantics) |
| Formal Demo v1 | Review-only front door and internal offline contracts implemented; complete product not executable | Inert v1 `TaskIntent`, scenario/profile pins, generic Scope, canonical binding, typed local disclosure/exact-`COMPILE` permit, consume-before-injected-fake coordinator, and independent no-key Review-only Console exist. The Console stops with Scope unavailable and `Start` disabled; the live provider call, permit consumption, positive built-in Scope, executable adapters, durable composition, and selected GitHub Issues -> PDF -> Excel -> Word -> unsent test-email run remain planned | [Formal Demo v1](FORMAL_DEMO_V1.md) |
| Application Coverage Set A | Planned independent acceptance | BOSS read-only, Google Docs long document, WeChat draft-only, and their legacy cross-application case remain representative mechanism coverage; they do not define the Formal Demo or project priority | [Application matrix](APPLICATION_EVALUATION_MATRIX.md) |
| Broader applications | Planned | Media/design, Office/data, remote/system, legacy, and enterprise governance coverage sets | [Application matrix](APPLICATION_EVALUATION_MATRIX.md) |
| Universal GUI final showcase | Planned/final integration gate | One chaptered campaign composed only after its selected mechanisms are independently eligible, with faults, takeover, tokens, authority, and retained artifacts | [Universal GUI final showcase](UNIVERSAL_GUI_DEMO.md) |
| Continual learning | L0-L4 implemented/offline and injected-runtime; L5 separately deferred | Redacted outcomes and typed facts remain isolated; reviewed content-free `ACTIVE`/`SHADOW` evidence can enter one exact-context, action-risk-bound persistent canary. Selection binds a separately compiled H7 plan but carries no arguments or authority; every regression rolls back, and automatic retry/promotion, memory injection, general procedure compilation, training, and real-application claims remain absent | [Continual learning](CONTINUAL_LEARNING.md) |
| Platform expansion | Planned | macOS AX, Linux AT-SPI, an Android device driver (ADB transport, behind the same contract; see [ADR-008](adr/008-android-device-driver-behind-driver-contract.md)), multi-monitor coordinate model, isolated worker runtimes | [Tech stack](TECH_STACK.md) |

## Implementation structure

### Source packages

| Package or area | Responsibility |
| --- | --- |
| `src/computer_use_mcp/contract.py` | Platform-free driver types and interface |
| `src/computer_use_mcp/core.py` | Session refs, snapshots, serialization, stale relocation |
| `src/computer_use_mcp/server.py` | Thirteen FastMCP tools and server-side guard orchestration |
| `src/computer_use_mcp/drivers/windows.py` | UIA, Win32, capture, activation, input, process identity |
| `src/computer_use_mcp/gate.py`, `human_activity.py`, `safety.py`, `audit.py` | Local action boundary and evidence |
| `src/computer_use_agent/types.py`, `tool_registry.py`, `policy.py`, `grounding.py` | Canonical host data, reviewed capabilities, policy, and action freshness |
| `src/computer_use_agent/runner.py`, `desktop_mcp.py`, `bounded_stdio.py` | Agent loop and sole MCP dispatch/transport boundary |
| `src/computer_use_agent/provider_catalog.py`, `provider_factory.py`, `providers/` | Eight exact cloud profiles, one loopback-only local Planner/final profile, and three wire-family adapters; local ordinary tool calling remains closed pending E3 |
| `src/computer_use_agent/trace.py`, `report.py`, `memory.py` | Safe state, metrics, reporting, and explicit memory |
| `src/computer_use_agent/episode_outcome.py` | Read-only L0 terminal outcome normalization, explicit metric coverage, durable source reconciliation, and no learning or execution port |
| `src/computer_use_agent/learning_quarantine.py` | Private L1 fresh-fact candidate extraction, revision-CAS lifecycle, digest-only audit events, and no memory injection or execution port |
| `src/computer_use_agent/verified_procedures.py` | Inert L2 procedure schema, frozen fixture decoder, pure replay/held-out gate, reviewed lifecycle, and exact rollback without runtime ports |
| `src/computer_use_agent/shadow_strategies.py` | Inert L3 exact-equivalence shadow comparison, visible reward weights/contributions, deterministic recommendation, and no runtime-selection port |
| `src/computer_use_agent/adaptive_routing.py` | L4 reviewed LOW-only canary policy, exact context/action-risk binding, private atomic cross-run state, first-regression rollback, and non-authorizing H7 route binding |
| `src/computer_use_agent/progress_view.py`, `task_center.py`, `product_receipt.py` | Structurally validated status projection, read-only task grouping/fixed receipt wording, and strict private product completion evidence |
| `src/computer_use_agent/public_web_word.py`, `pre_run_review.py` | Fixed workflow/profile guard plus the Host-compiled Scope Sheet, versioned JSON, and human rendering without external ports |
| `src/computer_use_agent/formal_demo_contract.py` | Internal inert Formal Demo v1 intent/scenario/profile/Scope contracts, exact reviewed pins, bounded canonical binding, and fail-closed structural compilation without execution ports |
| `src/computer_use_agent/formal_demo_intent_gate.py` | Internal typed sensitive-local intent disclosure plus exact `COMPILE` issue/consume gate; validates one exact route against static reviewed catalog/routing rules and one reviewed warning pin, opens no provider/execution/persistence port, and makes no durable or cross-process exactly-once claim |
| `src/computer_use_agent/formal_demo_intent_request.py` | Provider-neutral offline one-attempt coordinator: exact reviewed-scenario preflight, permit consume before one injected call, strict untrusted-candidate validation, terminal no-retry behavior, and no concrete provider/credential/network/execution wiring |
| `src/computer_use_agent/formal_demo_console.py`, `formal_demo_console_win32.py`, `formal_demo_console_launcher.py` | Independent no-key Review-only Formal Demo front door: one in-memory draft, reviewed route/profile disclosure, inert exact-`COMPILE` permit issue, honest unavailable Scope, and disabled native `Start`; no config/credential/provider/network/consume/Runner/MCP/desktop-automation/application/persistence port |
| `src/computer_use_agent/continuation.py`, `recovery.py`, `reconstruction.py` | Sensitive WAL, crash classification, and bounded recovery |
| `src/computer_use_agent/planning.py`, `planner.py`, `plan_store.py` | Declarative plan compilation, provider port, and persistence |
| `src/computer_use_agent/hierarchical_control.py` | Inert H1 node schema, canonical tree digest, reviewed limits, pure status reduction, and linear-plan projection |
| `src/computer_use_agent/tree_store.py` | Private H2 `RunLock`-bound atomic snapshots, strict restart decoding, and sequence/tree-digest CAS with no external ports |
| `src/computer_use_agent/hierarchical_compiler.py` | Pure H3 next-leaf result, digest-bound inert boundary, ordered leaf transition reducer, and unresolved-choice fail-closed behavior |
| `src/computer_use_agent/hierarchical_runtime.py` | Port-free H4 plan/tree identity binding, exact leaf status projection, and local-only reconciliation around the existing Runtime Executor |
| `src/computer_use_agent/world_state.py` | Pure H5 content-free observation evidence, typed facts, exact freshness/window invalidation, and unavailable-not-false condition evaluation |
| `src/computer_use_agent/behavior_templates.py` | Immutable H6 exact-version template registry, pinned BOSS observation ladder, inert request binding, and no-fallback reducer compatibility |
| `src/computer_use_agent/hierarchical_parallel_contract.py`, `hierarchical_parallel.py` | H8A content-free batch evidence plus bounded four-worker local H5 evaluation and one exact tree-store CAS; no external port |
| `src/computer_use_agent/hierarchical_graph_contract.py`, `hierarchical_control.py`, `hierarchical_compiler.py` | H8B content-free all-of edges, bounded combined-DAG validation, local joins, stable one-ready-leaf compilation, and global external-leaf serialization; no external port |
| `src/computer_use_agent/hierarchical_choice_contract.py`, `hierarchical_choice.py` | H8C content-free Host-order branch evidence, bounded local H5 gate evaluation, immutable selection, and exact pre-boundary-false/read-only-verified-miss fallback; no external port |
| `src/computer_use_agent/executor*.py`, `planned_observation_runtime.py` | Observation/final runtimes, WALs, reconciliation, and bounded read-only CLI composition |
| `src/computer_use_agent/campaign*.py`, `batch*.py`, lease/heartbeat modules | Internal long-running control plane |
| `src/computer_use_agent/evaluation.py`, `release.py` | Deterministic evidence and release preflight |
| `tests/`, `evals/`, `scripts/` | Pure/offline tests, frozen cases, on-device smokes, VMware helper |

### Current direct MCP action flow

~~~text
client tool request
  -> FastMCP schema validation
  -> e-stop and mode-specific guard checks
  -> foreground owner-chain / human-activity checks when required
  -> dangerous ref-click confirmation when required
  -> Session + Driver operation
  -> bounded result and audit JSONL
~~~

### Current Agent Host flow

~~~text
task + strict config
  -> acquire application RunLock
  -> create safe checkpoint and discover exact MCP schemas
  -> provider receives reviewed tools and bounded context
  -> normalize requested call as untrusted data
  -> policy + budgets + grounding + optional exact approval
  -> durable intent when continuation is enabled
  -> sole Runner MCP dispatch
  -> validate result and dispatch certainty
  -> mandatory observation after side effects
  -> continue provider or write terminal checkpoint
  -> close desktop bridge, release lock, return bounded JSON
~~~

These current surfaces are separate entries. In particular, the implemented
`public-web-word` Scope Sheet is fixed to that one workflow, and Task Center is
read-only; together they do not form a generic recipe or Console lifecycle.

### Host front-door flow — implemented Review-only stop, planned continuation

~~~text
natural-language outcome in Review-only Agent Console [implemented command]
  -> local Host-fixed provider/data-use disclosure [implemented]
  -> exact COMPILE acknowledgement [inert permit issued; not consumed]
  -> Scope unavailable / Start disabled [current executable stop]
  -> one-attempt Host coordinator [implemented; injected fake only]
  -> concrete tool-free provider adapter/call [planned]
  -> strict TaskIntent decode + reviewed-scenario validation [implemented fake-only]
  -> Host validates reviewed application-role profiles
  -> Host compiles generic Scope Sheet
  -> explicit start acknowledgement (not action approval)
  -> existing planning / campaign / operator-control components
  -> existing Agent Runner policy + grounding + budgets + approval + WAL
  -> sole stdio MCP server
  -> Windows Driver
~~~

The inert `TaskIntent`, scenario/profile, generic Scope, local disclosure /
permit contracts, and injected-port one-attempt coordinator are implemented as
internal source modules. The sensitive surfaces keep the exact task only in
trusted in-process memory and copy only its digest into canonical bindings and
receipts. The disclosure gate and coordinator accept typed Host objects and
expose no serialized loader, concrete provider adapter, credential lookup, or
network path. Their one-use guarantee is limited to one in-memory gate instance;
consume-before-fake ordering is not crash-safe exactly-once. The independent
Review-only Console/launcher is a command, but it deliberately does not connect
to that coordinator or consume its permit. The live provider call, product
compiler integration, recipe lifecycle, positive Scope, and `Start` remain
absent. No built-in full product path can
compile while the exact email role remains `UNSELECTED`. Future product layers
may narrow and compose reviewed Host behavior but cannot select arbitrary
tools, grant authority, bypass the Runner, or create a second desktop path.

## Runner and tool change-impact map

The front-door plan above does not require a Runner or core-tool change. If a
later activated slice does change those contracts, it is not a local edit and
must update every affected owner in the same bounded change:

| Change | Required companion work |
| --- | --- |
| Add or remove a reviewed tool | Keep the Host `ToolSpec` and FastMCP discovery schema exact; update policy/effect/sensitivity/grounding metadata, provider projections, registry digest and continuation/replay fixtures, plan/tree/procedure/adaptive-routing bindings, campaign worker capability catalogs, tool/server/Runner tests, and create a new manifest version/consumer fixture when that tool belongs in a future Full Cycle export rather than mutating frozen manifest v1 |
| Change a tool input or output schema | Update both Host and MCP schemas plus result conversion/types; update digest-bound plan/tree/procedure/adaptive-routing/campaign persistence and migration/fixtures; expect incompatible approvals, continuations, replay, compiled plans/trees, learned procedures, canary routes, and worker specs to fail closed |
| Change tool semantics without changing schema | Re-review effect, approval, grounding, observation invalidation, safety baseline, result sensitivity, and unknown-outcome behavior; add scoped behavior tests and new live evidence before changing a capability claim |
| Add a new native primitive | Update the Driver Contract, platform Driver implementation, MCP Session/server orchestration, and contract tests; the Runner still cannot call the Driver directly |
| Change Runner dispatch, recovery, or result certainty | Update WAL/continuation/recovery contracts, policy and grounding checks, canonical result conversion, unknown-outcome/no-replay tests, and the owning docs before promotion |
| Add only a Host front-door recipe or scenario contract | Reuse the existing Runner and reviewed tools. Keep the registry static unless the scenario truly needs a new primitive; a Console, channel, scheduler, or adapter may submit reviewed requests but may never dispatch desktop actions itself |

The frozen Full Cycle Lane A manifest remains the thirteen-core-tool surface. A
core tool/schema change therefore needs an explicit versioned compatibility
decision; a planned Demo cannot silently widen that external contract.

The planned live tool-free `TaskIntent` request is also not zero external work.
The internal gate renders the Host-fixed exact text, provider/model, purpose,
and conservative data-use boundary and issues one process-local inert permit
after exact `COMPILE`. The offline coordinator now validates an exact reviewed
scenario, consumes that permit before one injected call, rejects terminal or
widened candidates, and never retries; it ships no concrete provider port or
credential/network wiring. A future activated live adapter must still revalidate
the current route/account boundary and use the consumed-attempt seam with no
automatic retry. The later generic Scope Sheet and `START` bind the full
execution scope; neither acknowledgement grants action authority.

### Planned campaign-to-mobile flow

~~~text
validated campaign plan
  -> bounded worker uses the existing Runner authority
  -> atomically commit each item and batch
  -> persist heartbeat, handoff, and terminal state
  -> Codex/Claude host reads bounded status projection
  -> host ends only on terminal or validated attention state
  -> ChatGPT/Claude mobile surface may notify the operator
~~~

## State and evidence artifacts

| Artifact | Sensitivity and purpose | Authority rule |
| --- | --- | --- |
| `audit/actions.jsonl` | Bounded desktop action summaries | Evidence only; typed text omitted |
| `state_dir/runs/<run_id>/state.json` | Redacted atomic run checkpoint | Drives inspection/classification, never replays a call by itself |
| `state_dir/traces/<run_id>.jsonl` | Redacted semantic event history | Reporting/debug evidence only |
| `state_dir/runs/<run_id>/continuation.json` | Opt-in sensitive task/provider/UI/image recovery evidence | Exact validation required; uncertain/pending action is non-executable |
| `state_dir/runs/<run_id>/control.json` | Strict content-free same-process control status, lease digest, safe-boundary binding, and outcome | Private local authority coordination; never automatic Full Cycle export input |
| `state_dir/memory.sqlite3` | Explicit confirmed preference/procedure text | Never auto-read or auto-promoted; selected scope is untrusted provider data |
| `state_dir/runs/<run_id>/task-plan.json` | Private declarative plan without task text | State, not authority; execution must re-enter Runner gates |
| `state_dir/runs/<run_id>/final-response.json` | Private final-response WAL and correlated result | Completion evidence, not provider retry or publication authority |
| `state_dir/workflows/public-web-word/<run_id>/receipt.json` | Private strict artifact path/digest plus save, reopen, and cleanup verification facts | Read-only product evidence; never execution authority or automatic Full Cycle export input |
| `state_dir/campaigns/<campaign_id>/...` | Manifest, heartbeat, item/batch ledgers, handoff | Durable campaign truth; the generic application worker and the composable discovery adapters both consume it, while retained application evidence remains BOSS-only |
| `out/` | Disposable local probes/reports | Ignored; promote repeatable facts into tests/docs |
| release/evaluation reports | Sanitized gate identity, counts, hashes, and outcomes | Support only the evidence level actually executed |

## Quality attributes and how the design realizes them

| Attribute | Design response | Evidence or owner |
| --- | --- | --- |
| Safety and least authority | Read-only default, reviewed registry, layered server/host gates, exact approval, e-stop, no second dispatch path | [Quality attributes](QUALITY_ATTRIBUTES.md), [Approvals](APPROVALS.md) |
| Correctness and grounding | Shared DPI-aware coordinate model, native patterns, fresh refs/observations, mandatory post-action verification | [Driver Contract](DRIVER_CONTRACT.md), [Approvals](APPROVALS.md) |
| Reliability | Explicit incomplete/stale/driver results, bounded retries, generation invalidation, application probes before claims | [Quality attributes](QUALITY_ATTRIBUTES.md) |
| Durability and recoverability | Atomic replace, append-only ledgers, RunLock, WAL before dispatch, exact CAS/digests, no replay after uncertainty | [Continuation](CONTINUATION.md), [Long-running tasks](LONG_RUNNING_TASKS.md) |
| Security and privacy | Secret-minimized child environment, redacted checkpoint/trace/audit, private sensitive artifacts, explicit memory consent, opt-in local text pseudonymization | [Agent Host](AGENT.md), [Trace](TRACE.md), [Context and memory](CONTEXT_MEMORY.md), [Local text privacy](LOCAL_PRIVACY.md) |
| Human coexistence | Recent-input yield, visible foreground assumptions, explicit takeover, and implemented passive non-activating Presence/Progress surfaces within their bounded evidence scopes | [Operator experience](OPERATOR_EXPERIENCE.md) |
| Observability and auditability | Fixed codes, bounded JSONL, safe metrics, deterministic reports, evidence-level dashboard | [Trace](TRACE.md), [Capability status](CAPABILITY_STATUS.md) |
| Testability and evidence integrity | Pure logic separated from named desktop smokes; frozen E1/E2 manifests; E3/E4 and release gates stay explicit | [Evaluation](EVALUATION.md), [Release](RELEASE.md) |
| Resource boundedness | Limits on frames, results, images, events, requests, tokens, turns, calls, side effects, batches, and artifacts | [Context and memory](CONTEXT_MEMORY.md), [Token efficiency](TOKEN_EFFICIENCY.md) |
| Performance and context efficiency | `find`, structured-first observation ladder, item-local context, bounded history packing, measured cost per result | [Token efficiency](TOKEN_EFFICIENCY.md) |
| Portability and maintainability | Platform-free Driver Contract, ports/adapters, canonical owner docs, deliberate versioned state schemas | [Design](DESIGN.md), [Tech stack](TECH_STACK.md) |
| Interoperability | Standard MCP surface and provider-neutral host types with isolated exact-vendor profiles over three wire families | [Provider support](PROVIDERS.md), [Agent Host](AGENT.md) |

The normative acceptance criteria live in
[Quality attributes](QUALITY_ATTRIBUTES.md); this table is the cross-system map.

## Trust and authority rules

These rules explain most implementation choices:

1. Model text, Planner output, memory, persisted plan fields, UI projections,
   and MCP log messages are data, not authority.
2. Every fresh desktop action passes the current policy, budget, grounding,
   approval, server guard, and MCP result-validation boundary.
3. A persisted completion can authorize local bookkeeping only when every
   identity, sequence, digest, effect, and dispatch fact matches.
4. Dispatch intent without correlated completion is uncertain and is never
   replayed automatically.
5. Side effects require fresh observation before dispatch and verification
   afterward; recovered approval is never reused.
6. Business authorization (tenant, object, field, recipient, role) is separate
   from permission to click or type in a visible GUI.
7. Missing metrics or evidence remain unknown; planned contracts never count as
   provider, desktop, application, or release proof.

## Validation model

| Level | Meaning | Typical mechanism |
| --- | --- | --- |
| E0 | Pure contracts, parsing, persistence, adapters, invariants | pytest and fake clients/ports |
| E1 | Deterministic bounded workflow success/failure | frozen fake-provider/fake-MCP cases |
| E2 | Safety, recovery, denial, unknown-outcome, exact replay boundaries | frozen semantic traces and exact-call matrices |
| E3 | Real provider with harmless fake MCP | retained OpenAI/Claude, exact Kimi `cn` + `kimi-k2.6`, exact MiniMax `cn` + `MiniMax-M2.7`, exact DeepSeek `global` + `deepseek-v4-pro`, exact Doubao `cn-beijing` + `doubao-seed-2-0-lite-260215`, exact Qwen `cn-beijing` + `qwen3.7-plus`, and exact GLM `cn` + `glm-5.2` results; other profiles and routes require separate opt-in exact-provider/model/route runs |
| E4 | Real provider plus isolated Windows desktop | four-cell disposable Notepad/VM runbook |
| E5 / release regression | Candidate-wide automated and human evidence | CI, preflight, retained records, explicit approval |

Offline passing tests do not fill E3/E4/application cells. See
[Evaluation](EVALUATION.md) and [Release evidence](RELEASE_EVIDENCE.md).

## Retained capability gaps and evidence gates

These are evidence dependencies, not operational task priority:

1. Use the retained isolated Windows evidence only for the repaired activation
   path and reviewed VM/model scope.
2. Retain one on-device UIA/document-text semantic item through the new bounded
   runtime; review the OCR Host safety baseline separately and add another
   source only on a demonstrated gap.
3. Preserve the exact scope of the retained installed
   [current-candidate product integration result](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md):
   one reviewed model, fixed public source, disposable Word output, durable
   reopen/readback, receipt, and exact fixture cleanup. The earlier Word-only
   record separately retains real-Word render QA.
4. Use the [retained on-device three-command synthetic campaign result](SYNTHETIC_CAMPAIGN_EVIDENCE.md)
   only for its exact fixed seam.
5. Preserve the bounded internal host terminal projection and fake-host
   notification semantics without broadening the campaign selector.
6. Promote BOSS, Google Docs, and WeChat only through their independent
   Application Coverage Set A gates; do not infer a product-priority sequence
   or Formal Demo acceptance from those cases. Formal Demo v1 application-role
   adapters require their own separately retained evidence.
7. Retain the implemented bounded Host-owned risk-tier policy: reviewed
   low-risk reversible public-web-word effects proceed under policy, high risk
   requires exact approval, and unknown/ambiguous/scope-drifted effects fail
   closed. The available named non-E4 human/native-control checks are retained
   as complete; physical two-monitor remains hardware-blocked, while other AT
   and locales, E4, and release remain separate explicit gates.

[Project status](../PROJECT_STATUS.md) is the sole owner of the active item and
exact next action. [Capability status](CAPABILITY_STATUS.md) owns evidence truth;
[Execution plan](EXECUTION_PLAN.md) retains capability gates and future design,
not a competing active tracker.

## Reading paths

| Reader | Fast path |
| --- | --- |
| Chinese-speaking user unsure what exists or how to ask | [Chinese user front door](../README.zh-CN.md) -> [Capability status](CAPABILITY_STATUS.md) |
| New user | [Root README](../README.md) -> [Tools](TOOLS.md) -> [Configuration](CONFIGURATION.md) |
| Product or hiring reviewer | This overview -> [Capability status](CAPABILITY_STATUS.md) -> [Application matrix](APPLICATION_EVALUATION_MATRIX.md) |
| Demo/product-entry designer | This overview -> [Formal Demo v1](FORMAL_DEMO_V1.md) -> [Application Coverage Set A](APPLICATION_EVALUATION_MATRIX.md) -> [Universal GUI final showcase](UNIVERSAL_GUI_DEMO.md) |
| Project author tailoring a job application | [Career and learning hub](career/) -> [Resume evidence](career/resume/) -> [Capability status](CAPABILITY_STATUS.md) |
| MCP/runtime engineer | This overview -> [Design](DESIGN.md) -> [Driver Contract](DRIVER_CONTRACT.md) -> [Development](DEVELOPMENT.md) |
| Agent engineer | This overview -> [Agent Host](AGENT.md) -> [Planning](PLANNING.md) -> [Continuation](CONTINUATION.md) |
| Reliability/safety reviewer | This overview -> [Quality attributes](QUALITY_ATTRIBUTES.md) -> [Approvals](APPROVALS.md) -> [Evaluation](EVALUATION.md) |
| Long-running workflow engineer | This overview -> [Long-running tasks](LONG_RUNNING_TASKS.md) -> [Roadmap](EXECUTION_PLAN.md) |
| Operator UX engineer | This overview -> [Operator experience](OPERATOR_EXPERIENCE.md) -> [Progress viewer](PROGRESS_VIEWER.md) |
| Maintainer | This overview -> [Maintainer handoff](../HANDOFF.md) -> owner document for the changed layer |

## Documentation ownership rule

This overview owns the cross-system map. It does not own exact tool schemas,
environment variables, state-machine schemas, application cases, or release
claims. Update the relevant owner document first, update
[Capability status](CAPABILITY_STATUS.md) when evidence moves, then update this
overview only when the project shape, feature inventory, implementation map,
quality-attribute mapping, or reading path changes.
