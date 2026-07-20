"""Telemetry port contract: structure, strict attributes, and no content."""

from __future__ import annotations

import pytest

from computer_use_agent.telemetry import (
    ALLOWED_ATTRIBUTES,
    MAX_ATTRIBUTE_STRING_LENGTH,
    InMemoryTelemetry,
    NoOpTelemetry,
    SpanPort,
    TelemetryError,
    TelemetryPort,
    validate_attributes,
)


def test_noop_is_the_default_shape_and_keeps_nothing() -> None:
    telemetry = NoOpTelemetry()
    assert isinstance(telemetry, TelemetryPort)

    with telemetry.start_span("agent.run") as span:
        assert isinstance(span, SpanPort)
        span.set_attributes({"run.phase": "running"})
        span.record_error("MCP_TRANSPORT_ERROR")
    telemetry.record_metric("agent_runs_total", 1)

    # No storage exists to inspect; the contract is that nothing is retained
    # and no attribute validation cost is paid on the default path.
    assert not hasattr(telemetry, "spans")


def test_in_memory_telemetry_records_parent_and_child_structure() -> None:
    telemetry = InMemoryTelemetry()
    with telemetry.start_span("agent.run", attributes={"run.phase": "running"}):
        with telemetry.start_span("tool.boundary", attributes={"tool.name": "click"}):
            pass
        with telemetry.start_span("checkpoint.persist"):
            pass

    roots = telemetry.roots()
    assert [span.name for span in roots] == ["agent.run"]
    assert [child.name for child in roots[0].children] == [
        "tool.boundary",
        "checkpoint.persist",
    ]
    assert all(span.ended for span in telemetry.spans)


def test_sibling_spans_do_not_nest_after_the_previous_one_ends() -> None:
    telemetry = InMemoryTelemetry()
    with telemetry.start_span("agent.run"):
        with telemetry.start_span("provider.turn"):
            pass
        with telemetry.start_span("provider.turn"):
            pass

    turns = telemetry.named("provider.turn")
    assert len(turns) == 2
    assert all(turn.parent is not None and turn.parent.name == "agent.run" for turn in turns)
    assert turns[1] not in turns[0].children


@pytest.mark.parametrize(
    "attributes",
    [
        {"task.text": "open the invoice"},
        {"tool.typed_text": "hunter2"},
        {"page.url": "https://example.invalid/a?token=abc"},
        {"window.title": "Inbox - private"},
        {"provider.api_key": "sk-live-000"},
        {"ocr.content": "recognized words"},
    ],
)
def test_content_bearing_attributes_are_rejected(attributes: dict[str, object]) -> None:
    with pytest.raises(TelemetryError):
        validate_attributes(attributes)


def test_unreviewed_attribute_is_rejected_even_when_harmless() -> None:
    with pytest.raises(TelemetryError, match="not reviewed"):
        validate_attributes({"tool.invocation_count": 3})


def test_long_or_multiline_values_are_rejected() -> None:
    with pytest.raises(TelemetryError, match="characters"):
        validate_attributes({"result.code": "x" * (MAX_ATTRIBUTE_STRING_LENGTH + 1)})
    with pytest.raises(TelemetryError, match="single-line"):
        validate_attributes({"result.code": "line\nline"})


def test_reviewed_codes_counts_and_flags_are_accepted() -> None:
    validated = validate_attributes(
        {
            "tool.name": "ui_snapshot",
            "tool.effect": "observation",
            "policy.disposition": "allow",
            "dispatch.certainty": "not_dispatched",
            "grounding.fresh": True,
            "duration.ms": 42,
            "tokens.input": 0,
            "tool.redacted_fields": ("text",),
        }
    )
    assert validated["duration.ms"] == 42
    assert validated["tool.redacted_fields"] == ("text",)


def test_every_reviewed_attribute_validates_with_a_representative_value() -> None:
    """A reviewed name must not be unusable because of the content guard."""
    for name in ALLOWED_ATTRIBUTES:
        validate_attributes({name: 1})


def test_metric_values_must_be_integers() -> None:
    telemetry = InMemoryTelemetry()
    with pytest.raises(TelemetryError):
        telemetry.record_metric("agent_runs_total", True)
    with pytest.raises(TelemetryError):
        telemetry.record_metric("agent_runs_total", 1.5)  # type: ignore[arg-type]
    telemetry.record_metric("agent_runs_total", 1, attributes={"run.phase": "completed"})
    assert telemetry.metrics == [("agent_runs_total", 1, {"run.phase": "completed"})]


def test_error_codes_are_fixed_strings_not_messages() -> None:
    telemetry = InMemoryTelemetry()
    span = telemetry.start_span("tool.boundary")
    span.record_error("POLICY_DENIED")
    assert span.error_code == "POLICY_DENIED"
    with pytest.raises(TelemetryError):
        span.record_error("Traceback (most recent call last):\n  File ...")
