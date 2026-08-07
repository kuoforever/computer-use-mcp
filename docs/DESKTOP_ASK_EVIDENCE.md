# Desktop Ask exact-candidate evidence

> **Status: PASS.** This is the reviewed execution plan and retained result for
> `GDA-PRODUCT-003`. Do not promote the result until every required field below
> is filled from one fresh installed-wheel run. A failed attempt remains a
> failure record until the observed functional defect is fixed and a new
> candidate is run.

## Acceptance boundary

- Runtime source candidate: `8bf139f2de5b12f22df7ef66d5840ec29a3225b7`.
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
values. Attempt 2 froze that repair in a new commit, wheel, and fresh state.

### Attempt 2 — `PASS`

| Field | Observed |
| --- | --- |
| Runtime source | `8bf139f2de5b12f22df7ef66d5840ec29a3225b7`; runtime/package diff count `0` |
| Wheel | `guarded_desktop_agent-0.1.0-py3-none-any.whl` |
| Wheel SHA-256 | `54ec7077f984b34f84093a18a6c70b69594da8f88e1d5c727195a55ae651a7a3` |
| Platform | Windows 11 Home build `26200`; Python `3.13.7` |
| Provider / model | OpenAI / `gpt-5.6-terra` |
| Doctor | `ready=true`; exact 13 installed sibling-MCP tools |
| Registry / config | `3112fbb88ad1398d4dc466cd0b2adff7199ace387d281f9c952ead7b961ed2bb` / `316b367eeda3e43db53a1fc99c08d1ab67386800869309307c27ed80507e56f7` |
| Fixture SHA-256 | `1f6e854180a04ae06abb32d4a6d938a8d6d7d56e042ed54be15b04c3c6a6d517` |
| Target selection | Computer Use listed zero Notepad windows before launch and exactly one `desktop_ask_product003.txt - Notepad` window afterwards. Its combined rehydrate/activate/state operation returned plugin error `node_repl exec context not found`, so no Computer Use input was retried. The installed product then completed `document_text(scope="foreground")` and returned all fixture-only facts, which is the retained foreground-content proof. |
| Run / plan | `2699db750c314b178e1f2fb400e233bf` / `plan_e8d703452032419ca43fa7ed35e7bdc3` |
| Plan | Sequence `4`; completed `document_text({"scope":"foreground"})`, then completed `final_response`; terminal digest `cb23f6a29fcbcc94bf715f9293e59a14d1a1c116b19aeb9f725ec47731be8911` |
| Trace / checkpoint | Successful `tool_call -> tool_result -> observation -> model_turn`; `SUCCESS`, 5 events, verified observation epoch `1`, 1 tool call, 0 failures |
| Usage | 1 Planner call; 1 final model turn; 1,065 final-input tokens; 41 output tokens |
| Answer projection | Length `113`; SHA-256 `7d0cb5022db5557bfa38b02e83b5a804db5ba225c1ea9e78724ee1e14b46a2e9`; codename, `37 + 58 = 95`, and `GO` predicates all `true` |
| Side effects / retries | 0 / 0 |
| Redacted export | Version `1`; manifest digest `sha256:63cbc89cae5ae980954f45cb2fd998575c3cdc40ede84a8d36bc12e27a3ef872`; artifact SHA-256 `cbb9addb684c356ebbc5563bb87741bbcfa28ab3e65502536e49b710565b77da` |

The task text omitted the codename, both region values, their sum, and the
decision. The safe trace proves that the sole observation was the installed
MCP's semantic `document_text` call, while the answer projection proves that
the final model recovered all predeclared fixture facts without manual
correction. The checkpoint and redacted Full Cycle export agree on one
successful tool call, one verified observation, one final model call, zero
side effects, zero retries, and zero tool failures.

The completed final-response WAL binds the pre-final snapshot digest
`95e16760cbaf20844242d8dbc4b9277ac98aa5aa0e80e44311acf77247b18ab1`;
the stored terminal plan digest above includes the later completed
`final_response` transition and is therefore intentionally different. Raw task,
document text, final text, and provider response identity remain only in the
ignored local evidence state and are not committed.

## Subsequent feature-freeze candidate rerun

`GDA-PRODUCT-015` reran this same bounded contract from clean wheel
`9589a611...e1423a` at runtime candidate `d254cd9`. Run
`8e87cfe9c16343319ae890d9756018f0` completed one foreground
`document_text`, then one final response with zero side effects, retries, or
tool failures. The 110-character answer projection had SHA-256
`860e601b...f846a`; the codename, arithmetic, and decision predicates all
passed, and the exact Notepad fixture window was closed. The shared
[current-candidate integration record](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md)
owns the full candidate, trace, redacted-export, and cleanup metadata.

## Supported claim

This record supports one model-scoped, application-scoped,
foreground read-only Desktop Ask result through Planner -> Runner -> installed
MCP `document_text` -> final response. It does not establish credential or
model portability, every-provider compatibility, broad Notepad support, a
desktop action, background operation, multi-monitor behavior, another
application, or release readiness.
