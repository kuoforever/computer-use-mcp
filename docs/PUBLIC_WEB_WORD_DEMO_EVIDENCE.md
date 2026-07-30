# Public-web-to-Word Demo evidence

> **Result: PASS — retained real-environment run on 2026-07-30.**

## Claim

One public Microsoft Support article was reviewed through a dedicated,
non-maximized Chrome profile. The workflow performed an approved page
navigation, then added a fixed public-source summary to a professionally
formatted research-note DOCX in real Microsoft Word with visible paced typing.

This is bounded evidence for the exact public page and Word fixture. It is not
a claim of arbitrary web understanding, authenticated browser automation,
general Office automation, or universal GUI capability.

## Retained run

| Field | Value |
| --- | --- |
| Run ID | `cross-app-demo-20260730-042826` |
| Result | `PASS` |
| Tool calls | `17` |
| Approved effects | `7` |
| Web source | Microsoft Support, “Collaborate on Word documents with real-time co-authoring” |
| Browser | Dedicated-profile Chrome, `1280x900`, positioned at `(80,80)` |
| Document | Disposable Word collaboration research notes |
| Dispatch | Existing Runner and stdio project MCP only |
| Provider | Fixed deterministic Demo provider; no model authority |

The output log reported `PASS`, the error log was empty, and an independent
post-run DOCX read found the fixed `VERIFIED PORTAL FOLLOW-UP` marker.

Post-evidence restart hardening adds a per-run `initial-state.json`, a
microsecond-unique run directory, an empty dedicated Chrome profile, a
byte-identical copy of the pristine DOCX template, absence of the typed marker,
fixed Chrome geometry, and foreground-only binding for a same-title browser.
Two consecutive offline fixture preparations verify that no profile, document,
or run identity is reused. The retained application run above predates this
restart-hardening delta; do not claim an on-device repeated-start result until
one fresh run is retained on the hardened code.

## Visible sequence

1. Enumerate and exactly bind the dedicated Chrome and Word windows.
2. Approve Chrome activation; re-observe the public Microsoft Support page.
3. Perform one bounded primary-display OCR observation.
4. Approve `PageDown` while Chrome remains foreground, then re-observe.
5. Refresh the Word window identity, approve activation, and re-observe Word.
6. Approve the real Word edit-area focus and `Ctrl+End` cursor movement.
7. Approve one fixed text effect. The focused-control fallback entered the
   source summary with a `0.035` second per-keystroke delay.
8. Verify semantic document text, approve `Ctrl+S`, re-observe, and verify the
   durable DOCX package.

## Approval heartbeat

Decision Card interaction itself counts as recent human input. The Demo now
uses a read-only approval-to-dispatch heartbeat instead of guessing a fixed
sleep:

- sample Windows last-input age every `250ms`;
- require three consecutive samples at least `3.25s` old;
- reset the healthy streak after any new input;
- defer without dispatch after `60s` or on probe failure;
- never retry an action after an MCP rejection or unknown outcome.

An earlier run demonstrated both remaining boundaries: the MCP rejected a page
key while human input was recent, and another run rejected it when ChatGPT
instead of Chrome owned the foreground. Neither action was replayed. The
retained run passed only when both heartbeat and foreground postconditions were
satisfied.

## Data and evidence limits

- The web source was public and required no login.
- The workflow did not submit a form, create an account, post a comment,
  download a file, or change remote state.
- The Word document used public-source research notes rather than personal or
  production content.
- OCR remained bounded observation data and never became execution authority.
- Static DOCX-to-PNG QA was unavailable because LibreOffice was not installed;
  the document was inspected in real Word during the retained run and was
  structurally reopened afterward.
- The completed Demo restores `GDA-FC-002` as the single active closure task.
