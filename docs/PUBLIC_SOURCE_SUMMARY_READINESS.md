# Fixed public-source summary readiness

Status: readiness audit complete; local summary attempt failed on 2026-09-07.

`GDA-GUI-008` is a development readiness check, not a browser-to-Word run.
The previous continuous Word result remains frozen in
[its separate evidence](GUI_WORD_CONTINUOUS_EVIDENCE.md).

## Source and acquisition boundary

The source remains [Microsoft Support: Collaborate on Word documents with
real-time co-authoring](https://support.microsoft.com/en-US/Word/training/collaborate-on-word-documents-with-real-time-co-authoring).
An external web-reference reader returned the title and article on 2026-09-07.
This establishes accessible reference content at retrieval, not the local Chrome
window's URL, page load, Runtime capture, or absence of concurrent navigation.
Only the relevant prose excerpt is sent through the local summary worker's pipe.
The source/request/output text stays in ignored local work files and is not
committed or included in automatic Full Cycle exports. The safe receipt binds
hashes, counts, result codes and explicit evidence limitations.

Actual browser collection must separately verify the source identity and body
through the existing Runner/MCP path. The previous tool's inability to verify
Chrome URL remains unresolved by this reference lookup; do not bypass it using
native screenshot, direct network retrieval or an unbound page index and call
that Chrome evidence. Existing optional `browser_snapshot` is a read-only CDP
surface, but the fixed Word workflow does not currently allow that tool or bind
its page to a disposable native window. Enabling it alone is not integration.

## Existing code and gaps

- `public_web_word._source_verified` checks a Chrome title in `ui_snapshot` and
  scoped nonempty `document_text` (or OCR). It does not verify the current URL.
- `_valid_source_brief` requires the fixed heading/URL, 2-4 bullets, total
  220-900 characters, 24-180 characters per prefixed bullet and two overlapping
  source tokens per bullet. Token overlap cannot establish entailment or catch
  negation/qualification errors. This existing product guard is unchanged.
- `probe_gui_word.py` accepts exactly its fixed `NOTE`. Arbitrary generated
  text cannot be substituted without a separately reviewed content-bound handoff
  and full-body/disk/reopen verification. Its fixed editor instruction worker
  also is not a summary interface or general local provider registration.

## Pre-run decision and limits

One new reference-text request uses the unchanged GUI-Owl 4B revision
`3f061c2c562cc860c42bf32542a70e07a7ff4840` with unchanged experimental adapter
SHA-256 `3654fc21a2cea688754b800f9b10a49ae5e931f6ceb7eec080bfd83931fd0445`.
No base-vs-adapter comparison, prompt search, training or retry belongs here.
The old pilot remains 17/24 against required 20/24; it is not admitted.

The model repository owns `scripts/probe_public_source_summary.py`. Its request
has the exact source URL/title, `public_reference_excerpt` kind, new request ID,
bounded body and matching SHA-256. Output is exactly three English bullets in
one JSON object. Each unprefixed bullet is 22-178 characters; the Host supplies
the existing heading/source/URL and literal bullet prefix. Formatting succeeds
only within the existing Word profile's total and line bounds. No model field
grants execution authority. Hash equality is binding, not source authentication.

Use the same pinned local model files/environment, BF16 greedy SDPA and seed 17.
This text-only task has no screenshot. Caps: 4096 input tokens, 384 generated
tokens, 45-second soft generation time, 60-second checked generation time,
15 GB allocated GPU memory and 180-second parent process timeout. Require an
EOS-completed response. Count one generation separately from zero Runtime
provider turns, desktop calls and side effects. Generation timing excludes load,
hashing, process startup and tool time. The parent passes bootstrap environment
variables plus offline flags, never cloud credentials, and suppresses stderr.

Before inference, transport tests must reject duplicate fields, source drift,
mislabelled Runtime provenance, malformed bodies and output control characters.
The reference request, worker and system prompt are hashed before invocation.
The attempt is consumed even if the model fails; it is a development protocol,
not external proof that alternate executions are impossible.

## Acceptance decided before inference

Report the following independently:

1. Worker completed once inside the pinned resource limits.
2. Raw JSON and strict shape pass without fence stripping or content repair.
3. Human reference review finds each bullet supported, no contradictory claims,
   no invented deadlines/permissions, and qualifications preserved for any
   older-version or subscription claim. Three useful distinct points are needed;
   covering every paragraph is not required.
4. Browser capture, local provider integration, generated-text Word write and
   reopen are **not tested** by this probe even if 1-3 pass.

Only a passing factual review makes the candidate useful for the next scoped
source-to-summary transport. It does not grant automatic approval or justify a
model quality/success-rate claim. Full Cycle freeze, Lane B, Formal Demo preflight,
core type-debt and portable-model resume points stay in `PROJECT_STATUS.md`.

## Observed result

The one request `public-source-summary-20260907` used a 712-character reference
excerpt. Its child process exited 1 with fixed code `SUMMARY_WORKER_FAILED` and
reported `model_requests=1`. This counter is incremented immediately before
`model.generate`; it proves entry into a generation call, not its successful
completion. No raw summary or generation metrics were returned, so output shape,
factual quality, actual token/memory/time usage and normal EOS completion cannot
be assessed. The generic error cannot distinguish generation, post-generation
resource/EOS checks or post-use pin validation. Do not attribute the outcome to
model quality, claim a cap violation, or rerun the consumed attempt.

[Safe receipt](evidence/public-source-summary-readiness-2026-09-07.json) preserves
the pre-invocation request/source/prompt/worker hashes and exact bounded response.
There were no Runtime browser observations, provider turns, desktop calls or side
effects. No Word artifact was created. This result does not alter the continuous
Word result or the failed model-admission gate.

The worker used by this attempt is retained at model implementation commit
`5d031e37cd96a79461d189439d11283ebcf7ddef`; its hash matches the safe receipt.
The subsequent repair adds a version-2 response with an allowlisted failure stage
and reason, retaining zero/one generation-entry counts. It never exports raw
exceptions, source text or failed model prose. Four new failure-injection tests
join the original ten transport/shape tests, including no retry after generation
entry and zero calls for preflight failure. No inference used this repaired worker.

The readiness audit and diagnostic repair are complete, but summary readiness
remains unestablished. After publication/cleanup, the exact next objective is a
separately scoped reference-summary diagnostic with the repaired response contract.
Its new request/parent validation must be reviewed before invocation; the consumed
v1 parent rejects v2 and must not be reused. Fresh Runtime source capture and
generated-text Word integration stay pending.

## GDA-GUI-009 stage diagnostic

Status: activated after Runtime #413/model #104 merge and cleanup.
Use new request `public-source-summary-stage-20260907`, the same pinned
712-character reference, unchanged system prompt/model/adapter/caps, and the
merged response-v2 worker with SHA-256
`b5be14217184010aad8a2f113d6f83213cb780e5a801a821be0ea9c78fad4b40`.
This is a diagnostic control, not a claim of freshly acquired webpage content.
The model-owned `run_public_summary_diagnostic.py` pins the worker/reference,
uses an exclusive new directory before one child invocation, validates v2 status,
exit code, stage/reason, bindings and resources, and writes a content-free receipt.
Timeout or malformed output retains unknown generation count and never retries.
Success retains local output for separate shape and factual review; it does not
authorize Word execution. Five injected-process tests and the existing fourteen
worker boundary tests passed before the call. Preserve the consumed v1 attempt.
Stop after the sole invocation and classify the observed stage; a new failure
cannot retrospectively prove the stage of the old generic error.

Result: the sole request returned `EOS_CHECK` / `GENERATION_INCOMPLETE`, with
one reported generation entry and no retry. [Safe receipt](evidence/public-source-summary-stage-2026-09-07.json)
binds the exact new parent, worker, source, prompt and request hashes. The worker
reached its EOS check after generation returned, decoding completed, and the
4096-byte output / 15 GB allocated-memory / 60-second generation checks passed.
No complete summary or actual resource counters were returned. This does not
distinguish max-token from max-time stopping or explain the old generic failure.

Read-only inspection of the pinned checkpoint found generation EOS IDs
`[151645, 151643]`, with tokenizer EOS `<|im_end|>` at 151645. The chat template
ends with the ordinary assistant prefix and has no `enable_thinking` switch.
No EOS configuration mismatch was found; no prompt, weights, limits or acceptance
criteria were changed. This is a failed bounded completion, not summary-quality
evidence and not a browser/Word run.

The next bounded diagnostic repair is to retain safe completion counters and
stop-condition flags on rejected output, without exposing model prose in the safe
receipt or weakening normal completion/shape/factual gates. Offline tests must
distinguish token cap, elapsed-time stop, missing EOS and malformed metadata
before another separately scoped invocation. The present attempt is consumed.
Final parent gate: eight tests passed, including three added after invocation for
success-response binding/authority, resource bounds and transport-vs-shape separation.

## Offline completion diagnostic repair

Status: implemented and offline-tested after the consumed GDA-GUI-009 call.
The same bounded slice now closes the identified diagnostic gap with worker
response v3. When generation and decoding return, it computes a closed numeric
completion record before rejecting resources or missing EOS: input/output token
counts, elapsed generation seconds, peak allocated bytes, UTF-8 output byte count,
last-token EOS match, and token/time threshold indicators. Unknown earlier
failures have `completion=null`, never invented zero counters. Over-budget actual
values remain reportable within separate telemetry bounds. No partial model text
is returned on failure, no cap is raised and acceptance is unchanged.

The two threshold flags are independent and may both be true; they do not identify
which internal stopping criterion fired first. Tests cover normal EOS, token-only,
time-only and simultaneous thresholds, resource rejection with retained counters,
nonfinite/bool/unknown-field/forged-flag rejection and missing observations.
Final gates: 18 worker tests and 9 parent tests passed. No inference used v3.
The consumed v2 parent deliberately retains its old worker SHA and rejects v3;
its offline fake-process tests explicitly inject the current test worker hash.
The historical worker remains available at model base
`e868f4b5c65c29245019f3ac8c6efa079289edf8`. Preserve the receipt unchanged.

After publication and cleanup, the exact next is a separately scoped v3-aware
completion diagnostic using reviewed metadata validation. No old request is
replayed and no automatic model retry, browser/Word run or training is enabled.
