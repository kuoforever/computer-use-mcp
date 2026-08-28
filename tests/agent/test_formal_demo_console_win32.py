from __future__ import annotations

import ast
import ctypes
import sys
from ctypes import wintypes
from dataclasses import fields
from pathlib import Path

import pytest

import computer_use_agent.formal_demo_console_win32 as win32_module
from computer_use_agent.formal_demo_console import (
    FormalDemoConsoleCallbacks,
    FormalDemoConsoleError,
    FormalDemoConsoleSession,
    FormalDemoConsoleStage,
    FormalDemoConsoleWindow,
    build_console_route,
)
from computer_use_agent.formal_demo_console_win32 import (
    Win32FormalDemoConsoleApi,
    _bounded_window_at,
    _bounded_window_rect,
    _client_size,
    _layout_rects,
)
from computer_use_agent.operator_accessibility import OperatorAccessibilitySettings


def _destroy_and_dispose(api: Win32FormalDemoConsoleApi, hwnd: int) -> None:
    try:
        api.destroy(hwnd)
    finally:
        api.dispose()


@pytest.mark.parametrize("dpi", (96, 120, 144, 192))
@pytest.mark.parametrize("text_scale", (1.0, 2.0, 4.0))
def test_layout_keeps_every_control_inside_the_client(
    dpi: int,
    text_scale: float,
) -> None:
    width, height = _client_size(dpi, text_scale)
    layout = _layout_rects(width, height, dpi, text_scale_factor=text_scale)

    for field in fields(layout):
        rect = getattr(layout, field.name)
        x, y, rect_width, rect_height = rect
        assert x >= 0
        assert y >= 0
        assert rect_width > 0
        assert rect_height > 0
        assert x + rect_width <= width
        assert y + rect_height <= height


def test_layout_rejects_unusable_client() -> None:
    with pytest.raises(ValueError, match="FORMAL_DEMO_CONSOLE_LAYOUT_TOO_SMALL"):
        _layout_rects(200, 200, 96, text_scale_factor=1.0)


def test_large_requested_window_is_bounded_to_the_work_area() -> None:
    assert _bounded_window_rect(1960, 1560, (0, 40, 1920, 1040)) == (
        0,
        40,
        1920,
        1000,
    )
    assert _bounded_window_at(
        -1800,
        100,
        1400,
        900,
        (-1920, 0, 0, 1080),
    ) == (-1800, 100, 1400, 900)


def test_work_area_sized_layout_keeps_400_percent_controls_reachable() -> None:
    layout = _layout_rects(1920, 1000, 96, text_scale_factor=4.0)

    for field in fields(layout):
        x, y, width, height = getattr(layout, field.name)
        assert x >= 0
        assert y >= 0
        assert x + width <= 1920
        assert y + height <= 1000


def test_native_start_is_structurally_disabled_and_absent_from_tab_order() -> None:
    source = Path(win32_module.__file__ or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "_WS_DISABLED | _BS_PUSHBUTTON" in source
    assert "on_start" not in source
    assert "BS_DEFPUSHBUTTON" not in source
    assert "RegisterHotKey" not in source
    assert "BlockInput" not in source
    assert "ClipCursor" not in source
    assert "SetForegroundWindow" not in source
    assert "_START_BUTTON_ID: callbacks" not in source

    methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not ({"start", "dispatch", "consume", "request", "send"} & methods)

def test_native_backend_has_no_provider_runtime_or_persistence_wiring() -> None:
    source = Path(win32_module.__file__ or "").read_text(encoding="utf-8")
    for value in (
        "provider_factory",
        "computer_use_agent.providers",
        "AgentRunner",
        "StdioDesktopMCP",
        "WindowsDriver",
        "compile_task_intent_once",
        "formal_demo_intent_request",
        ".consume(",
        "os.environ",
        "getenv",
        "socket",
        "subprocess",
        "pathlib",
        "open(",
    ):
        assert value not in source


@pytest.mark.skipif(sys.platform != "win32", reason="native ABI contract")
def test_native_pointer_apis_have_explicit_64_bit_prototypes() -> None:
    api = Win32FormalDemoConsoleApi()
    try:
        assert api._user32.LoadCursorW.argtypes is not None
        assert api._user32.LoadCursorW.restype is wintypes.HANDLE
        for name in (
            "CreateWindowExW",
            "DestroyWindow",
            "SetFocus",
            "GetMessageW",
            "DispatchMessageW",
            "MoveWindow",
            "GetClientRect",
            "GetWindowTextW",
            "SetWindowTextW",
            "UnregisterClassW",
        ):
            assert getattr(api._user32, name).argtypes is not None
        assert ctypes.sizeof(api._user32.LoadCursorW.restype) == ctypes.sizeof(
            ctypes.c_void_p
        )
    finally:
        api.dispose()


@pytest.mark.skipif(sys.platform != "win32", reason="native hidden-window contract")
@pytest.mark.parametrize(
    ("dpi", "text_scale", "work_area"),
    (
        (192, 1.0, (0, 0, 1366, 728)),
        (96, 4.0, (0, 0, 1366, 728)),
        (96, 4.0, (0, 0, 1536, 824)),
    ),
)
def test_hidden_native_initial_layout_matches_dpi_and_bounded_work_area(
    dpi: int,
    text_scale: float,
    work_area: tuple[int, int, int, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = Win32FormalDemoConsoleApi(
        accessibility=OperatorAccessibilitySettings(text_scale_factor=text_scale)
    )
    monkeypatch.setattr(api, "_system_dpi", lambda: dpi)
    monkeypatch.setattr(api, "_dpi", lambda _hwnd: dpi)
    monkeypatch.setattr(api, "_work_area", lambda: work_area)
    monkeypatch.setattr(api, "_monitor_work_area_for_window", lambda _hwnd: work_area)
    callbacks = FormalDemoConsoleCallbacks(
        on_review=lambda: None,
        on_acknowledge=lambda: None,
        on_reset=lambda: None,
        on_cancel=lambda: None,
    )
    hwnd = api.create(title="hidden dpi seam", callbacks=callbacks)
    try:
        window = wintypes.RECT()
        cancel = wintypes.RECT()
        assert api._user32.GetWindowRect(
            wintypes.HWND(hwnd), ctypes.byref(window)
        )
        assert api._user32.GetWindowRect(
            wintypes.HWND(api._controls[hwnd].cancel_button),
            ctypes.byref(cancel),
        )
        left, top, right, bottom = work_area
        assert left <= window.left < window.right <= right
        assert top <= window.top < window.bottom <= bottom
        assert window.left <= cancel.left < cancel.right <= window.right
        assert window.top <= cancel.top < cancel.bottom <= window.bottom
    finally:
        _destroy_and_dispose(api, hwnd)


@pytest.mark.skipif(sys.platform != "win32", reason="native hidden-window contract")
def test_hidden_native_dpi_change_preserves_secondary_origin_and_rebuilds_font(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = Win32FormalDemoConsoleApi()
    work_area = (-1920, 0, 0, 1080)
    monkeypatch.setattr(
        api,
        "_monitor_work_area_for_rect",
        lambda _rect: work_area,
    )
    monkeypatch.setattr(
        api,
        "_monitor_work_area_for_window",
        lambda _hwnd: work_area,
    )
    callbacks = FormalDemoConsoleCallbacks(
        on_review=lambda: None,
        on_acknowledge=lambda: None,
        on_reset=lambda: None,
        on_cancel=lambda: None,
    )
    hwnd = api.create(title="hidden dpi change", callbacks=callbacks)
    try:
        previous_font = api._fonts[hwnd]
        suggested = wintypes.RECT(-1800, 100, -400, 1000)
        dpi = 192
        api._user32.SendMessageW(
            wintypes.HWND(hwnd),
            0x02E0,
            dpi | (dpi << 16),
            ctypes.addressof(suggested),
        )
        assert api._user32.IsWindow(wintypes.HWND(hwnd))
        assert api._dpi(hwnd) == dpi
        assert api._fonts[hwnd] != previous_font
        window = wintypes.RECT()
        assert api._user32.GetWindowRect(
            wintypes.HWND(hwnd), ctypes.byref(window)
        )
        left, top, right, bottom = work_area
        assert left <= window.left < window.right <= right
        assert top <= window.top < window.bottom <= bottom
        assert window.left < 0 and window.right <= 0
        cancel = wintypes.RECT()
        assert api._user32.GetWindowRect(
            wintypes.HWND(api._controls[hwnd].cancel_button),
            ctypes.byref(cancel),
        )
        assert window.left <= cancel.left < cancel.right <= window.right
        assert window.top <= cancel.top < cancel.bottom <= window.bottom
    finally:
        _destroy_and_dispose(api, hwnd)


@pytest.mark.skipif(sys.platform != "win32", reason="native glyph contract")
def test_hidden_400_percent_fixed_copy_fits_real_native_font(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = Win32FormalDemoConsoleApi(
        accessibility=OperatorAccessibilitySettings(text_scale_factor=4.0)
    )
    monkeypatch.setattr(api, "_system_dpi", lambda: 96)
    monkeypatch.setattr(api, "_dpi", lambda _hwnd: 96)
    monkeypatch.setattr(api, "_work_area", lambda: (0, 0, 1366, 728))
    monkeypatch.setattr(
        api,
        "_monitor_work_area_for_window",
        lambda _hwnd: (0, 0, 1366, 728),
    )
    callbacks = FormalDemoConsoleCallbacks(
        on_review=lambda: None,
        on_acknowledge=lambda: None,
        on_reset=lambda: None,
        on_cancel=lambda: None,
    )
    hwnd = api.create(title="hidden glyph seam", callbacks=callbacks)
    try:
        controls = api._controls[hwnd]
        user32 = api._user32
        gdi32 = api._gdi32
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.ReleaseDC.restype = ctypes.c_int
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.GetTextExtentPoint32W.argtypes = [
            wintypes.HDC,
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(wintypes.SIZE),
        ]
        gdi32.GetTextExtentPoint32W.restype = wintypes.BOOL
        dc = user32.GetDC(wintypes.HWND(hwnd))
        assert dc
        previous = gdi32.SelectObject(dc, wintypes.HGDIOBJ(api._fonts[hwnd]))
        try:
            fixed_copy = (
                controls.mode,
                controls.task_label,
                controls.review_button,
                controls.reset_button,
                controls.detail_label,
                controls.ack_label,
                controls.ack_button,
                controls.start_button,
                controls.cancel_button,
            )
            button_handles = {
                controls.review_button,
                controls.reset_button,
                controls.ack_button,
                controls.start_button,
                controls.cancel_button,
            }
            for control in fixed_copy:
                text = api._read_text(control)
                extent = wintypes.SIZE()
                assert gdi32.GetTextExtentPoint32W(
                    dc,
                    text,
                    len(text),
                    ctypes.byref(extent),
                )
                client = wintypes.RECT()
                assert user32.GetClientRect(
                    wintypes.HWND(control), ctypes.byref(client)
                )
                assert client.bottom - client.top >= extent.cy
                padding = 16 if control in button_handles else 0
                assert client.right - client.left >= extent.cx + padding, (
                    text,
                    client.right - client.left,
                    extent.cx + padding,
                )
        finally:
            gdi32.SelectObject(dc, previous)
            assert user32.ReleaseDC(wintypes.HWND(hwnd), dc)
    finally:
        _destroy_and_dispose(api, hwnd)


@pytest.mark.skipif(sys.platform != "win32", reason="native hidden-window contract")
def test_hidden_native_window_keeps_start_disabled_and_inert() -> None:
    callbacks_seen: list[str] = []
    api = Win32FormalDemoConsoleApi()
    session = FormalDemoConsoleSession(
        build_console_route(provider_id="openai", model_id="gpt-reviewed"),
        identity_factory=lambda: "native-hidden-smoke",
    )
    callbacks = FormalDemoConsoleCallbacks(
        on_review=lambda: callbacks_seen.append("review"),
        on_acknowledge=lambda: callbacks_seen.append("acknowledge"),
        on_reset=lambda: callbacks_seen.append("reset"),
        on_cancel=lambda: callbacks_seen.append("cancel"),
    )
    hwnd = api.create(title="hidden native review", callbacks=callbacks)
    try:
        api.apply(hwnd, session.view())
        assert not api.start_control_enabled(hwnd)
        start = api._controls[hwnd].start_button
        api._user32.SendMessageW(wintypes.HWND(start), 0x00F5, 0, 0)  # BM_CLICK
        assert callbacks_seen == []
        assert not api.start_control_enabled(hwnd)
    finally:
        _destroy_and_dispose(api, hwnd)


@pytest.mark.skipif(sys.platform != "win32", reason="native hidden-window contract")
def test_hidden_native_tab_order_and_child_escape_use_real_window_state() -> None:
    callbacks_seen: list[str] = []
    api = Win32FormalDemoConsoleApi()
    session = FormalDemoConsoleSession(
        build_console_route(provider_id="openai", model_id="gpt-reviewed"),
        identity_factory=lambda: "native-keyboard-smoke",
    )
    callbacks = FormalDemoConsoleCallbacks(
        on_review=lambda: callbacks_seen.append("review"),
        on_acknowledge=lambda: callbacks_seen.append("acknowledge"),
        on_reset=lambda: callbacks_seen.append("reset"),
        on_cancel=lambda: callbacks_seen.append("cancel"),
    )
    hwnd = api.create(title="hidden native keyboard", callbacks=callbacks)
    try:
        api.apply(hwnd, session.view())
        controls = api._controls[hwnd]
        api._user32.SetFocus(wintypes.HWND(controls.task_edit))
        assert int(api._user32.GetFocus() or 0) == controls.task_edit
        expected_focus = (
            controls.review_button,
            controls.reset_button,
            controls.cancel_button,
            controls.task_edit,
        )
        current = controls.task_edit
        for expected in expected_focus:
            tab = wintypes.MSG()
            tab.hWnd = wintypes.HWND(current)
            tab.message = 0x0100  # WM_KEYDOWN
            tab.wParam = 0x09  # VK_TAB
            assert api._route_message(hwnd, tab)
            assert int(api._user32.GetFocus() or 0) == expected
            assert expected != controls.start_button
            current = expected

        message = wintypes.MSG()
        message.hWnd = wintypes.HWND(controls.task_edit)
        message.message = 0x0100  # WM_KEYDOWN
        message.wParam = 0x1B  # VK_ESCAPE
        assert api._route_message(hwnd, message)
        assert callbacks_seen == ["cancel"]
    finally:
        _destroy_and_dispose(api, hwnd)


@pytest.mark.skipif(sys.platform != "win32", reason="native hidden-window contract")
def test_hidden_native_resize_minimize_and_high_text_work_area_are_safe() -> None:
    api = Win32FormalDemoConsoleApi(
        accessibility=OperatorAccessibilitySettings(text_scale_factor=4.0)
    )
    session = FormalDemoConsoleSession(
        build_console_route(provider_id="openai", model_id="gpt-reviewed"),
        identity_factory=lambda: "native-layout-smoke",
    )
    callbacks = FormalDemoConsoleCallbacks(
        on_review=lambda: None,
        on_acknowledge=lambda: None,
        on_reset=lambda: None,
        on_cancel=lambda: None,
    )
    hwnd = api.create(title="hidden native layout", callbacks=callbacks)
    try:
        api.apply(hwnd, session.view())
        window = wintypes.RECT()
        assert api._user32.GetWindowRect(
            wintypes.HWND(hwnd), ctypes.byref(window)
        )
        left, top, right, bottom = api._work_area()
        assert left <= window.left < window.right <= right
        assert top <= window.top < window.bottom <= bottom

        assert api._user32.MoveWindow(wintypes.HWND(hwnd), 0, 0, 300, 300, True)
        window = wintypes.RECT()
        cancel = wintypes.RECT()
        assert api._user32.GetWindowRect(
            wintypes.HWND(hwnd), ctypes.byref(window)
        )
        assert api._user32.GetWindowRect(
            wintypes.HWND(api._controls[hwnd].cancel_button),
            ctypes.byref(cancel),
        )
        assert window.left <= cancel.left < cancel.right <= window.right
        assert window.top <= cancel.top < cancel.bottom <= window.bottom
        api._user32.SendMessageW(wintypes.HWND(hwnd), 0x0005, 1, 0)  # minimized
        assert api._user32.IsWindow(wintypes.HWND(hwnd))
        assert not api.start_control_enabled(hwnd)
    finally:
        _destroy_and_dispose(api, hwnd)


@pytest.mark.skipif(sys.platform != "win32", reason="native hidden-window contract")
def test_hidden_destroy_does_not_poison_the_next_message_loop() -> None:
    api = Win32FormalDemoConsoleApi()
    callbacks = FormalDemoConsoleCallbacks(
        on_review=lambda: None,
        on_acknowledge=lambda: None,
        on_reset=lambda: None,
        on_cancel=lambda: None,
    )
    try:
        first = api.create(title="first hidden lifecycle", callbacks=callbacks)
        api.destroy(first)

        holder: dict[str, int] = {}
        closing_callbacks = FormalDemoConsoleCallbacks(
            on_review=lambda: None,
            on_acknowledge=lambda: None,
            on_reset=lambda: None,
            on_cancel=lambda: api.destroy(holder["hwnd"]),
        )
        second = api.create(
            title="second hidden lifecycle", callbacks=closing_callbacks
        )
        holder["hwnd"] = second
        assert api._user32.PostMessageW(wintypes.HWND(second), 0x0010, 0, 0)

        assert api.run(second) == 0
        assert not api._user32.IsWindow(wintypes.HWND(second))
    finally:
        api.dispose()


@pytest.mark.skipif(sys.platform != "win32", reason="native hidden-window contract")
def test_native_callback_fault_is_fixed_and_clears_sensitive_session() -> None:
    secret = "native-callback-secret"
    api = Win32FormalDemoConsoleApi()
    session = FormalDemoConsoleSession(
        build_console_route(provider_id="openai", model_id="gpt-reviewed"),
        identity_factory=lambda: "native-fault",
    )
    session.review(f"Review {secret}.")
    window = FormalDemoConsoleWindow(session, api)
    hwnd = window.open()

    def fail_read(_hwnd: int) -> str:
        raise RuntimeError(secret)

    api.read_task = fail_read  # type: ignore[method-assign]
    try:
        assert api._user32.PostMessageW(
            wintypes.HWND(hwnd),
            0x0111,  # WM_COMMAND
            1003,  # Review button / BN_CLICKED
            0,
        )
        with pytest.raises(
            FormalDemoConsoleError,
            match="^FORMAL_DEMO_CONSOLE_WINDOW_FAILED$",
        ) as caught:
            window.run()
        assert secret not in str(caught.value)
        cleared = session.view()
        assert cleared.stage is FormalDemoConsoleStage.CANCELLED
        assert cleared.task_text == ""
        assert cleared.disclosure_text == ""
    finally:
        window.close()
        api.dispose()


@pytest.mark.skipif(sys.platform != "win32", reason="native hidden-window contract")
def test_repeated_native_adapter_disposal_releases_registered_classes() -> None:
    for _index in range(3):
        api = Win32FormalDemoConsoleApi()
        callbacks = FormalDemoConsoleCallbacks(
            on_review=lambda: None,
            on_acknowledge=lambda: None,
            on_reset=lambda: None,
            on_cancel=lambda: None,
        )
        hwnd = api.create(title="hidden dispose", callbacks=callbacks)
        api.destroy(hwnd)
        api.dispose()
        api.dispose()
        assert api._disposed
        assert not api._class_registered


@pytest.mark.skipif(sys.platform != "win32", reason="native hidden-window contract")
def test_hidden_native_buttons_reach_only_review_and_local_scope_compile() -> None:
    api = Win32FormalDemoConsoleApi()
    session = FormalDemoConsoleSession(
        build_console_route(provider_id="openai", model_id="gpt-reviewed"),
        identity_factory=lambda: "native-hidden-flow",
    )
    holder: dict[str, int] = {}

    def review() -> None:
        hwnd = holder["hwnd"]
        api.apply(hwnd, session.review(api.read_task(hwnd)))

    def acknowledge() -> None:
        hwnd = holder["hwnd"]
        api.apply(hwnd, session.acknowledge(api.read_acknowledgement(hwnd)))

    callbacks = FormalDemoConsoleCallbacks(
        on_review=review,
        on_acknowledge=acknowledge,
        on_reset=lambda: None,
        on_cancel=lambda: None,
    )
    hwnd = api.create(title="hidden native flow", callbacks=callbacks)
    holder["hwnd"] = hwnd
    try:
        controls = api._controls[hwnd]
        api.apply(hwnd, session.view())
        api._set_text(controls.task_edit, "Review this hidden local task.")
        api._user32.SetFocus(wintypes.HWND(controls.review_button))
        api._user32.SendMessageW(
            wintypes.HWND(controls.review_button), 0x00F5, 0, 0
        )
        assert session.stage is FormalDemoConsoleStage.DISCLOSURE_READY
        assert int(api._user32.GetFocus() or 0) == controls.ack_edit
        assert not api.start_control_enabled(hwnd)

        api._set_text(controls.ack_edit, "COMPILE")
        api._user32.SetFocus(wintypes.HWND(controls.ack_button))
        api._user32.SendMessageW(
            wintypes.HWND(controls.ack_button), 0x00F5, 0, 0
        )
        assert session.stage is FormalDemoConsoleStage.SCOPE_READY
        assert int(api._user32.GetFocus() or 0) == controls.reset_button
        detail = api._read_text(controls.detail_edit)
        assert "Formal Demo Scope Sheet - Host compiled locally" in detail
        assert "START: unavailable" in detail
        assert not api.start_control_enabled(hwnd)
    finally:
        _destroy_and_dispose(api, hwnd)
