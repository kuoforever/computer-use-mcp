# Passive progress-window non-activation evidence

> **Status: bounded on-device non-activation smoke retained 2026-07-22.** This
> record demonstrates that the passive operator progress window (delivery step 2
> of the [progress viewer](PROGRESS_VIEWER.md)) can be drawn, refreshed, moved,
> and toggled topmost on a live Windows desktop without changing the foreground
> window. It is not live-polling, campaign, presence-indicator, Decision-Card,
> application-acceptance, or release evidence.

## Reviewed boundary

- Source commit: `1ce1e887b6b14a928047dfceb465809ac4b59c6b`.
- Interpreter: CPython 3.13.7 from the checked-out virtual environment.
- Surface: `scripts/smoke_progress_window.py`, which drives the real
  `computer_use_agent.progress_window_win32.Win32ProgressWindowApi` through the
  `computer_use_agent.progress_window.PassiveProgressWindow` controller over
  synthetic view models only.
- Scope: one operator-approved interactive desktop session, read-only with
  respect to every other window. No checkpoint, campaign, provider, MCP, or
  desktop-automation path is touched; the window is drawn from fixed synthetic
  records built in the script.
- Excluded: any real run/campaign checkpoint, live polling, provider or MCP
  calls, screenshots, foreground activation, keyboard focus, and any write or
  click that changes another window's state.

## What was exercised

The controller ran the full passive cycle against the live backend:

1. `open()` — create `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST` over
   `WS_POPUP`, set the whitelisted lines, `ShowWindow(SW_SHOWNOACTIVATE)`;
2. `update()` — refresh the drawn lines via `InvalidateRect`;
3. `move(80, 80)` — `SetWindowPos(..., SWP_NOSIZE | SWP_NOACTIVATE)`;
4. `set_topmost(False)` then `set_topmost(True)` — reposition non-activated with
   `HWND_NOTOPMOST` / `HWND_TOPMOST`;
5. `close()` — `DestroyWindow`.

The backend never calls `SetForegroundWindow`, `SetFocus`, `SetActiveWindow`, or
`BringWindowToTop`; the `ProgressWindowApi` surface the controller is written
against does not define any such call.

## Result

The probe records `GetForegroundWindow()` before and after the cycle and
discards the run if `GetLastInputInfo` changes during it (human or injected
input would make foreground attribution inconclusive). Three consecutive runs
on 2026-07-22 each reported:

~~~text
RESULT: PASS (foreground unchanged at 0xb00c0; passive window drawn)
~~~

The foreground HWND stayed `0x000b00c0` across open, refresh, move, topmost
toggle, and close, and no local-input invalidation occurred. This is the live
form of [Operator progress viewer](PROGRESS_VIEWER.md) acceptance check 1, which
the offline suite already proves in injectable form.

## Supported claim and next gate

This closes the single on-device non-activation gate for the passive window and
promotes the Operator UI **Desktop verified** cell for that bounded slice from
`NO` in [Capability status](CAPABILITY_STATUS.md). It does not demonstrate live
checkpoint polling, multi-run grouping, campaign heartbeat display, the presence
indicator, Decision Cards, DPI/reduced-motion behaviour, or any real checkpoint
content on screen — the window was driven from synthetic records only.

Remaining after this gate (unchanged): delivery step 3 (atomic live checkpoint
polling) and step 4 (multi-run grouping) from
[Operator progress viewer](PROGRESS_VIEWER.md); the presence indicator and
fake-only Decision Card view models stay sequenced behind the passive surfaces
per the [roadmap](EXECUTION_PLAN.md).

Related: [Capability status](CAPABILITY_STATUS.md),
[Operator progress viewer](PROGRESS_VIEWER.md),
[Operator experience](OPERATOR_EXPERIENCE.md).
