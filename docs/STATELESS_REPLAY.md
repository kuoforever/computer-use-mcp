# OpenAI stateless replay readiness

> **Status: design and fail-closed readiness gate implemented; replay is not
> implemented.** The runtime continues only through `previous_response_id` and
> never silently falls back to a new stateless request.

## Why this is a separate capability

The OpenAI Responses API supports provider-managed continuation through
`previous_response_id`. It also documents manual conversation management by
passing prior response output items back in the next request. Function-calling
examples preserve `response.output` and then append each matching
`function_call_output` by `call_id`.

Those wire items are richer than the current canonical host ledger. The ledger
normalizes assistant text, reviewed function calls, usage, and tool results; it
does not persist the exact original request or every provider output item, such
as reasoning items. Reconstructing a plausible transcript from normalized
events would therefore be lossy and is prohibited.

Official protocol references:

- [Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)

## Executable readiness contract

`ProviderContinuationStrategy` distinguishes OpenAI's
`remote_response_id` from Claude's `local_message_history`. The OpenAI adapter
returns a `StatelessReplayReadiness` with these blockers:

| Blocker | Required evidence before removal |
| --- | --- |
| `original_request_not_persisted` | Persist the exact initial input, including whether explicit memory was disclosed, without turning it into policy or approval. |
| `provider_output_items_not_persisted` | Preserve every required Responses API output item in exact order, not only normalized text/function calls. |
| `request_contract_not_digest_bound` | Bind model, instructions, tool definitions, relevant request settings, and their reviewed schema/version to the replay artifact. |
| `replay_compiler_not_implemented` | Add a separately reviewed compiler that emits one bounded request and never dispatches historical tools. |

The assessment is descriptive and non-executable. No CLI/config switch invokes
it, and an empty blocker set alone would not authorize provider or desktop I/O.

## Activation invariants

A future implementation must satisfy all of the following in one separately
reviewed milestone:

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
   limit, side-effect budget, grounding, approval, or action authority.
7. Offline fixtures freeze exact wire order for text, function calls/results,
   screenshots, missing output items, contract drift, and over-budget requests;
   every rejected case records zero provider and desktop calls.

Until those gates are implemented, OpenAI context pressure remains
fail-closed. Claude's existing atomic local-history packing is a different
provider strategy and does not establish OpenAI replay safety.
