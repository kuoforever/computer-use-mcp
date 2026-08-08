from __future__ import annotations

from pathlib import Path

import pytest

from computer_use_agent.approval_inbox import ApprovalNotice
from computer_use_agent.approval_notification_activation import (
    ApprovalNotificationActivationSink,
)
from computer_use_agent.approval_notification_toast_win32 import (
    ACTIVATOR_CLSID,
    APP_USER_MODEL_ID,
    ModernToastApprovalNotifier,
    _registration_for,
    _toast_xml,
)
from computer_use_agent.operator_localization import OperatorLocale


class _Identity:
    def __init__(self) -> None:
        self.ensure_calls = 0

    def ensure(self) -> None:
        self.ensure_calls += 1


class _Runtime:
    def __init__(self) -> None:
        self.shown: list[ApprovalNotice] = []
        self.hidden: list[object] = []

    def show(self, notice: ApprovalNotice) -> object:
        self.shown.append(notice)
        return ("handle", notice.notice_id)

    def hide(self, handle: object) -> None:
        self.hidden.append(handle)


def test_modern_toast_uses_fixed_content_and_exact_withdrawal() -> None:
    identity = _Identity()
    runtime = _Runtime()
    notifier = ModernToastApprovalNotifier(identity=identity, runtime=runtime)
    notice = ApprovalNotice("private_request_id", OperatorLocale.ZH_CN)

    notifier.show(notice)
    notifier.withdraw("different_request")
    notifier.withdraw(notice.notice_id)

    assert identity.ensure_calls == 1
    assert runtime.shown == [notice]
    assert runtime.hidden == [("handle", "private_request_id")]


def test_modern_toast_replaces_only_its_active_notice() -> None:
    runtime = _Runtime()
    notifier = ModernToastApprovalNotifier(identity=_Identity(), runtime=runtime)

    notifier.show(ApprovalNotice("request_1"))
    notifier.show(ApprovalNotice("request_2"))

    assert [notice.notice_id for notice in runtime.shown] == ["request_1", "request_2"]
    assert runtime.hidden == [("handle", "request_1")]


def test_modern_toast_rejects_unreviewed_notice_types() -> None:
    notifier = ModernToastApprovalNotifier(identity=_Identity(), runtime=_Runtime())

    with pytest.raises(ValueError, match="notice must be an ApprovalNotice"):
        notifier.show(object())  # type: ignore[arg-type]


def test_toast_xml_escapes_copy_and_excludes_routing_identity() -> None:
    notice = ApprovalNotice("private_request_id")

    xml = _toast_xml(notice)

    assert "Guarded Desktop Agent" in xml
    assert "Approval needed. Return to the open decision window." in xml
    assert "private_request_id" not in xml
    assert "action" not in xml.casefold()


def test_registration_binds_current_python_host_without_task_authority(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    executable.touch()
    pythonw.touch()

    registration = _registration_for(executable=executable, appdata=tmp_path)

    assert registration.executable == executable.resolve()
    assert registration.pythonw == pythonw.resolve()
    assert registration.shortcut.name == "Guarded Desktop Agent.lnk"
    assert registration.local_server_command == (
        f'"{pythonw.resolve()}" '
        "-m computer_use_agent.approval_notification_activation"
    )
    assert APP_USER_MODEL_ID == "Kuoforever.GuardedDesktopAgent"
    assert ACTIVATOR_CLSID == "{B4743C8A-AF5D-50E8-B648-8D052D83B0C1}"


def test_activation_sink_is_an_inert_success_path() -> None:
    sink = ApprovalNotificationActivationSink()

    result = sink.Activate(APP_USER_MODEL_ID, "untrusted-activation-data", None, 0)

    assert result == 0
