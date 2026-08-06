# Public Web to Word workflow

`guarded-desktop-agent workflow public-web-word` is the first installed
cross-application product workflow. It opens one fixed public Microsoft Support
page in a fresh Chrome profile, lets the configured model inspect that page,
and appends a model-authored two-to-four-bullet brief to a disposable Word
document.

## Product boundary

The command is intentionally fixed rather than a general browser automation
surface:

- source: Microsoft Support, **Collaborate on Word documents with real-time
  co-authoring**;
- applications: installed Google Chrome and Microsoft Word on Windows;
- output: one new absolute `.docx` path that is never overwritten;
- model behavior: choose each reviewed step and author the brief from fresh
  page observations;
- desktop authority: every model-proposed desktop observation and action passes
  through the existing `AgentRunner` and sole MCP desktop boundary;
- action authority: the generated profile uses `approved_actions`, so the
  existing local approval surface still authorizes each proposed side effect;
- shared-desktop coexistence: after a Decision Card click, the action waits for
  three stable human-idle samples inside that single MCP call; continued user
  input keeps control with the user, and the profile's 15-second bound returns
  before the 30-second MCP bridge timeout;
- persistence: continuation is disabled because typed content remains
  ephemeral and does not enter the continuation record.

The Host does not contain the bullet findings. It constrains only the required
heading/source/URL shape, two-to-four-bullet bound, exact fixture windows,
the selected main Word editor bounds, and save-verification sequence. Invoking the CLI
also authorizes the fixed fixture launch and exact-process close lifecycle;
those trusted orchestration steps are not model calls. Model prose is not a
completion signal.

Each bullet uses a literal `• ` prefix. That preserves the exact authored text
through Word instead of triggering hyphen-based AutoFormat list conversion.

## Installed use

Install either provider extra, then create the dedicated profile:

```powershell
guarded-desktop-agent config init `
  --profile public-web-word `
  --provider openai `
  --model <reviewed-model-id> `
  --output C:\absolute\path\public-web-word.toml

$env:OPENAI_API_KEY = "<provider credential>"

guarded-desktop-agent config doctor `
  --config C:\absolute\path\public-web-word.toml
```

Run the fixed workflow with a new output path:

```powershell
guarded-desktop-agent workflow public-web-word `
  --config C:\absolute\path\public-web-word.toml `
  --output C:\absolute\path\collaboration-brief.docx
```

Chrome and Word are discovered from `PATH` and standard Windows installation
locations. `--chrome-executable` and `--word-executable` accept absolute paths
when an installation is elsewhere.

## Completion evidence

Success requires all of these states in one run:

1. the model observes the unique Chrome and Word fixtures;
2. fresh Chrome evidence grounds the model-authored brief;
3. a fresh exact-window UIA observation identifies one enabled Word editor; a
   screen-sized grayscale preview derived from at most `160×120` samples keeps
   the original coordinate space while visually grounding the screen, and the
   model proposes the explicit editor-center coordinate; no ref silently
   degrades to coordinates;
4. the full brief is observed before `Ctrl+S` and again afterward;
5. the OOXML package on disk contains the exact ephemeral brief;
6. the original fixture windows close cleanly;
7. the same DOCX is reopened in a new exact Word process and read back through
   a second bounded `AgentRunner` / MCP observation;
8. the verifier window also closes cleanly.

The command prints bounded JSON metadata: provider/model, run ID, source
identity, artifact/template/brief SHA-256 digests, character and bullet counts,
proposal-correction count, tool/side-effect usage, reopen status, and exact
process-cleanup outcomes. It does not print or retain the raw brief in that
metadata.

Visual render QA is a release/evidence gate, not a hidden runtime dependency.
The installed workflow needs Word, but it does not require LibreOffice or a PDF
renderer on an end user's machine.

## Failure and retry

A provider call is bounded by the generated 90-second request timeout. Invalid
model proposals may be corrected twice before any desktop dispatch. An
ambiguous fixture, stale window list, out-of-scope tool, invalid brief, missing
disk content, failed reopen, or unresolved exact-process cleanup returns a
fixed non-zero error.

The output is exclusive and is never silently replaced. A failed attempt may
leave its partial DOCX for inspection; retry with a new output path after the
cause is resolved. Unknown side-effect outcomes remain governed by the ordinary
Runner contract and are never automatically replayed.

This workflow does not establish arbitrary webpages, other browsers, other
office suites, account-authenticated content, universal GUI coverage, or a
release artifact.
