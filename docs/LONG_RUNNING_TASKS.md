# Long-running task contract

> **Status: campaign control plane implemented and offline verified; first
> fixed observation-through-restart/resume seam connected.** Manifests, item/batch ledgers, leases,
> heartbeat, pause/stale inspection, deterministic handoff, bounded resume/run
> transfer, read-only item progression, and completion are implemented without
> provider, general worker, timer, side-effect, or free-form campaign-creation
> authority. One
> exact claimed synthetic item can execute `list_windows` through the existing
> Runner authority, persist correlated `OBSERVED`, extract only a bounded
> non-sensitive window count, persist `EXTRACTED`, verify canonical JSON,
> persist its SHA-256 digest at `COMMITTED`, close the batch with measured
> usage, write deterministic handoff, and transfer a fresh Runner run to the
> expected exhausted resume decision using only durable campaign records.
> See [Capability status](CAPABILITY_STATUS.md) for the next evidence gate.

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
    discovery.jsonl
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

## Discovery-pass ledger

A campaign that discovers its items by observing a source repeatedly records
each observation in `discovery.jsonl`. One pass holds only `sequence`, `at`, a
`source_digest` of the bounded observed text, `observed_count`, `new_count`, and
an optional `run_id`. It never holds observed content, a URL, a page number, or
a selector, because progression is caused by the operator moving the observed
source, not by a parameter this boundary accepts.

The ledger is append-only and enforces two durable invariants: sequence numbers
are contiguous with non-decreasing timestamps, and a pass may not repeat the
immediately preceding `source_digest`. An unchanged source therefore fails
closed instead of recording a second pass over the same observation.

Items are appended before the pass that records them. A persisted item count
above the recorded `new_count` total means an interrupted pass and stays
repairable by observing the same source again; the reverse means a pass claims
items that were never persisted and must fail closed for operator inspection. A
pass with `new_count` zero is a recorded fact, not an inferred end of the
source: a later distinct source may still add items.

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

### Current control-state boundary

The implemented offline control plane provides:

- a read-only selector over stable `DISCOVERED` and `RETRYABLE` ordinals with
  fixed hard-limit reasons;
- fixed-schema `STARTED` and `FINISHED` batch records with bounded measured
  counters;
- exact-plan first and continued claims with injected, bounded leases;
- fail-closed `CLAIMED -> OBSERVED -> EXTRACTED -> COMMITTED` transitions;
- result digests without extracted application content;
- batch finish and deterministic handoff preflights;
- fresh-owner run transfer, resumed batch progression, exhausted-campaign
  completion, and byte-stable terminal handoff;
- terminal heartbeat-retirement readiness that validates the completed handoff
  and owner but does not remove the heartbeat;
- pause, heartbeat, stale-state inspection, and locked lease/owner recovery; and
- rejection of free-form item substitution, usage drift, plan drift, repeated
  writes, and in-flight resume.

Every `READY` preflight result is a control-state directive only. Campaign
control methods still do not invoke a provider or dispatch MCP. The separate
internal synthetic observation runtime accepts only the exact campaign kind,
single planned item key, active claim/session owner, and fixed `list_windows`
call; it reuses Runner discovery, policy, budget, trace, correlation, and MCP
dispatch before calling the existing `OBSERVED` coordinator transition. Its
explicit extension accepts at most 64 Ki characters, produces only a
non-empty-line count as its extraction value, persists no result text in the
campaign ledger or redacted trace, and calls the existing `EXTRACTED`
transition. Its commit extension re-counts the same bounded result, hashes only
canonical `{"window_count":N}` JSON, and calls the existing `COMMITTED`
transition. Its handoff extension derives usage only from Runner state plus a
monotonic elapsed clock, closes through the existing continuation validator,
and writes the existing fixed handoff without changing heartbeat ownership. A
fixed restart/resume extension creates a new Runner run, rebuilds the finished
session from manifest, ledgers, handoff, and heartbeat rather than accepting
task text or an old `BatchSession`, transfers heartbeat ownership, and accepts
only the exhausted resume decision. It makes no provider or MCP call and
exposes no selector, side effect, campaign completion, or heartbeat retirement.
A fixed preparation boundary creates only the exact synthetic manifest,
discovery record, heartbeat, single-item batch, and claim without provider/MCP
ports or a trace. Three fixed CLI commands consume preparation, pre-claimed
execution, and fresh-run resume; provider access is forbidden and only bounded
control/result metadata is printed. Expiry
can release a stale read-only claim to `RETRYABLE`; it
cannot claim the item for another run or authorize action replay.

The incremental implementation sequence is retained in
[archived campaign control-state history](archive/CAMPAIGN_CONTROL_STATE_HISTORY.md).

### Executable batch contract

A future campaign worker must:

1. hold the existing OS run lock at every durable transition;
2. accept only the exact item selected by the validated batch state;
3. perform page/account and stable-item re-observation before extraction;
4. use the existing Agent Runner authority, budgets, trace, and MCP dispatch
   boundary rather than creating a campaign-specific tool path;
5. attest bounded read-only extraction and verified result digest separately;
6. persist measured provider/tool/token/time usage rather than estimates;
7. close and hand off at the first validated batch limit; and
8. stop on uncertainty, challenge, stale ownership, policy denial, or evidence
   drift without replaying a dispatched action.

The first executable slice is one synthetic read-only item through open, claim,
observe, extract, verify, commit, finish, handoff, forced restart, and resume.
Only after that slice retains evidence should the project connect the BOSS
read-only campaign.

The first BOSS-specific internal boundary is now implemented in
`boss_campaign_discovery.py`. It creates only the fixed
`boss_saved_job_read_only` manifest and ingests bounded, complete UIA `link` or
`hyperlink` values. It requires a reviewed same-snapshot BOSS source marker and
then accepts only public job-detail URLs from that same bounded snapshot. Query
fields, page text, company and role content, and full URLs are never persisted;
only stable `boss:job:<id>`
keys enter the ledger. Repeated pages are idempotent, discovery stops before any
batch transition, and wrong-host, injected, truncated, oversized, or drifted
state fails closed. A fixed runtime now dispatches exactly one foreground
`ui_snapshot` through the existing Runner and project MCP, then feeds only the
correlated successful text into this identity boundary. `campaign
prepare-boss-discovery` and `campaign observe-boss-page` expose that narrow
seam without task, URL, page, scope, item, provider, or navigation inputs. The
path has a
[current-contract two-pass on-device result](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md)
with twelve identities and distinct source digests; it still has no automatic
activation or navigation, provider, or semantic job extraction.

`boss_campaign_batch_runtime.py` adds the first worker-side connection without
opening a provider or desktop port. Fixed `campaign start-boss-batch` requires
the current BOSS manifest and at least two complete discovery passes, rejects a
torn ledger, existing heartbeat, handoff, or batch, asks the existing
`BatchCoordinator` for its stable-ordinal plan, caps that plan at twenty items,
creates a five-minute heartbeat, and claims only ordinal 1. It accepts no item,
URL, page, scope, batch, campaign kind, or policy selector. It does not observe,
extract, commit, finish, hand off, resume, or navigate.

`boss_campaign_item_runtime.py` and
`boss_campaign_restart_runtime.py` complete the first bounded processing seam.
Fixed `campaign run-claimed-boss` reconstructs the exact active claim, sends
one foreground `ui_snapshot` through the sole Runner/project-MCP boundary with
provider access forbidden, and requires that the claimed public identity is
present. It persists only the bounded source digest and a canonical
identity-presence digest through `OBSERVED -> EXTRACTED -> COMMITTED`, closes
the batch at the fixed single-call limit, and writes deterministic handoff. Fixed
`campaign resume-boss-batch` accepts only config, campaign ID, and a fresh run
ID; without external ports it reconstructs the exact finished session,
transfers fresh ownership or recovers a proven-stale owner with no item claim,
opens the coordinator-selected resumed plan, and claims its first item. Both
boundaries fail closed on ownership, plan,
handoff, or identity drift. They are offline verified only and do not navigate
or extract role, company, compensation, or other job semantics.


A future worker must close the current run cleanly at a batch boundary, write
`handoff.json`, and start a fresh provider context. A replacement session must
need only the campaign ID and config path, not prior conversation text.

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

Checkpoint replacement alone does not prove that a process is alive. Liveness
classification combines the OS run lock, bounded heartbeat freshness, campaign
manifest, active batch owner, and item leases.

The implemented control plane has a fixed private `heartbeat.json` record, a
pure injected-time `MISSING`/`FRESH`/`STALE` classifier, durable
operator-requested pause/resume, a locked combined stale-run inspector, and
locked owner replacement after stale claims have been released. It has no
worker or timer that updates the heartbeat automatically.

Operator projections may use only validated states:

- `RUNNING`: the worker holds the expected authority and has a fresh heartbeat
  plus any required valid lease;
- `WAITING_APPROVAL`: a durable approval boundary is active;
- `PAUSED`: the operator explicitly paused the campaign;
- `STALE`: heartbeat/ownership evidence is stale and requires reviewed
  recovery;
- `CHALLENGE`: authentication, site, tenant, or other human intervention is
  required; and
- terminal campaign states.

A stale heartbeat is not permission to replay work. Reclaim requires the OS run
lock, current manifest and batch validation, lease inspection, and release of
every stale read-only claim to `RETRYABLE` before owner replacement. The
replacement grants no item or action authority and starts no worker.

## Host-visible completion and mobile notification

> **Status: internal projection implemented and offline verified; no public
> status tool or notification bridge is implemented.** The current eleven-tool
> desktop MCP surface remains unchanged. The projection is a read-only campaign
> module and does not broaden the fixed synthetic seam into a general worker.

Codex and Claude mobile push notifications are host capabilities. The MCP
server must not claim that a whole task is complete, emit a log notification as
if it were a terminal result, or return success immediately after merely
starting background work. A host may finish its turn, and therefore notify the
operator, only after it has read a durable campaign terminal or attention
state.

The future worker boundary should expose one start operation and bounded,
read-only status observation. Names are illustrative until the worker and CLI
surface are reviewed:

~~~text
start_task(...) -> {task_id, status}
get_task_status(task_id) -> durable status projection
wait_task(task_id, timeout_seconds <= bounded_limit) -> same projection
~~~

`wait_task` is bounded long polling, not an indefinitely blocked MCP call. A
timeout returns the current nonterminal projection so the host can decide
whether to call again. The projection contains only fixed control data already
validated under the run lock: task/campaign identity, status, bounded progress
counts, last checkpoint time, and a fixed failure or attention code. It must
not expose raw task text, model prose, screenshots, typed values, credentials,
or arbitrary application content.

Host behavior is fixed by the validated projection:

| Durable projection | Host behavior | Notification meaning |
| --- | --- | --- |
| `RUNNING` | Continue bounded polling; do not end the turn | None |
| `WAITING_APPROVAL`, `PAUSED`, `CHALLENGE` | Stop automatic progress and request operator input | Needs attention; not complete |
| `COMPLETED` | Return the verified final result and end the turn | Completed |
| `FAILED`, `CANCELLED` | Return the fixed terminal outcome and end the turn | Failed or cancelled |
| `UNCERTAIN` / unknown dispatched outcome | Preserve evidence, forbid replay, and end with human-review guidance | Result uncertain; not success |
| stale, malformed, missing, or identity-mismatched state | Fail closed without manufacturing a terminal result | Needs inspection |

Mobile delivery remains outside this repository: ChatGPT Remote or Claude
Remote Control may notify an iPhone when the host turn completes or needs
attention. The repository owns only the durable evidence and status projection
that make that host decision accurate. MCP `notifications/message` is logging,
not the completion protocol.

Acceptance evidence must prove that a fake host never emits a completion event
for `RUNNING`, waiting, stale, malformed, or uncertain state; emits exactly one
terminal event for a validated terminal transition; survives process/context
restart without duplicate completion; and performs zero provider, desktop, or
side-effect calls while polling.

The internal `campaign_host_status` module now covers this contract. It reads
the existing control records under the run lock, fails malformed or unvalidated
terminal state to `NEEDS_INSPECTION`, derives deterministic event IDs from fixed
control fields, and lets a fake host carry emitted IDs across context restart.
Offline tests cover non-completion for running, waiting, stale, malformed, and
uncertain states; exactly-once completion after restart; and byte-for-byte
read-only polling. It still exposes no CLI/MCP status method or mobile delivery.


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

1. **Implemented and offline verified:** strict read-only campaign control
   plane, including manifest, item/batch ledgers, leases, heartbeat, pause,
   stale inspection, deterministic handoff, bounded resume/run transfer, item
   progression, and exhausted-campaign completion.
2. **Implemented and offline verified:** bind one exact claimed synthetic item
   to one fixed `list_windows` observation through the existing Runner boundary,
   persist correlated `OBSERVED`, reduce the bounded result to a non-sensitive
   window count, persist `EXTRACTED`, verify canonical JSON, and persist its
   digest at `COMMITTED`, close with measured usage, and write deterministic
   handoff.
3. **Implemented and offline verified:** start a fresh Runner run without prior
   task text or `BatchSession`, reconstruct the exact finished session from
   durable records, transfer heartbeat ownership, and reach the exhausted
   resume decision without a provider/MCP/desktop path.
4. **Implemented and offline verified:** a bounded resume-only CLI
   exposes the fixed durable fresh-run boundary without task text, item
   selection, provider, or desktop ports.
5. **Implemented and offline verified:** a second fixed CLI command reconstructs
   an exact active synthetic claim and reuses Runner dispatch through handoff
   with provider access forbidden.
6. **Implemented and offline verified:** a third fixed CLI command creates only
   the exact one-item manifest, discovery record, heartbeat, batch, and claim;
   the complete three-command sequence requires no private fixture setup.
7. **Retained on device:** the exact three-command synthetic state,
   redacted-trace, and cost evidence run passed; see
   [Synthetic campaign evidence](SYNTHETIC_CAMPAIGN_EVIDENCE.md).
8. **Implemented and offline verified:** bounded host status projection and
   fake-host polling decisions; ChatGPT/Claude mobile delivery remains outside
   the desktop MCP surface.
9. **Implemented and offline verified:** fixed bounded BOSS public-job identity
   discovery into the existing ledger, with query-token removal and idempotent
   multi-page ingestion before batch execution.
10. **Implemented and on-device verified for two passes:** two fixed CLI
    commands create the BOSS discovery manifest and run foreground observations
    through the sole Runner/project-MCP path with the provider forbidden;
    twelve stable identities were retained under the current contract.
11. **Implemented and offline verified:** a third fixed BOSS command validates
    the complete discovery ledger, opens the exact first maximum-20-item batch,
    creates its bounded heartbeat, and claims only ordinal 1 with no provider,
    MCP, navigation, or selector.
12. **Implemented and offline verified:** a fourth fixed BOSS command verifies
    the exact claimed public identity through one Runner/project-MCP snapshot,
    commits only canonical identity-presence evidence, finishes at the
    single-call boundary, and writes deterministic handoff with no provider.
13. **Implemented and offline verified:** a fifth fixed BOSS command transfers
    the finished session to a fresh zero-port run, opens the exact resumed
    batch, and claims the next coordinator-selected item.
14. **Partial on-device diagnostic retained:** three identity-only commits and
    one clean post-fix stale-owner recovery passed, while two integration
    defects were preserved and fixed; see
    [diagnostic evidence](BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md).
15. **Next:** repeat the bounded multi-item sequence without local correction,
    then add semantic extraction only under a separately reviewed schema and
    run the 100-item evaluation.
16. Run Google Docs 50-section and WeChat draft-only evaluations.
17. Run the cross-application campaign with a fresh-session boundary.
18. Add Wave 2 application coverage: Excel, PDF, Figma/Canva, and Electron.
19. Only then consider resumable side-effect campaigns and higher-complexity
    remote-desktop or modal-tool workloads.
20. Define object-scoped enterprise authority, data classification, transaction
    reconciliation, SLA ownership, and human takeover before Wave 4.
21. Run the synthetic read-only IT incident campaign, then add approved ticket
    updates and notifications one effect tier at a time.
