from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from computer_use_agent.config_init import initialize_agent_config
from computer_use_agent.cooperative_control import (
    ControlBoundary,
    ControlRequestKind,
    ControlStatus,
    CooperativeControlSnapshot,
    DesktopControlAuthority,
)
from computer_use_agent.shortcut_broker import ShortcutAction
from computer_use_agent.shortcut_service import (
    ConsoleAgentControlsPresenter,
    ShortcutServiceError,
    run_shortcut_service,
)


def _config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    pause_shortcut: str = "ctrl+alt+p",
) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    executable = tmp_path / "guarded-desktop-mcp.exe"
    executable.write_bytes(b"")
    path = tmp_path / "agent.toml"
    initialize_agent_config(
        profile="desktop-ask",
        provider="openai",
        model="reviewed-model",
        output=path,
        mcp_executable=executable,
        pause_shortcut=pause_shortcut,
    )
    return path


def _requested() -> CooperativeControlSnapshot:
    return CooperativeControlSnapshot(
        run_id="run-1",
        owner_token_digest="a" * 64,
        runner_state_path="runs/run-1",
        sequence=2,
        status=ControlStatus.PAUSE_REQUESTED,
        request_kind=ControlRequestKind.PAUSE,
        request_id="request-1",
        authority=DesktopControlAuthority.AGENT,
        fresh_observation_required=False,
        boundary=None,
        checkpoint_sequence=None,
        outcome=None,
        created_at="2026-08-08T00:00:00+00:00",
        updated_at="2026-08-08T00:00:01+00:00",
    )


class _Control:
    def request_pause(
        self,
        kind: ControlRequestKind,
        *,
        run_id: str | None = None,
    ) -> CooperativeControlSnapshot:
        assert kind is ControlRequestKind.PAUSE
        assert run_id is None
        return _requested()

    def read(self, run_id: str) -> CooperativeControlSnapshot:
        assert run_id == "run-1"
        return replace(
            _requested(),
            sequence=3,
            status=ControlStatus.PAUSED,
            authority=DesktopControlAuthority.RELEASED,
            fresh_observation_required=True,
            boundary=ControlBoundary.BEFORE_PROVIDER,
            checkpoint_sequence=4,
            updated_at="2026-08-08T00:00:02+00:00",
        )


class _Loop:
    def run(self, broker, *, on_registered=None) -> int:  # noqa: ANN001
        assert on_registered is not None
        on_registered()
        broker.handle(ShortcutAction.OPEN_CONTROLS)
        broker.handle(ShortcutAction.REQUEST_PAUSE)
        broker.poll()
        return 3


def test_service_composes_controls_pause_request_and_released_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-rendered")
    path = _config(tmp_path, monkeypatch)
    output: list[str] = []
    presented: list[str] = []

    assert (
        run_shortcut_service(
            path,
            loop=_Loop(),
            presenter=lambda: presented.append("controls"),
            control=_Control(),
            output=output.append,
        )
        == 0
    )

    rendered = "".join(output)
    assert presented == ["controls"]
    assert "SHORTCUTS ACTIVE" in rendered
    assert "Global approve: not assigned" in rendered
    assert "Global resume: not assigned" in rendered
    assert "PAUSE REQUESTED" in rendered
    assert "PAUSED RELEASED" in rendered
    assert rendered.index("PAUSE REQUESTED") < rendered.index("PAUSED RELEASED")
    assert "must-not-be-rendered" not in rendered


def test_service_handles_keyboard_interrupt_as_clean_local_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _config(tmp_path, monkeypatch)
    output: list[str] = []

    class InterruptedLoop:
        def run(self, _broker, *, on_registered=None) -> int:  # noqa: ANN001
            assert on_registered is not None
            on_registered()
            raise KeyboardInterrupt

    assert (
        run_shortcut_service(
            path,
            loop=InterruptedLoop(),
            presenter=lambda: None,
            control=_Control(),
            output=output.append,
        )
        == 0
    )
    assert "SHORTCUTS STOPPED · Registrations released." in "".join(output)


def test_service_never_reports_active_before_registration_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _config(tmp_path, monkeypatch)
    output: list[str] = []

    class ConflictingLoop:
        def run(self, _broker, *, on_registered=None) -> int:  # noqa: ANN001
            assert on_registered is not None
            raise ShortcutServiceError("SHORTCUT_CONFLICT_OPEN_CONTROLS")

    with pytest.raises(ShortcutServiceError, match="SHORTCUT_CONFLICT_OPEN_CONTROLS"):
        run_shortcut_service(
            path,
            loop=ConflictingLoop(),
            presenter=lambda: None,
            control=_Control(),
            output=output.append,
        )

    assert "SHORTCUTS ACTIVE" not in "".join(output)


def test_console_presenter_requires_foreground_before_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _config(tmp_path, monkeypatch)
    output: list[str] = []
    presenter = ConsoleAgentControlsPresenter(
        path,
        foreground=lambda: False,
        output=output.append,
    )

    with pytest.raises(ShortcutServiceError, match="FOREGROUND_UNAVAILABLE"):
        presenter()

    assert output == []


def test_console_presenter_reloads_same_strict_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _config(tmp_path, monkeypatch)
    output: list[str] = []
    presenter = ConsoleAgentControlsPresenter(
        path,
        foreground=lambda: True,
        output=output.append,
    )

    presenter()

    assert "AGENT CONTROLS" in "".join(output)
    assert "SHORTCUT HOST · ACTIVE" in "".join(output)
    assert "reviewed-model" in "".join(output)


def test_service_passes_configured_pause_key_to_concrete_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _config(tmp_path, monkeypatch, pause_shortcut="ctrl+alt+k")
    output: list[str] = []
    captured: dict[str, object] = {}

    class ConcreteLoop:
        def __init__(self, api: object, *, request_pause_virtual_key: int) -> None:
            captured["api"] = api
            captured["virtual_key"] = request_pause_virtual_key

        def run(self, _broker, *, on_registered=None) -> int:  # noqa: ANN001
            assert on_registered is not None
            on_registered()
            return 0

    api = object()
    monkeypatch.setattr(
        "computer_use_agent.shortcut_service.Win32GlobalShortcutApi",
        lambda: api,
    )
    monkeypatch.setattr(
        "computer_use_agent.shortcut_service.GlobalShortcutLoop",
        ConcreteLoop,
    )

    assert (
        run_shortcut_service(
            path,
            presenter=lambda: None,
            control=_Control(),
            output=output.append,
        )
        == 0
    )

    assert captured == {"api": api, "virtual_key": ord("K")}
    assert "Ctrl+Alt+K: Request safe pause" in "".join(output)
