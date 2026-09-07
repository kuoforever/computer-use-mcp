# Single-window read-only probe v1

Status: implemented; one fixed native-window attempt passed on 2026-09-07.

[Retained native receipt](evidence/gui-readonly-native-2026-09-07.json) includes
the exact probe/fixture source hashes and redacted stdout result. The native
run recorded epoch 3, three tool calls, one matched button, unchanged input and
zero model turns/side effects. The test window was closed afterward. This
proves the fixed fixture path only; it does not establish Chrome/Word coverage.

`GDA-GUI-003` adds a development-only, explicit opt-in harness. The ordinary
MCP server and Agent CLI remain unchanged and default-off for GUI metadata.
This is not a model/action route or Chrome-to-Word acceptance.

## Preparation and invocation

On an authorized interactive Windows desktop, launch the disposable fixture:

```powershell
.venv\Scripts\pythonw.exe scripts/gui_readonly_fixture.py --show-test-window
```

It draws a borderless primary-display window with only synthetic static text
and one inert native button. It reads no files and its button has no command
handler. Activate this particular window through the operator or approved
desktop tooling and obtain its actual HWND. Keep it in front and do not type
or move the mouse during collection. Alt+F4 closes the fixture after the run.

```powershell
.venv\Scripts\python.exe -B scripts/probe_gui_readonly.py --live-readonly --scope <actual-hwnd>
```

The development script launches itself in explicit `--serve-readonly` mode
through the existing stdio bridge, enabling only the already implemented
metadata resource. It uses the real Windows driver, Session, Host source and
sole Runner call boundary. The fixed policy has three tool calls, zero model
turns and zero side effects. Empty fake provider/approval ports fail if invoked;
no provider SDK or credential is configured. Child environment construction,
server safety controls, strict metadata/registry validation and cleanup remain
unchanged. Missing opt-in, malformed scope and non-Windows hosts reject.

## Evidence ceiling

The measured sequence is two metadata reads bracketing `list_windows`, scoped
`ui_snapshot`, and primary-display `screenshot`. The existing five-second
maximum acceptance bound remains. A passing receipt additionally requires the
fixed foreground fixture title and exactly one matching button. Model turns,
side effects and observation epochs come from the actual redacted checkpoint.

The application state directory is the normal user-local root under
`computer-use-agent/gui-readonly-probe`. The stdout JSON contains only a fixed
version, outcome/code, run ID, phase, counters and boolean evidence flags. Raw
window titles, control names, native IDs, tool text and screenshot bytes are
never written by the harness or exported to Full Cycle. Standard redacted
Runner records remain local. This is not Lane B capture or a training dataset.

Last-input ticks bracket the attempt. A changed tick yields `INVALID` even if
the collector checkpoint says `SUCCESS`; the latter only describes collection
and connection closure. A failed read is not silently retried. Take a new
observation and a new run ID before a separately attributable rerun. Endpoint
equality and unchanged input do not prove atomic capture, complete occlusion
tracking, or freedom from every possible external window change.

The fullscreen synthetic fixture reduces incidental visible desktop content;
it does not make screenshots generally safe to export. This probe must not be
used to bypass an auxiliary tool's browser policy rejection. Browser tool
failures, native collection failures and model failures remain distinct.

## Offline checks

```powershell
.venv\Scripts\python.exe -B -m pytest tests/agent/test_gui_readonly_probe.py tests/agent/test_gui_host_source.py tests/agent/test_gui_observation.py -q
```

Injected desktop tests exercise the genuine collector, count-only output,
metadata/fixture rejection, input-change invalidation and opt-in validation.
They establish no live evidence. Actual attempt outcomes and sequencing belong
to `PROJECT_STATUS.md`.
