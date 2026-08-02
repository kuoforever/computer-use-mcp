"""The HUD adapters must not share ctypes prototype tables.

`ctypes.windll.user32` returns one cached library object per process, and every
function on it carries a single mutable ``argtypes``/``restype``. Two adapters
that prototype the same call therefore overwrite each other.

That happened. The Decision Card and the workflow Progress HUD each define
their own ``_MONITORINFO`` and each pinned ``GetMonitorInfoW.argtypes`` to a
pointer to *its own* type. Constructing the card adapter made the progress
adapter's ``byref`` of a structurally identical type raise ``ArgumentError``,
so the progress window failed to open. The bounded Demo builds the card adapter
before the Runner opens the progress window, and the progress lifecycle is
fail-silent, so the workflow HUD never appeared and reported nothing.
"""
from __future__ import annotations

import ctypes

from computer_use_agent.decision_card_window_win32 import Win32DecisionCardWindowApi
from computer_use_agent.presence_window_win32 import Win32PresenceWindowApi
from computer_use_agent.progress_window_win32 import Win32ProgressWindowApi
from computer_use_agent.win32_dll import private_windll


def test_each_adapter_holds_its_own_library_handles() -> None:
    progress = Win32ProgressWindowApi()
    card = Win32DecisionCardWindowApi()
    presence = Win32PresenceWindowApi()

    handles = [
        progress._user32,
        card._user32,
        presence._user32,
        ctypes.windll.user32,
    ]
    for index, first in enumerate(handles):
        for second in handles[index + 1 :]:
            assert first is not second, "adapters share one prototype table"


def test_prototyping_one_handle_cannot_reach_another() -> None:
    """The property that actually matters, asserted directly."""

    first = private_windll("user32")
    second = private_windll("user32")

    first.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    assert second.GetMonitorInfoW.argtypes != first.GetMonitorInfoW.argtypes
    assert ctypes.windll.user32.GetMonitorInfoW.argtypes != first.GetMonitorInfoW.argtypes


def test_a_card_adapter_does_not_break_a_progress_adapter() -> None:
    """The exact ordering the bounded Demo uses."""

    progress = Win32ProgressWindowApi()
    Win32DecisionCardWindowApi()

    # The call that used to raise ArgumentError once the card had prototyped it.
    assert progress._work_area(progress.foreground()) is not None
