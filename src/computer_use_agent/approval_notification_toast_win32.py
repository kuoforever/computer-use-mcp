"""Modern Windows toast delivery for fixed approval-attention notices.

The notification platform registration is presentation infrastructure only.
It carries no approval, task-control, provider, MCP, retry, replay, or desktop
authority.  Toast activation is routed to a separate no-op COM sink; the bound
Decision Card remains the only decision surface.
"""

from __future__ import annotations

import ctypes
import os
import sys
import winreg
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, cast
from xml.sax.saxutils import escape

from .approval_inbox import ApprovalNotice
from .win32_dll import private_windll


APP_USER_MODEL_ID = "Kuoforever.GuardedDesktopAgent"
ACTIVATOR_CLSID = "{B4743C8A-AF5D-50E8-B648-8D052D83B0C1}"
_DISPLAY_NAME = "Guarded Desktop Agent"
_SHORTCUT_NAME = f"{_DISPLAY_NAME}.lnk"
_ACTIVATION_MODULE = "computer_use_agent.approval_notification_activation"
_TOAST_TAG = "approval"
_TOAST_GROUP = "gda"
_TOAST_LIFETIME = timedelta(minutes=5)
_PKEY_APP_USER_MODEL_TOAST_ACTIVATOR_CLSID = (
    "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}",
    26,
)


@dataclass(frozen=True)
class _ToastRegistration:
    executable: Path
    pythonw: Path
    shortcut: Path

    @property
    def local_server_command(self) -> str:
        return f'"{self.pythonw}" -m {_ACTIVATION_MODULE}'


class _IdentityPort(Protocol):
    def ensure(self) -> None: ...


class _ToastRuntimePort(Protocol):
    def show(self, notice: ApprovalNotice) -> object: ...

    def hide(self, handle: object) -> None: ...


def _registration_for(
    *,
    executable: Path | None = None,
    appdata: Path | None = None,
) -> _ToastRegistration:
    resolved_executable = Path(executable or sys.executable).resolve(strict=True)
    if resolved_executable.name.casefold() != "python.exe":
        raise OSError("APPROVAL_NOTIFICATION_PYTHON_HOST_UNAVAILABLE")
    pythonw = resolved_executable.with_name("pythonw.exe")
    if not pythonw.is_file():
        raise OSError("APPROVAL_NOTIFICATION_PYTHONW_HOST_UNAVAILABLE")
    resolved_appdata = Path(appdata or os.environ.get("APPDATA", ""))
    if not resolved_appdata.is_absolute():
        raise OSError("APPROVAL_NOTIFICATION_APPDATA_UNAVAILABLE")
    shortcut = (
        resolved_appdata
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / _SHORTCUT_NAME
    )
    return _ToastRegistration(
        executable=resolved_executable,
        pythonw=pythonw,
        shortcut=shortcut,
    )


def _toast_xml(notice: ApprovalNotice) -> str:
    if not isinstance(notice, ApprovalNotice):
        raise ValueError("notice must be an ApprovalNotice")
    return (
        '<toast><visual><binding template="ToastGeneric">'
        f"<text>{escape(notice.title)}</text>"
        f"<text>{escape(notice.body)}</text>"
        "</binding></visual></toast>"
    )


class _Win32ToastIdentity:
    def __init__(
        self,
        *,
        executable: Path | None = None,
        appdata: Path | None = None,
        shell32: Any | None = None,
    ) -> None:
        self._registration = _registration_for(
            executable=executable,
            appdata=appdata,
        )
        self._shell32 = shell32 if shell32 is not None else private_windll("shell32")
        self._registered = False

    def ensure(self) -> None:
        if self._registered:
            return
        self._set_process_identity()
        self._register_user_identity()
        self._write_shortcut()
        self._registered = True

    def _set_process_identity(self) -> None:
        setter = self._shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        result = int(setter(APP_USER_MODEL_ID))
        if result < 0:
            raise OSError(
                "APPROVAL_NOTIFICATION_PROCESS_IDENTITY_FAILED: "
                f"0x{result & 0xFFFFFFFF:08X}"
            )

    def _register_user_identity(self) -> None:
        app_key_path = rf"Software\Classes\AppUserModelId\{APP_USER_MODEL_ID}"
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            app_key_path,
            0,
            winreg.KEY_WRITE,
        ) as app_key:
            winreg.SetValueEx(app_key, "DisplayName", 0, winreg.REG_SZ, _DISPLAY_NAME)
            winreg.SetValueEx(
                app_key,
                "IconBackgroundColor",
                0,
                winreg.REG_SZ,
                "FFDDDDDD",
            )
            winreg.SetValueEx(
                app_key,
                "CustomActivator",
                0,
                winreg.REG_SZ,
                ACTIVATOR_CLSID,
            )

        clsid_key_path = rf"Software\Classes\CLSID\{ACTIVATOR_CLSID}\LocalServer32"
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            clsid_key_path,
            0,
            winreg.KEY_WRITE,
        ) as clsid_key:
            winreg.SetValueEx(
                clsid_key,
                "",
                0,
                winreg.REG_SZ,
                self._registration.local_server_command,
            )

    def _write_shortcut(self) -> None:
        import pythoncom
        import pywintypes
        from win32com.propsys import propsys, pscon
        from win32com.shell import shell

        self._registration.shortcut.parent.mkdir(parents=True, exist_ok=True)
        toast_activator_key = (
            pywintypes.IID(_PKEY_APP_USER_MODEL_TOAST_ACTIVATOR_CLSID[0]),
            _PKEY_APP_USER_MODEL_TOAST_ACTIVATOR_CLSID[1],
        )
        pythoncom.CoInitialize()
        try:
            link = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink,
                None,
                pythoncom.CLSCTX_INPROC_SERVER,
                shell.IID_IShellLink,
            )
            link.SetPath(str(self._registration.executable))
            link.SetArguments("-m computer_use_agent.cli")
            link.SetWorkingDirectory(str(self._registration.executable.parent))
            link.SetDescription(_DISPLAY_NAME)
            link.SetIconLocation(str(self._registration.executable), 0)
            store = link.QueryInterface(propsys.IID_IPropertyStore)
            store.SetValue(
                pscon.PKEY_AppUserModel_ID,
                propsys.PROPVARIANTType(APP_USER_MODEL_ID, pythoncom.VT_LPWSTR),
            )
            store.SetValue(
                toast_activator_key,
                propsys.PROPVARIANTType(
                    pywintypes.IID(ACTIVATOR_CLSID),
                    pythoncom.VT_CLSID,
                ),
            )
            store.Commit()
            persist = link.QueryInterface(pythoncom.IID_IPersistFile)
            persist.Save(str(self._registration.shortcut), 0)
        finally:
            pythoncom.CoUninitialize()
        self._notify_shell()

    def _notify_shell(self) -> None:
        shcne_create = 0x00000002
        shcne_updateitem = 0x00002000
        shcnf_pathw = 0x0005
        notifier = self._shell32.SHChangeNotify
        notifier.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        notifier.restype = None
        path = ctypes.c_wchar_p(str(self._registration.shortcut))
        pointer = ctypes.cast(path, ctypes.c_void_p)
        notifier(shcne_create, shcnf_pathw, pointer, None)
        notifier(shcne_updateitem, shcnf_pathw, pointer, None)


class _WinRTToastRuntime:
    def show(self, notice: ApprovalNotice) -> object:
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import ToastNotification, ToastNotificationManager

        document = XmlDocument()
        document.load_xml(_toast_xml(notice))
        toast = ToastNotification(document)
        toast.tag = _TOAST_TAG
        toast.group = _TOAST_GROUP
        toast.expiration_time = datetime.now(timezone.utc) + _TOAST_LIFETIME
        notifier = ToastNotificationManager.create_toast_notifier_with_id(
            APP_USER_MODEL_ID
        )
        notifier.show(toast)
        return notifier, toast

    def hide(self, handle: object) -> None:
        notifier, toast = cast(tuple[Any, Any], handle)
        notifier.hide(toast)


class ModernToastApprovalNotifier:
    """Show one identity-backed fixed-content toast until withdrawn."""

    def __init__(
        self,
        *,
        identity: _IdentityPort | None = None,
        runtime: _ToastRuntimePort | None = None,
    ) -> None:
        self._identity = identity if identity is not None else _Win32ToastIdentity()
        self._runtime = runtime if runtime is not None else _WinRTToastRuntime()
        self._active_notice_id: str | None = None
        self._active_handle: object | None = None

    def show(self, notice: ApprovalNotice) -> None:
        if not isinstance(notice, ApprovalNotice):
            raise ValueError("notice must be an ApprovalNotice")
        if self._active_notice_id is not None:
            self.withdraw(self._active_notice_id)
        self._identity.ensure()
        handle = self._runtime.show(notice)
        self._active_notice_id = notice.notice_id
        self._active_handle = handle

    def withdraw(self, notice_id: str) -> None:
        if notice_id != self._active_notice_id or self._active_handle is None:
            return
        handle = self._active_handle
        self._active_notice_id = None
        self._active_handle = None
        self._runtime.hide(handle)


__all__ = [
    "ACTIVATOR_CLSID",
    "APP_USER_MODEL_ID",
    "ModernToastApprovalNotifier",
]
