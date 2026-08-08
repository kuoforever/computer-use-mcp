# PRODUCT-021 physical ShortcutBroker evidence

> **Status: passed on 2026-08-08 as bounded human acceptance only.** This
> record covers one installed configurable-key ShortcutBroker run on one
> Windows machine. It does not widen shortcut authority or claim layouts that
> were not loaded for the run.

## Candidate and environment

- Product implementation: PR #293 merge `51ff2d8`.
- Repository observation point: `6e325a4`, the documentation-only PRODUCT-021
  closeout on top of that merge.
- Follow-up observation point: `0d37677`, the documentation closeout after the
  first supervised configured-G/K evidence publication.
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

The first run proves one human-triggered configured G/K path on the two layouts
loaded on this machine: G visibly foregrounded Agent Controls, K failed closed
without an active run, and both registrations were released.

## Follow-up physical acceptance

The same installed wheel was rebound explicitly through its isolated `site`
directory, with a fresh isolated `LOCALAPPDATA` and K pause configuration. The
follow-up used only operator physical key input. It opened no real provider,
MCP server, application, or desktop-dispatch port.

### Direct-console Ctrl+C

The Host ran directly in a console under PowerShell transcription rather than
through `Tee-Object`. The operator confirmed that physical `Ctrl+C` stopped the
Host. The flushed transcript contains the exact final line:

```text
SHORTCUTS STOPPED · Registrations released.
```

Retained ignored transcript:

```text
out/product021-remaining-physical-308f5e8745544caa8b171a4fafe6f99d/
  direct-console-transcript.txt
```

SHA-256:
`6AA743EB0EDD7309E2091499789F4D31D873808670FC18DB9B773617A3A8CD09`.

### Independent physical Q latch

An installed-candidate `EStop` harness registered only the independent fixed
`Ctrl+Alt+Q` path. After the operator pressed Q, its transcript recorded:

```text
ESTOP LATCHED - actions would remain denied until restart
```

Retained ignored transcript:

```text
out/product021-remaining-physical-308f5e8745544caa8b171a4fafe6f99d/
  physical-q-transcript.txt
```

SHA-256:
`0038FD7F60EC529B38B728152B7009FC9D7A2A2B8A37730587854F6192601786`.

This proves the installed E-stop object latched from physical Q. The harness
did not start the full MCP server or attempt an action after the latch, so it
does not promote full-server action-denial evidence.

### Invalid first active-K attempt

The first fake-only active-Runner harness allowed only 120 seconds. Its Runner
timed out before the operator input arrived; the later K therefore correctly
printed `PAUSE UNAVAILABLE` against a closed/failed control record. Timing and
control evidence invalidate that attempt as a live-pause result. It is retained
to distinguish a harness-window failure from a product failure:

```text
out/product021-remaining-physical-308f5e8745544caa8b171a4fafe6f99d/
  physical-k-transcript.txt
  physical-pause-runner.log
  physical-pause-runner.err.log
```

Their respective SHA-256 values are
`C2A6AEFAE6ECCCA35E552C3968721B6CF385D0C18B56221B8F4934E3A1FF72D2`,
`F89A3BEEF530C201C719CAC13F635894E5C8B81260E37B206208C7ECB3BA8013`,
and `04A1DE17350B2058FE0C488FBA8EBD95E56A0B8D7D7CFFB26F6A8E221969040E`.

### Valid active-Runner K pause and release

A fresh isolated rerun gave the fake-only harness 600 seconds. It used the
production `AgentRunner`, `LocalCooperativeControl`, control record, and
OS-backed run lock; fake provider and desktop-MCP objects performed no external
work. Read-only Win32 probes confirmed that the visible Host owned G/K before
the operator pressed physical `Ctrl+Alt+K`.

The Host and Runner then recorded this order:

```text
PAUSE REQUESTED · Pause requested. Wait before touching the shared desktop.
PAUSED RELEASED · Paused. Desktop authority is released for local use.
RUNNER OBSERVED PAUSE_REQUESTED
RUNNER PAUSED - DESKTOP AUTHORITY RELEASED checkpoint=1
```

The pause occurred at checkpoint `1` with boundary `before_provider`. The state
and trace retain `model_turns_used=1`, `tool_calls_used=0`, and
`side_effects_used=0`. A harness-only automated resume was then intentionally
unable to complete because the fake provider returned final text without a
fresh observation. The production Runner failed closed with
`VERIFICATION_REQUIRED`; final control was `closed/failed`, authority `none`,
and `fresh_observation_required=true`. That cleanup result is not a failed
pause: it proves stale grounding did not become resume authority.

Retained ignored evidence and SHA-256 values:

```text
out/product021-remaining-physical-rerun-3544223c91fe40ed9a2ff2b25a9bffdf/
  host-transcript.txt  7E9262BC49CEC6E0C2DDE721237C29CB2A014AB93CC4013AAB2C23138414B456
  runner.log           950CF0B07000E5E555F9E4CFB40620CDD97557AA1B0469AB4F82DA514DA33353
  runner.err.log       B09BBD36292D4DA4B226E461C34BE433ADDB710B4C076BE7A88EDC586B433D0E
  localappdata/computer-use-agent/runs/physical_pause_run/
    control.json       B7F399B077642E00F864D4D8D4CA75F265CDFB4D3672A0C2C8F1E03E402A5738
    state.json         5F01765CEA3C267A2483C4FF8C451F9E91835022CB4FE448187D27E1E07B62FA
  localappdata/computer-use-agent/traces/
    physical_pause_run.jsonl
      AC2EF185911F083D987C7FD4FF880C2A565C59288EF44837A73C189E8337BFAA
```

After evidence capture, the exact Host processes were stopped. A fresh Win32
probe registered and released G/K with `error=0`, and no test process remained.

### Layout boundary

The current Windows profile exposed only Simplified Chinese with Microsoft
Pinyin and English (United States), matching the two loaded handles above. No
third installed/loaded layout existed for a bounded physical rerun. This is an
environment limitation and remains unclaimed rather than a failed layout.

## Updated exact claim boundary

Together, the supervised runs prove configured G foreground/fail-closed K,
direct-console Ctrl+C cleanup wording, the installed physical-Q E-stop latch,
and physical K driving an active production Runner control lifecycle through
`pause_requested -> paused/released` before any provider call. They do not
prove full-MCP post-Q action denial, real-provider/MCP/application pause or
resume, layouts not installed/loaded for the run, other Windows builds,
broader assistive technology or hardware, E4, or release readiness.
