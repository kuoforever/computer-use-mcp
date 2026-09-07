# Local-model Word artifact diagnostic v1

Status: implemented; real artifact verified after recovery on 2026-09-07.

Subsequent `GDA-GUI-007` evidence: the unchanged revised main sequence passed
once continuously, followed by a new-process read-only reopen. See the
[separate evidence](GUI_WORD_CONTINUOUS_EVIDENCE.md); the recovered history below
retains its original outcome.

`GDA-GUI-006` is a development-only, fixed-text Word readiness slice. The
2026-09-07 attempt produced an artifact **after explicit recovery**; it was not
an uninterrupted successful run. No Chrome source, summary generation, cloud
planner, model admission or production default is added.

## Recorded outcome

The [safe receipt](evidence/gui-word-native-2026-09-07.json) retains these phases:

- Initial observation rejected before inference or actions because the window
  TextPattern stream included ribbon font/size fields. A separate grounded body
  selector now requires a complete unique Document block; it never strips text
  by guessing font names or accepting substring-only document verification.
- `gui-word-faa42481866644fb947a33ac28114594`: one GUI-Owl 4B plus unchanged
  experimental LoRA request, 2.094 seconds generation, 797 input / 29 output
  tokens, 9,331,244,032 peak allocated bytes. A screenshot-conditioned explicit
  coordinate passed the editor bounds guard. Click, Ctrl+End and one fixed-text
  type call succeeded through Runner/MCP. The next UIA snapshot timed out at
  32,018 ms; the original ledger remains `UNKNOWN_OUTCOME`. Save was not called.
- A first save-only attempt found no interactive elements and performed no action.
  An ancillary read-only diagnostic detected changed input and was invalidated;
  it is not positive attribution evidence or a model retry.
- `gui-word-e64126692e4e4781afeb022c2922892d`: a new Session verified the exact
  expected full body, executed only Ctrl+S, then verified semantic and disk text.
  Five tools, one approval/action, zero model requests. No text was replayed.
- `gui-word-f1440e650e554030ba680d86b2380ec8`: a new Word process reopened the
  same saved artifact. Two read-only tools, zero model requests/actions, full
  body comparison and unchanged artifact hash. Both test windows were closed.

Artifact SHA-256: `3fe9dd6b36e7b136373d5ce817b35c0e328db827713d06c7ba5c606a2f05b476`.
The DOCX remains local under ignored `out/`; it is synthetic test content in
the existing packaged template, not a finished model-authored research brief.
Generation time excludes file verification, model loading and desktop tools.
The local model's previous admission result remains 17/24 against required 20/24.

## Authority and acceptance

The operator creates a new `out/gui-word-*.docx` exclusively from the existing
packaged template and launches it in an independent Word process (`/q /x`).
Initial content must byte-match that template. Actual window selection and
foreground setup are separate from measured execution. Only this disposable
file and its exact observed Word window are authorized.

The separately named model worker receives one screenshot with a fixed Word
editor instruction, request ID and context digest. It has no desktop interface.
It uses the pinned local files/environment and one tool-free inference with
the prior 4096/192 token, 60-second generation and 15 GB allocated-memory caps.
Its parent preserves the 180-second process timeout, offline flags, restricted
bootstrap environment and bounded response validation. This is not an OS sandbox.
The old fixture worker and prior evidence stay unchanged. The existing strict
native syntax parser is reused; this Word harness does not claim the full native
ref compiler or the strict fixture metadata collector accepted a Word ribbon.

The Host accepts only one native left-click coordinate at least eight pixels
inside the uniquely named, enabled, visible page editor. After inference it
rechecks foreground scope/title/owner, editor ref/name/bounds, complete original
body, input tick and MCP generation. Focus is freshly checked before Ctrl+End
and before typing. Every action uses an exact-call, consumed Host permit plus
the unchanged Runner policy, grounding, approval binding, WAL and budget path.
The child MCP retains safe-local mode, Word-only allowlist, baseline attestation,
human activity, e-stop, dangerous-target checks and native execution boundary.

After typing, Save requires a new exact-window list and complete expected body
read, not a second traversal of the entire ribbon. Ctrl+S is an app-level command;
it does not depend on caret placement. Exactly one body block must match the
full normalized original plus one fixed note. Other blocks must be bounded small
fields outside its rectangle; overlaps, missing geometry and extra document-sized
blocks reject. Complete body equality is also required after Save and from disk
OOXML. A separate reopened-file read must match the disk body and caller-pinned
artifact hash. Whitespace normalization is semantic content verification, not
byte identity of formatting; the artifact hash separately covers file bytes.

The final main harness has one model request, at most 21 expected tool calls and
four side effects; hard budgets are 32 calls / four actions / one reserved Host
provider turn. Actual Host provider turns remain zero. The independently opted-in
save-only and reopen modes have zero model calls and no typing/clicking. Unknown
actions are never replayed; recovery first observes current state in a new run.
There is no automatic retry, fallback click, automatic recovery or production
provider registration.

```powershell
.venv\Scripts\python.exe scripts/probe_gui_word.py --allow-disposable-word --scope <actual-hwnd> --document out/gui-word-<unique>.docx --consumer-root <model-checkout>
.venv\Scripts\python.exe scripts/probe_gui_word.py --allow-disposable-word --scope <actual-hwnd> --document out/gui-word-<unique>.docx --save-verified-only
.venv\Scripts\python.exe scripts/probe_gui_word.py --allow-disposable-word --scope <new-hwnd> --document out/gui-word-<unique>.docx --reopen-read-only --expected-artifact-sha256 <verified-sha256>
```

## Limits and next evidence

At `GDA-GUI-006` closeout, the revised main sequence had offline coverage; its
real evidence was the separate localization/write and recovery/save/reopen phases above. That closeout
still needed one fresh uninterrupted attempt, now recorded separately in
[the subsequent evidence](GUI_WORD_CONTINUOUS_EVIDENCE.md). No success-rate, broad Word-version/layout or
complete Chrome-to-Word claim follows. Input checks invalidate changed input
between calls; injected input legitimately changes the tick during actions, where
MCP owns human-activity gating. This does not exclude every concurrent human or
programmatic change. Snapshot equality is not atomic capture or occlusion proof,
and hashes do not grant authority. A screenshot hash need not remain identical
after inference because of Word's blinking caret; this limit is explicit.

Raw screenshots, model output and document text stay in memory/local pipes during
the probe. The safe receipt contains counts, fixed codes and hashes only. The
synthetic DOCX and these diagnostics never enter automatic Full Cycle exports.
Lane B, Full Cycle consumer, Formal Demo preflight and all deferred gates retain
their canonical resume points in `PROJECT_STATUS.md`.
