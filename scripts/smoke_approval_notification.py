"""Bounded two-locale native lifecycle smoke for approval notifications.

The probe carries fixed product wording only.  It verifies Shell acceptance,
hidden-host cleanup, and foreground preservation; Windows quiet time may still
suppress the visible toast, so this is not visibility or assistive-technology
evidence.
"""
from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from computer_use_agent.approval_inbox import ApprovalNotice  # noqa: E402
from computer_use_agent.approval_notification_win32 import (  # noqa: E402
    Win32ApprovalNotifier,
)
from computer_use_agent.operator_localization import OperatorLocale  # noqa: E402


def _foreground() -> int:
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    return int(user32.GetForegroundWindow() or 0)


def _is_window(hwnd: int) -> bool:
    user32 = ctypes.windll.user32
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    return bool(user32.IsWindow(wintypes.HWND(hwnd)))


def _smoke(locale: OperatorLocale) -> dict[str, object]:
    notice = ApprovalNotice(f"product014-{locale.value}", locale=locale)
    notifier = Win32ApprovalNotifier()
    before = _foreground()
    notifier.show(notice)
    hwnd = int(notifier._active_hwnd or 0)
    try:
        if not hwnd or not _is_window(hwnd):
            raise RuntimeError("approval notification host window is unavailable")
        time.sleep(0.75)
        after = _foreground()
    finally:
        notifier.withdraw(notice.notice_id)
    if before != after:
        raise RuntimeError("approval notification changed foreground")
    if _is_window(hwnd):
        raise RuntimeError("approval notification host was not destroyed")
    return {
        "fixed_body": notice.body,
        "fixed_title": notice.title,
        "foreground_unchanged": True,
        "host_destroyed": True,
        "shell_delivery_accepted": True,
        "visible_toast_claimed": False,
    }


def main() -> int:
    results = {locale.value: _smoke(locale) for locale in OperatorLocale}
    print(json.dumps({"locales": results}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
