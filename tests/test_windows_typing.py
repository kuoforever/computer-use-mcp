from __future__ import annotations

import pytest

from computer_use_mcp.drivers.windows import WindowsDriver


def test_keyboard_typing_uses_the_configured_visible_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, float]] = []
    monkeypatch.setattr(
        "computer_use_mcp.drivers.windows.auto.SendKeys",
        lambda text, *, waitTime: calls.append((text, waitTime)),
    )
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._type_wait_seconds = 0.035

    result = driver.type("visible")

    assert result.ok
    assert calls == [("visible", 0.035)]


@pytest.mark.parametrize("value", [-0.01, 0.101, float("inf"), True])
def test_keyboard_typing_delay_is_bounded(value: object) -> None:
    with pytest.raises(ValueError, match="between 0 and 0.1"):
        WindowsDriver(type_wait_seconds=value)  # type: ignore[arg-type]


def test_page_navigation_keys_have_standard_windows_virtual_key_codes() -> None:
    assert WindowsDriver._vk("PageUp") == 0x21
    assert WindowsDriver._vk("PageDown") == 0x22
