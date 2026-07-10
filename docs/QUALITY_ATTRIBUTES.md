# Quality attributes

> **Status: review and acceptance criteria.** These are guardrails for design,
> implementation, and testing; they do not imply universal coverage or support
> for every desktop application.

## Safety

**Goal:** Actions remain inside an explicit, reviewable local authorization
boundary.

- Safe mode uses foreground process ancestry rather than a single process name.
- E-stop, audit logging, and human-activity behavior must be considered for
  every new action tool.
- Dangerous-action confirmation must state exactly which actions it covers.
- Password values must not appear in UI snapshots.
- Screenshot-redaction claims must stay limited to the configured title-based
  blackout behavior.

**Acceptance signal:** Unit tests cover the gate, e-stop, keyword detection,
and JSONL audit shape; on-device smoke coverage verifies the relevant desktop
path.

## Correctness

**Goal:** The model's observation and the native action target agree.

- Set DPI awareness before desktop libraries are used.
- Keep primary-display screenshot pixels, UIA bounding boxes, and coordinate
  clicks in one supported pixel space.
- Prefer native accessibility patterns for ref actions.
- Return an explicit stale-reference error after no more than one relocation
  retry.
- Do not advertise multi-monitor or region behavior until it is exercised
  end-to-end.

**Acceptance signal:** DPI/coordinate and ref-lifecycle smokes pass on a real
Windows desktop.

## Reliability

**Goal:** Real application quirks are visible rather than silently hidden.

- Include owned dialogs in window enumeration.
- Do not force foreground activation merely to read a UI snapshot.
- Make browser warm-up, truncation, and incomplete accessibility state visible
  to the caller.
- Keep real-app probes read-only until their behavior is understood.

**Acceptance signal:** A failure explains whether it is a UIA, coordinate,
foreground, safety-gate, or driver problem.

## Human coexistence

**Goal:** The project does not pretend a shared desktop provides parallel
control.

- In safe mode, yield after recent local input.
- Treat coordinate clicks, key chords, focus-based typing, and window
  activation as visible foreground operations.
- Never describe UIA `SetValue`, `Invoke`, or `Select` as generally
  foreground-free.
- Require an independent runtime for true background operation.

**Acceptance signal:** Human-activity tests reject competing safe-mode actions
with an explanatory result.

## Observability and testability

**Goal:** A maintainer can diagnose a failure without guessing.

- Use concrete driver error codes and server-level guard messages.
- Preserve a truncation count in snapshot output.
- Write audit records as bounded JSONL.
- Keep pure logic in pytest and visible desktop effects in named smoke scripts.
- Store throwaway probes and artifacts in ignored `out/`; promote repeatable
  findings to tests or documentation.

**Acceptance signal:** `pytest` runs without desktop side effects; a matching
`smoke_*.py` script exists for changed native behavior where practical.

## Portability, performance, and maintenance

**Goal:** The core stays small enough to support native drivers without
premature abstraction.

- Keep `contract.py` platform-free.
- Push tree pruning into drivers and use `find()` to reduce returned context.
- Change the contract deliberately, version it, and update its documentation.
- Separate current runtime documentation from planned architecture.
- Keep docs English-first and avoid sentence-by-sentence bilingual duplication.

**Acceptance signal:** A change can be reviewed against one clear owner
document: [Design](DESIGN.md), [Driver Contract](DRIVER_CONTRACT.md),
[Configuration](CONFIGURATION.md), or [Roadmap](EXECUTION_PLAN.md).
