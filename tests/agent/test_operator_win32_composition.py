from __future__ import annotations

import sys

import pytest

from computer_use_agent.decision_card_window_win32 import (
    Win32DecisionCardWindowApi,
)
from computer_use_agent.presence_window_win32 import Win32PresenceWindowApi
from computer_use_agent.progress_window_win32 import Win32ProgressWindowApi


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 operator surfaces")
def test_native_operator_surfaces_can_share_one_process_abi() -> None:
    # Decision Card configures the process-global user32 handle first, matching
    # the integration order that exposed nominally incompatible ctypes pointers.
    Win32DecisionCardWindowApi()
    presence = Win32PresenceWindowApi()
    progress = Win32ProgressWindowApi()

    # The card also configures message-pump signatures. Both passive surfaces
    # must still accept their layout-compatible wintypes.MSG structures.
    presence.pump()
    progress.pump()
