# PRODUCT-017 automated native evidence

> **Status: the automatically testable non-E4 subset passed on 2026-08-07.**
> Human assistive-technology, human large-text/visual, visible-notification,
> physical two-monitor, and real operator takeover timing remain `NOT RUN` or
> hardware-blocked. This is not E4, release approval, or a waiver.

## Candidate and authority boundary

| Field | Result |
| --- | --- |
| Runtime candidate | PRODUCT-016 merge `7184dee31b36c4f8a987c30309e97a9c7965ed58` |
| Platform | Windows, CPython 3.13.7 |
| Display observed | one monitor; bounds `2560x1600`, work area `2560x1528`, 144 DPI |
| External ports | no provider, MCP, application, or desktop-action port opened |
| Action decision | every native Decision Card returned safe `option_deny`; no automated self-approval smoke ran |
| E4 / release / waiver | `NOT RUN` / not approved / none |

The branch and original checkout were inspected before the native runs. No
unexpected focus or window result occurred, so no failure required attribution
to either product code or possible user interference.

## Native UIA, locale, theme, and large-text automation

Command:

~~~powershell
python scripts/smoke_operator_accessibility.py
~~~

Five presentation cases ran in both English and Simplified Chinese: dark,
light, High-Contrast-over-light, light at 200% text, and dark at 400% text. All
ten cases:

- exposed the expected UIA Edit/Button path and complete focus sequence;
- began and ended on the localized safe denial option;
- kept Decision Card and Progress rectangles inside the selected work area;
- kept Presence aligned to the monitor and capture-excluded; and
- preserved foreground across the passive Progress and Presence surfaces.

This proves automated UIA names, order, safe focus, geometry, reflow, locale,
theme, and passive-focus contracts. It does not prove spoken output, braille,
human legibility, visual hierarchy, or aesthetics.

## Fixed notification lifecycle automation

Command:

~~~powershell
python scripts/smoke_approval_notification.py
~~~

English and Simplified-Chinese fixed payloads were accepted by the Windows
Shell. Foreground remained unchanged and each hidden notification host was
destroyed after withdrawal. The probe explicitly returned
`visible_toast_claimed=false`: Windows quiet time can suppress presentation, so
this is not proof that a person saw, heard, or could later retrieve a toast.

## Cooperative-control composition automation

`tests/agent/test_cooperative_control.py` now composes the PRODUCT-016
`high_risk_only` policy with external takeover. A low-risk action is stopped at
the distinct `after_authorization` boundary as
`OPERATOR_TAKEOVER / NOT_DISPATCHED`; resume permits observation tools only,
and one fresh observation is required before a new low-risk action can consume
side-effect budget. This is deterministic fake-port evidence, not human/native
takeover timing or application evidence.

## Complete source gate

The evidence/test branch passed `2038 passed, 8 skipped`, Ruff over `src`,
`tests`, and `scripts`, mypy over 138 source files, documentation consistency
for 13 reviewed tools, and `git diff --check`. CI and merge remain separate
publication gates.

## Explicitly open gates

| Gate | State | Required evidence |
| --- | --- | --- |
| Narrator/NVDA/JAWS | `NOT RUN` | a person judges spoken order, pronunciation, verbosity, and usability |
| Human 200%/400% and visual design | `NOT RUN` | a person judges legibility, clipping, hierarchy, and aesthetics |
| Visible notification presentation | `NOT RUN` | a person confirms presentation/retrieval under reviewed Windows notification settings |
| Native cooperative takeover timing | `NOT RUN` | a person takes the desktop only after `paused/released`, then stops input before resume and confirms focus/timing |
| Physical two-monitor usability | `BLOCKED BY AVAILABLE HARDWARE` | two physical displays; synthetic coordinates are insufficient |
| E4 four-cell matrix | `NOT RUN` | remains explicitly deferred; no waiver exists |
| Release/tag/artifact publication | `NOT RUN` | separate final-candidate review and explicit release authority |

The automatic subset is complete. None of these open rows can be promoted by
another unattended script.
