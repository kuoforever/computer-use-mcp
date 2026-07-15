from __future__ import annotations

import unittest

from computer_use_mcp.contract import DRIVER_ERROR, STALE_ELEMENT
from computer_use_mcp.drivers.windows import WindowsDriver, _activate_window_with_api


class FakeKernel32:
    def __init__(self, events: list[tuple], thread_id: int = 10) -> None:
        self.events = events
        self.thread_id = thread_id

    def GetCurrentThreadId(self) -> int:
        self.events.append(("current_thread",))
        return self.thread_id

    def GetLastError(self) -> int:
        self.events.append(("last_error",))
        return 5


class FakeUser32:
    def __init__(
        self,
        *,
        foreground: int = 100,
        target: int = 200,
        foreground_thread: int = 20,
        target_thread: int = 30,
        minimized: bool = False,
    ) -> None:
        self.events: list[tuple] = []
        self.foreground = foreground
        self.target = target
        self.threads = {foreground: foreground_thread, target: target_thread}
        self.minimized = minimized
        self.valid = True
        self.failed_attach: tuple[int, int] | None = None
        self.failed_detach: set[tuple[int, int]] = set()
        self.set_foreground_result = True
        self.update_foreground = True

    def IsWindow(self, hwnd: int) -> bool:
        self.events.append(("is_window", hwnd))
        return self.valid and hwnd == self.target

    def GetForegroundWindow(self) -> int:
        self.events.append(("foreground",))
        return self.foreground

    def GetWindowThreadProcessId(self, hwnd: int, _pid: object) -> int:
        self.events.append(("window_thread", hwnd))
        return self.threads.get(hwnd, 0)

    def IsIconic(self, hwnd: int) -> bool:
        self.events.append(("is_iconic", hwnd))
        return self.minimized

    def ShowWindow(self, hwnd: int, command: int) -> int:
        self.events.append(("show_window", hwnd, command))
        self.minimized = False
        return 1

    def AttachThreadInput(self, caller: int, other: int, attach: bool) -> bool:
        action = "attach" if attach else "detach"
        self.events.append((action, caller, other))
        pair = (caller, other)
        if attach and pair == self.failed_attach:
            return False
        if not attach and pair in self.failed_detach:
            return False
        return True

    def BringWindowToTop(self, hwnd: int) -> bool:
        self.events.append(("bring_to_top", hwnd))
        return True

    def SetForegroundWindow(self, hwnd: int) -> bool:
        self.events.append(("set_foreground", hwnd))
        if self.set_foreground_result and self.update_foreground:
            self.foreground = hwnd
        return self.set_foreground_result


def activate(user32: FakeUser32):
    return _activate_window_with_api(
        user32.target,
        user32,
        FakeKernel32(user32.events),
    )


class WindowsActivationTests(unittest.TestCase):
    def test_attaches_caller_to_foreground_and_target_then_detaches_in_reverse(self) -> None:
        user32 = FakeUser32()

        result = activate(user32)

        self.assertTrue(result.ok)
        self.assertEqual(
            [event for event in user32.events if event[0] in {"attach", "detach"}],
            [
                ("attach", 10, 20),
                ("attach", 10, 30),
                ("detach", 10, 30),
                ("detach", 10, 20),
            ],
        )
        self.assertLess(
            user32.events.index(("attach", 10, 30)),
            user32.events.index(("bring_to_top", 200)),
        )
        self.assertLess(
            user32.events.index(("set_foreground", 200)),
            user32.events.index(("detach", 10, 30)),
        )

    def test_partial_attach_failure_detaches_every_successful_pair(self) -> None:
        user32 = FakeUser32()
        user32.failed_attach = (10, 30)

        result = activate(user32)

        self.assertFalse(result.ok)
        self.assertEqual(result.code, DRIVER_ERROR)
        self.assertIn("win32 error 5", result.message)
        self.assertEqual(
            [event for event in user32.events if event[0] in {"attach", "detach"}],
            [("attach", 10, 20), ("attach", 10, 30), ("detach", 10, 20)],
        )
        self.assertNotIn(("bring_to_top", 200), user32.events)

    def test_cleanup_attempts_all_detaches_and_reports_failure(self) -> None:
        user32 = FakeUser32()
        user32.failed_detach.add((10, 30))

        result = activate(user32)

        self.assertFalse(result.ok)
        self.assertIn(("detach", 10, 30), user32.events)
        self.assertIn(("detach", 10, 20), user32.events)
        self.assertIn("could not detach input threads", result.message)

    def test_already_foreground_is_idempotent_without_attachment_or_restore(self) -> None:
        user32 = FakeUser32(foreground=200)

        result = activate(user32)

        self.assertTrue(result.ok)
        self.assertEqual(user32.events, [("is_window", 200), ("foreground",)])

    def test_minimized_target_is_restored_before_attachment(self) -> None:
        user32 = FakeUser32(minimized=True)

        result = activate(user32)

        self.assertTrue(result.ok)
        self.assertIn(("show_window", 200, 9), user32.events)
        self.assertLess(
            user32.events.index(("show_window", 200, 9)),
            user32.events.index(("attach", 10, 20)),
        )

    def test_stale_numeric_window_id_fails_before_thread_or_activation_calls(self) -> None:
        user32 = FakeUser32()
        user32.valid = False

        result = activate(user32)

        self.assertFalse(result.ok)
        self.assertEqual(result.code, STALE_ELEMENT)
        self.assertEqual(user32.events, [("is_window", 200)])

    def test_invalid_text_window_id_fails_without_loading_native_apis(self) -> None:
        driver = WindowsDriver.__new__(WindowsDriver)

        result = driver.activate_window("not-an-hwnd")

        self.assertFalse(result.ok)
        self.assertEqual(result.code, DRIVER_ERROR)
        self.assertIn("bad window_id", result.message)

    def test_native_success_without_foreground_postcondition_is_failure(self) -> None:
        user32 = FakeUser32()
        user32.update_foreground = False

        result = activate(user32)

        self.assertFalse(result.ok)
        self.assertEqual(result.code, DRIVER_ERROR)
        self.assertEqual(result.message, "could not bring window to foreground")
        self.assertIn(("detach", 10, 30), user32.events)
        self.assertIn(("detach", 10, 20), user32.events)

    def test_set_foreground_failure_still_detaches_all_pairs(self) -> None:
        user32 = FakeUser32()
        user32.set_foreground_result = False

        result = activate(user32)

        self.assertFalse(result.ok)
        self.assertEqual(result.code, DRIVER_ERROR)
        self.assertEqual(result.message, "SetForegroundWindow failed")
        self.assertIn(("detach", 10, 30), user32.events)
        self.assertIn(("detach", 10, 20), user32.events)


if __name__ == "__main__":
    unittest.main()
