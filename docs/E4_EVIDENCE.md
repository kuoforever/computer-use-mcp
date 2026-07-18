# Isolated Windows E4 evidence

> **Status: maintained sanitized E4 evidence.** This record contains no API
> credentials, task or model prose, UI text, screenshots, provider response
> identifiers, raw transport, or unredacted error bodies.

## Reviewed environment

| Field | Value |
| --- | --- |
| Review date | `2026-07-18` |
| Source base | `5dd96fde93a7ce2d0371928454b7f18663366479` plus the reviewed dirty activation and Claude-schema repair under test |
| Runtime | disposable `CUMCP E4` Windows 11 VM; Python `3.13.14`; package `0.1.0` |
| Isolation | fresh rebuilt `CUMCP E4-rebuilt.vmdk`; Notepad-only `safe_local` allowlist; `type` disabled |
| OpenAI model | `gpt-5.6-terra` |
| Claude model | `claude-haiku-4-5-20251001` |
| Operator | local repository owner |

The VM was disposable and contained no sensitive documents. Credentials were
provided only to the Agent parent process for each run; the fixed MCP child
environment excluded them. A temporary VMnet8-only proxy relay was used because
the host proxy listened only on loopback, and was not part of retained evidence.

## Windows activation regression

All five reviewed cases passed on the same Windows revision: already
foreground, cross-process Explorer-to-Notepad activation, minimized restore,
stale HWND fixed failure, and injected native-call failure with reverse cleanup.
The sanitized result SHA-256 is
`d6cbe66049139e2162ea2b9d9613852b2e2450d0d4a0a231ec3a295e14c5dc36`.

## Four-cell matrix

| Scenario | Config SHA-256 | Run ID | Trace SHA-256 | Result |
| --- | --- | --- | --- | --- |
| E4-OAI-RO | `e9ca14091afc80fb1be047a487c8f2d538accac63cc6659b6ed50468f9abd111` | `47089b464b11460180ab3f92a52c4b31` | `dfe6d2381a9d80fba0f17d94748a795e32de3700398b8f5b575a3e6c25b287b2` | `PASS` |
| E4-OAI-ACT | `e10682ae7c1ca875f268f5fc071a712be5604906703a8a426360c5f528c0e6f8` | `5b497132bf2548d3927b807366f126be` | `1bde46f5efef31b931f0fa1ae644f954736788449fd8b471108d1190d86cc6b6` | `PASS` |
| E4-ANT-RO | `bec8db842b854a046460704711e131f9003e212dc679a5a75eeaf2174ec6bb37` | `25697b4aa2c54836b305bc3e50332438` | `793e81b51d02e1c90ce4117e820ead27ca5dda6746d89a4f4f8d150e8f4d71d7` | `PASS` |
| E4-ANT-ACT | `a665d2f50f845b65cc8279f4600b64f6e728dd2eed6339a3efaec875a2849ce5` | `b9ad8946cd5546a1b77ad086cb7891f7` | `bb74cbc8e0b3b17392c8bfa63666fa6e323b1ed7aec6696e2a11d8aeaaab0474` | `PASS` |

Both read-only traces reached `SUCCESS` after one successful observation with
zero side effects and zero retries. Both action traces contain exactly one
digest-bound local approval, one `activate_window` dispatch, a later successful
observation, `SUCCESS`, one side effect, and zero automatic retries.

Claude action-mode request validation initially exposed that its API rejects
the strict `click` schema's `oneOf`/nested `anyOf` combination. The adapter now
advertises only the reviewed base click properties to Claude while the unchanged
strict Host `ToolSpec` remains authoritative before approval or dispatch. A
separate fail-closed attempt correctly ended as `VERIFICATION_REQUIRED` when
Claude omitted post-action observation; no action was replayed.

This record fills the bounded Agent Host E4 gate only. It does not establish
application acceptance, all-model compatibility, or release approval.
