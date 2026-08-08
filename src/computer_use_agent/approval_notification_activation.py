"""No-authority COM activation sink for identity-backed Windows toasts."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

from comtypes import CLSCTX_LOCAL_SERVER, COMMETHOD, COMObject, GUID, HRESULT, IUnknown
from comtypes.server.localserver import run

from .approval_notification_toast_win32 import ACTIVATOR_CLSID


class _NotificationUserInputData(ctypes.Structure):
    _fields_ = [
        ("key", wintypes.LPCWSTR),
        ("value", wintypes.LPCWSTR),
    ]


class _INotificationActivationCallback(IUnknown):
    _iid_ = GUID("{53E31837-6600-4A81-9395-75CFFE746F94}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "Activate",
            (["in"], wintypes.LPCWSTR, "app_user_model_id"),
            (["in"], wintypes.LPCWSTR, "invoked_args"),
            (
                ["in"],
                ctypes.POINTER(_NotificationUserInputData),
                "data",
            ),
            (["in"], wintypes.ULONG, "data_count"),
        )
    ]


class ApprovalNotificationActivationSink(COMObject):
    """Acknowledge toast activation without opening any product authority port."""

    _reg_clsid_ = GUID(ACTIVATOR_CLSID)
    _reg_progid_ = "GuardedDesktopAgent.NotificationActivation"
    _reg_desc_ = "Guarded Desktop Agent notification activation sink"
    _reg_clsctx_ = CLSCTX_LOCAL_SERVER
    _reg_threading_ = "Both"
    _com_interfaces_ = [_INotificationActivationCallback]

    def Activate(  # noqa: N802 - COM method name
        self,
        _app_user_model_id: str | None,
        _invoked_args: str | None,
        _data: Any,
        _data_count: int,
    ) -> int:
        return 0


def main() -> int:
    run([ApprovalNotificationActivationSink])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ApprovalNotificationActivationSink", "main"]
