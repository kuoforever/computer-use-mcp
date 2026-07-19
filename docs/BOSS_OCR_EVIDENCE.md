# Bounded BOSS OCR evidence

> **Status: bounded on-device interested-jobs observation retained
> 2026-07-19.** This record demonstrates the Windows OCR vertical slice on a
> real BOSS page through the project's stdio MCP boundary. It is not provider,
> campaign, 100-item application-acceptance, or release evidence.

## Reviewed boundary

- Source commit: `75a3a4a64490c237bb982c97a0cbc074f0566f39`.
- Surface: project-local `computer-use-mcp.exe` launched through
  `StdioDesktopMCP` from the checked-out virtual environment.
- Mode: `safe_local`, `chrome.exe` allowlisted, dangerous confirmation enabled,
  and the 2.5-second human-idle gate retained.
- Scope: one existing signed-in Chrome window, BOSS home, the account's
  recommendation page, and one read-only interested-jobs page.
- Excluded: provider calls, screenshots, messages, applications, uploads,
  collection changes, challenge bypass, and retention of recruiter names,
  personal collection counts, or URL security tokens.

The stdio handshake exposed exactly the reviewed nine tools:
`activate_window`, `click`, `find`, `key`, `list_windows`, `ocr`, `screenshot`,
`type`, and `ui_snapshot`.

## Navigation and safety result

The first resumed activation returned `HUMAN_ACTIVE`; the run stopped without
lowering or disabling the idle threshold. After the operator explicitly
resumed while idle, the bridge re-listed windows, activated the fresh Chrome
window ID, resolved a fresh address-bar ref, and navigated to the BOSS home
page. The home snapshot contained 120 lines and 10,498 serialized characters.

The page exposed `/web/geek/recommend`, but `find("感兴趣")` returned no
interactive element. On that account page, UIA exposed job cards and links but
still omitted the static status-tab labels. No login, challenge, rate-limit, or
site-blocked state appeared.

## OCR result

An OCR call over the explicit main-content region
`(381,260,1326,600)` used 795,600 pixels and completed in 0.236 seconds. It
returned the `zh-Hans-CN` language hint, image digest
`53b9d3290a9551756ef6f971125b9b17628b4b5a1cf2f2704b25916057fecc33`,
and screen-relative boxes for the otherwise absent `感兴趣` label. The broad
result reached the 100-run limit, reported 28 omitted runs, and explicitly set
`complete=false` and `truncated=true`.

A 200-by-100 crop was too narrow and recognized only the adjacent count. The
runtime did not click from that incomplete target check. Expanding the fresh
verification crop to `(381,500,600,100)` returned a complete ten-run row:
`沟通过`, `已投递`, and `感兴趣`, plus their adjacent counts. A same-session
verification located `感兴趣` at screen x `785..852`, y `536..558`; only then
did the read-only navigation click its center.

The resulting address was the BOSS interested-jobs route with
`tab=4`, `sub=1`, `page=1`, and `tag=4`. The post-navigation UIA snapshot
contained 92 lines and 7,493 characters. Job and company links carried the
`personal_interest_brand` marker, confirming that the result was not the
general recommendation list.

## Source and cost comparison

For the first visible interested-job card:

- `find` returned the card plus its stable public job-detail URL and structured
  role, location, compensation, experience, and education text;
- OCR over `(381,650,1326,230)` used 304,980 pixels, completed in 0.204
  seconds, returned 56 runs, omitted zero runs, and set `complete=true`;
- the OCR image digest was
  `835bab2ff5b812700e18528097a6caaf7299a7b96bb4aaac7cbd001ba86fc98c`;
- OCR and UIA agreed on the visible role family, city/district, compensation,
  experience, education, and company text, with expected OCR punctuation and
  Latin-letter errors.

The evidence supports the intended ladder: use UIA when it is complete, use a
bounded OCR region for missing static labels, and return to structured UIA for
stable job identities after navigation. It also shows that crop context matters
and that a broad OCR result can truncate even when its pixel bound is safe.

## Supported claim and next gate

This closes the single BOSS static-content OCR gate and retains the separate
interested-jobs result requested after the home-page evidence. It fills only a
partial real-application observation cell. It does not demonstrate five
batches, two provider contexts, restart recovery, 100 committed identities, or
campaign acceptance.

An internal fixed runtime now validates and records durable public BOSS job keys
from one bounded complete foreground `ui_snapshot` through Runner/project MCP
while dropping URL query data. It is offline fake-MCP verified and adds no live
application evidence. A separate
[one-page campaign discovery result](BOSS_CAMPAIGN_DISCOVERY_EVIDENCE.md) now
closes the next fixed-runtime gate. Reviewed page progression and the bounded
multi-item read-only BOSS campaign with restart evidence remain. Google Docs
and WeChat remain later Wave 1
cases; action authority is unchanged.
