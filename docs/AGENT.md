# Agent Host contract and safety boundary

> **Status: Phase 2 foundation.** The provider-neutral contract, safety
> baseline, CLI skeleton, injected runner ports, deterministic fakes, and local
> run lock are implemented. Provider calls and MCP desktop execution are not.

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

## Phase-2 foundation behavior

The `computer-use-agent` entry point and `python -m computer_use_agent` expose
only safe foundation commands:

- `config validate --config PATH` parses and validates TOML without creating
  state directories, reading provider credentials, or starting another process.
- `run --config PATH --task TEXT --dry-run` acquires the local run lock, creates
  a bounded initial `RunState`, prints task length and other safe metadata, and
  releases the lock. It calls no provider, MCP, approval, or desktop port.
- `run` without `--dry-run` fails closed before reading configuration or
  acquiring a lock because provider and desktop bridge phases are not present.

`AgentRunner` accepts the three external ports through `RunnerPorts`; Phase 2
retains but never invokes them. Its first ledger event contains only task
length, while raw task text remains in the in-memory `RunState`. The host policy
allows observation tools in read-only mode, denies side effects, and continues
to deny tools with an unverified required safety baseline.

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
server settings; it never inherits host variables.

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
| `[mcp]` | fixed absolute executable, argv, cwd, reviewed child controls | No shell, no relative executable/cwd, no inherited environment, and no arbitrary variables. Only reviewed `CUMCP_*` names are accepted; unsafe mode, disabled confirmation/e-stop, too-short human idle, audit redirection, and custom redaction controls are rejected. |
| `[policy]` | read-only/approved-actions choice and fixed budgets | `approved_actions` cannot disable per-action approval. |

Configuration parsing has no side effects: it does not create state directories,
start a provider, start an MCP child, or interact with a desktop.

## Phase 0-2 acceptance matrix

The executable contract tests are in `tests/agent/`; broader evaluation
sequencing is in [Evaluation](EVALUATION.md).

| Acceptance case | Evidence required | Phase-0 status |
| --- | --- | --- |
| Same contract supports both providers | Provider-neutral `ModelTurn`, `ToolCall`, and `ToolResult` ports have no SDK imports | implemented contract |
| Exactly eight reviewed tools | Registry rejects discovery name, duplicate, and exact-schema mismatch | implemented contract test |
| Invalid tool arguments fail before dispatch | Unknown fields, missing fields, bad scalar types, and all invalid `click` combinations are rejected | implemented contract test |
| Host is stricter than server | All action specs require approval and invalidate grounding; `click` XOR is tested | implemented contract test |
| Configuration cannot weaken or leak into MCP | Parser allowlists child variable names, pins a safe baseline, rejects unsafe server controls, and confines state to the user-local app root | implemented contract test |
| Approval and ledger cannot replay or retain typed text | Run/turn-qualified call identity, request/digest binding, deep immutability, and redacted typed-text summaries are tested | implemented contract test |
| Result and recovery content is bounded and typed | Screenshot-only PNG output has parsed dimensions; text tools reject images; type results use only reviewed codes; action and transport failures differ; unknown outcomes cannot be `ready` | implemented contract test |
| Default host mode is read-only | Default `PolicyConfig` denies action mode selection by omission | implemented contract test |
| No runtime capability introduced | Contract package imports without provider SDK, MCP child, or desktop | implemented contract test |
| CLI foundation is offline | Help/config validation need no key or state write; non-dry run fails closed; dry-run emits safe metadata only | implemented foundation test |
| Runner ports are inert in Phase 2 | Preparing state calls no provider, MCP, or approval fake | implemented foundation test |
| One local run owns the desktop application root | OS-held lock spans state subdirectories, rejects concurrent/unknown owners, and verifies its token before writing a released marker | implemented foundation test |

The remaining phases add stdio lifecycle, provider adapters, the actual bounded
workflow, memory, traces, offline workflow evaluations, isolated desktop smoke
tests, and release review. Until then, this foundation must not be presented as
a usable desktop Agent Host.
