# Reviewed Word content adapter

Status: implemented and validated offline; no new native application evidence.

GDA-GUI-013 adds an optional Host-owned `WordContentAdapter` to the existing
`scripts/probe_gui_word.py` Python entry point. The CLI remains fixed-note only.
This change is validated using injected model responses, fake MCP transport and
synthetic DOCX packages. No native Word or model call is evidence for this slice.

Validation: 99 focused adapter/Word-probe/handoff tests pass. Full local regression
before the final bounded durability-reader refinement passed 3,136 tests with 39
skips and one existing Pydantic warning. The final reader and complete 99-case
focused gate pass; Ruff, mypy (182 source files), docs consistency (13 reviewed
tools), dependencies and diff checks pass. Final CI must pass before merge.

## Construction and dispatch

Trusted application code constructs the adapter from candidate bytes,
`ContentProfile`, `HostContentContext` and an explicitly selected `.docx` path.
The generic handoff validates the complete candidate's review, source, target,
initial body, content and expected final body. The adapter additionally binds
the resolved Host-selected path and initial DOCX byte digest. A model cannot
provide its own Host context or select a path via the candidate's target ID.

Pass the adapter as `content_adapter=` to `probe`. Its payload replaces NOTE only
on this explicit path. The local GUI request's context digest also binds the task
digest. Model output still supplies only a grounded editor point. The sequence
remains click, Ctrl+End, type, Ctrl+S through `WordRun.call` and the existing
AgentRunner execution boundary, policy, one-call approval, WAL, grounding and
budgets. Before writing, the complete UI body and initial file are revalidated.
The adapter rechecks the initial file before each action, including save. AutoSave
or another writer changing that file causes rejection; it is not silently adopted.

## Exact text and file verification

The reviewed path compares complete body text exactly, without collapsing spaces
or line breaks. Save is allowed only after the expected UI body was read back.
After save, the UI body and bounded DOCX main-body snapshot must both equal the
reviewed expected body; its actual byte digest is retained. The file check may wait
for durability with at most 51 bounded reads and 50 sleeps of 0.1 seconds; this
never replays a GUI write/save. A subsequent read-only
probe with `reopen=True` requires that exact saved file and expected complete UI
body. Only that second phase sets `complete_content_verified=true`. The first
phase's success is write/save evidence only.

The file reader accepts at most 8 MiB per DOCX and 1 MiB for UTF-8 `document.xml`,
rejects duplicate XML entries and DTD/entities, and reads ordinary paragraph text
without stripping whitespace. Tables, fields, tracked changes, drawings, tabs and
manual breaks are unsupported rather than silently ignored. Headers and rich
formatting are outside this plain-main-body profile. Other formats need their own
adapters. The fixed-note predecessor keeps its historical normalization behavior.

## Failure and evidence boundaries

The adapter consumes its main/reopen phase before processing. A rejected or unknown
main attempt cannot be retried with that object, and no save-only recovery is
available for reviewed content. This is process-local consumption, not durable
deduplication against object reconstruction. A live attempt still needs a reviewed
new attempt identity/record and explicit handling of interrupted/unknown outcomes.

The read-only phase validates a caller-presented window and saved artifact; it does
not itself close/open Word or prove that a new application session occurred. Host
orchestration must establish that lifecycle independently. The existing window
guard matches a unique Word title/scope, not an authenticated full filesystem path;
the Host must independently establish its selected window/file relationship.
File-byte and UI checks
are not an atomic snapshot and do not replace input-interference attribution.

Receipts include digests/counts, phase and artifact binding, with no content or
source prose. The explicit content path uses receipt version 2; the fixed-note
default retains its original version-1 fields without a new null field.
The nested generic `execution_authorized=false` remains a statement
about the inert handoff; only Runtime's existing action permits authorize calls.
No automatic Lane A export, Lane B activation or model promotion is introduced.
The old fixed-note CLI, consumed receipts and summary failures remain unchanged.

Next: prepare one separately scoped disposable Word run with a real Host review,
fresh target observation and explicit close/reopen evidence. A synthetic text run
would prove adapter integration only; it must not be called a generated webpage
summary or complete Chrome-to-Word demo. No live run is activated by this document.
