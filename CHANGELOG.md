# Changelog

Notable changes to this project. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each released entry describes that version and is not revised afterwards.
Current-state claims belong in [Capability status](docs/CAPABILITY_STATUS.md);
a version number states what is packaged, never what has been verified.

## [Unreleased]

### Evidence

- **Exact-candidate Desktop Ask.** A fresh Python 3.13 wheel and state completed
  one installed OpenAI `gpt-5.6-terra` Windows/Notepad
  `document_text(scope=foreground) -> final_response` run. The answer recovered
  the fixture-only codename, arithmetic, and decision with one tool call, one
  final model turn, zero side effects, zero retries, and retained redacted
  [evidence](docs/DESKTOP_ASK_EVIDENCE.md).
- **Clean BOSS item/restart sequence.** Retained a fixed-code on-device result
  with two discovery passes, twelve stable identities, and three consecutive
  fresh-run identity commits without local state correction. All accepted runs
  used one tool call, zero provider calls, and zero tokens; final handoff points
  to ordinal 4 with no retryable or uncertain items.
- **Exact provider E3.** Harmless fake-MCP matrices retain exact Kimi `cn` +
  `kimi-k2.6`, MiniMax `cn` + `MiniMax-M2.7`, and DeepSeek `global` +
  `deepseek-v4-pro`, Doubao `cn-beijing` +
  `doubao-seed-2-0-lite-260215`, Qwen `cn-beijing` + `qwen3.7-plus`, and GLM
  `cn` + `glm-5.2` ordinary, Planner/final, capability, timeout, and continuation evidence
  without promoting sibling routes/models, desktop, E4, applications, or
  release.

### Fixed

- **GLM Planner JSON Object compatibility is exact-scoped.** Live China
  `glm-5.2` E3 returned valid JSON that was not conformant to the Host-requested
  Planner wire: it used unreviewed `arguments_` instead of requested
  `arguments_json`. Only that provider/region/model wire requests string field
  `arguments`; the shared Host compiler still enforces exact keys, allowed
  tools, decoded-object arguments, and reviewed tool schemas. Observed, default,
  duplicate, sibling-route, and sibling-model forms fail closed.
- **Qwen Planner JSON-fence compatibility is exact-scoped.** Live Beijing
  `qwen3.7-plus` E3 exposed intermittent valid plan JSON inside one exact
  lowercase Markdown fence. Only that provider/region/model Planner removes
  the LF-delimited wrapper after the original response-byte gate; unchanged
  Host compilation remains authoritative, and all other wrappers, routes,
  models, ordinary turns, and final responses retain fail-closed behavior.
- **Planner scope values are now executable, not prose.** The first
  exact-candidate Desktop Ask attempt exposed a real `document_text` failure
  when the Planner emitted `"foreground document"` and the Host accepted any
  non-empty scope. Provider schemas now disclose the exact
  `foreground | all | positive decimal window id` grammar, Host compilation
  rejects paraphrased scopes before persistence or MCP dispatch, and both
  Planner prompts require literal schema values.

### Added

- **Formal Demo local intent-disclosure gate.** Added a pure-local typed v1
  disclosure that renders the exact sensitive task and exact provider route
  validated against reviewed static routing rules, with a conservative warning,
  plus exact `COMPILE` and one
  opaque issue/consume transition per in-memory gate instance. Task/route/profile/
  draft drift, returned-record tamper, wrong acknowledgement, copy/forgery,
  cross-gate use, concurrency, and same-gate replay fail closed. Raw
  task bytes are absent from permit and receipt; there is no serialized gate
  loader, provider request, filesystem/persistence, Runner, MCP, Driver, desktop,
  application, CLI, or launcher port and no durable/process-wide exactly-once
  claim.
- **Formal Demo v1 offline contracts.** Added four inert internal v1 data
  contracts for untrusted intent, Host-reviewed scenario and semantic-role
  pins, generic Scope review, and a domain-separated canonical binding digest.
  Exact-key bounded loaders, Unicode-stable canonicalization, tamper and stale
  pin detection, authority rejection, and an explicitly unselected email role
  fail closed without Provider, Runner, MCP, Driver, filesystem, network, CLI,
  desktop, or application ports. This is not a Demo launcher or live evidence.
- **Eight exact provider profiles.** Agent ordinary, Planner, and final-response
  routing now supports OpenAI, Anthropic, Qwen, Doubao, Kimi, DeepSeek, GLM,
  and MiniMax over reviewed Responses, Chat Completions, and Messages wire
  families. Provider credentials/endpoints/capabilities remain separate;
  Qwen alone requires a strict workspace-derived regional endpoint, text-only
  profiles withdraw image tools, and continuation v8 binds
  vendor/model/region/protocol/endpoint. All profiles are offline verified;
  exact Kimi and MiniMax China, DeepSeek global, Doubao China, and Qwen Beijing
  plus GLM China E3 cells are retained, while the remaining routes, sibling
  models, local candidates, E4, and application gates remain unverified.
- **Cooperative Pause/Takeover/Resume.** The installed public-web-word Runner
  loops now publish one strict local control lifecycle. CLI `task pause` and
  `task takeover` become effective only after a durable safe-boundary
  acknowledgement releases Agent desktop authority; `task resume` invalidates
  prior grounding and approval authority and permits only fresh observation
  before later side effects. The product Decision Card routes Human takeover
  through the same path. Possibly dispatched work remains terminal
  `UNKNOWN_OUTCOME` with no replay. This adds no `BlockInput`, continuation,
  campaign, remote-control, Full Cycle export, or second desktop-dispatch path.
- **Host-compiled Pre-run Review.** The installed public-web-word workflow now
  displays a human Scope Sheet before any provider, MCP, application, desktop,
  or fixture startup, covering its fixed goal, applications, read/change
  boundary, exact output, maximum seven one-effect approvals, stop conditions,
  and possible residue. Exact interactive `START` or an explicit
  `--acknowledge-scope` flag starts only the ordinary workflow and grants no
  action approval, retry, or replay authority. A separate `review
  public-web-word` command returns the same text or versioned JSON with zero
  external work. The review is compiled from Host contract strings and exact
  local paths, never model prose.
- **Read-only Task Center and trustworthy outcome receipts.** Added the
  human-first `task center` command over the existing validated redacted
  run/campaign projection, with bounded Attention/In progress/History grouping,
  versioned JSON, fixed Completion/Failure wording, and every control capability
  explicitly disabled. `UNKNOWN_OUTCOME` warns against automatic retry. The
  public-web-word workflow now publishes an immutable strict local receipt only
  after save, digest, reopen/read-back, and both cleanup checks succeed; Task
  Center withholds the artifact-success claim if that receipt is absent or
  corrupt. Neither surface adds a provider, MCP, desktop, approval, resume,
  retry, cancel, campaign-advance, notification, or Full Cycle export port.
- **Installed Runtime doctor and actionable setup UX.** Added `config doctor`
  to verify the selected provider extra and documented credential presence,
  installed MCP executable/cwd, and the exact thirteen names and schemas
  returned by the real sibling MCP handshake. It makes no provider request and
  no MCP tool call. Provider client construction now turns missing extras,
  missing credentials, and initialization failures into one-line corrective
  CLI errors. Clean-wheel CI exercises both provider extras and the real
  installed discovery path. Windows Driver capability metadata now truthfully
  includes its existing `scroll` and `drag` primitives.
- **Desktop Ask first-run vertical.** Added `config init` to generate a
  non-overwriting, user-local, read-only configuration for an installed MCP
  sibling, and added product-facing `ask` over the existing bounded
  Planner/Executor path. `ask` prints the final answer by default and preserves
  run/plan/usage metadata behind `--json`. The Planner scope now includes the
  existing bounded semantic `document_text` observation, so document questions
  can traverse Planner -> Runner -> MCP -> tool-free final response without a
  new dispatch path. English and Chinese quick starts plus the clean-wheel smoke
  exercise the canonical product commands. This expanded scope is offline
  verified; its exact-candidate live result is retained separately from the
  packaged feature claim.
- **Guarded Desktop Agent project identity.** Renamed the repository,
  distribution, product, and MCP service to distinguish the project-local
  runtime from platform Computer Use plugins. Added canonical
  `guarded-desktop-agent` and `guarded-desktop-mcp` commands while retaining
  legacy import paths, console aliases, environment variables, durable state
  paths, and historical evidence.
- **Composable application discovery adapters.** A declarative adapter states
  how one bounded foreground observation yields stable public item identities
  for a reviewed scenario: `link_url` reads identifiers out of hyperlink
  targets on an exact allowlisted host and discards every other URL field,
  while `control_name` reads them out of control names for an exact role set.
  Both require a same-observation source marker, bound snapshot size, identity
  count, campaign size, and pass count, and persist only a prefixed public key.
  New `campaign prepare-discovery` and `campaign observe-discovery-page`
  commands create the reviewed campaign and record exactly one pass through the
  sole Runner boundary with the provider forbidden; the adapter is bound by the
  durable manifest kind, never by a caller argument, and no command accepts a
  page, URL, scope, or item selector. Because the campaign carries the ordinary
  worker policy and schema digests, a discovered campaign enters `campaign
  start` without a second manifest shape or dispatch path. Two reviewed
  adapters are registered as examples; unregistered kinds, unchanged sources,
  torn pass ledgers, and campaigns that already opened a batch or wrote a
  handoff fail closed. The fixed BOSS discovery module, its contract digests,
  and its retained on-device evidence are unchanged, and this generic path is
  offline verified only.
- **Composable scroll and drag input primitives.** The reviewed Windows MCP
  surface now exposes bounded `scroll` and `drag` actions through the same
  foreground guard, approval, side-effect budget, write-ahead, audit, grounding,
  and post-action invalidation path as existing actions. Both require
  screenshot-grounded coordinates; drag validates both endpoints. Worker
  scenarios can compose viewport navigation and canvas manipulation without a
  new dispatch site.
- **Automatic application-campaign terminalization.** A fresh generic
  application-campaign resume that finds no eligible items now completes the
  exhausted manifest, writes the deterministic terminal handoff, and retires
  the exact finalizer-owned heartbeat. Retirement fails closed unless every
  item is committed and the completed manifest, handoff, and heartbeat owner
  agree; repeating it after the heartbeat is absent is idempotent.
- **Composable application campaign workers.** New `campaign
  prepare-application`, `campaign start`, `campaign run-claimed`, and `campaign
  resume` commands run capability-composed scenario contracts through one
  manifest-routed runtime. The nineteen A1-A19 matrix cases are built-in
  examples, not the product boundary: callers can construct another validated
  `ApplicationWorkerSpec`, compose reviewed capabilities, and register it
  without changing the Runner or campaign runtime. Fifteen reviewed capabilities
  compose stable identity revalidation, observation ladders, navigation, text
  entry, mode recovery, challenge detection, post-action verification, and
  approval-bound external/critical commits without adding another MCP dispatch
  site. The Runner advertises only the composed reviewed tool subset. Provider
  output must return an exact bounded scenario/item/schema result, claim only
  observation tools actually executed, and pass digest-backed campaign commit
  and one-item fresh-context handoff. Unsupported kinds, tools, effects, result
  fields, identities, and stop codes fail closed. Existing fixed BOSS commands
  remain compatible. This is offline contract/runtime coverage, not retained
  real-application acceptance for the built-in examples or new scenarios.
- **Opt-in progress lifecycle.** Ordinary `run`, `resume`, bounded
  observation-only `plan run`, and explicit read-only crash recovery can now
  drive the passive progress window from durable checkpoints on a dedicated
  Win32 UI thread. The feature defaults off, remains read-only, survives human
  takeover, closes on E-stop/final cleanup, and fails silently without
  affecting the run. The three fixed MCP-backed campaign execution commands
  also own the same poller for their bounded process lifetime; zero-port
  prepare/start/resume commands remain window-free. One provider-free bounded
  plan, one persisted read-only recovery observation, and the fixed synthetic
  campaign command have retained native lifecycle evidence.
- **Bounded-plan presence lifecycle.** The opt-in passive presence halo now
  follows durable phases for bounded observation-only `plan run` sessions as
  well as ordinary `run`/`resume`. It shares the Executor's fail-silent
  lifecycle, receives immediate E-stop/human-yield teardown, and cannot affect
  plan success or desktop authority. One provider-free bounded plan has
  retained native halo lifecycle evidence.
- **Read-only recovery presence lifecycle.** Explicit `recover
  --execute-read-only` now projects only validated persisted phases through the
  same opt-in halo. Recovery CAS writes notify presence and progress together;
  `ABORTED`/`HUMAN_ACTIVE` close the halo before another recovery step, and
  independent teardown remains fail-silent.
- **Fixed-campaign presence lifecycle.** The three fixed MCP-backed campaign
  execution commands now project their durable run phases through the same
  opt-in fail-silent halo. MCP E-stop or human activity closes presence at the
  authoritative tool boundary, while zero-port prepare/start/resume commands
  remain window-free.
- **Responsive native Decision Card.** Replaced the topmost Task Dialog with a
  compact, configurable-corner normal Windows window that can be dragged,
  resized, minimized, maximized, and covered by other applications. Decision
  and digest-only evidence panes scroll independently, buttons reflow for
  narrow widths, and close/timeout semantics still deny before dispatch.
- **Honest progress telemetry.** Backward-compatible run checkpoints now retain
  the run creation time, count model turns with complete provider usage, and
  distinguish successful screenshots from other image-bearing tool results.
  The passive progress view reports elapsed time and exact screenshots only
  when those facts are present; legacy checkpoints remain explicitly unknown.
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

[Unreleased]: https://github.com/kuoforever/guarded-desktop-agent/compare/main...HEAD
