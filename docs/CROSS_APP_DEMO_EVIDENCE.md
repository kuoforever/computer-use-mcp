# Bounded Chrome-to-Word Demo evidence

> **Result: PASS — retained real-environment run on 2026-07-30.**

## Claim

One controlled local webpage was observed in a dedicated Chrome profile and
one disposable RTF document was edited and saved in Microsoft Word through the
existing Agent Runner and project MCP. The run composed the native Presence,
Progress, and Decision Card surfaces.

This result is limited to the exact controlled workflow. It is not evidence of
general browser automation, general Office automation, arbitrary webpage
understanding, or universal GUI capability.

## Retained run

| Field | Value |
| --- | --- |
| Run ID | `cross-app-demo-20260730-034539` |
| Result | `PASS` |
| Tool calls | `13` |
| Approved side effects | `5` |
| Applications | Dedicated-profile Google Chrome and disposable Microsoft Word document |
| Provider | Fixed deterministic Demo provider; no model authority |
| Dispatch | Existing Runner and stdio project MCP only |

The output log reported `PASS`, the error log was empty, and an independent
post-run file read found the fixed `VERIFIED CROSS-APPLICATION SUMMARY` marker
in the saved RTF artifact.

## Observed sequence

1. Enumerate the controlled Chrome and Word windows.
2. Show a Decision Card, activate the exact Chrome window, and verify success.
3. Re-observe the Chrome window and perform one bounded primary-display OCR
   observation.
4. Re-enumerate windows so the Word identity is fresh after the Chrome stage.
5. Show a Decision Card, activate the exact Word window, and re-observe it.
6. Show separately bound Decision Cards for edit-area selection, fixed text
   input, and `Ctrl+S`.
7. Observe document text after input and again after save.
8. Verify the fixed marker in both the semantic observation and saved file.

The application owning the current step was placed in the foreground before
that application stage. Foreground activation was postcondition-verified; the
workflow would stop rather than continue against a background application.

## Safety boundaries exercised

- The Runner remained the sole policy, grounding, approval, budget,
  persistence, and MCP dispatch authority.
- Five effects required five exact operator decisions.
- Approval clicks yielded to the human-activity gate before dispatch.
- Window identities were refreshed after an activation invalidated prior
  grounding.
- OCR and typed-text safety baselines were attested by the initialized MCP
  session; an absent baseline removes the affected tool from provider access.
- OCR output was accepted only as a bounded observation envelope. The fixed
  fixture summary remained local reviewed data and OCR text never became
  execution authority.
- Structured observation failures map to redacted action-error status instead
  of appearing as successful observations.
- No personal browser profile, account, production document, message, or
  network service was used. The webpage came from a temporary loopback server.

## Validation

After implementation:

~~~text
1434 passed, 8 skipped
ruff: passed
mypy: passed
docs consistency: passed
git diff --check: passed
~~~

The full Full Cycle closure task resumes at `GDA-FC-002`; this Demo evidence
does not create a second active project tracker.
