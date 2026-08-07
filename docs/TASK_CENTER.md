# Read-only Task Center and outcome receipts

> **Status: implemented as a CLI-first local product surface and offline
> verified.** It is not a native desktop window, notification service, or
> general process-control surface. Live provider, desktop, application, and
> release evidence remain separate gates.

## Purpose

The Task Center answers two operator questions from durable evidence:

1. Which validated local tasks need attention, are still in progress, or are
   already history?
2. What fixed outcome can the product honestly report without repeating model
   prose or exposing raw task and tool content?

Use the installed command in its human-readable form:

~~~powershell
guarded-desktop-agent task center --config C:\absolute\path\agent.toml
~~~

Automation may request the same bounded projection as versioned JSON:

~~~powershell
guarded-desktop-agent task center `
  --config C:\absolute\path\agent.toml `
  --limit 20 `
  --json
~~~

The limit is `1` through `100`; the default is `20`. Attention items are
selected before in-progress and historical items.

## Trust and authority boundary

~~~text
validated redacted run checkpoints -----> progress projection --+
validated campaign snapshots ----------> progress projection --+--> Task Center
verified public-web-word completion ----> private receipt -------+
~~~

The Task Center has no provider, MCP, desktop, approval, resume, retry, cancel,
campaign-advance, or notification port. It cannot change durable task state.
Every JSON capability flag is fixed to `false`, and the human view repeats the
same boundary.

Run and campaign facts come only from the structurally validated, redacted
projection already owned by `computer_use_agent.progress_view`. A corrupt,
unsafe, oversized, or unsupported record is rejected or isolated; it is not
partially displayed. Nonterminal state is never treated as proof that a process
is currently alive.

## Grouping and fixed receipts

The surface groups items as:

- **Attention** — waiting approval, paused, failed, unknown outcome, or a
  completed public-web-word run whose product receipt is missing or invalid;
- **In progress** — another validated nonterminal run or campaign state;
- **History** — validated successful, cancelled, or otherwise terminal state.

Receipt wording is compiled from fixed state and failure-code mappings. In
particular, an unknown side-effect outcome always says:

> Result unknown — do not retry automatically

The projection may include bounded timestamps and progress metrics only when
the owning checkpoint supports them. It never includes raw task text, model
prose, screenshots, typed content, provider traffic, approval payloads, or raw
tool results.

## Product completion receipt

After `workflow public-web-word` has proved the durable save, exact artifact
digest, independent reopen/read-back, and both exact fixture-cleanup checks, it
writes one immutable version-1 receipt:

~~~text
state_dir/workflows/public-web-word/<run_id>/receipt.json
~~~

The strict receipt contains only the workflow kind, run ID, absolute DOCX path,
SHA-256 digest, four required verification booleans, and a UTC completion
timestamp. It is written exclusively and never overwritten. A symlinked path,
oversized file, extra or missing field, unsupported version, invalid path or
digest, false verification flag, or malformed timestamp fails closed.

The absolute artifact path is private local product data. It is shown only when
the operator explicitly runs Task Center; it is not read by, or added to, the
automatic Full Cycle Lane A export. The receipt contains no task, UI content,
model content, provider data, screenshot, typed text, credential, approval, or
tool-result body.

A generic successful run receives a fixed success summary but no artifact
claim. A public-web-word success claims that its document was saved and
verified only when its strict receipt is present. A missing or corrupt receipt
moves that item to Attention and asks for inspection; it does not reconstruct
or replay the workflow.

## Verification boundary

Offline tests cover strict receipt parsing and immutability, path and size
safety, corrupt-record isolation, attention-first limiting, fixed status
wording, artifact-claim gating, campaign/run composition, CLI text and JSON,
and the absence of state creation in an empty Task Center. Those tests establish
the local contract. They do not establish a native window, mobile notification,
live provider behavior, desktop behavior, application acceptance, or a release
artifact.
