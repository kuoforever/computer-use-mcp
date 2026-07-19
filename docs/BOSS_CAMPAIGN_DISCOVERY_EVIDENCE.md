# Bounded BOSS campaign discovery evidence

> **Status: one on-device page retained 2026-07-19.** This record demonstrates
> the fixed BOSS campaign preparation and one-page observation commands through
> the Agent Runner and project stdio MCP. It is not page-progression, provider,
> item-processing, restart, 100-item, or application-acceptance evidence.

## Reviewed boundary

- Surface: project-local `computer-use-agent.exe` launching the project
  `computer-use-mcp.exe` through `StdioDesktopMCP`.
- Target: one existing signed-in Chrome window with the BOSS interested-jobs
  page already in the foreground.
- Authority: one fixed `ui_snapshot({"scope":"foreground"})`; no provider,
  navigation, task, URL, page, scope, or item selector and no side effect.
- Runtime base revision: `b96fa7ea7906444b3e76728dd25b77a41b35d3c5`,
  with the parser repair retained by the evidence change that includes this
  record.
- Runtime: Windows `10.0.26200.0`, Python `3.13.7`.
- Reviewed configuration SHA-256:
  `8340F4B1CA1E5B4F35A5AB0E87C041C878704652494164C542EBB08188DEC43E`.
  The user-local configuration contained no credential and allowed only
  `chrome.exe` in `safe_local` read-only mode.

## Fail-closed discovery and repair

The first run observed the wrong foreground surface after the operator returned
to Codex; it produced a 142-character snapshot and failed with
`BOSS_DISCOVERY_NO_IDENTITIES`. A fresh run against the intended foreground
page produced a 7,941-character snapshot but failed with the same fixed code
and made no campaign mutation.

A bounded in-memory shape probe through the same project MCP found two real UIA
contract differences without retaining page content or full URLs:

- Chrome exposed web links with the UIA role `hyperlink`, while the offline
  fixture accepted only `link`;
- the stable public job links carried only the job path and a discarded query
  field, while same-page BOSS company links carried
  `personal_interest_brand_<short-hex>` source markers.

The parser now accepts only the reviewed `link` or `hyperlink` roles, requires
at least one same-snapshot HTTPS link on `www.zhipin.com` with the exact source
marker or a bounded 6-32 digit hexadecimal suffix, and separately extracts only
same-snapshot `/job_detail/<public-id>.html` identities. Wrong host, malformed
marker suffix, injected text, incomplete output, excessive output, and drifted
campaign state remain fail-closed. The policy digest was advanced for this
semantic change.

## Retained successful result

The fixed preparation command created a fresh
`boss_saved_job_read_only` manifest. The fixed observation command then:

- dispatched exactly one successful `ui_snapshot`;
- made zero model/provider calls and zero side-effect calls;
- recorded 7 new stable public job keys, with 0 duplicates;
- reached `SUCCESS` in 2,823 ms, including 2,076 ms of MCP tool latency;
- used 0 input/output tokens and performed 0 retries.

The redacted trace SHA-256 is
`DD7E84CFEE22B5917B739785D3BFBC1DC0C7FD4871C3BAEFF046D28A68176B80`.
The seven-line item ledger SHA-256 is
`DCF035DCFE59BA03F2A543B911CE737FC6D8EA6BD3D1168348B74AB7D5D0F38F`.
Ledger review confirmed that it contains the fixed `boss:job:` key prefix but
does not contain HTTPS URLs, `securityId`, or the source marker. No screenshot,
raw UI text, full URL, query value, role/company content, provider payload, or
credential is retained in the repository.

## Supported claim and next gate

This closes only the one-page on-device BOSS campaign discovery gate. Next add
a separately reviewed, bounded page-progression mechanism and run the first
100-item read-only campaign with a forced restart and retained committed-item,
retry, recovery, takeover, and cost evidence. Do not infer general worker,
provider, extraction, item commit, or side-effect authority from this result.
