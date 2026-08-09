# Bounded BOSS semantic extraction contract

> **Status: implemented and offline verified bounded runtime.** The strict
> result schema, deterministic observation-ladder reducer, one-item runtime,
> fixed CLI seam, and successful fresh-run transfer are implemented. There is
> no on-device semantic result, automatic navigation, or application evidence.

## Boundary

`computer_use_agent.boss_semantic_extraction` defines the next BOSS worker
boundary without widening desktop authority:

- one exact `boss:job:<public_id>` item key;
- required bounded company, role, and location strings;
- optional bounded compensation and experience strings;
- one fixed classification plus one to five fixed reason codes;
- a required digest binding classification to a separately reviewed policy;
- one reviewed sufficient observation source and its content digest; and
- an exact schema version included in the canonical result digest.

Every text field is at most 160 characters. Control characters, leading or
trailing whitespace, extra fields, arbitrary model prose, raw descriptions,
URLs, UI references, screenshots, and image bytes are outside the result
contract. The classification labels have no meaning without the supplied
classification-policy digest; this module does not select or authorize that
policy.

The strict JSON schema is returned as a fresh JSON object and has a stable
SHA-256 contract digest. Parsing independently revalidates the exact shape,
enums, bounds, item key, reason consistency, policy digest, and source digest.
The committed content digest covers the canonical validated payload.

## Observation ladder

The pure reducer permits exactly this order:

1. UIA snapshot;
2. bounded document text;
3. bounded OCR;
4. cropped image;
5. full screenshot for final layout/orientation recovery.

The next rung is available only after the preceding attempt explicitly reports
`INCOMPLETE` with a fixed reason. The reducer rejects retries, skipped rungs,
and any continuation after a sufficient or terminal result. `AUTH_REQUIRED`,
`CHALLENGE_REQUIRED`, `RATE_LIMITED`, `SITE_BLOCKED`, and
`CONTENT_UNAVAILABLE` produce a durable-handoff decision rather than another
equivalent observation. Exhausting all five rungs also hands off.

H6 registers this unchanged reducer as
`boss.per_item_observation_ladder` version 1. The semantic runtime resolves the
exact ID/version/digest pin, derives the same tool and argument binding from the
reviewed template, and rejects registry or reducer drift. There is no
latest-version fallback, dynamic template selection, or additional dispatch
surface.

An observation attempt retains only its source, fixed status/reason, and a
content digest. It does not retain the observed text or pixels.

## Offline verification

The focused test matrix proves:

- exact-shape parsing, canonical round trip, and stable digest;
- rejection of extra fields, oversized/control-character text, unknown enums,
  and inconsistent insufficient-evidence reasons;
- serializable fresh JSON schema exports and a stable schema digest;
- exact ordered escalation from UIA through screenshot;
- immediate extraction after sufficient evidence;
- fixed handoff for challenge and ladder exhaustion; and
- refusal of skips, retries, continuation after terminal state, or malformed
  incomplete reasons.

## Runtime connection

Three fixed commands preserve the no-selector campaign boundary:

- `start-boss-semantic-batch` opens one one-item batch with at most five
  provider turns, five tool-call attempts, two image observations, one OCR
  region, one consecutive failure, and zero side effects;
- `run-claimed-boss-semantic` re-establishes the exact durable public identity
  with a Runner-dispatched foreground UIA snapshot, exposes only the exact next
  reviewed observation tool, accepts only strict assessment/result JSON, and
  commits only a locally revalidated canonical result; and
- `resume-boss-semantic-batch` reconstructs one successful semantic batch,
  transfers heartbeat ownership to a fresh zero-port run, and claims the exact
  next coordinator-selected item.

The semantic run command requires `read_only` mode,
`max_side_effects = 0`, and configured Host budgets of at least five model
turns and five tool calls. A looser or action-capable configuration fails
before provider/MCP work.

The initial classification policy is intentionally fixed: without a reviewed
user job preference, the only permitted classification and reason are
`INSUFFICIENT_EVIDENCE`. The exact policy digest is bound into every result.
This proves semantic field extraction without inventing a recommendation.

UIA and bounded document text remain connected through the sole Runner dispatch
boundary. The pinned template records but does not satisfy safety baselines.
OCR remains marked by the Agent Host as requiring a separately
approved safety baseline. If document text is incomplete and the provider
requests OCR, Runner records `POLICY_DENIED`, performs no OCR MCP dispatch, and
the semantic runtime writes a retryable `CONTENT_UNAVAILABLE` failure-limit
handoff. It does not bypass the baseline to reach crop or screenshot.

The CLI prints only fixed control metadata, source, counts, and digests; it
does not print company, role, location, compensation, or experience.

## Remaining gate

The current `run-claimed-boss` command intentionally keeps its retained
one-snapshot/one-tool-call identity contract; the new semantic commands are a
separate policy and do not alter that evidence path. Next retain one on-device
UIA or document-text semantic item with a reviewed provider. Pixel escalation
requires a separate Host safety-baseline review. Only after those gates should
the 100-item evaluation be attempted.
