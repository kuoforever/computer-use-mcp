# Persisted continuation and crash reconstruction design

> **Status: opt-in runtime write-ahead persistence and controlled bounded
> read-only recovery implemented.** The strict
> bounded v5 envelope, private atomic reader/writer, provider/MCP
> `prepared -> dispatch_intent -> completed` boundaries, conservative crash
> classifier, frozen E2 boundary matrix, provider continuation export/restore,
> strict planner, atomic sequence-checked intent/completion commits under the
> run lock, and an explicit CLI entry point exist for three completed
> read-only external recovery boundaries plus local final-response
> terminalization. The CLI may chain up to four individually
> committed steps under one run lock and never replays uncertain dispatches or
> pending side effects.

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
base64 PNG blocks in v5; no arbitrary MIME type or external path is accepted.

## Continuation envelope v5

~~~json
{
  "continuation_version": 5,
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
  "provider_state": {
    "response_id": "resp_...",
    "prior_context_tokens": 1234,
    "request_contract_digest": "<sha256>",
    "memory_context_used": false,
    "initial_input": "original task and optional canonical memory data",
    "output_batches": [
      {"response_id": "resp_...", "items": []}
    ]
  },
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
  current Agent, v5 continuation cannot contain or resume a `type` call;
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

- OpenAI: the last completed `response_id`, that response's reported input and
  output token total, a canonical request-contract digest, and a boolean saying
  whether explicit memory context was present on the initial request, and the
  exact initial SDK input string, and ordered per-response batches containing
  every canonical JSON `response.output` item. OpenAI requests explicitly include
  `reasoning.encrypted_content`, and request-contract version 3 binds that include
  list so portable encrypted reasoning cannot be silently omitted. The initial
  input's SHA-256 is included in the request
  contract digest. Resume restores these before preflight, then sends only the next new
  `function_call_output` set with that ID. The boolean preserves the fixed
  memory-as-untrusted-data instruction; the persisted initial input may contain
  the explicitly selected memory and remains confined to the sensitive private
  artifact. It is replayed only through the explicit stateless compiler after
  complete envelope validation. Token mismatch,
  output-batch mismatch, contract drift, and v1-v4 state fail closed before
  provider dispatch. If the provider cannot continue that response, the run
  stops; it does not resend the previous request.
- Claude: the exact bounded canonical user/assistant message history compiled
  from the persisted ledger. Resume appends only the next new `tool_result`
  message. Provider-returned wire objects are never pickled or trusted directly.

The adapter must expose pure `export_continuation` and `restore_continuation`
operations. Restoration performs validation and network I/O is forbidden until
the host commits a new dispatch intent.

For both `DISPATCH_OBSERVATION` and `MANDATORY_REOBSERVE`, a recovered call
remains non-authoritative data. Immediately before any tool `dispatch_intent`
can be committed, the executor resolves the current reviewed tool specification
and requires all of its `required_safety_baselines` to be present in the
currently connected MCP generation's `satisfied_safety_baselines`. Missing
current evidence fails with fixed `RECOVERY_SAFETY_BASELINE_UNSATISFIED`, with
no checkpoint or continuation mutation and zero MCP tool dispatch.

## Write-ahead operation protocol

Every external operation has a unique `operation_id` and three possible durable
records:

1. `prepared`: request/call material is durable; nothing has been dispatched.
2. `dispatch_intent`: written and flushed immediately before entering the SDK or
   MCP dispatch boundary.
3. `completed`: the normalized response/result is durable and the next step is
   named explicitly.

A provider `dispatch_intent` does not make the returned turn trusted or
completed. After the provider returns and turn identity is checked, the Runner
atomically verifies every requested tool against the exact set the Host actually
advertised after caller, privacy, and MCP safety-baseline filtering. If any call
is absent, fixed `PROVIDER_TOOL_NOT_ADVERTISED` terminates the run before model
ledger/budget consumption, provider-state export, `completed`, policy, approval,
or MCP dispatch. A surviving provider intent remains conservative unknown
evidence; it is never reconstructed as completed provider work.

A result-carrying post-dispatch MCP cancellation is completed through this same
protocol before cancellation is re-propagated. The Runner validates and privacy
protects the bridge's `unknown_outcome` result, records the correlated tool
result, writes the `completed` continuation boundary, and terminalizes the safe
checkpoint as `UNKNOWN_OUTCOME`. Shared callers must not overwrite that terminal
state with generic `CANCELLED`. Ordinary Runner cancellation cleanup then deletes
the opt-in sensitive continuation as documented above; the redacted trace and
checkpoint remain durable and recovery cannot replay the call. A persistence
failure while writing `completed` is not hidden by the cancellation handler:
the Runner still terminalizes the redacted checkpoint as `UNKNOWN_OUTCOME` and
re-propagates the result-carrying cancellation with that persistence failure as
its chained cause. Recovery treats any surviving `dispatch_intent` or incomplete
record conservatively.

The conservative reconstruction matrix is:

| Durable boundary at crash | Reconstruction decision |
| --- | --- |
| `prepared`, provider request | Do not send it; start a new run. |
| `dispatch_intent`, provider request, no completion | `UNKNOWN_OUTCOME`; do not resend. |
| `completed`, provider response | Consume the response locally; do not call provider again. A pending observation call may be dispatched once. A provider-requested side effect is validated as an input record, terminalized as a fixed failure, and never dispatched. |
| `prepared`, tool call | Observation may be dispatched once only if no dispatch intent exists and its current required MCP safety baselines are satisfied. Pending side-effect requires a new run. |
| `dispatch_intent`, any tool call, no completion | `UNKNOWN_OUTCOME`; do not call the tool again. |
| `completed`, observation result | Consume the result and issue only the next new provider continuation. |
| `completed`, side-effect result | Consume the result, invalidate grounding, and issue only a new mandatory observation. Never repeat the side-effect. |
| `completed`, unknown-outcome result | `UNKNOWN_OUTCOME`; require human re-observation in a new run. |

Writing `dispatch_intent` before the actual dispatch creates a conservative
false-unknown window if the process dies between the two. That cost is accepted:
avoiding duplicate actions is more important than maximizing resume rate.

## Frozen E2 crash-reconstruction cases

The canonical deterministic E2 fixture covers every durable boundary below.
Each case freezes the recovery classification and exact runtime external calls;
the execution test constructs real checkpoint/continuation artifacts, holds the
run lock, and uses fake provider/MCP ports to prove zero action replay.

| Case ID | Frozen boundary | Expected behavior |
| --- | --- | --- |
| `e2_resume_provider_completed_observation_pending` | Completed provider turn requests `ui_snapshot`; no tool dispatch intent | Dispatch `ui_snapshot` once, never repeat the provider request. |
| `e2_resume_provider_dispatch_uncertain` | Provider `dispatch_intent`; no completed response | `UNKNOWN_OUTCOME`; zero provider and tool calls. |
| `e2_resume_provider_completed_action_pending` | Completed turn requests `click`; no tool dispatch intent | Validate the input record, terminalize as `FAILED/RECOVERED_ACTION_REQUESTED`, delete the continuation, and dispatch zero policy/approval/MCP calls. |
| `e2_resume_provider_completed_final` | Completed provider turn has exact final text and no tool calls | Validate correlation, advance to `SUCCESS`, and delete the continuation with zero provider/MCP calls. |
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
default `previous_response_id` path and the separately explicit stateless
request's complete item order; Claude assertions freeze the reconstructed
assistant `tool_use` plus user `tool_result` pair. Neither suite may trigger an
automatic fallback.

The separately frozen `evals/e2-stateless-replay.json` matrix covers nine
digest-bound replay artifacts. Its manifest freezes successful text and
screenshot compilation, unknown/missing/mismatched/reordered items,
side-effect history, request overflow, and provider failure. A recovery
executor test additionally proves replay preflight completes before the durable
provider intent and that historical calls cause zero MCP dispatches.
Release preflight report v5 exposes both this replay matrix and the 15-case
crash-reconstruction matrix as independent fail-closed gates with canonical
fixture/manifest hashes and case/test counts. The CI matrix runs both separately
and retains JUnit evidence without enabling provider or desktop integration.

## Delivery sequence

1. **Implemented:** add persistence DTO schemas, bounded strict readers, atomic
   writer, expiry, and pure round-trip tests without enabling resume.
2. **Implemented:** add operation identities, enforce
   `prepared -> dispatch_intent -> completed`, classify every crash boundary,
   freeze the crash-boundary E2 matrix, and persist the boundaries immediately around
   live provider and MCP dispatch when explicitly enabled. All reconstruction
   decisions remain non-executable and authorize zero external calls.
3. **Implemented:** pure provider export/restore, strict attach planning, and a
   controlled executor covers the completed read-only boundaries.
   `agent recover ... --execute-read-only` holds the run lock, compares both
   persisted sequences, revalidates the reviewed call's required safety
   baselines against the current MCP generation, durably commits intent before
   exactly one external call, then commits its normalized completion. Torn
   cross-file updates and repeated attaches fail closed on sequence mismatch.
   The full runtime E2 matrix freezes exact external-call counts for enabled and
   rejected boundaries.
4. **Implemented:** a completed side effect can dispatch exactly one synthetic
   `ui_snapshot` under the same locked intent/completion protocol. It never
   repeats the action, reuses approval, or continues the old provider exchange;
   successful observation persists `next_step=stop` and requires a new run.
5. **Implemented:** terminalize a fully persisted provider response with no
   tool calls locally under the run lock. This records `SUCCESS` and final-text
   length in the safe checkpoint, deletes the sensitive continuation, returns
   the already persisted text, and performs zero provider/MCP calls.
6. **Implemented:** terminalize complete recovered provider action requests as
   fixed local failures. One or more calls are correlated as input records only;
   the checkpoint advances to `FAILED`, the continuation is deleted, the CLI
   exits nonzero, and policy/approval/MCP receive zero calls.
7. Keep uncertain dispatches, pending side-effects, drift, corruption, and
   expired records permanently fail-closed unless a later design is separately
   reviewed.
