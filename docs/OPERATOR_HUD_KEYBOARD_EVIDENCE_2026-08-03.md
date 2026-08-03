# Decision Card physical Alt+Tab acceptance — 2026-08-03

> **Result: PASS for the bounded `GDA-HUD-004` Alt+Tab clause.**

## Acceptance standard

The check required all of the following:

1. the visual-only Decision Card was presented with synthetic data;
2. the operator, not automation, pressed physical Alt+Tab while reviewing it;
3. Windows switched foreground to another application; and
4. the review left no matching `Needs input · approval locked` window behind.

The operator reported: “我按了alt tab，可以切换窗口”. A post-check found no
remaining visible process whose exact main-window title was
`Needs input · approval locked`.

## Safety boundary

The review helper opens no Runner, MCP server, provider, application action, or
desktop dispatch. It therefore cannot approve or execute an external effect.
The keystroke was deliberately not synthesized: automation would not prove
that the physical operator escape path remained available.

This evidence proves only that a physical Alt+Tab press can switch away while
the bounded synthetic Decision Card is presented. It does not independently
promote Windows security-key, foreground-restoration, DPI, Chrome, Word,
provider, release, or universal-GUI claims. Those remain owned by their
separate source, smoke, visual, and complete-run evidence.

## Closure mapping

This closes the last operator-only clause listed for `GDA-HUD-004`. Together
with the retained exit smoke (`Esc`, close, and timeout), the no-global-hook
source check, the multi-DPI visual evidence, and the post-fix complete Demo, it
closes the bounded `GDA-DEMO-003` acceptance detour.

## Final validation

After the evidence and canonical status records were updated, the complete
repository gate passed:

- `1566 passed, 8 skipped`;
- Ruff: `All checks passed!`;
- mypy: `Success: no issues found in 118 source files`;
- documentation consistency: `OK (13 reviewed tools)`; and
- `git diff --check` completed successfully (line-ending notices only).
