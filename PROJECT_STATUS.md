# Project status

> **Mode: one executable repository item is active.** `GDA-MAINT-003` was
> activated by the user on 2026-09-01 after the `GDA-MAINT-002` tracker
> closeout merged through PR #370 as `8c3f9a9` and passed merge-main CI.
> **Exact next:** complete only the first `computer_use_agent.tool_registry`
> schema-typing tranche. Resolve the 41 independently reproduced
> schema-construction `dict-item` errors plus the one schema-export error and
> remove the stale export `type: ignore`. Exact schema JSON and registry digests
> must remain unchanged. Do not add a cast, `type: ignore`, or module exemption;
> stop before the six descriptor-narrowing errors, the 46 argument-validation
> errors, or any Runtime/schema/data-lane/live change.
> The exact `GDA-DEMO-007F` Provider gate remains paused until a current
> account/data-controls preflight and process-local `OPENAI_API_KEY` are both
> supplied; no `GDA-DEMO-007F`-specific Provider evidence exists yet. General
> E3, `START`, Console live-mode exposure, executable role adapters,
> Runner/MCP/desktop/application work, durable execution, and the complete
> Formal Demo remain inactive.
> The Full Cycle Runtime baseline remains frozen at
> `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`; consumer work remains paused.
> No live Formal Demo acceptance or evidence run is active. `GDA-DEMO-006` remains retired under tag
> `archive/gda-demo-006-pr231-5c403a5`. L5 remains inactive.
> Updated: 2026-09-01.

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
| `GDA-MAINT-003` | Active | Remove only the first 42 schema construction/export typing errors from `computer_use_agent.tool_registry` without changing its reviewed contracts | Acceptance requires typed schema constants, explicit fail-closed object narrowing for the exported schema copies, removal of the stale export ignore, an isolated diagnostic proving exactly the six descriptor plus 46 argument-validation errors remain, canonical schema-JSON and core/optional registry-digest zero-drift tests, and the complete repository gate. Stop on a cast, new ignore/exemption, descriptor/argument-validation edit, changed schema/digest/Runtime/data lane, live surface, or any failing/unresolved PR state |

A branch name, archived plan, capability gate, or dated evidence record is
never permission to start another item.

## Exact next and preserved resume points

| Track | Current state | Next permitted action |
| --- | --- | --- |
| Core type debt | `GDA-MAINT-003` is the only active tranche. `computer_use_agent.types` has no module exemption. A follow-import isolated diagnostic for `computer_use_agent.tool_registry` reports 94 errors: 41 schema-construction `dict-item`, one schema-export, six descriptor-narrowing, and 46 argument-validation errors | Resolve only the first 42 schema construction/export errors. Remove the stale export ignore, add no cast/ignore/exemption, prove exact schema JSON and registry-digest zero drift, and stop with the six descriptor plus 46 argument-validation errors unchanged for separately activated tranches |
| Formal Demo Provider gate | `GDA-DEMO-007F` is Implemented/Offline complete and merged for the exact OpenAI tuple; no credential was configured, no live call ran, and this is not general E3 ordinary tool-cycle evidence | Wait for the exact current account/data-controls preflight plus process-local credential injection. If both are supplied, run only the separately gated one-call TaskIntent check; never inherit evidence across accounts, routes, regions, or models |
| Local provider E3 | The prior blanket deferral was lifted, but no loopback server/model row is active | None until a named loopback server/model scope becomes the single active row |
| Full Cycle | Runtime freeze complete; consumer paused | Resume only on explicit user direction. Lane B / `FC-BRIDGE-003` still requires its separate consent, security, and privacy review |
| [Formal Demo v1](docs/FORMAL_DEMO_V1.md) | `GDA-DEMO-007A` through `GDA-DEMO-007F` merged. The exact OpenAI intent/Scope adapter is Implemented/Offline only; its live Provider gate has not run. Native `Start` remains disabled | Wait for the exact current account/data-controls preflight plus process credential before the one-call `007F` gate. Free-form intent on the Console, executable role adapters, `START`, Runner/MCP/desktop/application work, durable composition, and formal evidence remain inactive |
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
| Latest complete local gate | `2858 passed, 39 skipped`; Ruff; mypy over 176 source files; docs consistency over 13 reviewed tools; diff check; clean hash-lock bootstrap and dependency check; locked wheel build; 2026-09-01. This is a dated offline repository snapshot, not `GDA-DEMO-007F`-specific Provider, desktop, application, E4, release, human-accessibility, or permanent capability evidence |

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
| `GDA-MAINT-002` | Complete; merged | Remove the whole-module mypy exemption from `computer_use_agent.types` without changing valid behavior or serialization | Commit `157d5ab`; PR #369 passed wheel plus Python 3.11/3.12/3.13 with zero review, comment, requested change, unresolved thread, conflict, or head drift, merged as `730d715`, removed both feature-branch copies, and passed merge-main CI run `33464339922`. Four independently reproduced errors were closed with explicit fail-closed LedgerEvent invariant checks; no cast or `type: ignore` was added, only the `computer_use_agent.types` exemption was removed, and the dependency-lock body remained unchanged. Six defense-in-depth cases joined the `39 passed` focused types/trace/environment gate. Full local gate: `2858 passed, 39 skipped`; Ruff; mypy-176; docs-13; diff check; clean hash-lock bootstrap and dependency check; locked wheel build. No valid Runtime, serialized output, schema, data-lane, Runner/recovery/driver, Provider, desktop, or application behavior changed, and no live test ran |
| `GDA-MAINT-001` | Complete; merged | Harden repository documentation and CI truth without changing product behavior | Commit `79b7ff1`; PR #367 preserved all four required check contexts, passed wheel plus Python 3.11/3.12/3.13, had zero review, comment, requested change, unresolved thread, conflict, or head drift, and merged as `a6a45d0`; both feature-branch copies were removed. Owner-derived Formal Demo summary checks and negative tests, LF/binary attributes, immutable-SHA Actions, a hash-locked Python 3.13 main gate, separate scheduled/manual floating canary, one 3.13 static/stress/report pass, retained compatibility matrix, and contract tests are complete. Local gate: `2852 passed, 39 skipped`; Ruff; mypy-176; docs-13; diff check; clean hash-lock bootstrap and dependency check; focused `16 passed`; locked wheel build; crash `22 passed`; replay `11 passed`; eval `13/13` with zero safety escapes. No Runtime behavior changed and no live Provider/desktop/application test ran |
| `GDA-DOCS-004A` | Complete; merged | Reconciled current truth across tracker and owner documents | Commit `e3308a8`; PR #350 passed wheel plus Python 3.11/3.12/3.13 with zero review, comment, or unresolved thread and merged as `b3fefde`; both branch copies were removed. Local gate: `2537 passed, 38 skipped`, Ruff, mypy-167, docs-13, 400-line status, diff check, and independent truth/editorial/safety reviews. No Runtime/tool behavior or evidence level changed |
| `GDA-DOCS-004B` | Complete; merged | Compact current status and archive chronology | Commit `60a18b4`; PR #351 passed wheel plus Python 3.11/3.12/3.13 with no review, comment, unresolved thread, conflict, or head drift and merged as `3dc8183`; both branch copies were removed. Local gate: `2537 passed, 38 skipped`, Ruff, mypy-167, docs-13, compact-status bound, diff check, and independent truth/link/safety reviews. No executable row remains active; the regional-account provider-E3 wait state is exact next |
| `GDA-DOCS-005` | Complete; merged | Align Formal Demo, application coverage, future showcase, architecture/front-door, and user-guidance owners | Commit `6194c23`; PR #353 passed wheel plus Python 3.11/3.12/3.13 with zero review, comment, requested change, unresolved thread, conflict, or head drift and merged as `983ac0d`; both feature-branch copies were removed. Local gate: `2537 passed, 38 skipped`, Ruff, mypy over 167 source files, docs consistency over 13 reviewed tools, diff check, and independent truth/link/safety reviews. No Runtime, Runner, MCP, tool/schema, provider, desktop, application, evidence, Full Cycle, L5, E4, or release behavior changed; stop for user review rather than silently starting `GDA-DEMO-007A` |
| `GDA-DEMO-007A` | Complete; merged | Add the first inert internal Formal Demo v1 contract slice | Commit `48249cb`; PR #355 passed wheel plus Python 3.11/3.12/3.13 with zero comment, review, requested change, unresolved thread, conflict, or head drift and merged as `0514906`; both implementation-branch copies were removed. Four strict versioned data contracts, Host-reviewed exact pins, canonical digest/bounds, required reload pins, fail-closed compiler/loaders, and 57 focused tests were added without execution ports. Full local gate: `2594 passed, 38 skipped`; Ruff; mypy over 168 source files; docs-13; diff check; independent contract, safety/docs, and test/packaging reviews found no blocker. Provider/Desktop/Application remain `NO`; no Console, provider request, Runner/MCP/Driver startup, desktop/application access, launcher, live Demo evidence, Full Cycle change, L5, E4, or release promotion occurred |
| `GDA-DEMO-007B` | Complete; merged | Add the pure-local typed intent disclosure and exact `COMPILE` permit boundary | Commit `66203be`; PR #357 passed wheel plus Python 3.11/3.12/3.13 with zero comment, review, requested change, unresolved thread, conflict, or head drift and merged as `cab2327`; both implementation-branch copies were removed. Exact static-routing-rule validation, conservative reviewed warning pins, sensitive local rendering, digest binding, one issue/consume per in-memory gate instance, returned-record tamper/drift, concurrency, same-gate replay, and no-port behavior are covered by 46 new gate tests within the 103-test combined `GDA-DEMO-007A`/`007B` focused set. Full local gate: `2640 passed, 38 skipped`; Ruff; mypy over 169 source files; docs-13; diff check; wheel inspection; independent contract/security, owner/capability, and test/packaging reviews found no blocker. Provider/Desktop/Application remain `NO`; no serialized gate loader, Console, provider request, Runner/MCP/Driver startup, desktop/application access, persistence, launcher, live Demo evidence, Full Cycle change, L5, E4, or release promotion occurred |
| `GDA-DEMO-007C` | Complete; merged | Add a provider-neutral offline one-attempt `TaskIntent` coordinator behind the local permit | Commit `c1c5e82`; PR #359 passed wheel plus Python 3.11/3.12/3.13 with zero comment, review, requested change, unresolved thread, conflict, or head drift and merged as `2ade92b`; both implementation-branch copies were removed. Fixed reviewed-scenario pins and detached snapshots, strict post-construction `TaskIntent` rebuilding, descriptor-safe consume-before-call ordering, forced-overlap one-call concurrency, terminal no-retry behavior, and raw exception-context sanitization are covered by the 137-test combined `GDA-DEMO-007A`/`007B`/`007C` focused set. Full local gate: `2674 passed, 38 skipped`; Ruff; mypy over 170 source files; docs-13; diff check; wheel inspection; independent security, test/packaging, and docs/capability reviews found no blocker. Provider/Desktop/Application remain `NO`; no concrete provider port, credential/config/environment read, network, Console, persistence, Runner/MCP/Driver startup, desktop/application access, Full Cycle change, E3, E4, release, or evidence promotion occurred |
| `GDA-DEMO-007D` | Complete; merged | Add the independent no-key Review-only Formal Demo Console through inert permit issue | Implementation commit `4f5fb0d`, final head `872a3fa`; PR #361's final head passed wheel plus Python 3.11/3.12/3.13 after the matrix exposed and closed cross-host native DPI/large-text seams, with zero comment, review, requested change, unresolved thread, conflict, base/head drift, or credential use, and merged as `bd513b2`; both feature-branch copies were removed. The pure-local controller and Windows launcher retain exact local text, reviewed route/profile display, one-success exact-`COMPILE` acknowledgement, fixed failures, clear reset/close/callback rollback, keyboard routing, work-area/DPI/400%-text reflow, disabled/inert native `Start`, and clean base-wheel startup without provider extras. Full local gate: `2746 passed, 38 skipped`; 74 focused Console/branding tests including 30 real Win32 native-component tests; Ruff; mypy over 173 source files; docs-13; diff check; final installed source hashes; independent architecture, contract/docs, and test/packaging reviews found no remaining P1/P2. Provider/Desktop/Application remain `NO`; no API key, E3, provider request, permit consumption, positive Scope, Runner/MCP/Driver/desktop-automation/application/persistence port, Full Cycle change, E4, release, human-accessibility, multi-display acceptance, or complete Formal Demo promotion occurred |
| `GDA-DEMO-007E` | Complete; merged | Add the no-key Host-fixed Offline Scope Review path while keeping execution unavailable | Implementation commit `dba653b`, final head `865cee9`; PR #363's final head passed wheel plus Python 3.11/3.12/3.13 after the matrix exposed and closed cross-runner 400%-text mode/action-label seams, with zero comment, review, requested change, unresolved thread, conflict, or base/head drift, and merged as `b5a4d30`; both implementation-branch copies were removed. The compiler consumes one exact process-local permit, maps task text only to digest identity, compiles the complete reviewed built-in Scope with an inert Outlook Desktop test-account draft design binding, and revalidates digest-bound intent, Scope, and consumption receipt before display. Full local gate: `2759 passed, 38 skipped`; 224 focused Formal Demo/branding tests including 30 real Win32 native-component tests; Ruff; mypy over 174 source files; docs-13; diff check; clean no-dependency base-wheel install and native Scope smoke with provider SDKs absent and API-key variables cleared. Independent security, native/packaging, and final docs/capability reviews found no remaining P1/P2 after three stale descriptions were corrected; final glyph review measured the shortened mode and action labels within the exact CI widths. Provider/Desktop/Application remain `NO`; no API key, E3, provider request, free-form semantic interpretation, executable Outlook/application adapter, Runner/MCP/Driver/desktop-automation/application/persistence path, Full Cycle change, E4, release, human-accessibility, or complete Formal Demo promotion occurred |
| `GDA-DEMO-007F` | Implemented/Offline complete; merged | Add the exact OpenAI Responses one-attempt intent candidate and Host-reviewed Scope boundary without execution authority | Commit `721a528`; PR #365 passed wheel plus Python 3.11/3.12/3.13 with zero comment, review, requested change, unresolved thread, conflict, base/head drift, or credential use and merged as `adcfa64`; both implementation-branch copies were removed. The adapter is pinned to `openai` / `global` / `gpt-5.6-terra`, constructs the credential/client only after exact permit consumption, performs at most one tool-free request with SDK retries disabled, strictly validates refusal/truncation/envelope/schema/status/output bounds, sanitizes failures, and rechecks activation, permit state, disclosure digest, intent, and Scope after the await. Full local gate: `2844 passed, 39 skipped`; focused Formal Demo gate `306 passed, 1 skipped`; final security review `130 passed, 1 skipped`; Ruff; mypy over 176 source files; docs-13; diff check; clean no-dependency base-wheel smoke; independent security and test/docs/packaging reviews found no P0-P2. The skipped case is the opt-in live gate: no current account/data-controls preflight or process credential existed, so no live call ran and no `GDA-DEMO-007F`-specific Provider evidence was promoted. No general E3, Console live mode, `START`, Runner/MCP/Driver/desktop/application/persistence path, Full Cycle change, E4, release, or complete Formal Demo promotion occurred |

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
- User direction on 2026-08-30 lifted the prior blanket Cloud/local E3 and
  credential-dependent deferral only far enough to complete the exact
  `GDA-DEMO-007F` Implemented/Offline row. The authorization did not create a
  current account/data-controls preflight or credential, and it does not
  activate another route, local model, desktop/application slice, Lane B, L5,
  E4, or release gate. The completed `GDA-DEMO-007C`, `GDA-DEMO-007D`, and
  `GDA-DEMO-007E` slices remain no-key evidence; `GDA-DEMO-007F` has no live
  Provider evidence. A credential value is never inferred, printed, persisted,
  or treated as authority merely because the task is authorized.
- If authority is missing, the active item is ambiguous, or checks/reviews/
  conflicts are unresolved, stop instead of selecting adjacent work.
