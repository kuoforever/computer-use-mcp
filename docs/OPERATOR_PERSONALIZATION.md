# Operator presentation personalization

> **Status: implemented and bounded native-smoke verified on Windows.** The
> three composed native operator surfaces share one strict dark, light, or
> system-following theme contract. This is presentation only; it is not a
> provider, model, desktop, approval, capture, retry, replay, or dispatch input.

## Configuration and fallback

`[operator].theme` accepts exactly `"dark"`, `"light"`, or `"auto"`.
Omitting the key preserves the legacy dark presentation. Newly generated
installed product profiles write `theme = "auto"`.

`auto` reads the current Windows application-theme preference from
`HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize` and accepts
only a DWORD `AppsUseLightTheme` value of `0` or `1`. A missing key, unavailable
API, invalid type, invalid value, or non-Windows runtime fails silently to dark.
An invalid configured string is different: strict configuration loading rejects
it before a native surface is opened.

The precedence is:

1. configured or detected Windows High Contrast selects Windows system colors;
2. otherwise explicit `dark` or `light` selects that fixed product palette;
3. otherwise `auto` selects the current Windows application theme;
4. an absent key or failed `auto` lookup uses the legacy dark palette.

Generated product profiles also retain `high_contrast = true` from
`GDA-PRODUCT-005`. That force-on accessibility choice intentionally overrides
their `theme = "auto"`. An operator who wants the selected theme while still
respecting detected Windows High Contrast can explicitly set
`high_contrast = false`; a detected system High Contrast preference still wins.

## Fixed visual contract

Dark preserves the shipped operator chrome. Light uses a shared light
background, raised surface, dark text, muted text, and hairline across Presence,
Progress, and Decision Card. Status roles and their stable labels, glyphs, and
machine IDs do not change. Light mode maps the fixed semantic accents to darker
variants so text and boundaries retain deterministic contrast; unknown accents
fail to the fixed light-mode blue instead of accepting arbitrary styling.

High Contrast bypasses both product palettes and continues to use
`COLOR_WINDOW`, `COLOR_WINDOWTEXT`, `COLOR_HIGHLIGHT`,
`COLOR_HIGHLIGHTTEXT`, `COLOR_BTNFACE`, and `COLOR_BTNTEXT`. The Decision Card
also disables immersive dark caption styling in light or High Contrast mode.

## Trust boundary and exclusions

Theme resolution returns one enum before native surface construction. It never
receives task text, model prose, application identity, run history, approval
facts, screenshots, or tool results. It cannot choose a monitor, change action
coordinates, alter capture scope, enable a surface, approve an effect, or
change Runner/MCP behavior. Native construction failure remains fail-silent
under the owning Presence, Progress, or approval boundary.

This slice deliberately excludes custom colors, typography, density, layout,
per-application or learned preferences, model-controlled styling, remote sync,
and preference persistence outside the existing strict TOML file.

## Evidence and limits

Deterministic tests cover strict configuration, system lookup fallback,
generated profiles, palette selection, High Contrast precedence, semantic
accent mapping, contrast ratios, and shared adapter wiring. The bounded native
probe exercises dark, light, and High-Contrast-over-light in English and
Simplified Chinese. Every Decision Card starts and resolves on safe
`option_deny`; Presence and Progress remain non-activating and inside the
Host-selected monitor geometry.

The probe is not a human visual-design review, Narrator/NVDA result, physical
two-monitor result, application/provider/MCP execution, E4 result, or release
evidence. Those gates remain separate for the exact feature-freeze candidate.
