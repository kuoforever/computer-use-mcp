# Roadmap

> **Status: planning document.** Items below are intentionally separated into
> delivered work, validation gaps, and future design. Do not treat a roadmap
> item as an available runtime feature.

## Delivered foundations

| Milestone | State | Evidence in the repository |
| --- | --- | --- |
| P0 — minimized-window snapshots | Implemented | Windows driver avoids treating a zero-area root as a silently empty tree. |
| P1 — browser snapshot warm-up | Implemented / experimental | Chromium-family UIA snapshots warm up and can return an incomplete-content hint. |
| P2 — human-active yielding | Implemented | Safe-mode actions yield after recent local input. |
| P3 — initial browser-content evaluation | Initial evidence recorded | The design retains flat refs and a 200-node cap pending harder application cases. |
| P5 — pure-logic tests | Implemented | pytest covers core refs, gate behavior, safety/audit, and human activity. |
| P6 — package and documentation hygiene | Partially complete | Public runtime/package metadata is reconciled at 0.1.0 and an offline release preflight uses a constrained child environment, emits UTC/runtime-bound sanitized evidence with independent crash-reconstruction and digest-bound replay E2 gates, and rejects start/end candidate drift; licensing/release policy remains open. |
| P7 — full-control local mode | Implemented | `safe_local` and `full_control_local` are supported modes. |
| P8 — VMware host helper | Experimental | The helper checks/starts an existing VM and can wait for VMware Tools. |

## Next validation priorities

### P0 - repair foreground activation

Fix the reproduced `activate_window` defect before treating approved desktop
actions as reliable. The driver must attach the caller, foreground, and target
input threads as required, release every attachment in `finally`, restore a
minimized target, and verify the resulting foreground HWND. Add pure ordering
tests plus the isolated regression matrix in [E4 smoke](E4_SMOKE.md).

### P1 - long-running campaign foundation

Implement the read-only campaign manifest, append-only item ledger, bounded
batches, and deterministic handoff described in
[Long-running tasks](LONG_RUNNING_TASKS.md). The first target is a 100-item BOSS
saved-job review across multiple provider contexts and at least one forced
restart. Conversation history must not be required for continuation.

The initial private control-state and planning foundations are implemented:
strict campaign manifest validation, a RunLock-bound append-only
item-transition reducer, atomic persistence, a fixed handoff projection, a
pure batch policy/selector with deterministic limit reasons, and a bounded
`batches.jsonl` lifecycle ledger. A fixed, RunLock-bound heartbeat record can
also advance monotonically for one run, and a pure inspector reports missing,
fresh, or stale control state without claiming liveness. No timer or combined
OS-lock/item-lease classifier uses it. The manifest can durably transition
between `RUNNING` and `PAUSED` under the run lock, but resume does not start
work. A combined locked inspector can identify stale control state only after
checking manifest state, heartbeat freshness, claim expiry, and run ownership;
an explicit locked recovery may replace only the stale heartbeat owner after
all claims have left `CLAIMED`. The fixed handoff now projects distinct
directives for running, paused, challenged, completed, and failed manifests.
Its reader rejects schema, status, count, or cursor drift against current
durable state. The foundation has no batch runner, CLI command, provider, MCP,
or desktop connection. A read-only resume preflight can now require a valid
resumable handoff, fresh matching heartbeat, idle batch ledger, and no current
claims without starting work. A pure resume planner can then apply the bounded
batch selector without writing `STARTED`; the coordinator may persist
`STARTED` only for that exact nonempty `READY` plan. It still performs no item
operation. The opened batch may now durably claim only the first item from its
exact recomputed plan after rechecking the running manifest, fresh matching
heartbeat, active batch, absence of another claim, and plan equality. This is
still control-state scaffolding: no item observation, provider, MCP, desktop
action, runner, or CLI is connected. Deterministic item-operation progression
remains the next step. A read-only claimed-item preflight now revalidates the
running campaign, active batch/run, fresh heartbeat, unique owned claim, and
lease before returning fixed page/account and item-identity re-observation
directives. It performs no observation and writes no `OBSERVED` transition.
Resume preflight now also blocks durable `OBSERVED` or `EXTRACTED` items as
`ITEMS_IN_FLIGHT`; it cannot mistake those incomplete boundaries for an idle
campaign merely because no current `CLAIMED` lease remains.
A locked persistence helper can now advance one exact claimed item to
`OBSERVED` only after explicit page/account and item-identity attestations and
a fresh re-run of the claimed-item preflight. It does not perform observation,
extraction, provider work, MCP dispatch, desktop actions, runner, or CLI work.
An observed-item extraction preflight now checks the active batch/run, fresh
heartbeat, unique in-flight item, and item ownership before returning a fixed
bounded read-only extraction directive. It remains read-only and does not write
`EXTRACTED` or authorize side effects.
The item-progress helper may now append a fixed `EXTRACTED` boundary only after
an exact bounded-read-only-extraction confirmation and a fresh extraction
preflight. It stores no application content and still has no provider, MCP,
desktop, runner, CLI, or side-effect connection.
An extracted-item commit preflight now revalidates the active batch/run, fresh
heartbeat, unique in-flight item, and item ownership before returning fixed
result-verification and digest/result-code preparation directives. It remains
read-only and does not write `COMMITTED`, advance the cursor, or connect a
provider, MCP, desktop action, runner, CLI, or side effect.
The item-progress helper may now append a fixed `COMMITTED` boundary only after
an exact result-verification confirmation, a valid SHA-256 content digest, and
a fresh commit preflight. The atomic ledger append advances the derived cursor
without rewriting handoff state; it stores no result content and still has no
provider, MCP, desktop, runner, CLI, or side-effect connection.
A read-only batch-continuation preflight now validates the committed plan
prefix, measured completed count, stable next-item order, active ownership,
fresh heartbeat, absence of in-flight work, and every hard limit before naming
the exact next planned item. It does not claim that item, close the batch, or
connect a provider, MCP, desktop action, runner, CLI, or side effect.
The coordinator may now append a bounded `CLAIMED` transition for only that
exact next item after re-running the continuation preflight. It requires a
nonempty committed prefix and fails closed on repeated calls, limits, drift,
stale control state, or invalid leases; no observation, execution, provider,
MCP, desktop, runner, CLI, or side-effect path is connected.
A continuation-validated finish helper may now append `FINISHED` only for a
reached hard limit or a fully committed original plan, persisting the exact
fixed stop code and bounded measured counters. It rejects ready or in-flight
work, drift, stale ownership, and repeated closure, and does not write handoff
state or connect a provider, MCP, desktop action, runner, CLI, or side effect.
A read-only finished-batch handoff preflight now revalidates the terminal
batch/run record, heartbeat, committed prefix, absence of in-flight work,
measured counters, stop reason, and next ordinal before returning one fixed
handoff-write directive. It does not write or read handoff state, resume work,
or connect a provider, MCP, desktop action, runner, CLI, or side effect.
The coordinator may now re-run that preflight and atomically write the existing
fixed handoff projection for the finished run. Ledger-derived counts and next
ordinal are preserved; blocked state never creates or replaces the file, and
the helper does not resume work, open a batch, or connect a provider, MCP,
desktop action, runner, CLI, or side effect.
A read-only clean run-transfer preflight now checks the validated finished
handoff, current fresh heartbeat owner, distinct replacement run ID, and exact
injected transfer time before returning one fixed heartbeat-owner replacement
directive. It does not mutate heartbeat state, resume work, open a batch, or
connect a provider, MCP, desktop action, runner, CLI, or side effect.
The coordinator may now re-run that preflight and atomically replace only the
finished heartbeat owner. All other durable campaign state remains unchanged;
blocked or repeated calls do not write, and success does not resume work, open
a batch, or connect a provider, MCP, desktop action, runner, CLI, or side
effect.
A read-only post-transfer resume preflight may now bind the exact finished
batch and handoff provenance to the replacement owner and its next bounded
stable item plan. It returns only a fixed exact-batch-open directive and does
not write `STARTED`, claim an item, or connect a provider, MCP, desktop action,
runner, CLI, or side effect.
The coordinator may now re-run that post-transfer preflight and persist one
exact resumed `STARTED` record with the unchanged bounded plan. Blocked,
empty, drifted, or repeated calls append nothing, and success still does not
claim an item or connect a provider, MCP, desktop action, runner, CLI, or side
effect.
A read-only first-claim preflight may now bind that active replacement batch
to its fresh heartbeat owner, unchanged plan, exact first stable item, next
attempt, and bounded lease expiry. It returns only a fixed claim directive and
does not write `CLAIMED` or connect a provider, MCP, desktop action, runner,
CLI, or side effect.
The coordinator now re-runs that preflight before persisting the exact first
`CLAIMED` transition, using its validated item identity, attempt, and lease
expiry. Blocked or repeated calls do not change the ledger, and success still
does not connect a provider, MCP, desktop action, runner, CLI, or side effect.
A read-only coordinator bridge may now feed the resumed session's exact first
planned item into the existing claimed-item re-observation preflight, removing
free-form item selection at that boundary. It does not write `OBSERVED`,
perform observations, or connect a provider, MCP, desktop action, runner, CLI,
or side effect.
After exact page/account and item-identity attestations, the coordinator may
now re-run that session-bound preflight and persist only the fixed `OBSERVED`
boundary for the resumed first item. Missing attestations, blocked state, or
repetition does not write, and no observation, extraction, provider, MCP,
desktop, runner, CLI, or side-effect path is connected.
A read-only coordinator bridge may now feed that resumed session's exact first
planned item into the existing observed-item extraction preflight. It returns
only the bounded read-only extraction directive, does not accept a free-form
item key, and does not extract content or write `EXTRACTED`.
After exact bounded-read-only-extraction confirmation, the coordinator may now
re-run that session-bound preflight and persist only the fixed `EXTRACTED`
boundary for the resumed first item. Missing confirmation, blocked state, or
repetition does not write; no application content, provider, MCP, desktop,
runner, CLI, or side-effect path is connected.
A read-only coordinator bridge may now feed that resumed session's exact first
planned item into the existing extracted-item commit preflight. It returns only
fixed result-verification and digest/result-code preparation directives, does
not accept a free-form item key, and does not inspect content or write
`COMMITTED`.
After exact bounded-result verification and SHA-256 digest preparation, the
coordinator may now re-run that session-bound preflight and persist only the
fixed `COMMITTED` boundary for the resumed first item. Invalid input, blocked
state, or repetition does not write; no result content, provider, MCP, desktop,
runner, CLI, or side-effect path is connected.
The committed resumed prefix now feeds the existing read-only continuation
preflight directly. Replacement-run commit count and run-local measured usage
must match before it identifies the exact next planned item; no claim, provider,
MCP, desktop action, runner, CLI, or side effect occurs.
The coordinator may now re-run that preflight and persist the bounded `CLAIMED`
transition for only the resumed session's exact next planned item. Repetition,
usage drift, stale state, or in-flight work does not write, and no observation,
provider, MCP, desktop action, runner, CLI, or side-effect path is connected.
A read-only coordinator bridge may now derive that exact continued claim from
the replacement run's committed prefix and matching run-local usage, then feed
it into the existing claimed-item re-observation preflight. It accepts no item
key, writes no `OBSERVED` boundary, and performs no observation or runtime work.
After exact page/account and item-identity attestations, the coordinator may now
re-run that continued-item preflight and persist only its fixed `OBSERVED`
boundary. Missing attestations, usage drift, blocked state, or repetition does
not write, and no observation, extraction, provider, MCP, desktop, runner, CLI,
or side-effect path is connected.
A read-only coordinator bridge may now derive that exact continued observation
from the replacement run's committed prefix and matching run-local usage, then
feed it into the existing bounded extraction preflight. It accepts no item key,
extracts no content, writes no `EXTRACTED`, and starts no runtime work.
After exact bounded-read-only-extraction confirmation, the coordinator may now
re-run that continued-item preflight and persist only its fixed `EXTRACTED`
boundary. Missing confirmation, usage drift, blocked state, or repetition does
not write, and no application content, provider, MCP, desktop, runner, CLI, or
side-effect path is connected.
A read-only coordinator bridge may now derive that exact continued extraction
from the replacement run's committed prefix and matching run-local usage, then
feed it into the existing commit preflight. It accepts no item key, inspects no
content, writes no `COMMITTED`, and starts no runtime work.
After exact bounded-result verification and SHA-256 digest preparation, the
coordinator may now re-run that continued-item preflight and persist only its
fixed `COMMITTED` boundary. Invalid input, usage drift, blocked state, or
repetition does not write, and no result content, provider, MCP, desktop,
runner, CLI, or side-effect path is connected.
The fully committed resumed plan now reaches the existing continuation
preflight's exact terminal state: `PLAN_COMPLETE` when no limit fired, otherwise
`LIMIT_REACHED` with its fixed reason. Both paths are read-only, identify no next
item, and do not write `FINISHED` or start runtime work.
The coordinator may now re-run either resumed terminal preflight and persist one
exact `FINISHED` batch record with its fixed stop code and measured run-local
counters. Repetition or drift does not write, no handoff is created, and no
provider, MCP, desktop action, runner, CLI, or side-effect path is connected.
The finished resumed batch now feeds the existing read-only handoff preflight,
which revalidates exact ownership, stop code, counters, committed prefix,
heartbeat, and next ordinal before returning only the fixed handoff-write
directive. It does not modify handoff or runtime state.
The coordinator may now re-run that preflight and atomically replace the prior
handoff with the exact finished replacement run and current fixed projection.
Repeated valid writes are byte-stable; manifest, ledgers, heartbeat, and batch
state remain unchanged, and no runtime path is connected.

After the BOSS baseline, run the Google Docs long-document and WeChat draft-only
cases, then the cross-application campaign in
[Application evaluation matrix](APPLICATION_EVALUATION_MATRIX.md).
Expand to Excel, PDF, Figma/Canva, one Electron collaboration client, and the
Douyin real-time-media/infinite-feed case only after the Wave 1 campaign and
observation measurements are reproducible. The Douyin case additionally waits
for bounded OCR or image observation and timestamped media-state evidence.
Remote Desktop, system-dialog boundaries, legacy UI, and modal GPU applications
remain later waves.

### P1 - bounded multi-source observation

The BOSS live probe established that important static text may be absent from
the interactive UIA tree. Implement the source envelope and escalation rules in
[Observation contract](OBSERVATION_CONTRACT.md), beginning with bounded OCR or
document text and region-scoped image capture. Measure the result using
[Token efficiency](TOKEN_EFFICIENCY.md).

### P1 - passive operator progress viewer

Implement the checkpoint-to-view-model reducer and non-activating Windows
overlay from [Operator progress viewer](PROGRESS_VIEWER.md). Do not display
active elapsed time, screenshot count, token coverage, or liveness as known
until the checkpoint/campaign schemas expose those facts.

### Agent Host remaining-work ledger

The following items are intentionally unfinished. They must remain visible in
release notes and cannot be inferred complete from offline CI:

| Item | Current boundary | Completion evidence |
| --- | --- | --- |
| OpenAI and Claude E3 | Opt-in tests exist; no credentialed evidence is retained | Both providers pass the harmless fake-MCP cycle with reviewed model IDs |
| Isolated E4 | Four-cell runbook exists; no isolated desktop evidence is recorded | Both providers pass read-only and one approved low-risk action with post-action observation |
| E5 release regression | Canonical workflow, crash-reconstruction, and OpenAI stateless-replay manifests are frozen and enforced through offline tests/CI; crash reconstruction and replay also produce independent preflight/CI evidence, while isolated evidence is pending | Reviewed isolated successful and failure traces are rerun after policy/schema/adapter changes |
| Release approval | Offline preflight is implemented and must pass on a clean candidate; human gates remain | Completed [release evidence](RELEASE_EVIDENCE.md), license review, version/changelog, CI, and human approval |
| Broader resume | Controlled recovery can chain 1-4 reviewed read-only calls under one run lock, with an atomic intent/completion pair for every call. A completed final provider response can be terminalized locally with zero external calls. Provider-requested actions are correlation-checked, terminalized as a fixed failure, and deleted without dispatch; completed side effects issue one synthetic `ui_snapshot` and stop. The frozen E2 matrix proves zero action replay | Keep uncertain dispatches and pending side effects permanently non-executable; require a separate design before raising the four-step cap or resuming action authority |
| Token-aware context | Event-count reduction, exact request-byte gates, cumulative provider-reported input-token cutoff, conservative provider/model pre-request enforcement, correlated OpenAI recovery token-state restoration, Claude-only oldest-complete-group packing, canonical OpenAI request-contract v3 digest binding, exact initial-input and ordered provider-output persistence, explicit portable encrypted-reasoning requests, and an explicit digest-bound OpenAI stateless-replay compiler for read-only recovery | Tokenizer-specific calibration, safe semantic compression, and broader replay/compaction policy beyond the explicit recovery boundary |
| Planner-Executor | Strict TaskPlan compilation/persistence, Planner adapters, fresh-call preflight/session, observation runtime/reconciliation, and bounded final-response compilation/adapters/WAL are implemented. The internal runtime orders one tool-free final call across prepared WAL, final-step `in_progress`, dispatch intent, correlated completion, host budget/ledger consumption, final-step CAS, terminal trace, and ordinary observation-WAL cleanup. Final WAL v2 plus a pure local preflight now revalidate and reconstruct exact completed-final crash evidence without writes or external ports. The runtime never enters normal provider continuation/recovery and is not connected to CLI | Apply the prepared completed-final reconciliation through separately reviewed idempotent CAS/terminal cleanup before CLI wiring; keep dispatch intent non-replayable, output untrusted, the four-step cap, and unchanged action boundaries. Side-effect plan execution remains a separate review |

If E3 or E4 is waived, the artifact remains an experimental prerelease. Its
release notes must say `E3 NOT RUN` and/or `E4 NOT RUN`; it must not be called a
complete safety MVP or production-ready.

### 1. Validate real multi-process application gating

Exercise an application with renderer/helper processes and confirm that its
foreground owner chain is correctly accepted or rejected by the allowlist.
Record both allow and deny paths without widening the default allowlist.

### 2. Expand browser-content testing carefully

Test dynamic and content-heavy pages for:

- Snapshot truncation above the 200-node cap.
- Duplicate role/name ambiguity.
- Stability after the current warm-up strategy.
- Whether flat refs and `find()` remain adequate.

The observed static-content gap justifies a bounded text/OCR path. Do not add
hierarchy, parent refs, or text-run merging until a case specifically requires
them; follow the shared observation envelope rather than returning unbounded
page text.

### 3. Define a real multi-monitor model

Before advertising support, decide and validate:

- Virtual-desktop capture bounds.
- Per-monitor DPI conversion.
- Region capture offsets.
- Cross-monitor coordinate clicks and window placement.

### 4. Finish release policy

The source distribution uses Apache-2.0. Reconcile public version sources,
review dependency and artifact redistribution terms for each release, and add
release automation only after the supported behavior is stable.

## Future architecture

### Isolated workers

The preferred direction for genuine background work is an independent VM,
session, display server, or machine. The short-term VMware helper remains
host-side only. Future work must first establish reliable in-guest MCP startup,
then define host-to-guest transport and lifecycle orchestration.

### Additional platform drivers

macOS AX and Linux AT-SPI drivers can target the existing Driver Contract after
the Windows baseline is sufficiently proven. They are not placeholders for
current support.

### Hidden Windows desktops

`CreateDesktop` / `SwitchDesktop` can be investigated as a research route,
but they are not the preferred isolation strategy and must not replace real
end-to-end validation.

### Enterprise workflow layer

After Wave 1-3 application mechanics are reproducible, define the planned E7
enterprise boundary before connecting the Agent to business systems. This layer
adds stable business-object identities, object- and field-scoped authority,
tenant isolation, data classification, maker-checker approval, SLA ownership,
and saga-style cross-system reconciliation. The first evaluation is the
synthetic IT incident workflow in
[Application evaluation matrix](APPLICATION_EVALUATION_MATRIX.md); production
records and credentials are outside the default evaluation boundary.

## Milestone discipline

Keep changes small and observable:

~~~powershell
git status --short --branch
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts
git diff --check
~~~

When a change touches a real desktop path, run the matching smoke only with
operator approval. Do not combine unrelated perception, foreground, and safety
changes in one milestone.
