# Bounded plan presence lifecycle evidence

Date: 2026-07-26

## Scope

This bounded Windows smoke exercised the observation-only `plan run`
composition through a fixed in-process Planner result, one project stdio MCP
observation, a fixed tool-free final response, and the real Win32 presence
backend. The runtime source under test was `6d80bd6`; the smoke harness is
retained with this evidence update.

The fixed plan contained exactly one `list_windows` step followed by the
required final-response step. Neither fake provider boundary opened a network
port, the ordinary provider port remained forbidden, Host policy allowed zero
side effects, and the temporary run state was deleted when the smoke finished.

## Command

~~~powershell
.venv\Scripts\python.exe scripts\smoke_plan_presence_lifecycle.py
~~~

## Result

~~~text
RESULT: PASS (foreground unchanged at 0x20554; one fixed provider-free plan drove one project-MCP list_windows observation while one native halo reused durable labels ['Observing', 'Planning', 'Executing', 'Executing', 'Executing', 'Executing', 'Observing', 'Planning']; terminal cleanup destroyed the halo; no private task or desktop content was retained)
~~~

The smoke verified:

1. the bounded plan composition accepted one fixed observation-only plan and
   opened the native halo only after a durable active phase;
2. one HWND was reused across the fixed `Observing`, `Planning`, and
   `Executing` projections;
3. the project MCP dispatched exactly one read-only `list_windows` observation
   through the sole Runner boundary;
4. exactly one fixed final-response boundary completed without tools, provider
   network access, approvals, or side effects;
5. terminal success and final cleanup destroyed the halo;
6. the foreground HWND and Windows last-input tick stayed unchanged; and
7. retained command output exposed no private task, title, window-list,
   screenshot, or desktop-result content.

The smoke waits for a three-second local-input quiet window before starting.
Failure to obtain that precondition or any input during the measured interval
makes the result inconclusive rather than claiming non-interference.

## Promotion boundary

This fills desktop evidence only for the opt-in presence lifecycle around one
fixed, provider-free, observation-only bounded plan. It does not fill the
Planner / Executor desktop evidence cell, verify a live provider, execute a
side effect, test more than one observation, verify recovery or campaign
presence, cover E-stop on a real MCP result, cover abrupt process termination
or multi-monitor behavior, or constitute application acceptance.
