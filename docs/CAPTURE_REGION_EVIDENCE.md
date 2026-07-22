# Bounded region-capture evidence

> **Status: RETAINED on-device result, 2026-07-22.** This record preserves the
> first bounded `capture_region` result through the project stdio MCP boundary.
> The PNG was validated in memory and discarded; only its dimensions, encoded
> byte count, digest, timing, and grounding envelope are retained.

This result demonstrates one real primary-display crop over synthetic project
content. It is not provider, campaign, arbitrary-application, full-screen,
multi-monitor, or release evidence.

## Reviewed boundary

- Source commit: `b5b00407274c6e5a9e9979aaaec9fe7ca49dd8a1`.
- Surface: `scripts/smoke_capture_region.py`, using the checked-out virtual
  environment's `computer-use-mcp.exe` through `StdioDesktopMCP`.
- Target: the real non-activating `PassiveProgressWindow`, positioned at
  `(80, 80)` and drawn exclusively from fixed synthetic view models.
- Mode: `safe_local`, dangerous confirmation enabled, 2.5-second human-idle
  threshold retained, and no side-effecting MCP tool called.
- Privacy: the requested rectangle was exactly the synthetic window's Win32
  bounds. No current chat, application page, full screenshot, provider data,
  task text, or other desktop pixels were retained.

The stdio handshake exposed exactly the reviewed eleven tools:

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

## Result

The smoke read the fixture's physical-pixel rectangle with `GetWindowRect`,
called `capture_region(x=80, y=80, w=420, h=320)`, and compared the returned
envelope against the decoded PNG held by the Agent bridge.

| Field | Expected | Observed |
| --- | --- | --- |
| `source` | `image` | `image` |
| `scope.display` | `primary` | `primary` |
| `scope.region` | requested rectangle | `[80, 80, 420, 320]` |
| `coordinate_space` | `primary_display_physical_pixels` | `primary_display_physical_pixels` |
| PNG dimensions | requested width and height | 420 × 320 |
| `encoded_bytes` | exact returned PNG length | 3,447 |
| `image_digest` | SHA-256 of returned PNG | `339d9c858fa171ddb566a519fb5362e05f930ef1ad8784b9ddc5a86a9cdc313a` |
| `complete` | `true` | `true` |
| `truncated` | `false` | `false` |
| call latency | measured wall clock | 320.5 ms |

The bridge independently decoded and integrity-checked the PNG. The smoke then
verified its dimensions, byte length, and SHA-256 against the grounding
envelope before discarding the bytes.

## Non-activation and attribution

The synthetic window used `WS_EX_NOACTIVATE` and was shown and moved only with
the existing non-activating backend. The probe recorded `GetForegroundWindow`
and `GetLastInputInfo` around the complete draw/capture cycle. The foreground
remained `0x000b0598`, and no local-input change invalidated the result.

The retained output was:

~~~text
RESULT: PASS (region=80,80,420,320; png_bytes=3447; digest=339d9c858fa171ddb566a519fb5362e05f930ef1ad8784b9ddc5a86a9cdc313a; latency_ms=320.5; foreground=0xb0598; 11-tool handshake matched; PNG discarded)
~~~

## Supported claim and next gate

This closes the single on-device `capture_region` gate and promotes bounded
region image capture from offline-only to desktop-verified for this synthetic
slice in [Capability status](CAPABILITY_STATUS.md). It does not establish
arbitrary application content, multi-monitor coordinates, provider image
handling, campaign restart, or application acceptance.

The next observation gate is to exercise the implemented UIA, document-text,
OCR, and cropped-image ladder inside the bounded multi-item read-only BOSS
campaign and retain restart evidence. Delta observations remain unimplemented.

Related: [Capability status](CAPABILITY_STATUS.md), [Tool reference](TOOLS.md),
[Observation contract](OBSERVATION_CONTRACT.md), and
[Document-text evidence](DOCUMENT_TEXT_EVIDENCE.md).
