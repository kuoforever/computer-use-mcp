"""OpenTelemetry adapter for the telemetry port.

This module is the *only* place in the package that imports OpenTelemetry, and
nothing in the domain imports this module. The dependency is an optional extra:

    pip install "computer-use-mcp[observability]"

Without that extra installed, or without an operator explicitly building an
adapter, the runner keeps using :class:`~computer_use_agent.telemetry.NoOpTelemetry`
and opens no connection.

The adapter deliberately keeps the strict attribute validation from the port
rather than handing values straight to OpenTelemetry. An exporter is a place
content can leave the machine, so it is the last place to relax a privacy rule.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Literal, Mapping

from .telemetry import TelemetryError, validate_attributes

__all__ = ["OpenTelemetryAdapter", "OpenTelemetrySpan", "require_opentelemetry"]


def require_opentelemetry() -> None:
    """Raise a fixed, actionable error when the optional extra is absent."""

    try:
        import opentelemetry.trace  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised by absence
        raise TelemetryError(
            "OpenTelemetry is not installed; "
            'install the optional extra: pip install "computer-use-mcp[observability]"'
        ) from exc


def _flatten(attributes: Mapping[str, object]) -> dict[str, object]:
    """Validate first, then convert to what the OTel attribute types accept."""

    validated = validate_attributes(attributes)
    flattened: dict[str, object] = {}
    for name, value in validated.items():
        flattened[name] = list(value) if isinstance(value, tuple) else value
    return flattened


class OpenTelemetrySpan:
    """Wraps one OTel span behind the port's narrow surface."""

    __slots__ = ("_span", "_token", "_ended")

    def __init__(self, span: Any, token: Any) -> None:
        # These are OpenTelemetry objects from an optional dependency. Typing
        # them as Any keeps this module checkable both with and without the
        # extra installed, instead of needing ignores that only apply in one
        # of the two environments.
        self._span: Any = span
        self._token: Any = token
        self._ended = False

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        self._span.set_attributes(_flatten(attributes))

    def record_error(self, code: str) -> None:
        """Record a fixed code as the span status.

        Never an exception object and never a message: OTel would happily
        attach a stack trace containing task or desktop content.
        """

        from opentelemetry.trace import Status, StatusCode

        if not isinstance(code, str) or not code or len(code) > 64 or "\n" in code:
            raise TelemetryError("error codes must be short single-line strings")
        self._span.set_status(Status(StatusCode.ERROR, code))
        self._span.set_attribute("result.code", code)

    def end(self) -> None:
        """End the span and detach its context exactly once.

        Detaching matters: a span left attached makes every later span its
        child, which silently turns a flat sequence of tool boundaries into a
        misleading nested trace.
        """

        if self._ended:
            return
        self._ended = True
        from opentelemetry import context as otel_context

        try:
            self._span.end()
        finally:
            otel_context.detach(self._token)

    def __enter__(self) -> "OpenTelemetrySpan":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        self.end()
        return False


class OpenTelemetryAdapter:
    """A :class:`~computer_use_agent.telemetry.TelemetryPort` backed by OTel.

    Parent/child structure comes from OTel's own context, so a span started
    while another is current becomes its child, matching the hierarchy in
    ``docs/TELEMETRY.md``.
    """

    def __init__(self, tracer: Any = None, *, meter: Any = None) -> None:
        require_opentelemetry()
        if tracer is None:
            from opentelemetry import trace

            tracer = trace.get_tracer("computer-use-agent")
        self._tracer: Any = tracer
        self._meter: Any = meter
        self._counters: dict[str, Any] = {}

    def start_span(
        self, name: str, *, attributes: Mapping[str, object] | None = None
    ) -> OpenTelemetrySpan:
        from opentelemetry import context as otel_context
        from opentelemetry import trace

        span = self._tracer.start_span(
            name, attributes=_flatten(attributes) if attributes else None
        )
        token = otel_context.attach(trace.set_span_in_context(span))
        return OpenTelemetrySpan(span, token)

    def record_metric(
        self, name: str, value: int, *, attributes: Mapping[str, object] | None = None
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TelemetryError("metric values must be integers")
        if self._meter is None:
            return None
        counter = self._counters.get(name)
        if counter is None:
            counter = self._meter.create_counter(name)
            self._counters[name] = counter
        counter.add(value, _flatten(attributes or {}))
        return None
