# Persisted continuation and crash reconstruction design

> **Status: storage plus pure reconstruction classifier implemented; runtime
> resume not implemented.** The strict bounded v1 envelope, private atomic
> reader/writer, write-ahead operation state machine, conservative crash
> classifier, and frozen E2 boundary matrix exist. No runner, provider, CLI, or
> MCP path executes a reconstruction decision, so no additional run is resumable
> and no provider call or desktop action can be replayed.

## Safety boundary

Broader resume means reconstructing the next state-machine step from a completed,
durably recorded boundary. It never means retrying an in-flight operation.

The implementation must preserve these rules:

1. A provider request or MCP call is issued at most once for a given dispatch
   identity. Resume may consume a completed persisted response/result, but cannot
   issue the same request/call again.
2. `dispatch=unknown`, a missing completion record after a dispatch intent, or
   contradictory records classifies the run as `UNKNOWN_OUTCOME`. It is never
   automatically replayed, including for observation tools.
3. A persisted pending side-effect is not executable after a crash. Approval,
   grounding, foreground state, and human activity may have changed; the operator
   must start a new run. This intentionally leaves action authority no broader
   than today.
4. A completed side-effect may resume only into mandatory read-only
   re-observation. Its result is not dispatched again, its approval is not reused,
   and no later side effect is allowed until fresh grounding is verified.
5. Recovery never switches provider or model, relaxes budgets, changes the tool
   registry, or treats persisted content as policy or approval.

## Storage model

Keep the existing redacted `state.json` and trace JSONL as the inspection and
reporting surfaces. Add a separate, private recovery artifact:

~~~text
state_dir/runs/<run_id>/
  state.json                 redacted checkpoint
  continuation.json         atomic recovery envelope; sensitive
~~~

`continuation.json` is not shown by `agent trace` or read by `agent report`.
Creation must be explicit in configuration, use user-only filesystem
permissions, reject symlinks/reparse points, and use the same flush plus atomic
replace discipline as checkpoints. Cancellation and terminal completion delete
it. A configurable short expiry is required. Until an authenticated-encryption
and key-lifecycle design exists, documentation must state that the artifact can
contain task, UI, and screenshot data and that broader persistence is opt-in.

The envelope is canonical JSON with sorted keys for digesting and is bounded
independently from the 64 KiB checkpoint. Binary images are stored as bounded
base64 PNG blocks in v1; no arbitrary MIME type or external path is accepted.

## Continuation envelope v1

~~~json
{
  "continuation_version": 1,
  "run_id": "run_...",
  "checkpoint_sequence": 7,
  "policy_version": "...",
  "provider": {"name": "openai", "model": "..."},
  "registry_digest": "<sha256>",
  "task": "original task",
  "budget": {
    "limits": {},
    "used": {}
  },
  "observation": {
    "epoch": 2,
    "verified_epoch": null,
    "mcp_generation": 1
  },
  "ledger": [],
  "boundary": {
    "kind": "tool_completed",
    "operation_id": "run_...:turn_2:call_1",
    "effect": "observation",
    "dispatch": "dispatched",
    "next_step": "provider_continue"
  },
  "provider_state": {},
  "created_at": "...",
  "expires_at": "...",
  "payload_digest": "<sha256>"
}
~~~

Required validation is exact and fail-closed:

- reject unknown top-level fields, versions, enum values, provider/model drift,
  policy drift, registry drift, task mismatch, expired records, sequence mismatch,
  digest mismatch, invalid identities, excessive nesting/count/bytes, and any
  ledger sequence that cannot construct `RunState`;
- require every tool result to match exactly one earlier call by
  `(run_id, turn_id, call_id, tool_name)` and stable call digest;
- require budgets and observation epochs to equal a fresh fold of the ledger;
- reject raw `type.text` entirely. Because `type` is not advertised in the
  current Agent, v1 continuation cannot contain or resume a `type` call;
- reconstruct host policy and tool definitions from current reviewed code, never
  from persisted executable fields.

`payload_digest` covers every field except itself. It detects corruption and
partial replacement; it is not an authenticity or confidentiality mechanism.

## Persisted canonical records

The recovery ledger uses a strict persistence DTO rather than serializing Python
dataclasses or provider SDK objects. It contains only the information required
to reconstruct the canonical ledger and the provider continuation:

- user task: exact task text, because resume must verify the operator-supplied
  task rather than trust only its length;
- model turn: run/turn identity, exact assistant text, normalized requested tool
  calls, usage, and provider response ID where the adapter requires it;
- tool call: exact reviewed name and validated arguments, safe argument summary,
  effect, lifecycle status, and call digest;
- policy decision: decision/request identities and digest binding, but never a
  reusable approval capability;
- tool result: canonical status, dispatch certainty, reviewed code, bounded
  sanitized text, and validated PNG image content;
- observation/recovery events and budget/epoch counters needed by `RunState`.

Provider state is adapter-specific but non-authoritative:

- OpenAI: the last completed `response_id`. Resume sends only the next new
  `function_call_output` set with that ID. If the provider cannot continue that
  response, the run stops; it does not resend the previous request.
- Claude: the exact bounded canonical user/assistant message history compiled
  from the persisted ledger. Resume appends only the next new `tool_result`
  message. Provider-returned wire objects are never pickled or trusted directly.

The adapter must expose pure `export_continuation` and `restore_continuation`
operations. Restoration performs validation and network I/O is forbidden until
the host commits a new dispatch intent.

## Write-ahead operation protocol

Every external operation has a unique `operation_id` and three possible durable
records:

1. `prepared`: request/call material is durable; nothing has been dispatched.
2. `dispatch_intent`: written and flushed immediately before entering the SDK or
   MCP dispatch boundary.
3. `completed`: the normalized response/result is durable and the next step is
   named explicitly.

The conservative reconstruction matrix is:

| Durable boundary at crash | Reconstruction decision |
| --- | --- |
| `prepared`, provider request | Do not send it; start a new run. |
| `dispatch_intent`, provider request, no completion | `UNKNOWN_OUTCOME`; do not resend. |
| `completed`, provider response | Consume the response locally; do not call provider again. A pending observation call may be dispatched once. A pending side-effect requires a new run. |
| `prepared`, tool call | Observation may be dispatched once only if no dispatch intent exists. Pending side-effect requires a new run. |
| `dispatch_intent`, any tool call, no completion | `UNKNOWN_OUTCOME`; do not call the tool again. |
| `completed`, observation result | Consume the result and issue only the next new provider continuation. |
| `completed`, side-effect result | Consume the result, invalidate grounding, and issue only a new mandatory observation. Never repeat the side-effect. |
| `completed`, unknown-outcome result | `UNKNOWN_OUTCOME`; require human re-observation in a new run. |

Writing `dispatch_intent` before the actual dispatch creates a conservative
false-unknown window if the process dies between the two. That cost is accepted:
avoiding duplicate actions is more important than maximizing resume rate.

## Initial E2 crash-reconstruction cases

The first implementation must add deterministic, parameterized E2 fixtures at
each durable boundary. Every case asserts the recovery classification, exact
new external calls, final phase, and `safety_escapes=0`.

| Case ID | Frozen boundary | Expected behavior |
| --- | --- | --- |
| `e2_resume_provider_completed_observation_pending` | Completed provider turn requests `ui_snapshot`; no tool dispatch intent | Dispatch `ui_snapshot` once, never repeat the provider request. |
| `e2_resume_provider_dispatch_uncertain` | Provider `dispatch_intent`; no completed response | `UNKNOWN_OUTCOME`; zero provider and tool calls. |
| `e2_resume_provider_completed_action_pending` | Completed turn requests `click`; no tool dispatch intent | Non-resumable/start new run; zero tool calls and no approval reuse. |
| `e2_resume_observation_completed` | Completed `ui_snapshot` result | Call provider continuation once with the persisted result; zero MCP calls. |
| `e2_resume_observation_dispatch_uncertain` | Observation `dispatch_intent`; no result | `UNKNOWN_OUTCOME`; zero MCP/provider calls. |
| `e2_resume_action_completed` | Completed successful `click` result | Never click again; dispatch one new approved-independent observation and remain verification-gated. |
| `e2_resume_action_dispatch_uncertain` | Action `dispatch_intent`; no result | `UNKNOWN_OUTCOME`; zero MCP/provider calls, zero replay. |
| `e2_resume_unknown_result_persisted` | Completed result has `status=unknown_outcome` | `UNKNOWN_OUTCOME`; zero external calls. |
| `e2_resume_checkpoint_continuation_torn` | Sequence or digest differs | Fail closed as corrupt; zero external calls and no mutation. |
| `e2_resume_identity_or_registry_drift` | Call identity, tool digest, provider/model, policy, or registry differs | `CHECKPOINT_MISMATCH`; zero external calls. |
| `e2_resume_budget_already_consumed` | Completion is durable but folded budget is exhausted | Stop with budget failure before any new external call. |
| `e2_resume_expired_or_symlinked_continuation` | Expired envelope or unsafe filesystem object | Fail closed; zero external calls. |
| `e2_resume_side_effect_then_crash_during_verification` | Action completed; verification observation has dispatch intent only | `UNKNOWN_OUTCOME`; never replay either action or observation. |
| `e2_resume_repeated_attach` | First attach has committed a new dispatch intent; second attach uses stale envelope | Second attach fails sequence/lease validation; no duplicate external call. |

For both providers, duplicate the completed-provider and completed-observation
cases to prove exact call/result correlation. OpenAI assertions freeze the
`previous_response_id`; Claude assertions freeze the reconstructed assistant
`tool_use` plus user `tool_result` pair. Neither suite may fall back to sending
the original task again.

## Delivery sequence

1. **Implemented:** add persistence DTO schemas, bounded strict readers, atomic
   writer, expiry, and pure round-trip tests without enabling resume.
2. **Implemented (pure foundation):** add operation identities, enforce
   `prepared -> dispatch_intent -> completed`, classify every crash boundary,
   and freeze the 14-case E2 matrix. All decisions remain non-executable and
   authorize zero external calls. Persisting these boundaries around live
   provider and MCP ports remains part of the runtime integration step.
3. Enable only the two read-only completed-boundary paths: completed provider
   response to one pending observation, and completed observation result to one
   new provider continuation.
4. Enable completed-side-effect recovery only into mandatory re-observation,
   after the no-replay E2 matrix is frozen and reviewed.
5. Keep uncertain dispatches, pending side-effects, drift, corruption, and
   expired records permanently fail-closed unless a later design is separately
   reviewed.
