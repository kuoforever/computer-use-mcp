from __future__ import annotations

import pytest

from computer_use_agent.operator_personalization import (
    OperatorTheme,
    resolve_operator_theme,
)


def test_explicit_theme_never_reads_windows_preference() -> None:
    def unexpected() -> OperatorTheme:
        raise AssertionError("explicit theme must not read system state")

    assert resolve_operator_theme("dark", system_loader=unexpected) is OperatorTheme.DARK
    assert resolve_operator_theme("light", system_loader=unexpected) is OperatorTheme.LIGHT


def test_auto_theme_uses_strict_system_result() -> None:
    assert resolve_operator_theme(
        "auto",
        system_loader=lambda: OperatorTheme.LIGHT,
    ) is OperatorTheme.LIGHT


@pytest.mark.parametrize(
    "loader",
    [
        lambda: None,
        lambda: "light",
        lambda: (_ for _ in ()).throw(OSError("unavailable")),
    ],
)
def test_auto_theme_fails_silently_to_legacy_dark(loader: object) -> None:
    assert resolve_operator_theme(
        "auto",
        system_loader=loader,  # type: ignore[arg-type]
    ) is OperatorTheme.DARK


@pytest.mark.parametrize("value", ["system", "auto ", "LIGHT", "", 1, True])
def test_theme_preference_is_strict(value: object) -> None:
    with pytest.raises(ValueError, match="OPERATOR_THEME_INVALID"):
        resolve_operator_theme(value)  # type: ignore[arg-type]
