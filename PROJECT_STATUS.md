# Project status

> **Mode:** `GDA-DOCS-004B` implementation and local review are complete on
> this feature branch. Until this revision reaches `main` through a clear PR,
> publication is the sole active action. Once merged, no executable repository
> item is active.
> **Exact next on merged `main`:** wait for one user-created supported
> regional account, then run one exact provider/model/region harmless fake-MCP
> E3 matrix. If matching authority is absent, stop; do not substitute local E3,
> E4, release, application, Demo, Full Cycle, or L5 work.
> The Full Cycle Runtime baseline remains frozen at
> `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`; consumer work remains paused.
> No Demo acceptance item is active. `GDA-DEMO-006` remains retired under tag
> `archive/gda-demo-006-pr231-5c403a5`. L5 remains inactive.
> Updated: 2026-08-11.

This file is the single operational task registry. The complete pre-compaction
closure and decision chronology is preserved in the
[2026-08-11 status snapshot](docs/archive/PROJECT_STATUS_SNAPSHOT_2026-08-11.md).
That archive is historical context, not a second tracker.

## Ownership and reading order

1. This file alone owns the active item, exact next action, and safe resume
   points.
2. [Capability status](docs/CAPABILITY_STATUS.md) owns evidence truth and next
   capability-specific gates; it does not activate work.
3. Current behavior is owned by the linked contract documents. Dated evidence
   proves only its recorded scope.
4. [Execution plan](docs/EXECUTION_PLAN.md) retains dependency ordering and
   future design, not operational priority.
5. Files under `docs/archive/` and archive tags are non-normative and never
   authorize resumption.

## Current item

| ID | State | Bounded outcome | Acceptance and stop condition |
| --- | --- | --- | --- |
| `GDA-DOCS-004B` | Implementation and local review complete; publication is the sole active action off `main`; complete on `main` after a clear merge | Separate current operational status from closure/decision chronology, while preserving every historical record and owner boundary | The pre-compaction tracker is archived; the compact root entry retains current item/resume points/baseline/invariants/closure/gates; direct historical-row links are repaired; the complete local repository gate and independent truth/link/safety reviews pass. Publish through a clear PR, then stop at the regional-account wait state. Documentation only: no Runtime/tool/test/evidence behavior, capability promotion, provider/live/application/E4/release scope, Full Cycle authority, Demo archive, L5, or second tracker |

No other row is active. Once this exact revision reaches `main` through a clear
merge, this row is complete and no executable row is active. A branch name,
archived plan, capability gate, or dated evidence record is never permission to
start another item.

## Exact next and preserved resume points

| Track | Current state | Next permitted action |
| --- | --- | --- |
| Cloud provider E3 | Preserved resume point; waiting for another user-created supported regional account | With matching authorization, run one exact provider/model/region harmless fake-MCP E3 matrix and repair only reproduced incompatibilities. Never inherit evidence across routes, regions, or models |
| Local provider E3 | Deferred by the user | None until the user explicitly resumes one named loopback server/model scope |
| Full Cycle | Runtime freeze complete; consumer paused | Resume only on explicit user direction. Lane B / `FC-BRIDGE-003` still requires its separate consent, security, and privacy review |
| Demo | No active acceptance item | Any new Demo starts from current `main` under a new explicit scope. Do not restore retired `GDA-DEMO-006` or infer Universal GUI acceptance |
| Hierarchical control and learning | H1-H8 and L0-L4 complete only at their recorded bounded offline or injected-runtime scopes; L5 inactive | L5 requires separate privacy, security, evaluation, deployment, and rollback consent |
| Wave 1 applications | Planned acceptance, not active | If explicitly activated later: one on-device BOSS UIA/document-text semantic item, separate OCR-baseline review, 100-item BOSS gate, then Google Docs, WeChat draft-only, and cross-application evidence |
| E4 and release | Deferred | Rebuild any future candidate from then-current `main`; rerun every named gate and obtain explicit approval or waiver |

## Product boundary now

The repository is an experimental Windows-only, supervised foreground desktop
Runtime and Agent Host. The first-release boundary includes installed setup and
doctor flows, read-only Desktop Ask, one fixed public-browser-to-disposable-Word
workflow, and bounded CLI-first review/control/status surfaces. Exact behavior
and limitations are mapped in [Project overview](docs/PROJECT_OVERVIEW.md).

The MCP server and existing Runner remain the only desktop dispatch path.
Thirteen core tools are reviewed; one configured optional rendered-browser
observer is read-only and does not change the core registry. The manifest-routed
general campaign worker exists internally and is offline verified, but it has no
generic retained provider/application result and is not a background daemon,
public scheduler, plugin host, or mobile gateway.

This repository does not currently claim universal GUI coverage, unattended or
parallel control of the operator's desktop, arbitrary application support,
Multi-Agent operation, automatic learning/model training, non-Windows drivers,
mobile completion delivery, E4-complete current-candidate release readiness, or
production safety.

## Current baseline

| Fact | Current state |
| --- | --- |
| Product | Experimental Windows-only foreground desktop MCP Runtime and Agent Host |
| Desktop authority | Sole Runner -> stdio MCP -> Windows Driver path; model output remains untrusted data |
| Tool surface | 13 reviewed core tools plus one configured optional read-only browser observer |
| Contracts | Driver `1.0.0`; Agent `0.1.0`; redacted trace/checkpoint version `1` |
| Providers | Nine implemented profiles: eight cloud identities plus loopback-only `local_openai`. Retained exact E3 scopes are listed in [Capability status](docs/CAPABILITY_STATUS.md) and [E3 evidence](docs/E3_EVIDENCE.md); sibling routes/models and local E3 remain unverified or deferred |
| Campaign | Manifest-routed general worker implemented/internal/offline-only; BOSS has narrower retained identity/restart evidence; semantic and 100-item gates remain open |
| Control and learning | H1-H8 and L0-L4 complete only at their recorded bounded scopes; no automatic promotion, training, or broad application claim |
| Full Cycle | Lane A and freeze validation complete; baseline `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9` frozen; consumer paused; Lane B separately deferred |
| Latest complete local gate | `2537 passed, 38 skipped`; Ruff; mypy over 167 source files; docs consistency over 13 reviewed tools; 2026-08-11. This is a dated snapshot, not permanent capability evidence |

## Non-negotiable invariants

- The MCP server and existing Runner remain the only desktop dispatch path.
- Model output is untrusted data, never authority.
- Unknown side-effect outcomes are never automatically replayed.
- Refs never silently degrade to coordinates.
- Policy, approval, grounding, budgets, audit, and mandatory post-action
  observation remain Host/Runner-owned.
- New exports are read-only, bounded, versioned, redacted, and fail closed.
- API keys, tokens, memory, continuations, screenshots, raw tasks, model prose,
  and raw tool-result text never enter the automatic Full Cycle export.
- Offline tests cannot promote provider, desktop, application, E4, or release
  evidence.
- During real desktop tests, possible operator mouse/keyboard/focus interference
  invalidates the attempt until a fresh observation and rerun; diagnose code
  only when trace, window, and timing evidence exclude intervention.

## Closure backlog

All closure rows and decision records through merge `b3fefde` remain
content-preserved, with relative links rebased, in the
[pre-compaction snapshot](docs/archive/PROJECT_STATUS_SNAPSHOT_2026-08-11.md#closure-backlog).
The compact table below records work completed after that snapshot or needed for
the current handoff.

| ID | State | Outcome | Completion evidence / next handoff |
| --- | --- | --- | --- |
| `GDA-DOCS-004A` | Complete; merged | Reconciled current truth across tracker and owner documents | Commit `e3308a8`; PR #350 passed wheel plus Python 3.11/3.12/3.13 with zero review, comment, or unresolved thread and merged as `b3fefde`; both branch copies were removed. Local gate: `2537 passed, 38 skipped`, Ruff, mypy-167, docs-13, 400-line status, diff check, and independent truth/editorial/safety reviews. No Runtime/tool behavior or evidence level changed |
| `GDA-DOCS-004B` | Implementation and local review complete; publication pending off `main`; complete on merged `main` | Compact current status and archive chronology | Local gate: `2537 passed, 38 skipped`, Ruff, mypy-167, docs-13, compact-status bound, diff check, and independent truth/link/safety reviews. After a clear merge, no executable row remains active and the regional-account provider-E3 wait state is exact next |

## Session protocol

At the beginning of every session:

1. Read `AGENTS.md` or `CLAUDE.md`.
2. Read this file.
3. Read only the owner documents linked by the current item or exact next.
4. Run `git status --short --branch`.
5. Confirm that no more than one active item is authorized. If none is active,
   wait for the authority named by the exact next action; do not invent work.

At the end of every session:

1. Run the active item's validation commands.
2. When closing active work, update exactly one Closure backlog row plus the
   header/current item.
3. Record durable maintainer facts in `HANDOFF.md` only when needed.
4. Do not rewrite dated evidence or promote capability without its required run.
5. Leave modified files, exact validation/results, limitations, and one next
   action.

## Validation gate

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe scripts\check_docs_consistency.py
git diff --check
```

On-device smokes are not routine closure checks. Run them only under an explicit
evidence plan on a non-sensitive desktop.

## Current binding decisions

- `main` is the only persistent development branch. Each bounded change uses a
  feature branch, merges only through a clear PR, then deletes both branch
  copies.
- Scope detours preserve the frozen Full Cycle state, data-lane boundaries,
  provider resume point, and exact next action in this file.
- Historical snapshots, archived plans, and archive tags are recoverability
  records, not resumable candidates or capability evidence.
- If authority is missing, the active item is ambiguous, or checks/reviews/
  conflicts are unresolved, stop instead of selecting adjacent work.
