# Project overview

> **Status: canonical orientation map, verified against the repository on
> 2026-08-09.** This page explains the complete project shape without promoting
> planned work to runtime capability. Exact behavior remains owned by the
> linked contract documents; current evidence remains owned by
> [Capability status](CAPABILITY_STATUS.md).

## One-minute summary

Guarded Desktop Agent (formerly `computer-use-mcp`) is evolving from a
model-agnostic Windows desktop MCP server
into a locally governed universal GUI Agent system. The project currently has
four distinct maturity layers:

1. **Windows desktop MCP runtime — implemented:** thirteen stdio tools combine
   UI Automation, primary-display screenshots, native input/window control,
   safety gates, audit logging, and an emergency stop.
2. **Agent Host — experimental and partially integrated:** a CLI can run bounded
   OpenAI or Claude observation workflows through the same MCP server. It adds
   policy, grounding, budgets, explicit approval, redacted trace/reporting,
   explicit memory, and conservative crash recovery.
3. **Planner/Executor and Campaign control plane — substantial internal/offline
   implementation:** strict planning, WAL-backed observation/final-response
   boundaries, campaign ledgers, leases, heartbeat, handoff, and reconciliation
   exist. Three fixed campaign CLI commands exercise one exact synthetic path;
   no general campaign worker or complete application workflow is connected.
4. **Complete-product layers — initial contract work active:** hierarchical
   H1-H6 and continual-learning L0-L2 are implemented through offline observation-runtime composition,
   typed freshness-bound facts, and one pinned reviewed behavior template;
   multi-source observation,
   operator UI, mobile-completion projection, broad application campaigns,
   isolated workers, additional platforms, and verified continual learning
   remain partial or planned at their documented evidence levels.

The central engineering idea is not “let a model click anywhere.” It is to
separate observation, reasoning, authority, execution, durable evidence, and
operator control so each layer can be bounded and verified independently.

## Product boundary

The motivating workflows are reliable Google Docs and WeChat operation, then
broader Windows and enterprise GUI work. The intended product is a universal
GUI execution system where pixels remain the universal fallback and structured
sources improve reliability when available.

The project is currently:

- local and Windows-first;
- model-agnostic at the MCP boundary;
- dual-provider at the experimental Agent Host boundary;
- explicit about foreground ownership and human takeover;
- conservative about replay, recovery, and capability claims; and
- evaluated through contracts and evidence gates before promotion.

It is not currently:

- a safe parallel background controller for the operator's active desktop;
- a production browser automation framework;
- a connected day-scale campaign worker;
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
| Provider verified | A retained credentialed OpenAI/Claude E3 result exists. |
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
         -> OpenAI Responses or Claude Messages adapter             |
         -> policy / grounding / budgets / approval                 |
         -> redacted trace / explicit memory / recovery             |
         -> bounded stdio bridge -> the same MCP server ------------+

internal, not complete product paths
  -> Planner / Executor: plan, observe, reconcile, final response
  -> Campaign control plane: items, batches, leases, heartbeat, handoff

planned projections and adapters
  -> OCR / document text / cropped image / delta observation
  -> passive progress / presence / Decision Cards
  -> host terminal polling -> ChatGPT or Claude mobile notification
  -> isolated workers / macOS / Linux / Android device driver / multi-monitor
  -> verified experience promotion and strategy selection
~~~

The MCP server remains the only desktop execution authority. Planner,
campaign, recovery, UI, and learning layers may request or project work, but
must not create a second native-action path.

## Executable surfaces today

| Surface | Entry point | Current purpose | Boundary |
| --- | --- | --- | --- |
| Desktop MCP server | `guarded-desktop-mcp` | Expose thirteen Windows GUI tools over stdio | Implemented Windows runtime |
| Agent Host | `guarded-desktop-agent` | Run bounded provider/MCP workflows and management commands | Experimental; scoped [E3](E3_EVIDENCE.md) and [E4](E4_EVIDENCE.md) evidence retained |
| Quick Setup | `config setup` | Create one non-overwriting recommended strict configuration | Implemented; no credential write or process start |
| Agent Controls | `config settings` / `config settings --json` | Explain purpose, connection, safety, interface, and exact readiness command | Implemented and inert; no authority or shortcut registration |
| ShortcutBroker | `shortcuts run` | Explicitly own fixed open-controls and a strict configurable cooperative-pause-request shortcut | Implemented/offline verified; loaded-layout guard and foreground host only, no approve/resume/provider/MCP/desktop dispatch |
| Agent config creation | `config init` | Create a non-overwriting Desktop Ask or public-web-word installed profile | Implemented; no credential read or process start |
| Installed readiness | `config doctor` | Check provider setup and verify the configured MCP child's exact thirteen-tool discovery contract | Implemented; real child handshake, no provider request or MCP tool call |
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

## Feature inventory

### Windows MCP runtime

| Feature | State | Implementation | Primary owner |
| --- | --- | --- | --- |
| Model-agnostic stdio MCP | Implemented | FastMCP schemas call a platform-neutral session/driver boundary | [Tools](TOOLS.md), [Design](DESIGN.md) |
| UIA snapshots | Implemented | Flat, 200-control-capped serialization with roles, names, bounds, states, and safe value summaries | [Tools](TOOLS.md) |
| Session refs | Implemented | `ref_N` binds model-visible controls to native UIA elements; one role/name relocation is allowed after staleness | [Tools](TOOLS.md), [Driver Contract](DRIVER_CONTRACT.md) |
| Scoped find | Implemented | Filters the same snapshot/ref model to reduce returned context | [Tools](TOOLS.md) |
| Window enumeration | Implemented | Win32 top-level enumeration includes owned dialogs and foreground identity | [Design](DESIGN.md) |
| Screenshot observation | Implemented / limited | `mss` returns a PNG for the primary display; configured title matches can be blacked out | [Tools](TOOLS.md), [Configuration](CONFIGURATION.md) |
| Bounded OCR observation | Implemented / Windows primary display | `Windows.Media.Ocr` recognizes one explicit region with run/character/pixel/time limits, pre-OCR title-based blackouts, image digest, and local/screen boxes | [Tools](TOOLS.md), [Observation contract](OBSERVATION_CONTRACT.md) |
| Window activation | Implemented; isolated rerun pending | Win32 input-thread attachment, restore, foreground request, reverse cleanup, and postcondition verification | [Capability status](CAPABILITY_STATUS.md) |
| Ref action | Implemented | Prefer UIA Invoke/Select/Value patterns; never silently convert a ref to a center-point click | [Design](DESIGN.md) |
| Coordinate action | Implemented / primary display only | Win32 pointer input uses the same supported DPI-aware pixel space as capture | [Driver Contract](DRIVER_CONTRACT.md) |
| Text and key input | Implemented | UIA ValuePattern when addressed by ref; Win32/native key events for focused input and chords | [Tools](TOOLS.md) |
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
| OpenAI adapter | Implemented/offline verified | Responses API continuation, strict tool/result correlation, byte/token gates, bounded PNG handling | [Agent Host](AGENT.md), [Evaluation](EVALUATION.md) |
| Claude adapter | Implemented/offline verified | Messages history, adjacent tool-use/results, atomic history packing, byte/token gates | [Agent Host](AGENT.md), [Evaluation](EVALUATION.md) |
| Bounded runner | Implemented | One canonical loop owns budgets, ledger, provider turns, policy, dispatch, verification, and cleanup | [Agent Host](AGENT.md) |
| Sole desktop dispatch site | Implemented/frozen | All Agent desktop execution routes through the Runner boundary and then the stdio MCP child | [Agent Host](AGENT.md) |
| Reviewed tool registry | Implemented | Host derives effect/schema/approval facts; provider output cannot grant authority | [Agent Host](AGENT.md) |
| Policy modes | Implemented | Read-only default; approved actions are opt-in, budgeted, grounded, and confirmed by default. The fixed public-web-word profile uses Host-owned low/high/unknown classification: low proceeds without a prompt, high requires exact approval, and unknown is denied | [Approvals](APPROVALS.md) |
| Grounding and verification | Implemented/fake verified | Actions require fresh observation binding and mandatory post-action observation | [Approvals](APPROVALS.md) |
| Bounded stdio bridge | Implemented | Absolute child command, reviewed environment, exact nine-schema discovery, bounded frames/results, generation invalidation | [Agent Host](AGENT.md) |
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
| One-shot dual-provider Planner | Implemented/internal | Isolated no-tool OpenAI/Claude structured-output request; fixed one-call failure, no fallback | [Planning](PLANNING.md) |
| Observation Executor | Implemented/internal | At most four observation steps; WAL before dispatch; shared Runner authority; known completion or fail-closed uncertainty | [Planning](PLANNING.md) |
| Observation reconciliation | Implemented/internal | Repairs only the exact missed plan CAS after a known completed result; never redispatches | [Planning](PLANNING.md) |
| Tool-free final response | Implemented/internal | Lossless observation compiler, isolated provider adapters, dedicated WAL, ordered budget/plan/trace terminalization | [Planning](PLANNING.md) |
| Final-response reconciliation | Preflight implemented/internal | Pure reconstruction of exact completed evidence; applying CAS/cleanup and CLI exposure remain next | [Planning](PLANNING.md) |
| Bounded Planner/Executor CLI | Implemented/read-only | `ask` and `plan run` compose one Planner call, one to four reviewed observations through Runner, and one tool-free final answer; side effects remain unavailable | [Capability status](CAPABILITY_STATUS.md) |
| Hierarchical task and behavior trees | H1-H6 implemented/offline; H7-H8 planned | Immutable versioned nodes, canonical tree/envelope digests, structural/budget limits, pure state reduction, lossless linear-plan projection, private `RunLock`-bound atomic snapshots with exact CAS, digest-bound next-leaf compilation, an optional observation-only projection over the existing Runtime Executor, typed freshness/window-bound three-valued facts, and one exact-version reviewed BOSS observation-ladder template exist without a second dispatch site or new authority | [Hierarchical task and behavior trees](HIERARCHICAL_TASK_AND_BEHAVIOR_TREES.md) |

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
| General campaign worker | Implemented/internal, offline only | Manifest-routed capability-composed scenario registry with A1-A19 as built-in examples rather than a closed list; validated new specs register without Runner changes. Includes explicit stable-item preparation, provider execution through the sole Runner boundary, strict semantic result schema, digest commit, one-item handoff, fresh-run resume, and automatic exhausted-manifest completion with exact terminal heartbeat retirement. No generic real-application acceptance claim | [Roadmap](EXECUTION_PLAN.md) |
| Composable discovery adapters | Implemented/internal, offline only | Declarative `link_url`/`control_name` adapters bound to a campaign kind derive stable public item keys from one bounded foreground `ui_snapshot`; two CLI commands create the reviewed campaign and record one operator-driven pass with the provider forbidden and no page, URL, scope, or item selector. The campaign carries the ordinary worker digests, so discovery enters `campaign start` unchanged. Only BOSS has retained on-device discovery evidence, under its own separate fixed contract | [Long-running tasks](LONG_RUNNING_TASKS.md) |
| Host completion polling | Implemented/internal contract | Bounded read-only projection and deduplicated fake-host terminal/attention decisions; the local Task Center consumes the projection, while no mobile bridge exists | [Long-running tasks](LONG_RUNNING_TASKS.md#host-visible-completion-and-mobile-notification) |

### Observation, operator, application, and learning layers

| Feature family | State | Intended implementation | Primary owner |
| --- | --- | --- | --- |
| Multi-source observation | Partial | UIA, full-screen PNG, bounded region OCR, standalone cropped images, and bounded document text exist; complete cross-source envelopes and delta observations remain | [Observation contract](OBSERVATION_CONTRACT.md), [BOSS OCR evidence](BOSS_OCR_EVIDENCE.md) |
| Token-efficient observation | Contract/planned experiments | Escalate from structured/cheap sources to pixels; retain item-local context and measured cost | [Token efficiency](TOKEN_EFFICIENCY.md) |
| Presence and progress UI | Partial | Passive progress is implemented and follows durable ordinary `run`/`resume`, bounded `ask` / `plan run`, explicit read-only recovery phases, and validated state during fixed MCP-backed campaign execution; zero-port campaign control remains window-free. System High Contrast, reduced motion, bounded UIA status names, native automated 200%/400% text reflow, bounded English/Simplified-Chinese presentation, strict dark/light/system theme resolution, and Host-owned foreground-monitor composition are implemented and verified through the stated offline/native boundary; human assistive-technology, human large-text/visual-design, and physical two-monitor review remain open. The fixed synthetic campaign lifecycle is [desktop verified](CAMPAIGN_PROGRESS_LIFECYCLE_EVIDENCE.md); one persisted read-only observation has separate [recovery progress evidence](RECOVERY_PROGRESS_LIFECYCLE_EVIDENCE.md); and one fixed provider-free plan has separate [plan progress](PLAN_PROGRESS_LIFECYCLE_EVIDENCE.md) and [presence](PLAN_PRESENCE_LIFECYCLE_EVIDENCE.md) lifecycle evidence. The current [feature-freeze non-E4 audit](FEATURE_FREEZE_NON_E4_EVIDENCE.md) covers ten theme/locale/large-text safe-denial cases and fixed notification lifecycle. The earlier bounded primary-display halo is also [desktop verified](PRESENCE_WINDOW_EVIDENCE.md); the newer [multi-display contract](OPERATOR_MULTI_DISPLAY.md) still lacks physical two-monitor evidence. Integrated BOSS-campaign progress/presence evidence and recovery presence desktop evidence remain planned | [Operator experience](OPERATOR_EXPERIENCE.md), [Operator accessibility](OPERATOR_ACCESSIBILITY.md), [Operator localization](OPERATOR_LOCALIZATION.md), [Operator personalization](OPERATOR_PERSONALIZATION.md), [Native operator multi-display composition](OPERATOR_MULTI_DISPLAY.md), [Progress viewer](PROGRESS_VIEWER.md) |
| Decision Cards | Partial / configurable Windows | Pure cards compile 2-4 bounded options; generated installed profiles enable the focus-taking four-choice Win32 adapter, which yields authority and returns exact-effect approval, re-observe, durable defer, or denial through the existing ApprovalPort. Native Text/Edit/Button semantics, safe initial focus, standard keyboard traversal, bounded countdown announcements, system High Contrast/reduced motion, native automated 200%/400% reflow, English/Simplified-Chinese presentation, and strict dark/light/system theme resolution are implemented and verified through the stated offline/native boundary. Internal option IDs and authority stay locale-neutral. Human Narrator/NVDA, human large-text, and visual-design review remain open; broader current-candidate cross-application evidence remains planned | [Operator experience](OPERATOR_EXPERIENCE.md), [Operator accessibility](OPERATOR_ACCESSIBILITY.md), [Operator localization](OPERATOR_LOCALIZATION.md), [Operator personalization](OPERATOR_PERSONALIZATION.md), [Feature-freeze non-E4 evidence](FEATURE_FREEZE_NON_E4_EVIDENCE.md), [Approved actions](APPROVALS.md) |
| Task Center and outcome receipts | Implemented / CLI-first, offline verified | Read-only Attention/In progress/History grouping over validated redacted run/campaign state, fixed human receipt wording, and strict immutable public-web-word completion receipts; no provider, MCP, desktop, approval, resume, retry, cancel, campaign-advance, or notification port | [Task Center](TASK_CENTER.md) |
| Pre-run Review | Implemented / CLI-first, offline verified | Host-fixed public-web-word objective, applications, data use, output, seven-side-effect bound, low-risk Host authorization, zero expected high-risk approvals, stop conditions, residue, and exact acknowledgement before every external startup; no model prose or blanket approval | [Pre-run Review](PRE_RUN_REVIEW.md) |
| Cooperative Pause/Takeover/Resume | Implemented / CLI-first, offline verified | One strict local control lifecycle for the public-web-word Runner loops; pause waits for a durable safe boundary, releases Agent desktop authority, and resumes only after explicit operator return plus fresh observation. No `BlockInput`, crash reconstruction, campaign mutation, or uncertain replay | [Cooperative control](COOPERATIVE_CONTROL.md) |
| Approval Inbox and local notification | Implemented / CLI-first, offline verified | Strict expiring identity/digest records supplement the bound Decision Card; optional Windows notification carries fixed wording only. Neither surface can decide, control, retry, replay, or dispatch, and native accessibility evidence remains open | [Approval Inbox](APPROVAL_INBOX.md) |
| Public web to Word workflow | Implemented / exact scoped evidence | One installed fixed workflow lets a reviewed OpenAI model observe a fresh public Microsoft Support page, author a bounded brief, and write, save, reopen, visually verify, and clean up one disposable Word fixture through the existing Runner/MCP and Decision Card boundaries. The [retained result](PUBLIC_WEB_WORD_PRODUCT_EVIDENCE.md) does not establish arbitrary websites or applications | [Workflow contract](PUBLIC_WEB_WORD_WORKFLOW.md) |
| Mobile notifications | Host capability; internal repository projection implemented | Local fixed-content approval attention exists, but mobile terminal/attention delivery remains absent; no MCP-log completion inference or repository mobile bridge | [Operator experience](OPERATOR_EXPERIENCE.md#remote-and-mobile-notification-semantics) |
| Wave 1 applications | Planned acceptance | BOSS read-only, Google Docs long document, WeChat draft-only, then cross-application handoff | [Application matrix](APPLICATION_EVALUATION_MATRIX.md) |
| Broader applications | Planned | Media/design, Office/data, remote/system, legacy, and enterprise governance waves | [Application matrix](APPLICATION_EVALUATION_MATRIX.md) |
| Complete-product demonstration | Planned/final integration gate | One chaptered campaign with faults, takeover, tokens, authority, and retained artifacts | [Universal GUI demo](UNIVERSAL_GUI_DEMO.md) |
| Continual learning | L0-L2 implemented/offline; L3-L5 planned | Redacted outcomes and fresh typed facts remain isolated; content-free procedure definitions now have frozen held-out replay, explicit reviewed data lifecycle, and exact rollback pins. No runtime procedure loader, memory injection, strategy routing, automatic promotion, training, or live authority exists | [Continual learning](CONTINUAL_LEARNING.md) |
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
| `src/computer_use_agent/providers/` | OpenAI and Claude ordinary, Planner, and final-response adapters |
| `src/computer_use_agent/trace.py`, `report.py`, `memory.py` | Safe state, metrics, reporting, and explicit memory |
| `src/computer_use_agent/episode_outcome.py` | Read-only L0 terminal outcome normalization, explicit metric coverage, durable source reconciliation, and no learning or execution port |
| `src/computer_use_agent/learning_quarantine.py` | Private L1 fresh-fact candidate extraction, revision-CAS lifecycle, digest-only audit events, and no memory injection or execution port |
| `src/computer_use_agent/verified_procedures.py` | Inert L2 procedure schema, frozen fixture decoder, pure replay/held-out gate, reviewed lifecycle, and exact rollback without runtime ports |
| `src/computer_use_agent/progress_view.py`, `task_center.py`, `product_receipt.py` | Structurally validated status projection, read-only task grouping/fixed receipt wording, and strict private product completion evidence |
| `src/computer_use_agent/public_web_word.py`, `pre_run_review.py` | Fixed workflow/profile guard plus the Host-compiled Scope Sheet, versioned JSON, and human rendering without external ports |
| `src/computer_use_agent/continuation.py`, `recovery.py`, `reconstruction.py` | Sensitive WAL, crash classification, and bounded recovery |
| `src/computer_use_agent/planning.py`, `planner.py`, `plan_store.py` | Declarative plan compilation, provider port, and persistence |
| `src/computer_use_agent/hierarchical_control.py` | Inert H1 node schema, canonical tree digest, reviewed limits, pure status reduction, and linear-plan projection |
| `src/computer_use_agent/tree_store.py` | Private H2 `RunLock`-bound atomic snapshots, strict restart decoding, and sequence/tree-digest CAS with no external ports |
| `src/computer_use_agent/hierarchical_compiler.py` | Pure H3 next-leaf result, digest-bound inert boundary, ordered leaf transition reducer, and unresolved-choice fail-closed behavior |
| `src/computer_use_agent/hierarchical_runtime.py` | Port-free H4 plan/tree identity binding, exact leaf status projection, and local-only reconciliation around the existing Runtime Executor |
| `src/computer_use_agent/world_state.py` | Pure H5 content-free observation evidence, typed facts, exact freshness/window invalidation, and unavailable-not-false condition evaluation |
| `src/computer_use_agent/behavior_templates.py` | Immutable H6 exact-version template registry, pinned BOSS observation ladder, inert request binding, and no-fallback reducer compatibility |
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
| Human coexistence | Recent-input yield, visible foreground assumptions, explicit takeover, planned passive non-activating UI | [Operator experience](OPERATOR_EXPERIENCE.md) |
| Observability and auditability | Fixed codes, bounded JSONL, safe metrics, deterministic reports, evidence-level dashboard | [Trace](TRACE.md), [Capability status](CAPABILITY_STATUS.md) |
| Testability and evidence integrity | Pure logic separated from named desktop smokes; frozen E1/E2 manifests; E3/E4 and release gates stay explicit | [Evaluation](EVALUATION.md), [Release](RELEASE.md) |
| Resource boundedness | Limits on frames, results, images, events, requests, tokens, turns, calls, side effects, batches, and artifacts | [Context and memory](CONTEXT_MEMORY.md), [Token efficiency](TOKEN_EFFICIENCY.md) |
| Performance and context efficiency | `find`, structured-first observation ladder, item-local context, bounded history packing, measured cost per result | [Token efficiency](TOKEN_EFFICIENCY.md) |
| Portability and maintainability | Platform-free Driver Contract, ports/adapters, canonical owner docs, deliberate versioned state schemas | [Design](DESIGN.md), [Tech stack](TECH_STACK.md) |
| Interoperability | Standard MCP surface and provider-neutral host types with isolated OpenAI/Claude adapters | [Agent Host](AGENT.md) |

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
| E3 | Real provider with harmless fake MCP | opt-in OpenAI and Claude integration tests |
| E4 | Real provider plus isolated Windows desktop | four-cell disposable Notepad/VM runbook |
| E5 / release regression | Candidate-wide automated and human evidence | CI, preflight, retained records, explicit approval |

Offline passing tests do not fill E3/E4/application cells. See
[Evaluation](EVALUATION.md) and [Release evidence](RELEASE_EVIDENCE.md).

## Current gaps and next gates

In priority order:

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
6. With provider E3 and isolated E4 retained, execute bounded BOSS evidence,
   then Google Docs and WeChat cases only after their preceding gates.
7. Retain the implemented bounded Host-owned risk-tier policy: reviewed
   low-risk reversible public-web-word effects proceed under policy, high risk
   requires exact approval, and unknown/ambiguous/scope-drifted effects fail
   closed. Next close the available non-E4 human/native-control checks;
   keep physical two-monitor, E4, and release as later explicit gates.

The authoritative current priorities live in
[Capability status](CAPABILITY_STATUS.md) and [Roadmap](EXECUTION_PLAN.md).

## Reading paths

| Reader | Fast path |
| --- | --- |
| New user | [Root README](../README.md) -> [Tools](TOOLS.md) -> [Configuration](CONFIGURATION.md) |
| Product or hiring reviewer | This overview -> [Capability status](CAPABILITY_STATUS.md) -> [Application matrix](APPLICATION_EVALUATION_MATRIX.md) |
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
