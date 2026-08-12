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

## Standing first-release boundary

The first release boundary was defined as an Experimental Windows Agent MVP:
installed first-run configuration, one public read-only Desktop Ask path,
current-candidate real document-aware evidence, one model-driven
public-browser-to-disposable-Word workflow, and a versioned GitHub release
artifact. The exact active batch and ordered PR map live only in
[Project status](../PROJECT_STATUS.md).

That standing MVP boundary does not depend on the 100-item BOSS gate, complete
Google Docs or WeChat application coverage, the Universal GUI final showcase,
additional platforms, hierarchical control, continual learning, or Multi-Agent
work.
H1-H8 and L0-L4 have since been implemented at their bounded offline or
injected-runtime scopes; they do not complete Application Coverage Set A, the
Formal Demo, the Universal GUI final showcase, Multi-Agent operation, E4, or
release acceptance.

## Separate planned programs

The following programs have different owners and acceptance. None is activated
by this roadmap; [Project status](../PROJECT_STATUS.md) alone may authorize one
bounded item.

| Program | Owner and current boundary | Relationship |
| --- | --- | --- |
| Formal Demo v1 | [Formal Demo v1](FORMAL_DEMO_V1.md) owns the selected independent Agent Console and GitHub Issues -> PDF -> disposable Excel -> disposable Word -> test-account email-draft story. The internal offline v1 intent/scenario/profile/Scope contracts and a typed local disclosure/exact-`COMPILE` per-gate permit are implemented; no serialized gate loader, Console, provider intent call, launcher, executable adapter, durable composition, or complete evidence exists | Product-demo delivery program. It may reuse only separately verified mechanisms and cannot inherit evidence from the fixed public-web-word workflow |
| Application coverage | [Application evaluation matrix](APPLICATION_EVALUATION_MATRIX.md) owns independent application cases. BOSS, Google Docs, WeChat, and their legacy cross-application case form representative Coverage Set A, not the Formal Demo story or product-priority order | Evidence program. Each case advances only through its own provider, desktop, application, safety, and recovery gates |
| Universal GUI final showcase | [Universal GUI final showcase](UNIVERSAL_GUI_DEMO.md) owns a future chaptered integration and presentation gate | Final showcase only after selected underlying mechanisms retain executable evidence; an edited showcase cannot substitute for Formal Demo or application acceptance |

## Retained validation sequence

This section preserves capability-specific gates and chronology. It is not the
active tracker; [Project status](../PROJECT_STATUS.md) alone owns the current
item and exact next action.

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
> terminal heartbeat-retirement preflight plus an exact idempotent removal
> mutation. One internal fixed
> synthetic item now binds an existing claim/session to one `list_windows`
> observation through the sole Runner dispatch boundary, persists a correlated
> `OBSERVED` transition, reduces the bounded text to a non-sensitive window
> count, persists `EXTRACTED`, verifies canonical JSON, and persists its digest
> at `COMMITTED`, closes the batch with measured Runner usage, writes the
> existing deterministic handoff, and transfers heartbeat ownership to a fresh
> Runner run that reconstructs the finished session from durable records and
> reaches the expected exhausted resume decision. This fixed seam has no
> provider turn, side effect, application-worker selection, campaign
> completion, or automatic terminal heartbeat removal. Three fixed CLI commands
> prepare the exact one-item synthetic claim, execute it through handoff, and
> enter the durable fresh-run resume half. Preparation opens no external port or
> trace; execution
> uses the configured MCP child with a fail-closed provider guard. None accepts
> task text, item selection, campaign-kind selection, or action authority.

> The separate generic application-campaign worker now consumes the terminal
> preflight: an exhausted fresh resume completes the manifest, writes the
> terminal handoff, and retires the finalizer-owned heartbeat. This does not
> broaden the fixed synthetic runtime or establish live-application evidence.

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
Remote Control. The later BOSS restart and semantic increments below supersede
that earlier gate.

The first application increment now connects the identity boundary to the sole
Runner dispatch path. Two fixed CLI commands create only the reviewed discovery
manifest and execute one foreground `ui_snapshot` through the project MCP. The
result must contain bounded complete link values on the reviewed BOSS
interested-jobs source; URL query data is stripped, stable public job keys are
persisted idempotently, and discovery is refused after batch execution begins.
The commands accept no task, URL, page, scope, item selector, provider, or
navigation authority. The superseded contract retains
[one historical on-device page result](BOSS_CAMPAIGN_DISCOVERY_EVIDENCE.md)
with seven stable public job keys. The current discovery-pass contract now also
has a [two-pass on-device result](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md) with
twelve stable public job keys, distinct source digests, and no provider or side
effect.

Repeated observation is now bounded by the durable discovery-pass ledger
described in [Long-running tasks](LONG_RUNNING_TASKS.md). The observation
command still accepts no page, URL, or selector: progression happens only
because the operator moved the observed foreground, and the boundary records
that a distinct source was observed, refuses an unchanged source, bounds the
campaign to twenty passes, and fails closed when a pass claims items that were
never persisted. A fresh run reconstructs pass count and last source digest
from durable records alone. The current policy and schema digests now have
two-pass on-device evidence; progression was operator-controlled outside the
fixed command and does not imply navigation authority or a general worker.

Before the 100-item campaign, retain one on-device UIA/document-text semantic
item and review the OCR fallback baseline. Only then run the first 100-item
read-only BOSS campaign across multiple provider contexts and at least one
forced restart, retaining committed-item, token, retry, recovery, takeover, and
cost evidence.

The first worker-side increment is now offline verified: fixed
`campaign start-boss-batch` accepts only config, campaign ID, and run ID,
validates at least two complete current-contract discovery passes, derives a
maximum-20-item plan through the existing `BatchCoordinator`, creates one
bounded heartbeat, and claims only the exact first planned item. It opens no
provider or MCP port and accepts no item, URL, page, scope, batch, or campaign
kind selector.

The next two control increments are also offline verified. Fixed
`campaign run-claimed-boss` reconstructs that exact claim, uses one foreground
project-MCP snapshot to verify only public-identity presence, advances it
through a canonical digest-backed `COMMITTED`, finishes at the single-call limit,
and writes deterministic handoff with the provider forbidden. Fixed
`campaign resume-boss-batch` uses a fresh zero-port run to reconstruct the
finished session, transfer heartbeat ownership, open the exact coordinator
resume plan, and claim its first item. Neither accepts an item selector or
performs automatic navigation or semantic job extraction.
A manifest-routed worker runtime now exposes explicit stable-item preparation
and generic `campaign start`, `campaign run-claimed`, and `campaign resume`
commands for capability-composed scenario contracts. A1-A19 are built-in
evaluation examples rather than a closed product list; another validated spec
can compose reviewed capabilities and register with the same runtime. Seventeen
immutable declarative capabilities—eight observation/verification, six
navigation/recovery, one draft, one external-commit, and one critical-commit—
compose the reviewed authority envelopes; their union derives the only
Runner-advertised MCP tool subset. Provider execution returns one strict
scenario/item/result schema and can commit only observation evidence matching
tools actually dispatched. One-item batches force deterministic handoff and a
fresh provider context. This is offline runtime coverage, not application
acceptance: every semantic/application claim still requires its own retained
provider/desktop/application evidence.

Composable discovery adapters now close the item-identity half of that gate
without widening authority. A reviewed adapter binds one campaign kind to one
identity dimension, an extraction mode (`link_url` or `control_name`), an
item-key prefix, an identity pattern, a source marker, and an exact role set.
`campaign prepare-discovery` creates only the empty reviewed campaign for one
registered kind, and `campaign observe-discovery-page` records exactly one
operator-driven pass from one foreground `ui_snapshot` through the sole Runner
boundary with the provider forbidden; the observing command takes no kind
because the durable manifest selects the adapter. Because the created campaign
carries the ordinary worker policy and schema digests, discovery flows into
`campaign start` without a second manifest shape or dispatch path. Two adapters
are registered as reviewed examples, and unregistered kinds, unchanged sources,
torn pass ledgers, and campaigns that already opened a batch or wrote a handoff
fail closed. BOSS keeps its own fixed discovery contract and its retained
on-device evidence; the generic path is offline verified only, so its next
application-specific evidence gate is one retained on-device adapter pass. It
does not displace the semantic-item sequence above or the active tracker.
A partial [three-item diagnostic](BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md)
retains two discovered-and-fixed integration defects plus one clean post-fix
stale-owner recovery. The later
[clean three-item sequence](BOSS_ITEM_RESTART_CLEAN_EVIDENCE.md) retained two
discovery passes, twelve stable identities, and three consecutive fresh-run
commits without local state correction. The separately
[reviewed bounded semantic contract](BOSS_SEMANTIC_EXTRACTION_CONTRACT.md) is
now connected to a separately bounded offline-verified runtime. Three fixed
no-selector commands open a one-item/five-call/zero-side-effect batch,
re-establish the exact claim through Runner UIA, permit document-text
escalation, validate strict provider JSON, commit only canonical
policy/source-bound results, and transfer successful handoff to a fresh run.
The runtime performs no OCR dispatch while that rung retains an unmet Host
safety baseline. Next retain one on-device UIA/document-text semantic item,
review pixel escalation separately, then expand to the 100-item evaluation.

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
default-off Host presence coordinator now projects atomically persisted phases
for ordinary `run`/`resume`, bounded observation-only `ask` / `plan run`, and explicit
read-only recovery lifecycles and latches off on MCP E-stop, human activity,
terminal state, or cleanup. Recovery notifications occur only after the
existing durable CAS. The
[on-device lifecycle result](PRESENCE_LIFECYCLE_EVIDENCE.md) now retains an
ordinary foreground-safe transition, one-HWND reuse, terminal teardown, and a
synthetic MCP E-stop boundary. One fixed provider-free bounded plan now has
separate [native presence lifecycle evidence](PLAN_PRESENCE_LIFECYCLE_EVIDENCE.md).
A separate default-off progress coordinator now
follows ordinary `run`/`resume`, bounded observation-only `ask` / `plan run`, and
explicit read-only recovery; recovery wakes occur only after the existing
durable CAS. The three fixed MCP-backed campaign execution commands start the
same poller and project their durable run phases through opt-in presence,
without inventing a campaign phase, while zero-port control commands remain
window-free. The fixed synthetic command has
[retained native evidence](CAMPAIGN_PROGRESS_LIFECYCLE_EVIDENCE.md), and one
persisted read-only recovery observation has separate
[native lifecycle evidence](RECOVERY_PROGRESS_LIFECYCLE_EVIDENCE.md). One fixed
provider-free bounded plan also has separate
[native lifecycle evidence](PLAN_PROGRESS_LIFECYCLE_EVIDENCE.md). BOSS campaign
lifecycle wiring remains offline-only. Fake-only, digest-bound Decision Card
models and choice validation from
[Operator experience](OPERATOR_EXPERIENCE.md) are now implemented without an
approval or dispatch port. An opt-in four-choice Win32
card now connects exact-effect selection, re-observe, durable defer, and denial through the existing `ApprovalPort`;
the Runner yields first and rechecks every Host digest before its unchanged
dispatch boundary. Expandable inspection exposes only fixed facts and digest
provenance. The native surface is now a compact corner-positioned normal
Windows window with drag/resize/minimize/maximize behavior, non-topmost
stacking, responsive option layout, and scrollable detail/evidence panes. Its
focus, options, approval, timeout-denial, sole-dispatch, resize/scroll, and
foreground-restoration path now has
[bounded on-device evidence](DECISION_CARD_WINDOW_EVIDENCE.md).
Re-observe now abandons the old turn and requires fresh reviewed evidence;
defer writes a non-resumable `PAUSED` checkpoint. These semantics have
[offline evidence](DECISION_CARD_RECOVERY_EVIDENCE.md); next retain a
human-operated four-choice cross-application result. Do not display
active elapsed time, screenshot count, token coverage, or liveness as known
until the checkpoint/campaign schemas expose those facts.

Presence must follow validated Host phases, avoid focus/input interception,
stay out of Agent observation content, support reduced motion and DPI changes,
and disappear on E-stop or authority release. The fake-only Decision Card view
models and focus-taking ApprovalPort adapter are now implemented at the bounded
scopes above; preserve their no-authority projection and fresh-digest checks.
Options and trade-offs remain advisory until a fresh bound Host decision passes
every ordinary action gate. The next evidence gap is the named human-operated
four-choice cross-application result, not reimplementation of these surfaces.

### Showcase gate - Universal GUI final showcase

After the narrower application, campaign, observation, operator, and enterprise
authority gates retain executable evidence, run the chaptered
[Universal GUI final showcase](UNIVERSAL_GUI_DEMO.md). One campaign covers all distinct
mechanism families across browser/native/document/data, media/design,
nested/legacy/system, and enterprise workflows. It must include deterministic
fault injection, provider-context rotation, restart recovery, presence/progress
UI, one multi-option Decision Card, and a versioned token-cost baseline.

This is a final integration and presentation gate, not Formal Demo v1, an
application-coverage set, or the next runtime increment. A partial or edited
showcase must preserve skipped, failed, challenged, uncertain, and
human-completed states in its retained report.

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
| Operator experience | The console remains default; passive progress/presence are retained; opt-in fail-silent presence follows durable ordinary `run`/`resume`, bounded `ask` / `plan run`, explicit read-only recovery, and fixed MCP-backed campaign execution phases, while the separate progress coordinator covers the same paths on a dedicated UI thread. Both remain observational and close on E-stop/final cleanup without gaining execution authority. Recovery notifications follow the existing durable CAS. Zero-port campaign control remains window-free. Progress checkpoints preserve creation time and distinguish complete provider-usage reports and successful screenshots from generic image results, while legacy missing facts remain unavailable. An opt-in focus-taking Win32 Decision Card yields Agent authority and presents exact-effect approval, re-observe, durable defer, and denial plus expandable digest-only evidence through the existing ApprovalPort. Re-observe abandons remaining calls from the stale turn and gates progress on fresh observation; defer persists non-resumable `PAUSED`/`stopped`; every non-allow choice has zero side-effect dispatch and Runner/MCP dispatch remains singular | Retain a human-operated four-choice cross-application result, recovery and BOSS campaign presence desktop evidence, and general post-provider same-run process resume |
| Host completion notification | Internal bounded projection and fake-host decisions are offline verified: running keeps polling, attention/uncertain states never complete, validated terminal events deduplicate across restart, and repeated polling is read-only. No public status tool, notification bridge, or mobile adapter exists. The separately implemented general worker is offline-only and is not connected to this polling/notification path | Retain application evidence before reviewing any public status surface; keep mobile delivery host-owned and provider/MCP/desktop calls absent from polling |
| Planner-Executor | Strict TaskPlan compilation/persistence, dual-provider Planner and final adapters, fresh-call preflight/session, observation runtime/reconciliation, final WAL, and completed-final local reconciliation are implemented. Product-facing `ask` and metadata-oriented `plan run` compose exactly one host-scoped plan request, one to four observations including bounded semantic document text through the sole Runner boundary, and one stateless tool-free final response. They expose no tool selector, side effect, ordinary provider continuation, approval option, or alternate MCP path. The expanded path is offline fake-verified and has one exact-candidate OpenAI/Windows/Notepad [result](DESKTOP_ASK_EVIDENCE.md); the installed public-browser-to-disposable-Word workflow is separately retained | Preserve those exact results; expand only through a named provider/application gate while keeping output untrusted and action authority inside the existing Runner/MCP boundaries |

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
as an isolated-worker target for mobile-facing application-coverage cases such
as BOSS and WeChat. See
[ADR-008](adr/008-android-device-driver-behind-driver-contract.md).
This is distinct from the roadmap's existing "mobile" work, which is a
notification sink, not a control target.

### Hidden Windows desktops

`CreateDesktop` / `SwitchDesktop` can be investigated as a research route,
but they are not the preferred isolation strategy and must not replace real
end-to-end validation.

### Enterprise workflow layer

After the staged application-coverage mechanics are reproducible, define the
planned E7 enterprise boundary before connecting the Agent to business systems.
This layer adds stable business-object identities, object- and field-scoped authority,
tenant isolation, data classification, maker-checker approval, SLA ownership,
and saga-style cross-system reconciliation. The first evaluation is the
synthetic IT incident workflow in
[Application evaluation matrix](APPLICATION_EVALUATION_MATRIX.md); production
records and credentials are outside the default evaluation boundary.

### Continual learning and verified experience evolution

L0-L4 now implement the bounded stages in the
[continual-learning architecture](CONTINUAL_LEARNING.md): quarantined factual
suggestions, versioned inert procedures, isolated replay, held-out comparison,
and canary-bounded selection among already approved equivalent low-risk
procedures. These are offline or injected-runtime data/evaluation/routing
scopes, not automatic learning or model training. L5 remains inactive and
requires separate privacy, security, evaluation, deployment, and rollback
consent.

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
