# Campaign progress lifecycle evidence

Date: 2026-07-26

## Scope

This bounded Windows smoke exercised the fixed one-item synthetic campaign
through the project stdio MCP and the real Win32 progress backend. The runtime
source under test was `f4804d0`; the smoke harness is retained with this
evidence update.

The campaign command made exactly one `list_windows` observation through the
sole Runner boundary. The provider port was forbidden, the Host policy allowed
zero side effects, and the retained output contained only the fixed campaign
identity, aggregate usage, one content digest, item status, stop code, and
window count. No window title, task text, screenshot, account session, or
desktop content was retained.

## Command

~~~powershell
.venv\Scripts\python.exe scripts\smoke_campaign_progress_lifecycle.py
~~~

## Result

~~~text
RESULT: PASS (foreground unchanged at 0x20554; one validated Active campaign reached one native progress window; the fixed synthetic command made one list_windows call; cleanup destroyed the window; no task, title, window, or screenshot field was retained)
~~~

The smoke verified:

1. the MCP-backed campaign command started one background-owned native progress
   window without inventing a run phase;
2. the drawn surface received one validated `Active campaigns` projection for
   the exact synthetic campaign;
3. the synthetic worker dispatched exactly one read-only `list_windows` call
   and stopped at the fixed one-item limit;
4. the foreground HWND and Windows last-input tick stayed unchanged;
5. command cleanup joined the progress thread and destroyed the exact created
   window; and
6. retained output exposed no task, title, window-list, or screenshot field.

Any detected local input would have made the result inconclusive rather than
claiming non-interference.

## Promotion boundary

This fills desktop evidence only for the opt-in progress lifecycle around the
fixed synthetic campaign command. It does not verify the BOSS campaign
commands, a general campaign worker, provider execution, side effects,
multi-monitor behavior, abrupt process termination, mobile notification, or
application acceptance.
