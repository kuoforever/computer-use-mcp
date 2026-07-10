"""Controlled probe for whether a background UIA SetValue changes foreground.

The probe never activates the target. It discards its result if the system's
last-input tick changes during the observation window, because that indicates
human or injected input and makes foreground attribution inconclusive.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import psutil  # noqa: E402
import uiautomation as auto  # noqa: E402

from computer_use_mcp.contract import PruneOpts  # noqa: E402
from computer_use_mcp.drivers.windows import WindowsDriver  # noqa: E402


def notepad_hwnd() -> int | None:
    for window in auto.GetRootControl().GetChildren():
        try:
            if psutil.Process(window.ProcessId).name().lower() == "notepad.exe" and window.NativeWindowHandle:
                return int(window.NativeWindowHandle)
        except Exception:
            continue
    return None


def main() -> int:
    target = notepad_hwnd()
    if target is None:
        subprocess.Popen(["notepad.exe"])
        time.sleep(1.5)
        target = notepad_hwnd()
    if target is None:
        print("RESULT: INCONCLUSIVE (Notepad window not found)")
        return 2

    driver = WindowsDriver()
    foreground = driver._foreground_hwnd()
    if foreground == target:
        print("RESULT: INCONCLUSIVE (target is foreground; focus another window and retry)")
        return 2

    print(f"target={target} foreground={foreground}; do not use mouse or keyboard for 2 seconds")
    stable_tick = driver.last_input_tick()
    time.sleep(1.0)
    if driver.last_input_tick() != stable_tick:
        print("RESULT: INCONCLUSIVE (input detected before action)")
        return 2

    tree = driver.get_tree(PruneOpts(scope=str(target)))
    document = next((node for node in tree.nodes if node.role == "Document" and "value" in node.patterns), None)
    if document is None:
        print("RESULT: INCONCLUSIVE (no writable Notepad Document)")
        return 2

    input_before = driver.last_input_tick()
    foreground_before = driver._foreground_hwnd()
    result = driver.set_value(document.native_id, "background focus probe")
    foreground_after = driver._foreground_hwnd()
    input_after = driver.last_input_tick()

    if input_after != input_before:
        print("RESULT: INCONCLUSIVE (input tick changed during action)")
        return 2
    if not result.ok:
        print(f"RESULT: FAIL (SetValue {result.code}: {result.message})")
        return 1
    if foreground_before != foreground_after:
        print(f"RESULT: FAIL (foreground changed {foreground_before} -> {foreground_after})")
        return 1
    print("RESULT: PASS (background SetValue preserved foreground with no input detected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
