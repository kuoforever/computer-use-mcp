# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each released entry describes that version and is not revised afterwards.
Current-state claims belong in [Capability status](docs/CAPABILITY_STATUS.md);
a version number states what is packaged, never what has been verified.

## [Unreleased]

### Evidence

- **Clean BOSS item/restart sequence.** Retained a fixed-code on-device result
  with two discovery passes, twelve stable identities, and three consecutive
  fresh-run identity commits without local state correction. All accepted runs
  used one tool call, zero provider calls, and zero tokens; final handoff points
  to ordinal 4 with no retryable or uncertain items.

### Added

- **Bounded BOSS semantic extraction seam.** Added a strict compact result with
  classification-policy binding, canonical digest, and deterministic
  UIA-to-screenshot ladder plus three fixed no-selector CLIs. The separate
  one-item/five-call/zero-side-effect runtime re-establishes the claim through
  Runner, supports UIA/document-text extraction, accepts only strict provider
  JSON, commits canonical digests, and transfers successful handoff to a fresh
  run. Authentication/challenge states hand off, and the still-gated OCR Host
  baseline produces a retryable `CONTENT_UNAVAILABLE` handoff with zero OCR
  MCP dispatch. The initial policy permits only `INSUFFICIENT_EVIDENCE`
  because no user job preference is configured.
- **Bounded BOSS batch-start boundary.** A fixed
  `campaign start-boss-batch` command validates the complete current BOSS
  discovery ledger, requires at least two discovery passes, opens only the
  coordinator-selected first read-only batch (maximum 20 items), creates a
  five-minute heartbeat, and claims only ordinal 1. It accepts no item, URL,
  page, scope, campaign-kind, or batch selector and opens no provider or MCP
  port.
- **Single-item BOSS commit and restart boundary.** Fixed
  `campaign run-claimed-boss` verifies only the exact claimed public identity
  in one foreground `ui_snapshot`, commits a canonical identity-presence
  digest, finishes at the single-call batch limit, and writes handoff. Fixed
  `campaign resume-boss-batch` reconstructs the finished session from durable
  state, transfers heartbeat ownership to a fresh run, opens the exact resumed
  plan, and claims its first item without provider, MCP, or caller-selected
  item input. Both paths are offline verified; semantic job extraction,
  automatic navigation, and the 100-item application gate remain open.
- **`document_text` observation tool.** An eleventh reviewed MCP tool reads
  bounded semantic document text for a scope through a real UIA `TextPattern`
  channel — the ladder rung between the interactive `ui_snapshot` and `ocr`. A
  control's text range covers its subtree, so page text returns as a small
  number of ordered blocks with optional boxes, a content digest, and explicit
  truncation metadata (≤200 blocks, ≤20,000 characters). Password subtrees are
  skipped, and a backend without a semantic text channel fails closed rather
  than dumping the accessibility tree. Offline evidence only; no on-device
  result yet.
- **Operator progress reducer.** A pure checkpoint-to-view-model reducer
  (`computer_use_agent.progress_view`) projects a validated run checkpoint into
  the small, honest field set a passive viewer may show. It reads only the
  checkpoint the `agent report` reader already trusts, copies a fixed allowlist
  of scalar fields, marks checkpoint-v1 token coverage and elapsed time as
  unknown rather than zero, never infers liveness from a nonterminal phase, and
  isolates a corrupt record from valid ones. This is delivery step 1 of the
  [operator progress viewer](docs/PROGRESS_VIEWER.md); no window is drawn yet.

## [0.1.0] — not yet released

First packaged version. **Experimental**: Windows-only, foreground desktop,
primary display. A release does not mean production-ready, and it does not
promote any capability evidence level.

### Added

- **MCP server** over stdio exposing ten reviewed tools: `ui_snapshot`,
  `find`, `list_windows`, `screenshot`, `capture_region`, `ocr`,
  `activate_window`, `click`, `type`, and `key`. Session-scoped `ref_N`
  handles, one bounded relocation of a stale ref by role and name, and no
  silent coordinate fallback.
- **Safety modes.** `safe_local` gates action tools on the foreground window's
  process ancestry, yields to human input, confirms dangerous ref clicks, and
  writes an audit record. `full_control_local` deliberately removes the
  allowlist and yielding checks and retains audit plus emergency stop.
- **Typed Driver Contract** with one in-process Windows implementation using
  UI Automation, screen capture, and process inspection.
- **Agent Host** (`computer-use-agent`) with provider-neutral tool contracts
  and OpenAI and Claude adapters behind optional extras, explicit local
  approval, budgets, a single-owner run lock, and a redacted event ledger.
- **Durable campaign layer**: append-only item ledger with an explicit
  transition table, per-call intent/completion boundary, lease and heartbeat
  ownership, and content digests. An uncertain dispatch is never replayed
  automatically.
- **Bounded OCR** as a static-text fallback after UIA, with run and character
  caps, a whole-call timeout, explicit truncation metadata, and blackout of
  configured sensitive window titles before recognition.
- **Bounded region image capture** (`capture_region`) as the cropped rung
  between OCR and a full screenshot: a grounding envelope plus the PNG of one
  explicit primary-display region, pixel and encoded-byte caps, blackout of
  configured sensitive window titles inside the crop, a digest of exactly the
  bytes the caller receives, and a text-only refusal that carries no pixels.
- **Local privacy boundary**, disabled by default: run-scoped text
  pseudonymization and local screenshot redaction before provider dispatch.
- **Offline release preflight** (`release preflight`) producing a sanitized
  report: candidate stability, lint, tests, frozen E2 manifests, deterministic
  E1/E2, wheel build with SHA-256, and a clean no-deps install smoke.
- **CI** on Windows across Python 3.11, 3.12, and 3.13, plus a wheel
  clean-install smoke, a documentation-consistency gate, and retained JUnit and
  JSON evaluation artifacts.
- **Decision records** for uncertain dispatch, ref actions, and the durability
  boundary; one postmortem; and a statement of AI-assisted development scope.

### Known limitations

- Windows only. No macOS, Linux, or multi-monitor coordinate support.
- Foreground desktop, primary display. Not a background worker.
- Not a browser automation framework. Chromium-family UIA trees may be
  incomplete until accessibility content is exposed.
- No application acceptance evidence. Retained BOSS records cover bounded
  read-only observation of specific pages only.
- Screenshot redaction is title-substring based, not comprehensive secret
  detection.
- Live provider and isolated desktop validation remain explicit human gates and
  are deliberately absent from default CI.

[Unreleased]: https://github.com/kuoforever/computer-use-mcp/compare/main...HEAD
