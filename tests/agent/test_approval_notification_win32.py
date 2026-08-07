from __future__ import annotations

import pytest

from computer_use_agent.approval_inbox import ApprovalNotice
from computer_use_agent.approval_notification_win32 import Win32ApprovalNotifier


class _User32:
    def __init__(self, *, hwnd: int = 101, icon: int = 202) -> None:
        self.hwnd = hwnd
        self.icon = icon
        self.created: list[tuple[str, str]] = []
        self.destroyed: list[int] = []

    def CreateWindowExW(  # noqa: ANN001, N802
        self,
        _ex_style,
        class_name,
        window_name,
        _style,
        _x,
        _y,
        _width,
        _height,
        _parent,
        _menu,
        _instance,
        _parameter,
    ) -> int:
        self.created.append((class_name, window_name))
        return self.hwnd

    def LoadIconW(self, _instance, _resource) -> int:  # noqa: ANN001, N802
        return self.icon

    def DestroyWindow(self, hwnd: int) -> bool:  # noqa: N802
        self.destroyed.append(hwnd)
        return True


class _Shell32:
    def __init__(self, *, fail_operation: int | None = None) -> None:
        self.calls: list[tuple[int, str, str, int]] = []
        self.fail_operation = fail_operation

    def Shell_NotifyIconW(self, operation: int, pointer) -> bool:  # noqa: ANN001, N802
        data = pointer._obj  # noqa: SLF001 - ctypes test probe
        self.calls.append(
            (int(operation), str(data.szInfoTitle), str(data.szInfo), int(data.uFlags))
        )
        return operation != self.fail_operation


def test_native_notification_uses_fixed_noninteractive_content_and_withdraws() -> None:
    shell32 = _Shell32()
    user32 = _User32()
    notifier = Win32ApprovalNotifier(
        shell32=shell32,
        user32=user32,
    )
    notice = ApprovalNotice("private_request_id")

    notifier.show(notice)
    notifier.withdraw(notice.notice_id)

    assert [call[0] for call in shell32.calls] == [0, 4, 2]
    _operation, title, body, flags = shell32.calls[0]
    assert title == "Guarded Desktop Agent"
    assert body == "Approval needed. Review the bound local approval surface."
    assert "private_request_id" not in title + body
    assert flags & 0x10  # NIF_INFO
    assert user32.created == [("STATIC", "Guarded Desktop Agent notification host")]
    assert user32.destroyed == [101]


def test_native_notification_requires_a_private_host_window_and_exact_notice_type() -> None:
    notifier = Win32ApprovalNotifier(
        shell32=_Shell32(),
        user32=_User32(hwnd=0),
    )

    with pytest.raises(OSError, match="APPROVAL_NOTIFICATION_HOST_UNAVAILABLE"):
        notifier.show(ApprovalNotice("request_1"))
    with pytest.raises(ValueError, match="notice must be an ApprovalNotice"):
        notifier.show(object())  # type: ignore[arg-type]


def test_withdrawing_a_different_notice_cannot_remove_the_active_one() -> None:
    shell32 = _Shell32()
    user32 = _User32()
    notifier = Win32ApprovalNotifier(
        shell32=shell32,
        user32=user32,
    )
    notifier.show(ApprovalNotice("request_1"))

    notifier.withdraw("request_2")

    assert [call[0] for call in shell32.calls] == [0, 4]
    assert user32.destroyed == []


@pytest.mark.parametrize("fail_operation", [0, 4])
def test_show_failure_always_destroys_the_private_host_window(
    fail_operation: int,
) -> None:
    user32 = _User32()
    notifier = Win32ApprovalNotifier(
        shell32=_Shell32(fail_operation=fail_operation),
        user32=user32,
    )

    with pytest.raises(OSError, match="APPROVAL_NOTIFICATION"):
        notifier.show(ApprovalNotice("request_1"))

    assert user32.destroyed == [101]
