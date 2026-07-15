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

After the BOSS baseline, run the Google Docs long-document and WeChat draft-only
cases, then the cross-application campaign in
[Application evaluation matrix](APPLICATION_EVALUATION_MATRIX.md).
Expand to Excel, PDF, Figma/Canva, and one Electron client only after the Wave 1
campaign and observation measurements are reproducible. Remote Desktop,
system-dialog boundaries, legacy UI, and modal GPU applications remain later
waves.

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
