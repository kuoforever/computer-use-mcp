# Roadmap

> **Status: planning document.** Items below are intentionally separated into
> delivered work, validation gaps, and future design. Do not treat a roadmap
> item as an available runtime feature. Use
> [Capability status](CAPABILITY_STATUS.md) for the current evidence dashboard.

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

### P0 - validate repaired foreground activation

The reproduced `activate_window` defect has been repaired in the Windows
driver. The implementation attaches the caller to the required foreground and
target input queues, releases successful attachments in reverse order from
`finally`, restores minimized targets, and verifies the final foreground HWND.
Pure tests cover ordering, cleanup, idempotence, minimized windows, native-call
failure, and failed postconditions.

The isolated Windows activation matrix and all four reviewed provider cells
have passed with [retained E4 evidence](E4_EVIDENCE.md). A subsequent
[bounded on-device BOSS home observation](BOSS_EVIDENCE.md) activated the real
Chrome target through the project stdio path and retained a bounded UIA result.
The later [BOSS OCR result](BOSS_OCR_EVIDENCE.md) recovered a static tab missing
from UIA and retained a separate interested-jobs observation. Together they
close the narrow post-repair and observation vertical-slice gates. They do not
imply application acceptance, broader model compatibility, or release
readiness. Continue with a bounded multi-item read-only BOSS campaign and
restart evidence.

### P1 - connect the long-running campaign runtime

> **Current boundary:** the private campaign control plane is implemented and
> offline verified. It has strict manifests, item and batch ledgers, leases,
> heartbeats, pause/stale inspection, deterministic handoff, bounded resume,
> read-only item progression, run transfer, campaign completion, and a
> read-only terminal heartbeat-retirement preflight. One internal fixed
> synthetic item now binds an existing claim/session to one `list_windows`
> observation through the sole Runner dispatch boundary, persists a correlated
> `OBSERVED` transition, reduces the bounded text to a non-sensitive window
> count, persists `EXTRACTED`, verifies canonical JSON, and persists its digest
> at `COMMITTED`, closes the batch with measured Runner usage, writes the
> existing deterministic handoff, and transfers heartbeat ownership to a fresh
> Runner run that reconstructs the finished session from durable records and
> reaches the expected exhausted resume decision. It has no general campaign
> worker, provider turn, side effect, campaign completion, or automatic
> terminal heartbeat removal. Three fixed CLI commands prepare the exact
> one-item synthetic claim, execute it through handoff, and enter the durable
> fresh-run resume half. Preparation opens no external port or trace; execution
> uses the configured MCP child with a fail-closed provider guard. None accepts
> task text, item selection, campaign-kind selection, or action authority.

The complete three-command sequence is offline verified without private fixture
setup and has [retained on-device state, redacted trace, and cost evidence](SYNTHETIC_CAMPAIGN_EVIDENCE.md).
Preserve the existing Runner dispatch site, budgets, trace, and fail-closed
result semantics; do not add a second MCP path, accept a free-form item
selector, replay an uncertain action, or connect side-effecting work.

The bounded read-only terminal-status projection is now implemented internally
and offline verified. A fake Codex/Claude host continues through `RUNNING`,
requests attention for waiting, stale, malformed, or uncertain state, and emits
one digest-identified completion only for validated terminal evidence. Polling
is byte-for-byte read-only and adds no provider/MCP/desktop path or public
desktop tool. Mobile push delivery remains owned by ChatGPT Remote or Claude
Remote Control. The next gate is the bounded multi-item BOSS restart run.

The first application increment now connects the identity boundary to the sole
Runner dispatch path. Two fixed CLI commands create only the reviewed discovery
manifest and execute one foreground `ui_snapshot` through the project MCP. The
result must contain bounded complete link values on the reviewed BOSS
interested-jobs source; URL query data is stripped, stable public job keys are
persisted idempotently, and discovery is refused after batch execution begins.
The commands accept no task, URL, page, scope, item selector, provider, or
navigation authority. The fixed path now has
[one retained on-device page result](BOSS_CAMPAIGN_DISCOVERY_EVIDENCE.md) with
seven stable public job keys and no provider or side effect.

Repeated observation is now bounded by the durable discovery-pass ledger
described in [Long-running tasks](LONG_RUNNING_TASKS.md). The observation
command still accepts no page, URL, or selector: progression happens only
because the operator moved the observed foreground, and the boundary records
that a distinct source was observed, refuses an unchanged source, bounds the
campaign to twenty passes, and fails closed when a pass claims items that were
never persisted. A fresh run reconstructs pass count and last source digest
from durable records alone. This is offline evidence only; the BOSS discovery
policy and schema digests were advanced for the change, so the earlier retained
one-page result does not transfer to the new contract.

Next run a multi-page on-device discovery sequence against the reviewed BOSS
source and retain its progression evidence, then the first 100-item read-only
BOSS campaign across multiple provider contexts and at least one forced
restart. Retain committed-item, token, retry, recovery, and takeover evidence.

The prior per-increment chronology is preserved in
[archived campaign control-state history](archive/CAMPAIGN_CONTROL_STATE_HISTORY.md);
the normative state and handoff rules remain in
[Long-running tasks](LONG_RUNNING_TASKS.md).


### P1 - bounded multi-source observation

The BOSS live probe established that important static text may be absent from
the interactive UIA tree. Bounded region OCR and bounded region image capture
now implement the OCR and image rungs of
[Observation contract](OBSERVATION_CONTRACT.md); `capture_region` is offline
verified and now has a retained synthetic
[on-device result](CAPTURE_REGION_EVIDENCE.md). Bounded UIA document text is
implemented, offline verified, and has a retained
[on-device result](DOCUMENT_TEXT_EVIDENCE.md). Deltas and any image scope beyond
one explicit primary-display rectangle remain unimplemented. Next exercise the
implemented ladder inside the bounded multi-item restart campaign and measure
each source using [Token efficiency](TOKEN_EFFICIENCY.md).

### P1 - operator presence and progress foundation

The checkpoint-to-view-model reducer and the passive non-activating window
shell, atomic live checkpoint polling, independent-run grouping, and bounded
campaign progress from
[Operator progress viewer](PROGRESS_VIEWER.md) are implemented and offline
verified (delivery steps 1-5); the window is drawn over an injectable native
surface with no focus-taking call, and both its non-activation and real
checkpoint transition path have retained on-device evidence in
[the window](PROGRESS_WINDOW_EVIDENCE.md) and
[poller](PROGRESS_POLLER_EVIDENCE.md) records; the updated poller result includes
a real two-run regrouping after one terminal transition, 400/400 paired
checkpoint/campaign publishes through a held execution lock, and a campaign
moving from Active to Attention after pause. A bounded primary-display
click-through computer-use presence surface is also implemented and
[desktop verified](PRESENCE_WINDOW_EVIDENCE.md), including capture affinity,
DPI geometry, reduced motion, and release/E-stop teardown. A fail-silent,
default-off Host coordinator now projects atomically persisted phases for the
ordinary `run`/`resume` lifecycle and latches off on MCP E-stop, human activity,
terminal state, or cleanup. The
[on-device lifecycle result](PRESENCE_LIFECYCLE_EVIDENCE.md) now retains an
ordinary foreground-safe transition, one-HWND reuse, terminal teardown, and a
synthetic MCP E-stop boundary. Fake-only, digest-bound Decision Card models and
choice validation from [Operator experience](OPERATOR_EXPERIENCE.md) are now
implemented without an approval or dispatch port. An opt-in two-choice Win32
card now connects exact-effect selection through the existing `ApprovalPort`;
the Runner yields first and rechecks every Host digest before its unchanged
dispatch boundary. Its focus, approval, timeout-denial, sole-dispatch, and
foreground-restoration path now has [bounded on-device evidence](DECISION_CARD_WINDOW_EVIDENCE.md).
Next add richer bounded business alternatives without widening approval or
dispatch authority. Do not display
active elapsed time, screenshot count, token coverage, or liveness as known
until the checkpoint/campaign schemas expose those facts.

Presence must follow validated Host phases, avoid focus/input interception,
stay out of Agent observation content, support reduced motion and DPI changes,
and disappear on E-stop or authority release. After the passive surfaces are
stable, implement fake-only Decision Card view models before connecting a
focus-taking card to the existing ApprovalPort. Options and trade-offs remain
advisory until a fresh bound Host decision passes every ordinary action gate.

### Showcase gate - universal GUI complete-product demo

After the narrower application, campaign, observation, operator, and enterprise
authority gates retain executable evidence, run the chaptered
[Universal GUI demo](UNIVERSAL_GUI_DEMO.md). One campaign covers all distinct
mechanism families across browser/native/document/data, media/design,
nested/legacy/system, and enterprise workflows. It must include deterministic
fault injection, provider-context rotation, restart recovery, presence/progress
UI, one multi-option Decision Card, and a versioned token-cost baseline.

This is a final integration and presentation gate, not the next runtime
increment. A partial or edited showcase must preserve skipped, failed,
challenged, uncertain, and human-completed states in its retained report.

### Agent Host remaining-work ledger

The following items are intentionally unfinished. They must remain visible in
release notes and cannot be inferred complete from offline CI:

| Item | Current boundary | Completion evidence |
| --- | --- | --- |
| OpenAI and Claude E3 | [Both providers passed](E3_EVIDENCE.md) the ordinary and exact bounded `plan run` fake-MCP cases with reviewed model IDs. The record is model-scoped, preserves the historical Sonnet 5 failure, and retains an exact-repair-commit pass for strict signed/redacted reasoning-block continuation | Completed for the bounded E3 definition; proceed to isolated E4 without inferring all-model or desktop compatibility |
| Isolated E4 | [Windows activation and all four provider cells passed](E4_EVIDENCE.md) with one approved action, mandatory post-action observation, and zero automatic retries | Completed for the reviewed VM, models, and exact repair tree; proceed without inferring application or release readiness |
| E5 release regression | Canonical workflow, crash-reconstruction, and OpenAI stateless-replay manifests are frozen and enforced through offline tests/CI; crash reconstruction and replay also produce independent preflight/CI evidence, while isolated evidence is pending | Reviewed isolated successful and failure traces are rerun after policy/schema/adapter changes |
| Release approval | Offline preflight is implemented and must pass on a clean candidate; human gates remain | Completed [release evidence](RELEASE_EVIDENCE.md), license review, version/changelog, CI, and human approval |
| Broader resume | Controlled recovery can chain 1-4 reviewed read-only calls under one run lock, with an atomic intent/completion pair for every call. A completed final provider response can be terminalized locally with zero external calls. Provider-requested actions are correlation-checked, terminalized as a fixed failure, and deleted without dispatch; completed side effects issue one synthetic `ui_snapshot` and stop. The frozen E2 matrix proves zero action replay | Keep uncertain dispatches and pending side effects permanently non-executable; require a separate design before raising the four-step cap or resuming action authority |
| Token-aware context | Event-count reduction, exact request-byte gates, cumulative provider-reported input-token cutoff, conservative provider/model pre-request enforcement, correlated OpenAI recovery token-state restoration, Claude-only oldest-complete-group packing, canonical OpenAI request-contract v3 digest binding, exact initial-input and ordered provider-output persistence, explicit portable encrypted-reasoning requests, and an explicit digest-bound OpenAI stateless-replay compiler for read-only recovery | Tokenizer-specific calibration, safe semantic compression, and broader replay/compaction policy beyond the explicit recovery boundary |
| Operator experience | The console remains default; passive progress/presence are retained; an opt-in focus-taking Win32 Decision Card now yields Agent authority and routes one exact-effect Yes/No choice through the existing ApprovalPort. Close, timeout, failure, malformed choice, expiry, and six Host digest drifts deny; Runner/MCP dispatch remains singular. Richer business alternatives remain planned | Retain native focus, timeout, restoration, and zero-dispatch denial evidence; then add richer bounded alternatives and provenance without batch/global approval or a second dispatch path |
| Host completion notification | Internal bounded projection and fake-host decisions are offline verified: running keeps polling, attention/uncertain states never complete, validated terminal events deduplicate across restart, and repeated polling is read-only. No public status tool, generic worker, notification bridge, or mobile adapter exists | Retain application evidence before reviewing any public status surface; keep mobile delivery host-owned and provider/MCP/desktop calls absent from polling |
| Planner-Executor | Strict TaskPlan compilation/persistence, dual-provider Planner and final adapters, fresh-call preflight/session, observation runtime/reconciliation, final WAL, and completed-final local reconciliation are implemented. `plan run` now composes exactly one host-scoped plan request, one to four observations through the sole Runner boundary, and one stateless tool-free final response. It exposes no tool selector, side effect, ordinary provider continuation, approval option, or alternate MCP path. The complete path is offline fake-verified, and [dual-provider E3 is retained](E3_EVIDENCE.md); the Agent Host E4 record does not constitute a separate Planner / Executor desktop pass | Retain a separately scoped desktop result only when warranted; keep dispatch intent non-replayable, output untrusted, the four-step cap, and unchanged action boundaries. Side-effect plan execution remains a separate review |

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

An Android device driver (ADB transport, `uiautomator dump` for structure,
`screencap`/scrcpy for capture, OCR fallback) targets the same contract and is
sequenced the same way — after the Windows vertical is application-verified, not
before. It first requires the additive contract v1.1 `swipe` / `long_press`
primitive and a deliberate second-coordinate-domain decision. Because a phone or
emulator is a machine with independent input and capture authority, it doubles
as an isolated-worker target for the mobile-first Wave 1 applications (BOSS,
WeChat). See [ADR-008](adr/008-android-device-driver-behind-driver-contract.md).
This is distinct from the roadmap's existing "mobile" work, which is a
notification sink, not a control target.

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

### Continual learning and verified experience evolution

After normalized campaign outcomes and complete cost vectors are reliable,
implement the staged [continual-learning architecture](CONTINUAL_LEARNING.md).
Begin with quarantined factual-memory suggestions, then versioned procedural
candidates, isolated replay, held-out evaluation, explicit promotion, and
rollback. Only after those gates pass may the Host produce shadow strategy
recommendations or select among already approved, equivalent low-risk
procedures using measured outcome and cost history.

Do not treat trace retention, explicit memory, model replanning, provider data
sharing, or one successful replay as reinforcement learning. Online
model-weight updates, uncontrolled exploration, automatic authority changes,
and learning challenge bypasses remain outside the runtime boundary.

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
