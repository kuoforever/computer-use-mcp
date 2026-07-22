# Tech stack

> **Status: current Windows stack plus explicitly planned directions.**

## Implemented runtime

| Layer | Technology | Why it is here |
| --- | --- | --- |
| Language and package | Python 3.11–3.13, setuptools | Local distribution and direct native interop. |
| MCP server | MCP Python SDK / FastMCP, stdio | Exposes the tool surface to MCP-capable clients. |
| Accessibility | `uiautomation` / Windows UI Automation | Finds controls and calls native accessibility patterns. |
| Capture | `mss` | Captures the current primary display. |
| Process ownership | `psutil` | Builds foreground process ancestry for the safe-mode gate. |
| Native desktop control | Win32 via `ctypes` | DPI awareness, input, window activation, and e-stop polling. |
| Image processing | Pillow | Draws configured screenshot blackouts in tests and runtime. |
| Tests and linting | pytest, Ruff | Covers pure logic and checks style. |

The package intentionally does not depend on `pyautogui`. Pointer, keyboard,
window, and DPI operations stay close to the Win32 APIs so their behavior is
visible in the driver.

## Current platform boundary

Only `src/computer_use_mcp/drivers/windows.py` implements a platform driver.
The project is therefore Windows-only despite the platform-neutral core and
contract. The current screenshot tool captures the primary display, not a full
virtual desktop.

Chromium, Chrome, and Edge receive a best-effort UIA warm-up. Their page-level
accessibility behavior is still experimental and needs application-specific
validation.

## Not implemented today

- A generic browser-native adapter. Browser interaction currently uses the same
  UIA, screenshot, and input paths as other Windows applications.
- `pyautogui`.
- A claim of foreground-free ref actions on the user's desktop.
- A default full-control mode.
- Host-to-guest MCP transport or guest lifecycle automation.

The planned universal-GUI direction may add bounded OCR, document-text, or
browser-native observation adapters behind a shared observation contract. It
does not require stealth automation or evasion of site security controls.

## Planned platform and worker options

| Area | Direction | Status |
| --- | --- | --- |
| macOS | AX-based native driver | Planned |
| Linux | AT-SPI-based native driver | Planned |
| Android device | ADB-transport driver (`input` / `uiautomator dump` / `screencap`), scrcpy as viewer, behind the same contract | Planned — deferred until the Windows vertical is application-verified; see [ADR-008](adr/008-android-device-driver-behind-driver-contract.md) |
| Windows multi-monitor | Virtual-desktop coordinate/capture model | Planned |
| Isolated Windows worker | Existing VMware VM helper as a host-side starting point | Experimental |
| Other isolated workers | Second session, independent display server, VM, or second machine | Planned |
| Hidden Windows desktop | `CreateDesktop` / `SwitchDesktop` investigation | Experimental research only |

An isolated worker needs its own foreground, pointer, keyboard, screenshot
source, allowlist, and audit log. It is a runtime-orchestration problem, not a
small branch inside the normal Windows driver.

For contract-level mappings, see [Driver Contract](DRIVER_CONTRACT.md). For
sequencing, see [Roadmap](EXECUTION_PLAN.md).
