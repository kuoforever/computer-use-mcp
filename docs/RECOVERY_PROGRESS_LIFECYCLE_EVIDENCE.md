# Recovery progress lifecycle evidence

Date: 2026-07-26

## Scope

This bounded Windows smoke resumed one persisted provider-completed,
observation-pending run through the explicit read-only recovery path, the
project stdio MCP, and the real Win32 progress backend. The runtime source under
test was `e98254c`; the smoke harness is retained with this evidence update.

The prepared continuation requested exactly one `list_windows` observation.
Recovery acquired the ordinary run lock, validated the checkpoint and private
continuation, wrote its dispatch intent before I/O, committed the result, and
stopped at the reviewed one-step boundary. The provider port was never opened,
Host policy allowed zero side effects, and the temporary private continuation
was deleted with the smoke state directory.

## Command

~~~powershell
.venv\Scripts\python.exe scripts\smoke_recovery_progress_lifecycle.py
~~~

## Result

~~~text
RESULT: PASS (foreground unchanged at 0x20554; one persisted read-only recovery boundary reached one native progress window; the project MCP made one list_windows observation; cleanup destroyed the window; no task, title, window, or screenshot field was retained)
~~~

The smoke verified:

1. explicit recovery started one background-owned native progress window from
   the validated persisted `PLANNING` checkpoint;
2. the drawn surface received the exact run ID in its nonterminal group without
   exposing the private task;
3. the project MCP dispatched exactly one read-only `list_windows` observation,
   and recovery durably advanced from checkpoint sequence 3 to 5;
4. the command stopped before provider continuation and performed zero side
   effects;
5. the foreground HWND and Windows last-input tick stayed unchanged;
6. command cleanup joined the progress thread and destroyed the exact created
   window; and
7. retained command output exposed no task, title, window-list, screenshot, or
   tool-result content field.

Any detected local input would have made the result inconclusive rather than
claiming non-interference.

## Promotion boundary

This fills desktop evidence only for the opt-in progress lifecycle around one
explicit, persisted, read-only recovery observation. It does not verify
provider continuation, stateless replay, completed-side-effect re-observation,
action replay, bounded plan-run progress, BOSS campaign progress, abrupt
process termination, mobile notification, or application acceptance.
