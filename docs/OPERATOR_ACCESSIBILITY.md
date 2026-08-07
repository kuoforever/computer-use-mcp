# Operator accessibility

> **Status: implemented and offline verified on Windows; bounded native UIA
> smoke passed on 2026-08-07.** This contract covers the focus-taking Decision
> Card and the passive Progress and Presence surfaces. It does not claim a
> Narrator/NVDA auditory review, physical multi-monitor usability, application acceptance,
> provider or MCP execution, or release-candidate evidence.

## Trust boundary

Accessibility settings are presentation inputs only. They never create an
approval, control, retry, replay, provider, MCP, or desktop-dispatch port.
Decision Card remains the only interactive approval surface. Progress and
Presence remain passive and non-activating; their accessible names project only
fixed Host-owned status.

Windows settings are resolved once for a composed operator experience:

- `SPI_GETHIGHCONTRAST` selects the operator's system color palette;
- `UISettings.animations_enabled` disables optional motion when Windows
  animations are off;
- `UISettings.text_scale_factor` supplies the system text scale;
- configured `high_contrast` and `reduced_motion` values are force-on flags and
  are combined with, never used to negate, the Windows preferences;
- unavailable or invalid Windows APIs fail silently to the legacy 100%, normal
  palette, motion-enabled presentation without affecting Runner authority.

The runtime accepts the documented Windows text range and combines it with
display DPI. Font growth is bounded at 400%. Containers grow through 200%, then
rows and controls reflow using requested font height. This separates text scale
from window geometry and prevents fixed-slot overlap at large effective scales.

## Keyboard and semantic contract

The Decision Card uses native `STATIC`, read-only `EDIT`, and `BUTTON` controls
so the standard Windows UI Automation proxies expose Text, Edit, and Button
semantics. The details edit has the visible label `Decision details`; fixed
header lines, the details toggle, and all four choices have bounded accessible
names derived from Host-owned presentation text in the selected locale.

- Initial focus is the unique safe `option_deny` button, displayed as
  `Stop task` in English and `停止任务` in Simplified Chinese.
- `Tab` and `Shift+Tab` traverse the details toggle, optional labelled details
  edit, and all choices in native dialog order, including wraparound.
- Arrow keys and `Space` retain native button navigation and activation.
- `Enter` activates only an already focused known toggle or option. It never
  creates a default approval from the top-level window or details text.
- `Esc`, close, timeout, malformed state, and native failure deny without
  dispatch.

The visible countdown is also the accessibility event source. Name-change
events are bounded to the initial timeout and the 60, 30, 10, and 0 second
milestones instead of announcing every timer tick. Progress emits a top-level
name change only when its six trusted summary fields change. Presence emits one
fixed content-free phase name only when the phase changes. Neither passive
surface takes focus or exposes an action pattern.

## Contrast, motion, and scaling

Normal product tokens meet at least 4.5:1 for text and 3:1 for non-text
boundaries in deterministic contrast tests. Forced or detected High Contrast
uses `COLOR_WINDOW`, `COLOR_WINDOWTEXT`, `COLOR_HIGHLIGHT`,
`COLOR_HIGHLIGHTTEXT`, `COLOR_BTNFACE`, and `COLOR_BTNTEXT`; it does not infer a
dark/light palette or retain optional dimming. Otherwise the strict dark/light
theme contract selects the fixed product palette; the complete precedence is in
[Operator presentation personalization](OPERATOR_PERSONALIZATION.md). Reduced
motion disables Presence animation while preserving the fixed label, glyph, and
phase state.

Decision Card layout tests cover compact and expanded controls at 100%, 200%,
and 400% effective text scale, including non-overlap and safe choice placement.
Progress layout tests cover all 19 summary/checklist rows at 400% and require
strictly increasing, non-overlapping text bounds. Presence font and status-tab
geometry use the same resolved effective text scale.

## Evidence and limits

Deterministic coverage validates preference fallback/composition, palette
selection, contrast ratios, focus order, safe keyboard activation, bounded
announcement milestones, UIA name construction, passive no-activation
contracts, and 200%/400% layout arithmetic.

Run the bounded native probe from a normal interactive Windows desktop:

~~~powershell
python scripts/smoke_operator_accessibility.py
~~~

The 2026-08-07 probe exercised dark, light, and High-Contrast-over-light in
English and Simplified Chinese, then exercised live 200% and 400% text reflow.
It found the Decision Card header as UIA Text
controls, the labelled details pane as Edit, and all four choices as Button. It
observed initial safe-denial focus, traversed the complete Tab path, resolved
`option_deny` with `Enter`, and confirmed that Progress and Presence kept the
foreground unchanged while exposing bounded top-level names. The trace was
deterministic and excluded plausible user input/focus interference.

All ten current-candidate locale/presentation cases and their exact evidence
boundary are retained in
[Feature-freeze non-E4 evidence](FEATURE_FREEZE_NON_E4_EVIDENCE.md). The live
large-text result proves automated geometry and UIA behavior only, not human
legibility or visual acceptance.

This is a UI Automation client smoke, not proof of spoken order, pronunciation,
verbosity, braille output, or usability with a particular assistive technology.
The same bounded probe now exercises English and Simplified Chinese UIA names;
the localization boundary and fallback rules are recorded in
[Operator localization](OPERATOR_LOCALIZATION.md). Narrator/NVDA human review,
live 200%/400% visual review, translation certification, physical two-monitor
usability evidence, human visual-design review, E4, and exact release evidence stay
separate later gates. The implemented per-monitor rectangle/DPI selection
contract is documented in
[Native operator multi-display composition](OPERATOR_MULTI_DISPLAY.md).
