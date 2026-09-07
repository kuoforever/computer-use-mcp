# Continuous local-model Word evidence

Status: one fresh fixed Word attempt passed on 2026-09-07 (`GDA-GUI-007`).

This executes the unchanged [Word diagnostic](GUI_WORD_PROBE_V1.md) at Runtime
`e112dd1455e5f349db353ffaa6e667d1f9390cbf`, using model checkout
`7188b9a84b9fda86cb2a59c1f7d5fa55b12815ac`. The earlier failed and recovered
receipts remain unchanged. No code, model, adapter or default route was changed.

## Actual result

[Safe receipt](evidence/gui-word-continuous-native-2026-09-07.json):

| Phase | Result |
| --- | --- |
| Main run | `gui-word-23968539e06247858d463318ccbd3813`, `SUCCESS` |
| Local model | One GUI-Owl 4B plus experimental LoRA request; 797 input / 29 output tokens |
| Generation | 2.297 seconds; 9,331,244,032 peak allocated bytes |
| Controlled sequence | Model coordinate click, Ctrl+End, one fixed-text type, Ctrl+S |
| Main accounting | 21 tools, four scoped approvals/actions, zero tool failures or retries |
| Save verification | Complete expected body before and after Save, plus disk OOXML equality |
| Reopen | New Word process; `gui-word-a7a921917fe8492a9cf1058ea22f21a9`, `SUCCESS` |
| Reopen accounting | Two read-only tools, zero model calls/actions/failures/retries |
| Cleanup | Both exact disposable windows closed; artifact hash unchanged |

Artifact SHA-256:
`8e67bc2f0ae2fbf631be6c677ffc264f903b4c61a542ef7a870898a6636da2aa`.
The local synthetic DOCX is under ignored `out/gui-word-continuous-20260907.docx`.
The main run needed no recovery. Reopen is intentionally a separate process and
read-only run, so the combined measured totals are 23 tools and four actions.
Fixture creation, foreground preparation and window close/reopen are operator
test lifecycle operations outside those action counts. Host provider turns are
zero; the one isolated local inference is counted separately.

## What this establishes

One screenshot-conditioned local editor proposal can pass the existing Runtime
checks and complete the fixed Word write/save path continuously. A fresh Word
process reads the same full saved body. This is an application diagnostic, not
an ordinary Host Provider integration or evidence that the model planned the
whole task or authored the content. The workflow uses fixed synthetic text.

The 2.297-second metric is generation time, excluding load and desktop work.
Recorded tool latency is 57,820 ms for the main run and 1,004 ms for reopen;
these are tool sums, not total wall-clock completion time. No input change was
detected between measured calls; MCP owns the human-activity gate during injected
actions. This is not a global input lock or exclusion of every concurrent change.

One passing task is not a success-rate benchmark or broad Word/layout coverage.
Model admission remains failed (17/24 against 20/24). No public webpage was read,
no summary was generated, and Chrome-to-Word or cloud-planner integration is not
proven here. The next bounded objective is integration readiness for the fixed
public-page-to-Word scenario, activated through `PROJECT_STATUS.md`.

Raw images, model output and document text are absent from the safe receipt and
automatic Full Cycle export. Lane B and all deferred gates remain unchanged.
