"""Explicitly started Agent Controls host for bounded global shortcuts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .agent_controls import load_agent_controls, render_agent_controls
from .config import DEFAULT_PAUSE_SHORTCUT, load_agent_config, pause_shortcut_virtual_key
from .cooperative_control import LocalCooperativeControl
from .shortcut_broker import (
    CooperativePausePort,
    ShortcutBroker,
    ShortcutEvent,
    render_shortcut_event,
)
from .shortcut_broker_win32 import (
    GlobalShortcutLoop,
    Win32ConsoleForeground,
    Win32GlobalShortcutApi,
)


class ShortcutServiceError(RuntimeError):
    """Fixed service failure without provider, task, or desktop content."""


class ShortcutLoopPort(Protocol):
    def run(
        self,
        broker: ShortcutBroker,
        *,
        on_registered: Callable[[], object] | None = None,
    ) -> int: ...


class ConsoleAgentControlsPresenter:
    """Refresh the strict settings projection in the owning console."""

    def __init__(
        self,
        config_path: Path,
        *,
        foreground: Callable[[], bool],
        output: Callable[[str], object],
    ) -> None:
        if (
            not isinstance(config_path, Path)
            or not callable(foreground)
            or not callable(output)
        ):
            raise ShortcutServiceError("SHORTCUT_PRESENTER_CONFIG_INVALID")
        self._config_path = config_path
        self._foreground = foreground
        self._output = output

    def __call__(self) -> None:
        if not self._foreground():
            raise ShortcutServiceError("AGENT_CONTROLS_FOREGROUND_UNAVAILABLE")
        snapshot = load_agent_controls(self._config_path)
        self._output(
            "\n"
            + render_agent_controls(snapshot)
            + "\n\nSHORTCUT HOST · ACTIVE\n"
        )


def render_shortcut_service_started(
    config_path: Path,
    pause_shortcut: str = DEFAULT_PAUSE_SHORTCUT,
) -> str:
    if not isinstance(config_path, Path) or not config_path.is_absolute():
        raise ShortcutServiceError("SHORTCUT_SERVICE_CONFIG_INVALID")
    pause_key = chr(pause_shortcut_virtual_key(pause_shortcut))
    return "\n".join(
        (
            "SHORTCUTS ACTIVE",
            "  Ctrl+Alt+G: Open Agent Controls",
            f"  Ctrl+Alt+{pause_key}: Request safe pause",
            "  Ctrl+Alt+Q: Emergency stop (independent)",
            "  Global approve: not assigned",
            "  Global resume: not assigned",
            "",
            "A pause request is not desktop authority.",
            "Wait for PAUSED · DESKTOP AUTHORITY RELEASED before local input.",
            f"Configuration: {config_path}",
            "Press Ctrl+C to stop this shortcut host.",
            "",
        )
    )


def _console_output(message: str) -> None:
    print(message, end="", flush=True)


def run_shortcut_service(
    path: Path,
    *,
    loop: ShortcutLoopPort | None = None,
    presenter: Callable[[], object] | None = None,
    control: CooperativePausePort | None = None,
    output: Callable[[str], object] = _console_output,
) -> int:
    """Run one foreground shortcut host without starting an external port."""

    if not isinstance(path, Path) or not callable(output):
        raise ShortcutServiceError("SHORTCUT_SERVICE_CONFIG_INVALID")
    config_path = path.expanduser().resolve(strict=True)
    config = load_agent_config(config_path)

    resolved_control = control or LocalCooperativeControl(
        config.state_dir,
        config.application_state_dir,
    )
    resolved_presenter = presenter
    if resolved_presenter is None:
        foreground = Win32ConsoleForeground()
        resolved_presenter = ConsoleAgentControlsPresenter(
            config_path,
            foreground=foreground.show,
            output=output,
        )

    def publish(event: ShortcutEvent) -> None:
        output(render_shortcut_event(event))

    broker = ShortcutBroker(
        presenter=resolved_presenter,
        control=resolved_control,
        event_sink=publish,
    )
    resolved_loop = loop or GlobalShortcutLoop(
        Win32GlobalShortcutApi(),
        request_pause_virtual_key=pause_shortcut_virtual_key(
            config.operator.pause_shortcut
        ),
    )

    def publish_registered() -> None:
        controls = load_agent_controls(config_path)
        output(render_agent_controls(controls) + "\n\n")
        output(
            render_shortcut_service_started(
                config_path,
                config.operator.pause_shortcut,
            )
        )

    try:
        resolved_loop.run(broker, on_registered=publish_registered)
    except KeyboardInterrupt:
        output("SHORTCUTS STOPPED · Registrations released.\n")
    return 0


__all__ = [
    "ConsoleAgentControlsPresenter",
    "ShortcutLoopPort",
    "ShortcutServiceError",
    "render_shortcut_service_started",
    "run_shortcut_service",
]
