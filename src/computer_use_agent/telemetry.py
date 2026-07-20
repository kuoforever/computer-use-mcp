"""Observation-only telemetry port with a no-op default.

Three kinds of data exist in this system and must not be confused:

* **Audit** records prove what operation boundary was crossed.
* **Durable state** (WAL, ledger, checkpoints) decides what may be resumed.
* **Telemetry** aggregates performance and failure trends.

Telemetry is the only one that may be lost. Nothing here participates in
recovery, completion, or replay decisions: an exporter dropping a span must not
be able to change run state, and a span is never evidence that a side effect
happened. See ``docs/TELEMETRY.md``.

The domain depends on this module only. No OpenTelemetry import exists here; an
exporter adapter is a separate, optional concern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import TracebackType
from typing import Literal, Mapping, Protocol, runtime_checkable

__all__ = [
    "ALLOWED_ATTRIBUTES",
    "FORBIDDEN_ATTRIBUTE_SUBSTRINGS",
    "MAX_ATTRIBUTE_STRING_LENGTH",
    "InMemorySpan",
    "InMemoryTelemetry",
    "NoOpTelemetry",
    "SpanPort",
    "TelemetryError",
    "TelemetryPort",
    "validate_attributes",
]


class TelemetryError(ValueError):
    """Raised when an attribute would leak content or is not reviewed."""


# Reviewed attribute names. Anything absent is rejected rather than passed
# through, so adding an attribute is a deliberate review step. Values must be
# fixed codes, counts, or durations - never free text from a task, a model, a
# desktop surface, or a URL.
ALLOWED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        # identity and lifecycle
        "run.phase",
        "run.resumed",
        "run.outcome_code",
        # provider
        "provider.name",
        "provider.model_family",
        "provider.turn_index",
        # tool boundary
        "tool.name",
        "tool.effect",
        "tool.argument_summary_keys",
        "tool.redacted_fields",
        # decisions
        "policy.disposition",
        "policy.denial_code",
        "grounding.fresh",
        "approval.required",
        "approval.granted",
        # dispatch and outcome
        "dispatch.certainty",
        "result.status",
        "result.code",
        # recovery
        "recovery.classification",
        "recovery.attempted",
        # counts and durations, all integers
        "budget.model_turns_remaining",
        "budget.tool_calls_remaining",
        "budget.side_effects_remaining",
        "tokens.input",
        "tokens.output",
        "bytes.request",
        "duration.ms",
        "item.ordinal",
        "item.count",
        "campaign.item_key_digest",
    }
)

# A defence in depth against a reviewed name being reused for content later.
FORBIDDEN_ATTRIBUTE_SUBSTRINGS: tuple[str, ...] = (
    "text",
    "prompt",
    "task",
    "message",
    "content",
    "url",
    "title",
    "token_value",
    "secret",
    "key",
    "password",
    "credential",
)

MAX_ATTRIBUTE_STRING_LENGTH = 64


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not name:
        raise TelemetryError("attribute names must be non-empty strings")
    if name not in ALLOWED_ATTRIBUTES:
        raise TelemetryError(f"attribute is not reviewed: {name}")
    lowered = name.lower()
    for forbidden in FORBIDDEN_ATTRIBUTE_SUBSTRINGS:
        # `tool.argument_summary_keys` and `campaign.item_key_digest` name
        # shapes, not values; every other match is a content smell.
        if forbidden in lowered and name not in {
            "tool.argument_summary_keys",
            "campaign.item_key_digest",
        }:
            raise TelemetryError(f"attribute name suggests content: {name}")


def _validate_value(name: str, value: object) -> None:
    if isinstance(value, bool) or isinstance(value, int):
        return
    if isinstance(value, str):
        if len(value) > MAX_ATTRIBUTE_STRING_LENGTH:
            raise TelemetryError(
                f"attribute {name} exceeds {MAX_ATTRIBUTE_STRING_LENGTH} characters; "
                "telemetry carries codes, not content"
            )
        if "\n" in value or "\r" in value:
            raise TelemetryError(f"attribute {name} must be a single-line code")
        return
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        for item in value:
            _validate_value(name, item)
        return
    raise TelemetryError(
        f"attribute {name} must be a bool, int, short string, or string tuple"
    )


def validate_attributes(attributes: Mapping[str, object]) -> dict[str, object]:
    """Return a validated copy, or raise ``TelemetryError``.

    Validation is deliberately strict and fail-closed at the *producer*. A
    caller that wants to record something new must add it to the reviewed set.
    """

    if not isinstance(attributes, Mapping):
        raise TelemetryError("attributes must be a mapping")
    validated: dict[str, object] = {}
    for name, value in attributes.items():
        _validate_name(name)
        _validate_value(name, value)
        validated[name] = value
    return validated


@runtime_checkable
class SpanPort(Protocol):
    """One in-progress unit of observation."""

    def set_attributes(self, attributes: Mapping[str, object]) -> None: ...

    def record_error(self, code: str) -> None:
        """Record a fixed failure code. Never an exception message."""

    def end(self) -> None: ...

    def __enter__(self) -> "SpanPort": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]: ...


@runtime_checkable
class TelemetryPort(Protocol):
    """Creates spans and records metric counters."""

    def start_span(
        self, name: str, *, attributes: Mapping[str, object] | None = None
    ) -> SpanPort: ...

    def record_metric(
        self, name: str, value: int, *, attributes: Mapping[str, object] | None = None
    ) -> None: ...


class _NoOpSpan:
    """Accepts every call and keeps nothing."""

    __slots__ = ()

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        return None

    def record_error(self, code: str) -> None:
        return None

    def end(self) -> None:
        return None

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        return False


class NoOpTelemetry:
    """The default. Allocates one shared span and opens no connection.

    This is what runs unless an operator explicitly configures an exporter, so
    the offline CLI and the test suite never depend on external infrastructure.
    """

    __slots__ = ("_span",)

    def __init__(self) -> None:
        self._span = _NoOpSpan()

    def start_span(
        self, name: str, *, attributes: Mapping[str, object] | None = None
    ) -> _NoOpSpan:
        return self._span

    def record_metric(
        self, name: str, value: int, *, attributes: Mapping[str, object] | None = None
    ) -> None:
        return None


@dataclass
class InMemorySpan:
    """A recorded span, used by tests to assert structure and absence."""

    name: str
    parent: "InMemorySpan | None" = None
    attributes: dict[str, object] = field(default_factory=dict)
    error_code: str | None = None
    ended: bool = False
    children: list["InMemorySpan"] = field(default_factory=list)

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        self.attributes.update(validate_attributes(attributes))

    def record_error(self, code: str) -> None:
        _validate_value("result.code", code)
        self.error_code = code

    def end(self) -> None:
        self.ended = True

    def __enter__(self) -> "InMemorySpan":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        self.end()
        return False


class InMemoryTelemetry:
    """Records spans and metrics in memory for offline structure/privacy tests."""

    def __init__(self) -> None:
        self.spans: list[InMemorySpan] = []
        self.metrics: list[tuple[str, int, dict[str, object]]] = []
        self._stack: list[InMemorySpan] = []

    def start_span(
        self, name: str, *, attributes: Mapping[str, object] | None = None
    ) -> InMemorySpan:
        parent = self._stack[-1] if self._stack else None
        span = InMemorySpan(name=name, parent=parent)
        if attributes:
            span.set_attributes(attributes)
        if parent is not None:
            parent.children.append(span)
        self.spans.append(span)
        self._stack.append(span)
        original_end = span.end

        def end() -> None:
            original_end()
            if self._stack and self._stack[-1] is span:
                self._stack.pop()

        span.end = end  # type: ignore[method-assign]
        return span

    def record_metric(
        self, name: str, value: int, *, attributes: Mapping[str, object] | None = None
    ) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TelemetryError("metric values must be integers")
        self.metrics.append(
            (name, value, validate_attributes(attributes or {}))
        )

    def roots(self) -> list[InMemorySpan]:
        return [span for span in self.spans if span.parent is None]

    def named(self, name: str) -> list[InMemorySpan]:
        return [span for span in self.spans if span.name == name]
