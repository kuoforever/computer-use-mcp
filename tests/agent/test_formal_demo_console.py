from __future__ import annotations

import ast
import builtins
import copy
import pickle
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import computer_use_agent.formal_demo_console as console_module
from computer_use_agent.formal_demo_console import (
    FormalDemoConsoleCallbacks,
    FormalDemoConsoleError,
    FormalDemoConsoleSession,
    FormalDemoConsoleStage,
    FormalDemoConsoleView,
    FormalDemoConsoleWindow,
    FormalDemoConsoleWindowApi,
    build_console_route,
)


SECRET = "sk-console-secret-must-stay-local"


class Identities:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"attempt-{self.value:03d}"


def _session() -> FormalDemoConsoleSession:
    return FormalDemoConsoleSession(
        build_console_route(provider_id="openai", model_id="gpt-reviewed"),
        identity_factory=Identities(),
    )


@pytest.mark.parametrize(
    "route_arguments",
    (
        {"provider_id": "openai", "model_id": "reviewed-model"},
        {"provider_id": "anthropic", "model_id": "reviewed-model"},
        {"provider_id": "doubao", "model_id": "reviewed-model"},
        {"provider_id": "kimi", "model_id": "reviewed-model"},
        {"provider_id": "deepseek", "model_id": "reviewed-model"},
        {"provider_id": "glm", "model_id": "reviewed-model"},
        {"provider_id": "minimax", "model_id": "reviewed-model"},
        {
            "provider_id": "qwen",
            "model_id": "reviewed-model",
            "region": "cn-beijing",
            "workspace_id": "workspace-demo",
        },
        {
            "provider_id": "local_openai",
            "model_id": "reviewed-model",
            "base_url": "http://127.0.0.1:11434/v1",
        },
    ),
)
def test_all_reviewed_routes_build_without_provider_sdk_import(
    route_arguments: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def checked_import(name, *args, **kwargs):  # noqa: ANN001, ANN202
        if name.split(".", 1)[0] in {"openai", "anthropic"}:
            raise AssertionError("Review-only route imported a provider SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    route = build_console_route(**route_arguments)
    session = FormalDemoConsoleSession(route, identity_factory=Identities())

    assert session.view().provider_id == route_arguments["provider_id"]
    assert not session.view().start_enabled


class FakeConsoleApi:
    def __init__(self) -> None:
        self.callbacks: FormalDemoConsoleCallbacks | None = None
        self.task = ""
        self.acknowledgement = ""
        self.views: list[FormalDemoConsoleView] = []
        self.calls: list[str] = []
        self.alive = False

    def create(self, *, title: str, callbacks: FormalDemoConsoleCallbacks) -> int:
        assert title
        self.callbacks = callbacks
        self.alive = True
        self.calls.append("create")
        return 71

    def apply(self, hwnd: int, view: FormalDemoConsoleView) -> None:
        assert hwnd == 71
        self.views.append(view)
        self.calls.append("apply")

    def read_task(self, hwnd: int) -> str:
        assert hwnd == 71
        return self.task

    def read_acknowledgement(self, hwnd: int) -> str:
        assert hwnd == 71
        return self.acknowledgement

    def focus_task(self, hwnd: int) -> None:
        assert hwnd == 71
        self.calls.append("focus_task")

    def show(self, hwnd: int) -> None:
        assert hwnd == 71
        self.calls.append("show")

    def run(self, hwnd: int) -> int:
        assert hwnd == 71
        self.calls.append("run")
        return 0

    def destroy(self, hwnd: int) -> None:
        assert hwnd == 71
        self.alive = False
        self.calls.append("destroy")


def test_review_only_session_starts_with_all_authority_false() -> None:
    view = _session().view()

    assert view.stage is FormalDemoConsoleStage.DRAFT
    assert view.review_enabled
    assert view.task_editable
    assert not view.acknowledgement_enabled
    assert not view.start_enabled
    assert not view.scope_available
    assert "readiness unchecked" in view.route_text
    assert "Scope Sheet: unavailable" in view.detail_text
    assert "External work started: no" in view.detail_text


def test_all_five_role_profiles_are_honest_design_bindings() -> None:
    summaries = _session().view().role_summaries

    assert [summary.role for summary in summaries] == [
        "source",
        "evidence",
        "analysis",
        "report",
        "handoff",
    ]
    assert all("readiness" in summary.note for summary in summaries[:4])
    assert summaries[-1].binding_state == "unselected"
    assert "blocks" in summaries[-1].note


def test_review_preserves_exact_local_task_and_issues_no_scope_or_start() -> None:
    source = f"Use literal local text {SECRET}.\r\nKeep trailing spaces.  "
    session = _session()

    view = session.review(source)

    assert view.stage is FormalDemoConsoleStage.DISCLOSURE_READY
    assert view.task_text == source
    assert SECRET in view.disclosure_text
    assert "nothing external has started" in view.disclosure_text
    assert "Scope Sheet: unavailable" in view.detail_text
    assert not view.start_enabled
    assert not view.scope_available
    assert SECRET not in repr(session)
    assert SECRET not in repr(view)


@pytest.mark.parametrize(
    "source",
    (
        "",
        " ",
        "bad\x00task",
        "a" * 8193,
        "界" * 2731,
        "\ud800",
    ),
)
def test_invalid_drafts_fail_with_content_free_codes(source: str) -> None:
    session = _session()
    view = session.review(source + SECRET if source == "bad\x00task" else source)

    assert view.stage is FormalDemoConsoleStage.DRAFT
    assert view.validation_code is not None
    assert SECRET not in view.validation_code
    assert SECRET not in repr(view)
    assert not view.start_enabled


def test_utf8_boundary_and_display_escaping_are_exact() -> None:
    exact_ascii = "a" * 8192
    exact_multibyte = "界" * 2730 + "ab"
    separators = "first\nsecond\u2028third\u202efourth"

    assert _session().review(exact_ascii).stage is FormalDemoConsoleStage.DISCLOSURE_READY
    assert _session().review(exact_multibyte).stage is FormalDemoConsoleStage.DISCLOSURE_READY
    rendered = _session().review(separators).disclosure_text
    assert separators not in rendered
    assert "\\n" in rendered
    assert "\\u2028" in rendered
    assert "\\u202e" in rendered


def test_only_exact_compile_issues_one_inert_permit() -> None:
    session = _session()
    session.review("Prepare a local review only.")

    view = session.acknowledge("COMPILE")

    assert view.stage is FormalDemoConsoleStage.PERMIT_ISSUED
    assert "inert process-local COMPILE permit" in view.detail_text
    assert not view.start_enabled
    assert not view.scope_available
    assert not hasattr(session, "consume")
    assert not hasattr(session, "start")
    assert not hasattr(session, "dispatch")


@pytest.mark.parametrize(
    "token",
    ("compile", "Compile", " COMPILE", "COMPILE ", "COMPILE\n", "", None, True),
)
def test_wrong_acknowledgement_is_terminal_and_never_enables_start(token: object) -> None:
    session = _session()
    session.review("Review this exact task.")

    view = session.acknowledge(token)

    assert view.stage is FormalDemoConsoleStage.CANCELLED
    assert view.validation_code == "FORMAL_DEMO_INTENT_ACKNOWLEDGEMENT_INVALID"
    assert not view.start_enabled
    assert session.acknowledge("COMPILE").stage is FormalDemoConsoleStage.CANCELLED


def test_concurrent_acknowledgement_has_only_one_permit_state() -> None:
    session = _session()
    session.review("Review this exact task.")

    with ThreadPoolExecutor(max_workers=8) as pool:
        views = list(pool.map(lambda _index: session.acknowledge("COMPILE"), range(8)))

    assert sum(view.validation_code is None for view in views) == 1
    assert sum(
        view.validation_code == "FORMAL_DEMO_INTENT_GATE_TERMINAL"
        for view in views
    ) == 7
    assert all(view.stage is FormalDemoConsoleStage.PERMIT_ISSUED for view in views)
    assert session.stage is FormalDemoConsoleStage.PERMIT_ISSUED
    assert all(not view.start_enabled for view in views)


def test_reset_abandons_disclosure_or_permit_and_requires_new_identity() -> None:
    identities = Identities()
    session = FormalDemoConsoleSession(
        build_console_route(provider_id="openai", model_id="gpt-reviewed"),
        identity_factory=identities,
    )
    first = session.review("First exact task.")
    session.acknowledge("COMPILE")

    reset = session.reset()
    second = session.review("Second exact task.")

    assert reset.stage is FormalDemoConsoleStage.DRAFT
    assert reset.task_text == ""
    assert first.disclosure_text != second.disclosure_text
    assert "attempt-001" in first.disclosure_text
    assert "attempt-002" in second.disclosure_text
    assert identities.value == 2


def test_cancel_drops_sensitive_local_state_without_consuming() -> None:
    session = _session()
    session.review(f"Review {SECRET}.")
    session.acknowledge("COMPILE")

    cancelled = session.cancel()

    assert cancelled.stage is FormalDemoConsoleStage.CANCELLED
    assert cancelled.task_text == ""
    assert cancelled.disclosure_text == ""
    assert SECRET not in cancelled.detail_text
    assert not cancelled.start_enabled


def test_view_and_session_cannot_be_copied_or_pickled() -> None:
    session = _session()
    view = session.review(f"Review {SECRET}.")

    for operation in (
        lambda: copy.copy(session),
        lambda: copy.deepcopy(session),
        lambda: pickle.dumps(session),
        lambda: copy.copy(view),
        lambda: copy.deepcopy(view),
        lambda: pickle.dumps(view),
    ):
        with pytest.raises(FormalDemoConsoleError):
            operation()


def test_window_api_has_no_start_callback_and_drives_only_review_compile_reset_cancel() -> None:
    api = FakeConsoleApi()
    assert isinstance(api, FormalDemoConsoleWindowApi)
    window = FormalDemoConsoleWindow(_session(), api)
    window.open()
    assert api.callbacks is not None
    assert not hasattr(api.callbacks, "on_start")

    api.task = "Review this local task."
    api.callbacks.on_review()
    assert api.views[-1].stage is FormalDemoConsoleStage.DISCLOSURE_READY

    api.acknowledgement = "COMPILE"
    api.callbacks.on_acknowledge()
    assert api.views[-1].stage is FormalDemoConsoleStage.PERMIT_ISSUED
    assert not api.views[-1].start_enabled

    api.callbacks.on_reset()
    assert api.views[-1].stage is FormalDemoConsoleStage.DRAFT
    api.callbacks.on_cancel()
    assert not api.alive


def test_window_open_failure_cancels_and_clears_sensitive_state() -> None:
    class ApplyFailureApi(FakeConsoleApi):
        def apply(self, hwnd: int, view: FormalDemoConsoleView) -> None:
            raise RuntimeError(SECRET)

    session = _session()
    session.review(f"Review {SECRET}.")
    api = ApplyFailureApi()

    with pytest.raises(
        FormalDemoConsoleError,
        match="^FORMAL_DEMO_CONSOLE_WINDOW_FAILED$",
    ) as caught:
        FormalDemoConsoleWindow(session, api).open()

    assert SECRET not in str(caught.value)
    assert not api.alive
    assert session.view().stage is FormalDemoConsoleStage.CANCELLED
    assert session.view().task_text == ""


def test_window_run_failure_closes_and_clears_sensitive_state() -> None:
    class RunFailureApi(FakeConsoleApi):
        def run(self, hwnd: int) -> int:
            raise RuntimeError(SECRET)

    session = _session()
    session.review(f"Review {SECRET}.")
    api = RunFailureApi()

    with pytest.raises(
        FormalDemoConsoleError,
        match="^FORMAL_DEMO_CONSOLE_WINDOW_FAILED$",
    ) as caught:
        FormalDemoConsoleWindow(session, api).run()

    assert SECRET not in str(caught.value)
    assert not api.alive
    assert session.view().stage is FormalDemoConsoleStage.CANCELLED
    assert session.view().task_text == ""


def test_window_run_reapply_failure_closes_and_clears_sensitive_state() -> None:
    class ReapplyFailureApi(FakeConsoleApi):
        fail_apply = False

        def apply(self, hwnd: int, view: FormalDemoConsoleView) -> None:
            if self.fail_apply:
                raise RuntimeError(SECRET)
            super().apply(hwnd, view)

    session = _session()
    api = ReapplyFailureApi()
    window = FormalDemoConsoleWindow(session, api)
    window.open()
    session.review(f"Review {SECRET}.")
    api.fail_apply = True

    with pytest.raises(
        FormalDemoConsoleError,
        match="^FORMAL_DEMO_CONSOLE_WINDOW_FAILED$",
    ) as caught:
        window.run()

    assert SECRET not in str(caught.value)
    assert not api.alive
    assert window.hwnd is None
    assert session.view().stage is FormalDemoConsoleStage.CANCELLED
    assert session.view().task_text == ""


def test_controller_modules_have_no_provider_execution_or_persistence_wiring() -> None:
    source_path = Path(console_module.__file__ or "")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_text = (
        "AgentRunner",
        "StdioDesktopMCP",
        "WindowsDriver",
        "compile_task_intent_once",
        "formal_demo_intent_request",
        "provider_factory",
        "computer_use_agent.providers",
        "os.environ",
        "getenv",
        "socket",
        "subprocess",
        "telemetry",
        "trace",
    )
    assert all(value not in source for value in forbidden_text)
    assert ".consume(" not in source
    forbidden_imports = {"asyncio", "pathlib", "socket", "subprocess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not ({item.name for item in node.names} & forbidden_imports)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in forbidden_imports
