from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from computer_use_agent.config import (
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.continuation import (
    ContinuationEnvelope,
    RuntimeContinuationRecorder,
    read_continuation,
    write_continuation,
)
from computer_use_agent.fakes import FakeDesktopMCP
from computer_use_agent.providers.openai import (
    OpenAIProviderError,
    OpenAIResponsesProvider,
    _instructions,
    _request_contract_digest,
    _tool_definitions,
)
from computer_use_agent.reconstruction import ReconstructionAction
from computer_use_agent.recovery import (
    execute_read_only_recovery_step,
    plan_read_only_recovery,
)
from computer_use_agent.tool_registry import REVIEWED_TOOLS, reviewed_registry_digest
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    ModelTurn,
    ModelUsage,
    RunBudget,
    RunState,
    ToolCall,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
)


FIXTURE = Path(__file__).parents[2] / "evals" / "e2-stateless-replay.json"
MANIFEST = Path(__file__).parents[2] / "evals" / "e2-stateless-replay-manifest.json"
PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@dataclass
class RecordingResponses:
    fail: bool = False
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("provider failure")
        return SimpleNamespace(
            id="response_2",
            output=[],
            output_text="done",
            usage=SimpleNamespace(input_tokens=10, output_tokens=4),
        )


def _provider_state(
    provider: OpenAIResponsesProvider,
    *,
    initial_input: str,
    items: list[dict[str, object]],
) -> dict[str, object]:
    tools = _tool_definitions(REVIEWED_TOOLS, allow_actions=provider.allow_actions)
    instructions = _instructions(allow_actions=False, memory_context_used=False)
    return {
        "response_id": "response_1",
        "prior_context_tokens": 14,
        "request_contract_digest": _request_contract_digest(
            model=provider.model,
            instructions=instructions,
            tools=tools,
            allow_actions=False,
            memory_context_used=False,
            initial_input_digest=sha256(initial_input.encode("utf-8")).hexdigest(),
            max_request_bytes=provider.max_request_bytes,
            context_window_tokens=provider.context_window_tokens,
            output_token_reserve=provider.output_token_reserve,
        ),
        "memory_context_used": False,
        "initial_input": initial_input,
        "output_batches": [{"response_id": "response_1", "items": items}],
    }


def _artifact(
    root: Path,
    provider: OpenAIResponsesProvider,
    *,
    result_kind: str,
    mutation: str,
) -> tuple[ContinuationEnvelope, dict[str, object], RunState]:
    run_id = "run_replay_eval"
    task = "Inspect"
    tool_name = "screenshot" if result_kind == "screenshot" else "list_windows"
    if mutation == "side_effect_history":
        tool_name = "click"
    arguments = {"ref": "ref_1"} if tool_name == "click" else {}
    call = ToolCall(CallIdentity(run_id, "turn_1", "call_1"), tool_name, arguments)
    state = RunState(
        run_id,
        task,
        "policy-v1",
        0,
        RunBudget(
            4,
            4,
            8,
            model_turns_used=1,
            tool_calls_used=1,
            input_tokens_used=10,
        ),
    )
    items: list[dict[str, object]] = [
        {
            "type": "reasoning",
            "id": "reasoning_1",
            "encrypted_content": "opaque",
            "content": [],
            "summary": [],
        },
        {
            "type": "function_call",
            "name": tool_name,
            "call_id": "call_1",
            "arguments": json.dumps(arguments, separators=(",", ":"), sort_keys=True),
        },
    ]
    provider_state = _provider_state(provider, initial_input=task, items=items)
    recorder = RuntimeContinuationRecorder(
        state_dir=root,
        state=state,
        provider_name="openai",
        provider_model=provider.model,
        registry_digest=reviewed_registry_digest(),
        advertised_tool_names=frozenset(tool.name for tool in REVIEWED_TOOLS),
        ttl_seconds=900,
        mcp_generation=1,
    )
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn(
            run_id,
            "turn_1",
            "response_1",
            "",
            (call,),
            ModelUsage(input_tokens=10, output_tokens=4),
        ),
        provider_state=provider_state,
        checkpoint_sequence=3,
    )
    images = (
        (
            ImageContent(
                "image/png", base64.b64decode(PNG_BASE64), width=1, height=1
            ),
        )
        if result_kind == "screenshot"
        else ()
    )
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="captured" if images else "Notepad",
        images=images,
    )
    effect = (
        ToolEffect.SIDE_EFFECT
        if mutation == "side_effect_history"
        else ToolEffect.OBSERVATION
    )
    recorder.prepare_tool(state, call, effect=effect, checkpoint_sequence=4)
    recorder.dispatch_tool(state, checkpoint_sequence=5)
    recorder.complete_tool(state, result, checkpoint_sequence=6)
    envelope = read_continuation(root, run_id)
    if mutation == "none" or mutation in {"over_budget", "provider_failure"}:
        return envelope, provider_state, state

    payload = copy.deepcopy(envelope.payload)
    ledger = payload["ledger"]
    output_batches = payload["provider_state"]["output_batches"]
    if mutation == "unknown_output_item":
        output_batches[0]["items"] = [{"type": "unknown_provider_item"}]
    elif mutation == "missing_result":
        payload["ledger"] = [event for event in ledger if event["kind"] != "tool_result"]
    elif mutation == "mismatched_call":
        output_batches[0]["items"][-1] = {
            "type": "function_call",
            "name": "find",
            "call_id": "call_1",
            "arguments": '{"query":"x"}',
        }
    elif mutation == "reordered_batches":
        model_event = next(event for event in ledger if event["kind"] == "model_turn")
        result_event = next(event for event in ledger if event["kind"] == "tool_result")
        second_model = copy.deepcopy(model_event)
        second_model["event_id"] = f"{run_id}:recovery:second_model"
        second_model["data"]["turn_id"] = "turn_2"
        second_model["data"]["provider_response_id"] = "response_2"
        second_model["data"]["tool_calls"][0]["identity"]["turn_id"] = "turn_2"
        second_model["data"]["tool_calls"][0]["identity"]["call_id"] = "call_2"
        second_result = copy.deepcopy(result_event)
        second_result["event_id"] = f"{run_id}:recovery:second_result"
        second_result["data"]["identity"]["turn_id"] = "turn_2"
        second_result["data"]["identity"]["call_id"] = "call_2"
        payload["ledger"].extend((second_model, second_result))
        second_items = copy.deepcopy(output_batches[0]["items"])
        second_items[-1]["call_id"] = "call_2"
        output_batches[:] = [
            {"response_id": "response_2", "items": second_items},
            output_batches[0],
        ]
    elif mutation == "side_effect_history":
        payload["boundary"]["next_step"] = "provider_continue"
    else:
        raise AssertionError("unsupported replay evaluation mutation")
    mutated = write_continuation(root / mutation, payload)
    return mutated, copy.deepcopy(payload["provider_state"]), state


def _cases() -> list[dict[str, object]]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(value) == {"version", "cases"}
    assert value["version"] == 1
    cases = value["cases"]
    assert isinstance(cases, list)
    assert len(cases) == 9
    identifiers: set[str] = set()
    supported_mutations = {
        "none",
        "unknown_output_item",
        "missing_result",
        "mismatched_call",
        "reordered_batches",
        "side_effect_history",
        "over_budget",
        "provider_failure",
    }
    for case in cases:
        assert isinstance(case, dict)
        assert set(case) == {
            "id",
            "mutation",
            "result_kind",
            "expected_error",
            "expected_provider_calls",
            "expected_remote_response_id",
        }
        identifier = case["id"]
        assert isinstance(identifier, str) and identifier and identifier not in identifiers
        identifiers.add(identifier)
        assert case["mutation"] in supported_mutations
        assert case["result_kind"] in {"text", "screenshot"}
        assert case["expected_error"] is None or isinstance(
            case["expected_error"], str
        )
        assert case["expected_provider_calls"] in {0, 1}
        assert case["expected_remote_response_id"] in {"response_1", "response_2"}
    return cases


def test_e2_stateless_replay_fixture_is_canonical_and_frozen() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    canonical = json.dumps(
        fixture, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest == {
        "version": 1,
        "sha256": {FIXTURE.name: hashlib.sha256(canonical).hexdigest()},
    }


@pytest.mark.parametrize("case", _cases(), ids=lambda case: str(case["id"]))
def test_e2_stateless_replay_matrix_is_exact_and_fail_closed(
    case: dict[str, object], tmp_path: Path
) -> None:
    mutation = str(case["mutation"])
    responses = RecordingResponses(fail=mutation == "provider_failure")
    max_request_bytes = 1_000 if mutation == "over_budget" else 8 * 1024 * 1024
    provider = OpenAIResponsesProvider(
        model="test-model",
        responses=responses,
        max_request_bytes=max_request_bytes,
    )
    envelope, provider_state, _ = _artifact(
        tmp_path,
        provider,
        result_kind=str(case["result_kind"]),
        mutation=mutation,
    )
    provider.restore_continuation("run_replay_eval", provider_state)
    before = provider.export_continuation("run_replay_eval")
    error = case["expected_error"]

    if error is None:
        provider.prepare_stateless_replay("run_replay_eval", envelope)
        asyncio.run(
            provider.create_turn(
                run_id="run_replay_eval",
                turn_id="turn_2",
                task="must not replace exact input",
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )
    else:
        with pytest.raises(OpenAIProviderError, match=str(error)):
            provider.prepare_stateless_replay("run_replay_eval", envelope)
            asyncio.run(
                provider.create_turn(
                    run_id="run_replay_eval",
                    turn_id="turn_2",
                    task="Inspect",
                    ledger=(),
                    tools=REVIEWED_TOOLS,
                )
            )

    assert len(responses.calls) == case["expected_provider_calls"]
    exported = provider.export_continuation("run_replay_eval")
    assert exported["response_id"] == case["expected_remote_response_id"]
    if error is not None:
        assert exported == before
    if responses.calls:
        assert "previous_response_id" not in responses.calls[0]
    if error is None:
        compiled = responses.calls[0]["input"]
        assert compiled[0] == {"role": "user", "content": "Inspect"}
        assert compiled[-1]["type"] == "function_call_output"
        if case["result_kind"] == "screenshot":
            assert compiled[-1]["output"][1]["image_url"] == (
                f"data:image/png;base64,{PNG_BASE64}"
            )


def test_recovery_executor_switches_only_after_replay_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    config = AgentConfig(
        state_dir=local / "computer-use-agent" / "replay-eval",
        policy_version="policy-v1",
        provider=ProviderConfig("openai", "test-model"),
        mcp=MCPLaunchConfig(tmp_path / "mcp.exe", (), tmp_path, {}),
        policy=PolicyConfig(max_model_turns=4, max_tool_calls=4),
        continuation=ContinuationConfig(enabled=True),
    )
    responses = RecordingResponses()
    provider = OpenAIResponsesProvider(model="test-model", responses=responses)
    envelope, _, state = _artifact(
        config.state_dir, provider, result_kind="text", mutation="none"
    )
    desktop = FakeDesktopMCP()
    commits: list[tuple[int, str, ReconstructionAction]] = []
    checkpoint = {
        "run_id": state.run_id,
        "policy_version": state.policy_version,
        "task_length": len(state.task),
        "checkpoint_sequence": 6,
    }
    plan = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)
    assert plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER

    def commit(sequence: int, operation_id: str, action: ReconstructionAction) -> None:
        assert responses.calls == []
        assert desktop.tool_calls == []
        commits.append((sequence, operation_id, action))

    step = asyncio.run(
        execute_read_only_recovery_step(
            checkpoint,
            envelope,
            config,
            task=state.task,
            provider=provider,
            desktop=desktop,
            commit_intent=commit,
            use_stateless_replay=True,
        )
    )

    assert commits == [
        (6, "run_replay_eval:turn_2:provider", ReconstructionAction.CONTINUE_PROVIDER)
    ]
    assert len(responses.calls) == 1
    assert desktop.tool_calls == []
    assert step.model_turn is not None
    assert step.model_turn.provider_response_id == "response_2"
