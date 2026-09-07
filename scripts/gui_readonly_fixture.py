"""Disposable native test application; contains no desktop automation or file data."""
from __future__ import annotations

import argparse
import sys

TITLE = "GDA read-only observation fixture"
TARGET = "Observation target"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show-test-window", action="store_true", required=True)
    parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("Windows interactive session required")
    from computer_use_mcp.dpi import enable_dpi_awareness

    enable_dpi_awareness()
    import win32api
    import win32con
    import win32gui

    def window_proc(hwnd, message, wparam, lparam):
        if message == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        # The target button has no command handler and performs no operation.
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    window_class = win32gui.WNDCLASS()
    window_class.hInstance = win32api.GetModuleHandle(None)
    window_class.lpszClassName = "GdaReadonlyFixtureV1"
    window_class.lpfnWndProc = window_proc
    window_class.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    window_class.hbrBackground = win32con.COLOR_WINDOW + 1
    atom = win32gui.RegisterClass(window_class)
    # Borderless primary-display window: no unsupported title-bar/menu targets,
    # no negative maximized-window margins, and only synthetic visible contents.
    window = win32gui.CreateWindowEx(
        0, atom, TITLE, win32con.WS_POPUP | win32con.WS_VISIBLE,
        0, 0, win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1),
        0, 0, window_class.hInstance, None,
    )
    for label, y in [
        ("GDA: real read-only observation test", 80),
        ("Synthetic contents only. No model call or action is running.", 130),
        ("Keep this window in front during collection. Alt+F4 closes it.", 180),
    ]:
        win32gui.CreateWindowEx(
            0, "STATIC", label, win32con.WS_CHILD | win32con.WS_VISIBLE,
            80, y, 800, 35, window, 0, window_class.hInstance, None,
        )
    win32gui.CreateWindowEx(
        0, "BUTTON", TARGET, win32con.WS_CHILD | win32con.WS_VISIBLE,
        80, 260, 260, 70, window, 1, window_class.hInstance, None,
    )
    win32gui.UpdateWindow(window)
    win32gui.PumpMessages()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
