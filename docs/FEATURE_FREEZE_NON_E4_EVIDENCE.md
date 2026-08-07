# Feature-freeze non-E4 evidence audit

> **Status: bounded audit passed at branch-reachable commit `23e71a5`; E4 NOT
> RUN.** This record closes only the available offline, clean-wheel, bounded E3,
> and native operator-surface checks. It is not a release approval, tag,
> permanent waiver, human assistive-technology review, physical two-monitor
> result, or current-candidate real-application result.

## Candidate and authority boundary

| Field | Sanitized value |
| --- | --- |
| Candidate commit | `23e71a58ce38b69caea28aa167f94afe55b887e7` |
| Runtime/package version | `0.1.0` / `0.1.0` |
| Platform | Windows, CPython 3.13.7 |
| Candidate source | clean before and after the retained exact preflight and E3 runs |
| E4 | `NOT RUN` by explicit user deferral |
| Release/tag | not created or approved |
| Waiver | none |

The probe refresh changed only three scripts. No Runtime, Agent Host, MCP,
provider adapter, application workflow, approval, capture, action, replay, or
data-lane implementation changed. The original checkout's peer-owned files
were not touched.

## Exact offline preflight

Command:

~~~powershell
guarded-desktop-agent release preflight `
  --root . `
  --artifacts out\product014-preflight-23e71a5 `
  --report out\product014-preflight-23e71a5.json
~~~

| Gate | Result |
| --- | --- |
| Report | v5 `PASS`; SHA-256 `4c7c02adf71d59cb55479cca25a8bc761d03f444db47834e666026f3ef2bcf5f` |
| Candidate stability | start/end commit identical; source clean at both endpoints |
| Ruff / pytest / diff | `PASS`; `2026 passed, 8 skipped`; diff clean |
| Crash reconstruction E2 | 15 canonical cases; 22 passed tests; zero failed/skipped |
| OpenAI stateless replay E2 | 9 canonical cases; 11 passed tests; zero failed/skipped |
| Frozen E1/E2 | 13/13 passed; zero failed cases; zero safety escapes |
| Wheel | `guarded_desktop_agent-0.1.0-py3-none-any.whl`; SHA-256 `4fd70facfe9957cf51e8a939f9c0421829c88e74e0bc3c9e3dfa8340f7719c26` |
| Installed wheel E1/E2 | 13/13 passed; package version `0.1.0` |
| Offline guarantees | no desktop calls, provider integration, or forwarded provider credential |

The ignored local report and wheel are reproducible evidence inputs, not
release artifacts. The report does not satisfy CI, E3, E4, human review, or
release approval by itself.

## Current-candidate bounded E3

Both runs used the harmless fake stdio MCP child, one reviewed observation,
zero side effects, no Windows driver, and a clean worktree before and after.
No credential, prompt, model prose, tool output, provider response identity, or
local state path is retained here.

| Provider | Explicit reviewed model | Command scope | Result |
| --- | --- | --- | --- |
| OpenAI | `gpt-5.6-terra` | ordinary read/tool/result/final plus bounded `plan run` | `2 passed in 21.35s` |
| Anthropic Claude | `claude-sonnet-5` | ordinary read/tool/result/final plus bounded `plan run` | `2 passed in 21.15s` |

This promotes only current-candidate fake-MCP provider compatibility. It does
not prove desktop, application, action, or E4 behavior.

## Native operator evidence

Every native attempt completed without plausible user mouse, keyboard, or
focus interference. The available Windows machine exposed one monitor:
full bounds `(0, 0)-(2560, 1600)`, work area `(0, 0)-(2560, 1528)`, and 144 DPI.

### Composed accessibility, theme, and localization

`scripts/smoke_operator_accessibility.py` covered five presentation cases in
both English and Simplified Chinese:

- dark at 100%;
- light at 100%;
- High-Contrast-over-light at 100%;
- light at 200% text scale; and
- dark at 400% text scale.

All ten Decision Cards exposed the expected UIA Text/Edit/Button path, started
and ended on safe `option_deny`, remained inside the selected work area, and
returned `option_deny`. Presence matched the monitor bounds and reported
capture exclusion accepted. Presence and Progress preserved the foreground.
At 200% and 400%, the live Progress windows reflowed inside the work area and
the live Decision Cards remained bounded. This is automated native geometry
and UIA evidence, not human visual or screen-reader evidence.

### Fixed notification lifecycle

`scripts/smoke_approval_notification.py` passed English and Simplified Chinese
fixed-content notification show/version/withdraw lifecycles. Shell delivery was
accepted, the hidden host existed during delivery and was destroyed afterward,
and foreground remained unchanged. Windows quiet time may suppress a toast, so
the result does not claim that a person saw, heard, or could retrieve it from
Notification Center.

### Decision Card current-contract regression

`scripts/smoke_decision_card.py` passed the current fixed-frame, non-topmost,
plain-language card contract. The card took focus, yielded Agent authority,
exposed the four choices plus details affordance, routed one synthetic approval
through the sole Runner-to-fake-MCP path and verification observation, denied a
five-second timeout with zero side-effect dispatch, and restored foreground.

The audit first reproduced a probe failure because that script still expected
the superseded resizable/scrollable frame and pre-localization long labels.
Current deterministic tests proved those expectations stale. The probe was
updated to the current fixed-frame/plain-language contract and then passed from
the clean commit above; no product code was changed to make the smoke pass.

## Explicitly open or unavailable gates

| Gate | State | Why it is not promoted |
| --- | --- | --- |
| Human Narrator/NVDA/JAWS review | `NOT RUN` | UIA automation cannot judge spoken order, pronunciation, verbosity, braille, or human usability |
| Human 200%/400% and visual-design review | `NOT RUN` | native geometry passed, but no person approved legibility, clipping, hierarchy, or aesthetics |
| Physical two-monitor usability | `BLOCKED BY AVAILABLE HARDWARE` | the machine enumerated one physical monitor; synthetic negative coordinates do not replace hardware evidence |
| Native cooperative takeover timing | `NOT RUN` | offline state/CAS coverage exists, but real operator timing requires a dedicated current-candidate workflow plan |
| Current-candidate Desktop Ask / public-web-word application results | `NOT RUN` | retained earlier results predate feature freeze; rerun belongs to the next bounded product-integration item |
| E4 four-cell isolated desktop matrix | `NOT RUN` | explicitly deferred by the user until the non-E4 sequence is complete |
| Release review, tag, artifact publication | `NOT RUN` | no authority was granted; PR #272 evidence and wheel are stale and non-reusable |

`NOT RUN` and `BLOCKED BY AVAILABLE HARDWARE` are disclosures, not passes.
Nothing in this record permanently waives a missing gate.

## Subsequent exact-candidate product integration

The application row above remains the truthful state of this dated
`23e71a5` audit. A later bounded item built one clean wheel from runtime
candidate `d254cd9` and passed both the installed Notepad Desktop Ask and the
fixed Chrome-to-disposable-Word workflow. Its separate
[current-candidate product integration record](CURRENT_CANDIDATE_PRODUCT_INTEGRATION_EVIDENCE.md)
owns those later run IDs, digests, receipts, cleanup facts, and explicit open
gates. That later result does not retroactively convert this audit's human,
hardware, E4, or release rows into passes.
