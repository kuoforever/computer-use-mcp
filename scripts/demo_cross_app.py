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
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
import zipfile
from ctypes import wintypes
from xml.etree import ElementTree
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from computer_use_agent.approvals import (  # noqa: E402
    DecisionCardApprovalPort,
    DecisionCardChoicePort,
)
from computer_use_agent.config import (  # noqa: E402
    AGENTIC_ACTIONS_MODE,
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
from computer_use_agent.decision_cards import (  # noqa: E402
    ApplicationClass,
    DecisionCardRequest,
    DecisionClass,
    DecisionOptionKind,
    EvidenceKind,
    EvidenceReference,
    IntendedEffect,
    RecipientScope,
    SelectionStatus,
    UnknownFact,
    compile_decision_card,
    validate_decision_selection,
)
from computer_use_agent.demo_cross_app import (  # noqa: E402
    CrossAppDemoError,
    DEMO_COMPLETE_TEXT,
    DEMO_TYPED_MARKER,
    CrossAppDemoProvider,
    DemoProposalRejection,
    ModelDrivenCrossAppDemoProvider,
    ModelDrivenDemoError,
)
from computer_use_agent.demo_workflow_progress import (  # noqa: E402
    DemoWorkflowProgress,
)
from computer_use_agent.desktop_mcp import StdioDesktopMCP  # noqa: E402
from computer_use_agent.disposable_process import (  # noqa: E402
    DisposableCleanup as FixtureCleanup,
    DisposableProcess as LaunchedFixture,
    ProcessWindows,
    Win32ProcessWindows,
    cleanup_disposable_processes,
)
from computer_use_agent.presence import PresencePreferences  # noqa: E402
from computer_use_agent.presence_lifecycle import RunPresenceCoordinator  # noqa: E402
from computer_use_agent.presence_window import PassivePresenceWindow  # noqa: E402
from computer_use_agent.presence_window_win32 import Win32PresenceWindowApi  # noqa: E402
from computer_use_agent.provider_instructions import (  # noqa: E402
    ActionInstructionProfile,
)
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import Win32ProgressWindowApi  # noqa: E402
from computer_use_agent.runner import (  # noqa: E402
    AgentRunner,
    RunDeferred,
    RunFailure,
    RunnerPorts,
)
from computer_use_agent.trace import RunPhase  # noqa: E402
from computer_use_agent.types import (  # noqa: E402
    ApprovalRequest,
    ModelProviderPort,
    PolicyDecision,
    PolicyDecisionKind,
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
    f"\n\n{DEMO_TYPED_MARKER}\n"
    f"Source: {SOURCE_TITLE}\n"
    f"URL: {SOURCE_URL}\n"
    "- People working in the same document can see presence and live changes.\n"
    "- Older Word versions can co-edit but require periodic saves to exchange changes.\n"
)


class DemoDecisionCards:
    """Add trusted Demo context without duplicating dispatch readiness."""

    focus_taking = True

    def __init__(
        self,
        inner: DecisionCardApprovalPort,
        *,
        pause_surface: DecisionCardChoicePort | None = None,
        pause_timeout_seconds: int = 3_600,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        step_context: list[OperatorStepContext | None],
        workflow: DemoWorkflowProgress | None = None,
    ) -> None:
        if (
            isinstance(pause_timeout_seconds, bool)
            or not isinstance(pause_timeout_seconds, int)
            or not 5 <= pause_timeout_seconds <= 3_600
        ):
            raise ValueError("DEMO_PAUSE_TIMEOUT_INVALID")
        self._inner = inner
        self._pause_surface = pause_surface
        self._pause_timeout_seconds = pause_timeout_seconds
        self._clock = clock
        self._step_context = step_context
        self._workflow = workflow
        self._approval_index = 0
        self._defer_count = 0

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        pending_index = self._approval_index + 1
        if pending_index > 7:
            raise RuntimeError("DEMO_APPROVAL_STEP_OVERFLOW")
        label, application = self._label(request)
        # The workflow breadcrumb and the approval count answer different
        # questions and stay separate: "which chapter" versus "approval n/7".
        self._step_context[0] = OperatorStepContext(
            pending_index,
            7,
            label,
            application,
            workflow=None if self._workflow is None else self._workflow.breadcrumb(),
        )
        decision = await self._inner.request_approval(request)
        if decision.kind is PolicyDecisionKind.DEFER:
            decision = await self._pause(request)
        if decision.kind is PolicyDecisionKind.ALLOW:
            self._approval_index = pending_index
        return decision

    @staticmethod
    def _decision(
        request: ApprovalRequest,
        kind: PolicyDecisionKind,
        reason: str,
    ) -> PolicyDecision:
        return PolicyDecision(
            request.request_id,
            request.identity,
            request.call_digest,
            kind,
            reason,
        )

    async def _pause(self, request: ApprovalRequest) -> PolicyDecision:
        """Hold the exact action until Resume forces a fresh observation."""

        if self._pause_surface is None or request.binding is None:
            return self._decision(
                request,
                PolicyDecisionKind.DENY,
                "demo_pause_surface_unavailable",
            )
        original_context = self._step_context[0]
        while True:
            self._defer_count += 1
            now = self._clock()
            card = compile_decision_card(
                DecisionCardRequest(
                    decision_id=f"{request.request_id}.resume.{self._defer_count}",
                    binding=request.binding,
                    expires_at=now + timedelta(seconds=self._pause_timeout_seconds),
                    decision_class=DecisionClass.RECOVERY,
                    application=ApplicationClass.DESKTOP,
                    intended_effect=IntendedEffect.PRESERVE_FOR_HANDOFF,
                    recipient_scope=RecipientScope.NONE,
                    evidence=(
                        EvidenceReference(
                            EvidenceKind.OBSERVATION,
                            request.binding.evidence_digest,
                        ),
                    ),
                    unknown_facts=(UnknownFact.ACTIVE_TARGET,),
                    option_kinds=(
                        DecisionOptionKind.RESUME,
                        DecisionOptionKind.DEFER,
                        DecisionOptionKind.DENY,
                    ),
                    recommended=DecisionOptionKind.RESUME,
                ),
                now=now,
            )
            if original_context is not None:
                self._step_context[0] = OperatorStepContext(
                    original_context.current,
                    original_context.total,
                    "Paused — resume re-observes before any action",
                    original_context.application,
                    workflow=original_context.workflow,
                )
            try:
                selection = await self._pause_surface.choose(
                    card,
                    timeout_seconds=self._pause_timeout_seconds,
                )
                result = validate_decision_selection(
                    card,
                    selection,
                    current_binding=request.binding,
                    now=self._clock(),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                result = None
            if (
                result is not None
                and result.status is SelectionStatus.SELECTED
                and result.option_kind is DecisionOptionKind.RESUME
            ):
                self._step_context[0] = original_context
                return self._decision(
                    request,
                    PolicyDecisionKind.REOBSERVE,
                    "demo_resume_requires_reobservation",
                )
            if result is not None and result.status is SelectionStatus.DEFERRED:
                continue
            self._step_context[0] = original_context
            return self._decision(
                request,
                PolicyDecisionKind.DENY,
                "demo_pause_denied_or_expired",
            )

    def _label(self, request: ApprovalRequest) -> tuple[str, str]:
        """Describe the requested effect, not a presumed provider sequence."""

        application = "Desktop"
        if self._workflow is not None:
            checklist = self._workflow.checklist
            if checklist is not None and checklist.current_step_id is not None:
                current = next(
                    row
                    for row in checklist.steps
                    if row.step_id == checklist.current_step_id
                )
                application = current.application
        values = request.safe_argument_summary.values
        if request.tool_name == "activate_window":
            return (
                "Open the public source"
                if application == "Google Chrome"
                else "Switch to the research notes",
                application,
            )
        if request.tool_name == "click":
            return "Focus the document editor", "Microsoft Word"
        if request.tool_name == "type":
            return "Type the verified source summary", "Microsoft Word"
        if request.tool_name == "key":
            combo = values.get("combo")
            if combo == "PageDown":
                return "Scroll to the next article section", "Google Chrome"
            if combo == "Ctrl+End":
                return "Move to the follow-up section", "Microsoft Word"
            if combo == "Ctrl+S":
                return "Save and preserve the document", "Microsoft Word"
        return f"Approve {request.tool_name}", application


@dataclass(frozen=True)
class OperatorHandoffResolution:
    """Bounded post-dialog fact derived without operating the desktop."""

    detected: bool
    resolved: bool
    resolution: str
    fixture_pids: tuple[int, ...]

    def __post_init__(self) -> None:
        allowed = {"not_required", "saved", "discarded", "unresolved"}
        if (
            not isinstance(self.detected, bool)
            or not isinstance(self.resolved, bool)
            or self.resolution not in allowed
            or not isinstance(self.fixture_pids, tuple)
            or not all(isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 for pid in self.fixture_pids)
            or (not self.detected and self.resolution != "not_required")
            or (not self.detected and self.fixture_pids)
            or (self.resolved != (self.resolution in {"saved", "discarded"}))
        ):
            raise ValueError("operator handoff resolution is invalid")


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
            "on_exit": "close_exact_launched_process_windows",
            "owned_dialog": "operator_handoff",
            "scope": "exact_launched_processes_only",
            "stable_zero_observations": 3,
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
    windows: ProcessWindows | None = None,
    readiness_timeout_seconds: float = 12.0,
    readiness_poll_seconds: float = 0.25,
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
        observer = windows or Win32ProcessWindows()
        deadline = time.monotonic() + readiness_timeout_seconds
        while True:
            ready = all(
                observer.snapshot(item.process.pid).unowned_count >= 1
                for item in launched
            )
            if ready:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("DEMO_FIXTURE_WINDOWS_NOT_READY")
            time.sleep(readiness_poll_seconds)
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
    stable_zero_observations: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    timeout_error: type[Exception] = subprocess.TimeoutExpired,
    windows: ProcessWindows | None = None,
) -> tuple[FixtureCleanup, ...]:
    """Apply the shared exact-process, window-first cleanup contract."""

    return cleanup_disposable_processes(
        launched,
        windows=windows,
        wait_seconds=wait_seconds,
        poll_interval_seconds=poll_interval_seconds,
        stable_zero_observations=stable_zero_observations,
        sleep=sleep,
        timeout_error=timeout_error,
    )


def _document_text(document: Path) -> str:
    with zipfile.ZipFile(document) as package:
        document_xml = package.read("word/document.xml")
    return "".join(ElementTree.fromstring(document_xml).itertext())


def _document_contains_marker(document: Path) -> bool:
    return DEMO_TYPED_MARKER in _document_text(document)


def _document_contains_text(document: Path, expected: str) -> bool:
    return "".join(expected.split()) in "".join(_document_text(document).split())


def _await_operator_handoff_resolution(
    launched: Sequence[LaunchedFixture],
    cleanup: Sequence[FixtureCleanup],
    document: Path,
    *,
    wait_seconds: float = 300.0,
    poll_interval_seconds: float = 0.25,
    stable_zero_observations: int = 3,
    windows: ProcessWindows | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[tuple[FixtureCleanup, ...], OperatorHandoffResolution]:
    """Wait for an exact owned-dialog handoff, then classify save vs discard."""

    handoff_pids = tuple(
        item.pid for item in cleanup if item.disposition == "handoff_required"
    )
    if not handoff_pids:
        return tuple(cleanup), OperatorHandoffResolution(
            detected=False,
            resolved=False,
            resolution="not_required",
            fixture_pids=(),
        )
    if (
        not math.isfinite(wait_seconds)
        or wait_seconds <= 0
        or not math.isfinite(poll_interval_seconds)
        or poll_interval_seconds <= 0
        or isinstance(stable_zero_observations, bool)
        or not isinstance(stable_zero_observations, int)
        or stable_zero_observations < 2
    ):
        raise ValueError("operator handoff timing is invalid")
    fixtures = {item.process.pid: item for item in launched}
    if any(pid not in fixtures for pid in handoff_pids):
        raise ValueError("operator handoff fixture is unavailable")
    observer = windows or Win32ProcessWindows()
    max_observations = max(1, math.floor(wait_seconds / poll_interval_seconds) + 1)
    stable_zero_count = 0
    for observation_index in range(max_observations):
        try:
            visible = []
            for pid in handoff_pids:
                process = fixtures[pid].process
                visible.append(
                    0
                    if process.poll() is not None
                    else observer.snapshot(pid).visible_count
                )
        except Exception:
            visible = [1]
        if all(count == 0 for count in visible):
            stable_zero_count += 1
            if stable_zero_count >= stable_zero_observations:
                break
        else:
            stable_zero_count = 0
        if observation_index + 1 < max_observations:
            sleep(poll_interval_seconds)

    if stable_zero_count < stable_zero_observations:
        return tuple(cleanup), OperatorHandoffResolution(
            detected=True,
            resolved=False,
            resolution="unresolved",
            fixture_pids=handoff_pids,
        )
    try:
        resolution = "saved" if _document_contains_marker(document) else "discarded"
    except Exception:
        return tuple(cleanup), OperatorHandoffResolution(
            detected=True,
            resolved=False,
            resolution="unresolved",
            fixture_pids=handoff_pids,
        )

    resolved_cleanup: list[FixtureCleanup] = []
    for item in cleanup:
        if item.pid not in handoff_pids:
            resolved_cleanup.append(item)
            continue
        process = fixtures[item.pid].process
        try:
            exit_code = process.poll()
        except Exception:
            exit_code = None
        resolved_cleanup.append(
            replace(
                item,
                disposition=f"handoff_resolved_{resolution}",
                exit_code=exit_code,
                window_cleanup_verified=True,
                process_running=exit_code is None,
            )
        )
    return tuple(resolved_cleanup), OperatorHandoffResolution(
        detected=True,
        resolved=True,
        resolution=resolution,
        fixture_pids=handoff_pids,
    )


def _write_final_state(
    root: Path,
    *,
    run_id: str,
    document_name: str,
    profile_name: str,
    permission_mode: str,
    outcome: str,
    failure_class: str | None,
    failure_code: str | None = None,
    cleanup: Sequence[FixtureCleanup],
    presence: dict[str, object] | None = None,
    proposal_rejections: Sequence[DemoProposalRejection] = (),
    operator_handoff: OperatorHandoffResolution | None = None,
) -> None:
    window_cleanup_complete = all(item.window_cleanup_verified for item in cleanup)
    operator_handoff_required = any(
        item.disposition == "handoff_required" for item in cleanup
    )
    resolved_handoff = operator_handoff or OperatorHandoffResolution(
        detected=operator_handoff_required,
        resolved=False,
        resolution="unresolved" if operator_handoff_required else "not_required",
        fixture_pids=tuple(
            item.pid for item in cleanup if item.disposition == "handoff_required"
        ),
    )
    state = {
        "schema_version": 3,
        "run_id": run_id,
        "permission_mode": permission_mode,
        "outcome": outcome,
        "failure_class": failure_class,
        "window_cleanup_complete": window_cleanup_complete,
        "all_processes_exited": all(not item.process_running for item in cleanup),
        "operator_handoff_required": operator_handoff_required,
        "operator_handoff": asdict(resolved_handoff),
        "cleanup_scope": "exact_launched_processes_only",
        "fixture_identity": {
            "browser_profile": profile_name,
            "document": document_name,
        },
        "fixtures": [asdict(item) for item in cleanup],
        "proposal_rejections": [asdict(item) for item in proposal_rejections],
    }
    if presence is not None:
        state["presence"] = presence
    if failure_code is not None:
        state["failure_code"] = failure_code
    (root / "final-state.json").write_text(
        json.dumps(state, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )


def _config(
    stamp: str,
    *,
    provider_name: str = "openai",
    provider_model: str = "controlled-demo-provider",
    model_driven: bool = False,
    permission_mode: str = AGENTIC_ACTIONS_MODE,
    interaction_speed: str = "deliberate",
    action_feedback: bool = True,
) -> AgentConfig:
    if permission_mode not in {AGENTIC_ACTIONS_MODE, APPROVED_ACTIONS_MODE}:
        raise ValueError("DEMO_PERMISSION_MODE_NOT_REVIEWED")
    state_dir = default_state_dir() / f"demo-cross-app-{stamp}"
    return AgentConfig(
        state_dir=state_dir,
        policy_version="cross-app-demo-v1",
        provider=ProviderConfig(
            provider_name,
            provider_model,
            request_timeout_seconds=90,
        ),
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
            mode=permission_mode,
            require_approval_for_actions=(
                permission_mode == APPROVED_ACTIONS_MODE
            ),
            max_model_turns=28 if model_driven else 20,
            max_tool_calls=24 if model_driven else 17,
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


def _start_presence_while_preparing(coordinator: object) -> None:
    """Light the passive halo before fixture applications begin launching."""

    try:
        coordinator.on_phase(RunPhase.PLANNING)  # type: ignore[attr-defined]
    except Exception:
        # Presence is display-only and must never decide whether setup runs.
        pass


def _release_presence(coordinator: object) -> None:
    """Close an early-started halo even when setup fails before Runner exists."""

    try:
        coordinator.release()  # type: ignore[attr-defined]
    except Exception:
        pass


def _live_provider(
    provider_name: str,
    model: str,
    *,
    chrome_title_fragment: str,
    word_title_fragment: str,
    source_url: str,
    on_provider_step: Callable[[int], None],
    on_proposal_rejected: Callable[[DemoProposalRejection], None],
) -> ModelProviderPort:
    """Compose one reviewed SDK adapter behind the Demo-specific guard."""

    if provider_name == "openai":
        from computer_use_agent.providers.openai import OpenAIResponsesProvider

        inner: ModelProviderPort = OpenAIResponsesProvider.from_environment(
            model,
            allow_actions=True,
            action_instruction_profile=ActionInstructionProfile.CROSS_APP_DEMO,
        )
    elif provider_name == "anthropic":
        from computer_use_agent.providers.anthropic import AnthropicMessagesProvider

        inner = AnthropicMessagesProvider.from_environment(
            model,
            allow_actions=True,
            action_instruction_profile=ActionInstructionProfile.CROSS_APP_DEMO,
        )
    else:
        raise ValueError("DEMO_PROVIDER_NOT_REVIEWED")
    return ModelDrivenCrossAppDemoProvider(
        inner=inner,
        chrome_title_fragment=chrome_title_fragment,
        word_title_fragment=word_title_fragment,
        source_url=source_url,
        on_provider_step=on_provider_step,
        on_proposal_rejected=on_proposal_rejected,
    )


async def _run(
    *,
    mode: str = "controlled",
    provider_name: str = "openai",
    provider_model: str | None = None,
    permission_mode: str = AGENTIC_ACTIONS_MODE,
    interaction_speed: str = "deliberate",
    action_feedback: bool = True,
    handoff_wait_seconds: float = 300.0,
) -> dict[str, object]:
    if mode not in {"model", "controlled"}:
        raise ValueError("DEMO_MODE_NOT_REVIEWED")
    if mode == "model" and (
        not isinstance(provider_model, str) or not provider_model.strip()
    ):
        raise ValueError("DEMO_MODEL_REQUIRED")
    document, profile, stamp = _fixtures()
    run_id = f"cross-app-demo-{stamp}"
    ownership: list[LaunchedFixture] = []
    cleanup: tuple[FixtureCleanup, ...] = ()
    result: dict[str, object] | None = None
    outcome = "failed"
    failure_class: str | None = None
    failure_code: str | None = None
    proposal_rejections: list[DemoProposalRejection] = []
    operator_handoff = OperatorHandoffResolution(
        False, False, "not_required", ()
    )
    presence_coordinator, presence_probe = _presence()
    _start_presence_while_preparing(presence_coordinator)
    try:
        _launch_fixtures(
            SOURCE_URL,
            document,
            profile,
            ownership=ownership,
        )
        config = _config(
            stamp,
            provider_name=provider_name if mode == "model" else "openai",
            provider_model=(
                provider_model if mode == "model" else "controlled-demo-provider"
            ),
            model_driven=mode == "model",
            permission_mode=permission_mode,
            interaction_speed=interaction_speed,
            action_feedback=action_feedback,
        )
        workflow = _progress()

        def on_proposal_rejected(rejection: DemoProposalRejection) -> None:
            proposal_rejections.append(rejection)
            workflow.on_proposal_rejected(
                rejection.attempt, rejection.max_attempts
            )

        provider: ModelProviderPort = (
            _live_provider(
                provider_name,
                provider_model or "",
                chrome_title_fragment=SOURCE_TITLE,
                word_title_fragment=document.name,
                source_url=SOURCE_URL,
                on_provider_step=workflow.on_provider_step,
                on_proposal_rejected=on_proposal_rejected,
            )
            if mode == "model"
            else CrossAppDemoProvider(
                chrome_title_fragment=SOURCE_TITLE,
                word_title_fragment=document.name,
                summary_text=SUMMARY,
                on_provider_step=workflow.on_provider_step,
            )
        )
        step_context: list[OperatorStepContext | None] = [None]
        card_surface = DecisionCardWindow(
            Win32DecisionCardWindowApi(
                corner=config.operator.decision_card_corner,
            ),
            step_context=lambda: step_context[0],
        )
        inner_cards = DecisionCardApprovalPort(
            card_surface,
            timeout_seconds=config.operator.decision_timeout_seconds,
        )
        approvals = DemoDecisionCards(
            inner_cards,
            pause_surface=card_surface,
            step_context=step_context,
            workflow=workflow,
        )
        desktop = StdioDesktopMCP(config.mcp)
        task = (
            "Complete this bounded disposable demonstration using fresh desktop "
            "evidence. Use only the dedicated Chrome window whose title contains "
            f"{SOURCE_TITLE!r} and the disposable Word document whose title contains "
            f"{document.name!r}. Review the public source and write a grounded brief "
            "at the end of the Word document. The brief must be 220-900 characters, "
            "contain two to four source-grounded bullets, and use this exact layout:\n\n"
            f"{DEMO_TYPED_MARKER}\n"
            f"Source: {SOURCE_TITLE}\n"
            f"URL: {SOURCE_URL}\n"
            "- <grounded finding>\n"
            "- <grounded finding>\n\n"
            "Begin the typed text with two newlines. Save it and verify the complete "
            "brief after saving."
            if mode == "model"
            else "Review the public Microsoft Support page in Chrome, update the "
            "disposable Word research notes, and save through the configured "
            "project permission policy."
        )
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
            task,
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
        expected_note = (
            provider.accepted_note(run_id)
            if isinstance(provider, ModelDrivenCrossAppDemoProvider)
            else SUMMARY
        )
        if (
            runner_outcome.text != DEMO_COMPLETE_TEXT
            or expected_note is None
            or not _document_contains_text(document, expected_note)
        ):
            raise RuntimeError("DEMO_DURABLE_ARTIFACT_VERIFICATION_FAILED")
        outcome = "passed"
        result = {
            "document": str(document),
            "mode": mode,
            "provider": (
                provider_name if mode == "model" else "controlled"
            ),
            "provider_model": provider_model if mode == "model" else None,
            "permission_mode": permission_mode,
            "result": "PASS",
            "run_id": runner_outcome.state.run_id,
            "side_effects": runner_outcome.state.budgets.side_effects_used,
            "tool_calls": runner_outcome.state.budgets.tool_calls_used,
        }
    except BaseException as exc:
        failure_class = type(exc).__name__
        if isinstance(exc, (CrossAppDemoError, ModelDrivenDemoError)):
            failure_code = str(exc)
        elif isinstance(exc, (RunFailure, RunDeferred)):
            failure_code = exc.code
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
            outcome = "cancelled"
        raise
    finally:
        cleanup = _cleanup_fixture_processes(ownership)
        _release_presence(presence_coordinator)
        if any(item.disposition == "handoff_required" for item in cleanup):
            print(
                "OPERATOR_HANDOFF_REQUIRED: resolve the owned application dialog; "
                "the Demo will record save or discard without operating it.",
                flush=True,
            )
        cleanup, operator_handoff = _await_operator_handoff_resolution(
            ownership,
            cleanup,
            document,
            wait_seconds=handoff_wait_seconds,
        )
        _write_final_state(
            document.parent,
            run_id=run_id,
            document_name=document.name,
            profile_name=profile.name,
            permission_mode=permission_mode,
            outcome=outcome,
            failure_class=failure_class,
            failure_code=failure_code,
            cleanup=cleanup,
            presence=presence_probe.report(),
            proposal_rejections=proposal_rejections,
            operator_handoff=operator_handoff,
        )
    if result is None:
        raise RuntimeError("DEMO_RESULT_UNAVAILABLE")
    result["fixture_cleanup"] = [asdict(item) for item in cleanup]
    result["proposal_rejections"] = [
        asdict(item) for item in proposal_rejections
    ]
    result["operator_handoff"] = asdict(operator_handoff)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded Chrome-to-Word desktop Demo."
    )
    parser.add_argument(
        "--mode",
        choices=("model", "controlled"),
        default="model",
        help=(
            "Use a real model to choose steps (default), or the deterministic "
            "provider retained for regression."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=("openai", "anthropic"),
        default="openai",
        help="Live provider used in model mode (default: openai).",
    )
    parser.add_argument(
        "--model",
        help="Explicit provider model ID; required in model mode.",
    )
    parser.add_argument(
        "--permission-mode",
        choices=(AGENTIC_ACTIONS_MODE, APPROVED_ACTIONS_MODE),
        default=AGENTIC_ACTIONS_MODE,
        help=(
            "Use autonomous reviewed actions with human fallback (default), "
            "or require a Decision Card for every side effect."
        ),
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
    parser.add_argument(
        "--handoff-wait-seconds",
        type=float,
        default=300.0,
        help=(
            "How long to wait for an owned application dialog to be resolved "
            "by the operator (default: 300)."
        ),
    )
    args = parser.parse_args()
    if args.mode == "model" and not args.model:
        parser.error("--model is required when --mode=model")
    try:
        result = asyncio.run(
            _run(
                mode=args.mode,
                provider_name=args.provider,
                provider_model=args.model,
                permission_mode=args.permission_mode,
                interaction_speed=args.interaction_speed,
                action_feedback=not args.no_action_feedback,
                handoff_wait_seconds=args.handoff_wait_seconds,
            )
        )
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
