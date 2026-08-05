from __future__ import annotations

from threading import Thread

import pytest

from computer_use_mcp.native_authority import (
    NativeActionBoundary,
    NativeAuthorityLost,
    NativeOutcomeUnknown,
)


def _allow() -> tuple[bool, str]:
    return True, ""


def _bound_boundary() -> NativeActionBoundary:
    boundary = NativeActionBoundary()
    boundary.bind(object())
    return boundary


def test_boundary_binds_exactly_one_driver() -> None:
    boundary = NativeActionBoundary()
    boundary.bind(object())

    with pytest.raises(ValueError, match="already bound"):
        boundary.bind(object())


def test_rejection_before_first_mutation_calls_no_native_operation() -> None:
    boundary = _bound_boundary()
    mutations: list[str] = []

    with boundary.call_scope(lambda: (False, "ABORTED: e-stop engaged"), _allow):
        with pytest.raises(NativeAuthorityLost) as caught:
            boundary.mutate(lambda: mutations.append("native"))

    assert mutations == []
    assert caught.value.dispatch_attempts == 0
    assert not caught.value.after_dispatch
    assert caught.value.rejection == "ABORTED: e-stop engaged"


def test_rejection_after_partial_mutation_retains_dispatch_evidence() -> None:
    boundary = _bound_boundary()
    decisions = iter(((True, ""), (False, "HUMAN_ACTIVE: changed")))
    mutations: list[str] = []

    with boundary.call_scope(lambda: next(decisions), _allow):
        boundary.mutate(lambda: mutations.append("first"))
        with pytest.raises(NativeAuthorityLost) as caught:
            boundary.mutate(lambda: mutations.append("second"))

    assert mutations == ["first"]
    assert caught.value.dispatch_attempts == 1
    assert caught.value.after_dispatch
    assert caught.value.rejection == "HUMAN_ACTIVE: changed"


def test_native_input_capture_failure_is_partial_unknown() -> None:
    boundary = _bound_boundary()
    mutations: list[str] = []

    with boundary.call_scope(
        _allow,
        lambda: (False, "HUMAN_ACTIVE: input state unavailable"),
    ):
        with pytest.raises(NativeAuthorityLost) as caught:
            boundary.mutate(
                lambda: mutations.append("input"),
                native_input=True,
            )

    assert mutations == ["input"]
    assert caught.value.after_dispatch
    assert caught.value.dispatch_attempts == 1


def test_native_input_capture_runs_after_each_known_returning_input() -> None:
    boundary = _bound_boundary()
    events: list[str] = []

    def capture() -> tuple[bool, str]:
        events.append("capture")
        return True, ""

    with boundary.call_scope(_allow, capture):
        boundary.mutate(lambda: events.append("native"), native_input=True)
        boundary.mutate(lambda: events.append("uia"))

    assert events == ["native", "capture", "uia"]


def test_failed_completion_after_native_attempt_is_unknown() -> None:
    boundary = _bound_boundary()

    with boundary.call_scope(_allow, _allow):
        boundary.mutate(lambda: None)
        with pytest.raises(NativeOutcomeUnknown) as caught:
            boundary.complete_action(succeeded=False)

    assert caught.value.dispatch_attempts == 1
    assert str(caught.value) == "native action outcome unknown"

    with boundary.call_scope(_allow, _allow):
        boundary.complete_action(succeeded=False)


def test_zero_attempt_completion_retains_existing_failure_semantics() -> None:
    boundary = _bound_boundary()

    with boundary.call_scope(_allow, _allow):
        boundary.complete_action(succeeded=False)


def test_raising_native_operation_is_fixed_unknown_after_attempt() -> None:
    boundary = _bound_boundary()

    with pytest.raises(NativeOutcomeUnknown) as caught:
        with boundary.call_scope(_allow, _allow):
            boundary.mutate(
                lambda: (_ for _ in ()).throw(RuntimeError("secret native failure"))
            )

    assert caught.value.dispatch_attempts == 1
    assert "secret" not in str(caught.value)


def test_exception_before_any_attempt_retains_existing_semantics() -> None:
    boundary = _bound_boundary()

    with pytest.raises(RuntimeError, match="pre-attempt failure"):
        with boundary.call_scope(_allow, _allow):
            raise RuntimeError("pre-attempt failure")


def test_missing_closed_nested_and_concurrent_scopes_fail_closed() -> None:
    unbound = NativeActionBoundary()
    with pytest.raises(NativeAuthorityLost, match="native action authority lost"):
        with unbound.call_scope(_allow, _allow):
            pass

    boundary = _bound_boundary()
    with pytest.raises(NativeAuthorityLost):
        boundary.mutate(lambda: None)


def test_concurrent_scope_fails_without_waiting_or_mutating() -> None:
    boundary = _bound_boundary()
    mutations: list[str] = []
    failures: list[NativeAuthorityLost] = []

    def contend() -> None:
        try:
            with boundary.call_scope(_allow, _allow):
                boundary.mutate(lambda: mutations.append("contender"))
        except NativeAuthorityLost as exc:
            failures.append(exc)

    with boundary.call_scope(_allow, _allow):
        boundary.mutate(lambda: mutations.append("owner"))
        thread = Thread(target=contend)
        thread.start()
        thread.join(timeout=1)

    assert not thread.is_alive()
    assert mutations == ["owner"]
    assert len(failures) == 1
    assert not failures[0].after_dispatch

    with boundary.call_scope(_allow, _allow):
        with pytest.raises(NativeAuthorityLost):
            with boundary.call_scope(_allow, _allow):
                pass

    with pytest.raises(NativeAuthorityLost):
        boundary.mutate(lambda: None)


@pytest.mark.parametrize(
    "probe",
    [
        lambda: None,
        lambda: (True,),
        lambda: ("yes", ""),
        lambda: (_ for _ in ()).throw(RuntimeError("secret")),
    ],
)
def test_malformed_or_raising_revalidator_fails_without_leaking_details(probe) -> None:
    boundary = _bound_boundary()

    with boundary.call_scope(probe, _allow):
        with pytest.raises(NativeAuthorityLost) as caught:
            boundary.mutate(lambda: None)

    assert not caught.value.after_dispatch
    assert "secret" not in caught.value.rejection
    assert caught.value.rejection.startswith("NATIVE_AUTHORITY_LOST:")
