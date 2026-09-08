# Content handoff v1

Status: GDA-GUI-012 implementation and offline validation. This module has no
provider, filesystem, browser, Word, Runner or desktop dispatch port.

Validation: 40 focused tests pass. Full local regression before the final large-
integer parser edge repair passed 3,108 tests with 39 skips and one existing
Pydantic warning; the repaired parser and all 40 focused cases were then checked.
Ruff, mypy (181 source files), docs consistency (13 tools), dependency and diff
checks pass. Required CI must validate the final commit before publication.

## Reusable boundary

`content_handoff.py` accepts an inert `append_text` candidate with a task and
profile ID, 1-8 source content digests, an opaque target ID and initial body digest,
the exact proposed text and its digest, and expected final-body digest. Required
checks are exactly `readback`, `saved`, `reopened`. The whole envelope is limited
to 65,536 UTF-8 bytes; initial/content/final text to 32,768 bytes each. Profiles
may impose tighter character limits. Text is preserved exactly with LF/tab;
carriage returns, other control characters and invalid Unicode are rejected.
An adapter must establish a consistent text representation before binding; this
module never hides changes by normalizing whitespace after execution.

The first operation is append-only plain text. It does not cover replacement,
spreadsheet cells, rich formatting, arbitrary tools or universal desktop control.
There is no fixed URL, browser, model, summary length or Word dependency in the
core. Two synthetic profiles demonstrate reuse: a browser-summary-to-document
case (900 content characters) and a local project note (2,000 characters).
Their 16,000-character final-document limit is fixture configuration, not a
claim about general document support. The fixture is offline, not source evidence.

## Trust and ownership

The model submits only the candidate. `HostContentContext` is supplied separately
by trusted application code: task/target identity, verified source pins, current
complete initial body, and the canonical candidate digest accepted by an external
factual/content review. Do not build this context from fields in a model response.
Unknown fields, including model-supplied approval or tool instructions, are rejected.
`candidate_digest` is only an identity helper, not validation or approval.

The Host reviewer must assess the exact complete candidate, including source,
target, profile and final-body bindings. Any later content mutation invalidates
that review even when a model recomputes the content/final digests. A matching
review digest records the caller's assertion; it does not authenticate that caller,
prove factual entailment or grant execution authority. Unsupported facts with a
mistaken external approval remain unsupported; a test makes this limit explicit.

`bind_content_task` returns immutable data with copied source pins. Before any
future action, the adapter must re-establish source/target/observation freshness
and use Runtime policy, approval, budgets, WAL and the sole Runner/MCP boundary.
The target ID is an opaque Host handle, never a model-selected filesystem path.
The local GUI model may propose grounded actions; it cannot redefine the content,
destination, completion tests or execution authority.

## Result verification and privacy

`verify_content_results` compares all three complete bodies against the expected
digest and target ID. It rejects missing phases, duplicate append, whitespace
drift, truncated reads and wrong targets. The trusted adapter must independently
prove that saving/reopening occurred, that each body is complete and belongs to
the target; passing three equal strings alone proves none of those events.
Disk artifact binding, run IDs/epochs and live validity belong to that adapter.

Raw source and content remain private application data. The local diagnostic
receipt includes only digests/counts and `execution_authorized=false`; no automatic
Lane A export hook is added. Lane B remains separately gated. No model is promoted.

## First integration

The existing `probe_gui_word.py` still uses its fixed synthetic NOTE and is
unchanged. Its successor can accept a reviewed `BoundContentTask`, preserve the
complete initial body, bind the actual artifact, revalidate before actions, and
use existing write/save/readback/reopen checks. That integration needs its own
tests; this interface is not a live Word run. A real source/summary producer and
Chrome URL/body capture remain pending. Manual fixtures must never be labeled
as model-generated summaries. Full Cycle freeze and Formal Demo pauses remain.
