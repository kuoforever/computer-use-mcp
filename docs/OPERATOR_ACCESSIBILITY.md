# Operator accessibility

> **Status: implemented and offline verified on Windows; bounded native UIA
> smoke passed on 2026-08-08 and one supervised English Narrator Decision Card
> review passed after a verbosity repair.** A later UX walkthrough accepted the
> Decision Card large-text design and repaired real Progress/Presence defects.
> This contract covers the focus-taking Decision Card and the non-activating
> Progress and Presence surfaces. It does not claim NVDA/JAWS/braille,
> other-locale auditory review, complete human large-text/visual acceptance,
> physical multi-monitor usability, application acceptance, provider or MCP
> execution, or release-candidate evidence.

## Trust boundary

Accessibility settings are presentation inputs only. They never create an
approval, control, retry, replay, provider, MCP, or desktop-dispatch port.
Decision Card remains the only interactive approval surface. Progress and
Presence remain non-activating; their accessible names project only fixed
Host-owned status. Progress has one presentation-only disclosure Button that
locally expands or collapses its read-only checklist. It cannot approve,
control, retry, replay, resume, or dispatch work. Presence has no action pattern.

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

The Decision Card uses native `STATIC`, read-only `RICHEDIT50W`, and `BUTTON`
controls so the standard Windows UI Automation proxies expose Text, Document,
TextPattern, and Button
semantics. The details edit has the visible label `Decision details`; fixed
header lines, the details toggle, and all four choices have bounded accessible
names derived from Host-owned presentation text in the selected locale.

- Initial focus is the unique safe `option_deny` button, displayed as
  `Stop task` in English and `停止任务` in Simplified Chinese.
- `Tab` and `Shift+Tab` traverse the details toggle and all interactive choices
  in native dialog order, including wraparound. The complete labelled,
read-only details Document remains in the UIA tree but is not a Tab stop: static
  evidence is read on demand with assistive-technology reading/scan commands
  instead of automatically dumping its full value into the decision flow.
- Arrow keys and `Space` retain native button navigation and activation.
- `Enter` activates only an already focused known toggle or option. It never
  creates a default approval from the top-level window or details text.
- `Esc`, close, timeout, malformed state, and native failure deny without
  dispatch.

The visible countdown is also the accessibility event source. Name-change
events are bounded to the initial timeout and the 60, 30, 10, and 0 second
milestones instead of announcing every timer tick. Progress emits a top-level
name change only when its six trusted summary fields change. Its wrapping,
scrolling read-only Document exposes TextPattern, while its real Button exposes
Invoke only for compact/expanded presentation state. Presence emits one fixed
content-free phase name only when the phase changes. Neither surface activates
or takes foreground focus, and neither exposes workflow authority.

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
Progress keeps all six semantic summary fields in one wrapping read-only
Document, uses a bounded scrolling viewport for the expanded checklist, and
keeps the disclosure Button in a separate bottom action row at 400%. Presence
measures the selected Segoe UI glyphs with `GetTextExtentPoint32W`; status-tab
geometry contains the measured English/Simplified-Chinese 200%/400% extents.

## Evidence and limits

Deterministic coverage validates preference fallback/composition, palette
selection, contrast ratios, focus order, safe keyboard activation, bounded
announcement milestones, UIA name construction, passive no-activation
contracts, and 200%/400% layout arithmetic.

Run the bounded native probe from a normal interactive Windows desktop:

~~~powershell
python scripts/smoke_operator_accessibility.py
~~~

The 2026-08-08 probe exercised dark, light, and High-Contrast-over-light in
English and Simplified Chinese, then exercised live 200% and 400% text reflow.
It found the Decision Card header as UIA Text
controls, the labelled details pane as Document/TextPattern, and all four choices as
Button. It
observed initial safe-denial focus, traversed the complete Tab path, resolved
`option_deny` with `Enter`, confirmed that Progress exposed one wrapping
Document/TextPattern plus one disclosure Button/Invoke with exact
compact/expanded/compact state, and confirmed that Progress and Presence kept
the foreground unchanged while exposing bounded top-level names. The trace was
deterministic and excluded plausible user input/focus interference.

All ten current-candidate locale/presentation cases and their exact evidence
boundary are retained in
[Feature-freeze non-E4 evidence](FEATURE_FREEZE_NON_E4_EVIDENCE.md). The same
ten safe-denial cases passed again after PRODUCT-016; the newer scope and open
human rows are in
[PRODUCT-017 automated native evidence](PRODUCT017_AUTOMATED_NATIVE_EVIDENCE.md).
The supervised [PRODUCT-017 human native evidence](PRODUCT017_HUMAN_NATIVE_EVIDENCE.md)
records the observed focus-triggered 500-plus-character Narrator dump, its
bounded Tab-order repair, the passing default-path plus on-demand scan-mode
rerun, and the later all-surface UX walkthrough. That walkthrough accepted the
Decision Card and repaired real Progress/Presence large-text defects; final
human confirmation of the revised passive surfaces remains open.

The automated probe is not proof of spoken output. The separate supervised
English Narrator result covers only the named Decision Card path, spoken order,
bounded default verbosity, and on-demand details access; it is not proof of
NVDA/JAWS, braille output, another locale, or broad assistive-technology
usability.
The same bounded probe now exercises English and Simplified Chinese UIA names;
the localization boundary and fallback rules are recorded in
[Operator localization](OPERATOR_LOCALIZATION.md). Other assistive-technology
and locale review, live 200%/400% visual review, translation certification, physical two-monitor
usability evidence, human visual-design review, E4, and exact release evidence stay
separate later gates. The implemented per-monitor rectangle/DPI selection
contract is documented in
[Native operator multi-display composition](OPERATOR_MULTI_DISPLAY.md).
