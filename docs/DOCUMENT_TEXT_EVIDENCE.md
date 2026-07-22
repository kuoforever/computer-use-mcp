# Bounded document-text evidence

> **Status: RETAINED on-device result, 2026-07-22.** This record preserves the
> first bounded `document_text` result through the project stdio MCP boundary.
> The probe retained only structural counts, timing, and a content digest; it
> did not persist the returned page text.
>
> When retained, this record demonstrates the Windows UIA semantic-text vertical
> slice on a real window through the project's stdio MCP boundary. It is not
> provider, campaign, 100-item application-acceptance, or release evidence.

## Reviewed boundary

- Source commit: `13a02c897c294b12a97df25e0eaca6be38f5ffdb`.
- Surface: project-local `computer-use-mcp.exe` launched through
  `StdioDesktopMCP` from the checked-out virtual environment.
- Mode: `safe_local`, target process allowlisted, dangerous confirmation
  enabled, and the 2.5-second human-idle gate retained.
- Scope: one existing, already-open UIA-rich window, read-only. `document_text`
  is `scope="foreground"` only, so the target must be foreground at call time.
- Excluded: provider calls, screenshots, messages, applications, uploads, any
  write/click that changes state, challenge bypass, and retention of any
  personal names, private counts, or URL security tokens surfaced in the blocks.

The stdio handshake must expose exactly the reviewed eleven tools:
`activate_window`, `capture_region`, `click`, `document_text`, `find`, `key`,
`list_windows`, `ocr`, `screenshot`, `type`, and `ui_snapshot`. Record the
actual handshake list here to prove the current binary was exercised:

~~~text
activate_window
capture_region
click
document_text
find
key
list_windows
ocr
screenshot
type
ui_snapshot
~~~

## Target selection

Pick a window that exposes a real UIA `TextPattern` semantic channel so the
result is not just a re-serialized `ui_snapshot`. Good candidates:

- a signed-in Chrome page (BOSS interested-jobs, or any article),
- a text editor / Word / VS Code document pane.

Chosen window: `ChatGPT.exe`, title `ChatGPT`, HWND `722328`. It was already the
foreground window; the probe did not call `activate_window` or any other action.

A backend with no semantic text channel is expected to **fail closed**. If the
first target fails closed, record that refusal and pick another — a fail-closed
result on a text-less surface is itself a valid observation, but the primary
gate needs at least one populated result.

## document_text result

Call `document_text` with `scope="foreground"` on the activated window and
record the returned envelope fields:

| Field | Expected | Observed |
| --- | --- | --- |
| `semantic_source` | `uia_text_pattern` | `uia_text_pattern` |
| `coordinate_space` | `primary_display_physical_pixels` | `primary_display_physical_pixels` |
| block count (`blocks`) | 1..200 | 1 |
| total chars kept | <= 20,000 | 10,189 |
| `content_digest` | sha256 over kept text, `\n`-joined | `769304afa28f85399188d5524479a7c1d5ffdac9c921221ca05f8c6d034dd430` |
| `complete` | true when nothing omitted | `true` |
| `truncated` | false unless a cap was hit | `false` |
| `omitted_blocks` | 0 unless a cap was hit | 0 |

Wall-clock latency for `document_text` was 17.2 ms. The returned block was
reviewed only for the bounded metadata above and was not retained. No password
subtree text appeared; the driver excludes `IsPassword` controls before block
construction.

## Semantic-channel comparison

Prove `document_text` is the intended ladder rung — the semantic-text channel,
distinct from both `ui_snapshot` (interactive element dump) and `ocr` (pixels).
For one visible region of the same window, record:

- `ui_snapshot` returned 68 structured lines / 3,810 characters of interactive
  roles, names, geometry, and refs in 228.4 ms;
- `document_text` returned one ordered 10,189-character semantic block in
  17.2 ms;
- the two shapes are observably distinct: the snapshot is an interactive-node
  projection, while `document_text` is a single ordered `TextPattern` range.
  The probe retained no prose from either result.

No OCR cross-check was run because it would require a screenshot-like pixel
observation and was not necessary to close this semantic-channel gate.

## Truncation path (optional but preferred)

To exercise the bound accounting, use a target whose text exceeds a cap
(> 200 blocks or > 20,000 chars) and record that the envelope set
`truncated=true`, reported a nonzero `omitted_blocks`, and that the
`content_digest` covers **only the kept text**, so a truncated payload cannot
masquerade as the whole document. This optional on-device path was not run;
the cap and digest accounting remain covered by the offline unit suite.

## Supported claim and next gate

When filled, this closes the single on-device `document_text` gate and promotes
that source from offline-only to on-device in [Capability status](CAPABILITY_STATUS.md).
It fills only a partial real-application observation cell. It does not
demonstrate five batches, two provider contexts, restart recovery, 100
committed identities, or campaign acceptance.

Remaining after this gate (unchanged): a bounded multi-item read-only BOSS
campaign with restart evidence, per the MCP Server row's next gate. Android and
a `swipe`/`long_press` primitive stay deferred behind
[ADR-008](adr/008-android-device-driver-behind-driver-contract.md) until the
Windows vertical is application-verified.

Related: [Capability status](CAPABILITY_STATUS.md), [Tools](TOOLS.md),
[Observation contract](OBSERVATION_CONTRACT.md),
[BOSS OCR evidence](BOSS_OCR_EVIDENCE.md).
