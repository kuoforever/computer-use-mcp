# GDA-05 — Native operator UX and accessibility evidence

> **Status: current candidate item; automated and human scopes are distinct.**
> Personal ownership: `TBC`. Submission-ready only after `My scope` is filled.

## Quick select

| Field | Guidance |
| --- | --- |
| Primary roles | Windows UI, accessibility, human-in-the-loop UX, client platform |
| Position | Lead for Windows/UX roles; support otherwise |
| Evidence ceiling | Named automated native cases plus exact English Narrator, one-monitor visual, fake-only control, and Windows 11 notification results |
| Use when | The JD mentions accessibility, UIA, localization, operator trust, native UX, or observability |
| Skip when | There is no space to retain the narrow human-evidence scope |
| Exact JD keywords | `Windows UI`, `accessibility`, `UI Automation`, `Narrator`, `High Contrast`, `localization`, `human-in-the-loop` |

## Resume copy

**Short ZH:** 构建 native Decision Card、Progress 与 Presence；经一次
English Narrator 路径及单显示器 200%/400% 人工审查，修复 500+ 字自动朗读、
文本裁剪及字形宽度缺陷。

**Evidence-rich ZH:** 实现 Decision Card、Progress/Presence、Task Center、
notification 与 cooperative control 的分层 operator UX；以 10 个双语/主题/
大字 native safe-denial cases、一次 English Narrator 路径和单显示器
200%/400% 人工审查驱动 RichEdit/TextPattern、Button/Invoke、measured-glyph
reflow 修复，并保留一条 Windows 11 notification 与 fake-only takeover timing
证据。

**Short EN:** Built native Windows operator surfaces and used one bounded
English Narrator path plus one-monitor 200%/400% reviews to fix excessive
speech, clipping, and glyph-measurement defects.

**Evidence-rich EN:** Implemented accessible Decision, Progress, and Presence
surfaces, plus layered Task Center, notification, and cooperative-control
paths, retaining exact automated and human evidence for safe focus, UIA
semantics, large-text reflow, one Narrator path, and one Windows 11 notification
path.

**My scope to confirm:** Identify the native UI implementation, accessibility
contract, human test design, defect diagnosis, repair, screenshots/operator
review, or evidence record you personally owned.

## Fact card

| Layer | Evidence-backed fact |
| --- | --- |
| Design constraint | Interactive approval must remain distinct from passive status and attention-only notification; presentation cannot grant authority |
| Automated native | Ten English/Simplified-Chinese dark/light/High-Contrast/200%/400% safe-denial cases verify UIA semantics, focus, reflow, and foreground preservation |
| Human Narrator | One bounded English Decision Card path passed after removing the static details Document from ordinary Tab order |
| Human visual | The named one-monitor 200%/400% Progress and Presence presentation was accepted after clipping and glyph-width repairs |
| Notification | One watched Simplified-Chinese modern banner, pending Notification Center item, foreground preservation, and Host withdrawal passed on Windows 11 |
| Cooperative timing | One fake-only same-machine run: pause acknowledged in `65.2 ms`; resume-to-close in `1587.5 ms`; fresh observation, no post-resume input, unchanged focus |

## Proof map

| Claim | Owner/evidence |
| --- | --- |
| Accessibility semantics and limits | [Operator accessibility](../../OPERATOR_ACCESSIBILITY.md) |
| Exact human/invalid/blocked attempts | [PRODUCT-017 human evidence](../../PRODUCT017_HUMAN_NATIVE_EVIDENCE.md) |
| Current evidence ceiling | [Capability dashboard](../../CAPABILITY_STATUS.md) |

## Interview card

- **S:** the original UI technically exposed content but created unusable
  speech, clipped large text, and non-semantic painted controls.
- **T:** state the implementation, accessibility review, or evidence portion you owned.
- **A:** use native UIA-friendly controls, safe focus, interaction-only Tab
  order, on-demand document reading, measured glyph extents, and bounded reflow.
- **R:** name the exact Narrator, visual, native-matrix, notification, or timing
  result you personally verified; keep the others as project evidence.
- **Trade-off:** passive surfaces remain non-activating and less interactive so
  they cannot steal focus or become a hidden control plane.
- **Debug story:** focus on the observed 500-plus-character Narrator dump or
  Progress 400% clipping, the root cause, and the bounded fix.

Deep-dive questions:

1. Why should static details remain in the UIA tree but outside ordinary Tab order?
2. Why is synthetic geometry insufficient for physical two-monitor acceptance?
3. How do notifications remain useful while having no approval or task-control port?

## Claim limits

Do not collapse the evidence into an all-matrix human claim. Narrator is one
English Decision Card path; 200%/400% is one-monitor visual acceptance;
notification is one Simplified-Chinese Windows 11 path; cooperative timing is
fake-only. Do not claim WCAG certification, NVDA/JAWS/braille, all locales,
all Windows versions, physical two-monitor acceptance, or application/E4/release
evidence.
