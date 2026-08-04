# Agent Host contract and safety boundary

> **Status: experimental Agent vertical slice.** The provider-neutral
> contract, local stdio bridge, bounded runner, OpenAI Responses adapter, and
> Claude Messages adapter are
> implemented. The CLI can inspect desktop text and bounded screenshots through four observation
> tools. Opt-in locally approved actions are implemented and have scoped
> [isolated E4 evidence](E4_EVIDENCE.md); unbounded recovery remains unavailable.
> Opt-in recovery can chain up to four reviewed read-only boundaries under one lock.

This is the canonical contract companion to the planned
[Agent implementation plan](AGENT_IMPLEMENTATION_PLAN.md). It uses the current
thirteen-tool local stdio MCP server as its sole desktop execution authority.

## Scope

The future host is a local, CLI-first process with adapters for OpenAI
Responses and Claude Messages. It must use a local stdio MCP child and must
not import `computer_use_mcp.core.Session`, the Windows driver, or native
control code.

~~~text
CLI / local operator
  -> Agent Host (policy, ledger, memory, trace)
      -> provider adapter
      -> local stdio MCP bridge
          -> guarded-desktop-mcp server
              -> gate, human activity, confirmation, e-stop, audit
              -> Windows UI Automation / Win32
~~~

The host may make this boundary stricter; it cannot bypass any server-side
allowlist, human-activity check, confirmation, e-stop, or audit behavior.

## Current CLI behavior

The `guarded-desktop-agent` entry point and `python -m computer_use_agent` expose
the following commands:

- `config validate --config PATH` parses and validates TOML without creating
  state directories, reading provider credentials, or starting another process.
- `run --config PATH --task TEXT --dry-run` acquires the local run lock, creates
  a bounded initial `RunState`, prints task length and other safe metadata, and
  releases the lock. It calls no provider, MCP, approval, or desktop port.
- `run --config PATH --task TEXT` uses the configured optional provider and
  local stdio MCP bridge. Read-only mode exposes three text observations and
  one bounded PNG screenshot observation.
  Both `approved_actions` and `agentic_actions` additionally expose reviewed
  action tools, then apply grounding, budgets, MCP checks, and mandatory
  post-action observation. The former adds digest-bound local approval for
  every side effect; the latter skips only that prompt. The CLI returns final text,
  run ID, and model/tool counts as JSON.
- `run ... --memory-scope SCOPE` explicitly includes up to eight active,
  revalidated, user-confirmed memories from that exact scope in the provider's
  initial turn. Omitting it reads no memory; it is rejected with `--dry-run`.
- `plan run --config PATH --task TEXT` makes exactly one configured-provider
  Planner request over the fixed `ui_snapshot`, `find`, `list_windows`,
  `screenshot`, `capture_region`, and `ocr` schemas, accepts only one to four
  observation steps plus the
  required final step, executes observations through the sole Runner boundary,
  and makes one stateless tool-free final-response request. It exposes no tool
  selector, action, approval, memory, recovery, or ordinary provider-loop
  option. Continuation WAL is required. [OpenAI and Claude provider evidence is retained](E3_EVIDENCE.md)
  for one reviewed model per provider. The separate [E4 record](E4_EVIDENCE.md)
  covers the reviewed Agent Host desktop path, not a separate Planner pass.
- `eval --cases PATH [--report PATH]` runs versioned E1/E2 JSON fixtures with
  deterministic fake ports, compares exact canonical traces and dispatched
  tool names, prints a JSON report, and exits nonzero on any mismatch or safety
  escape. It needs no provider SDK, credential, MCP child, or desktop.
- `release preflight` runs the clean-source, public-version, Ruff, full offline
  pytest, independent frozen crash-reconstruction and OpenAI stateless-replay E2 gates, frozen workflow
  E1/E2, wheel-build, and clean-wheel smoke gates. Replay evidence records the
  canonical fixture and manifest hashes, case count, and targeted test counts.
  Every child
  receives only a reviewed platform/path/temp environment allowlist; provider,
  cloud, GitHub, Python import-path, and arbitrary host variables are not
  forwarded. User site loading and pip index/input/config discovery are
  disabled. The command writes only fixed outcomes, counts, package identity,
  UTC generation time, non-path Python/platform identity, and SHA-256 evidence.
  It rechecks `HEAD` and the complete working tree after all gates; a dirty
  endpoint, changed commit, or any missing/failed gate makes the aggregate
  result fail.
- `trace RUN_ID --config PATH` validates and prints one persisted safe
  checkpoint with aggregate latency/token/tool metrics plus its redacted JSONL events. It starts no external port and
  never implicitly resumes or mutates the run. Explicit `resume` is restricted
  to a pre-provider initial checkpoint; `cancel` closes a non-terminal record.
- `recover RUN_ID --config PATH --task TEXT --execute-read-only` executes at
  most one sequence-checked boundary by default. `--max-steps N` permits 1-4
  reviewed read-only calls under the same run lock. A completed side effect may
  trigger one synthetic `ui_snapshot`, then stops. The command never replays
  uncertain work or dispatches a recovered action. OpenAI-only
  `--stateless-replay` explicitly replaces the current remote continuation for
  the next provider boundary after complete transcript, correlation, contract,
  byte, and token preflight. It is never an automatic fallback.
  A durably completed final provider response with no tool calls can be
  sequence-checked and terminalized locally as `SUCCESS`; this makes zero
  provider/MCP calls, records only final-text length in the safe checkpoint,
  and deletes the sensitive continuation artifact.
  A completed recovered provider turn containing one or more action requests
  is likewise terminalized locally, but as `FAILED` with the fixed
  `RECOVERED_ACTION_REQUESTED` code. Calls remain input records only; no policy,
  approval, MCP dispatch, or action authority is entered, and the CLI exits
  nonzero after deleting the continuation.
- `campaign resume-synthetic --config PATH --campaign-id ID --run-id ID`
  exposes only the fixed durable restart/resume boundary. It accepts no task,
  item selector, provider, or desktop option; reconstructs the finished
  synthetic session under a fresh Runner lock; transfers heartbeat ownership;
  and prints only fixed resume control metadata.
- `campaign prepare-synthetic --config PATH --campaign-id ID --run-id ID`
  creates and claims exactly one `synthetic_read_only_observation` campaign
  containing only `synthetic:list_windows`. It binds the current Host and batch
  policy plus reviewed tool-registry digest, opens no provider or MCP port,
  starts no trace, and exposes no kind, item, batch, lease, task, or action
  selector.
- `campaign run-claimed-synthetic --config PATH --campaign-id ID --run-id ID`
  reconstructs only the exact pre-existing active synthetic claim, launches the
  configured local MCP child, and reuses the sole Runner dispatch boundary for
  `list_windows` through commit and handoff. A fail-closed provider guard makes
  any model call impossible; no task, item selector, action, or approval option
  is exposed.
- `report --config PATH` aggregates phase/success/failure and token/call/latency
  metrics from bounded validated checkpoints only. It opens no trace JSONL,
  provider, MCP, approval, or desktop port and fails closed on corrupt records.
- `remember add/list/delete` explicitly manages local preference and verified
  procedure records. Add requires confirmation and a future expiry; no memory
  is automatically extracted or injected into provider context.

`src/computer_use_agent/planning.py` defines a separate non-executable TaskPlan
contract. Its strict JSON compiler accepts only host-scoped reviewed tools,
derives effect and approval metadata from the registry, forbids sensitive
arguments, binds task and registry digests, and assigns ordered step IDs.
`plan_store.py` adds strict bounded private snapshots beneath the run directory.
Creating, reading, or transitioning them requires the existing application
RunLock; transitions atomically replace state only after exact sequence and
plan-digest comparison. `planner.py` adds a one-shot provider-neutral port: its
bounded immutable request contains only task text and host-selected exact
non-sensitive tool schemas, and its only result is untrusted JSON passed to the
same compiler. Planner failures are fixed, never retried, and never fall back.
`providers/openai_planner.py` implements that port as one isolated, stateless
Responses API Structured Outputs request. It advertises no function tools,
continuation, replay history, or reasoning payload; sets `store=false`; applies
complete byte/token preflight before I/O; and rejects refusals, incomplete or
ambiguous output, malformed arguments, and scope drift.
`providers/anthropic_planner.py` provides the same boundary through one Claude
Messages request using GA `output_config.format`, with no tools, history,
thinking, retry, or fallback. It rejects refusal, token truncation, tool-use,
extra content, malformed output, and scope drift. Both adapters share the
bounded `planner_wire.py` envelope converter before the existing exact host
compiler. Compiling, storing, or locally transitioning a plan performs no
policy, approval, MCP, or desktop call and grants no tool authority.
`executor.py` adds a pure first-step preflight only: it rechecks the exact
persisted sequence and plan digest, current run/task/registry bindings, ordered
pending status, and fresh call identity, then reconstructs a `requested`
`ToolCall`. It does not mutate the plan or enter policy, grounding, budget,
approval, write-ahead, MCP, or verification code. The bounded `plan run` CLI
consumes Planner output only through the observation runtime described below;
the plan itself still grants no authority. Its non-executing
`BoundedExecutorSession` keeps the same
live PlanStore lock for up to four observation steps, generates identities
inside the host, allows one outstanding call, preserves the complete ledger as
a monotonic prefix, and accepts progress only after exact call/result ledger
evidence plus the matching plan transition. Unknown outcomes must remain
`in_progress` and close the session. It has no external ports and still cannot
dispatch; see [Task planning](PLANNING.md).

`executor_runtime.py` adds the first plan-connected runtime, but only for
observation and tool-free final-response steps. `planned_observation_runtime.py`
and `plan run` now compose that API without adding a dispatch site. Opening requires continuation
WAL, creates one new plan/run under the application RunLock, verifies exact MCP
discovery, and retains one recorder, continuation, grounding state, and MCP
generation across bounded steps. Before any call reaches the shared Runner
boundary, its plan step is atomically changed to `in_progress`. Success and
known failure then commit `completed` or `failed`; an unknown outcome leaves the
step `in_progress`, retains the sensitive continuation, closes every live port,
and cannot be retried. The module contains no direct MCP dispatch call. It does
not permit side effects or resume an earlier session implicitly.

`executor_reconciliation.py` adds a narrower explicit crash repair, not a
general resume path. Under the existing RunLock it strictly cross-checks an
`in_progress` observation plan step against the final correlated tool
call/result in a revalidated completed WAL envelope. Only a known completed
outcome can CAS the plan locally to `completed` or `failed`; the WAL is retained
and no external port is called. Dispatch intent, unknown outcome, side effects,
snapshot/task/registry/call drift, and malformed evidence leave the plan
unchanged. It cannot continue execution, restore Runner state, execute final
text, or replay historical calls.

`executor_final.py` defines the final-request compilation boundary. Its compiler
accepts only an exact plan with one to four completed observation steps and a
pending final step, plus a canonical in-memory ledger containing exactly the
matching successful call/result/observation groups. It rechecks task, registry,
snapshot, recovery, verified observation, and budget state, then produces a
bounded digest-bound `FinalResponseRequest`. Historical calls are input
evidence only and are not exposed as tool calls, schemas, approvals, or dispatch
work. Isolated tool-free adapters implement `FinalResponsePort`, while the
compiler itself does not call a provider, consume budget, write WAL, transition
the plan, or trust/terminalize response text.

`final_response_wire.py` plus isolated OpenAI and Claude final-response adapters
implement that port and are selected by the bounded plan CLI composition. Canonical task
and observation text remains untrusted JSON data; PNGs are digest/dimension
bound and sent as ordered provider-native image blocks. Each adapter performs
one stateless request with no tools, continuation, retry, fallback, policy,
approval, or MCP surface, and applies exact request-byte plus conservative
token-window gates before I/O. Only one bounded non-empty text response is
accepted. The adapters do not write continuation state, consume host budget,
transition the final step, record terminal trace state, or make returned text
authoritative.

Final adapters return a correlated `FinalResponseResult` containing response
identity, bounded sensitive text, and normalized usage rather than a bare
string. `executor_final_store.py` adds an independent RunLock-bound private WAL
whose version 2 evidence binds the exact plan/step/turn/request, source plan and
checkpoint sequences/digests, ordinary continuation payload, and provider
latency, with only prepared, dispatch-intent, and completed CAS transitions.
Version 1 fails closed rather than being migrated. It is deliberately separate from the ordinary
provider continuation envelope, so existing recovery cannot interpret final
text as a resumable provider/tool turn. A completed WAL remains non-authorizing:
it does not consume budget, transition the plan, write terminal trace state,
publish text, or permit replay by itself.

`RuntimeExecutorSession.execute_final_response()` now supplies the first
orchestration boundary for that WAL. It rereads and compiles an exact pending
final step, creates `prepared`, CAS-marks the plan step `in_progress`, writes
`dispatch_intent`, and only then calls one explicitly injected tool-free
`FinalResponsePort`. Correlated completion is durable before provider usage is
consumed into the host budget and canonical model-turn ledger; only afterward
may the final plan step become `completed` and the safe checkpoint become
`SUCCESS`. The ordinary observation continuation is then removed and all live
ports and the run lock close. Any intent-or-later failure preserves both WALs,
keeps the final step non-terminal, closes without retry, and never enters normal
provider recovery, policy, approval, or MCP.

`executor_final_reconciliation.py` adds a pure, non-writing preflight for an
exact completed-final crash window. It revalidates caller-pinned plan/final WAL,
ordinary continuation, safe checkpoint/trace, task/registry, observation
ledger, and the recompiled original request. Only completed provider evidence
can yield a canonical terminal state and explicit already-recorded flags;
prepared/intent state, drift, and malformed evidence fail closed. The module
has no store writer or external/recovery port, cannot publish final text, and
does not apply plan, trace, budget, or continuation changes.
`executor_final_reconciliation_apply.py` is the separately reviewed local
writer. Under the same RunLock it rereads and recompiles the pinned evidence,
CAS-completes only the final plan step, writes or reuses exactly one terminal
model-turn trace and `SUCCESS` checkpoint, retains final WAL v2, and removes
only the ordinary sensitive continuation. A cleanup retry accepts the already
completed plan and terminal record without duplicating either. It has no
provider, MCP, policy, approval, recovery-executor, or desktop port. CLI
exposure remains unavailable.

`AgentRunner` accepts the three external ports through `RunnerPorts`. All
normalized tool requests now enter one shared `_execute_requested_call_boundary`.
That method is the only Runner MCP dispatch site and contains the existing
policy, grounding, tool/side-effect budget, approval, write-ahead, result
validation, observation update, and post-action verification behavior. The
provider loop delegates every call to it; there is no plan-specific dispatch
path. Its first ledger event contains only task
length, while raw task text remains in the in-memory `RunState`. The host policy
denies side effects by default; opt-in action mode still requires local approval. Model-turn,
tool-call, result, and observation events are appended to the canonical ledger;
model and tool budgets are consumed before another external call can occur.
The current ledger is in-memory only and is not a resumable trace.

`campaign_observation_runtime.py` reuses that same boundary for one internal
execution-bearing campaign seam. It accepts only an already-claimed first item
from the fixed `synthetic_read_only_observation` campaign, requires the sole
planned key `synthetic:list_windows`, constructs one `list_windows` call inside
the Host, and persists `OBSERVED` only after a successful correlated result.
Its explicit extraction extension accepts at most 64 Ki characters, produces
only the non-empty-line count as its extraction value, persists no result text
in campaign state or redacted trace, and then persists `EXTRACTED`. Its commit
extension re-counts that bounded result, hashes only canonical
`{"window_count":N}` JSON, and persists the digest at `COMMITTED`. Its handoff
extension closes through the existing continuation validator with measured
Runner usage and writes the fixed campaign handoff without changing heartbeat
ownership. Its restart/resume extension creates a fresh Runner run with no
caller-supplied task text or prior `BatchSession`, reconstructs the exact
finished synthetic session from durable campaign records, transfers heartbeat
ownership, and accepts only the exhausted resume decision. That extension
makes no provider or MCP call and does not complete the campaign or retire its
heartbeat. The module exposes no free-form selector, side effect, or second MCP path.
The three fixed campaign boundaries are consumed by `campaign
prepare-synthetic`, `campaign run-claimed-synthetic`, and `campaign
resume-synthetic`. Preparation creates only the exact fixed manifest,
discovery record, heartbeat, single-item batch, and claim. Campaign-kind/item
selection and a general worker remain unavailable.

`boss_campaign_discovery.py` adds a separate non-executable application
preparation boundary. Under the existing run lock it can create only the fixed
`boss_saved_job_read_only` manifest and append stable public job keys parsed
from bounded, complete BOSS UIA link values on a same-snapshot page carrying
the reviewed source marker.
It drops URL query data and all page content, makes repeated page ingestion
idempotent, and refuses writes after any batch transition. It has no desktop,
provider, navigation, item-processing, or side-effect port. A separate fixed
runtime now sends one foreground `ui_snapshot` through the same Runner/project
MCP boundary used elsewhere and passes only a correlated successful result to
the parser. The `prepare-boss-discovery` and `observe-boss-page` campaign
commands accept no task, URL, page, scope, or item selector. The path has
a [current-contract two-pass on-device result](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md)
with twelve identities and distinct source digests. Progression remained
externally controlled; automatic navigation and the 100-item application gate
remain unfilled.

`boss_campaign_batch_runtime.py` adds one zero-port worker-side boundary.
`campaign start-boss-batch` validates at least two complete current-contract
discovery passes, asks the existing `BatchCoordinator` for a stable-ordinal
maximum-20-item plan, creates one bounded heartbeat, and claims only ordinal 1.
It accepts no item, URL, page, scope, batch, campaign-kind, provider, or desktop
input. `boss_campaign_item_runtime.py` adds a single-call identity-presence slice:
fixed `campaign run-claimed-boss` reconstructs the exact active claim, executes
one foreground `ui_snapshot` through Runner/project MCP with provider access
forbidden, requires that exact public job key, persists only source and
canonical presence digests through `COMMITTED`, finishes at
`TOOL_CALL_LIMIT`, and writes handoff. `boss_campaign_restart_runtime.py` adds
fixed `campaign resume-boss-batch`; a fresh zero-port run reconstructs the
finished session, transfers heartbeat ownership, opens the exact resumed plan,
and claims its first item. These paths are offline verified and accept no item
selector. They do not navigate automatically, extract job semantics, or fill
the 100-item application gate.

`discovery_adapters.py`, `application_campaign_discovery.py`, and
`application_discovery_runtime.py` generalize identity discovery without
generalizing authority. An adapter is reviewed data bound to one campaign kind:
`link_url` keeps only the path identifier of an `https` target on an
allowlisted host and discards scheme, host, query, and fragment, while
`control_name` keeps only a control name matching the declared roles and
pattern. Both require a same-observation source marker and bound snapshot size,
lines, identities per pass, campaign items, and passes. `campaign
prepare-discovery` creates only the empty reviewed campaign for one registered
kind; `campaign observe-discovery-page` takes no kind, resolves the adapter from
the durable manifest, and dispatches exactly one foreground `ui_snapshot`
through the same Runner/project-MCP boundary with the provider forbidden. The
created campaign carries the ordinary worker policy and schema digests, so it
enters `campaign start` unchanged. These paths are offline verified only.

`boss_semantic_item_runtime.py` adds a separate one-item semantic policy
without changing that retained identity seam. Fixed
`start-boss-semantic-batch` permits one item, at most five provider turns and
five tool attempts, and zero side effects. Fixed
`run-claimed-boss-semantic` re-establishes the exact public identity through
Runner UIA, discloses only the exact next observation tool, accepts only strict
assessment/result JSON, and commits only a schema-, source-, and fixed
no-preference-policy-bound digest. UIA and document text are connected; the
still-gated OCR Host baseline produces a zero-OCR-dispatch
`CONTENT_UNAVAILABLE` handoff. Fixed `resume-boss-semantic-batch` transfers a
successful batch to a fresh zero-port run and claims the exact next item. These
paths are offline verified, have no free-form task or item selector, and have
no on-device semantic result.

Non-dry runs now project that in-memory ledger to an atomic safe checkpoint and
append-only redacted JSONL trace. The projection deliberately omits task/final
text, observation content, screenshots, provider IDs/errors, and typed values.
See [Agent traces](TRACE.md) for phases, storage bounds, inspection, and the
bounded multi-step recovery boundary.

Before each provider call, the host applies the configured event-count context
budget to the canonical ledger view supplied to the adapter. It preserves the latest continuation, policy
decisions, latest observation, and identity-correlated call/result groups, or
fails closed if mandatory state cannot fit. The canonical ledger remains
unchanged. See [Context and memory](CONTEXT_MEMORY.md) for reducer and explicit
SQLite-memory rules.
Every final provider SDK request is additionally bounded by configurable
canonical UTF-8 JSON bytes (8 MiB default, 1 KiB-48 MiB reviewed range). This
includes task, explicit memory, tools/results, screenshots, and Claude history;
oversize requests fail before network I/O. Required provider/model-specific
`context_window_tokens` and `output_token_reserve` settings add a conservative
pre-network token-window gate over the complete request. Each visible UTF-8
request byte is charged as one input token; OpenAI continuations additionally
carry forward the preceding provider-reported input/output usage. The gate
fails with a fixed provider code and never splits mandatory atomic groups.
Persisted OpenAI recovery restores that usage together with the required
`previous_response_id`, a canonical request-contract digest, and the safe
memory-disclosure marker. Continuation v5 also retains the exact initial SDK
input in the private sensitive artifact and binds its SHA-256 into that
contract. It retains every bounded canonical JSON `response.output` item in
ordered response-ID batches; missing, non-correlated, oversized, or drifted
state fails before the next provider dispatch.
Every OpenAI request also includes `reasoning.encrypted_content`. The include
list is bound by request-contract version 3 and is never silently dropped, so
persisted reasoning output can carry its portable encrypted representation.
Claude may first remove oldest complete local tool-use/result pairs while
preserving the task and newest complete pair, including images. A fixed notice
marks the omission. Mandatory overflow still fails before SDK I/O, and OpenAI
never silently breaks its remote `previous_response_id` chain.
Both adapters expose an explicit provider-neutral continuation strategy.
OpenAI read-only recovery can explicitly stage one stateless replay request
from the digest-bound continuation envelope. The compiler requires the exact
initial input, every ordered provider output batch, and one matching persisted
tool result for every historical function call. Historical calls remain input
records and never enter policy, approval, recovery planning, or MCP dispatch;
see [Stateless replay](STATELESS_REPLAY.md).

The OpenAI adapter uses Responses API function tools with
`parallel_tool_calls=false` and `include=["reasoning.encrypted_content"]`. It
preserves the provider `call_id` in the
canonical identity and returns a matching `function_call_output` with
`previous_response_id`. Text results remain JSON strings; screenshot results
use a status `input_text` block plus one base64 data-URL `input_image` block.
Provider, protocol, and policy failures use fixed error codes rather than
echoing task, UI, or API error text. In approved mode it advertises only
reviewed action tools whose required safety baselines are satisfied. The closed
model-driven Demo profile may receive the baseline-dependent tools that Runner
already retained after MCP discovery; its separate Host guard then restricts
fixture identity, semantic refs, keys, typed payload, call count, and
completion. A model-generated unadvertised tool fails closed. See
[Model-driven Demo](MODEL_DRIVEN_DEMO.md).

The Claude adapter uses Messages API client tools and preserves each assistant
`tool_use` block in its in-memory message history. Signed `thinking` and opaque
`redacted_thinking` blocks are strictly validated, excluded from canonical
model text and redacted trace, and retained unmodified only inside that private
history so the matching tool-result continuation can replay the complete
assistant block. The next user message begins with the matching `tool_result`
block keyed by the original `tool_use.id`.
Screenshot results contain a status text block and one nested base64 PNG image
block.
Parallel tool use is disabled in the request and any returned calls are still
serialized by the common Runner. Malformed reasoning blocks, unknown blocks,
mismatched stop reasons, unadvertised tools, and malformed inputs fail closed.
Context packing drops only complete assistant/tool-result groups, including
their reasoning blocks. Provider message history is an active-run optimization,
not persisted recovery state.

Install and run the experimental slice with:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -e ".[agent-openai]"
$env:OPENAI_API_KEY = "..."
.\.venv\Scripts\guarded-desktop-agent.exe config validate --config agent.toml
.\.venv\Scripts\guarded-desktop-agent.exe run --config agent.toml --task "List the open windows"
~~~

For Claude, install `.[agent-anthropic]`, set `ANTHROPIC_API_KEY`, and use
`provider.name="anthropic"` plus an explicit Claude model ID. Install `.[agent]`
when both optional provider SDKs are needed.

The task and returned desktop text are disclosed to the configured OpenAI
model. The API key is read by the provider SDK from the host environment and is
not passed to the MCP child. Use a non-sensitive desktop and narrow MCP
allowlist. Approved actions remain experimental and require an interactive
console; see [Approved actions](APPROVALS.md). `type` remains disabled for the
ordinary provider path. The separate bounded Demo profile permits only its
model-authored, source/title/URL/length-validated disposable brief after fresh
public-source and Word grounding under the selected project permission mode.

Opt-in E3 tests exercise both adapters against the harmless stdio fixture
rather than the real desktop. See [Evaluation](EVALUATION.md) for their three
environment gates, explicit model selection, bounds, and invocation.

`RunLock` holds a non-blocking OS file lock for the full lease at the canonical
user-local application root, so different configured state subdirectories
still serialize access to the same desktop. Concurrent and unknown/stale owner
records fail closed and are never reclaimed automatically. Clean release
verifies the owner token and writes a persistent `released` marker; it never
deletes a pathname after a separate token check. Active content contains only
PID, timestamp, and token.

The exclusion guarantee is reviewed for the Windows target. The POSIX fallback
uses advisory `flock` for offline development and is not a supported desktop
safety boundary. `PreparedRun` must be used as a context manager or closed
explicitly; abandoned/crashed leases intentionally fail closed until operator
recovery rather than relying on a garbage-collection finalizer.

## Phase-3 desktop MCP bridge behavior

`src/computer_use_agent/desktop_mcp.py` implements `DesktopMCPPort` over one
fixed local stdio child. It starts the configured absolute executable and argv
without a shell, initializes an MCP client session, follows bounded discovery
pagination, and requires the discovered names and input schemas to equal the
reviewed thirteen-tool registry before any call can be dispatched.

One asyncio task owns each live child generation and all calls are serialized.
A call must be host-authorized and structurally valid. Unknown tools, bad
arguments, calls before successful discovery, calls after close, discovery
drift, and startup timeouts return or raise reviewed fail-closed outcomes before
dispatch. If a timeout, EOF, transport exception, or cancellation occurs after
entering the SDK's `call_tool`, the result is `unknown_outcome`; that generation
is closed and the call is never replayed. Restart is explicit through a new
successful discovery and increments the bridge generation.

Text tools accept exactly one bounded text block. The SDK's generated
`structuredContent={"result": text}` mirror is accepted only when it exactly
matches that block; it cannot add authority or content. Action success and
known server failures are classified from fixed strings and codes, while type
results retain no text. Screenshots accept exactly one strict base64
`image/png`, capped at 32 MiB decoded, 16,384 pixels per dimension, and 64
million pixels; Pillow verifies the full PNG before dimensions are recorded.
Malformed post-dispatch side-effect results remain `unknown_outcome`.

The process-level bridge test uses a harmless MCP fixture that imports no
desktop server or driver. It verifies exact schema discovery, paths and argv
containing spaces/Unicode, reviewed environment controls, and exclusion of
OpenAI, Anthropic, AWS, and unrelated secret variables.
Child stderr is discarded rather than copied into host output or future traces;
failures surface only as reviewed bridge codes.

## Canonical host types and ports

`src/computer_use_agent/types.py` is the executable projection of this
contract. It contains no provider SDK, desktop library, or MCP-server import.

| Type | Contract |
| --- | --- |
| `CallIdentity` | A run-, turn-, and provider-call-qualified key. Every result, ledger entry, and approval uses it, preventing cross-turn correlation or replay ambiguity. |
| `ModelTurn` | Run/turn IDs, provider response ID, text, normalized requested `ToolCall` values, and usage. Provider-returned calls cannot claim host-only authorization/dispatch states. |
| `ToolCall` | Reviewed tool name, deeply immutable JSON arguments, host lifecycle status, and a stable digest that excludes mutable lifecycle state. |
| `ToolResult` | Semantic desktop outcome (`success`, action error, transport error, rejected, or unknown) plus dispatch certainty, error code where relevant, sanitized text, and reviewed image content. |
| `RunBudget` | Host-owned hard limits for model turns, tool calls, and side effects. |
| `SafeArgumentSummary` | Non-reversible metadata for sensitive arguments. For typed text it retains length/presence only, never its value. |
| `LedgerEvent` | Canonical replay-log event with typed call/result/decision correlation. Tool-call events require a `SafeArgumentSummary`; the ledger is the recovery source of truth, not a provider conversation ID. |
| `RunState` | Task, policy version, observation epoch, budgets, event ledger, verified observation epoch, and recovery state. |
| `PolicyDecision` / `ApprovalRequest` | Auditable local-human approval boundary bound to host request ID, `CallIdentity`, and call digest. Approval exposes no raw `ToolCall`. |
| `MCPToolDescriptor` | Normalized local-child discovery name and input schema used for exact startup verification. |
| `TaskPlan` / `PlanStep` | Immutable, digest-bound, non-executable planning data. Provider candidates cannot supply IDs, statuses, effects, approval flags, or dispatch authority. |
| `PreparedPlanToolCall` | Pure preflight output binding one exact pending plan snapshot to a fresh `requested` call. It is not authorized and cannot be dispatched without every ordinary host boundary. |

The ports are deliberately narrow:

- `ModelProviderPort` turns the canonical ledger plus reviewed tools into a
  `ModelTurn`. OpenAI and Claude adapters compile the same registry but do not
  own policy.
- `PlannerPort` receives one bounded immutable planning request and returns only
  untrusted JSON candidate text. It has no continuation, policy, approval, MCP,
  persistence, or execution method, and the host never retries it automatically.
- `DesktopMCPPort` discovers child `MCPToolDescriptor` values, dispatches a
  normalized `ToolCall`, converts it to a `ToolResult`, and closes the child.
  It is the only host port that can reach a desktop.
- `ApprovalPort` receives an `ApprovalRequest` and returns an explicit
  `PolicyDecision`. A model provider is never an approval authority.

Provider response identifiers are cache/retry optimizations only. A recovered
run must remain understandable from the canonical ledger.

## Reviewed tool registry

`src/computer_use_agent/tool_registry.py` contains the entire allowed surface.
At MCP-child startup, discovery must equal this exact set: no missing,
additional, duplicate, or schema-modified tools. Future provider adapters
compile only the strict host schemas; dynamic tool discovery never expands
authority.

| Tool | Effect | Input contract | Result kind | Host policy metadata |
| --- | --- | --- | --- | --- |
| `ui_snapshot` | observation | optional non-empty `scope` | text | establishes an observation epoch |
| `find` | observation | non-empty `query`, optional non-empty `scope` | text | establishes an observation epoch |
| `list_windows` | observation | none | text | establishes current window IDs |
| `screenshot` | observation | none | image | sensitive output with configured title-based redaction; establishes screenshot geometry |
| `capture_region` | observation | integer `x`, `y`, `w`, `h` | text and image | sensitive output with configured title-based redaction inside the crop; the envelope declares the crop origin and does not establish click grounding |
| `activate_window` | side effect | non-empty `window_id` | text | approval; ID must come from current `list_windows` result |
| `click` | side effect | exactly `ref` **or** integer `x` and `y` | text | approval; ref or screenshot grounding required |
| `type` | side effect | `text`, optional non-empty `ref` | text | approval; `text` is sensitive and must never be logged raw |
| `key` | side effect | non-empty `combo` | text | approval; fresh observation required |

Every host/provider JSON Schema has `additionalProperties: false`. The local
MCP discovery schemas are separately pinned to the currently implemented
server, including its generated titles/defaults; a schema drift fails closed.
The host's `click` contract intentionally narrows the current Python function
signature:
it rejects an empty call, partial coordinates, nullable arguments, and a ref
combined with coordinates. The current server accepts a broader signature and
prefers a ref when both forms are present; the host must fail closed instead.

Structural validation happens before dispatch. Later workflow policy must also
enforce dynamic grounding:

- a ref belongs to the live MCP child and a current observation epoch;
- a window ID appears in the current `list_windows` result;
- coordinates fall inside the most recent screenshot's validated primary-display
  dimensions; and
- any state-changing call invalidates grounding, requiring a new observation
  before another action.

The bridge must distinguish a successful MCP transport from a successful
desktop action. `ToolResult` records both semantic outcome and dispatch
certainty: a failure before dispatch is a transport error, while any failure
after an uncertain dispatch is `unknown_outcome` and cannot be replayed.
`RunState` rejects a `ready` recovery status whenever its ledger contains an
unknown outcome. Error codes are a fixed non-sensitive allowlist rather than
free-form server text.
Current server action results are text, so result conversion must classify known
error text explicitly rather than treating any returned content as success.

Only `screenshot` and `capture_region` may return image content. Every image
must be one bounded `image/png` with parsed positive dimensions; all other tools
reject image content. A `screenshot` result is exactly one image, while a
`capture_region` result is one grounding envelope optionally followed by one
crop, so a refused region carries no pixels. Both are marked sensitive and their
only currently reviewed redaction guarantee is configured title matching, not
general secret detection.
After conversion, `type` results must also carry no text content; success and
failure are represented by status/code and safe metadata rather than a server
message that could echo the typed value.

## Trust boundaries and non-negotiable rules

| Boundary | Trusted authority | Untrusted input | Required behavior |
| --- | --- | --- | --- |
| User/operator -> host | local operator and host policy | task text and approval context | Task text cannot change policy. Actions start disabled in `read_only` mode. |
| Provider -> host | host policy and reviewed registry | model text, tool calls, response IDs | Validate schemas, serialize calls, apply budgets, and never grant approval from model text. |
| Desktop/UI -> host | host policy only | UI text, window titles, refs, screenshots, tool output | Treat as untrusted data; never execute instructions embedded in it or promote it to memory automatically. |
| Host -> MCP child | current MCP server safety controls | child output and discovery metadata | Start a fixed executable/argv/cwd without a shell; fail closed on discovery or schema mismatch. |
| MCP action guard -> desktop driver | MCP guard policy and fresh local observations | approval timing, human-idle state, foreground state | Within one action call, require the configured stable-idle streak and initial foreground gate, then immediately before at most one driver invocation re-check e-stop and take one non-waiting foreground observation. Every guard rejection is known `not_dispatched` and is never replayed. |
| Host state -> disk | explicit local persistence rules | all candidate memory and trace content | Keep state under a user-local directory; redact traces and store memory only after explicit confirmation. |

Provider credentials are read by their future adapter from the host process
environment. They are not a configuration field and are never placed in the
MCP child environment. `MCPLaunchConfig.child_environment()` creates a fixed
safe baseline (`safe_local`, enabled confirmation, at least 2.5 seconds of
human-idle yielding, and a non-empty e-stop) plus only a small reviewed set of
server settings. Those reviewed settings include bounded stable-sample count,
poll interval, and maximum wait for the call-scoped human-readiness guard. The
MCP SDK separately adds its fixed OS bootstrap allowlist (such as `SYSTEMROOT`,
`PATH`, and `TEMP`); arbitrary variables and provider or cloud credentials are
not inherited.

The Host policy has three project-wide modes:

- `read_only` is the default and denies all four state-changing tools.
- `approved_actions` remains opt-in and still requires an explicit local host
  approval for every action in the MVP.
- `agentic_actions` is an explicit two-field opt-in that permits reviewed,
  grounded, in-budget actions without per-action approval. It does not weaken
  MCP safe-local allowlisting, human-activity yielding, confirmation, E-stop,
  audit, post-action observation, or unknown-outcome no-replay rules.

No policy or configuration setting may downgrade the MCP server to evade its
safety mechanisms. A timeout, crash, or provider error after dispatch is an
`unknown_outcome`; a host must not replay the action automatically.

### Planned enterprise authority boundary

The current Host authorizes reviewed GUI calls; it does not yet authorize
business operations. An enterprise extension must represent an immutable
authority envelope containing user, tenant, role, application, stable business
object, permitted fields and transitions, data classification, purpose,
recipient scope, quantitative limits, expiration, and policy digest.

The execution boundary must prove both layers before dispatch:

1. the GUI action is structurally valid, freshly grounded, and allowed by the
   existing Host and MCP safety controls;
2. the intended business transition is within the current authority envelope
   and still matches the re-observed object version and tenant.

Visible access, SSO state, provider output, task text, retrieved documents, and
instructions rendered inside an application are never authority. Enterprise
identity providers and human approvers remain separate trusted decision points.
Maker-checker separation, field-level restrictions, external-recipient checks,
and financial thresholds cannot be reduced to approval of a click coordinate.

Enterprise traces should retain fixed identities, policy and authority digests,
transition codes, versions, timestamps, and redacted evidence references. Raw
customer, employee, authentication, financial, message, attachment, screenshot,
or model content belongs only in an explicitly classified private artifact with
tenant isolation and retention controls.

## Sensitive data and Phase 1 baseline

Typed text is sensitive regardless of its length. The contract marks the
`type.text` argument as sensitive. `ApprovalRequest` carries a digest,
identity, and `SafeArgumentSummary` rather than a raw call; a typed-text
summary is structurally required to contain `text_length` and omit `text`.
Its only allowed metadata fields are text presence/length and ref presence.
Tool-call ledger events enforce the same redacted summary shape and permit no
arbitrary payload for typed-text calls. `type` results likewise forbid text and
free-form codes.

The current server now enforces this at the `AuditLog.record()` boundary. Type
arguments are rebuilt as an allowlisted summary (`text_present`, `text_length`,
`ref_supplied`, plus a controlled mode), type decisions are normalized, and
type results become length-only metadata. Regression coverage includes success,
human-active, gate-denied, e-stop, full-control e-stop, and a driver error that
echoes the original typed value.

The registry encodes this as the required `typed_text_audit_redaction` safety
baseline. A later runner must enable `type` only when it has verified a server
revision that provides this behavior; documentation alone is not authorization.

Screenshots, UI text, titles, and refs are also sensitive/untrusted. Screenshot
redaction in the current server is title-based only; it must not be described
as general secret detection.

## Configuration model

`agent.example.toml` documents the Phase-0 TOML shape, implemented by
`src/computer_use_agent/config.py`:

| Section | Purpose | Fail-closed rule |
| --- | --- | --- |
| `[agent]` | absolute user-local `state_dir`, policy version | The directory must be inside the platform user-local `computer-use-agent` application root. Trace and memory locations are separate beneath it. |
| `[provider]` | provider name (`openai` or `anthropic`), model ID, bounded `max_request_bytes`, reviewed model context window, output reserve, and 1-600 second request timeout | Token-window values are required and must be valid for the exact model; a timed-out turn stops as `PROVIDER_TIMEOUT`; API keys are rejected because they do not belong in config. |
| `[mcp]` | fixed absolute executable, argv, cwd, reviewed child controls | No shell, no relative executable/cwd, and no arbitrary environment variables. Only the SDK OS bootstrap allowlist plus reviewed `CUMCP_*` names reach the child; unsafe mode, disabled confirmation/e-stop, too-short human idle, out-of-range stable-sample/poll/wait values, audit redirection, and custom redaction controls are rejected. |
| `[policy]` | read-only/approved-actions/agentic-actions choice and fixed budgets | `approved_actions` requires per-action approval; `agentic_actions` requires `require_approval_for_actions = false`. |

Configuration parsing has no side effects: it does not create state directories,
start a provider, start an MCP child, or interact with a desktop.

## Current acceptance matrix

The executable contract tests are in `tests/agent/`; broader evaluation
sequencing is in [Evaluation](EVALUATION.md).

| Acceptance case | Evidence required | Status |
| --- | --- | --- |
| Same contract supports both providers | Provider-neutral `ModelTurn`, `ToolCall`, and `ToolResult` ports have no SDK imports | implemented contract |
| Exactly thirteen reviewed tools | Registry rejects discovery name, duplicate, and exact-schema mismatch | implemented contract test |
| Invalid tool arguments fail before dispatch | Unknown fields, missing fields, bad scalar types, and all invalid `click` combinations are rejected | implemented contract test |
| Host is stricter than server | All action specs require approval and invalidate grounding; `click` XOR is tested | implemented contract test |
| Configuration cannot weaken or leak into MCP | Parser allowlists child variable names, pins a safe baseline, rejects unsafe server controls, and confines state to the user-local app root | implemented contract test |
| Approval and ledger cannot replay or retain typed text | Run/turn-qualified call identity, request/digest binding, deep immutability, and redacted typed-text summaries are tested | implemented contract test |
| Result and recovery content is bounded and typed | Screenshot-only PNG output has parsed dimensions; text tools reject images; type results use only reviewed codes; action and transport failures differ; unknown outcomes cannot be `ready` | implemented contract test |
| Default host mode is read-only | Default `PolicyConfig` denies action mode selection by omission | implemented contract test |
| Agentic Host mode preserves action guards | `agentic_actions` skips per-action approval but still enforces safety baselines, grounding, budgets, sole dispatch, and mandatory verification | implemented contract tests |
| Optional runtime dependency | Contract and CLI imports need no provider SDK; OpenAI is imported only by a live run | implemented contract test |
| CLI offline commands | Help/config validation need no key or state write; dry-run emits safe metadata only | implemented foundation test |
| Runner preparation is inert | Preparing state calls no provider, MCP, or approval fake | implemented foundation test |
| One local run owns the desktop application root | OS-held lock spans state subdirectories, rejects concurrent/unknown owners, and verifies its token before writing a released marker | implemented foundation test |
| Desktop child authority is fixed | Real stdio fixture starts an absolute executable/argv/cwd without a shell, excludes provider/cloud secrets, and must exactly match all eight schemas | implemented bridge test |
| Invalid bridge calls never dispatch | Requested/non-authorized status, unknown tools, and malformed arguments return reviewed rejections with zero session calls | implemented bridge test |
| MCP failure certainty is preserved | Startup timeout is not-dispatched; timeout, EOF, exception, or cancellation after `call_tool` entry is unknown and invalidates the generation without replay | implemented bridge test |
| Child restart is explicit | A broken generation rejects further calls until full discovery succeeds on a new incremented generation | implemented bridge test |
| MCP results are bounded and converted | Text size, fixed action error codes, typed-text erasure, exact structured mirrors, full PNG integrity, dimensions, pixels, MIME, and content cardinality are tested | implemented bridge test |
| OpenAI call/result correlation | Fixture proves function call normalization and matching `function_call_output` continuation with the original call ID | implemented adapter test |
| Claude call/result correlation | Fixture proves `tool_use` normalization, adjacent matching `tool_result`, strict signed/opaque reasoning-block preservation, atomic message-history packing, and stop-reason validation | implemented adapter test |
| Screenshot provider continuation | Both adapters advertise the reviewed screenshot tool; adapter fixtures plus full common-Runner tests prove exact bounded PNG wire blocks without retaining images in trace output | implemented workflow test |
| Read-only workflow is bounded | Fake provider/desktop tests prove observe-continue-answer, exact ledger order, budget stop, identity mismatch, cleanup, and zero action dispatch | implemented workflow test |
| Offline E1/E2 gate is reproducible | Thirteen versioned cases plus a canonical manifest freeze semantic traces for success, model/token budgets, identity mismatch, unknown tools, denied/injected actions, human/gate/e-stop/driver results, mandatory re-observation, and post-dispatch unknown outcome; all require zero safety escapes | implemented evaluation suite |
| Run records are safe and conservative | Atomic checkpoints, append-only bounded JSONL, legal phase transitions, typed-text redaction, strict reading, success-after-close, and no automatic resume/replay are tested | implemented trace baseline |
| Run metrics are inspectable | Checkpoints aggregate model/tool calls, tokens, provider/tool/run latency, failures, images, and zero automatic retries without retaining sensitive content or estimating unversioned cost | implemented metrics test |
| Cross-run reports are bounded | `agent report` reads only strict atomic checkpoints and aggregates phase, success, fixed failure codes, metric coverage, totals, and averages; corrupt or path-unsafe records fail the whole report | implemented report test |
| Context and memory are bounded and explicit | Provider-only reduction preserves mandatory atomic groups; SQLite add/list/expiry/delete requires user confirmation and rejects reviewed secret/UI/image patterns | implemented management baseline |
| Provider requests have a byte gate | Both adapters count canonical UTF-8 JSON for the final SDK kwargs and reject oversized initial, memory/image/tool continuation, or Claude-history requests before network I/O | implemented request-budget test |
| Provider requests have a token-window gate | Both adapters conservatively bound the complete final request plus output reserve before SDK I/O; OpenAI also carries forward reported remote-context usage across live and persisted recovery, and no atomic tool/result/image group is split | implemented provider token-window and recovery-state tests |
| OpenAI stateless replay is explicitly gated | `recover --stateless-replay` compiles only a complete digest-bound read-only transcript, rejects unknown/missing/reordered/mismatched or over-budget state before provider dispatch, and commits a new remote response ID only after a valid response | implemented explicit recovery capability; no automatic fallback |
| OpenAI stateless replay evaluation is frozen | A canonical nine-case fixture and SHA-256 manifest freeze exact text/screenshot input order, rejected transcript classes, provider-call counts, remote-chain preservation, and zero historical MCP dispatch through the recovery executor | implemented E2 replay matrix |
| OpenAI stateless replay release evidence is explicit | Release preflight and each CI Python job run the replay module as a separate fail-closed gate; preflight v5 records its case/test counts plus canonical fixture and manifest SHA-256 values | implemented offline release gate |
| Crash reconstruction release evidence is explicit | Release preflight and each CI Python job run the classifier plus 15-case exact-call runtime matrix as a separate fail-closed gate; preflight v5 records case/test counts plus canonical fixture and manifest SHA-256 values | implemented offline release gate |
| Completed final recovery is local-only | A correlated provider completion with no tool calls advances the checkpoint to `SUCCESS` and removes its continuation under the run lock with zero provider/MCP calls; hidden call output, drift, and sequence mismatch fail closed | implemented terminal recovery boundary |
| Recovered action requests terminate without dispatch | One or more correlated action calls from a completed recovery provider turn advance the checkpoint to fixed `FAILED/RECOVERED_ACTION_REQUESTED`, remove the continuation, and cause a nonzero CLI exit with zero policy/approval/MCP calls | implemented blocked terminal boundary |
| Claude history is packed atomically | Over-window local history drops only oldest complete tool-use/result pairs, retains the task and latest image-capable pair, adds a trusted omission notice, and commits history only after a valid response | implemented packing and mandatory-overflow tests |
| Memory disclosure is per-run opt-in | Exact-scope active records are revalidated, capped at 8/8192 characters, sent as non-authoritative JSON data on the initial provider turn, and excluded from ledger/trace/checkpoint output | implemented retrieval test |
| Task planning is declarative and bounded | Strict JSON candidates are byte/step bounded, scoped to reviewed tools, schema checked, stripped of sensitive-tool support, host-ID/digest bound, and limited to pure ordered transitions with zero external calls | implemented non-executable contract test |
| Task plans persist without becoming authority | Private snapshots are strict/size bounded, task-text free, registry/plan/envelope digest bound, path safe, owner-only where supported, atomically replaced under the application RunLock, and reject stale sequence or plan-digest writes without changing disk state | implemented non-executable persistence test |
| Planner output remains untrusted data | The one-shot port receives only a bounded task and the four fixed observation schemas; fixed failures, invalid/out-of-scope/authority-bearing/oversized/non-UTF-8 candidates, and provider errors stop after one call with no retry or fallback. The isolated OpenAI and Claude adapters use one tool-free stateless Structured Outputs request each with complete byte/token preflight and strict refusal/output-shape handling. The CLI composition accepts only one to four observations before opening MCP | implemented provider-neutral port, offline fake-client dual-provider adapter tests, bounded CLI composition, and [retained dual-provider E3 evidence](E3_EVIDENCE.md) for one reviewed model per provider; the Agent Host E4 record is not a separate Planner desktop pass |
| Executor preflight cannot grant authority | Exact snapshot sequence/plan digest plus current run/task/registry bindings are revalidated; only the first pending tool step can become a fresh `requested` call, while reused identities, started/terminal/final steps, and drift fail closed. The compiler has no ports and neither mutates plan/budget state nor authorizes or dispatches | implemented pure local contract tests; runtime not connected |
| Executor session remains bounded data coordination | One live PlanStore lock scopes at most four host-identified observation requests with one outstanding call. State must retain the prior ledger exactly, and progress requires correlated call/result evidence plus exact completed/failed transitions; unknown outcomes retain `in_progress` and close. No provider, approval, recovery, trace, MCP, or desktop port is present | implemented non-executing lock/session contract; runtime not connected |
| Runner call authority has one boundary | Provider workflow, campaign runtime, and observation-plan CLI delegate normalized requests to the sole Runner MCP dispatch site, which retains policy, grounding, budgets, approval, WAL, result validation, and verification. Structural tests freeze the single-site invariant and forbid direct composition/runtime dispatch sites | implemented shared host boundary and offline CLI composition |
| Plan runtime executes observations through the same boundary | WAL is mandatory; a fresh plan step is CAS-marked `in_progress` before dispatch intent, then sent only through the shared Runner boundary. Success/known failure commit exact transitions; uncertainty keeps `in_progress`, preserves WAL, closes, and produces one call with zero replay. Side effects and CLI paths remain absent | implemented internal fake-MCP observation runtime; broader Executor unavailable |
| Completed observation reconciliation is local-only | A revalidated completed WAL must exactly match the current `in_progress` observation step, snapshot, task, registry, identity, arguments, call digest, and known result. Only the missed terminal plan CAS is applied; WAL remains and provider/MCP/approval paths stay absent. Dispatch intent and unknown outcomes never reconcile | implemented explicit local repair; execution resume remains unavailable |
| Final-response input is tool-free and non-executable | One to four completed plan observations must exactly match a successful canonical ledger and verified recovery/budget state. The compiler emits a bounded digest-bound task plus lossless observation data, never executable historical calls; compilation itself grants no authority | implemented pure request contract consumed only by the internal final runtime and isolated adapters |
| Final-response adapters are isolated and stateless | Shared canonical wire data binds text plus ordered native PNGs. OpenAI and Claude each make one no-tool request with byte/token preflight, fixed failure codes, no retry/fallback/continuation, and strict bounded single-text output | implemented offline fake-client adapters and bounded CLI selection; no retained real-provider evidence |
| Final-response runtime ordering is fail-closed | Under one RunLock, exact compile and prepared WAL precede final-step `in_progress`; durable intent precedes the single provider call; correlated completion precedes host budget/ledger consumption, final CAS, terminal trace, and ordinary-WAL cleanup. Intent-or-later failure preserves evidence, closes, and never retries or reaches MCP/recovery | implemented offline injected-port runtime and CLI composition tests |
| Completed final-response reconciliation is local-only | Version 2 WAL binds the source plan/checkpoint/continuation and provider latency. A pure compiler revalidates exact completed evidence and reconstructs the original request and canonical terminal state. A separate same-lock writer rereads those pins, idempotently CAS-completes the final plan step, writes or reuses one terminal event and `SUCCESS` checkpoint, retains final WAL, and deletes only the ordinary continuation. Prepared/intent state, drift, malformed evidence, and commit failure fail closed without provider/MCP/approval/recovery paths | implemented offline preflight, application, retry, no-mutation, and real runtime-failure artifact tests; no automatic CLI recovery |
| Host completion projection is evidence-only | The internal read-only projection validates durable campaign control state under the run lock; running continues, waiting/stale/malformed states request attention, uncertainty forbids replay, and only digest-identified validated terminal state can complete once across host restart | implemented and offline fake-host verified; the public status tool, notification bridge, mobile adapter, and general worker remain unimplemented |

The remaining work connects a bounded Executor through the existing host boundaries, adds broader post-provider resumable state, semantic
context compression, broader isolated regression, and release review. The current
slice is experimental and must not be presented as the complete safety MVP.
