"""Call-scoped authority checkpoints for native desktop mutations.

The MCP server owns policy and supplies one non-waiting revalidator per action
call. Platform code sees only this controller; it never receives gate state,
human-input captures, tool arguments, or model data.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from typing import TypeVar


T = TypeVar("T")
AuthorityProbe = Callable[[], tuple[bool, str]]

_BOUNDARY_UNAVAILABLE = "NATIVE_AUTHORITY_LOST: native action boundary unavailable"


class NativeAuthorityLost(RuntimeError):
    """A fixed control-flow exception for a rejected native checkpoint."""

    def __init__(
        self,
        *,
        dispatch_attempts: int,
        rejection: str = _BOUNDARY_UNAVAILABLE,
    ) -> None:
        super().__init__("native action authority lost")
        self.dispatch_attempts = max(0, int(dispatch_attempts))
        self.rejection = rejection if isinstance(rejection, str) and rejection else _BOUNDARY_UNAVAILABLE

    @property
    def after_dispatch(self) -> bool:
        return self.dispatch_attempts > 0


class NativeOutcomeUnknown(RuntimeError):
    """A fixed control-flow exception for failure after a native attempt."""

    def __init__(self, *, dispatch_attempts: int) -> None:
        super().__init__("native action outcome unknown")
        self.dispatch_attempts = max(1, int(dispatch_attempts))


@dataclass(slots=True)
class _CallScope:
    revalidate: AuthorityProbe
    capture_native_input: AuthorityProbe
    dispatch_attempts: int = 0
    closed: bool = False


class NativeActionBoundary:
    """One explicitly bound controller with at most one active action scope."""

    def __init__(self) -> None:
        self._current: ContextVar[_CallScope | None] = ContextVar(
            f"native_action_scope_{id(self)}",
            default=None,
        )
        self._active_scope = Lock()
        self._binding_lock = Lock()
        self._bound_driver_id: int | None = None

    def bind(self, driver: object) -> None:
        """Bind exactly one driver instance; duplicate binding is rejected."""

        if driver is None:
            raise ValueError("native action boundary requires a driver")
        with self._binding_lock:
            if self._bound_driver_id is not None:
                raise ValueError("native action boundary is already bound")
            self._bound_driver_id = id(driver)

    @contextmanager
    def call_scope(
        self,
        revalidate: AuthorityProbe,
        capture_native_input: AuthorityProbe,
    ) -> Iterator[None]:
        """Open one non-waiting, non-nestable action scope."""

        if self._bound_driver_id is None or not callable(revalidate) or not callable(
            capture_native_input
        ):
            raise NativeAuthorityLost(dispatch_attempts=0)
        if not self._active_scope.acquire(blocking=False):
            raise NativeAuthorityLost(dispatch_attempts=0)
        if self._current.get() is not None:
            self._active_scope.release()
            raise NativeAuthorityLost(dispatch_attempts=0)
        scope = _CallScope(revalidate, capture_native_input)
        token = self._current.set(scope)
        try:
            yield
        except (NativeAuthorityLost, NativeOutcomeUnknown):
            raise
        except Exception:
            if scope.dispatch_attempts > 0:
                raise NativeOutcomeUnknown(
                    dispatch_attempts=scope.dispatch_attempts
                ) from None
            raise
        finally:
            scope.closed = True
            self._current.reset(token)
            self._active_scope.release()

    def mutate(self, operation: Callable[[], T], *, native_input: bool = False) -> T:
        """Revalidate, mark dispatch, run one native API, then capture self-input."""

        if not callable(operation):
            raise TypeError("native mutation must be callable")
        scope = self._current.get()
        if scope is None or scope.closed:
            raise NativeAuthorityLost(dispatch_attempts=0)

        allowed, rejection = self._probe(scope.revalidate)
        if not allowed:
            raise NativeAuthorityLost(
                dispatch_attempts=scope.dispatch_attempts,
                rejection=rejection,
            )

        # Mark before the native API call: an API may apply an effect and then
        # fail, so entering it is already a conservative dispatch attempt.
        scope.dispatch_attempts += 1
        result = operation()

        if native_input:
            captured, rejection = self._probe(scope.capture_native_input)
            if not captured:
                raise NativeAuthorityLost(
                    dispatch_attempts=scope.dispatch_attempts,
                    rejection=rejection,
                )
        return result

    def complete_action(self, *, succeeded: bool) -> None:
        """Promote a failed action with any native attempt to unknown outcome."""

        if not isinstance(succeeded, bool):
            raise TypeError("native action completion requires a boolean result")
        scope = self._current.get()
        if scope is None or scope.closed:
            raise NativeAuthorityLost(dispatch_attempts=0)
        if not succeeded and scope.dispatch_attempts > 0:
            raise NativeOutcomeUnknown(dispatch_attempts=scope.dispatch_attempts)

    @staticmethod
    def _probe(probe: AuthorityProbe) -> tuple[bool, str]:
        try:
            decision = probe()
        except Exception:
            return False, _BOUNDARY_UNAVAILABLE
        if (
            not isinstance(decision, tuple)
            or len(decision) != 2
            or not isinstance(decision[0], bool)
            or not isinstance(decision[1], str)
        ):
            return False, _BOUNDARY_UNAVAILABLE
        return decision


__all__ = ["NativeActionBoundary", "NativeAuthorityLost", "NativeOutcomeUnknown"]
