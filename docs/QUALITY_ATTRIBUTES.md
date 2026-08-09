# Quality attributes

> **Status: review and acceptance criteria.** These are guardrails for design,
> implementation, and testing; they do not imply universal coverage or support
> for every desktop application.

For the cross-system mapping from each attribute to concrete feature families,
source modules, and evidence owners, see
[Project overview](PROJECT_OVERVIEW.md#quality-attributes-and-how-the-design-realizes-them).

## Attribute map

| Attribute family | Primary concern |
| --- | --- |
| Safety and least authority | Who may cause which effect, through which reviewed boundary |
| Correctness and grounding | Whether observation, identity, coordinates, and action target agree |
| Reliability | Whether quirks and failures remain explicit and bounded |
| Durability and recoverability | Whether committed progress survives failure without replaying uncertainty |
| Security and privacy | Whether secrets, sensitive content, credentials, and authority are minimized |
| Human coexistence | Whether the Agent yields, exposes control, and avoids false background claims |
| Observability and auditability | Whether failures and outcomes are diagnosable from bounded evidence |
| Testability and evidence integrity | Whether claims are tied to the evidence level actually executed |
| Resource and context boundedness | Whether bytes, tokens, images, calls, time, and state remain capped |
| Performance and context efficiency | Whether useful verified results minimize observation and provider cost |
| Portability and maintainability | Whether platform-specific code stays behind deliberate contracts |
| Interoperability | Whether MCP clients and provider adapters share canonical semantics |

## Security and privacy

**Goal:** Sensitive content and executable authority are minimized at every
process, persistence, provider, and operator boundary.

- Launch MCP children with a reviewed environment rather than forwarding
  provider, cloud, source-control, and arbitrary host secrets.
- Keep task text, model prose, UI text, screenshots, typed values, provider
  identifiers, and raw errors out of redacted checkpoint, trace, report, and
  audit surfaces.
- Treat the opt-in continuation artifact as sensitive private state with strict
  paths, bounds, expiry, owner-only permissions where supported, and explicit
  deletion on ordinary terminal completion.
- Require explicit confirmation, scope, type, and expiry for local memory;
  memory remains untrusted data and cannot modify policy or approve actions.
- Treat digests as integrity/correlation evidence, not encryption,
  authentication, confidentiality, or an operating-system security boundary.

**Acceptance signal:** Secret-sentinel, redaction, unsafe-path, environment,
memory-rejection, and artifact-lifecycle tests pass; human release review
confirms that retained evidence contains only its documented safe schema.

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
- Use fresh observation for every ref-backed OS click; permit native
  accessibility patterns only through explicit user opt-in, and never fall
  back between action backends after failure.
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

## Long-running stability

**Goal:** Hour- or day-scale work survives provider-context rotation, process
failure, and Codex-session replacement without depending on chat history.

- Decompose campaigns into independently committed items and bounded batches.
- Persist a deterministic cursor and append-only item transitions.
- Never advance past an item before its result commit is durable.
- Do not replay a dispatched action with an unknown outcome.
- Bound attempts, consecutive failures, wall time, screenshots, and tokens.
- Produce a compact handoff that a fresh session can validate without model
  prose from the previous session.

**Acceptance signal:** A 100-item read-only campaign crosses at least two fresh
provider contexts and one forced restart with one committed result per stable
item key.

## Context efficiency

**Goal:** Provider context scales with the current item rather than total
campaign history.

- Prefer `find`, scoped UIA, document text, OCR regions, and cropped images in
  that order when each cheaper source is sufficient.
- Keep screenshots out of text serialization and retain local digests for
  reuse.
- Rotate provider context at bounded batch or token limits.
- Measure provider-reported tokens per committed item.
- Treat missing usage as unknown, not reported zero.

**Acceptance signal:** Evaluation reports tokens, image pixels, and tool calls
per committed item and proves that an optimization does not increase uncertain
or incorrect outcomes.

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
