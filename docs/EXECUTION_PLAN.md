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
| P6 — package and documentation hygiene | Partially complete | Package metadata is at 0.1.0 and docs are organized; licensing/release policy remains open. |
| P7 — full-control local mode | Implemented | `safe_local` and `full_control_local` are supported modes. |
| P8 — VMware host helper | Experimental | The helper checks/starts an existing VM and can wait for VMware Tools. |

## Next validation priorities

### Agent Host remaining-work ledger

The following items are intentionally unfinished. They must remain visible in
release notes and cannot be inferred complete from offline CI:

| Item | Current boundary | Completion evidence |
| --- | --- | --- |
| OpenAI and Claude E3 | Opt-in tests exist; no credentialed evidence is retained | Both providers pass the harmless fake-MCP cycle with reviewed model IDs |
| Isolated E4 | Four-cell runbook exists; no isolated desktop evidence is recorded | Both providers pass read-only and one approved low-risk action with post-action observation |
| E5 release regression | Canonical E1/E2 case manifest is frozen and enforced in CI; isolated evidence is pending | Reviewed isolated successful and failure traces are rerun after policy/schema/adapter changes |
| Release approval | Automated preflight passes locally; human gates remain | Completed [release evidence](RELEASE_EVIDENCE.md), license review, version/changelog, and human approval |
| Broader resume | Controlled recovery can chain 1-4 reviewed read-only calls under one run lock, with an atomic intent/completion pair for every call. Provider-requested actions stop without dispatch; completed side effects issue one synthetic `ui_snapshot` and stop. The frozen E2 matrix proves zero action replay | Keep uncertain dispatches and pending side effects permanently non-executable; require a separate design before raising the four-step cap or resuming action authority |
| Token-aware context | Event-count reduction, exact request-byte gates, and cumulative provider-reported input-token cutoff | Provider/model-aware pre-request token-window enforcement without splitting mandatory atomic groups |

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

Do not add hierarchy, parent refs, or text-run merging without observed need.

### 3. Define a real multi-monitor model

Before advertising support, decide and validate:

- Virtual-desktop capture bounds.
- Per-monitor DPI conversion.
- Region capture offsets.
- Cross-monitor coordinate clicks and window placement.

### 4. Finish release policy

Choose a license/redistribution policy, reconcile public version sources, and
add release automation only after the supported behavior is stable.

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
