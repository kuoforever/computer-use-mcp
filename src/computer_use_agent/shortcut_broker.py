"""No-authority shortcut routing over presentation and cooperative control.

The broker accepts exactly two intents: refresh the local Agent Controls
presentation and request an ordinary cooperative pause.  It cannot approve,
resume, retry, replay, dispatch, or replace the independent MCP emergency-stop
poller.  A pause request is never presented as released authority until the
existing strict control record says both ``paused`` and ``released``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from .cooperative_control import (
    ControlRequestKind,
    ControlStatus,
    CooperativeControlSnapshot,
    DesktopControlAuthority,
)
from .types import JSONValue


SHORTCUT_BROKER_VERSION = 1


class ShortcutBrokerError(RuntimeError):
    """Fixed broker-contract failure without desktop or task content."""


class ShortcutAction(str, Enum):
    OPEN_CONTROLS = "open_controls"
    REQUEST_PAUSE = "request_pause"


class ShortcutEventState(str, Enum):
    CONTROLS_OPENED = "controls_opened"
    CONTROLS_UNAVAILABLE = "controls_unavailable"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED_RELEASED = "paused_released"
    PAUSE_UNAVAILABLE = "pause_unavailable"


_MESSAGES = {
    ShortcutEventState.CONTROLS_OPENED: "Agent Controls opened.",
    ShortcutEventState.CONTROLS_UNAVAILABLE: "Agent Controls are unavailable.",
    ShortcutEventState.PAUSE_REQUESTED: (
        "Pause requested. Wait before touching the shared desktop."
    ),
    ShortcutEventState.PAUSED_RELEASED: (
        "Paused. Desktop authority is released for local use."
    ),
    ShortcutEventState.PAUSE_UNAVAILABLE: (
        "Safe pause is unavailable. Do not assume desktop authority was released."
    ),
}


@dataclass(frozen=True)
class ShortcutEvent:
    """One fixed, content-free operator result."""

    action: ShortcutAction
    state: ShortcutEventState
    run_id: str | None = None
    desktop_authority_released: bool = False
    shortcut_broker_version: int = SHORTCUT_BROKER_VERSION

    def __post_init__(self) -> None:
        if (
            self.shortcut_broker_version != SHORTCUT_BROKER_VERSION
            or not isinstance(self.action, ShortcutAction)
            or not isinstance(self.state, ShortcutEventState)
            or (self.run_id is not None and not isinstance(self.run_id, str))
            or not isinstance(self.desktop_authority_released, bool)
        ):
            raise ShortcutBrokerError("SHORTCUT_EVENT_INVALID")
        if self.desktop_authority_released != (
            self.state is ShortcutEventState.PAUSED_RELEASED
        ):
            raise ShortcutBrokerError("SHORTCUT_EVENT_INVALID")
        if self.action is ShortcutAction.OPEN_CONTROLS:
            valid = self.state in {
                ShortcutEventState.CONTROLS_OPENED,
                ShortcutEventState.CONTROLS_UNAVAILABLE,
            } and self.run_id is None
        else:
            valid = self.state in {
                ShortcutEventState.PAUSE_REQUESTED,
                ShortcutEventState.PAUSED_RELEASED,
                ShortcutEventState.PAUSE_UNAVAILABLE,
            }
            if self.state in {
                ShortcutEventState.PAUSE_REQUESTED,
                ShortcutEventState.PAUSED_RELEASED,
            }:
                valid = valid and self.run_id is not None
            if self.state is ShortcutEventState.PAUSE_UNAVAILABLE:
                valid = valid and self.run_id is None
        if not valid:
            raise ShortcutBrokerError("SHORTCUT_EVENT_INVALID")

    @property
    def message(self) -> str:
        return _MESSAGES[self.state]

    def as_json(self) -> dict[str, JSONValue]:
        return {
            "shortcut_broker_version": self.shortcut_broker_version,
            "action": self.action.value,
            "state": self.state.value,
            "message": self.message,
            "run_id": self.run_id,
            "desktop_authority_released": self.desktop_authority_released,
            "authority": {
                "can_approve": False,
                "can_dispatch": False,
                "can_resume": False,
            },
        }


class CooperativePausePort(Protocol):
    def request_pause(
        self,
        kind: ControlRequestKind,
        *,
        run_id: str | None = None,
    ) -> CooperativeControlSnapshot: ...

    def read(self, run_id: str) -> CooperativeControlSnapshot: ...


class ShortcutBroker:
    """Route two bounded shortcut intents without owning runtime authority."""

    def __init__(
        self,
        *,
        presenter: Callable[[], object],
        control: CooperativePausePort,
        event_sink: Callable[[ShortcutEvent], object],
    ) -> None:
        if not callable(presenter) or not callable(event_sink):
            raise ShortcutBrokerError("SHORTCUT_BROKER_CONFIG_INVALID")
        if not callable(getattr(control, "request_pause", None)) or not callable(
            getattr(control, "read", None)
        ):
            raise ShortcutBrokerError("SHORTCUT_BROKER_CONFIG_INVALID")
        self._presenter = presenter
        self._control = control
        self._event_sink = event_sink
        self._pending_run_id: str | None = None

    @property
    def pending_run_id(self) -> str | None:
        return self._pending_run_id

    def _emit(
        self,
        action: ShortcutAction,
        state: ShortcutEventState,
        *,
        run_id: str | None = None,
        released: bool = False,
    ) -> None:
        self._event_sink(
            ShortcutEvent(
                action=action,
                state=state,
                run_id=run_id,
                desktop_authority_released=released,
            )
        )

    def handle(self, action: ShortcutAction) -> None:
        if not isinstance(action, ShortcutAction):
            raise ShortcutBrokerError("SHORTCUT_ACTION_INVALID")
        if action is ShortcutAction.OPEN_CONTROLS:
            try:
                self._presenter()
            except Exception:
                self._emit(action, ShortcutEventState.CONTROLS_UNAVAILABLE)
            else:
                self._emit(action, ShortcutEventState.CONTROLS_OPENED)
            return
        if self._pending_run_id is not None:
            self.poll()
            return
        try:
            snapshot = self._control.request_pause(ControlRequestKind.PAUSE)
        except Exception:
            self._pause_unavailable()
            return
        self._project_pause(snapshot)

    def poll(self) -> None:
        run_id = self._pending_run_id
        if run_id is None:
            return
        try:
            snapshot = self._control.read(run_id)
        except Exception:
            self._pause_unavailable()
            return
        self._project_pause(snapshot)

    def _project_pause(self, snapshot: CooperativeControlSnapshot) -> None:
        if not isinstance(snapshot, CooperativeControlSnapshot):
            self._pause_unavailable()
            return
        if (
            snapshot.status is ControlStatus.PAUSE_REQUESTED
            and snapshot.authority is DesktopControlAuthority.AGENT
            and snapshot.request_kind is ControlRequestKind.PAUSE
        ):
            if self._pending_run_id is None:
                self._pending_run_id = snapshot.run_id
                self._emit(
                    ShortcutAction.REQUEST_PAUSE,
                    ShortcutEventState.PAUSE_REQUESTED,
                    run_id=snapshot.run_id,
                )
            elif self._pending_run_id != snapshot.run_id:
                self._pause_unavailable()
            return
        if (
            snapshot.status is ControlStatus.PAUSED
            and snapshot.authority is DesktopControlAuthority.RELEASED
            and snapshot.request_kind is ControlRequestKind.PAUSE
        ):
            self._pending_run_id = None
            self._emit(
                ShortcutAction.REQUEST_PAUSE,
                ShortcutEventState.PAUSED_RELEASED,
                run_id=snapshot.run_id,
                released=True,
            )
            return
        self._pause_unavailable()

    def _pause_unavailable(self) -> None:
        self._pending_run_id = None
        self._emit(
            ShortcutAction.REQUEST_PAUSE,
            ShortcutEventState.PAUSE_UNAVAILABLE,
        )


def render_shortcut_event(event: ShortcutEvent) -> str:
    if not isinstance(event, ShortcutEvent):
        raise ShortcutBrokerError("SHORTCUT_EVENT_INVALID")
    return f"{event.state.value.upper().replace('_', ' ')} · {event.message}\n"


__all__ = [
    "SHORTCUT_BROKER_VERSION",
    "CooperativePausePort",
    "ShortcutAction",
    "ShortcutBroker",
    "ShortcutBrokerError",
    "ShortcutEvent",
    "ShortcutEventState",
    "render_shortcut_event",
]
