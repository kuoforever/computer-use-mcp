"""Private Win32 library handles, so two adapters cannot overwrite each other.

``ctypes.windll.user32`` returns one cached library object for the whole
process, and each function on it carries a single mutable ``argtypes`` and
``restype``. Two adapters that both prototype the same call therefore share one
prototype, and whichever is constructed last wins.

That is not theoretical. The Decision Card and the workflow Progress HUD each
define their own ``_MONITORINFO`` structure and each pinned
``GetMonitorInfoW.argtypes`` to a pointer to *its own* type. Constructing the
Decision Card adapter made the Progress adapter's ``ctypes.byref`` of its
structurally identical type raise ``ArgumentError``, so the Progress window
failed to open. The bounded Demo constructs the card adapter before the Runner
ever opens the Progress window, and the Progress lifecycle is fail-silent, so
the workflow HUD simply never appeared and said nothing about it.

Each adapter takes its own handle here. The libraries are still the same loaded
DLLs; only the Python-side prototype tables are private.
"""

from __future__ import annotations

import ctypes


def private_windll(name: str) -> ctypes.WinDLL:
    """Return a library handle with prototypes no other adapter can change.

    Every call builds a new ``WinDLL``. Hold the result for the lifetime of the
    adapter rather than calling this per operation.
    """

    if not isinstance(name, str) or not name or not name.isidentifier():
        raise ValueError("WIN32_LIBRARY_NAME_INVALID")
    return ctypes.WinDLL(name)


__all__ = ["private_windll"]
