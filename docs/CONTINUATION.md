# Persisted continuation and crash reconstruction design

> **Status: opt-in runtime write-ahead persistence and controlled bounded
> read-only recovery implemented.** The strict
> bounded v6 envelope, private atomic reader/writer, provider/MCP
> `prepared -> dispatch_intent -> completed` boundaries, conservative crash
> classifier, frozen E2 boundary matrix, provider continuation export/restore,
> strict planner, atomic sequence-checked intent/completion commits under the
> run lock, and an explicit CLI entry point exist for three completed
> read-only external recovery boundaries plus local final-response
> terminalization. Complete-ledger certainty folding prevents a tail provider
> response from erasing an earlier verification or unknown-outcome obligation.
> The CLI may chain up to four individually
> committed steps under one run lock and never replays uncertain dispatches or
> pending side effects.

## Safety boundary

Broader resume means reconstructing the next state-machine step from a completed,
durably recorded boundary. It never means retrying an in-flight operation.

Same-process cooperative Pause/Takeover/Resume is a separate authority lane.
The live Runner owns it, explicit resume always requires a fresh successful
observation, and it is rejected before external work when continuation is
enabled. A persisted `PAUSED` checkpoint without its still-live cooperative
lease is not crash-resumable; use the conservative recovery/new-run rules in
this document instead. See [Cooperative control](COOPERATIVE_CONTROL.md).

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
6. Verification and terminal certainty are monotonic across the complete
   ledger. Provider completion, recovery intent, and failed observation cannot
   clear them; only a correlated successful ordinary observation can restore
   `ready`.

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
independently from the 64 KiB checkpoint. Binary images remain stored as
bounded base64 PNG blocks in v6; no arbitrary MIME type or external path is
accepted.

## Continuation envelope v6

This is a shape excerpt. Placeholder identities, digests, timestamps, provider
state, and the empty ledger are illustrative and are not accepted verbatim.

~~~json
{
  "continuation_version": 6,
  "run_id": "run_...",
  "checkpoint_sequence": 7,
  "policy_version": "...",
  "provider": {"name": "openai", "model": "..."},
  "registry_digest": "<sha256>",
  "advertised_tool_names": ["ui_snapshot"],
  "task": "original task",
  "budget": {
    "max_model_turns": 12,
    "max_tool_calls": 32,
    "max_side_effects": 8,
    "max_input_tokens": 1000000,
    "model_turns_used": 2,
    "tool_calls_used": 1,
    "side_effects_used": 0,
    "input_tokens_used": 1234
  },
  "observation": {
    "epoch": 2,
    "verified_epoch": null,
    "mcp_generation": 1
  },
  "ledger": [],
  "boundary": {
    "operation_kind": "tool",
    "stage": "completed",
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
- require budget counters and the observation epoch to equal a fresh fold of
  the ledger. A verified epoch may only equal the folded value or be cleared by
  a checkpoint-backed stricter Host state; it can never be advanced beyond
  ledger evidence;
- treat the recomputable payload digest as corruption evidence, never
  authority;
- require non-authoritative `boundary.next_step` to match the complete operation
  kind/stage/identity/effect/dispatch plus correlated ledger and provider state,
  or fail with fixed `CONTINUATION_LEDGER_INVALID` before any budget choice,
  intent write, provider restore, MCP discovery, or dispatch;
- require `advertised_tool_names` to be the unique, current-reviewed names in
  canonical registry order and require every persisted provider-requested call
  to belong to that immutable set;
- reject continuation v1-v5 as unsupported rather than inferring a wider tool
  set from an older artifact, and reject missing, malformed, duplicate,
  reordered, or unreviewed v6 scope evidence;
- reject raw `type.text` entirely. Persisted scope evidence cannot make a
  sensitive typed-text call resumable;
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
  output-batch mismatch, contract drift, and v1-v5 state fail closed before
  provider dispatch. If the provider cannot continue that response, the run
  stops; it does not resend the previous request.
- Claude: the exact bounded canonical user/assistant message history compiled
  from the persisted ledger. Resume appends only the next new `tool_result`
  message. Provider-returned wire objects are never pickled or trusted directly.

The adapter must expose pure `export_continuation` and `restore_continuation`
operations. The Host supplies the exact recovered tuple to restoration and the
next request. OpenAI binds it through its request-contract digest; Claude's
state restoration grants no tool authority, so the Host's shared tuple and
post-response membership gate remain authoritative. Network I/O is forbidden
until the Host commits a new dispatch intent.

`advertised_tool_names` is Host-owned authority evidence, not provider state.
The live Runner records the exact immutable set remaining after caller,
privacy, connected-MCP safety-baseline, and continuation-compatibility
filtering. Because v6 rejects raw `type.text`, enabling continuation removes
`type` from both the provider schema tuple and persisted names even when the MCP
reports `typed_text_audit_redaction`. Disabling continuation does not itself
disable a baseline-satisfied `type` call. At a
`CONTINUE_PROVIDER` boundary, recovery narrows that set again to current
reviewed observation tools. A baseline-required observation remains eligible
only when an attached, already-discovered desktop currently reports every
required baseline; with no desktop attached, the current baseline set is
empty and every baseline-required tool is omitted. Side-effect tools are
always omitted even if they were present in the original live scope.

The resulting registry-ordered tuple is supplied unchanged to provider-state
restoration, explicit OpenAI stateless-replay preflight, and the new provider
`create_turn` call. OpenAI validates that tuple against the persisted
adapter-visible request contract and continues only when the digest is
unchanged; an action-enabled or otherwise drifted chain fails with
`OPENAI_REQUEST_CONTRACT_MISMATCH` before network I/O rather than weakening the
binding. Claude receives the same Host restriction despite having no equivalent
request digest. Scope recovery can only remove tools. It does not authorize a
historical call, replay an operation, open MCP merely to discover more
authority, or create a second dispatch path.

For both `DISPATCH_OBSERVATION` and `MANDATORY_REOBSERVE`, a recovered call
remains non-authoritative data. Immediately before any tool `dispatch_intent`
can be committed, the executor resolves the current reviewed tool specification
and requires all of its `required_safety_baselines` to be present in the
currently connected MCP generation's `satisfied_safety_baselines`. Missing
current evidence fails with fixed `RECOVERY_SAFETY_BASELINE_UNSATISFIED`, with
no checkpoint or continuation mutation and zero MCP tool dispatch.

The Host-synthesized mandatory `ui_snapshot` is also bounded by the original
v6 names. If the caller did not advertise `ui_snapshot`, recovery returns
`START_NEW_RUN/RECOVERY_MANDATORY_OBSERVATION_NOT_ADVERTISED` with no new intent
or MCP call; a safety observation never becomes an implicit scope expansion.

Recovery budget authority is derived only after the complete topology has
reconstructed the final action. `CONTINUE_PROVIDER` requires both a fresh model
turn and remaining input-token capacity. A new `DISPATCH_OBSERVATION` or
`MANDATORY_REOBSERVE` requires a fresh tool-call slot. A provider-correlated tool
observation already durable at `prepared` has consumed its one slot, so recovery
advances that same call without incrementing the budget or appending a duplicate
`tool_call`. A non-provider verification call must instead match the fixed
Host-synthesized mandatory identity, arguments, and checkpoint sequence; it can
never appear as an executable `prepared` call. Local terminal, unknown, and
start-new-run decisions consume no new external-call budget. The CLI planner
applies this rule before opening a provider or MCP connection; the executor
repeats it before the first port call, and locked persistence replans the current
sequence before writing intent.

Recovery certainty is likewise derived from the complete canonical ledger, not
the tail boundary. Sequential provider turns advertise the only calls that may
later appear as ordinary tool records; each result must correlate to one issued,
unfinished call. Every advertised call must either remain in the current
completed-provider tail or receive its ordered call/result pair before a later
provider turn. An unissued request, unfinished issued call, completed final
provider response, terminal unknown result, or completed Host-synthesized
recovery observation cannot be followed by another durable event.

Each folded provider turn also reapplies the live Runner's whole-turn
seriality rule. A turn with more than one call and any side effect may exist
only as the current completed-provider tail, where its requests remain
untrusted input and are terminalized together as `RECOVERED_ACTION_REQUESTED`
with zero dispatch. Any later durable event or non-current boundary makes that
turn invalid. Pure observation multi-call turns remain valid. This prevents a
historical sibling observation from counting as verification and clearing an
action's recovery debt.

The certainty fold mirrors the live Runner. A dispatched side effect and the
exact `REJECTED/not_dispatched/HUMAN_ACTIVE|DENIED_BY_GATE` tuples clear the
verified epoch and establish `requires_reobservation`. Provider completion,
ordinary dispatch intent, and a failed ordinary observation preserve the
current state. A Host-synthesized mandatory-observation intent establishes or
retains `requires_reobservation` and clears the verified epoch; a correlated
successful ordinary observation is the only ordinary transition back to
`ready`. `UNKNOWN_OUTCOME` is absorbing. A known completion of the exact
Host-synthesized mandatory recovery observation remains `stopped`, preserving
the existing new-run boundary.

The checkpoint must match continuation budgets and observation counters and may
be only as permissive as this fold. Host-only evidence may make it stricter, but
a checkpoint cannot claim `ready` while the ledger still requires verification.
A stricter non-`ready` checkpoint may keep the verified epoch cleared as its
status progresses to `unknown_outcome` or `stopped`; the ledger's older verified
epoch cannot force that Host-only debt back to `ready`.
A completed final provider response is locally terminalizable only when both
the folded ledger and checkpoint are `ready`. An outstanding
`requires_reobservation` state returns fixed
`START_NEW_RUN/VERIFICATION_REQUIRED`; stricter terminal unknown or stopped
evidence retains its own human/new-run outcome. None returns final text, calls a
provider/MCP port, or mutates state. Locked recovery writes preserve the current
obligation through intent, provider completion, and failed observation, while
the trace finalizer independently refuses any checkpoint not already `ready`.

## Write-ahead operation protocol

Every external operation has a unique `operation_id` and three possible durable
records:

1. `prepared`: request/call material is durable; nothing has been dispatched.
2. `dispatch_intent`: written and flushed immediately before entering the SDK or
   MCP dispatch boundary.
3. `completed`: the normalized response/result is durable and the next step is
   named explicitly.

The active Runner can distinguish a local tool-WAL write failure from a crash.
If `prepare_tool` or `dispatch_tool` raises `CONTINUATION_WRITE_FAILED`, control
has not yet entered the sole MCP call site, so dispatch is known not to have
occurred even if a `dispatch_intent` replacement reached disk before a later
filesystem operation failed. The Runner appends a correlated
`REJECTED/not_dispatched` result, terminalizes the safe checkpoint as fixed
`FAILED/CONTINUATION_WRITE_FAILED` from that latest ledger, and closes the
sensitive continuation. It does not retry or reinterpret the failure as an
unknown outcome. This mapping is deliberately limited to those two calls;
`complete_tool` runs after MCP entry and its failures never gain
known-not-dispatched semantics.

A provider `dispatch_intent` does not make the returned turn trusted or
completed. After the provider returns and turn identity is checked, the Runner
atomically verifies every requested tool against the exact set the Host actually
advertised after caller, privacy, MCP safety-baseline, and continuation-
compatibility filtering. If any call
is absent, fixed `PROVIDER_TOOL_NOT_ADVERTISED` terminates the run before model
ledger/budget consumption, provider-state export, `completed`, policy, approval,
or MCP dispatch. The Runner next preflights every call's reviewed schema and
canonical arguments at the same whole-turn boundary; one invalid sibling fails
with fixed `SCHEMA_MISMATCH` before any valid prefix executes. Once those specs
are reviewed, a multi-call turn containing any side effect fails with fixed
`PROVIDER_SIDE_EFFECT_TURN_NOT_SERIAL`; action/action, observation/action, and
action/observation orderings all stop before provider completion, while a pure
observation multi-call turn remains eligible. Any rejection may leave only the
conservative provider `prepared` and `dispatch_intent` records; no provider
`completed` or tool boundary is written, and surviving intent remains unknown
evidence rather than completed provider work.

Recovered provider turns use the same ordering against the narrowed v6 scope.
After turn identity validation, any unadvertised sibling rejects the whole turn
with fixed `RECOVERY_PROVIDER_TOOL_NOT_ADVERTISED` before schema validation,
provider-state export, provider completion, or any future MCP dispatch. A valid
observation prefix cannot execute first. Because the new provider request still
crosses an external boundary, its durable `dispatch_intent` necessarily
precedes the SDK call and remains conservative unknown evidence if returned
data is rejected.

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
| `completed`, provider response | Consume the response locally; do not call provider again. A pending observation call may be dispatched once. A provider-requested side effect is validated as an input record, terminalized as a fixed failure, and never dispatched. Final text succeeds only when the complete ledger and checkpoint are `ready`; an earlier unmet verification obligation returns `VERIFICATION_REQUIRED`. |
| `prepared`, tool call | A provider-correlated observation may be dispatched once only if no dispatch intent exists and its current required MCP safety baselines are satisfied. It advances the already charged call without another ledger entry or tool-budget increment. A forged/non-provider prepared call fails closed; a pending side effect requires a new run. |
| `dispatch_intent`, any tool call, no completion | `UNKNOWN_OUTCOME`; do not call the tool again. |
| `completed`, observation result | Consume the result and issue only the next new provider continuation with the original v6 scope narrowed to current-safe observations. |
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

Restricted-scope recovery tests additionally freeze the same tool tuple across
restore, replay preflight, and provider creation for both real adapters. They
cover valid restricted continuation, current-baseline narrowing, old or
malformed scope rejection, and mixed returned turns with zero valid-prefix or
MCP execution. These checks strengthen the Host boundary without changing the
frozen crash/replay fixture semantics or authorizing automatic fallback.

Live Runner compatibility tests additionally give the fake MCP the typed-text
audit baseline while continuation is enabled. They require `type` to be absent
from both provider schemas and both pre-request persisted scope records. A mixed
returned turn containing a valid observation plus `type` fails atomically as
`PROVIDER_TOOL_NOT_ADVERTISED` with only the user-task trace, zero budget,
approval, or MCP authority, and no raw typed text in the safe record. A separate
continuation-disabled approved workflow retains baseline-satisfied typing.

Side-effect turn-seriality tests cover action/action, observation/action, and
action/observation returns with valid advertised names and canonical schemas.
Each fails before model/tool budget, provider completion, approval, or MCP and
leaves only provider `prepared` and `dispatch_intent` evidence. A separate pure
observation multi-call turn completes both tool boundaries, and the existing
single-action workflow still reaches mandatory re-observation and success.

Live tool-WAL failure tests inject both `prepared` and `dispatch_intent` writes
for an observation and an approved action. All four cases retain exact budgets
and canonical ledger order, end with a correlated rejected/not-dispatched
result and terminal safe checkpoint, close the continuation, and prove the
target MCP call is zero. The approved-action cases retain the audited `ALLOW`
and consumed side-effect budget; neither fact becomes dispatch authority.
Normal WAL completion, provider-side intent failure, post-dispatch unknown
outcome, and result-carrying cancellation remain separate controls.

Recovery semantic-binding tests recompute a valid v6 digest after replacing the
three completed executable boundary classes' canonical `next_step` with every
other schema-valid value. All mismatches fail as
`CONTINUATION_LEDGER_INVALID` without intent or external I/O and leave
checkpoint and continuation bytes unchanged. Separate canonical controls
exhaust model turns, input tokens, and tool calls and retain
`START_NEW_RUN/BUDGET_EXHAUSTED`. A prepared-observation control exhausts its
single already charged tool slot, dispatches exactly once, and proves that
intent/completion neither duplicate the call nor increment the budget again.
A digest-valid non-provider observation appended after a completed side effect
is rejected before intent or MCP; only the exact Host-synthesized mandatory
identity can represent that verification lineage.

Complete-ledger certainty tests construct the ordinary Runner crash window in
which a correlated side effect is durable, a final provider response is also
durable, and the process dies before the live `VERIFICATION_REQUIRED` check.
OpenAI and Claude plus success, dispatched failure, human-yield, and live-gate
result variants all stop locally with zero provider/MCP calls and byte-identical
artifacts. Separate controls prove successful verification restores finalization,
ordinary known-not-dispatched transport failure does not create debt, unknown
certainty is absorbing, counter/status swaps cannot widen the checkpoint, and
recovery intent, failed observation, and later provider completion preserve the
obligation. A provider-neutral historical-turn matrix additionally covers
action/observation, observation/action, and action/action ordering; every
side-effect-bearing multi-call turn fails as `CONTINUATION_LEDGER_INVALID`
before persistence or external I/O and leaves both artifacts byte-identical.
A separate current-tail multi-action control retains fixed
`RECOVERED_ACTION_REQUESTED` terminalization with zero dispatch. These tests
also reject an abandoned action or observation before a later provider turn,
while a complete pure-observation multi-call history remains finalizable. A
locked Host-only-debt chain proves an unknown recovered observation retains
`UNKNOWN_OUTCOME` with its verified epoch cleared. These tests use continuation
v6 without changing the frozen E2 fixture or schema version.

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
7. **Implemented:** continuation v6 binds the original Host-advertised names.
   Provider continuation narrows them to current-safe observations, uses that
   exact tuple for restore/replay/request construction, and rejects a returned
   out-of-scope sibling atomically before completion or later tool dispatch.
8. **Implemented:** the live Host excludes `type` whenever continuation is
   enabled, so no advertised provider call can require persisting raw typed text.
   The v6 validator remains strict and continuation-disabled behavior is
   unchanged.
9. **Implemented:** semantically bind v6 `next_step` to the complete durable
   topology before using it, reconstruct the final recovery action before
   selecting its budget dimension, and repeat that check at executor and locked
   persistence boundaries. Digest-valid semantic swaps and canonical exhausted
   budgets stop before intent or external I/O; a prepared observation reuses its
   already charged call.
10. **Implemented:** fold complete-ledger recovery certainty and bind it to the
    checkpoint before final-provider success. Verification debt survives every
    intent, provider completion, and failed observation write; unknown and
    synthetic-stop states are terminal, and only a correlated successful
    ordinary observation restores `ready`.
11. Keep uncertain dispatches, pending side-effects, drift, corruption, and
   expired records permanently fail-closed unless a later design is separately
   reviewed.
