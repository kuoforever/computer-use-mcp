# Bounded BOSS observation evidence

> **Status: bounded on-device MCP observation retained 2026-07-18.** This
> record demonstrates the repaired foreground-activation path and a read-only
> BOSS home-page observation through the project's Windows stdio server. It is
> not BOSS workflow acceptance, provider evidence, or release evidence.

## Reviewed boundary

- Source commit before this documentation update: `bb0f483`.
- Surface: project-local `computer-use-mcp.exe` launched through the Agent
  Host's bounded stdio bridge.
- Mode: `safe_local`, `chrome.exe` allowlisted, dangerous confirmation enabled,
  and the 2.5-second human-idle gate retained.
- Scope: one existing Chrome window and the signed-in BOSS home page.
- Excluded: messages, applications, saved-job changes, uploads, screenshots,
  provider calls, and any attempt to bypass login or challenge state.

The stdio handshake exposed exactly the reviewed eight tools:
`activate_window`, `click`, `find`, `key`, `list_windows`, `screenshot`, `type`,
and `ui_snapshot`.

## Result

The MCP server selected the sole returned Chrome window, activated it
successfully, addressed the UIA-returned Chrome address-bar ref, and navigated
to the BOSS home page. The post-navigation `list_windows` title was
`BOSS直聘-找工作BOSS直聘直接谈！招聘求职找工作！ - Google Chrome`.

The bounded home-page snapshot contained 126 lines and 10,760 serialized
characters. It exposed the signed-in navigation, search control, interactive
job cards, and stable job-detail URLs. `find("BOSS")` reduced the observation
to three matching interactive lines. `find("感兴趣")` and
`find("岗位职责")` returned no matching interactive elements on that page.

The local action audit recorded successful activation at
`2026-07-18T10:11:49+00:00`, followed by redacted address-bar typing and the
Enter key. Typed content is represented only by presence and length metadata.

## Safety stop and unresolved boundary

The next attempted UI-only navigation, opening the signed-in user menu, was
rejected as `HUMAN_ACTIVE`. A later activation retry was rejected for the same
reason. No menu click or interested-jobs navigation occurred after those
decisions, and the human-idle threshold was not disabled or shortened.

This result closes the narrow post-repair P0 evidence gate: the repaired
activation path can reach and observe one real BOSS page through the project
MCP. It does not fill the application-verification column. The next observation
gate remains a bounded document-text or OCR fallback for static content, then a
separate interested-jobs result when the workstation is idle.
