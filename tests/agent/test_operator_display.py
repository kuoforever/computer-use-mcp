from __future__ import annotations

import ctypes
from ctypes import wintypes

import pytest

from computer_use_agent.operator_display import (
    OperatorDisplayError,
    OperatorMonitor,
)
from computer_use_agent.operator_display_win32 import (
    foreground_operator_monitor,
    operator_dpi_for_monitor,
    operator_monitor_for_window,
)


class _FakeUser32:
    def __init__(
        self,
        *,
        foreground: int = 42,
        window_dpi: int = 144,
        system_dpi: int = 96,
        monitor_ok: bool = True,
    ) -> None:
        self.foreground = foreground
        self.window_dpi = window_dpi
        self.system_dpi = system_dpi
        self.monitor_ok = monitor_ok
        self.monitor_requests: list[int] = []

    def GetForegroundWindow(self) -> int:  # noqa: N802
        return self.foreground

    def MonitorFromWindow(self, hwnd: wintypes.HWND, fallback: int) -> int:  # noqa: N802
        assert fallback == 1
        self.monitor_requests.append(int(hwnd.value or 0))
        return 9001

    def GetMonitorInfoW(self, _monitor: int, pointer: object) -> bool:  # noqa: N802
        if not self.monitor_ok:
            return False
        info = ctypes.cast(pointer, ctypes.POINTER(_FakeMonitorInfo)).contents
        info.rcMonitor = wintypes.RECT(-1920, -120, 0, 1080)
        info.rcWork = wintypes.RECT(-1920, -80, 0, 1040)
        return True

    def GetDpiForWindow(self, _hwnd: wintypes.HWND) -> int:  # noqa: N802
        return self.window_dpi

    def GetDpiForSystem(self) -> int:  # noqa: N802
        return self.system_dpi


class _FakeMonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _FakeShcore:
    def __init__(self, *, dpi: int = 144, result: int = 0) -> None:
        self.dpi = dpi
        self.result = result
        self.requests: list[tuple[int, int]] = []

    def GetDpiForMonitor(  # noqa: N802
        self,
        monitor: int,
        dpi_type: int,
        dpi_x_pointer: object,
        dpi_y_pointer: object,
    ) -> int:
        self.requests.append((monitor, dpi_type))
        ctypes.cast(dpi_x_pointer, ctypes.POINTER(wintypes.UINT)).contents.value = (
            self.dpi
        )
        ctypes.cast(dpi_y_pointer, ctypes.POINTER(wintypes.UINT)).contents.value = (
            self.dpi
        )
        return self.result


def test_foreground_monitor_snapshot_preserves_negative_coordinates_and_dpi() -> None:
    user32 = _FakeUser32()
    shcore = _FakeShcore()

    selected = foreground_operator_monitor(user32, shcore=shcore)

    assert selected == OperatorMonitor(
        bounds=(-1920, -120, 0, 1080),
        work_area=(-1920, -80, 0, 1040),
        dpi=144,
    )
    assert user32.monitor_requests == [42]
    assert shcore.requests == [(9001, 0)]


def test_monitor_dpi_does_not_inherit_foreground_app_awareness() -> None:
    user32 = _FakeUser32(window_dpi=96, system_dpi=120)

    selected = operator_monitor_for_window(
        user32,
        42,
        shcore=_FakeShcore(dpi=168),
    )

    assert selected.dpi == 168


def test_missing_foreground_uses_primary_fallback_and_system_dpi() -> None:
    user32 = _FakeUser32(foreground=0, window_dpi=0, system_dpi=120)

    selected = foreground_operator_monitor(user32)

    assert selected.dpi == 120
    assert user32.monitor_requests == [0]


def test_invalid_window_dpi_has_fixed_96_dpi_last_resort() -> None:
    user32 = _FakeUser32(window_dpi=0, system_dpi=0)

    assert operator_monitor_for_window(user32, 42).dpi == 96


def test_failed_monitor_dpi_query_uses_window_then_system_fallbacks() -> None:
    user32 = _FakeUser32(window_dpi=120, system_dpi=96)

    assert operator_dpi_for_monitor(
        user32,
        _FakeShcore(dpi=144, result=-1),
        9001,
        42,
    ) == 120


def test_failed_monitor_query_fails_closed() -> None:
    with pytest.raises(OperatorDisplayError, match="OPERATOR_MONITOR_INFO_FAILED"):
        operator_monitor_for_window(_FakeUser32(monitor_ok=False), 42)


@pytest.mark.parametrize(
    "monitor",
    [
        OperatorMonitor((0, 0, 10, 10), (0, 0, 10, 10), 96),
    ],
)
def test_valid_monitor_contract_is_immutable(monitor: OperatorMonitor) -> None:
    assert monitor.bounds == (0, 0, 10, 10)


@pytest.mark.parametrize(
    ("bounds", "work_area", "dpi"),
    [
        ((0, 0, 0, 10), (0, 0, 1, 1), 96),
        ((0, 0, 10, 10), (-1, 0, 10, 10), 96),
        ((0, 0, 10, 10), (0, 0, 10, 10), True),
        ((0, 0, 10, 10), (0, 0, 10, 10), 769),
    ],
)
def test_invalid_monitor_contract_fails_closed(
    bounds: tuple[int, int, int, int],
    work_area: tuple[int, int, int, int],
    dpi: int,
) -> None:
    with pytest.raises(OperatorDisplayError, match="OPERATOR_MONITOR_INVALID"):
        OperatorMonitor(bounds, work_area, dpi)
