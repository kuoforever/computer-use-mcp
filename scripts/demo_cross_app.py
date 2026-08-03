"""Run the real Chrome-to-Word interview Demo on disposable local fixtures.

Fixture setup launches installed applications, but every observed or mutating
desktop operation is requested through AgentRunner and StdioDesktopMCP.
"""

from __future__ import annotations

import asyncio
import argparse
import ctypes
import threading
from collections.abc import Callable, Sequence
from dataclasses import asdict
import hashlib
import json
import shutil
import subprocess
import sys
import time
import zipfile
from ctypes import wintypes
from xml.etree import ElementTree
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from computer_use_agent.approvals import DecisionCardApprovalPort  # noqa: E402
from computer_use_agent.config import (  # noqa: E402
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    MCPLaunchConfig,
    OperatorConfig,
    PolicyConfig,
    ProviderConfig,
    default_state_dir,
)
from computer_use_agent.decision_card_window import (  # noqa: E402
    DecisionCardWindow,
    OperatorStepContext,
)
from computer_use_agent.decision_card_window_win32 import (  # noqa: E402
    Win32DecisionCardWindowApi,
)
from computer_use_agent.demo_cross_app import (  # noqa: E402
    DEMO_COMPLETE_TEXT,
    DEMO_TYPED_MARKER,
    CrossAppDemoProvider,
)
from computer_use_agent.demo_workflow_progress import (  # noqa: E402
    DemoWorkflowProgress,
)
from computer_use_agent.desktop_mcp import StdioDesktopMCP  # noqa: E402
from computer_use_agent.disposable_process import (  # noqa: E402
    DisposableCleanup as FixtureCleanup,
    DisposableProcess as LaunchedFixture,
    ProcessWindows,
    cleanup_disposable_processes,
)
from computer_use_agent.presence import PresencePreferences  # noqa: E402
from computer_use_agent.presence_lifecycle import RunPresenceCoordinator  # noqa: E402
from computer_use_agent.presence_window import PassivePresenceWindow  # noqa: E402
from computer_use_agent.presence_window_win32 import Win32PresenceWindowApi  # noqa: E402
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import Win32ProgressWindowApi  # noqa: E402
from computer_use_agent.runner import AgentRunner, RunnerPorts  # noqa: E402
from computer_use_agent.types import (  # noqa: E402
    ApprovalRequest,
    PolicyDecision,
)

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
WORD = Path(r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE")
MCP = ROOT / ".venv" / "Scripts" / "guarded-desktop-mcp.exe"
WORD_TEMPLATE = ROOT / "demo_templates" / "word-collaboration-research.docx"
HUMAN_IDLE_SECONDS = 2.5
HUMAN_STABLE_SAMPLES = 3
HUMAN_POLL_INTERVAL_SECONDS = 0.25
HUMAN_MAX_WAIT_SECONDS = 60.0
SOURCE_URL = (
    "https://support.microsoft.com/en-US/Word/training/"
    "collaborate-on-word-documents-with-real-time-co-authoring"
)
SOURCE_TITLE = "Collaborate on Word documents with real-time co-authoring"

SUMMARY = (
    "\n\nVERIFIED PORTAL FOLLOW-UP\n"
    "Source: Microsoft Support - Collaborate on Word documents\n"
    "Finding: Word supports real-time co-authoring in a shared document.\n"
    "Workflow: Comments and mentions support review and follow-up.\n"
    "Practical note: Keep changes in one reviewable file instead of extra copies.\n"
)


class DemoDecisionCards:
    """Add trusted Demo context without duplicating dispatch readiness."""

    focus_taking = True

    def __init__(
        self,
        inner: DecisionCardApprovalPort,
        *,
        step_context: list[OperatorStepContext | None],
        workflow: DemoWorkflowProgress | None = None,
    ) -> None:
        self._inner = inner
        self._step_context = step_context
        self._workflow = workflow
        self._approval_index = 0

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        labels = (
            ("Open the public source", "Chrome"),
            ("Scroll to the next article section", "Chrome"),
            ("Switch to the research notes", "Microsoft Word"),
            ("Focus the document editor", "Microsoft Word"),
            ("Move to the follow-up section", "Microsoft Word"),
            ("Type the verified source summary", "Microsoft Word"),
            ("Save and preserve the document", "Microsoft Word"),
        )
        if self._approval_index >= len(labels):
            raise RuntimeError("DEMO_APPROVAL_STEP_OVERFLOW")
        label, application = labels[self._approval_index]
        self._approval_index += 1
        # The workflow breadcrumb and the approval count answer different
        # questions and stay separate: "which chapter" versus "approval n/7".
        self._step_context[0] = OperatorStepContext(
            self._approval_index,
            len(labels),
            label,
            application,
            workflow=None if self._workflow is None else self._workflow.breadcrumb(),
        )
        decision = await self._inner.request_approval(request)
        return decision


def _fixtures() -> tuple[Path, Path, str]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    root = ROOT / "out" / "cross-app-demo" / "runs" / stamp
    root.mkdir(parents=True, exist_ok=False)
    document = root / f"word-collaboration-research-{stamp}.docx"
    profile = root / "chrome-profile"
    profile.mkdir()
    if not WORD_TEMPLATE.is_file():
        raise RuntimeError("DEMO_WORD_TEMPLATE_NOT_FOUND")
    shutil.copy2(WORD_TEMPLATE, document)
    if any(profile.iterdir()):
        raise RuntimeError("DEMO_BROWSER_PROFILE_NOT_CLEAN")
    if document.read_bytes() != WORD_TEMPLATE.read_bytes():
        raise RuntimeError("DEMO_WORD_TEMPLATE_COPY_MISMATCH")
    with zipfile.ZipFile(document) as package:
        document_xml = package.read("word/document.xml")
    initial_text = "".join(ElementTree.fromstring(document_xml).itertext())
    if DEMO_TYPED_MARKER in initial_text:
        raise RuntimeError("DEMO_WORD_TEMPLATE_ALREADY_MODIFIED")
    initial_state = {
        "browser_profile_empty": True,
        "browser_window": {"x": 80, "y": 80, "width": 1280, "height": 900},
        "cleanup_contract": {
            "on_exit": "close_exact_owned_windows",
            "scope": "exact_launched_processes_only",
            "unresolved": "record_explicit_handoff",
        },
        "document_marker_present": False,
        "source_url": SOURCE_URL,
        "template_sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
    }
    (root / "initial-state.json").write_text(
        json.dumps(initial_state, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    return document, profile, stamp


def _launch_fixtures(
    page_url: str,
    document: Path,
    profile: Path,
    *,
    ownership: list[LaunchedFixture] | None = None,
) -> tuple[LaunchedFixture, ...]:
    for executable in (CHROME, WORD, MCP):
        if not executable.is_file():
            raise RuntimeError("DEMO_REQUIRED_EXECUTABLE_NOT_FOUND")
    launched = ownership if ownership is not None else []
    try:
        word = subprocess.Popen([str(WORD), "/q", "/x", str(document)])
        launched.append(LaunchedFixture("Microsoft Word", word))
        time.sleep(3)
        if word.poll() is not None:
            raise RuntimeError("DEMO_WORD_EXITED_DURING_STARTUP")
        chrome = subprocess.Popen(
            [
                str(CHROME),
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-session-crashed-bubble",
                "--disable-sync",
                "--force-renderer-accessibility",
                "--window-position=80,80",
                "--window-size=1280,900",
                "--new-window",
                page_url,
            ]
        )
        launched.append(LaunchedFixture("Google Chrome", chrome))
        time.sleep(5)
        if chrome.poll() is not None:
            raise RuntimeError("DEMO_CHROME_EXITED_DURING_STARTUP")
    except BaseException:
        if ownership is None:
            _cleanup_fixture_processes(launched)
        raise
    return tuple(launched)


def _cleanup_fixture_processes(
    launched: Sequence[LaunchedFixture],
    *,
    wait_seconds: float = 5.0,
    poll_interval_seconds: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
    timeout_error: type[BaseException] = subprocess.TimeoutExpired,
    windows: ProcessWindows | None = None,
) -> tuple[FixtureCleanup, ...]:
    """Apply the shared exact-process, window-first cleanup contract."""

    return cleanup_disposable_processes(
        launched,
        windows=windows,
        wait_seconds=wait_seconds,
        poll_interval_seconds=poll_interval_seconds,
        sleep=sleep,
        timeout_error=timeout_error,
    )


def _write_final_state(
    root: Path,
    *,
    run_id: str,
    document_name: str,
    profile_name: str,
    outcome: str,
    failure_class: str | None,
    cleanup: Sequence[FixtureCleanup],
    presence: dict[str, object] | None = None,
) -> None:
    cleanup_complete = all(
        item.disposition != "handoff_required" for item in cleanup
    )
    state = {
        "schema_version": 1,
        "run_id": run_id,
        "outcome": outcome,
        "failure_class": failure_class,
        "cleanup_complete": cleanup_complete,
        "cleanup_scope": "exact_launched_processes_only",
        "fixture_identity": {
            "browser_profile": profile_name,
            "document": document_name,
        },
        "fixtures": [asdict(item) for item in cleanup],
    }
    if presence is not None:
        state["presence"] = presence
    (root / "final-state.json").write_text(
        json.dumps(state, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )


def _config(
    stamp: str,
    *,
    interaction_speed: str = "deliberate",
    action_feedback: bool = True,
) -> AgentConfig:
    state_dir = default_state_dir() / f"demo-cross-app-{stamp}"
    return AgentConfig(
        state_dir=state_dir,
        policy_version="cross-app-demo-v1",
        provider=ProviderConfig("openai", "controlled-demo-provider"),
        mcp=MCPLaunchConfig(
            executable=MCP.resolve(),
            args=(),
            cwd=ROOT.resolve(),
            environment={
                "CUMCP_ALLOWLIST": "chrome.exe,winword.exe",
                "CUMCP_HUMAN_IDLE_SECONDS": str(HUMAN_IDLE_SECONDS),
                "CUMCP_HUMAN_STABLE_SAMPLES": str(HUMAN_STABLE_SAMPLES),
                "CUMCP_HUMAN_POLL_INTERVAL_SECONDS": str(
                    HUMAN_POLL_INTERVAL_SECONDS
                ),
                "CUMCP_HUMAN_MAX_WAIT_SECONDS": str(
                    HUMAN_MAX_WAIT_SECONDS
                ),
                "CUMCP_INTERACTION_SPEED": interaction_speed,
                "CUMCP_ACTION_FEEDBACK": "1" if action_feedback else "0",
            },
        ),
        policy=PolicyConfig(
            mode=APPROVED_ACTIONS_MODE,
            max_model_turns=20,
            max_tool_calls=17,
            max_side_effects=7,
        ),
        operator=OperatorConfig(
            presence_enabled=True,
            progress_enabled=True,
            decision_cards_enabled=True,
            decision_timeout_seconds=180,
            decision_card_corner="bottom_right",
        ),
    )


class _PresenceProbe:
    """Record what the halo was actually asked to show, and whether it painted.

    Presence is `WDA_EXCLUDEFROMCAPTURE` by design, so it can never appear in a
    screenshot and its evidence would otherwise rest entirely on an operator
    saying they saw it. Two complete runs passed while the halo was in fact
    invisible, because nothing pumped it and a colour-keyed layered window that
    never receives `WM_PAINT` is fully transparent.

    This wraps the surface to record every projection, and samples the native
    window from a separate thread. A window with a pending update region has
    not been painted; an empty update region means it has.
    """

    def __init__(self, window: PassivePresenceWindow) -> None:
        self._window = window
        self._projections: list[dict[str, str]] = []
        self._painted = 0
        self._unpainted = 0
        self._missing = 0
        self._stop = threading.Event()
        self._sampler = threading.Thread(
            target=self._sample, name="demo-presence-probe", daemon=True
        )
        self._sampler.start()

    def sync(self, snapshot: object) -> object:
        phase = getattr(getattr(snapshot, "phase", None), "value", "?")
        authority = getattr(getattr(snapshot, "authority", None), "value", "?")
        self._projections.append({"phase": phase, "authority": authority})
        return self._window.sync(snapshot)  # type: ignore[arg-type]

    def close(self) -> None:
        self._stop.set()
        self._window.close()

    def _sample(self) -> None:
        user32 = ctypes.windll.user32
        while not self._stop.wait(0.25):
            hwnd = self._window.hwnd
            if hwnd is None or not user32.IsWindow(wintypes.HWND(hwnd)):
                self._missing += 1
                continue
            rect = wintypes.RECT()
            pending = bool(
                user32.GetUpdateRect(wintypes.HWND(hwnd), ctypes.byref(rect), False)
            )
            if pending:
                self._unpainted += 1
            else:
                self._painted += 1

    def report(self) -> dict[str, object]:
        self._stop.set()
        ordered: list[dict[str, str]] = []
        for entry in self._projections:
            if not ordered or ordered[-1] != entry:
                ordered.append(entry)
        return {
            "projection_count": len(self._projections),
            "projection_sequence": ordered,
            "distinct_states": sorted({
                f"{e['phase']}/{e['authority']}" for e in self._projections
            }),
            "samples_painted": self._painted,
            "samples_unpainted": self._unpainted,
            "samples_window_absent": self._missing,
        }


def _presence() -> tuple[RunPresenceCoordinator, _PresenceProbe]:
    """Give the halo a message pump, without which it paints nothing.

    A Win32 window that is never pumped never receives `WM_PAINT`. The halo was
    created, visible, and colour-key transparent, so it drew no border and no
    phase tab and no operator ever saw it during a complete Demo.
    """

    api = Win32PresenceWindowApi()
    probe = _PresenceProbe(PassivePresenceWindow(api))
    return (
        RunPresenceCoordinator(
            probe,  # type: ignore[arg-type]
            preferences=PresencePreferences(enabled=True),
            pump=api.pump,
        ),
        probe,
    )


def _progress() -> DemoWorkflowProgress:
    """Show the six Host-owned Demo chapters instead of run diagnostics.

    The generic ``state_dir`` poller renders tool-call budgets, which is exactly
    the mixed-total problem `GDA-HUD-005` records. This surface shows only the
    fixed workflow chapters; the approval `n/7` count stays on the Decision Card.
    """

    api = Win32ProgressWindowApi()
    return DemoWorkflowProgress(
        PassiveProgressWindow(api),
        pump=api.pump,
        interval_seconds=0.5,
    )


async def _run(
    *,
    interaction_speed: str = "deliberate",
    action_feedback: bool = True,
) -> dict[str, object]:
    document, profile, stamp = _fixtures()
    run_id = f"cross-app-demo-{stamp}"
    ownership: list[LaunchedFixture] = []
    cleanup: tuple[FixtureCleanup, ...] = ()
    result: dict[str, object] | None = None
    outcome = "failed"
    failure_class: str | None = None
    presence_coordinator, presence_probe = _presence()
    try:
        _launch_fixtures(
            SOURCE_URL,
            document,
            profile,
            ownership=ownership,
        )
        config = _config(
            stamp,
            interaction_speed=interaction_speed,
            action_feedback=action_feedback,
        )
        workflow = _progress()
        provider = CrossAppDemoProvider(
            chrome_title_fragment=SOURCE_TITLE,
            word_title_fragment=document.name,
            summary_text=SUMMARY,
            on_provider_step=workflow.on_provider_step,
        )
        step_context: list[OperatorStepContext | None] = [None]
        inner_cards = DecisionCardApprovalPort(
            DecisionCardWindow(
                Win32DecisionCardWindowApi(
                    corner=config.operator.decision_card_corner,
                ),
                step_context=lambda: step_context[0],
            ),
            timeout_seconds=config.operator.decision_timeout_seconds,
        )
        approvals = DemoDecisionCards(
            inner_cards,
            step_context=step_context,
            workflow=workflow,
        )
        desktop = StdioDesktopMCP(config.mcp)
        runner_outcome = await AgentRunner(
            config,
            RunnerPorts(
                provider=provider,
                desktop=desktop,
                approvals=approvals,
                presence=presence_coordinator,
                progress=workflow,
            ),
        ).run(
            "Review the public Microsoft Support page in Chrome, update the "
            "disposable Word research notes, and save only after exact local approvals.",
            run_id=run_id,
            allowed_tool_names=frozenset(
                {
                    "list_windows",
                    "document_text",
                    "ocr",
                    "activate_window",
                    "ui_snapshot",
                    "click",
                    "type",
                    "key",
                }
            ),
        )
        with zipfile.ZipFile(document) as package:
            document_xml = package.read("word/document.xml")
        body = "".join(ElementTree.fromstring(document_xml).itertext())
        if (
            runner_outcome.text != DEMO_COMPLETE_TEXT
            or DEMO_TYPED_MARKER not in body
        ):
            raise RuntimeError("DEMO_DURABLE_ARTIFACT_VERIFICATION_FAILED")
        outcome = "passed"
        result = {
            "document": str(document),
            "result": "PASS",
            "run_id": runner_outcome.state.run_id,
            "side_effects": runner_outcome.state.budgets.side_effects_used,
            "tool_calls": runner_outcome.state.budgets.tool_calls_used,
        }
    except BaseException as exc:
        failure_class = type(exc).__name__
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
            outcome = "cancelled"
        raise
    finally:
        cleanup = _cleanup_fixture_processes(ownership)
        _write_final_state(
            document.parent,
            run_id=run_id,
            document_name=document.name,
            profile_name=profile.name,
            outcome=outcome,
            failure_class=failure_class,
            cleanup=cleanup,
            presence=presence_probe.report(),
        )
    if result is None:
        raise RuntimeError("DEMO_RESULT_UNAVAILABLE")
    result["fixture_cleanup"] = [asdict(item) for item in cleanup]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded Chrome-to-Word desktop Demo."
    )
    parser.add_argument(
        "--interaction-speed",
        choices=("fast", "normal", "deliberate"),
        default="deliberate",
        help="Host-owned desktop presentation speed (default: deliberate).",
    )
    parser.add_argument(
        "--no-action-feedback",
        action="store_true",
        help="Disable the capture-excluded mouse and keyboard activity overlay.",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(
            _run(
                interaction_speed=args.interaction_speed,
                action_feedback=not args.no_action_feedback,
            )
        )
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
