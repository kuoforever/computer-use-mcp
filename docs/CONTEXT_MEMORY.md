# Agent context reduction and explicit memory

> **Status: implemented management baseline.** Provider-facing context is
> bounded by canonical event count, and users can explicitly add, list, expire,
> and delete local SQLite memories. Memory is not automatically extracted from
> tasks, providers, traces, or the desktop and is not yet injected into runs.

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

This is a bound on the host-supplied canonical ledger view, not a
tokenizer-specific end-to-end provider context limit. OpenAI's active
`previous_response_id` chain and Claude's active message history still preserve
the current run's provider-native continuation state. Provider-neutral
stateless replay, safe summarization, and actual token-window enforcement remain
future work; model-turn limits continue to bound the current run.

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

Memory currently has no authority over policy, approval, grounding, tool
selection, or execution. Records are not automatically included in provider
prompts; this keeps the initial persistence boundary testable before retrieval
and prompt-injection defenses are designed.
