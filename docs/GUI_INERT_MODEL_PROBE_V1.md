# Real-window inert model diagnostic v1

Status: implemented development harness; one native/model attempt passed on 2026-09-07.

[Retained receipt](evidence/gui-inert-native-2026-09-07.json): one local generation
accepted as an inert `click_ref`, 2.344 seconds, 781 input / 27 output tokens,
9,317,841,408 peak allocated bytes, three Host reads, zero Host provider turns
and zero side effects. Input was unchanged; the fixture was closed afterward.
The receipt binds source and response hashes but retains no raw output/image,
so it cannot independently replay compilation of this actual response.

`GDA-GUI-004` composes the unchanged [native collector](GUI_READONLY_PROBE_V1.md)
with the model repository's pinned projector/compiler and an isolated local
GUI-Owl 4B + saved experimental LoRA worker. Ordinary launch defaults, reviewed
tools and production packages are unchanged. The earlier failed LoRA admission
threshold remains failed; this diagnostic cannot promote it.

## Registered attempt

Before observing its output, the acceptance rule is one fresh fixture capture,
one greedy screenshot-only model generation, and a `click_ref` proposal accepted
by the existing strict compiler against that captured snapshot. A stop, malformed
response, or point outside the unique enabled target is a valid negative; do not
tune or retry it. User-input changes invalidate attribution and require a fresh
observation before an attributable rerun. No model action is dispatched.

Launch and foreground the unchanged `gui_readonly_fixture.py` test application
as described in the predecessor contract, then run:

```powershell
.venv\Scripts\python.exe -B scripts/probe_gui_inert_model.py --live-inert-proposal --scope <actual-hwnd> --consumer-root <model-checkout>
```

The Host keeps budgets of three read calls, zero provider turns and zero side
effects. Its MCP connection closes before invoking the worker. Separate counters
record one worker invocation and zero/one actual generation calls; a lost worker
response leaves generation count unknown (`null`). There is no retry path.
Checkpoint `SUCCESS` describes observation collection only. Diagnostic outcome
additionally requires a validated model response, compilation and unchanged input.

The model worker lives in the model repository and has no desktop port. It uses
the retained environment and verifies the fixed model and adapter file hashes,
with offline-only loading and no dependency installation. Its model prompt is
the existing visual prompt plus the fixed target instruction. UIA refs, bounds,
and coordinates are not supplied to the model. The host binds its response to
the issued request/context/image and validates resource counters before compiling.

Limits: 8 MiB PNG, 4096 input tokens, 192 new tokens, greedy generation, a
45-second generation soft deadline, 60-second measured acceptance cap, 15 GB
allocated-memory acceptance cap and 180-second process timeout. These are not
GPU isolation or hard real-time guarantees. The process runs trusted local
code with a bootstrap-only environment; this is not an OS security sandbox.
The trusted worker emits bounded output; the parent rejects over 16 KiB after
collection. It does not provide streaming memory containment of a malicious worker.

## Proof and data boundaries

Only fixed outcome codes, counters, timings and hashes are retained. Native
observations, screenshot bytes and model prose stay in memory and local pipes;
worker stderr is discarded. This is an explicit synthetic-fixture diagnostic,
not automatic Lane A rich export or Lane B capture/training data.

The compiler's `current` argument is a detached copy of the acquired snapshot,
not a second post-inference desktop observation. This proves snapshot-relative
grounding only. Refs belong to the closed Session and cannot be dispatched by
this harness. Future action work must reacquire live state through Runtime and
pass its policy, grounding, approval, WAL and budgets. Unchanged last-input ticks
and equal endpoint metadata do not prove atomic capture or complete occlusion
tracking. Chrome-to-Word, closed-loop success and generic local Provider E3 remain
unverified. Close the disposable fixture after the attempt.

## Validation

The injected Runtime tests verify real Host collection/cleanup, exactly one
worker call, rejected metadata, no retry, input attribution, safe errors, and
separate ledgers. They inject the pure consumer API and do not establish model
or native desktop success. Model-side tests cover its transport and the existing
projector/compiler gates; the actual staged run checks cross-repository wiring.
