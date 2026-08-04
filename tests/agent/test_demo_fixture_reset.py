from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from computer_use_agent.demo_workflow_progress import DemoWorkflowProgress
from computer_use_agent.decision_cards import DecisionSelection
from computer_use_agent.disposable_process import ProcessWindowSnapshot
from computer_use_agent.fakes import FakeProgressWindowApi
from computer_use_agent.progress_window import PassiveProgressWindow
from computer_use_agent.types import (
    ApprovalBinding,
    ApprovalRequest,
    CallIdentity,
    PolicyDecision,
    PolicyDecisionKind,
    ToolCall,
)


def _offline_workflow_progress() -> DemoWorkflowProgress:
    """The real workflow HUD over a recording fake, so the wiring is exercised.

    Nothing here starts the worker thread: these tests never deliver a run
    phase, so no native call and no window can occur.
    """

    return DemoWorkflowProgress(
        PassiveProgressWindow(FakeProgressWindowApi()),
        pump=lambda: None,
    )


class _OfflineProbe:
    """Stand in for the presence probe without opening a native window."""

    def report(self) -> dict[str, object]:
        return {"projection_count": 0, "samples_painted": 0}


def _offline_presence() -> tuple[object, _OfflineProbe]:
    return object(), _OfflineProbe()


def test_demo_starts_and_releases_presence_around_fixture_preparation() -> None:
    demo = _load_demo_script()

    class RecordingPresence:
        def __init__(self) -> None:
            self.phases: list[object] = []
            self.releases = 0

        def on_phase(self, phase: object) -> None:
            self.phases.append(phase)

        def release(self) -> None:
            self.releases += 1

    presence = RecordingPresence()
    demo._start_presence_while_preparing(presence)
    demo._release_presence(presence)

    assert presence.phases == [demo.RunPhase.PLANNING]
    assert presence.releases == 1


def _approval_request() -> ApprovalRequest:
    call = ToolCall(
        CallIdentity("run_1", "turn_1", "call_1"),
        "activate_window",
        {"window_id": "101"},
    )
    return ApprovalRequest.from_tool_call(
        request_id="approval_1",
        call=call,
        reason="side_effect_requires_local_approval",
        sensitive_arguments=(),
        binding=ApprovalBinding(
            "run_1", *(f"{index:x}" * 64 for index in range(1, 7))
        ),
    )


class _ApprovalSequence:
    focus_taking = True

    def __init__(self, *kinds: PolicyDecisionKind) -> None:
        self.kinds = list(kinds)

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        return PolicyDecision(
            request.request_id,
            request.identity,
            request.call_digest,
            self.kinds.pop(0),
            "test_operator",
        )


class _PauseSurface:
    def __init__(self, *option_ids: str) -> None:
        self.option_ids = list(option_ids)
        self.cards: list[object] = []

    async def choose(self, card: object, *, timeout_seconds: int) -> DecisionSelection:
        del timeout_seconds
        self.cards.append(card)
        return DecisionSelection(
            card.decision_id,  # type: ignore[attr-defined]
            card.card_digest,  # type: ignore[attr-defined]
            self.option_ids.pop(0),
        )


def test_demo_defer_keeps_the_action_paused_until_explicit_resume() -> None:
    demo = _load_demo_script()
    context: list[object | None] = [None]
    surface = _PauseSurface("option_defer", "option_resume")
    approvals = demo.DemoDecisionCards(
        _ApprovalSequence(PolicyDecisionKind.DEFER, PolicyDecisionKind.ALLOW),
        pause_surface=surface,
        step_context=context,
        clock=lambda: datetime(2026, 8, 3, tzinfo=UTC),
    )
    request = _approval_request()

    resumed = asyncio.run(approvals.request_approval(request))

    assert resumed.kind is PolicyDecisionKind.REOBSERVE
    assert resumed.reason == "demo_resume_requires_reobservation"
    assert len(surface.cards) == 2
    assert [option.kind.value for option in surface.cards[0].options] == [  # type: ignore[attr-defined]
        "resume",
        "defer",
        "deny",
    ]
    assert context[0].current == 1  # type: ignore[attr-defined]

    allowed = asyncio.run(approvals.request_approval(request))

    assert allowed.kind is PolicyDecisionKind.ALLOW
    assert context[0].current == 1  # type: ignore[attr-defined]


def test_demo_reobserve_and_deny_do_not_consume_an_approval_number() -> None:
    demo = _load_demo_script()
    context: list[object | None] = [None]
    approvals = demo.DemoDecisionCards(
        _ApprovalSequence(
            PolicyDecisionKind.REOBSERVE,
            PolicyDecisionKind.DENY,
            PolicyDecisionKind.ALLOW,
        ),
        step_context=context,
    )
    request = _approval_request()

    assert (
        asyncio.run(approvals.request_approval(request)).kind
        is PolicyDecisionKind.REOBSERVE
    )
    assert context[0].current == 1  # type: ignore[attr-defined]
    assert (
        asyncio.run(approvals.request_approval(request)).kind
        is PolicyDecisionKind.DENY
    )
    assert context[0].current == 1  # type: ignore[attr-defined]
    assert (
        asyncio.run(approvals.request_approval(request)).kind
        is PolicyDecisionKind.ALLOW
    )
    assert context[0].current == 1  # type: ignore[attr-defined]


def _load_demo_script() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "demo_cross_app.py"
    spec = importlib.util.spec_from_file_location("demo_cross_app_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _minimal_docx(path: Path, text: str = "Clean research template") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r>'
                f"<w:t>{text}</w:t>"
                "</w:r></w:p></w:body></w:document>"
            ),
        )


def test_each_demo_run_starts_from_a_fresh_profile_and_template(
    tmp_path: Path,
) -> None:
    demo = _load_demo_script()
    template = tmp_path / "demo_templates" / "word-collaboration-research.docx"
    _minimal_docx(template)
    demo.ROOT = tmp_path
    demo.WORD_TEMPLATE = template

    first_document, first_profile, first_stamp = demo._fixtures()
    second_document, second_profile, second_stamp = demo._fixtures()

    assert first_stamp != second_stamp
    assert first_document != second_document
    assert first_profile != second_profile
    assert not tuple(first_profile.iterdir())
    assert not tuple(second_profile.iterdir())
    assert first_document.read_bytes() == template.read_bytes()
    assert second_document.read_bytes() == template.read_bytes()
    for document in (first_document, second_document):
        state = json.loads((document.parent / "initial-state.json").read_text())
        assert state["browser_profile_empty"] is True
        assert state["document_marker_present"] is False
        assert state["browser_window"] == {
            "height": 900,
            "width": 1280,
            "x": 80,
            "y": 80,
        }
        assert state["cleanup_contract"] == {
            "on_exit": "close_exact_launched_process_windows",
            "owned_dialog": "operator_handoff",
            "scope": "exact_launched_processes_only",
            "stable_zero_observations": 3,
            "unresolved": "record_explicit_handoff",
        }


def test_demo_configures_one_mcp_dispatch_readiness_handshake() -> None:
    demo = _load_demo_script()

    config = demo._config("readiness-contract")
    environment = config.mcp.environment

    assert config.policy.mode == demo.AGENTIC_ACTIONS_MODE
    assert config.policy.require_approval_for_actions is False
    assert environment["CUMCP_HUMAN_IDLE_SECONDS"] == "2.5"
    assert environment["CUMCP_HUMAN_STABLE_SAMPLES"] == "3"
    assert environment["CUMCP_HUMAN_POLL_INTERVAL_SECONDS"] == "0.25"
    assert environment["CUMCP_HUMAN_MAX_WAIT_SECONDS"] == "60.0"
    assert environment["CUMCP_INTERACTION_SPEED"] == "deliberate"
    assert environment["CUMCP_ACTION_FEEDBACK"] == "1"
    assert "CUMCP_TYPE_WAIT_SECONDS" not in environment
    assert hasattr(demo, "DemoDecisionCards")
    assert not hasattr(demo, "HeartbeatDecisionCards")


class _Process:
    def __init__(
        self,
        pid: int,
        *,
        exit_code: int | None = None,
        wait_times_out: bool = False,
        terminate_fails: bool = False,
    ) -> None:
        self.pid = pid
        self.exit_code = exit_code
        self.wait_times_out = wait_times_out
        self.terminate_fails = terminate_fails
        self.terminated = 0
        self.killed = 0

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated += 1
        if self.terminate_fails:
            raise OSError("synthetic")

    def kill(self) -> None:
        self.killed += 1
        self.exit_code = -9

    def wait(self, timeout: float) -> int:
        del timeout
        if self.wait_times_out and not self.killed:
            raise subprocess.TimeoutExpired("synthetic", 0)
        if self.exit_code is None:
            self.exit_code = 0
        return self.exit_code


class _Windows:
    def __init__(
        self,
        states: dict[int, list[int | ProcessWindowSnapshot]],
    ) -> None:
        self.states = {pid: list(values) for pid, values in states.items()}
        self.close_requests: list[int] = []

    def snapshot(self, pid: int) -> ProcessWindowSnapshot:
        values = self.states[pid]
        if len(values) > 1:
            value = values.pop(0)
        else:
            value = values[0]
        if isinstance(value, int):
            return ProcessWindowSnapshot(value, value, 0)
        return value

    def request_close(self, pid: int) -> int:
        self.close_requests.append(pid)
        return 1


def test_fixture_launch_uses_isolated_word_instance_and_exact_process_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _load_demo_script()
    chrome = tmp_path / "chrome.exe"
    word = tmp_path / "winword.exe"
    mcp = tmp_path / "mcp.exe"
    for executable in (chrome, word, mcp):
        executable.write_bytes(b"fixture")
    demo.CHROME = chrome
    demo.WORD = word
    demo.MCP = mcp
    calls: list[list[str]] = []
    processes = [_Process(101), _Process(202)]

    def popen(arguments: list[str]) -> _Process:
        calls.append(arguments)
        return processes[len(calls) - 1]

    monkeypatch.setattr(demo.subprocess, "Popen", popen)
    monkeypatch.setattr(demo.time, "sleep", lambda _seconds: None)

    launched = demo._launch_fixtures(
        "https://example.invalid/source",
        tmp_path / "fixture.docx",
        tmp_path / "profile",
        windows=_Windows({101: [1], 202: [1]}),
    )

    assert [item.application for item in launched] == [
        "Microsoft Word",
        "Google Chrome",
    ]
    assert [item.process.pid for item in launched] == [101, 202]
    assert calls[0][1:3] == ["/q", "/x"]
    assert f"--user-data-dir={tmp_path / 'profile'}" in calls[1]


def test_fixture_launch_waits_until_both_exact_process_windows_are_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _load_demo_script()
    chrome = tmp_path / "chrome.exe"
    word = tmp_path / "winword.exe"
    mcp = tmp_path / "mcp.exe"
    for executable in (chrome, word, mcp):
        executable.write_bytes(b"fixture")
    demo.CHROME = chrome
    demo.WORD = word
    demo.MCP = mcp
    processes = [_Process(101), _Process(202)]
    calls = 0

    def popen(_arguments: list[str]) -> _Process:
        nonlocal calls
        process = processes[calls]
        calls += 1
        return process

    monotonic = iter((0.0, 0.1, 0.2))
    monkeypatch.setattr(demo.subprocess, "Popen", popen)
    monkeypatch.setattr(demo.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(demo.time, "monotonic", lambda: next(monotonic))

    launched = demo._launch_fixtures(
        "https://example.invalid/source",
        tmp_path / "fixture.docx",
        tmp_path / "profile",
        windows=_Windows({101: [0, 1], 202: [0, 1]}),
        readiness_timeout_seconds=1.0,
    )

    assert [item.process.pid for item in launched] == [101, 202]


def test_cleanup_targets_every_exact_process_and_never_uses_process_names() -> None:
    demo = _load_demo_script()
    word = _Process(101, terminate_fails=True)
    chrome = _Process(202, wait_times_out=True)
    launched = (
        demo.LaunchedFixture("Microsoft Word", word),
        demo.LaunchedFixture("Google Chrome", chrome),
    )

    cleanup = demo._cleanup_fixture_processes(
        launched,
        wait_seconds=0.01,
        poll_interval_seconds=0.01,
        sleep=lambda _seconds: None,
        windows=_Windows({101: [0], 202: [1, 1]}),
    )

    assert [(item.application, item.pid, item.disposition) for item in cleanup] == [
        ("Google Chrome", 202, "killed_after_close_timeout"),
        ("Microsoft Word", 101, "handoff_required"),
    ]
    assert chrome.terminated == 1
    assert chrome.killed == 1
    assert word.terminated == 1


def test_cleanup_requests_graceful_close_before_any_process_termination() -> None:
    demo = _load_demo_script()
    word = _Process(101)
    launched = (demo.LaunchedFixture("Microsoft Word", word),)

    cleanup = demo._cleanup_fixture_processes(
        launched,
        sleep=lambda _seconds: None,
        windows=_Windows({101: [1, 0]}),
    )

    assert cleanup == (
        demo.FixtureCleanup(
            application="Microsoft Word",
            pid=101,
            disposition="windows_closed",
            exit_code=None,
            close_requests=1,
            window_cleanup_verified=True,
            process_running=True,
        ),
    )
    assert word.terminated == 0
    assert word.killed == 0


@pytest.mark.parametrize(
    ("document_text", "expected_resolution"),
    [
        ("Clean research template", "discarded"),
        ("Clean research template VERIFIED SOURCE BRIEF", "saved"),
    ],
)
def test_operator_handoff_records_save_or_discard_after_stable_window_exit(
    tmp_path: Path,
    document_text: str,
    expected_resolution: str,
) -> None:
    demo = _load_demo_script()
    document = tmp_path / "fixture.docx"
    _minimal_docx(document, document_text)
    word = _Process(101)
    launched = (demo.LaunchedFixture("Microsoft Word", word),)
    cleanup = (
        demo.FixtureCleanup(
            application="Microsoft Word",
            pid=101,
            disposition="handoff_required",
            exit_code=None,
            close_requests=1,
            window_cleanup_verified=False,
            process_running=True,
        ),
    )

    resolved, handoff = demo._await_operator_handoff_resolution(
        launched,
        cleanup,
        document,
        wait_seconds=0.03,
        poll_interval_seconds=0.01,
        sleep=lambda _seconds: None,
        windows=_Windows({101: [0, 0, 0]}),
    )

    assert handoff == demo.OperatorHandoffResolution(
        detected=True,
        resolved=True,
        resolution=expected_resolution,
        fixture_pids=(101,),
    )
    assert resolved[0].disposition == f"handoff_resolved_{expected_resolution}"
    assert resolved[0].window_cleanup_verified is True
    assert resolved[0].process_running is True


def test_operator_handoff_cancel_or_timeout_remains_unresolved(tmp_path: Path) -> None:
    demo = _load_demo_script()
    document = tmp_path / "fixture.docx"
    _minimal_docx(document)
    word = _Process(101)
    cleanup = (
        demo.FixtureCleanup(
            application="Microsoft Word",
            pid=101,
            disposition="handoff_required",
            exit_code=None,
            close_requests=1,
            window_cleanup_verified=False,
            process_running=True,
        ),
    )

    unresolved, handoff = demo._await_operator_handoff_resolution(
        (demo.LaunchedFixture("Microsoft Word", word),),
        cleanup,
        document,
        wait_seconds=0.02,
        poll_interval_seconds=0.01,
        sleep=lambda _seconds: None,
        windows=_Windows({101: [1]}),
    )

    assert unresolved == cleanup
    assert handoff.resolution == "unresolved"
    assert handoff.resolved is False


def test_partial_launch_failure_cleans_the_process_already_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _load_demo_script()
    chrome = tmp_path / "chrome.exe"
    word = tmp_path / "winword.exe"
    mcp = tmp_path / "mcp.exe"
    for executable in (chrome, word, mcp):
        executable.write_bytes(b"fixture")
    demo.CHROME = chrome
    demo.WORD = word
    demo.MCP = mcp
    process = _Process(101)
    calls = 0

    def popen(_arguments: list[str]) -> _Process:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic launch failure")
        return process

    monkeypatch.setattr(demo.subprocess, "Popen", popen)
    monkeypatch.setattr(demo.time, "sleep", lambda _seconds: None)

    with pytest.raises(OSError):
        demo._launch_fixtures(
            "https://example.invalid/source",
            tmp_path / "fixture.docx",
            tmp_path / "profile",
        )

    assert process.terminated == 1


def test_final_state_declares_cleanup_scope_and_explicit_handoff(
    tmp_path: Path,
) -> None:
    demo = _load_demo_script()
    cleanup = (
        demo.FixtureCleanup(
            application="Google Chrome",
            pid=202,
            disposition="windows_closed",
            exit_code=None,
            close_requests=1,
            window_cleanup_verified=True,
            process_running=True,
        ),
        demo.FixtureCleanup(
            application="Microsoft Word",
            pid=101,
            disposition="handoff_required",
            exit_code=None,
            close_requests=0,
            window_cleanup_verified=False,
            process_running=True,
        ),
    )

    demo._write_final_state(
        tmp_path,
        run_id="cross-app-demo-test",
        document_name="fixture.docx",
        profile_name="chrome-profile",
        permission_mode=demo.AGENTIC_ACTIONS_MODE,
        outcome="failed",
        failure_class="RuntimeError",
        cleanup=cleanup,
    )

    state = json.loads((tmp_path / "final-state.json").read_text())
    assert state == {
        "all_processes_exited": False,
        "cleanup_scope": "exact_launched_processes_only",
        "failure_class": "RuntimeError",
        "fixture_identity": {
            "browser_profile": "chrome-profile",
            "document": "fixture.docx",
        },
        "fixtures": [
            {
                "application": "Google Chrome",
                "close_requests": 1,
                "disposition": "windows_closed",
                "exit_code": None,
                "pid": 202,
                "process_running": True,
                "window_cleanup_verified": True,
            },
            {
                "application": "Microsoft Word",
                "close_requests": 0,
                "disposition": "handoff_required",
                "exit_code": None,
                "pid": 101,
                "process_running": True,
                "window_cleanup_verified": False,
            },
        ],
        "outcome": "failed",
        "operator_handoff": {
            "detected": True,
            "fixture_pids": [101],
            "resolution": "unresolved",
            "resolved": False,
        },
        "operator_handoff_required": True,
        "permission_mode": "agentic_actions",
        "proposal_rejections": [],
        "run_id": "cross-app-demo-test",
        "schema_version": 3,
        "window_cleanup_complete": False,
    }


@pytest.mark.parametrize(
    ("raised", "expected_outcome"),
    [
        (RuntimeError("synthetic failure"), "failed"),
        (asyncio.CancelledError(), "cancelled"),
    ],
)
def test_run_cleans_exact_fixtures_and_records_failure_or_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raised: BaseException,
    expected_outcome: str,
) -> None:
    demo = _load_demo_script()
    document = tmp_path / "fixture.docx"
    _minimal_docx(document)
    profile = tmp_path / "profile"
    profile.mkdir()
    processes = (_Process(101), _Process(202))
    launched = (
        demo.LaunchedFixture("Microsoft Word", processes[0]),
        demo.LaunchedFixture("Google Chrome", processes[1]),
    )

    class FailingRunner:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def run(self, *_args: object, **_kwargs: object) -> object:
            raise raised

    def launch(
        *_args: object,
        ownership: list[object],
        **_kwargs: object,
    ) -> tuple[object, ...]:
        ownership.extend(launched)
        return launched

    monkeypatch.setattr(demo, "_fixtures", lambda: (document, profile, "test"))
    monkeypatch.setattr(demo, "_launch_fixtures", launch)
    monkeypatch.setattr(demo, "_presence", _offline_presence)
    monkeypatch.setattr(demo, "_progress", _offline_workflow_progress)
    monkeypatch.setattr(
        demo,
        "DecisionCardApprovalPort",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        demo,
        "DecisionCardWindow",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        demo,
        "Win32DecisionCardWindowApi",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(demo, "AgentRunner", FailingRunner)

    with pytest.raises(type(raised)):
        asyncio.run(demo._run())

    state = json.loads((tmp_path / "final-state.json").read_text())
    assert state["outcome"] == expected_outcome
    assert state["failure_class"] == type(raised).__name__
    assert state["permission_mode"] == "agentic_actions"
    assert state["window_cleanup_complete"] is True
    assert state["all_processes_exited"] is True
    assert state["operator_handoff_required"] is False
    assert [item["pid"] for item in state["fixtures"]] == [202, 101]
    assert all(process.terminated == 1 for process in processes)


def test_run_records_normal_completion_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _load_demo_script()
    document = tmp_path / "fixture.docx"
    _minimal_docx(document, demo.SUMMARY)
    profile = tmp_path / "profile"
    profile.mkdir()
    processes = (_Process(101), _Process(202))
    launched = (
        demo.LaunchedFixture("Microsoft Word", processes[0]),
        demo.LaunchedFixture("Google Chrome", processes[1]),
    )
    runner_outcome = SimpleNamespace(
        text=demo.DEMO_COMPLETE_TEXT,
        state=SimpleNamespace(
            run_id="cross-app-demo-test",
            budgets=SimpleNamespace(side_effects_used=7, tool_calls_used=17),
        ),
    )

    class PassingRunner:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def run(self, *_args: object, **_kwargs: object) -> object:
            return runner_outcome

    def launch(
        *_args: object,
        ownership: list[object],
        **_kwargs: object,
    ) -> tuple[object, ...]:
        ownership.extend(launched)
        return launched

    monkeypatch.setattr(demo, "_fixtures", lambda: (document, profile, "test"))
    monkeypatch.setattr(demo, "_launch_fixtures", launch)
    monkeypatch.setattr(demo, "_presence", _offline_presence)
    monkeypatch.setattr(demo, "_progress", _offline_workflow_progress)
    monkeypatch.setattr(
        demo,
        "DecisionCardApprovalPort",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(demo, "DecisionCardWindow", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(demo, "Win32DecisionCardWindowApi", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(demo, "AgentRunner", PassingRunner)

    result = asyncio.run(demo._run())

    assert result["result"] == "PASS"
    assert [item["pid"] for item in result["fixture_cleanup"]] == [202, 101]
    state = json.loads((tmp_path / "final-state.json").read_text())
    assert state["outcome"] == "passed"
    assert state["failure_class"] is None
    assert state["permission_mode"] == "agentic_actions"
    assert state["window_cleanup_complete"] is True
    assert state["all_processes_exited"] is True
    assert state["operator_handoff_required"] is False


def test_the_demo_gives_its_presence_halo_a_message_pump() -> None:
    """The exact wiring whose absence made the halo invisible for every run.

    `_presence()` built a coordinator with no pump, so the halo window was
    created and shown but never received WM_PAINT. It drew no border and no
    phase tab, and a colour-keyed layered window that never paints is fully
    transparent. Two complete Demo runs passed with an operator watching and
    neither showed a halo.
    """

    demo = _load_demo_script()
    coordinator, probe = demo._presence()

    assert coordinator.pump is not None, "the halo would never paint"
    assert callable(coordinator.pump)
    report = probe.report()
    assert "samples_painted" in report
    assert "projection_sequence" in report
