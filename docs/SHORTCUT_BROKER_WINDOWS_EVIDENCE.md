# ShortcutBroker real Windows registration evidence

> **Status: passed on 2026-08-08 for one non-input Windows 11 registration
> path.** This record proves the merged fixed G/P broker can own and release its
> reviewed Win32 registrations on the observed machine. It is not physical-key,
> universal-layout, configurable-shortcut, application, E4, or release evidence.

## Candidate and command

| Field | Value |
| --- | --- |
| Product candidate | PRODUCT-019 merge `60b26cc45b7145c8a197abbda3cfc2bcf20f612a` |
| Installed wheel SHA-256 | `26B4263035EAD2B2F4842CF741677CA1B410B12E3B37B2E1C0BDD0F993A72B76` |
| Evidence JSON SHA-256 | `8A4B2495C37CD69F8BF1EC7CD295D6FAC55605BFBCB14E10A6CE1AF02EA845B5` |
| Platform | Windows 11 `10.0.26200`, Python `3.13.7` |
| Physical input | `false` |

The repository harness was imported against the clean installed-wheel target,
not the worktree package:

~~~powershell
$env:PYTHONPATH = "<clean installed-wheel target>"
.\.venv\Scripts\python.exe scripts\smoke_shortcut_broker_win32.py `
  --candidate-sha 60b26cc45b7145c8a197abbda3cfc2bcf20f612a `
  --output out\product020-shortcut-windows.json
~~~

The harness starts only bounded copies of itself. It opens no provider, MCP,
application, desktop-dispatch, approval, resume, retry, or replay port.

## Native results

| Check | Observed result |
| --- | --- |
| Exact modifiers | `MOD_CONTROL | MOD_ALT | MOD_NOREPEAT` |
| Real message queue | Product `GlobalShortcutLoop` registered G/P, accepted direct worker-thread `WM_HOTKEY` messages in exact `open_controls -> request_pause` order, accepted `WM_QUIT`, and unregistered in `finally` |
| Cross-process multi-instance | A second product loop failed visibly with `SHORTCUT_CONFLICT_OPEN_CONTROLS` while another process held both keys |
| Atomic second-key conflict | With only P held by another process, the product loop registered G, failed with `SHORTCUT_CONFLICT_REQUEST_PAUSE`, and released G |
| Rollback proof | G was immediately reacquired while the other process still held P |
| Final release | G/P were reacquired together after holder exit; a separate post-harness probe reacquired and released both again |
| Foreground | The same nonzero foreground window handle remained before and after the complete run |

The `WM_HOTKEY` messages were posted directly to the evidence worker's thread
queue with `PostThreadMessageW`. That safely exercises the real product message
loop without sending global keyboard input. It deliberately does not prove that
a human or `SendInput` physical-key path triggers the shortcuts.

## Loaded-layout / AltGr audit

The run enumerated the layouts loaded on this machine and queried
`VkKeyScanExW` for `U+0020` through `U+FFFF` excluding surrogate code points.
It found no character mapped to virtual key G or P with both Control and Alt in
either loaded layout:

| Layout handle | Locale | Current thread | Ctrl+Alt+G/P mappings |
| --- | --- | --- | --- |
| `0x0000000008040804` | `zh-CN` | yes | none / none |
| `0x0000000004090409` | `en-US` | no | none / none |

This is an exact observation of two currently loaded layouts, not a universal
keyboard-layout claim. Layouts not loaded during the run, dead-key behavior not
represented by `VkKeyScanExW`, physical AltGr input, and future configurable
key choices remain outside this result.

## Claim boundary

The evidence promotes only one Windows native registration/message-queue,
conflict/rollback, release/reacquisition, foreground-preservation, and
currently-loaded-layout result. `Ctrl+Alt+Q` remains independent and was not
registered. Global approve/resume remain absent. Provider, MCP, application,
desktop action, other AT/hardware, E4, and release readiness remain unclaimed.
