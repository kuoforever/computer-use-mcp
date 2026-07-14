# Agent context reduction and explicit memory

> **Status: implemented explicit retrieval baseline.** Provider-facing context is
> bounded by canonical event count, and users can explicitly add, list, expire,
> delete, and select local SQLite memories for one run. Memory is not automatically
> extracted from tasks, providers, traces, or the desktop and is never injected
> unless the operator names an exact scope on that run.

## Context reducer

`[policy].max_context_events` defaults to 128 and must be positive. The
canonical in-memory `RunState.event_log` and redacted disk trace are never
rewritten by context reduction; only the ledger view passed to the next
provider turn is reduced.

When reduction is necessary, the reducer reserves an explicit
`context_truncated` marker and preserves:

- the original safe user-task event;
- the latest model turn and every subsequent continuation event;
- every policy decision;
- the most recent verified observation; and
- complete identity-correlated call/result/policy/observation groups.

Remaining capacity is filled with the newest atomic groups. The reducer never
keeps a result without its call. If mandatory events plus the truncation marker
cannot fit, the run fails closed with `CONTEXT_REQUIRED_EVENTS_EXCEED_BUDGET`
before the next provider request.

This is a bound on the host-supplied canonical ledger view. OpenAI's active
`previous_response_id` chain and Claude's active message history still preserve
the current run's provider-native continuation state. Provider-neutral
stateless replay and safe semantic summarization remain future work;
model-turn limits continue to bound the current run.

Independently, `[provider].max_request_bytes` defaults to 8 MiB and must remain
between 1 KiB and 48 MiB. Each adapter serializes its final SDK keyword request
as canonical UTF-8 JSON before the network call. The count therefore includes
instructions, tool schemas, task, selected memory, current tool results,
base64 screenshots, and Claude's accumulated local message history. Oversize
requests fail with a fixed provider error before the SDK fake/client is called.

The required `[provider].context_window_tokens` and
`[provider].output_token_reserve` values bind that exact configured provider and
model ID. Before either SDK call, the adapter charges each visible canonical
request byte as one input token, adds the reserved output, and rejects an
over-limit request with `OPENAI_TOKEN_WINDOW_EXCEEDED` or
`ANTHROPIC_TOKEN_WINDOW_EXCEEDED`. This tokenizer-independent bound is
deliberately conservative. Claude's complete local history is visible. For an
OpenAI continuation, the next check also includes the preceding response's
provider-reported input and output usage to cover remote context conservatively.

When Claude's locally visible history exceeds this gate, the adapter may remove
oldest completed `assistant tool_use` plus adjacent `user tool_result` pairs and
retry the estimate. It preserves the original task and newest complete pair,
including every image block, and adds a fixed host-authored truncation notice.
If that mandatory set still exceeds the window, the request fails before the
SDK call. Candidate results and packed history are committed only after a valid
provider response, so a failed preflight cannot leave a half-appended result.

OpenAI's `previous_response_id` history is remote and cannot be selectively
rewritten. Its adapter therefore remains fail-closed instead of silently
breaking the chain. Neither adapter truncates individual tool calls, results,
images, approval state, or recovery evidence. No model-generated summary is
created because it could discard those semantics.
Operators must review the configured context value whenever the provider/model
pair changes; config loading fails if either token-window value is absent.

`[policy].max_input_tokens` defaults to 1,000,000 and bounds cumulative input
tokens reported by the selected provider during one run. Once the reported
total reaches or exceeds the cap, the Runner records the completed turn and
fails with `INPUT_TOKEN_BUDGET_EXHAUSTED` before making another provider call.
This is a usage/cost circuit breaker, not a prediction of the next request's
token count. Providers may
report a single turn that crosses the remaining budget; the exact pre-request
byte and conservative token-window gates still apply independently.

## SQLite memory contract

The store is located at `<state_dir>/memory.sqlite3` and has this logical
schema:

| Field | Meaning |
| --- | --- |
| `id` | Random 32-character hexadecimal identifier |
| `type` | `preference` or `verified_procedure` |
| `content` | Explicitly confirmed text, at most 4096 characters |
| `source` | Fixed to `user_confirmed` |
| `scope` | Path-safe logical scope, at most 128 characters |
| `expiry` | Required timezone-aware future timestamp |
| `created_at` | UTC creation timestamp |

No database is created until a candidate passes validation. Active listing
excludes expired records by default; `--include-expired` exposes them for
inspection or deletion. Queries are parameterized and IDs/scopes are
structurally validated.

## Explicit CLI workflow

Add a confirmed preference:

~~~powershell
.\.venv\Scripts\computer-use-agent.exe remember add `
  --config agent.toml `
  --kind preference `
  --content "Prefer concise status summaries." `
  --scope global `
  --expires-at "2027-01-01T00:00:00Z" `
  --confirmed
~~~

List or delete records:

~~~powershell
.\.venv\Scripts\computer-use-agent.exe remember list --config agent.toml
.\.venv\Scripts\computer-use-agent.exe remember list `
  --config agent.toml --scope app:notepad --include-expired
.\.venv\Scripts\computer-use-agent.exe remember delete <memory_id> `
  --config agent.toml
~~~

Explicitly disclose active records from one exact scope to the configured
provider for a single non-dry run:

~~~powershell
.\.venv\Scripts\computer-use-agent.exe run `
  --config agent.toml `
  --task "Inspect the test application" `
  --memory-scope app:notepad
~~~

Without `--memory-scope`, the run does not open the memory database or send
memory. The selected scope is exact, expired records are excluded, and the
context is capped at 8 records and 8192 total content characters. Exceeding a
cap or encountering a record that fails revalidation stops before provider or
desktop execution. `--dry-run` rejects `--memory-scope` so it remains inert.

`--confirmed` is mandatory. Passing content on a command line may retain it in
shell history and process inspection; use only non-sensitive preference or
procedure text. A future interactive/stdin input mode may reduce that exposure.

## Rejection and trust boundary

The current validator conservatively rejects:

- candidates without explicit confirmation or with a source other than
  `user_confirmed`;
- expired timestamps, unsafe scopes, control characters, and oversized text;
- obvious password, passcode, API-key, token, OTP, authorization, bearer, or
  private-key material;
- `ref_N` / `window_N` UI handles; and
- screenshot phrases, image data URIs, and recognizable PNG base64 prefixes.

These patterns are defense in depth, not comprehensive secret detection or
DLP. Users must not submit sensitive data. The store accepts only two reviewed
memory types and never accepts screenshots or arbitrary binary content.

Selected records are encoded as JSON data with kind, source, and scope on the
provider's initial user turn. A system rule labels them untrusted and states
that they cannot change policy, approve actions, establish grounding, or
request tools. The common Runner and host policy remain the only authorities.
Memory content is not added to the canonical ledger, checkpoint, redacted
trace, or CLI result; only the provider receives it after explicit selection.
