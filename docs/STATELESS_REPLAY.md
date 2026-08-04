# OpenAI stateless replay readiness

> **Status: explicit read-only recovery replay implemented.** Normal runtime
> continues through `previous_response_id`. Replay requires the operator's
> `recover --stateless-replay` flag and is never an automatic fallback.

## Why this is a separate capability

The OpenAI Responses API supports provider-managed continuation through
`previous_response_id`. It also documents manual conversation management by
passing prior response output items back in the next request. Function-calling
examples preserve `response.output` and then append each matching
`function_call_output` by `call_id`.

Those wire items are richer than the current canonical host ledger. The ledger
normalizes assistant text, reviewed function calls, usage, and tool results; it
now persists the exact initial input and every bounded provider output item in
response order. The recovery compiler constructs one request from those exact
persisted records. Reconstructing a plausible transcript through any other
path remains prohibited.

Official protocol references:

- [Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)

## Executable contract

`ProviderContinuationStrategy` distinguishes OpenAI's normal
`remote_response_id`, its one-request `stateless_replay` transition, and
Claude's `local_message_history`. OpenAI readiness now has no blocker, but
eligibility alone performs no I/O and grants no action authority.

The initial-input, provider-output, and request-contract prerequisites are now
delivered independently of replay. Every OpenAI Responses request explicitly
includes `reasoning.encrypted_content`, so persisted reasoning items can carry
the provider's portable encrypted payload instead of depending only on remote
response storage. This setting is mandatory: the adapter does not retry without
it. Continuation v6 stores the exact initial SDK `input`
string inside the already-sensitive private artifact. This includes the task
and any explicitly selected memory data, is never copied into trace/report/error
surfaces, and is not itself executable. The contract digest binds its SHA-256
along with the model, instructions, reviewed tool definitions,
action mode, memory-disclosure marker, parallel-call setting, encrypted-reasoning
include list, request-byte gate, context window, output reserve, and request
contract version 3 under a canonical SHA-256
digest. Restore or active-chain drift fails with
`OPENAI_REQUEST_CONTRACT_MISMATCH` before provider I/O and before restored state
is attached. Each completed response also appends one bounded batch containing
the response ID and every canonical JSON `response.output` item in original
order, including reasoning items. Invalid JSON, duplicate/mismatched response
IDs, excessive item counts, and oversized accumulated batches fail before
state commit. The compiler additionally revalidates the complete envelope
digest, response-batch/model-turn order, exact call ID/name/arguments, reviewed
observation-only tool identity, and one ordered matching tool result per call.

Continuation v6 additionally binds the live Runner's exact
`advertised_tool_names`. At recovery the Host intersects that set with current
reviewed observations and current attached-desktop baseline evidence; without
a desktop, baseline-required tools are excluded, and actions are always
excluded. The resulting registry-ordered tuple is used unchanged for OpenAI
restore, this replay preflight, and the next `create_turn`, so the contract
digest and actual restricted request cannot silently use different tool
definitions. An old v5 or malformed scope artifact fails closed rather than
falling back to the full registry. Replay proceeds only if that restricted
tuple preserves the persisted adapter-visible request contract; an
action-enabled or otherwise drifted chain fails before network I/O.

The CLI invokes replay only with both `--execute-read-only` and
`--stateless-replay`, at a completed `provider_continue` boundary. Compilation
and request byte/token gates finish before the durable provider dispatch
intent. Historical calls are appended to Responses input only; the compiler
does not call host policy, approval, recovery planning, or MCP.

## Activation invariants

The implementation enforces all of the following:

1. Replay uses only a complete, validated, digest-bound transcript. Missing,
   unknown, reordered, summarized, or provider-unsupported items fail before
   SDK I/O.
2. Historical function calls are input records only. They never re-enter host
   policy, approval, recovery, or MCP dispatch paths.
3. The full compiled request passes the existing byte and conservative token
   window gates before network dispatch.
4. Switching away from `previous_response_id` is explicit and atomic. A remote
   continuation failure never triggers automatic stateless fallback.
5. The new response ID is committed only after a valid provider response. A
   failed replay preflight or request leaves the existing remote chain intact.
6. Replay cannot change the configured provider/model, tool registry, recovery
   limit, side-effect budget, grounding, approval, action authority, or the
   original Host tool scope; recovery may only narrow it to current-safe
   observations.
7. Offline fixtures freeze exact wire order for text, function calls/results,
   screenshots, missing output items, contract drift, and over-budget requests;
   every rejected case records zero provider and desktop calls.

`evals/e2-stateless-replay.json` and its SHA-256 manifest freeze nine cases,
including successful text/screenshot replay, unknown/missing/mismatched/
reordered state, side-effect history, request overflow, and provider failure.
The recovery-executor assertion proves compilation finishes before the durable
provider intent and that historical calls produce zero MCP dispatches.
Release preflight report v5 runs this module as an independent gate and records
the canonical fixture hash, manifest hash, case count, and targeted test counts.
CI repeats the gate on every supported Python version and retains JUnit output;
this remains offline evidence and does not imply E3 or E4 completion.

The switch is one-shot and atomic. Preflight failure leaves the provider in
`remote_response_id`. After staging, provider failure or invalid output leaves
the exported old response ID unchanged and never retries with either strategy.
Only a valid new response commits its ID and returns the adapter to normal
remote continuation. Claude's atomic local-history packing remains a different
provider strategy and does not use this compiler. Regardless of strategy, a
returned call outside the narrowed tuple is rejected before provider completion
or any future MCP dispatch; historical replay items remain data only.
