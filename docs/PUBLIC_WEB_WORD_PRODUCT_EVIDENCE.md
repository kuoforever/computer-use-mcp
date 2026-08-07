# Public Web to Word exact-candidate evidence

> **Status: PASS.** This record supports only the fixed installed workflow and
> exact Windows/provider/application scope below. It retains hashes, counts,
> state transitions, and visual conclusions rather than source text, model
> prose, typed content, or shared-desktop screenshots.

## Acceptance boundary

- Runtime source candidate:
  `74544d8c7f63958268a5615217f27fa59b819deb`.
- Product surface: a clean-wheel installation of
  `guarded-desktop-agent workflow public-web-word`, not an internal Python API
  or fake MCP.
- Platform: Windows 11, Python 3.13, one supervised foreground desktop and
  primary display.
- Provider: OpenAI Responses API with reviewed model `gpt-5.6-terra`.
- Applications: one fresh Chrome fixture on the fixed public Microsoft Support
  source and one disposable Microsoft Word DOCX fixture.
- Authority: model-proposed observations and actions used the installed
  `AgentRunner` and sole stdio MCP path. The user approved each Decision Card;
  no unapproved action, direct automation bypass, manual document correction,
  or ambiguous user-input event contributed to the retained result.
- Data boundary: the retained record contains only bounded metadata. The raw
  page observation, authored brief, typed tool arguments, model response, and
  screenshots remain outside the repository.

The clean source archive and wheel were built before the live run. The later
evidence-only documentation change does not alter runtime or package inputs.

## Retained result

| Field | Observed |
| --- | --- |
| Runtime source | `74544d8c7f63958268a5615217f27fa59b819deb`; clean Git archive |
| Wheel | `guarded_desktop_agent-0.1.0-py3-none-any.whl` |
| Wheel SHA-256 | `b9eef2983d65a3e8044fa26126735e2e089fa3ff3e5248fc285f6a01c1e9ab22` |
| Fresh install / doctor | Python 3.13 virtual environment with `agent-openai`; `ready=true`; exact 13 installed sibling-MCP tools |
| Template SHA-256 | `3311022016ab64287b169e44cb072b0f5e11612fa821b8dc6e754d3cdd973a63` |
| Provider / model | OpenAI / `gpt-5.6-terra` |
| Source | Fixed Microsoft Support co-authoring page identified by title and URL in bounded CLI metadata |
| Run ID | `public-web-word-e713ae032a3eb8ebf9923cc4eeeca02d` |
| Authored brief projection | 518 characters; 3 bullets; SHA-256 `99090012c9777c6aa1182b52c95ec53941a7d394218fd85f01699d778d085d9f` |
| Artifact | New disposable DOCX; SHA-256 `db01a12a7b539893b6f0063d0f933e078fd08ce91db2bcd369006c3573d01b76` |
| Workflow verification | Pre-save semantic match, `Ctrl+S`, post-save semantic match, exact OOXML content and structure, then independent reopen/readback all passed |
| Model/runtime usage | 17 tool calls; 5 side effects; 0 proposal corrections |
| Cleanup | Exact Chrome and Word fixture windows closed; independent verifier window closed; every reported `window_cleanup_verified` value was `true` |
| Bounded CLI output | 1,452 bytes on stdout; 0 bytes on stderr; no raw brief in the output |
| Installed presentation defaults | Action feedback and passive progress remained opt-in for this product batch |

Fresh Chrome observations grounded the model-authored brief. The Host accepted
the write only after the model selected the uniquely observed Word editor, then
enforced the fixed pre-save read, save, post-save read, completion sequence.
The disk package contained the exact ephemeral brief, and a new Word process
read the same content back. The reopen-only comparison normalized paragraph
whitespace exposed by Word TextPattern; the pre-save, post-save, and OOXML
checks retained their stricter contracts, so no non-whitespace mismatch was
accepted.

## Visual render QA

The bundled document renderer could not start because LibreOffice was not
installed on the test machine. That failed toolchain attempt is not counted as
render evidence and does not create an end-user LibreOffice dependency.

The exact final artifact was instead reopened in Microsoft Word and inspected
through the same reviewed Runner/MCP desktop boundary. Visual QA run
`public-web-word-render-742da18da3974167b16085e6dfe1f9e1` used 9 tool calls
and 3 user-approved side effects to activate the exact window, capture the top,
move to the end, capture the bottom, and close the fixture. At 100% zoom Word
reported page 1 of 1. The title, metadata, section hierarchy, source reference,
and generated brief were visible with natural wrapping; the final page showed
no clipping, overlap, missing glyph, footer collision, or page overflow.

The two QA captures were inspected at original resolution but are deliberately
not committed because they include ambient shared-desktop pixels. Their safe
conclusion is retained here. The exact Word window and the QA run lock were
clean after capture.

## Validation

The executable candidate passed the complete local gate:

```text
1877 passed, 8 skipped
Ruff: passed
mypy: passed over 127 source files
documentation consistency: passed with 13 reviewed tools
git diff --check: passed
```

The fresh installed-wheel `config init`, `config doctor`, application run,
save/readback, independent reopen, visual QA, and exact-window cleanup gates
also passed. GitHub CI and review remain publication gates for the change that
adds this retained record; they do not retroactively widen the live result.

## Supported claim

This record supports one model-scoped, provider-scoped, application-scoped
installed workflow from a fixed public webpage to a new disposable Word
document, including explicit human approval, durable save and independent
reopen verification, real-Word visual QA, and exact fixture cleanup. It does
not establish arbitrary webpages, every provider or model, background use,
unattended operation, account-authenticated content, other browsers or office
suites, multi-monitor behavior, universal GUI coverage, or release readiness.
