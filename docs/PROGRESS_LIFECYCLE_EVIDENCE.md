# Progress lifecycle evidence

Date: 2026-07-26

## Scope

This isolated Windows smoke used synthetic local checkpoints and the real Win32
progress backend. It did not open a provider, MCP, desktop-action, approval, or
account session.

## Command

~~~powershell
.venv\Scripts\python.exe scripts\smoke_progress_lifecycle.py
~~~

## Result

~~~text
RESULT: PASS (foreground unchanged at 0x20240; durable OBSERVING and SUCCESS reached the background-owned window; release joined the UI thread and destroyed the window; no private content)
~~~

The smoke verified that one dedicated background thread created, pumped,
updated, and destroyed the native window; durable `OBSERVING` and `SUCCESS`
checkpoints reached it; the foreground window and last-input timestamp stayed
unchanged; final release joined the UI thread; and a synthetic task secret was
absent from rendered content. Any detected input would have made the result
inconclusive rather than claiming non-interference.
