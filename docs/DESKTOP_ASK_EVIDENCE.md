# Desktop Ask exact-candidate evidence

> **Status: ATTEMPT 1 FAILED; RETEST NOT RUN.** This is the reviewed execution plan for
> `GDA-PRODUCT-003`. Do not promote the result until every required field below
> is filled from one fresh installed-wheel run. A failed attempt remains a
> failure record until the observed functional defect is fixed and a new
> candidate is run.

## Acceptance boundary

- Runtime source candidate: `d94d5f9a7d70b43d6824190135f3f66547a8242f`.
- Platform: Windows, Python 3.13, foreground primary display.
- Provider: OpenAI Responses API with reviewed model `gpt-5.6-terra`.
- Product surface: installed `guarded-desktop-agent ask --json`, not an
  internal Python API or fake MCP.
- Target: one uniquely selected disposable Notepad window opened on the
  repository's synthetic `docs/fixtures/desktop_ask_product003.txt` document.
- Authority: read-only generated configuration; no approval or desktop action
  is available to the Planner/Executor path.

The synthetic fixture has three predeclared facts: codename
`ORBIT-LANTERN-731`, region values `37` and `58`, and a `GO` condition when the
sum is `95`. The question asks for the codename, arithmetic, and decision using
semantic document text. A correct result must report all three facts without
manual correction.

## Execution plan

1. Confirm that runtime/package inputs are byte-identical to the source
   candidate, build one wheel, record its SHA-256, and install it with the
   `agent-openai` extra in a new Python 3.13 virtual environment under ignored
   local evidence storage.
2. Point `LOCALAPPDATA` at a fresh evidence directory, run `config init`, then
   require `config doctor` to return `ready=true` and the exact thirteen-tool
   installed sibling-MCP contract.
3. Through the Windows Computer Use boundary, list applications first. Proceed
   only when no Notepad window exists, then launch the system Notepad on the
   reviewed fixture. Select exactly one returned window, refresh state, and
   verify the expected synthetic document is foreground. Do not inspect or
   modify an existing user document. If the Computer Use launcher itself is
   unavailable, a direct process launch may open this exact file; all target
   selection and state verification remain through the returned window API.
4. Run exactly one installed `ask --json` request. Retain raw CLI output only
   in transient local parsing or ignored evidence storage. Record only final
   length/digest and the three correctness predicates in this document.
5. Read the run's validated `task-plan.json`, redacted trace, and safe report.
   Produce the versioned redacted `fullcycle export-run` artifact for the same
   run and inspect only its safe projection.
   Require one terminal plan whose observation steps include successful
   `document_text`, whose last step is `final_response`, and whose metadata
   agrees with CLI tool/observation counts. No planned or executed step may be
   a side effect. Planner calls remain separate from checkpoint/report model
   calls.

Stop and retain the attempt as failed if target selection is ambiguous, doctor
does not attest the exact installed contract, the Planner omits
`document_text`, an observation or provider call fails, stored identities or
counts disagree, or the answer misses any predeclared fact. Fix only a defect
actually observed, then build and identify a new candidate before retrying.

## Result

### Attempt 1 — `FAIL`

| Field | Observed |
| --- | --- |
| Runtime source | `d94d5f9a7d70b43d6824190135f3f66547a8242f` |
| Wheel | `guarded_desktop_agent-0.1.0-py3-none-any.whl` |
| Wheel SHA-256 | `d6febf04564c3f5be7247bdb91fc4150295d6839230e4218528f91f503cc8ff4` |
| Python / provider / model | Python 3.13.7 / OpenAI / `gpt-5.6-terra` |
| Doctor | `ready=true`, exact 13 tools |
| Fixture SHA-256 | `8c7de3587243194af52edec3c11277df493a71cd939c57481f3eb860ec346c1e` |
| Target selection | Computer Use listed zero Notepad windows before fixture launch, then exactly one `desktop_ask_product003.txt - Notepad` window; its launcher/state APIs returned `node_repl exec context not found`, so the reviewed fixture was opened by direct process launch and no Computer Use input was attempted |
| Run / plan | `bfa0078877424745803a67fe8633bcc3` / `plan_7201cee9116347d99c14ce107a1fc774` |
| Terminal failure | `EXECUTOR_TOOL_FAILED` |
| Side effects / retries | 0 / 0 |

The Planner first completed `list_windows`, then planned
`document_text({"scope":"foreground document"})`. The Host's scope schema
accepted any non-empty string, so the paraphrase was persisted and dispatched;
the Windows Driver could not resolve it and returned `DRIVER_ERROR`. The
`document_text` plan step is `failed`, the `final_response` step remains
`pending`, no final model call or answer exists, and this attempt supports no
Desktop Ask capability claim.

The observed functional fix narrows the Host scope schema to exact
`foreground | all | positive decimal window id`, validates its pattern during
plan compilation, and instructs both provider Planners to copy literal schema
values. A new commit, wheel, and fresh state are required before Attempt 2.

## Supported claim

When complete, this record supports one model-scoped, application-scoped,
foreground read-only Desktop Ask result through Planner -> Runner -> installed
MCP `document_text` -> final response. It does not establish credential or
model portability, every-provider compatibility, broad Notepad support, a
desktop action, background operation, multi-monitor behavior, another
application, or release readiness.
