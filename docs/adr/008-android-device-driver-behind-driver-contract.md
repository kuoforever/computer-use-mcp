# ADR-008: An Android device is a driver behind the contract, not a second MCP

Status: Proposed
Date: 2026-07-22

> **Terminology note (2026-08-12):** this dated proposal uses “Wave 1” for the
> BOSS/WeChat evaluation batch. Current planning calls those cases Application
> Coverage Set A; the label is not the Formal Demo v1 story or project priority.
> The decision text below remains unchanged as a dated design record.

## Context

Some target applications — recruiter chat on BOSS, WeChat, and similar
mobile-first products — are only reachable, or are materially better, on a real
Android device rather than on the Windows desktop. A requirements draft proposed
reaching them by mirroring the phone to Windows with scrcpy and driving it with
the existing computer-use paths.

Two acquisition shapes exist:

- **scrcpy-as-window.** The phone is mirrored into an ordinary Windows window.
  The current Windows driver can already screenshot it and land coordinate
  clicks inside it, because scrcpy forwards mouse and keyboard to the device.
- **ADB transport.** Input, capture, and the accessibility tree come from the
  device directly over ADB (`input tap` / `swipe`, `exec-out screencap`,
  `uiautomator dump`), with scrcpy reduced to a human-facing viewer.

The draft also proposed a parallel tool surface — `android.*`, `scrcpy.*`,
`computer.*`, and a `recruitment.*` business layer — roughly forty tools.

## Decision drivers

- The [Driver Contract](../DRIVER_CONTRACT.md) already exists precisely to keep
  platform-native code out of the core; macOS and Linux are recorded as future
  drivers behind it. A device target is the same seam, not a new subsystem.
- A parallel `android.*` / `computer.*` surface would give the model two ways to
  click, with two coordinate spaces, and no single place that owns grounding,
  approval, or the owner-chain gate. That contradicts
  [ADR-004](004-mcp-server-is-sole-desktop-authority.md).
- The governance invariants must be *fed*, not bypassed: no auto-replay of an
  uncertain dispatch ([ADR-001](001-uncertain-dispatch-is-never-auto-replayed.md)),
  a fresh owner-chain check before every side effect, mandatory post-action
  observation, and human approval before a message is sent. The device's
  foreground package is the owner-chain analogue.
- Sequencing matters. The project's discipline is depth before breadth: prove
  the Windows vertical to application-verified before spreading the same effort
  across a second platform.

## Considered options

### 1. A parallel Android / scrcpy / recruitment MCP surface

*Rejected.* Duplicates click/type/screenshot across `android.*`, `computer.*`,
and `scrcpy.*`; leaks recruitment-specific logic into the tool layer; and
splits authority the way ADR-004 exists to prevent. The requirements draft's
own principle — the business layer should compose lower primitives, not own
them — argues against it.

### 2. scrcpy-as-window through the existing Windows driver, unchanged

*Rejected as a product path, retained as a stopgap.* It works today for
screenshot, coordinate tap, region OCR, and window activation, because scrcpy is
an ordinary window. But scrcpy is an **opaque video surface**: Windows UIA sees
no controls inside it, so `ui_snapshot` / `find` / `get_tree` / `document_text`
collapse to OCR and vision only. There is also **no swipe primitive** in the
contract — `click` is a same-point press/release — so scrolling a mobile list is
impossible, and text injection of Chinese through `SendKeys` is unreliable. This
is a demo, not a usable path.

### 3. An `AndroidDriver` behind the Driver Contract, ADB as transport

*Chosen (as direction).* One new driver implements the existing contract:
`capture_screen` via screencap or the scrcpy video frame, `get_tree` / `find`
via `uiautomator dump` mapped into `Node`, `click` / `type` / `key` via `input`,
OCR as the same bounded fallback the Windows path already uses. scrcpy stays a
viewer; ADB is the authority. The device's own resolution is the native
coordinate space, which removes the title-bar / letterbox / DPI reprojection
that a window-scraping approach would need.

## Decision

**A phone or emulator is reached by adding one `AndroidDriver` behind Driver
Contract v1.x, not by adding a parallel tool surface.** The model-facing tools
and the `ref_N` / shared-pixel-grid model are unchanged. Recruitment reply
drafting, job structuring, and stop-word risk judgement stay in the Agent /
skill layer, alongside the existing `boss_campaign_*` control logic; the driver
only observes and acts on the device.

The work is **deferred until the Windows vertical is application-verified.** It
is a breadth move, and opening it before the depth-first baseline is proven
would relitigate the project's sequencing. It is recorded as a direction, not a
current capability.

Two contract-level items are prerequisites and are tracked as a **v1.1** minor
change (backward compatible, additive):

1. A `swipe` / `long_press` primitive, absent from v1.0. This is a real contract
   change and affects every driver, so it is versioned, not smuggled in.
2. A deliberate answer for the device coordinate domain. The contract today
   treats the primary display as the only supported coordinate space
   ([Driver Contract](../DRIVER_CONTRACT.md) "Coordinate semantics"). A device
   is a *second* domain; this must be an explicit decision, because silently
   extending the coordinate model is exactly what the Windows notes warn
   against.

## Consequences

- The accessibility-first, pixels-fallback model is preserved in spirit but the
  Android structured source is UIAutomator, a different tree reached over ADB —
  mapping it into `Node` is genuine driver work, not a config flag.
- A device over ADB is literally "a second machine with independent input and
  capture authority," which is the answer
  [ADR-007](007-one-active-lease-per-foreground-desktop.md) and the roadmap's
  isolated-worker goal already point to. A phone/emulator worker advances that
  goal rather than competing with it.
- The Wave 1 targets (BOSS, WeChat) are mobile-first; this gives an alternative
  acquisition path to applications already prioritized, not a new application
  wave.
- Cost: a second driver widens the surface that every governance and reliability
  claim must cover. Until the Windows path is application-verified, Android
  remains `Planned` in [Capability status](../CAPABILITY_STATUS.md) and earns no
  runtime claim.
- Note the vocabulary split: the roadmap's existing "mobile" work is a
  *notification sink* (the operator is notified on their phone). Driving a phone
  is a distinct, previously unplanned scope; this ADR records it, it does not
  merge the two.

Related: [ADR-004](004-mcp-server-is-sole-desktop-authority.md),
[ADR-007](007-one-active-lease-per-foreground-desktop.md),
[Driver Contract](../DRIVER_CONTRACT.md), [Roadmap](../EXECUTION_PLAN.md).
