from __future__ import annotations

import asyncio
import ctypes
import json
from pathlib import Path

import pytest

from computer_use_mcp.contract import DRIVER_ERROR, Node, Rect, Result, TreeResult
from computer_use_mcp.drivers import windows as windows_driver_module
from computer_use_mcp.drivers.windows import WindowsDriver
from computer_use_mcp.server import build_server


UNKNOWN_ENVELOPE = "ERROR NATIVE_OUTCOME_UNKNOWN: native action outcome unknown after dispatch"
UIA_SECRET = "uia-effect-then-raise-secret"
TYPE_SECRET = "typed-partial-sendinput-secret"


class _Feedback:
    def __init__(self) -> None:
        self.events: list[tuple[str, str] | tuple[str]] = []

    def show_pointer(self, _x: int, _y: int, *, action: str) -> None:
        self.events.append(("pointer", action))

    def show_keyboard(
        self,
        *,
        action: str,
        total_units: int = 0,
        estimated_seconds: float = 0.0,
    ) -> None:
        del total_units, estimated_seconds
        self.events.append(("keyboard", action))

    def clear(self) -> None:
        self.events.append(("clear",))


def _windows_driver(feedback: _Feedback) -> WindowsDriver:
    """Construct the real action implementation without touching a real desktop."""

    driver = WindowsDriver.__new__(WindowsDriver)
    driver._pacing = None
    driver._action_feedback = feedback
    driver._typing_interval = 0.0
    driver._sleep = lambda _seconds: None
    driver._native_action_boundary = None
    driver._node_cache = {}
    driver.snapshot_warmup_delay = lambda _scope: 0.0  # type: ignore[method-assign]
    driver.snapshot_incomplete_reason = (  # type: ignore[method-assign]
        lambda _scope, _tree: None
    )
    return driver


def _tool_text(result: object) -> str:
    content = result[0] if isinstance(result, tuple) else result
    return "\n".join(getattr(item, "text", "") for item in content)


def _read_action_audit(path: Path) -> tuple[str, dict[str, object]]:
    raw = path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in raw.splitlines()]
    assert len(records) == 1
    return raw, records[0]


def _assert_fixed_unknown(
    result: object,
    audit_path: Path,
    *,
    secret: str,
) -> dict[str, object]:
    text = _tool_text(result)
    raw, record = _read_action_audit(audit_path)

    assert text == UNKNOWN_ENVELOPE
    assert record["decision"] == "unknown_outcome"
    assert secret not in text
    assert secret not in raw
    return record


def test_uia_callback_effect_then_raise_is_central_redacted_unknown(
    tmp_path: Path,
) -> None:
    effects: list[str] = []
    driver_results: list[Result] = []
    feedback = _Feedback()
    driver = _windows_driver(feedback)
    native_id = "7001"

    class InvokePattern:
        def Invoke(self) -> None:
            effects.append("invoke-effect")
            raise RuntimeError(f"effect applied before {UIA_SECRET}")

    class Bounds:
        left = 10
        top = 20
        right = 40
        bottom = 60

    class Control:
        BoundingRectangle = Bounds()

        @staticmethod
        def GetRuntimeId() -> list[int]:
            return [int(native_id)]

        @staticmethod
        def GetInvokePattern() -> InvokePattern:
            return InvokePattern()

    control = Control()

    def get_tree(_opts: object) -> TreeResult:
        driver._node_cache = {native_id: control}
        return TreeResult(
            nodes=[
                Node(
                    native_id=native_id,
                    role="Button",
                    name="Preview",
                    value=None,
                    bbox=Rect(10, 20, 30, 40),
                    states=["enabled"],
                    patterns=["invoke"],
                )
            ],
            truncated=0,
        )

    driver.get_tree = get_tree  # type: ignore[method-assign]
    invoke = driver.invoke

    def capture_driver_result(resolved_native_id: str) -> Result:
        result = invoke(resolved_native_id)
        driver_results.append(result)
        return result

    driver.invoke = capture_driver_result  # type: ignore[method-assign]
    audit_path = tmp_path / "uia-actions.jsonl"
    server = build_server(
        driver=driver,
        start_estop=False,
        dangerous_confirmation=False,
        control_mode="full_control_local",
        audit_path=str(audit_path),
    )
    snapshot = _tool_text(asyncio.run(server.call_tool("ui_snapshot", {"scope": "foreground"})))
    assert "ref_1" in snapshot

    result = asyncio.run(
        server.call_tool(
            "click",
            {"ref": "ref_1", "x": None, "y": None, "button": "left"},
        )
    )
    record = _assert_fixed_unknown(result, audit_path, secret=UIA_SECRET)

    assert effects == ["invoke-effect"]
    assert len(driver_results) == 1
    assert not driver_results[0].ok
    assert driver_results[0].code == DRIVER_ERROR
    assert UIA_SECRET in driver_results[0].message
    assert feedback.events == [("pointer", "target"), ("clear",)]
    assert record["tool"] == "click"


def test_focused_type_positive_partial_sendinput_unwinds_then_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send_calls: list[list[tuple[int, int]]] = []
    driver_results: list[Result] = []

    class User32:
        @staticmethod
        def SendInput(count: int, pointer: object, _size: int) -> int:
            typed_pointer = ctypes.cast(
                pointer,
                ctypes.POINTER(windows_driver_module.auto.INPUT),
            )
            send_calls.append(
                [
                    (
                        int(typed_pointer[index].union.ki.wScan),
                        int(typed_pointer[index].union.ki.dwFlags),
                    )
                    for index in range(count)
                ]
            )
            return 1

    monkeypatch.setattr(
        "computer_use_mcp.drivers.windows.ctypes.windll.user32",
        User32(),
    )
    feedback = _Feedback()
    driver = _windows_driver(feedback)
    type_focused = driver.type

    def capture_driver_result(text: str) -> Result:
        result = type_focused(text)
        driver_results.append(result)
        return result

    driver.type = capture_driver_result  # type: ignore[method-assign]
    audit_path = tmp_path / "type-actions.jsonl"
    server = build_server(
        driver=driver,
        start_estop=False,
        dangerous_confirmation=False,
        control_mode="full_control_local",
        audit_path=str(audit_path),
    )

    result = asyncio.run(server.call_tool("type", {"text": TYPE_SECRET, "ref": None}))
    record = _assert_fixed_unknown(result, audit_path, secret=TYPE_SECRET)

    assert len(driver_results) == 1
    assert not driver_results[0].ok
    assert driver_results[0].code == DRIVER_ERROR
    assert driver_results[0].message == "SendInput did not insert the complete scalar"
    assert len(send_calls) == 2
    assert len(send_calls[0]) == 2
    assert send_calls[0][0][1] == 0x0004
    assert send_calls[0][1][1] == 0x0006
    assert send_calls[1] == [send_calls[0][1]]
    assert feedback.events == [("keyboard", "typing"), ("clear",)]
    assert record["tool"] == "type"
