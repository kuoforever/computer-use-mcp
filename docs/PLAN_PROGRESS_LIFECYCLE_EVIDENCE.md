# Bounded plan progress lifecycle evidence

Date: 2026-07-26

## Scope

This bounded Windows smoke exercised the complete observation-only `plan run`
composition through a fixed in-process Planner result, one project stdio MCP
observation, a fixed tool-free final response, and the real Win32 progress
backend. The runtime source under test was `35131d6`; the smoke harness is
retained with this evidence update.

The fixed plan contained exactly one `list_windows` step followed by the
required final-response step. Neither fake provider boundary opened a network
port, the ordinary provider port remained forbidden, Host policy allowed zero
side effects, and the temporary run state was deleted when the smoke finished.

## Command

~~~powershell
.venv\Scripts\python.exe scripts\smoke_plan_progress_lifecycle.py
~~~

## Result

~~~text
RESULT: PASS (foreground unchanged at 0x20554; one fixed provider-free plan drove one project-MCP list_windows observation through one native progress window; the tool-free final boundary completed; cleanup destroyed the window; no private task or desktop content was retained)
~~~

The smoke verified:

1. the bounded plan composition accepted one fixed observation-only plan and
   started one background-owned native progress window after durable run
   creation;
2. the drawn surface received the generated run ID in its nonterminal group
   without exposing the private task;
3. the project MCP dispatched exactly one read-only `list_windows` observation
   through the sole Runner boundary;
4. exactly one fixed final-response boundary completed without tools, provider
   network access, approvals, or side effects;
5. the terminal checkpoint retained one planner call, one final model turn, and
   one tool call;
6. the foreground HWND and Windows last-input tick stayed unchanged;
7. command cleanup joined the progress thread and destroyed the exact created
   window; and
8. retained command output exposed no task, title, window-list, screenshot, or
   desktop-result content.

The smoke waits for a three-second local-input quiet window before starting.
Failure to obtain that precondition or any input during the measured interval
makes the result inconclusive rather than claiming non-interference.

## Promotion boundary

This fills desktop evidence only for the opt-in progress lifecycle around one
fixed, provider-free, observation-only bounded plan. It does not fill the
Planner / Executor desktop evidence cell, verify a live provider, execute a
side effect, test more than one observation, verify BOSS campaign progress,
cover abrupt process termination or mobile notification, or constitute
application acceptance.
