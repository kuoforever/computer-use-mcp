# Bounded BOSS semantic extraction contract

> **Status: implemented and offline verified contract only.** The strict result
> schema and deterministic observation-ladder reducer are implemented. They are
> not connected to the BOSS item runtime, do not call a provider or MCP, and
> have no automatic navigation or application evidence.

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

## Remaining gate

The current `run-claimed-boss` command intentionally keeps its retained
one-snapshot/one-tool-call identity contract. The next implementation must
review a new item-worker budget and connect this pure contract through the sole
Runner dispatch boundary, while re-establishing the claimed identity before
extraction. Only then should an on-device semantic item result and the 100-item
evaluation be attempted.
