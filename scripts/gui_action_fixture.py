"""Disposable one-use native fixture for the explicitly authorized action diagnostic."""
import argparse
import sys

TITLE = "GDA single-action fixture"
TARGET = "Observation target"
COMPLETED = "Completed once"


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

    completed = False

    def window_proc(hwnd, message, wparam, lparam):
        nonlocal completed
        if message == win32con.WM_COMMAND and wparam == 1 and not completed:
            button = win32gui.GetDlgItem(hwnd, 1)
            if lparam == button:
                completed = True
                win32gui.SetWindowText(button, COMPLETED)
                win32gui.EnableWindow(button, False)
                return 0
        if message == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    window_class = win32gui.WNDCLASS()
    window_class.hInstance = win32api.GetModuleHandle(None)
    window_class.lpszClassName = "GdaSingleActionFixtureV1"
    window_class.lpfnWndProc = window_proc
    window_class.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
    window_class.hbrBackground = win32con.COLOR_WINDOW + 1
    atom = win32gui.RegisterClass(window_class)
    window = win32gui.CreateWindowEx(
        0, atom, TITLE, win32con.WS_POPUP | win32con.WS_VISIBLE, 0, 0,
        win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1),
        0, 0, window_class.hInstance, None,
    )
    for label, y in [
        ("GDA: one local-model action test", 80),
        ("The agent may operate the test button once. No files are changed.", 130),
        ("Keep this window in front. Do not use mouse/keyboard. Alt+F4 closes it.", 180),
    ]:
        win32gui.CreateWindowEx(0, "STATIC", label, win32con.WS_CHILD | win32con.WS_VISIBLE,
                                80, y, 1000, 35, window, 0, window_class.hInstance, None)
    win32gui.CreateWindowEx(0, "BUTTON", TARGET, win32con.WS_CHILD | win32con.WS_VISIBLE,
                            80, 260, 260, 70, window, 1, window_class.hInstance, None)
    win32gui.UpdateWindow(window)
    win32gui.PumpMessages()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
