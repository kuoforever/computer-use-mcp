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
experimental Windows-only MCP server with thirteen tools, a typed Driver Contract
v1.0.0, and one in-process Windows implementation. The second is an
experimental `guarded-desktop-agent` Host with a dual-provider read-only loop,
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
closed when a pass claims unpersisted items, and is reconstructed by a fresh
run. A current-contract
[two-pass on-device result](docs/BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md) retained
twelve stable identities with distinct source digests and externally controlled
project-MCP progression; no command accepts a page, URL, or selector. A
separate composable adapter layer now generalizes only that identity step for
other reviewed scenarios: `campaign prepare-discovery` creates the empty
reviewed campaign for one registered kind and `campaign observe-discovery-page`
records one operator-driven pass from one foreground `ui_snapshot`, binding the
adapter through the durable manifest rather than a caller argument. Its
campaigns carry the ordinary worker digests and enter `campaign start`
unchanged; it is offline verified only. No complete application workflow is
connected. A fixed
zero-port `start-boss-batch` boundary now validates the complete discovery
ledger, opens the first coordinator-selected maximum-20-item batch, creates its
bounded heartbeat, and claims only ordinal 1. Fixed `run-claimed-boss` then
uses one project-MCP foreground snapshot to verify only that claimed public
identity, persists a canonical presence digest through `COMMITTED`, finishes at
`TOOL_CALL_LIMIT`, and writes handoff. Fixed `resume-boss-batch` reconstructs
that finished session in a fresh zero-port run, transfers heartbeat ownership,
opens the coordinator-selected resumed plan, and claims its first item. These
boundaries are offline verified, and a
[clean three-item on-device sequence](docs/BOSS_ITEM_RESTART_CLEAN_EVIDENCE.md)
retained twelve discovered identities plus three consecutive fresh-run commits
without local state correction. They still do not perform semantic job
extraction, automatic navigation, provider execution, or the 100-item
application gate. A separate
[bounded semantic contract](docs/BOSS_SEMANTIC_EXTRACTION_CONTRACT.md) now
offline-verifies the exact compact result, classification-policy binding,
canonical digest, and fail-closed UIA-to-screenshot observation ladder. A
separate one-item semantic CLI seam now connects UIA and document text through
Runner, commits only strict provider JSON under a fixed no-preference
classification policy, writes failure handoff when the still-gated OCR rung is
denied without dispatch, and transfers a successful batch to a fresh run. It
does not alter the retained one-call identity runtime and has no on-device
semantic evidence. The broader
universal GUI, operator UI, cross-application demo, continual-learning, and additional
platform-driver layers (macOS, Linux, and an ADB-transport Android device
driver behind the same contract — [ADR-008](docs/adr/008-android-device-driver-behind-driver-contract.md))
remain planned. Start with [Capability status](docs/CAPABILITY_STATUS.md) and
read the status header of every owner document before treating it as available.

The Runtime-side Full Cycle Lane A bridge is implemented. `fullcycle manifest`
derives a versioned capability document from the reviewed registry, and
`fullcycle export-run` packages only the already-redacted checkpoint and trace.
Both write canonical bounded JSON to a new absolute path and open no external
port. The strict offline consumer fixture was completed in
`reliable-agent-model-lifecycle` as `FC-BRIDGE-001` and pins producer commit
`8ace897`; on 2026-08-02 a manifest regenerated from freeze commit
`324ff2fb5911e332ddb5c5f90eb41296e8faf7a9` reproduced that pinned digest
exactly, so Lane A has not drifted. `GDA-FC-004` is complete locally and no
Runtime item is active. Rich episode capture is explicitly deferred to the
Full Cycle project's separate `FC-BRIDGE-003` review and remains disabled by
default.

## Bounded Operator HUD handoff (2026-07-31)

`PROJECT_STATUS.md` remains the only task registry. `GDA-FC-002` closed on
2026-08-01, so `GDA-FC-004` is now the sole active closure item and exact Full
Cycle resume point. The notes below
describe only the user-authorized, bounded `GDA-DEMO-003` detour; they do not
activate broader operator UI or replace the Full Cycle backlog.

`codex/demo-hud-baseline` merged into `main` as `6a21d33` through PR #221 on
2026-08-01 and was deleted from the remote and the local checkout. There is no
HUD working branch; `main` carries the work.

The branch had been rebased onto `main` at `9cb38c8` on 2026-07-31, which gave
every commit a new identity. The pre-rebase commits were kept on a local
`backup/demo-hud-pre-rebase` branch, which was deleted on 2026-08-01 once the
rebased history merged. The old identities are recorded here so an earlier
document or note that names one still resolves to something:

- `07efbb6` `Document Operator HUD handoff`, pre-rebase `f4b0a70`;
- `3e9af02` `Map Demo steps to workflow chapters`, pre-rebase `35c5363`;
- `efc5062` `Retain isolated operator HUD evidence`, pre-rebase `d1507e3`.

The pre-rebase hashes are no longer reachable from any branch. Only the rebased
identities on the left are resolvable, and all three are ancestors of `main`.

The offline gate that had been outstanding for the rebased branch was
re-established on 2026-08-01 and again after the merge; the dated results are
in `PROJECT_STATUS.md`.

Read these files in order for the HUD continuation:

1. `PROJECT_STATUS.md`, especially `GDA-HUD-005`, `GDA-HUD-006`, and
   `GDA-HUD-011`;
2. `docs/OPERATOR_HUD_VISUAL_EVIDENCE.md` for the retained 150% DPI matrix and
   its promotion boundary;
3. `docs/OPERATOR_EXPERIENCE.md` and `docs/PROGRESS_VIEWER.md` for the default
   expanded checklist and operator-collapse contract;
4. `src/computer_use_agent/demo_cross_app.py` and
   `tests/agent/test_demo_cross_app.py` for the new pure mapping.

The completed HUD foundation includes:

- compact and expanded human-readable Decision Card geometry;
- default-expanded six-row Progress checklist with explicit collapse
  preservation;
- fixed 150% DPI Decision/Progress screenshots retained at `efc5062`
  (pre-rebase `d1507e3`);
- exact-title, DPI-aware, compositor-settled capture with fixed output slots;
- a named mutex that rejects duplicate visual-review instances;
- exact-process Chrome/Word fixture cleanup that does not scan by executable
  name and avoids Word AutoRecover on the next run.

`3e9af02` (pre-rebase `35c5363`) adds only the pure transition projector. Its
fixed mapping is:

- provider steps `0..5`: workspace complete, public-source review current;
- `6..8`: source review complete, open-research-brief current;
- `9..14`: brief open, add-verified-note current;
- `15`: note added, save current;
- `16..17`: save complete, durable verification current;
- `18` with `WorkflowStatus.READY`: all six chapters complete.

That projector was connected on 2026-08-01 by
`src/computer_use_agent/demo_workflow_progress.py` (`DemoWorkflowProgress`),
without starting the complete Demo. All six prescribed points are done:

1. one Demo-only, UI-thread-owned workflow lifecycle that receives only the
   fixed provider boundary and the durable Runner phase. It implements the
   passive progress lifecycle port the Runner already accepts, so it drops into
   `RunnerPorts.progress` without a second dispatch path;
2. its latest validated checklist drives `PassiveProgressWindow.open/update`;
   first open shows all six chapters and an explicit operator collapse survives
   later refreshes;
3. `scripts/demo_cross_app.py` sets `OperatorStepContext.workflow` from
   `WorkflowBreadcrumb.from_checklist(...)` before each Decision Card, and the
   approval `n/7` count remains a separate field;
4. approval wait projects `NEEDS_INPUT`; durable success projects `READY` only
   at provider boundary 18. Between the provider's last turn and the durable
   phase the final chapter is held open rather than completed, so a late
   failure lands on that chapter. Cancellation keeps the resolved prefix and
   claims no current chapter;
5. `tests/agent/test_demo_workflow_progress.py` covers thread ownership,
   monotonic chapters, approval breadcrumbs, collapse preservation, and
   fail-closed invalid state. `CrossAppDemoProvider.on_provider_step` is an
   integer-only passive observer whose failure drops the observer and never
   changes the Demo;
6. the complete offline gate passed on 2026-08-01; the exact dated counts are
   in the `GDA-HUD-005` row of `PROJECT_STATUS.md`.

That dedicated live smoke now exists as
`scripts/smoke_demo_workflow_progress.py` and passed three consecutive times on
2026-08-01. It drives the real non-activating Win32 surface through every
projected transition and opens no Runner, MCP, provider, or application, so it
is projection-surface evidence only.

Clipping at 100% and 125% is now covered deterministically:
`measure_tier_text_width` measures real Segoe UI extents on a memory device
context, and the tests assert every longest realistic header line, countdown,
and choice label fits its exact painted rectangle at all three scales. A
companion test proves that check trips on the layout that produced the observed
clipping, so the guard cannot rot into a tautology.

What remains for `GDA-HUD-002` is live operator acceptance at 100% and 125%,
which needs display scaling changed and therefore belongs to the operator. A
run of `scripts/capture_operator_hud_evidence.py` at each scale would retain it.

## State at the 2026-08-02 handoff

### 2026-08-03 completion update

The requested post-fix complete run is now retained as
`cross-app-demo-20260803-024517-764321`. It reached durable `SUCCESS` with 17
tool calls, seven approved side effects, zero tool failures, and exact-process
fixture cleanup. Its Presence probe recorded 85 projections, 247 painted
samples, zero unpainted samples, and all seven approval-wait boundaries. The
saved 19-entry DOCX contains the fixed marker and has SHA-256
`48d8393e70e9305dfb4aa8537a1a9d49aa2d1eb18202a55a422c008036c52629`.
[The dated evidence](docs/OPERATOR_HUD_DEMO_EVIDENCE_2026-08-03.md) owns the
claim. Item 1 below is closed. Live compact/expanded review at 100% and 125%
also passed on 2026-08-03 and is retained in
`docs/OPERATOR_HUD_DPI_EVIDENCE_2026-08-03.md`; item 2 below is closed. Only a
physical Alt+Tab press remained operator-only evidence at that point; the
final closure update below records its subsequent pass.

`main` is at the merge of PR #225 plus the presence work described below. Nine
of the eleven `GDA-HUD-*` rows have implementation and offline or isolated live
evidence; **no row is marked passed**. What is left is short and specific:

1. **One complete Demo run with the presence fixes in place.** Three runs
   completed successfully on 2026-08-02 — `...141038-994636`,
   `...142840-759829`, and `...144124-559107` — but all three had an invisible
   halo. The fixes landed
   after the last one, and the halo's behaviour is verified programmatically
   against the real window, not by a run. Running
   `scripts/demo_cross_app.py` and reading the `presence` section of
   `final-state.json` closes this: expect a non-empty `projection_sequence`
   containing `WAITING_APPROVAL/WAITING`, `samples_painted` well above zero,
   and `samples_unpainted` near zero.
2. **100% and 125% DPI acceptance** for `GDA-HUD-002`. Needs the operator to
   change display scaling, then `scripts/capture_operator_hud_evidence.py`.
3. **A real Alt+Tab press** while a card is open, for `GDA-HUD-004`. Every
   other clause of that row is done; synthesising the keystroke would prove
   nothing, so it needs a person.
4. `GDA-HUD-001` can never have a retained image: Presence is
   `WDA_EXCLUDEFROMCAPTURE` and must not be made capturable to produce one.
   The probe report is its evidence instead.

### 2026-08-03 final Operator HUD closure update

The operator physically pressed Alt+Tab while the synthetic, non-dispatching
Decision Card was presented and confirmed that Windows switched windows. The
test left no matching Decision Card window behind. The bounded acceptance
standard and non-promotion boundary are retained in
`docs/OPERATOR_HUD_KEYBOARD_EVIDENCE_2026-08-03.md`.

All three operator actions listed above are now closed. `GDA-DEMO-003` is
complete locally; no Operator HUD item or Runtime feature item is active. This
does not promote high-contrast, every-DPI Chrome/Word, provider, release, or
universal-GUI evidence. Resume Full Cycle work in
`C:\Users\Alienware\reliable-agent-model-lifecycle`, whose current single
active `FC-MVP-001` objective is the v2 failure-classification gate. Lane B
remains the separately reviewed `FC-BRIDGE-003` rich-capture path.

The final Runtime validation after these records passed. The exact dated
outputs are retained in
`docs/OPERATOR_HUD_KEYBOARD_EVIDENCE_2026-08-03.md` rather than copied into
this durable handoff.

Operating requirement discovered by the runs: **leave the desktop alone from
launch until the first Decision Card appears**, and for a few seconds after
each approval. The Demo binds Chrome by requiring it to be foreground and
cannot pre-activate it, because activation is approval number one.

Two defect classes found this session are worth carrying forward as habits.
Surfaces verified alone hid a defect that only appeared when two were composed
(shared `ctypes` prototype tables), and a surface that cannot be screenshotted
hid three defects behind one operator report. Compose surfaces in smokes, and
instrument what cannot be photographed.

After this, `GDA-DEMO-003` returned to paused and `GDA-FC-004` freeze
validation completed locally. The exact freeze result is recorded below.

The complete Chrome-to-Word Demo must not be restarted until a separate live
evidence plan is declared.

Do not wire provider prose, tool-budget counts, or raw task text into the
checklist. Do not add another Runner/MCP dispatch path. Do not treat a provider
step callback as execution authority or durable side-effect evidence. Do not
run the full Chrome-to-Word Demo until the offline lifecycle tests pass and a
separate live evidence plan has been declared. Presence remains
capture-excluded by design.

## Full Cycle freeze handoff (2026-08-02)

Local `main` was fast-forwarded to the three presence commits without rewriting
them. Clean release preflight then passed at
`324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`, with the same start/end commit and
clean source at both endpoints: CPython 3.13.7, report schema 5, the full
pytest/Ruff/diff gates, 13/13 E1/E2 cases, 15 crash-reconstruction cases, 9
stateless-replay cases, and clean wheel build/install all passed. The dated
pytest count is retained in `PROJECT_STATUS.md`; the sanitized report SHA-256 is
`dc78f08030b4d3c4fac255a91fb7badf2b06fdb0eb0c487073e1f825260c6d0e`.

The candidate manifest SHA-256 remains
`6abe3431ea0e6b4065f21e9a6c6fe34de772f9c3c86a2437f8d14f95a5d6f522`.
The Full Cycle repository records the matching freeze SHA and all contract
versions in `baseline/runtime-freeze-v1.json`; its old `FC-BRIDGE-001` fixture
continues to name `8ace897` as immutable generation provenance.

No Runtime item is active. Continue `FC-MVP-001` in the Full Cycle repository.
Do not resume Runtime feature work, Lane B, or a paused HUD issue unless
`PROJECT_STATUS.md` explicitly changes the active scope.

### 2026-08-03 bounded Demo action-presentation closure

The user explicitly reopened one bounded item, `GDA-DEMO-004`, after the HUD
closure. It adds `fast`, `normal`, and `deliberate` Host-owned presentation
profiles plus a capture-excluded high-contrast pointer ring and content-free
keyboard activity badge. Unset Runtime timing is unchanged. The profile can
only slow presentation; it does not shorten or bypass observation, approval,
human-idle readiness, policy, budgets, re-observation, or verification. The
feedback protocol accepts fixed activity classes only and cannot receive typed
text, a key combination, model prose, or tool-result text.

The native Win32 probe passed paint, visibility, click-through/no-activate,
capture-exclusion, foreground-preservation, and live typing-progress checks.
Retained caret-following deliberate-mode run
`cross-app-demo-20260803-043417-697826` then passed with 17 tool calls,
seven approved side effects, durable DOCX verification, and complete exact
window cleanup. The full offline gate, Ruff, mypy, documentation consistency,
and diff checks passed; the dated totals are retained in
`docs/DEMO_ACTION_PRESENTATION_EVIDENCE_2026-08-03.md`.

No Runtime item is active. Do not infer that Demo closure automatically resumes
Full Cycle. The consumer is paused after merged PRs #10 and #11; its three
uncommitted BF16 merge-probe files remain preserved and unpublished until the
user explicitly resumes that work.

The user then proposed, but did not merge into this presentation item, a
cooperative desktop-authority lifecycle. Track it only as proposed
`GDA-DEMO-005`: never block physical input; expose an explicit operator pause or
takeover; pause at a known safe boundary; require a fresh observation and
explicit resume; and keep an interrupted possibly-dispatched action in unknown
outcome. The generic Decision Card already compiles approve, re-observe, defer,
deny, and human-takeover semantics, but the ordinary approval port offers only
the first four, and the deterministic Demo provider cannot currently recover
from re-observe or resume a defer. Those integration gaps are the bounded work,
not a reason to weaken the existing side-effect contract.

### 2026-08-03 model-driven Demo reopening

The user explicitly reopened bounded `GDA-DEMO-006` because the deterministic
Chrome-to-Word provider demonstrates Runtime execution but not Agent adaptation.
The live CLI now defaults to `--mode model` and requires an explicit OpenAI or
Claude model ID. `CrossAppDemoProvider` remains available through
`--mode controlled` as the deterministic E1 regression baseline.

The model-driven path is not an unconstrained script. A closed provider prompt
asks the model to choose zero or one next tool from fresh evidence, while a
Host-owned guard rejects any request outside the exact launched Chrome and Word
fixtures, semantic refs, reviewed key set, bounded model-authored source brief,
source UIA/text prerequisite, one-call-per-turn limit, and post-save durable
content verification. The live path reads the real public Microsoft Support
article and does not substitute a prewritten Host answer; the deterministic
provider remains the only fixed-content regression path.
Runner remains the sole policy, grounding, approval, budget, persistence, and
MCP dispatch authority. Provider prose is discarded and cannot establish Demo
completion. Do not claim provider or application evidence until an explicit
opt-in reviewed-model run is retained; the current implementation is offline
evidence only. The paused Full Cycle resume point and proposed `GDA-DEMO-005`
cooperative takeover item remain unchanged.

### 2026-08-03 fixture-cleanup review hardening

The exact-process cleanup contract now requires three consecutive observations
with no visible top-level window before recording `windows_closed`; a window
that reappears resets the count. Visible owned dialogs are unresolved operator
choices, so cleanup records `handoff_required` without terminating that process.
Unexpected adapter/process exceptions are isolated to one retained PID and do
not skip the remaining cleanup targets. `Win32ProcessWindows` uses its own
private `user32` prototype table.

New `final-state.json` records use schema v3. They deliberately separate
`window_cleanup_complete`, `all_processes_exited`, and
`operator_handoff_required`, and each fixture records
`window_cleanup_verified`. They also retain bounded proposal-rejection facts and
the exact owned-dialog resolution (`saved`, `discarded`, or `unresolved`). A
known-not-dispatched model proposal may be returned to the same provider for at
most two corrections; the HUD shows that replanning state, while unknown
outcomes still stop. Do not summarize this as every process having exited.
The hardening passed the repository's full offline validation gate but has not
promoted new Chrome or Word evidence. The next task remains the fresh
operator-ready `GDA-DEMO-006` model run, and the paused Full Cycle resume point
is unchanged.

### 2026-08-03 project permission mode

The Host now has three project-wide modes: default `read_only`, per-side-effect
`approved_actions`, and explicit `agentic_actions`. Agentic mode requires both
`mode = "agentic_actions"` and `require_approval_for_actions = false`; provider
adapters then expose reviewed action tools and Runner permits safety-ready
side effects without calling the approval port. Runner still owns safety
baseline checks, current-generation grounding, side-effect budgets, serialized
MCP dispatch, WAL/result validation, and mandatory post-action observation.
Unknown outcomes still stop and are never replayed.

Keep MCP in `safe_local` for this mode. This retains the foreground allowlist,
human-activity wait, dangerous-click confirmation, E-stop, and audit. Do not
use MCP `full_control_local` as a synonym for agentic behavior: it bypasses the
foreground allowlist and human-activity yielding. The bounded model-driven Demo
defaults to `agentic_actions`, accepts `--permission-mode approved_actions` for
per-action compatibility, and records the selected mode in `final-state.json`.

Decision Card labels and resume compilation are shared project code. The
Demo-specific defer compatibility loop offers `Resume agent`, `Keep paused`,
and `Stop task`; resume becomes a zero-dispatch re-observe decision. There is
not yet a general manual pause/resume hotkey for `agentic_actions`: physical
input temporarily holds MCP dispatch and resumes after stable idle, while the
configured E-stop remains the hard fallback. Do not claim the general manual
control lifecycle complete until that explicit boundary is implemented.

The complete offline gate after this change passed: pytest, Ruff, mypy, docs
consistency, and `git diff --check` were all clean. The dated running totals are
owned by `PROJECT_STATUS.md`. This is offline contract evidence only; the exact
next action is a fresh model-driven Demo run in default agentic mode. Full Cycle
remains paused at its recorded resume point.

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
  fullcycle_export.py  versioned manifest and redacted run-export producer
  executor*.py         internal observation/final runtime and local reconciliation
  planned_observation_runtime.py fixed observation-only CLI composition
  campaign*.py         offline campaign control state and preflights
  discovery_adapters.py declarative bounded stable-identity extraction rules
  application_*discovery*.py generic durable discovery ledger and one-pass runtime
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

When the repository is in closure mode, start with
[Project status](PROJECT_STATUS.md). It owns the single active `GDA-FC-*` item,
the freeze scope, and the exact next task. For Full Cycle bridge work, then read
[the integration contract](docs/FULLCYCLE_INTEGRATION.md). Do not infer active
work from the branch name or the broad roadmap.

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
  focus-taking Win32 adapter yields authority first, exposes only digest-bound
  evidence, and only its fresh exact-effect selection can become an allowing
  request-bound `PolicyDecision`; re-observe, defer, and denial remain
  zero-side-effect decisions. Re-observe must abandon the stale provider turn
  and refresh reviewed evidence. Defer persists `PAUSED` but is not permission
  to resume post-provider state. Never add a second
  dispatch path, global/batch allow, or model-selected approval. Its bounded
  native focus/timeout result is retained in
  [Decision Card evidence](docs/DECISION_CARD_WINDOW_EVIDENCE.md).
- Retain standalone presence desktop results in
  [presence evidence](docs/PRESENCE_WINDOW_EVIDENCE.md). Ordinary `run`/`resume`
  now have default-off, fail-silent durable-phase wiring; do not infer planned,
  campaign, recovery, multi-monitor, or abrupt-process support from it.
- Keep host completion polling synchronized across
  [long-running tasks](docs/LONG_RUNNING_TASKS.md),
  [operator experience](docs/OPERATOR_EXPERIENCE.md), the roadmap, and the
  capability dashboard. Mobile delivery belongs to the Codex/Claude host; do
  not add it to the thirteen-tool desktop MCP surface or treat MCP logs as terminal
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
