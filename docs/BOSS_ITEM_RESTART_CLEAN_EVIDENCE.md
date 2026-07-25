# Bounded BOSS clean item/restart evidence

> **Status: clean bounded on-device sequence retained 2026-07-25.**
> This record proves three consecutive identity-only commits across fresh runs
> on the fixed code without local state correction. It is not semantic job
> extraction, provider rotation, automatic navigation, a 100-item result, or
> complete BOSS application acceptance.

## Boundary

- Surface: the project-local Agent CLI, `StdioDesktopMCP`, and one existing
  signed-in BOSS interested-jobs view in Chrome.
- Reviewed configuration SHA-256:
  `8340F4B1CA1E5B4F35A5AB0E87C041C878704652494164C542EBB08188DEC43E`.
  It allowed only `chrome.exe`, used `safe_local` and `read_only`, limited each
  fixed campaign run to one tool call, and allowed zero side effects.
- Campaign: `boss_live_20260725_clean`.
- Operator-controlled navigation stayed outside the fixed campaign commands.
  It used the project MCP to activate the unique Chrome window, navigate to the
  already observed interested-jobs route, and send one `End` key between
  discovery passes. No browser plugin supplied campaign data or execution.
- The fixed commands accepted no item, URL, page, scope, batch, campaign kind,
  provider, or semantic-extraction selector.

The first fixed discovery attempt observed the wrong foreground and failed
closed with `BOSS_DISCOVERY_NO_IDENTITIES`. It wrote no discovery pass or item
identity. The accepted sequence then co-located project-MCP foreground
activation and the fixed command in one local orchestration process so the
operator host could not reclaim foreground between them. No campaign file was
edited or corrected.

## Result

Two accepted discovery passes retained eight and four new stable identities,
for twelve total. Their distinct source digests were:

- `54d43cea812a5e4e6d8e2b428a1075e4d0814adfab0165e75dc6e4ebbab1e88c`;
- `131735eae6aa8177ef3856734dece4582d5140f5774ff3b0ddce890def712c24`.

The coordinator then completed three exact claimed identities:

| Run | Result | Usage |
| --- | --- | --- |
| `boss_clean_item_1` | ordinal 1 committed; handoff to ordinal 2 | 1 tool call, 0 provider turns, 0 tokens |
| `boss_clean_item_2` | fresh-run transfer; ordinal 2 committed; handoff to ordinal 3 | 1 tool call, 0 provider turns, 0 tokens |
| `boss_clean_item_3` | fresh-run transfer; ordinal 3 committed; handoff to ordinal 4 | 1 tool call, 0 provider turns, 0 tokens |

Every item run stopped at `TOOL_CALL_LIMIT`. Durable state contains twelve
`DISCOVERED`, three matching `CLAIMED`, `OBSERVED`, `EXTRACTED`, and
`COMMITTED` transitions, plus three `STARTED` and three matching `FINISHED`
batch transitions. Final handoff reports:

- `completed_count = 3`;
- `next_item_ordinal = 4`;
- `next_action = "resume_batch"`;
- `retryable_count = 0`;
- `uncertain_count = 0`.

All five accepted discovery and item run checkpoints ended in `SUCCESS`, used
one tool call each, and used zero model calls and zero input/output tokens.

## Artifact integrity and privacy

Sanitized SHA-256 values:

- item ledger:
  `E14A6542626FB75151646340922E134744BC0626EADF15D76083867969FA6CC6`;
- discovery ledger:
  `8C1BD6C9EA49CAA4C448E4CB86B172A4684A488ECA9AAD2B09755AE724DA3E6B`;
- batch ledger:
  `DCD455FCF5628A6D99AA10E72295486E4307B0A5612C5937F4FA9C45F7B199E4`;
- handoff:
  `11C41FBFAC3E11D2D6E1DDEDA9F66BA5EE9F4FE1B95F2B04D6DEDEF2E28EE2FE`;
- heartbeat:
  `4C2C3C7DCA5EC832E6FB0B3D4C397EA7CFF33B9BEF72144A44367E9C161CFDBB`;
- manifest:
  `B2162407241BB01F1EA9062BFF26F9FA3EE61115978FF564C0C2DCBD2E774101`.

The complete campaign directory and the five accepted redacted traces contained
zero matches for full HTTPS URLs, `securityId`,
`personal_interest_brand_`, or `personal_added_brand_`. The traces also
contained zero `boss:job:` keys.

## Supported claim and next gate

This closes the fixed-code, no-local-correction bounded multi-item restart gate
for public identity presence. It replaces the prior diagnostic as the current
positive evidence while preserving that diagnostic's defect history.

The next implementation gate is a separately reviewed bounded semantic
extraction schema and observation ladder. Only after that boundary is offline
verified should the project run the 100-item read-only evaluation with provider
context rotation, forced restart, retry, recovery, takeover, token, and cost
measurements. A general campaign worker remains unconnected.
