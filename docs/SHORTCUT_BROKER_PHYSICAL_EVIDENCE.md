# PRODUCT-021 physical ShortcutBroker evidence

> **Status: passed on 2026-08-08 as bounded human acceptance only.** This
> record covers one installed configurable-key ShortcutBroker run on one
> Windows machine. It does not widen shortcut authority or claim layouts that
> were not loaded for the run.

## Candidate and environment

- Product implementation: PR #293 merge `51ff2d8`.
- Repository observation point: `6e325a4`, the documentation-only PRODUCT-021
  closeout on top of that merge.
- Installed wheel SHA-256:
  `4D531EF57559AC884DA2D0044522DEBE9EF39683279A58330702F75E44908D13`.
- The wheel source tree and PR #293 merge tree both resolved to
  `727d425ded487f76f6202abcef8b9e208eda6fea`.
- Machine: 64-bit Windows build `26200`.
- Loaded Win32 layout handles: `0x08040804` (`zh-CN`) and `0x04090409`
  (`en-US`).
- Effective shortcuts: fixed `Ctrl+Alt+G` Agent Controls, configured
  `Ctrl+Alt+K` cooperative-pause request, and independent `Ctrl+Alt+Q`
  emergency stop.

The Host used the installed wheel from an isolated target directory. It opened
no provider, MCP, application, or desktop-dispatch port and had no active
controlled run.

## Invalid setup attempt

The first launch omitted the isolated candidate's matching `LOCALAPPDATA`.
Strict validation rejected the config with
`agent state_dir must be inside the user-local application directory` before
`SHORTCUTS ACTIVE`. No shortcut was registered. This attempt is invalid setup
evidence and contributes no physical-key result.

## Valid supervised run

The corrected launch supplied the same isolated user-local root. The Host
checked both loaded layouts, registered G/K, and printed `SHORTCUTS ACTIVE`.
The operator then provided the only physical input:

1. From another foreground window, the operator pressed `Ctrl+Alt+G` and
   explicitly confirmed that the Agent Controls console came to the
   foreground. The Host log contains `CONTROLS OPENED · Agent Controls opened.`
   (two accepted G events were recorded during the supervised interaction).
2. From another foreground window, the operator pressed `Ctrl+Alt+K`. With no
   active controlled run, the Host emitted exactly
   `PAUSE UNAVAILABLE · Safe pause is unavailable. Do not assume desktop
   authority was released.` It did not claim pause, release, approval, resume,
   or dispatch authority.
3. `Ctrl+Alt+Q` was intentionally not exercised. It remained outside the
   broker and independent of this acceptance.

The operator supplied an in-session screenshot showing the configured G/K/Q
projection, `SHORTCUT HOST · ACTIVE`, the G success, the K fail-closed result,
and the later PowerShell prompt. The raw screenshot was not copied into the
repository.

## Exit and registration cleanup

The evidence launcher piped Host output through PowerShell `Tee-Object` to
retain a log. Physical `Ctrl+C` stopped that pipeline and returned to the
PowerShell prompt; the product's direct-console `SHORTCUTS STOPPED` line was
not observed, so this run does not claim that presentation detail.

Read-only process inspection found zero remaining Python ShortcutBroker hosts.
A fresh non-input Win32 process then registered G/K, released them, registered
both again, and finally released both. This proves the physical run left no
hotkey registration behind. The empty launcher shell was then closed.

Retained ignored log:

```text
out/product021-physical-acceptance-d537481c50414ccb82e3276300384280/
  shortcut-host-attempt2.log
```

Log SHA-256:
`9A95D6DD2349F4C39BB91D7787D81F4D0EE212A1C7A891099AA7C33C902DA968`.

## Exact claim boundary

This run proves one human-triggered configured G/K path on the two layouts
loaded on this machine: G visibly foregrounded Agent Controls, K failed closed
without an active run, and both registrations were released. It does not prove
physical Q, a successful pause/release against a live workflow, direct-console
Ctrl+C wording, layouts not loaded for the run, other Windows builds,
provider/MCP/application behavior, E4, or release readiness.
