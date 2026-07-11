# Agent Host contract and safety boundary

> **Status: experimental read-only vertical slice.** The provider-neutral
> contract, local stdio bridge, bounded runner, and OpenAI Responses adapter are
> implemented. The CLI can inspect desktop text through three observation
> tools. Screenshot return, Claude, actions/approvals, persistence, trace, and
> recovery remain unavailable.

This is the canonical contract companion to the planned
[Agent implementation plan](AGENT_IMPLEMENTATION_PLAN.md). It uses the current
eight-tool local stdio MCP server as its sole desktop execution authority.

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
          -> computer-use-mcp server
              -> gate, human activity, confirmation, e-stop, audit
              -> Windows UI Automation / Win32
~~~

The host may make this boundary stricter; it cannot bypass any server-side
allowlist, human-activity check, confirmation, e-stop, or audit behavior.

## Current CLI behavior

The `computer-use-agent` entry point and `python -m computer_use_agent` expose
the following commands:

- `config validate --config PATH` parses and validates TOML without creating
  state directories, reading provider credentials, or starting another process.
- `run --config PATH --task TEXT --dry-run` acquires the local run lock, creates
  a bounded initial `RunState`, prints task length and other safe metadata, and
  releases the lock. It calls no provider, MCP, approval, or desktop port.
- `run --config PATH --task TEXT` uses the optional OpenAI adapter and local
  stdio MCP bridge to execute a bounded read-only loop. It exposes only
  `ui_snapshot`, `find`, and `list_windows` to the model. Every returned call is
  validated and host-authorized before serialized dispatch. The CLI returns
  final text, run ID, and model/tool counts as JSON.

`AgentRunner` accepts the three external ports through `RunnerPorts`. Its first ledger event contains only task
length, while raw task text remains in the in-memory `RunState`. The host policy
allows observation tools in read-only mode and denies side effects. Model-turn,
tool-call, result, and observation events are appended to the canonical ledger;
model and tool budgets are consumed before another external call can occur.
The current ledger is in-memory only and is not a resumable trace.

The OpenAI adapter uses Responses API function tools with
`parallel_tool_calls=false`. It preserves the provider `call_id` in the
canonical identity and returns a matching `function_call_output` with
`previous_response_id`. Provider, protocol, and policy failures use fixed error
codes rather than echoing task, UI, or API error text. Only text observation
tools are advertised because screenshot-to-provider continuation has not been
implemented. A model-generated action or unadvertised tool fails closed.

Install and run the experimental slice with:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -e ".[agent-openai]"
$env:OPENAI_API_KEY = "..."
.\.venv\Scripts\computer-use-agent.exe config validate --config agent.toml
.\.venv\Scripts\computer-use-agent.exe run --config agent.toml --task "List the open windows"
~~~

The task and returned desktop text are disclosed to the configured OpenAI
model. The API key is read by the provider SDK from the host environment and is
not passed to the MCP child. Use a non-sensitive desktop and narrow MCP
allowlist. `provider.name="anthropic"` and `policy.mode="approved_actions"`
currently fail closed.

An opt-in E3 test exercises the same OpenAI adapter against the harmless stdio
fixture rather than the real desktop. See [Evaluation](EVALUATION.md) for its
three environment gates, explicit model selection, bounds, and invocation.

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
reviewed eight-tool registry before any call can be dispatched.

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

The ports are deliberately narrow:

- `ModelProviderPort` turns the canonical ledger plus reviewed tools into a
  `ModelTurn`. OpenAI and Claude adapters compile the same registry but do not
  own policy.
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

Only `screenshot` may return image content. Its result must be one bounded
`image/png` with parsed positive dimensions; all other tools reject image
content. Screenshot output is marked sensitive and its only currently reviewed
redaction guarantee is configured title matching, not general secret detection.
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
| Host state -> disk | explicit local persistence rules | all candidate memory and trace content | Keep state under a user-local directory; redact traces and store memory only after explicit confirmation. |

Provider credentials are read by their future adapter from the host process
environment. They are not a configuration field and are never placed in the
MCP child environment. `MCPLaunchConfig.child_environment()` creates a fixed
safe baseline (`safe_local`, enabled confirmation, at least 2.5 seconds of
human-idle yielding, and a non-empty e-stop) plus only a small reviewed set of
server settings. The MCP SDK separately adds its fixed OS bootstrap allowlist
(such as `SYSTEMROOT`, `PATH`, and `TEMP`); arbitrary variables and provider or
cloud credentials are not inherited.

The initial host policy has two modes:

- `read_only` is the default and denies all four state-changing tools.
- `approved_actions` remains opt-in and still requires an explicit local host
  approval for every action in the MVP.

No policy or configuration setting may downgrade the MCP server to evade its
safety mechanisms. A timeout, crash, or provider error after dispatch is an
`unknown_outcome`; a host must not replay the action automatically.

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
| `[provider]` | provider name (`openai` or `anthropic`) and model ID | API keys are rejected because they do not belong in config. |
| `[mcp]` | fixed absolute executable, argv, cwd, reviewed child controls | No shell, no relative executable/cwd, and no arbitrary environment variables. Only the SDK OS bootstrap allowlist plus reviewed `CUMCP_*` names reach the child; unsafe mode, disabled confirmation/e-stop, too-short human idle, audit redirection, and custom redaction controls are rejected. |
| `[policy]` | read-only/approved-actions choice and fixed budgets | `approved_actions` cannot disable per-action approval. |

Configuration parsing has no side effects: it does not create state directories,
start a provider, start an MCP child, or interact with a desktop.

## Current acceptance matrix

The executable contract tests are in `tests/agent/`; broader evaluation
sequencing is in [Evaluation](EVALUATION.md).

| Acceptance case | Evidence required | Status |
| --- | --- | --- |
| Same contract supports both providers | Provider-neutral `ModelTurn`, `ToolCall`, and `ToolResult` ports have no SDK imports | implemented contract |
| Exactly eight reviewed tools | Registry rejects discovery name, duplicate, and exact-schema mismatch | implemented contract test |
| Invalid tool arguments fail before dispatch | Unknown fields, missing fields, bad scalar types, and all invalid `click` combinations are rejected | implemented contract test |
| Host is stricter than server | All action specs require approval and invalidate grounding; `click` XOR is tested | implemented contract test |
| Configuration cannot weaken or leak into MCP | Parser allowlists child variable names, pins a safe baseline, rejects unsafe server controls, and confines state to the user-local app root | implemented contract test |
| Approval and ledger cannot replay or retain typed text | Run/turn-qualified call identity, request/digest binding, deep immutability, and redacted typed-text summaries are tested | implemented contract test |
| Result and recovery content is bounded and typed | Screenshot-only PNG output has parsed dimensions; text tools reject images; type results use only reviewed codes; action and transport failures differ; unknown outcomes cannot be `ready` | implemented contract test |
| Default host mode is read-only | Default `PolicyConfig` denies action mode selection by omission | implemented contract test |
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
| Read-only workflow is bounded | Fake provider/desktop tests prove observe-continue-answer, exact ledger order, budget stop, identity mismatch, cleanup, and zero action dispatch | implemented workflow test |

The remaining work adds Claude, screenshots, persisted state and traces,
context reduction, memory, broader E1/E2 cases, approvals/actions, isolated
desktop smokes, and release review. The current slice is experimental and
read-only; it must not be presented as the complete safety MVP.
