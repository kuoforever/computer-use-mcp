# Long-running task contract

> **Status: initial control-state and batch-planning foundations implemented;
> orchestration remains planned.** The private campaign schema, append-only item
> ledger, fixed handoff projection, pure bounded batch selector, and locked
> heartbeat persistence plus pure freshness inspection are implemented without
> execution authority. The manifest also supports locked, durable
> `RUNNING`/`PAUSED` transitions and combined read-only stale-run inspection.
> The current Agent Host does not yet implement a batch runner, heartbeat
> timer, CLI command, or complete cross-session handoff model.

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
