# Demo action-presentation evidence (2026-08-03)

> **Result: PASS — retained on-device record, 2026-08-03.** Frozen observation
> of one dated run. Do not update its numbers; supersede it with a new record.

## Scope

`GDA-DEMO-004` adds an operator-owned presentation layer to the existing
Runner/MCP dispatch path. It does not add a tool, action authority, model
control, data lane, or evidence promotion.

The bounded Demo accepts `--interaction-speed fast|normal|deliberate` and uses
`deliberate` by default. The profile controls only pointer animation,
pre/post-action dwell, and the default focused-control typing delay. An explicit
`CUMCP_TYPE_WAIT_SECONDS` still overrides the profile. With no profile selected,
ordinary Runtime behavior retains its prior native timing.

The optional action overlay is topmost, click-through, non-activating, and
capture-excluded. Pointer activity shows a high-contrast ring and fixed action
class. Keyboard activity shows only `AGENT TYPING` or `AGENT KEY`. Visible
typing animates a pulsing caret, cycling dots, and an estimated progress bar
using bounded text length and selected interval only; the feedback protocol has
no typed-text or key-value field. The worker polls only the foreground editor's
native caret geometry, so the badge moves with insertion and line wrapping. It
falls back to its last bounded anchor when a surface exposes no native caret.

## Native surface probe

Command:

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_action_feedback.py
```

Result:

```json
{"capture_excluded":true,"click_through_nonactivating":true,"foreground_preserved":true,"keyboard_visible":true,"pointer_painted":true,"pointer_visible":true,"typing_progress_advanced":true}
```

The probe displayed a pointer click ring and a content-free typing badge,
pumped the real Win32 window, verified that its update region was painted,
read back `WDA_EXCLUDEFROMCAPTURE`, checked the required extended styles, and
confirmed that the foreground HWND did not change. A worker-owned message loop
also proved that typing progress advanced while the caller was busy. The probe
injected no mouse click, key, or text.

## Retained end-to-end Demo

Command:

```powershell
.\.venv\Scripts\python.exe .\scripts\demo_cross_app.py --interaction-speed deliberate
```

Retained caret-following run: `cross-app-demo-20260803-043417-697826`.

- Result: `PASS`.
- Tool calls: `17`.
- Operator-approved side effects: `7`.
- Durable DOCX marker verification: passed.
- Exact launched-window cleanup: complete.
- Presence projections: `85`.
- Presence painted samples: `261`; one sample observed a pending paint and the
  later samples painted normally.

The final run uses the corrected `uiautomation.SendKeys` argument: the selected
profile now controls the per-character `interval`, while the final `waitTime`
is zero. The prior implementation had passed the configured value as
`waitTime`, so it delayed only after the complete text and did not actually
control visible typing speed.

This is bounded Demo evidence for the controlled Chrome-to-Word workflow. It is
not provider/model-speed evidence, broad application evidence, release
evidence, or a universal-GUI capability claim. The Demo provider remains a
fixed deterministic script rather than a model.

Preceding run `cross-app-demo-20260803-043233-392422` stopped safely at the
typing boundary with `DENIED_BY_GATE` and `dispatch=not_dispatched` after local
human activity prevented the required stable-idle streak. No text was sent and
the run was not resumed or replayed; a new run was started only after inspecting
the trace and confirming the not-dispatched result.

## Offline gate

- `pytest -q`: `1577 passed, 8 skipped`.
- Ruff: passed.
- mypy: no issues in `120` source files.
- Documentation consistency: passed with `13` reviewed tools.
- `git diff --check`: passed.
