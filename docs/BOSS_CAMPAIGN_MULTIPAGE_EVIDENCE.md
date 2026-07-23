# Bounded BOSS multi-pass discovery evidence

> **Status: two distinct on-device discovery passes retained 2026-07-23.**
> This record demonstrates the current discovery-pass contract against one
> existing signed-in BOSS interested-jobs view. It is not item processing,
> provider execution, restart recovery, a 100-item result, or application
> acceptance.

## Reviewed boundary

- Surface: project-local `computer-use-agent.exe` launching the project
  `computer-use-mcp.exe` through `StdioDesktopMCP`.
- Runtime base revision:
  `fb72227e158453ecae6d1dc7b2fa7e6c3ce44ba7`.
- Runtime: Windows `10.0.26200.0`, Python `3.13.7`.
- Reviewed configuration SHA-256:
  `8340F4B1CA1E5B4F35A5AB0E87C041C878704652494164C542EBB08188DEC43E`.
  The user-local configuration contained no credential, allowed only
  `chrome.exe`, used `safe_local` and `read_only`, limited the campaign command
  to one tool call, and allowed zero side effects.
- Each retained discovery pass dispatched exactly one
  `ui_snapshot({"scope":"foreground"})` through Runner and the project MCP.
  The fixed command accepted no task, URL, page, scope, item selector, provider,
  or navigation authority.
- Page progression occurred outside the fixed campaign command through
  operator-controlled project MCP navigation. The project MCP activated the
  unique BOSS Chrome window, used bounded OCR to ground the interested-jobs tab,
  and sent one `End` key between the retained passes. These navigation calls
  are not campaign execution evidence and do not constitute a general worker.

An initial observation against the wrong BOSS city-recruitment surface failed
closed with `BOSS_DISCOVERY_NO_IDENTITIES` and left the item and discovery
ledgers empty. The operator then selected the interested-jobs view. A fresh UIA
snapshot showed `personal_interest_brand_*` source markers and no
`personal_added_brand_*` markers before the first retained pass.

## Retained result

| Pass | Snapshot text | Tool latency | Observed | New | Duplicate | Source digest |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 8,079 characters | 2,086 ms | 8 | 8 | 0 | `62886c352adae7c2417a89a2d9844e739abd916babef65c12e7976e724cb89fe` |
| 2 | 9,326 characters | 1,943 ms | 4 | 4 | 0 | `b23b6da34c4b096f100f0e9fe45b11dd826ff23f7802d5737a0581cc16ee4a07` |

The durable result contains twelve unique `boss:job:*` item records and two
ordered discovery-pass records with distinct source digests. Both passes used
zero provider calls, zero input/output tokens, and zero side-effect calls.

Sanitized artifact SHA-256 values:

- item ledger:
  `93256EB06B32336C7A40CF166FE96EA3C5EC2559E587A01950A9D9CFCB81E86B`;
- discovery-pass ledger:
  `327DC8BE5AA68EFCD248EFD9090B75846FA59F1E616CFC073170C864E5934A2A`;
- pass-1 redacted trace:
  `60C9EF52EF48D3C56DEEAEA7510A78B4F43696459047404827C2A8FDAB0FB51C`;
- pass-2 redacted trace:
  `9DA106C8AF897FAADB5B359F995F91AB850D36491E03B96AAFA3D76A9527F854`.

The campaign directory and both retained traces were checked for full URLs,
`securityId`, `personal_interest_brand_`, and `personal_added_brand_`; no
matches were retained. Every item-ledger line contains the fixed `boss:job:`
prefix. The traces retain only bounded call metadata, status, latency, and text
length, not job keys or page content.

## Supported claim and next gate

This closes the current-contract, two-pass on-device BOSS discovery gate. It
proves distinct-source accumulation and durable identity deduplication only.
It does not prove automatic page progression, extraction, commit, provider
context rotation, restart recovery, or a complete application workflow.

The next gate is the first 100-item read-only BOSS campaign across multiple
provider contexts with at least one forced restart and retained committed-item,
token, retry, recovery, takeover, and cost evidence. A general campaign worker
remains unconnected.
