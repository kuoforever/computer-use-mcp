"""Deterministic offline E1/E2 evaluation cases and JSON reports."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from unittest.mock import patch

from .config import (
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from .fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from .runner import AgentRunner, RunFailure, RunnerPorts
from .tool_registry import REVIEWED_TOOLS
from .types import (
    CallIdentity,
    ApprovalRequest,
    DispatchCertainty,
    JSONValue,
    LedgerEventKind,
    ModelTurn,
    ModelUsage,
    PolicyDecision,
    PolicyDecisionKind,
    RunState,
    ToolCall,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
    to_json_value,
)


CASE_VERSION = 1
REPORT_VERSION = 1
MANIFEST_VERSION = 1


class EvaluationCaseError(ValueError):
    """Raised when an evaluation case is malformed or unreviewed."""


def _canonical_case_digest(path: Path) -> str:
    try:
        case = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationCaseError("cannot canonicalize case manifest input") from exc
    canonical = json.dumps(
        case, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def verify_case_manifest(cases_dir: Path, manifest_path: Path) -> None:
    """Fail closed when the reviewed E1/E2 case set or canonical JSON drifts."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationCaseError("cannot load case manifest") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"version", "sha256"}:
        raise EvaluationCaseError("case manifest has invalid fields")
    hashes = manifest.get("sha256")
    if manifest.get("version") != MANIFEST_VERSION or not isinstance(hashes, dict):
        raise EvaluationCaseError("unsupported case manifest")
    paths = sorted(cases_dir.glob("*.json"), key=lambda path: path.name)
    if set(hashes) != {path.name for path in paths}:
        raise EvaluationCaseError("case manifest file set mismatch")
    for path in paths:
        expected = hashes.get(path.name)
        if not isinstance(expected, str) or len(expected) != 64:
            raise EvaluationCaseError("case manifest digest is invalid")
        if _canonical_case_digest(path) != expected:
            raise EvaluationCaseError("case manifest digest mismatch")


def write_case_manifest(cases_dir: Path, manifest_path: Path) -> None:
    """Write a reviewed canonical case manifest after validating every case."""
    paths = sorted(cases_dir.glob("*.json"), key=lambda path: path.name)
    if not paths:
        raise EvaluationCaseError("no evaluation cases found")
    for path in paths:
        _load_case(path)
    payload = {
        "version": MANIFEST_VERSION,
        "sha256": {path.name: _canonical_case_digest(path) for path in paths},
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@dataclass(frozen=True)
class EvaluationReport:
    payload: Mapping[str, JSONValue]

    @property
    def passed(self) -> bool:
        return bool(self.payload["passed"])

    def as_json(self) -> dict[str, JSONValue]:
        return to_json_value(self.payload)  # type: ignore[return-value]


def _object(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise EvaluationCaseError(f"{field_name} must be an object")
    return value


def _keys(value: Mapping[str, object], allowed: set[str], field_name: str) -> None:
    unexpected = set(value) - allowed
    if unexpected:
        raise EvaluationCaseError(f"{field_name} has unknown fields: {sorted(unexpected)}")


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationCaseError(f"{field_name} must be a non-empty string")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvaluationCaseError(f"{field_name} must be a non-negative integer")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationCaseError(f"{field_name} must be boolean")
    return value


def _load_case(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationCaseError(f"cannot load case: {path.name}") from exc
    case = _object(document, "case")
    _keys(
        case,
        {
            "version",
            "id",
            "level",
            "task",
            "approved_actions",
            "budgets",
            "turns",
            "results",
            "expected",
        },
        "case",
    )
    if case.get("version") != CASE_VERSION:
        raise EvaluationCaseError(f"unsupported case version: {path.name}")
    _string(case.get("id"), "case.id")
    if case.get("level") not in {"E1", "E2"}:
        raise EvaluationCaseError("case.level must be E1 or E2")
    _string(case.get("task"), "case.task")
    if not isinstance(case.get("turns"), list) or not case["turns"]:
        raise EvaluationCaseError("case.turns must be a non-empty array")
    if not isinstance(case.get("results"), list):
        raise EvaluationCaseError("case.results must be an array")
    _object(case.get("budgets"), "case.budgets")
    _object(case.get("expected"), "case.expected")
    return case


def _turns(case: Mapping[str, object], run_id: str) -> deque[ModelTurn]:
    turns: deque[ModelTurn] = deque()
    for index, raw_turn in enumerate(case["turns"], start=1):  # type: ignore[index]
        turn = _object(raw_turn, f"turns[{index - 1}]")
        _keys(
            turn,
            {"text", "calls", "run_id", "turn_id", "input_tokens", "output_tokens"},
            f"turns[{index - 1}]",
        )
        raw_calls = turn.get("calls", [])
        if not isinstance(raw_calls, list):
            raise EvaluationCaseError("turn.calls must be an array")
        resolved_run_id = turn.get("run_id", run_id)
        resolved_turn_id = turn.get("turn_id", f"turn_{index}")
        resolved_run_id = _string(resolved_run_id, "turn.run_id")
        resolved_turn_id = _string(resolved_turn_id, "turn.turn_id")
        calls: list[ToolCall] = []
        for call_index, raw_call in enumerate(raw_calls, start=1):
            call = _object(raw_call, "turn.call")
            _keys(call, {"id", "name", "arguments"}, "turn.call")
            arguments = _object(call.get("arguments", {}), "turn.call.arguments")
            calls.append(
                ToolCall(
                    identity=CallIdentity(
                        run_id=resolved_run_id,
                        turn_id=resolved_turn_id,
                        call_id=_string(call.get("id", f"call_{call_index}"), "turn.call.id"),
                    ),
                    name=_string(call.get("name"), "turn.call.name"),
                    arguments=arguments,
                )
            )
        text = turn.get("text", "")
        if not isinstance(text, str):
            raise EvaluationCaseError("turn.text must be a string")
        turns.append(
            ModelTurn(
                run_id=resolved_run_id,
                turn_id=resolved_turn_id,
                provider_response_id=f"response_{index}",
                text=text,
                tool_calls=tuple(calls),
                usage=ModelUsage(
                    input_tokens=_integer(turn.get("input_tokens", 1), "turn.input_tokens"),
                    output_tokens=_integer(turn.get("output_tokens", 1), "turn.output_tokens"),
                ),
            )
        )
    return turns


def _results(case: Mapping[str, object], run_id: str) -> deque[ToolResult]:
    results: deque[ToolResult] = deque()
    for raw_result in case["results"]:  # type: ignore[index]
        result = _object(raw_result, "result")
        _keys(
            result,
            {"call_id", "turn_id", "tool", "status", "dispatch", "text", "code"},
            "result",
        )
        try:
            status = ToolResultStatus(_string(result.get("status"), "result.status"))
            dispatch = DispatchCertainty(_string(result.get("dispatch"), "result.dispatch"))
        except ValueError as exc:
            raise EvaluationCaseError("result status or dispatch is invalid") from exc
        text = result.get("text", "")
        if not isinstance(text, str):
            raise EvaluationCaseError("result.text must be a string")
        code = result.get("code")
        if code is not None:
            code = _string(code, "result.code")
        results.append(
            ToolResult(
                identity=CallIdentity(
                    run_id=run_id,
                    turn_id=_string(result.get("turn_id"), "result.turn_id"),
                    call_id=_string(result.get("call_id"), "result.call_id"),
                ),
                tool_name=_string(result.get("tool"), "result.tool"),
                status=status,
                dispatch=dispatch,
                sanitized_text=text,
                code=code,
            )
        )
    return results


class _AllowApprovalPort:
    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        return PolicyDecision(
            request_id=request.request_id,
            identity=request.identity,
            call_digest=request.call_digest,
            kind=PolicyDecisionKind.ALLOW,
            reason="evaluation_fixture",
        )


def canonical_trace(state: RunState) -> list[dict[str, JSONValue]]:
    """Project a ledger to stable semantic fields suitable for exact fixtures."""

    trace: list[dict[str, JSONValue]] = []
    for event in state.event_log:
        item: dict[str, JSONValue] = {"kind": event.kind.value}
        if event.kind is LedgerEventKind.MODEL_TURN:
            item["tool_call_count"] = event.payload["tool_call_count"]
        elif event.kind is LedgerEventKind.TOOL_CALL:
            assert event.safe_argument_summary is not None
            item["tool"] = event.safe_argument_summary.tool_name
            item["arguments"] = to_json_value(event.safe_argument_summary.values)
        elif event.kind is LedgerEventKind.TOOL_RESULT:
            assert event.tool_result is not None
            item["tool"] = event.tool_result.tool_name
            item["status"] = event.tool_result.status.value
            if event.tool_result.code is not None:
                item["code"] = event.tool_result.code
        elif event.kind is LedgerEventKind.OBSERVATION:
            item["tool"] = event.payload["tool_name"]
            item["observation_epoch"] = event.payload["observation_epoch"]
        trace.append(item)
    return trace


async def _run_case(case: Mapping[str, object], state_root: Path) -> dict[str, JSONValue]:
    case_id = _string(case["id"], "case.id")
    run_id = f"eval_{case_id}"
    budgets = _object(case["budgets"], "case.budgets")
    _keys(
        budgets,
        {"model_turns", "tool_calls", "side_effects", "input_tokens"},
        "case.budgets",
    )
    approved_actions = _boolean(case.get("approved_actions", False), "case.approved_actions")
    config = AgentConfig(
        state_dir=state_root / "computer-use-agent" / case_id,
        policy_version="eval-v1",
        provider=ProviderConfig(name="openai", model="fake"),
        mcp=MCPLaunchConfig(
            executable=state_root / "fake-mcp.exe",
            args=(),
            cwd=state_root,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(
            mode=APPROVED_ACTIONS_MODE if approved_actions else "read_only",
            max_model_turns=_integer(budgets.get("model_turns"), "budgets.model_turns"),
            max_tool_calls=_integer(budgets.get("tool_calls"), "budgets.tool_calls"),
            max_side_effects=_integer(
                budgets.get("side_effects", 0), "budgets.side_effects"
            ),
            max_input_tokens=_integer(
                budgets.get("input_tokens", 1_000_000), "budgets.input_tokens"
            ),
        ),
    )
    provider = FakeModelProvider(turns=_turns(case, run_id))
    desktop = FakeDesktopMCP(results=_results(case, run_id))
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=provider,
            desktop=desktop,
            approvals=_AllowApprovalPort() if approved_actions else FakeApprovalPort(),
        ),
    )
    state: RunState
    outcome_code = "success"
    try:
        outcome = await runner.run(_string(case["task"], "case.task"), run_id=run_id)
        state = outcome.state
    except RunFailure as failure:
        outcome_code = failure.code
        state = failure.state

    actual_trace = canonical_trace(state)
    dispatched_tools = [call.name for call in desktop.tool_calls]
    expected = _object(case["expected"], "case.expected")
    _keys(expected, {"outcome", "trace", "dispatched_tools"}, "case.expected")
    expected_trace = expected.get("trace")
    expected_dispatched = expected.get("dispatched_tools")
    if not isinstance(expected_trace, list) or not isinstance(expected_dispatched, list):
        raise EvaluationCaseError("expected trace and dispatched_tools must be arrays")
    side_effect_names = {
        tool.name for tool in REVIEWED_TOOLS if tool.effect is ToolEffect.SIDE_EFFECT
    }
    actual_actions = Counter(
        call.name for call in desktop.tool_calls if call.name in side_effect_names
    )
    expected_actions = Counter(
        name for name in expected_dispatched if name in side_effect_names
    )
    safety_escapes = sum((actual_actions - expected_actions).values())
    passed = (
        outcome_code == expected.get("outcome")
        and actual_trace == expected_trace
        and dispatched_tools == expected_dispatched
        and safety_escapes == 0
    )
    return {
        "id": case_id,
        "level": _string(case["level"], "case.level"),
        "passed": passed,
        "expected_outcome": _string(expected.get("outcome"), "expected.outcome"),
        "actual_outcome": outcome_code,
        "expected_trace": to_json_value(expected_trace),
        "actual_trace": to_json_value(actual_trace),
        "expected_dispatched_tools": to_json_value(expected_dispatched),
        "actual_dispatched_tools": dispatched_tools,
        "safety_escapes": safety_escapes,
    }


def run_evaluations(cases_dir: Path) -> EvaluationReport:
    """Load all versioned JSON cases and return a deterministic aggregate report."""

    if not isinstance(cases_dir, Path) or not cases_dir.is_dir():
        raise EvaluationCaseError("cases directory does not exist")
    paths = sorted(cases_dir.glob("*.json"))
    if not paths:
        raise EvaluationCaseError("cases directory contains no JSON cases")
    cases = [_load_case(path) for path in paths]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise EvaluationCaseError("case identifiers must be unique")

    with tempfile.TemporaryDirectory(prefix="computer-use-agent-eval-") as temp:
        state_root = Path(temp).resolve()
        with patch.dict(os.environ, {"LOCALAPPDATA": str(state_root)}):
            results = [asyncio.run(_run_case(case, state_root)) for case in cases]
    passed_cases = sum(bool(result["passed"]) for result in results)
    safety_escapes = sum(int(result["safety_escapes"]) for result in results)
    payload: dict[str, JSONValue] = {
        "report_version": REPORT_VERSION,
        "passed": passed_cases == len(results) and safety_escapes == 0,
        "case_count": len(results),
        "passed_cases": passed_cases,
        "failed_cases": len(results) - passed_cases,
        "safety_escapes": safety_escapes,
        "cases": results,
    }
    return EvaluationReport(payload)


def write_report(report: EvaluationReport, path: Path) -> None:
    if not isinstance(path, Path):
        raise ValueError("report path must be a Path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.as_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "EvaluationCaseError",
    "EvaluationReport",
    "canonical_trace",
    "run_evaluations",
    "write_report",
    "verify_case_manifest",
    "write_case_manifest",
]
