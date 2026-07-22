# Desktop presence halo on-device evidence

> **Status: bounded primary-display presence smoke retained 2026-07-22.**
> This record demonstrates the standalone passive presence model/controller and
> real Win32 halo. It is not automatic Agent lifecycle integration,
> multi-monitor support, a Decision Card, application acceptance, or release
> evidence.

## Reviewed boundary

- Source commit: `90989a4fa23552fd86255c257328bf30a162dac0`.
- Interpreter: CPython 3.13.7 from the checked-out virtual environment.
- Surface: `scripts/smoke_presence_window.py`, driving
  `PresenceSnapshot` -> `PassivePresenceWindow` ->
  `Win32PresenceWindowApi` on the primary display.
- Scope: one operator-approved interactive Windows desktop session. The probe
  created, updated, and destroyed only its own top-level tool window.
- Excluded: provider/MCP calls, desktop actions, Agent CLI lifecycle wiring,
  target-window identification, multi-monitor selection, application content,
  and any focus-taking operator interaction.

## What was exercised

1. Open a real primary-display halo from the fixed `OBSERVING` state.
2. Read back the real extended styles and require the complete
   `WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST |
   WS_EX_LAYERED` set.
3. Send native `WM_NCHITTEST` and `WM_MOUSEACTIVATE` probes and require
   `HTTRANSPARENT` and `MA_NOACTIVATE` respectively.
4. Require both the controller result and `GetWindowDisplayAffinity` to report
   `WDA_EXCLUDEFROMCAPTURE` (`0x11`). This proves the OS retained the feedback
   prevention request; it is not a secrecy or DRM claim and does not replace
   trusted-window masking.
5. Change the fixed phase to `EXECUTING`, pump the real timer, and require its
   bounded animation frame to advance without recreating the window.
6. Enable reduced motion plus high contrast and require animation to stop and
   the fixed monochrome palette to replace phase color while the text/glyph
   label remains.
7. Compare the painted geometry with current primary-display dimensions and
   DPI-scaled border rules.
8. Engage the projected E-stop and require the HWND to be destroyed. Reopen in
   `WAITING_APPROVAL`, release desktop authority, and require immediate teardown
   again.
9. Compare foreground HWND and `GetLastInputInfo` across the probe. Any local
   input makes the run inconclusive rather than weakening attribution.

## Result

The first two attempts on the exact source commit were correctly discarded as
inconclusive because `GetLastInputInfo` changed. The third attempt reported:

~~~text
RESULT: PASS (foreground unchanged at 0x10614; HTTRANSPARENT + MA_NOACTIVATE;
capture affinity 0x11; DPI geometry valid; animation advanced and reduced
motion stopped it; E-stop and authority release destroyed the halo)
~~~

Thus, for this bounded primary-display session, opening, phase refresh,
animation, accessibility-mode refresh, E-stop teardown, and authority-release
teardown never changed the foreground window. Native hit testing refused both
pointer targeting and activation, Windows retained capture exclusion, and the
halo used the observed display DPI.

## Offline evidence and structural controls

The live probe complements deterministic tests rather than replacing them:

- every allowed phase maps to fixed label, glyph, palette, and motion metadata;
- the display model has no run/campaign ID, task, target, title, argument,
  approval, or dispatch field;
- release, E-stop, terminal close, and per-user disablement all destroy the
  window immediately and idempotently;
- the native protocol exposes no focus, activation, input capture, hotkey,
  execution, or approval method;
- exact click-through/non-activation styles and DPI scaling from 96 through 768
  are asserted against a recording fake;
- capture-affinity failure remains visible in the controller result and is not
  promoted to a secrecy claim.

The exact implementation gate completed with Ruff clean, mypy clean across 93
source modules, and `1162 passed, 5 skipped` in the full offline suite.

## Supported claim and next gate

This supports a bounded **Desktop verified** claim for the standalone
primary-display presence surface. It does not prove that the Agent CLI updates
the surface from every real lifecycle boundary, that an MCP-child E-stop tears
down a separate Host process synchronously, that every capture technology
honors display affinity, or that multi-monitor and abrupt-process cases pass.

Next connect the surface to a single Host-owned lifecycle coordinator without
creating execution or approval authority, then retain a real run transition and
teardown result. Fake-only Decision Card models remain behind that passive
integration gate.

Related: [Operator experience](OPERATOR_EXPERIENCE.md),
[Capability status](CAPABILITY_STATUS.md),
[Execution plan](EXECUTION_PLAN.md).
