# GDA-07 — Evidence-driven engineering discipline

> **Status: current candidate item; repository-wide process evidence.**
> Personal ownership: `TBC`. Submission-ready only after `My scope` confirms
> the evaluation/release process you actually established or operated.

## Quick select

| Field | Guidance |
| --- | --- |
| Primary roles | Evaluation, quality engineering, release/platform engineering, developer productivity, AI safety |
| Position | Support by default; lead for evaluation/QA/release or developer-productivity JDs |
| Evidence ceiling | Repository process, deterministic gates, and named dated evidence records |
| Use when | The JD emphasizes evaluation design, CI, release gates, traceability, reproducible environments, or evidence-based safety |
| Skip when | A stronger implementation/result bullet is available and the role is not evaluation-focused |
| Exact JD keywords | `evaluation`, `CI/CD`, `release gate`, `traceability`, `negative testing`, `dependency locking`, `developer productivity`, `evidence`, `reproducibility` |

## Resume copy

**Short ZH:** 项目采用分层 evidence model，将 offline/provider/desktop/
application/human/release gates 分开，防止 mock 或 green CI 冒充线上能力。

**Evidence-rich ZH:** 项目采用 evidence-driven 交付流程：Windows Python 3.11-3.13 CI
执行 pytest/Ruff/mypy、独立 E1/E2 manifests、wheel install 与结构化文档契约
检查；真实 provider/desktop/application/human 结果保留为 immutable dated
records，并显式记录 invalid、blocked、negative 与 do-not-claim 边界。

**Short EN:** Project evidence uses a layered model separating implementation,
offline gates, provider, desktop, application, human, and release claims.

**Evidence-rich EN:** The project uses an evidence-driven delivery process combining a Windows
Python 3.11-3.13 CI matrix, deterministic safety manifests, clean-wheel checks,
structured documentation contracts, and immutable dated live records with
explicit negative and claim-limit boundaries.

**Optional environment ZH:** 项目为 Windows CPython 3.13 建立可复现 `.[dev]`
基线：将 machine-bound `.venv` 保持为 generated state，版本化 hash-pinned
lock、non-destructive bootstrap、stale-lock gate 与 deterministic regeneration；
fresh isolated bootstrap、`pip check` 和 `2502` 项 offline tests 通过。

**Optional environment EN:** The project keeps the machine-bound `.venv` as
generated state and versions a hash-pinned Windows CPython 3.13 `.[dev]` lock,
non-destructive bootstrap, stale-lock gate, and deterministic regeneration,
verified by a fresh isolated bootstrap, `pip check`, and 2,502 offline tests.

**My scope to confirm:** Which taxonomy, CI/preflight gate, fixture/manifest,
evidence run, review decision, postmortem, or documentation contract did you
personally create or operate? For the environment example, confirm which lock,
bootstrap, regeneration, contract-test, or fresh-install evidence work you
personally owned.

## Fact card

| Dimension | Evidence-backed fact |
| --- | --- |
| Problem | Detailed agent-generated code/docs and green mocks can sound more complete than the behavior actually verified |
| Decision | Separate evidence layers and require the claimed surface itself for promotion |
| Automated gate | Windows Python 3.11-3.13: full offline suite, Ruff, mypy, independent crash/replay E2 modules, deterministic eval, wheel build/install, docs/diff checks |
| Reproducible contributor baseline | Windows CPython 3.13 `.[dev]` uses a hash-pinned, source-digest-bound lock plus non-destructive bootstrap, stale-lock rejection, and deterministic regeneration; `.venv` remains ignored generated state |
| Live gate | E3/E4/application/human/release remain explicit opt-in records and never enter default CI |
| Record discipline | Dated evidence keeps its exact candidate, environment, metrics, invalid/blocked attempts, and limitations |
| Known limit | Structured consistency checks catch selected contracts and drift; they do not prove that all prose is true or that test coverage is complete |

## Proof map

| Claim | Owner/evidence |
| --- | --- |
| Current capability/evidence taxonomy | [Capability dashboard](../../CAPABILITY_STATUS.md) |
| E0-E7 evaluation ownership and gates | [Evaluation contract](../../EVALUATION.md) |
| AI-assisted responsibility split and known limits | [AI-assisted development](../../AI_ASSISTED_DEVELOPMENT.md) |
| Preflight, CI, and human release gates | [Release contract](../../RELEASE.md) |
| Development profile, generated-state boundary, and explicit extras | [Development contract](../../DEVELOPMENT.md) |
| Environment delivery, exact validation, and retained limitations | [`GDA-MAINT-001`](../../../PROJECT_STATUS.md#closure-backlog) |

## Interview card

- **S:** fast AI-assisted development makes planned work, mock coverage, and
  real-system evidence easy to conflate.
- **T:** state the evaluation/release/documentation mechanism you personally owned.
- **A:** define layers, freeze deterministic fixtures, retain live results by
  exact candidate, and make claim limits part of the evidence.
- **R:** explain one drift or invalid-attempt case the process caught; do not use
  a moving test count as user impact.
- **Trade-off:** strict evidence increases documentation and review cost but
  makes claims reproducible and failures inspectable.
- **Debug story:** explain why a green structured documentation check cannot
  validate every prose claim, and how owner/evidence comparison exposes the
  remaining review boundary without treating CI as release proof.
- **Environment case:** explain why committing `.venv` would preserve a
  machine-specific artifact rather than a reproducible environment, and why a
  hashed lock plus bootstrap/regeneration contracts give reviewers stronger,
  diffable evidence.

Deep-dive questions:

1. Why can CI prove offline correctness but not provider or application behavior?
2. What makes a negative result valid evidence versus an invalid attempt?
3. Which documentation facts can be checked structurally, and which still require review?
4. Why are provider SDKs, Playwright, observability, and Temporal still project
   features when they are excluded from the default `.[dev]` lock?
5. What additional evidence would be required before claiming cross-platform
   or all-profile environment reproducibility?

## Claim limits

Do not claim full test coverage, formal verification, production reliability,
or that CI validates all prose. Repository process does not prove personal
ownership; avoid `established` or `led` until your concrete scope is confirmed.
The development lock proves only the Windows CPython 3.13 `.[dev]` baseline;
it does not lock task-specific provider/browser/observability/Temporal extras,
prove cross-platform reproducibility, or provide provider/desktop/application
evidence. The Python 3.11-3.13 CI matrix is a separate compatibility signal,
not proof that this one lock applies across all three interpreters.
