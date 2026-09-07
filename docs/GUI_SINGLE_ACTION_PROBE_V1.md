# Single-use native fixture action diagnostic v1

Status: implemented; one real native/local-model action attempt passed on 2026-09-07.

[Retained receipt](evidence/gui-single-action-native-2026-09-07.json) records
`gui-action-a74b8ac5694d46b0b3813a476f41a594`: one model request, one scoped
approval, one UIA action, ten tool calls and epoch 9. Read-back verified the
button label change and disabled state; independent desktop tooling observed
the same result. Input was unchanged and the fixture was closed. Generation
took 2.563 seconds with 9,317,841,408 peak allocated bytes. These exclude model
load and capture time. No raw image/output replay is available from this receipt.

`GDA-GUI-005` extends the [inert diagnostic](GUI_INERT_MODEL_PROBE_V1.md) with
one separately authorized observable action. It does not change frozen scripts,
model weights, default launch routes, reviewed tool schemas or production modules.

## Registered acceptance and invocation

Before viewing the model output, the attempt is fixed to one fresh fixture,
one saved GUI-Owl + experimental LoRA request, one semantic ref click, and an
observed button transition from `Observation target` enabled to `Completed once`
disabled. Only this synthetic window is authorized. A model stop, malformed
response, changed observation, rejected action or absent transition fails;
there is no automatic retry. An unknown action outcome must not be replayed.
Any input change invalidates attribution; a rerun needs a new fixture and fresh
observation and cannot reuse an uncertain prior action.

```powershell
.venv\Scripts\pythonw.exe scripts/gui_action_fixture.py --show-test-window
.venv\Scripts\python.exe -B scripts/probe_gui_single_action.py --allow-one-fixture-click --scope <actual-hwnd> --consumer-root <model-checkout>
```

Launch and foreground preparation use the operator or approved desktop tooling.
Keep the synthetic fixture in front and do not use the mouse/keyboard during
the measured attempt. The explicit action switch carries the owner's one-use
fixture preauthorization. It is not a model-controlled approval or general
blanket permission. Alt+F4 closes the disposable fixture after the attempt.

## Revalidation and execution

The harness owns the ordinary run lock, redacted recorder and one StdioDesktopMCP
Session. Each capture uses the unchanged `_RunnerSource` and producer: endpoint
metadata surrounds three charged reads (windows, UIA snapshot, screenshot).
The existing model worker receives only the initial image and fixed target text.
Its model/package/resource checks and single-request bounds are unchanged.

The response is bound and compiled against its original issued context. A second
capture must match every context field except the exactly three advancing
observation epochs; frame hash, complete control set, refs, bounds, target,
foreground window and generation stay equal. Native metadata must also match,
including native identities. The original reply is never rewritten to claim it
saw the new epoch. The Host constructs a fresh call using that same verified ref.

The one-use Host permit checks the exact call identity/digest and approval
binding, unchanged input, a two-second freshness deadline and a final bounded
metadata read. Mismatch consumes the permit and denies. The call then uses the
existing Runner policy/grounding/approval/WAL path and the normal MCP safe-local
e-stop, human activity, foreground allowlist, dangerous-target and final native
authority gates. The child alone opts into UIA semantic ref actions and allows
`pythonw.exe`; the harness additionally requires the exact foreground fixture
scope/title/one-button state. This is not pointer injection or a general local
Provider route. No guard is disabled or relaxed.

Budgets are ten tool calls, one side effect and one reserved Host model-turn
capacity. The latter satisfies the existing action verification preflight; actual
Host provider calls remain zero, and the external inference is counted separately.
After the click, a third three-read capture must prove the same native button
changed its label and became disabled. A success return alone never passes.
The fixture handles its button once and changes no files or external data.

## Evidence limits

Raw images, UI contents and model prose remain in memory/local pipes. Retained
receipts contain fixed codes, counters, booleans, timings and hashes. Existing
redacted Host/MCP logs stay local. No rich Lane A export or Lane B data capture is
introduced. Endpoint comparisons are not atomic capture or complete occlusion
tracking. Final native safety gates remain necessary after the metadata check.
Cancellation after uncertain dispatch must preserve the existing UNKNOWN_OUTCOME
checkpoint; neither model nor action is automatically replayed.

Semantic UIA invocation does not inject mouse/keyboard input, so unchanged
last-input ticks bracket the whole attempt. This is supporting attribution,
not proof excluding every external process or window mutation. User-observed
interference invalidates an otherwise positive receipt.

The previous LoRA admission threshold remains failed. This bounded engineering
diagnostic does not establish model promotion, general application coverage,
Chrome-to-Word completion or a robust multi-step success rate.

## Checks

```powershell
.venv\Scripts\python.exe -B -m pytest tests/agent/test_gui_single_action.py -q
```

These tests run genuine Host collection, policy, approval, WAL, budgets, safe
records and memory-stream MCP observation with injected native data/action and
consumer/model responses. They establish no live desktop or inference evidence.
