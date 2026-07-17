# Maintainer handoff

> **Internal engineering notes.** This file preserves operational knowledge for
> maintainers. It is not the product specification; start with
> [README.md](README.md) and [docs/README.md](docs/README.md) for the current
> public documentation.

## Current shape

The codebase has two executable surfaces. The public baseline is an
experimental Windows-only MCP server with eight tools, a typed Driver Contract
v1.0.0, and one in-process Windows implementation. The second is an
experimental `computer-use-agent` Host with a dual-provider read-only loop,
explicit memory, traces/evaluation, bounded recovery, and fake-verified approved
actions. Provider E3 and isolated desktop E4 evidence are not retained.

Planner/Executor and Campaign packages also contain substantial offline-tested
control logic. One fixed synthetic claimed campaign item can now execute a
single `list_windows` observation through the existing Runner boundary, persist
`OBSERVED`, reduce the bounded result to a non-sensitive window count, persist
`EXTRACTED`, verify its canonical JSON digest, persist `COMMITTED`, close the
batch with measured usage, write deterministic handoff, and transfer ownership
to a fresh Runner run that reconstructs the finished session from durable
campaign records and reaches the expected exhausted resume decision. No
campaign CLI or complete application workflow is connected. The broader universal GUI,
operator UI, cross-application demo, and continual-learning layers remain
planned. Start with [Capability status](docs/CAPABILITY_STATUS.md) and read the
status header of every owner document before treating it as available.

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
  dpi.py               DPI-awareness bootstrap
  drivers/windows.py   UIA, Win32, capture, process ownership

src/computer_use_agent/
  runner.py            sole Agent tool-dispatch authority boundary
  providers/           OpenAI and Claude adapters
  planning.py          bounded declarative planning contracts
  executor*.py         internal observation/final runtime and reconciliation
  campaign*.py         offline campaign control state and preflights
  continuation*.py     private bounded crash evidence and recovery

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
10. **Window activation was reproduced, repaired, and unit tested, but still
    needs retained isolated evidence.** The driver now attaches the required
    input queues, restores minimized targets, releases attachments in `finally`,
    and verifies the foreground HWND. Treat the E4 Windows regression matrix,
    not another speculative rewrite, as P0.
11. **Interactive UIA is not document text.** The BOSS probe exposed useful
    controls while static job-description content was absent. Use the planned
    observation ladder rather than assuming a full UIA snapshot contains page
    content.

## Starting a fresh maintenance session

For long-running feature work, read only the documents needed for the current
layer:

1. [Capability status](docs/CAPABILITY_STATUS.md) for the shortest current
   implemented/evidence/next-gate view.
2. [Operator session notes](docs/OPERATOR_SESSION_NOTES.md) for sanitized live
   evidence and unresolved validation gaps.
3. [Roadmap](docs/EXECUTION_PLAN.md) for P0/P1 ordering.
4. [Long-running tasks](docs/LONG_RUNNING_TASKS.md) for campaigns, item ledgers,
   batching, and cross-session handoff.
5. [Application evaluation matrix](docs/APPLICATION_EVALUATION_MATRIX.md) for
   the BOSS, Google Docs, WeChat, Douyin real-time-media, enterprise workflow,
   and cross-application acceptance cases.
6. [Token efficiency](docs/TOKEN_EFFICIENCY.md) and
   [Observation contract](docs/OBSERVATION_CONTRACT.md) for model-context and
   perception changes.
7. [Operator experience](docs/OPERATOR_EXPERIENCE.md) for the planned
   computer-use presence indicator and Decision Cards, then
   [Operator progress viewer](docs/PROGRESS_VIEWER.md) for the passive Windows
   status projection.
8. [Universal GUI demo](docs/UNIVERSAL_GUI_DEMO.md) only when assembling the
   final chaptered showcase and retained evidence package; it is not a shortcut
   around the narrower application and safety gates.
9. [Continual learning](docs/CONTINUAL_LEARNING.md) for the planned progression
   from explicit memory through verified workflow promotion and cost-aware
   strategy selection; it does not describe current runtime behavior.

The campaign control plane can validate `campaign_id`, manifest, ledgers, and
`handoff.json`. Its first internal execution seam is limited to the exact
synthetic observation-through-restart/resume described above. The replacement
run accepts no task text or prior `BatchSession`, performs no provider or MCP
call, and leaves campaign completion and heartbeat retirement untouched. A
general worker and CLI remain unconnected. Use these documents as the
cross-session source of truth.

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
- Keep planned automatic extraction and strategy-learning claims synchronized
  across [context and memory](docs/CONTEXT_MEMORY.md),
  [continual learning](docs/CONTINUAL_LEARNING.md), the roadmap, and the
  universal demo.
- Keep contract changes synchronized with `contract.py`.
- Keep superseded plans and implementation chronology under `docs/archive/`;
  archived files are non-normative and must point to their current owner.

Avoid restoring sentence-by-sentence bilingual copies; they obscure the current
status and create needless translation drift.
