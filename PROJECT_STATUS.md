# Project status

> **Mode: `GDA-DOCS-005` Demo/application-roadmap alignment is implementation-
> complete and remains the sole active publication item until this exact
> revision reaches `main` through a clear PR.** On merged `main`, it is complete
> and no executable repository item is active.
> **Exact next on merged `main`:** stop for user review. The proposed first
> implementation slice is `GDA-DEMO-007A`, a versioned offline Demo scenario and
> `TaskIntent` contract with zero provider, MCP, desktop, or application work;
> it is not active until the user explicitly authorizes it.
> The Full Cycle Runtime baseline remains frozen at
> `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`; consumer work remains paused.
> No Demo acceptance item is active. `GDA-DEMO-006` remains retired under tag
> `archive/gda-demo-006-pr231-5c403a5`. L5 remains inactive.
> Updated: 2026-08-12.

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

## Current authorization

| ID | State | Bounded outcome | Acceptance and stop condition |
| --- | --- | --- | --- |
| `GDA-DOCS-005` | Implementation and local review complete; publication active | Make the current Formal Demo decision, application-coverage program, future Universal GUI showcase, architecture/front-door plan, and user instruction entry point unambiguous | One Formal Demo v1 owner, independent application coverage, future-only Universal GUI showcase, Chinese user front door, current/planned architecture, and Runner/tool impact map are synchronized. Complete local gate: `2537 passed, 38 skipped`, Ruff, mypy over 167 source files, docs consistency over 13 reviewed tools, diff check, and independent truth/link/safety reviews. Publish only through a clear PR; on merged `main`, this row is complete and the exact next remains user review. Documentation only: no Runtime, Runner, MCP, tool/schema, provider, desktop, application, evidence, Full Cycle, L5, E4, or release behavior changes |

No other row is active. A branch name, archived plan, capability gate, or dated
evidence record is never permission to start another item.

## Exact next and preserved resume points

| Track | Current state | Next permitted action |
| --- | --- | --- |
| Cloud provider E3 | Preserved resume point; waiting for another user-created supported regional account | With matching authorization, run one exact provider/model/region harmless fake-MCP E3 matrix and repair only reproduced incompatibilities. Never inherit evidence across routes, regions, or models |
| Local provider E3 | Deferred by the user | None until the user explicitly resumes one named loopback server/model scope |
| Full Cycle | Runtime freeze complete; consumer paused | Resume only on explicit user direction. Lane B / `FC-BRIDGE-003` still requires its separate consent, security, and privacy review |
| [Formal Demo v1](docs/FORMAL_DEMO_V1.md) | Product direction selected; contract, Console, generic Scope Sheet, launcher, application adapters, and formal evidence are not implemented | After this documentation merge, stop for review. If explicitly activated, begin only with proposed `GDA-DEMO-007A`: versioned `DemoScenarioSpec`, `TaskIntent`, reviewed role profiles, generic Scope Sheet, deterministic digest, and offline fail-closed tests. Do not restore retired `GDA-DEMO-006` or infer application/Universal GUI acceptance |
| [Application coverage](docs/APPLICATION_EVALUATION_MATRIX.md) | Planned evidence program, not active | BOSS, Google Docs, WeChat, and their legacy cross-application scenario remain representative Coverage Set A cases. They do not define the Formal Demo story or project priority; promote each case only through its own retained gates |
| [Universal GUI final showcase](docs/UNIVERSAL_GUI_DEMO.md) | Future final integration gate, not active | Assemble only after selected application, safety, authority, observation, operator-UX, and enterprise gates retain executable evidence. Its 3-minute edit is not Formal Demo v1 |
| Hierarchical control and learning | H1-H8 and L0-L4 complete only at their recorded bounded offline or injected-runtime scopes; L5 inactive | L5 requires separate privacy, security, evaluation, deployment, and rollback consent |
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
| `GDA-DOCS-004B` | Complete; merged | Compact current status and archive chronology | Commit `60a18b4`; PR #351 passed wheel plus Python 3.11/3.12/3.13 with no review, comment, unresolved thread, conflict, or head drift and merged as `3dc8183`; both branch copies were removed. Local gate: `2537 passed, 38 skipped`, Ruff, mypy-167, docs-13, compact-status bound, diff check, and independent truth/link/safety reviews. No executable row remains active; the regional-account provider-E3 wait state is exact next |
| `GDA-DOCS-005` | Implementation and local review complete; publication active | Align Formal Demo, application coverage, future showcase, architecture/front-door, and user-guidance owners | Active row above owns the final publication gate. Preserve the cloud-provider E3 and every other resume point; stop for user review after a clear merge rather than silently starting `GDA-DEMO-007A` |

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
