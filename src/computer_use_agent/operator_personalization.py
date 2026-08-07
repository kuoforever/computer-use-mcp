"""Strict, presentation-only operator theme preference resolution."""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum


class OperatorTheme(str, Enum):
    DARK = "dark"
    LIGHT = "light"


ThemePreference = str


def _system_theme() -> OperatorTheme:
    """Read the current Windows application theme or raise to the caller."""

    import winreg

    path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
        value, value_type = winreg.QueryValueEx(key, "AppsUseLightTheme")
    if (
        value_type != winreg.REG_DWORD
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value not in {0, 1}
    ):
        raise OSError("OPERATOR_SYSTEM_THEME_INVALID")
    return OperatorTheme.LIGHT if value == 1 else OperatorTheme.DARK


def resolve_operator_theme(
    preference: ThemePreference,
    *,
    system_loader: Callable[[], OperatorTheme] | None = None,
) -> OperatorTheme:
    """Resolve ``dark``/``light``/``auto`` without opening a native surface."""

    if not isinstance(preference, str) or preference not in {"dark", "light", "auto"}:
        raise ValueError("OPERATOR_THEME_INVALID")
    if preference != "auto":
        return OperatorTheme(preference)
    loader = _system_theme if system_loader is None else system_loader
    try:
        theme = loader()
        if not isinstance(theme, OperatorTheme):
            raise TypeError("OPERATOR_SYSTEM_THEME_INVALID")
        return theme
    except Exception:
        return OperatorTheme.DARK


__all__ = ["OperatorTheme", "ThemePreference", "resolve_operator_theme"]
