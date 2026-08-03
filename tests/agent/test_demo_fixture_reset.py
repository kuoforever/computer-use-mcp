from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from computer_use_agent.demo_workflow_progress import DemoWorkflowProgress
from computer_use_agent.fakes import FakeProgressWindowApi
from computer_use_agent.progress_window import PassiveProgressWindow


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
            "on_exit": "close_exact_owned_windows",
            "scope": "exact_launched_processes_only",
            "unresolved": "record_explicit_handoff",
        }


def test_demo_configures_one_mcp_dispatch_readiness_handshake() -> None:
    demo = _load_demo_script()

    config = demo._config("readiness-contract")
    environment = config.mcp.environment

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
    def __init__(self, states: dict[int, list[int]]) -> None:
        self.states = {pid: list(values) for pid, values in states.items()}
        self.close_requests: list[int] = []

    def visible_count(self, pid: int) -> int:
        values = self.states[pid]
        if len(values) > 1:
            return values.pop(0)
        return values[0]

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
    )

    assert [item.application for item in launched] == [
        "Microsoft Word",
        "Google Chrome",
    ]
    assert [item.process.pid for item in launched] == [101, 202]
    assert calls[0][1:3] == ["/q", "/x"]
    assert f"--user-data-dir={tmp_path / 'profile'}" in calls[1]


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
            "Microsoft Word",
            101,
            "windows_closed",
            None,
            1,
            True,
        ),
    )
    assert word.terminated == 0
    assert word.killed == 0


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
            "Google Chrome",
            202,
            "windows_closed",
            None,
            1,
            True,
        ),
        demo.FixtureCleanup(
            "Microsoft Word",
            101,
            "handoff_required",
            None,
            0,
            True,
        ),
    )

    demo._write_final_state(
        tmp_path,
        run_id="cross-app-demo-test",
        document_name="fixture.docx",
        profile_name="chrome-profile",
        outcome="failed",
        failure_class="RuntimeError",
        cleanup=cleanup,
    )

    state = json.loads((tmp_path / "final-state.json").read_text())
    assert state == {
        "cleanup_complete": False,
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
            },
            {
                "application": "Microsoft Word",
                "close_requests": 0,
                "disposition": "handoff_required",
                "exit_code": None,
                "pid": 101,
                "process_running": True,
            },
        ],
        "outcome": "failed",
        "run_id": "cross-app-demo-test",
        "schema_version": 1,
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
    assert state["cleanup_complete"] is True
    assert [item["pid"] for item in state["fixtures"]] == [202, 101]
    assert all(process.terminated == 1 for process in processes)


def test_run_records_normal_completion_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = _load_demo_script()
    document = tmp_path / "fixture.docx"
    _minimal_docx(document, demo.DEMO_TYPED_MARKER)
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
    assert state["cleanup_complete"] is True


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
