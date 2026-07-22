# Maintainer handoff

> **Internal engineering notes.** This file preserves operational knowledge for
> maintainers. It is not the product specification; start with
> [README.md](README.md) and [docs/README.md](docs/README.md) for the current
> public documentation.

For the fastest complete orientation, read
[Project overview](docs/PROJECT_OVERVIEW.md) before entering a layer-specific
contract.

## Current shape

The codebase has two executable surfaces. The public baseline is an
experimental Windows-only MCP server with eleven tools, a typed Driver Contract
v1.0.0, and one in-process Windows implementation. The second is an
experimental `computer-use-agent` Host with a dual-provider read-only loop,
explicit memory, traces/evaluation, bounded recovery, and fake-verified approved
actions. [Dual-provider E3 evidence](docs/E3_EVIDENCE.md) is retained for both
bounded fake-MCP cases with one reviewed model per provider. [Isolated desktop
E4 evidence](docs/E4_EVIDENCE.md) is retained for the reviewed VM and one model
per provider, including read-only and explicitly approved action cells. The
record also preserves a separate Sonnet 5
`thinking`-block compatibility failure. The ordinary Claude adapter now has an
offline-verified strict preservation path for signed `thinking` and opaque
`redacted_thinking` blocks, plus retained exact-commit Sonnet 5 fake-MCP
evidence. This does not broaden the passing model-scoped Claude claim.

Planner/Executor and Campaign packages also contain substantial offline-tested
control logic. Completed final-response crash evidence can now be applied
through a local-only idempotent plan CAS, terminal trace/checkpoint repair, and
ordinary-continuation cleanup while retaining the completed final WAL. A
bounded `plan run` CLI now asks the configured provider for one host-scoped
plan containing one to four observation steps, executes only those steps
through the sole Runner boundary, and obtains one stateless tool-free final
response. It has offline fake-port evidence plus retained OpenAI and Claude E3
results. The reviewed Agent Host path also has retained isolated desktop E4
evidence, but the Planner / Executor path has no separate desktop result. One
fixed synthetic claimed campaign item can execute a
single `list_windows` observation through the existing Runner boundary, persist
`OBSERVED`, reduce the bounded result to a non-sensitive window count, persist
`EXTRACTED`, verify its canonical JSON digest, persist `COMMITTED`, close the
batch with measured usage, write deterministic handoff, and transfer ownership
to a fresh Runner run that reconstructs the finished session from durable
campaign records and reaches the expected exhausted resume decision. The exact
three-command seam now has [retained on-device evidence](docs/SYNTHETIC_CAMPAIGN_EVIDENCE.md).
A third fixed CLI command now creates exactly that one-item synthetic manifest,
discovery record, heartbeat, batch, and claim without opening provider or MCP
ports. BOSS discovery now accumulates identities across repeated observations
through a durable append-only discovery-pass ledger that stores only counts and
a source digest, refuses an unchanged source, bounds the pass count, fails
closed when a pass claims unpersisted items, and is reconstructed by a fresh run
from durable records; the operator still causes progression by moving the
observed foreground, because no command accepts a page, URL, or selector. No general campaign worker or complete application workflow is
connected. The broader universal GUI,
operator UI, cross-application demo, continual-learning, and additional
platform-driver layers (macOS, Linux, and an ADB-transport Android device
driver behind the same contract — [ADR-008](docs/adr/008-android-device-driver-behind-driver-contract.md))
remain planned. Start with [Capability status](docs/CAPABILITY_STATUS.md) and
read the status header of every owner document before treating it as available.

Before changing behavior, inspect the current worktree and run the unit suite:

~~~powershell
git status --short --branch
.\.venv\Scripts\python.exe -m pytest -q
~~~

## Source map

~~~text
src/computer_use_mcp/
  contract.py          typed, platform-free Driver Contract
  core.py              session refs, snapshots, stale relocation
  server.py            FastMCP tools and action guard orchestration
  gate.py              foreground owner-chain allowlist
  human_activity.py    synchronous yield after human input
  safety.py            confirmation, e-stop, screenshot redaction
  audit.py             JSONL records
  capture.py           bounded region image envelope
  ocr.py               bounded Windows OCR over captured bytes
  document_text.py     bounded UIA document-text envelope
  region.py            shared region validation and crop-local redaction boxes
  dpi.py               DPI-awareness bootstrap
  drivers/windows.py   UIA, Win32, capture, process ownership

src/computer_use_agent/
  runner.py            sole Agent tool-dispatch authority boundary
  providers/           OpenAI and Claude adapters
  planning.py          bounded declarative planning contracts
  executor*.py         internal observation/final runtime and local reconciliation
  planned_observation_runtime.py fixed observation-only CLI composition
  campaign*.py         offline campaign control state and preflights
  continuation*.py     private bounded crash evidence and recovery
  progress_view.py     pure run/campaign reducer and fixed relevance grouping
  presence*.py         pure presence state plus passive primary-display halo

scripts/               on-device smoke and VMware helper
tests/                 side-effect-free unit tests
out/                   ignored disposable probes and artifacts
docs/                  canonical English documentation
~~~

## Hard-earned implementation facts

1. **Set DPI awareness early.** It must happen before UIA/capture libraries
   initialize, or coordinate alignment breaks under display scaling.
2. **Use native key events for chords.** Win32 `keybd_event` is used for
   combinations such as `Ctrl+S`; do not assume `uiautomation.SendKeys`
   handles every chord correctly.
3. **Foreground is a real resource.** Background processes may not directly
   activate a window. Keyboard actions and focus-based typing need the intended
   foreground target.
4. **Owned dialogs are special.** Save dialogs can be owned top-level windows
   rather than ordinary desktop siblings; `list_windows()` deliberately uses
   Win32 enumeration that includes them.
5. **Modern Notepad is not just an Edit control.** Its document surface can
   expose a writable ValuePattern, and one visible menu item may appear with
   multiple UIA control types. The driver deduplicates by geometry and name.
6. **Browser UIA is lazy.** A first Chromium traversal may only materialize
   accessibility content; warm-up is best effort and must not steal foreground.
7. **Primary display is the supported coordinate domain.** Do not silently
   extend the current model to secondary monitors or region offsets.
8. **Refs are session state.** They accumulate across snapshots; stale actions
   get one role/name relocation attempt. Snapshot the target scope before
   acting across windows so the driver has fresh native handles.
9. **Same-desktop UIA is not background-safe.** A controlled ValuePattern
   operation can alter foreground state. Use an isolated runtime for true
   background work.
10. **Window activation was reproduced, repaired, unit tested, and retained in
    the isolated E4 evidence.** The driver now attaches the required
    input queues, restores minimized targets, releases attachments in `finally`,
    and verifies the foreground HWND. Treat the retained E4 result as scoped to
    the reviewed VM and exact repair tree. Later bounded on-device BOSS home,
    OCR, and UIA document-text observations passed through the project stdio
    path; these remain narrow observation results rather than application
    acceptance.
11. **Interactive UIA is not document text.** The BOSS probe exposed useful
    controls while static job-description content was absent. A later bounded
    on-device stdio probe retained a real `uia_text_pattern` result: one ordered
    10,189-character block versus 68 structured `ui_snapshot` lines from the
    same foreground window, with no page prose retained. Use the observation
    ladder rather than assuming a full UIA snapshot contains page content.
12. **A bounded crop must prove both pixels and grounding.** The retained
    on-device region-capture smoke draws only the project's synthetic passive
    window, captures its exact Win32 rectangle through stdio MCP, verifies the
    returned PNG dimensions/byte count/digest against the envelope, and then
    discards the pixels without changing foreground.
13. **Progress grouping describes checkpoints, not liveness.** Independent runs
    are grouped as Attention, In progress, or History using only validated
    phase and `updated_at`; the In progress label still says liveness unknown.
    Attention consumes the bounded display budget first, duplicate IDs fail
    closed, and a retained live poller run proves one terminal transition moved
    exactly one of two runs into History without changing foreground.

## Starting a fresh maintenance session

For long-running feature work, read only the documents needed for the current
layer:

1. [Project overview](docs/PROJECT_OVERVIEW.md) for the complete feature,
   implementation, quality, status, and ownership map.
2. [Capability status](docs/CAPABILITY_STATUS.md) for the shortest current
   implemented/evidence/next-gate view.
3. [Operator session notes](docs/OPERATOR_SESSION_NOTES.md) for sanitized live
   evidence and unresolved validation gaps.
4. [Roadmap](docs/EXECUTION_PLAN.md) for P0/P1 ordering.
5. [Long-running tasks](docs/LONG_RUNNING_TASKS.md) for campaigns, item ledgers,
   batching, cross-session handoff, and the planned host-terminal polling
   contract used before Codex/Claude mobile notification.
6. [Application evaluation matrix](docs/APPLICATION_EVALUATION_MATRIX.md) for
   the BOSS, Google Docs, WeChat, Douyin real-time-media, enterprise workflow,
   and cross-application acceptance cases.
7. [Token efficiency](docs/TOKEN_EFFICIENCY.md) and
   [Observation contract](docs/OBSERVATION_CONTRACT.md) for model-context and
   perception changes.
8. [Operator experience](docs/OPERATOR_EXPERIENCE.md) for the planned
   computer-use presence indicator and Decision Cards, then
   [Operator progress viewer](docs/PROGRESS_VIEWER.md) for the passive Windows
   status projection.
9. [Universal GUI demo](docs/UNIVERSAL_GUI_DEMO.md) only when assembling the
   final chaptered showcase and retained evidence package; it is not a shortcut
   around the narrower application and safety gates.
10. [Continual learning](docs/CONTINUAL_LEARNING.md) for the planned progression
   from explicit memory through verified workflow promotion and cost-aware
   strategy selection; it does not describe current runtime behavior.

The campaign control plane can validate `campaign_id`, manifest, ledgers, and
`handoff.json`. Its first internal execution seam is limited to the exact
synthetic observation-through-restart/resume described above. The replacement
run accepts no task text or prior `BatchSession`, performs no provider or MCP
call, and leaves campaign completion and heartbeat retirement untouched. Three
fixed CLI commands prepare the exact synthetic claim, execute it through
handoff, and enter the durable fresh-run resume boundary. Preparation has no
selector and cannot create another campaign kind or item; a general worker
remains unconnected. Use these documents as the cross-session source of truth.

## Guardrail checklist for new actions

When adding an action tool, decide explicitly:

- Does it need e-stop and audit? (Usually yes; neither should be skipped.)
- Can it contend with local human input?
- Is foreground allowlist verification appropriate?
- Does its target need dangerous-action confirmation?
- Which direct unit test and on-device smoke demonstrate the behavior?

Document any intentional exception such as `activate_window`, which skips the
foreground allowlist only because it is itself the foreground-changing action.

## Validation policy

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts
git diff --check
~~~

The `scripts/smoke_*.py` scripts can interact with real applications. Do not
run them casually on a sensitive or active workstation. Use a read-only probe
in `out/` to understand a new application before implementing behavior around
its UIA tree.

## Documentation maintenance

- English is canonical. The Chinese root quick-start is intentionally shorter,
  so update it when setup, safety defaults, or supported capability summaries
  change.
- Keep current behavior in the README, configuration page, and tool reference.
- Update [capability status](docs/CAPABILITY_STATUS.md) whenever implementation
  or retained evidence moves a row between states; offline tests cannot fill a
  provider, desktop, or application evidence cell.
- Keep design directions in [docs/DESIGN.md](docs/DESIGN.md) and
   [docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md).
- Keep computer-use presence, passive progress, and interactive decision
  boundaries synchronized across [operator experience](docs/OPERATOR_EXPERIENCE.md),
  [progress viewer](docs/PROGRESS_VIEWER.md), and
  [approved actions](docs/APPROVALS.md).
- Keep Decision Card choices on the existing `ApprovalPort`: the opt-in
  focus-taking Win32 adapter yields authority first and only its fresh exact
  selection can become a request-bound `PolicyDecision`. Never add a second
  dispatch path, global/batch allow, or model-selected approval.
- Retain standalone presence desktop results in
  [presence evidence](docs/PRESENCE_WINDOW_EVIDENCE.md). Ordinary `run`/`resume`
  now have default-off, fail-silent durable-phase wiring; do not infer planned,
  campaign, recovery, multi-monitor, or abrupt-process support from it.
- Keep host completion polling synchronized across
  [long-running tasks](docs/LONG_RUNNING_TASKS.md),
  [operator experience](docs/OPERATOR_EXPERIENCE.md), the roadmap, and the
  capability dashboard. Mobile delivery belongs to the Codex/Claude host; do
  not add it to the eleven-tool desktop MCP surface or treat MCP logs as terminal
  evidence.
- Keep planned automatic extraction and strategy-learning claims synchronized
  across [context and memory](docs/CONTEXT_MEMORY.md),
  [continual learning](docs/CONTINUAL_LEARNING.md), the roadmap, and the
  universal demo.
- Keep contract changes synchronized with `contract.py`.
- Keep superseded plans and implementation chronology under `docs/archive/`;
  archived files are non-normative and must point to their current owner.

Avoid restoring sentence-by-sentence bilingual copies; they obscure the current
status and create needless translation drift.
