# Token efficiency contract

> **Status: planned optimization contract.** Correctness and resumability are
> prerequisites. Token reduction must not hide uncertainty or remove the
> observation needed to verify an action.

## Objective

Day-scale tasks must keep provider context proportional to the current work
item, not to all previous screenshots and pages. Provider-reported usage is the
measurement source; serialized bytes are useful diagnostics but are not token
counts.

## Observation ladder

Use the cheapest source that can answer the next decision:

1. Cached stable identity or prior item metadata.
2. `find()` for a known interactive target.
3. Scoped or delta UIA snapshot.
4. Bounded document-text extraction.
5. OCR over a small region.
6. Cropped screenshot.
7. Full-window or full-display screenshot only when necessary.

Do not request UIA, OCR, and a screenshot together by default. Escalate when a
cheaper source is incomplete or when visual verification is itself the goal.

## Observation envelope

Every model-visible observation should carry compact control metadata:

~~~json
{
  "observation_id": "obs_...",
  "source": "uia",
  "scope": "window:123",
  "epoch": 8,
  "complete": false,
  "truncated": 14,
  "content_digest": "...",
  "payload": "bounded source-specific content"
}
~~~

Unchanged observations should be referenced by ID and digest instead of being
resent in full when the provider continuation mechanism permits it.

## Screenshot policy

- Prefer window or region capture to a primary-display image.
- Never serialize base64 into model-visible text.
- Send image content through the provider's native image field.
- Cache image bytes locally by digest for the duration of the campaign.
- Record dimensions, crop origin, coordinate space, and digest separately.
- After an action, capture only the region needed to verify the expected effect
  unless window identity or layout may have changed.

The current MCP screenshot has no region parameter, so region capture is a
planned contract and implementation change.

## Delta observations

For stable windows, retain a local prior scene and compute:

- window identity and bounds changes;
- added, removed, or changed UIA nodes;
- changed OCR text regions;
- changed image tiles or bounding regions.

The provider receives a bounded delta plus enough surrounding context to
interpret it. If the delta is ambiguous, truncated, or crosses a window/layout
change, send a fresh scoped snapshot instead.

## Item-local provider context

For campaign work, the prompt should contain only:

- fixed campaign objective and schema;
- current item identity and ordinal;
- compact recent action/observation group;
- current budgets;
- fixed recovery state;
- bounded aggregate facts needed for classification.

Do not append all prior job descriptions or screenshots. Committed item output
belongs in the campaign artifact and is retrieved only when needed for final
aggregation.

## Local extraction before model use

Deterministic local code should handle:

- deduplication by stable item key;
- normalization of salary, location, company, and date fields;
- bounding and hashing observations;
- exact text search;
- schema validation;
- aggregation counts and progress metrics.

Use a model for semantic classification or ambiguous visual interpretation,
not for repeatedly parsing identical navigation chrome.

## Batch summaries

Every N committed items, produce a typed aggregate rather than free-form model
prose:

~~~json
{
  "summary_version": 1,
  "items": 10,
  "field_coverage": {"salary": 10, "location": 10},
  "classification_counts": {"strong_match": 3, "review": 5, "weak": 2},
  "output_digest": "..."
}
~~~

Final reporting reads committed structured results and summaries. It should not
require replaying the full browsing context.

## Token budgets

Track per run, batch, item, source, and successful commit:

- provider input/output tokens;
- model calls;
- tool calls;
- UIA characters/nodes;
- OCR characters/regions;
- image count and pixel area;
- retries and failed observations.

Useful derived measures:

~~~text
tokens_per_committed_item
tokens_per_successful_classification
image_pixels_per_committed_item
tool_calls_per_committed_item
retry_tokens / total_tokens
~~~

A missing provider usage report must remain unknown. Checkpoint v1 currently
collapses missing usage to zero; a future checkpoint revision should add a
usage-report count or explicit coverage flag.

## Context rotation policy

Rotate to a fresh provider context when the first limit is reached:

- configured safe context fraction;
- item-count batch boundary;
- wall-clock batch boundary;
- large screenshot or OCR escalation;
- application or account state reset;
- repeated recovery that makes the current context noisy.

Before rotation, commit the current item or mark it nonterminal, write the
campaign handoff, and verify that a fresh session can reconstruct the next
operation without conversational history.

## Initial optimization experiments

1. Compare full `ui_snapshot` with `find` on known BOSS controls.
2. Add a bounded OCR region and compare it with full screenshots for one job
   card and one detail panel.
3. Measure full `screenshot` versus `capture_region` crop token usage through
   both providers.
4. Process 20 items with no context rotation, then 5 x 4-item batches, and
   compare tokens per committed item.
5. Prototype UIA deltas and stop if their ambiguity increases retries enough to
   erase token savings.

## Non-goals

- Saving tokens by omitting post-action verification.
- Compressing uncertain calls into prose that cannot be replay-audited.
- Treating PNG base64 character length as provider token usage.
- Keeping a single provider conversation alive for an entire day when durable
  item state can replace that context.
