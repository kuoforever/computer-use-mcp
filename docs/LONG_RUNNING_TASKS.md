# Long-running task contract

> **Status: initial control-state and batch-planning foundations implemented;
> orchestration remains planned.** The private campaign schema, append-only item
> ledger, fixed handoff projection, pure bounded batch selector, and locked
> heartbeat persistence plus pure freshness inspection are implemented without
> execution authority. The manifest also supports locked, durable
> `RUNNING`/`PAUSED` transitions and combined read-only stale-run inspection.
> A stale heartbeat owner can be explicitly replaced only after all item claims
> are released, and the fixed handoff projection is status-aware. The current
> handoff reader revalidates that projection against current durable state. The
> read-only resume preflight additionally checks heartbeat ownership, batches,
> and claims, and a pure resume planner can select the next bounded batch. The
> Agent Host does not yet implement a batch runner, heartbeat timer, CLI
> command, or complete cross-session handoff model.

## Goal

A task such as inspecting several hundred saved BOSS job postings must survive:

- provider context exhaustion;
- a Codex session ending or being replaced;
- browser, target-window, or MCP child restarts;
- a temporary login, challenge, network, or application failure;
- one malformed or unexpectedly expensive item;
- operator pause and later continuation.

The durable run state, not conversation history, is the source of truth.

## Work decomposition

One long task is a `campaign`. A campaign contains ordered, bounded `work
items`; one Agent invocation processes a bounded `batch`.

~~~text
campaign
  -> discovery snapshot
  -> item ledger
      -> item 0001
      -> item 0002
      -> ...
  -> batches
  -> aggregate result
~~~

For a saved-job review, one item is one stable job identity, not one viewport or
one click. Prefer an application-provided stable identifier or URL. If neither
exists, use a namespaced hash of the smallest repeatable visible identity and
record that the key is heuristic.

## Campaign state

Planned private state lives beside, but not inside, the redacted Agent
checkpoint:

~~~text
state_dir/
  campaigns/<campaign_id>/
    manifest.json
    items.jsonl
    batches.jsonl
    handoff.json
  runs/<run_id>/state.json
  traces/<run_id>.jsonl
~~~

`manifest.json` should contain only bounded control data:

~~~json
{
  "campaign_version": 2,
  "campaign_id": "campaign_...",
  "kind": "saved_job_review",
  "created_at": "...",
  "updated_at": "...",
  "status": "RUNNING",
  "cursor": {"next_ordinal": 41},
  "counts": {
    "discovered": 300,
    "completed": 40,
    "skipped": 0,
    "retryable": 1,
    "uncertain": 0
  },
  "active_run_id": "run_...",
  "policy_digest": "...",
  "schema_digest": "..."
}
~~~

Raw page text, screenshots, credentials, messages, and arbitrary model output
must not be placed in this control manifest. Application data belongs in a
separate explicitly private artifact with its own size and retention policy.

## Item ledger

Each item advances monotonically through:

~~~text
DISCOVERED -> CLAIMED -> OBSERVED -> EXTRACTED -> COMMITTED
                         |             |
                         +-> RETRYABLE +-> SKIPPED
                         +-> CHALLENGE
                         +-> UNCERTAIN
~~~

Required item metadata:

- stable item key and ordinal;
- current state and attempt count;
- claiming `run_id` and a lease expiry no more than one hour after the claim;
- last completed operation boundary;
- fixed result or failure code;
- content digest for committed output;
- no raw screenshot or unbounded page text in the ledger.

Append state transitions to `items.jsonl`; do not rewrite prior transitions.
The reducer may build an index, but the append-only ledger remains the recovery
source.

## Atomic work boundary

The minimum restart-safe unit is one item:

1. Claim the item with a lease.
2. Restore or verify the target application and account state.
3. Observe the item identity again.
4. Extract or perform the planned operation.
5. Verify the result.
6. Atomically commit the item result and advance the campaign cursor.

Do not advance the cursor before the item commit is durable. A crash before the
commit causes re-observation, not blind replay.

## Idempotency and uncertain actions

Read-only extraction can normally be repeated. Side effects require an
application-visible idempotency check. For example, before adding a favorite,
observe whether the item is already favorited; after acting, verify that state
before committing.

The contract does not promise exactly-once external side effects. It promises:

- no replay of an uncertain dispatched action;
- explicit `UNCERTAIN` state when verification is unavailable;
- re-observation before a new run decides what to do;
- item keys and operation digests that make duplicate work detectable.

## Batches and context rotation

A batch should be bounded by all of:

- maximum items;
- maximum wall-clock duration;
- maximum provider turns and tool calls;
- maximum input/output tokens;
- maximum screenshots or OCR regions;
- maximum consecutive failures.

Initial defaults for evaluation, not production promises:

~~~text
items_per_batch: 20
batch_wall_time: 20 minutes
checkpoint_every_items: 1
summary_every_items: 10
max_consecutive_failures: 3
~~~

The current selector is read-only: it orders only `DISCOVERED` and `RETRYABLE`
items by stable ordinal, applies every hard cap with a fixed stop reason, and
does not claim an item or invoke a provider. The private `batches.jsonl` ledger
now records a fixed-schema `STARTED`/`FINISHED` lifecycle and bounded measured
counters, but it does not measure time or start work. Clock measurement and
item claiming belong to the future worker.

The current coordinator may durably open a nonempty plan and close it only at a
derived hard limit or after every planned item is accounted for. It does not
perform those item operations, take a clock reading, or connect a provider.
For cross-session resume, it may now persist `STARTED` only from the exact
nonempty plan returned after a `READY` resume preflight. Blocked or empty
resume plans leave `batches.jsonl` unchanged. Opening this control-state record
still does not claim or execute any item.

An opened batch may now claim only the first item from its exact recomputed
plan when that item remains `DISCOVERED` or `RETRYABLE`, using the active batch
run identity and an injected lease no longer than one hour. Claiming rechecks
that the campaign is running, the heartbeat is fresh and owned by the batch
run, no other claim is current, and the caller's plan has not drifted. It
appends only the fixed `CLAIMED` transition; it does not observe or execute the
item, invoke a provider, or perform an MCP or desktop action.

Before any future item operation, a read-only claimed-item preflight can now
require a running campaign, the exact active batch/run, a fresh matching
heartbeat, exactly one current claim owned by that run, and an unexpired lease.
`READY` carries only the fixed `verify_current_page_and_account_state` and
`verify_claimed_item_identity` directives. The preflight does not perform
either observation or advance the item to `OBSERVED`.

After a caller explicitly confirms both required observations, a locked
persistence helper may now re-run that preflight and append the fixed
`OBSERVED`/`APPLICATION_AND_ITEM_VERIFIED` boundary. Missing attestations,
stale control state, owner drift, expired lease, clock rollback, or a repeated
call fail without a ledger write. The helper records an observation boundary;
it does not perform or infer the application observations itself.

An observed-item extraction preflight can now require the exact active
batch/run, a fresh matching heartbeat, one uniquely in-flight `OBSERVED` item,
and matching item ownership. `READY` carries only the fixed
`perform_bounded_read_only_extraction` directive. It does not extract content,
write `EXTRACTED`, or authorize side effects.

After a caller explicitly confirms that bounded read-only extraction is
complete, the locked item-progress helper may now re-run that preflight and
append only the fixed `EXTRACTED`/`READ_ONLY_EXTRACTION_COMPLETED` boundary.
It stores no extracted application content or result digest, performs no
extraction itself, and cannot represent a side-effect operation.

An extracted-item commit preflight can now require the exact active batch/run,
a fresh matching heartbeat, one uniquely in-flight `EXTRACTED` item, and
matching item ownership. `READY` carries only fixed directives to verify the
bounded extraction result and prepare its content digest plus fixed result
code. It does not inspect result content, calculate a digest, write
`COMMITTED`, advance the campaign cursor, or authorize side effects.

After a caller explicitly confirms the bounded result and supplies an exact
SHA-256 content digest, the locked item-progress helper may now re-run that
preflight and append only the fixed `COMMITTED`/`READ_ONLY_RESULT_VERIFIED`
boundary. The append atomically advances the ledger projection's derived
cursor. It stores the digest but no result content, does not rewrite the
handoff, and cannot commit side-effect work.

After a committed prefix, a read-only batch-continuation preflight can now
revalidate the active batch/run, fresh matching heartbeat, measured completed
count, original plan prefix, current stable item order, and every hard batch
limit. `READY` identifies only the exact next planned item and the fixed
`claim_exact_next_planned_item` directive. Plan drift, in-flight work, usage
drift, a reached limit, or a completed plan never writes or claims an item.

The locked coordinator may now re-run that continuation preflight and append a
fixed `CLAIMED` transition only for its exact next item, with a new bounded
lease owned by the active batch run. An empty committed prefix, repeated call,
limit boundary, plan or usage drift, stale control state, or invalid lease
fails without a write. The helper does not observe or execute the claimed item.

At a continuation boundary, the locked coordinator may now append `FINISHED`
only when a fresh continuation preflight reports a reached hard limit or the
entire original plan committed. The fixed stop code and all bounded counters
come from that validated state and measured usage. Ready work, in-flight work,
drift, stale ownership, or a repeated finish fails without a batch-ledger
write. This helper does not create or rewrite `handoff.json`.

After that fixed finish, a read-only handoff preflight can now revalidate the
finished batch/run identity, fresh heartbeat ownership, committed plan prefix,
absence of in-flight work, measured counters, fixed stop reason, and next
durable item ordinal. `READY` carries only the fixed
`write_current_campaign_handoff` directive. It does not create, replace, or
read `handoff.json`, and grants no resume or execution authority.

An expired current claim may now be released to `RETRYABLE` only while the
campaign store holds the OS run lock and the injected recovery time proves the
lease stale. The append-only transition uses fixed `LEASE_EXPIRED` semantics;
it does not claim the item for a new run, re-observe it, or authorize action
replay. Active and non-claimed items fail closed without a ledger write.

At a batch boundary, close the current run cleanly, write `handoff.json`, and
start a fresh provider context. A new Codex session should need only the
campaign ID and config path.

## Handoff record

`handoff.json` is compact, deterministic, and replaceable:

~~~json
{
  "campaign_id": "campaign_...",
  "campaign_version": 2,
  "next_item_ordinal": 41,
  "completed_count": 40,
  "retryable_count": 1,
  "uncertain_count": 0,
  "last_run_id": "run_...",
  "next_action": "resume_batch",
  "required_observation": "verify_current_page_and_account_state",
  "updated_at": "..."
}
~~~

It must not contain prose instructions generated by a model. The executable
meaning comes from the campaign version and fixed enums.

The current projection derives fixed directives from manifest status:

| Manifest status | `next_action` | `required_observation` |
| --- | --- | --- |
| `RUNNING` | `resume_batch` | `verify_current_page_and_account_state` |
| `PAUSED` | `wait_for_resume` | `none_until_resumed` |
| `CHALLENGE` | `wait_for_challenge_resolution` | `resolve_challenge_then_reobserve` |
| `COMPLETED` | `none_completed` | `none` |
| `FAILED` | `human_review_failed` | `review_failure_before_any_resume` |

This is a projection only. It does not resume a campaign, resolve a challenge,
or turn terminal state back into executable work.

The current reader accepts only the exact fixed field set and campaign version,
then compares status directives, counts, and next ordinal with the current
manifest and item ledger under the OS run lock. Missing, malformed, oversized,
or stale handoff data fails closed and must be regenerated from durable state.
Reading a valid handoff still does not start a worker or grant execution
authority.

The resume preflight combines a currently valid `resume_batch` handoff with a
fresh heartbeat owned by the proposed run, no active batch, and no current item
claim. It also fails closed when any item remains at the nonterminal
`OBSERVED` or `EXTRACTED` boundary, rather than treating the absence of a
current `CLAIMED` lease as completed work. It returns fixed readiness or
blocking states and preserves the required re-observation directive. `READY`
is control-state readiness only: no batch is opened, no item is claimed, and no
provider or desktop operation begins.

After `READY`, the pure resume planner applies the existing bounded batch
policy to the current ledger with zero initial usage. A blocked preflight does
not select items; an empty eligible set returns `NO_ELIGIBLE_ITEMS`. Even a
nonempty plan remains read-only: it does not write `STARTED`, claim an item, or
invoke a worker.

## Liveness

Checkpoint replacement alone does not prove a process is alive. A future
campaign worker should hold an OS run lock and update a bounded heartbeat at a
coarse interval. The operator UI may display:

The private campaign store now supports a fixed `heartbeat.json` record with
run identity, start time, observation time, and a freshness bound of at most
five minutes. Writes require the OS run lock, advance monotonically for the
same run, and cannot replace another run's record. This is persistence only:
no timer updates it, and the record alone does not classify a run as live or
stale.

The current pure inspector classifies an optional record as `MISSING`, `FRESH`,
or `STALE` against an injected aware time. Expiry at the exact observation
instant is stale, and a clock earlier than the recorded heartbeat fails closed.
This classification does not inspect the OS lock or item leases and therefore
cannot by itself declare `RUNNING` or authorize reclaim.

An operator-requested pause may now atomically move the campaign manifest from
`RUNNING` to `PAUSED` while the store holds the OS run lock. A later explicit
resume returns only the manifest to `RUNNING`; it does not claim an item,
restart a timer, re-observe an application, or authorize replay. Repeated pause
or resume requests are idempotent and do not rewrite the transition timestamp.

The combined stale-run inspector is available only while the campaign store's
OS run lock is held. It reads the manifest, heartbeat, and current item claims,
then reports a fixed blocking state for paused or terminal campaigns, missing
or fresh heartbeat, active lease, or mismatched run ownership. It reports
`STALE` only when a running campaign has a stale heartbeat and no active or
foreign-owned claim. `STALE` is a candidate for a separately reviewed recovery
step; it never authorizes item execution or action replay.

The store may replace a stale heartbeat owner only while holding the OS run
lock, after re-running the combined inspection in the same critical section.
Every stale item claim must first be released to `RETRYABLE`; owner replacement
does not change the manifest or item ledger. The replacement heartbeat must use
a new run identity and begin exactly at the injected recovery time. It starts
no worker and grants no item or action authority.

- `RUNNING`: valid lease and fresh heartbeat;
- `WAITING_APPROVAL`: explicit phase;
- `PAUSED`: operator-requested durable state;
- `STALE`: expired heartbeat or lease; not automatically reclaimed;
- `CHALLENGE`: user intervention required;
- terminal campaign states.

Reclaiming stale work requires validating both the OS lock and the item lease.
The current read-only lease inspector reports `CLAIMED` items as active or
stale using an injected timestamp; it does not reclaim them. Never infer
permission to replay an action from an expired heartbeat.

## Retry classes

| Class | Default behavior |
| --- | --- |
| Stale UI reference or page changed | Re-observe once inside the same item. |
| Window activation failure | Re-list windows and retry once only after a fresh identity match. |
| Provider or transport failure before dispatch | Retry within the remaining batch budget. |
| Unknown result after dispatch | Mark the item `UNCERTAIN`; do not replay. |
| Authentication or challenge required | Mark `CHALLENGE`, persist handoff, and wait for the operator. |
| Rate limit or repeated site refusal | Pause the campaign with a fixed reason; do not rotate backends as an evasion strategy. |
| Repeated item-specific parse failure | Mark `RETRYABLE` or `SKIPPED` according to campaign policy and continue. |

## Application acceptance scenarios

The detailed cases live in [Application evaluation matrix](APPLICATION_EVALUATION_MATRIX.md).
The first long-run evaluation should use a non-destructive BOSS review campaign:

1. Discover at least 100 saved-job identities without changing the collection.
2. Process them in at least five batches and two fresh provider contexts.
3. Terminate one run between items and resume from the next durable item.
4. Terminate one run after observation but before commit and prove the item is
   re-observed without duplicating committed output.
5. Inject one activation failure, one stale UI reference, and one provider
   failure.
6. Finish with one committed result per stable item key, a bounded handoff, and
   no uncertain side-effect replay.

After the BOSS baseline, add two structurally different workloads:

- a Google Docs campaign over at least 50 heading-delimited sections, including
  canvas/document-text/OCR observation fallback, zoom-induced coordinate
  invalidation, provider-context rotation, and restart away from the current
  scroll position;
- a WeChat campaign over dedicated test conversations, covering launcher-to-
  main-window handle replacement, activation, exact conversation identity,
  editor focus, and draft verification. Sending remains a separate optional
  side-effect tier with no replay after an unknown outcome.

The first cross-application campaign should read BOSS results, write a
structured summary to a disposable Google Doc copy, and prepare a WeChat draft
after a fresh-session handoff.

## Planned enterprise workflow ledger

Enterprise campaigns require a second layer above the item ledger: a durable
cross-system transaction record. One business item, such as an incident or
invoice, may contain ordered operations in several applications. Each operation
records the stable object identity, expected pre-version, requested business
transition, authority-envelope digest, dispatch boundary, verification result,
and resulting version.

~~~text
business item
  -> observe source notification
  -> verify system-of-record object and version
  -> collect evidence from approved sources
  -> prepare bounded proposal
  -> wait for role-appropriate approval
  -> dispatch one business transition
  -> verify new object version
  -> notify or reconcile downstream systems
~~~

The record uses fixed states such as `PREPARED`, `WAITING_APPROVAL`,
`DISPATCHED`, `COMMITTED`, `CONFLICT`, `CHALLENGE`, and `UNCERTAIN`. It is a
saga-style reconciliation record, not a claim of an atomic transaction across
unrelated applications. A committed external step is never silently reversed;
compensation requires its own reviewed operation and authority.

Enterprise queue metadata additionally includes owner, priority, SLA deadline,
tenant, data classification, escalation route, lease, and pause reason. Workers
must stop on tenant drift, expired authority, concurrent object modification,
classification mismatch, or loss of the required role. Reassignment and human
takeover are durable transitions, not informal chat instructions.

## Delivery sequence

1. Read-only campaign schema and item ledger. **Initial private foundation
   implemented:** strict manifest, durable append-only transition reducer,
   RunLock-bound atomic writes, and fixed handoff projection; no batch runner,
   provider, MCP, desktop, or CLI connection.
2. Batch runner and deterministic handoff command.
3. Heartbeat, pause, and stale-run inspection.
4. BOSS read-only 100-item evaluation.
5. Google Docs 50-section and WeChat draft-only evaluations.
6. Cross-application campaign with a fresh-session boundary.
7. Wave 2 application coverage: Excel, PDF, Figma/Canva, and Electron.
8. Only then consider resumable side-effect campaigns and higher-complexity
   remote-desktop or modal-tool workloads.
9. Define object-scoped enterprise authority, data classification, transaction
   reconciliation, SLA ownership, and human takeover before Wave 4.
10. Run the synthetic read-only IT incident campaign, then add approved ticket
    updates and notifications one effect tier at a time.
